from collections import OrderedDict
import math
import os
import numpy as np
from osgeo import gdal
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY
from .spatial import transform_xy
from .vtkio import poly

CELL_LIMIT = 350000
READ_LIMIT = 64 * 1024 * 1024


class Terrain:
    def __init__(self, path, frame, band_number, factor, native, cap=CELL_LIMIT):
        self.frame = frame
        drivers = ['GTiff']
        # ASCII grids may scan preceding rows. Bound the entire physical file
        # before enabling that driver, even when its extension says .tif.
        if os.path.isfile(path) and os.path.getsize(path) <= 8 * 1024**2:
            drivers.append('AAIGrid')
        self.ds = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY, allowed_drivers=drivers)
        if not self.ds:
            raise ValueError('Use a local GeoTIFF or an Arc/Info ASCII grid up to 8 MiB.')
        if self.ds.GetDriver().ShortName == 'AAIGrid' and self.ds.RasterXSize*self.ds.RasterYSize > 2000000:
            raise ValueError('ASCII grid exceeds two million cells. Convert it to a tiled GeoTIFF.')
        self.base = self.ds.GetRasterBand(band_number)
        self.inv = gdal.InvGeoTransform(self.ds.GetGeoTransform())
        self.crs = QgsCoordinateReferenceSystem.fromWkt(self.ds.GetProjection())
        if frame.local_grid and self.crs != frame.crs:
            raise ValueError('Raster source has a different CRS label from the local grid.')
        if not self.inv or not self.crs.isValid():
            raise ValueError('Elevation grid needs a valid affine transform and horizontal CRS.')
        self.factor = factor
        self.a, self.b, _, self.d = np.array([[p.x(), p.y()] for p in frame.corners])
        self.dx, self.dy = self.b - self.a, self.d - self.a
        center = self.a + (self.dx + self.dy) / 2
        probes = np.array([center, center + self.dx / frame.width, center + self.dy / frame.height])
        px, py = self.pixel(probes[:, 0], probes[:, 1])
        # Unwrap a geographic seam before estimating pixel spacing.
        delta = np.column_stack((px[1:] - px[0], py[1:] - py[0]))
        if self.wrap:
            delta[:, 0] -= np.rint(delta[:, 0] / self.base.XSize) * self.base.XSize
        spacing = np.maximum(1.e-8, np.linalg.norm(delta, axis=1))
        dims = np.array([frame.width, frame.height], dtype=float)
        self.native_dims = np.maximum(2,np.ceil(dims * spacing) + 1)
        if native:
            dims = self.native_dims
            if np.prod(dims) > cap:
                raise ValueError(f'Native terrain needs {int(np.prod(dims)):,} samples (about {int(np.prod(dims)*64/1048576)} MiB before encoding). Zoom in or choose screen resolution.')
        else:
            dims = np.minimum(dims,self.native_dims)
        dims = np.maximum(2, np.floor(dims * min(1, math.sqrt(cap / np.prod(dims))))).astype(int)
        self.nx, self.ny = map(int, dims)
        if self.nx * self.ny > cap:
            raise ValueError('Canvas aspect exceeds the terrain sample budget.')
        target = min(spacing * [frame.width/self.nx, frame.height/self.ny])
        self.band = self.base
        for i in range(self.base.GetOverviewCount()):
            overview = self.base.GetOverview(i)
            if self.base.XSize / overview.XSize <= target:
                self.band = overview
        self.bx, self.by = self.band.GetBlockSize()
        self.masked = self.band.GetMaskFlags() != gdal.GMF_ALL_VALID
        unit_bytes = ((gdal.GetDataTypeSize(self.band.DataType)+7)//8) + int(self.masked)
        self.block_bytes = self.bx * self.by * unit_bytes
        if self.block_bytes > 4 * 1024**2:
            raise ValueError('Source storage blocks exceed 4 MiB. Use a tiled elevation GeoTIFF.')
        self.cache = OrderedDict()
        self.audit = dict(source=[self.base.XSize,self.base.YSize], overview=[self.band.XSize,self.band.YSize],
                          output=[self.nx,self.ny], block=[self.bx,self.by], reads=0, bytes_upper_bound=0, windows=[])
        self.grid = np.full((self.ny,self.nx), np.nan)
        self.to_map = QgsCoordinateTransform(frame.scene, frame.crs, frame.context)

    @property
    def wrap(self):
        gt = self.ds.GetGeoTransform()
        return not self.frame.local_grid and self.crs.isGeographic() and abs(abs(gt[1])*self.base.XSize - 360) < 1.e-5 and gt[2] == 0

    def pixel(self, x, y):
        x, y = transform_xy(self.frame.crs, self.crs, x, y)
        t = self.inv
        px = t[0] + x*t[1] + y*t[2]
        if self.wrap:
            px %= self.base.XSize
        return px, t[3] + x*t[4] + y*t[5]

    def read(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        x, y = key[0]*self.bx, key[1]*self.by
        w, h = min(self.bx,self.band.XSize-x), min(self.by,self.band.YSize-y)
        self.audit['bytes_upper_bound'] += self.block_bytes
        if self.audit['bytes_upper_bound'] > READ_LIMIT:
            raise ValueError('Terrain exceeds the 64 MiB block-read budget. Zoom in or build raster overviews.')
        data = self.band.ReadAsArray(x,y,w,h)
        if data is None:
            raise ValueError('A terrain block could not be read.')
        data = data.astype(float)
        nodata = self.band.GetNoDataValue()
        if nodata is not None:
            data[data == nodata] = np.nan
        if self.masked:
            data[self.band.GetMaskBand().ReadAsArray(x,y,w,h) == 0] = np.nan
        scale = self.base.GetScale()
        data = (data * (1 if scale is None else scale) + (self.base.GetOffset() or 0)) * self.factor
        self.audit['reads'] += 1
        if len(self.audit['windows']) < 16:
            self.audit['windows'].append([x,y,w,h])
        self.cache[key] = data
        while len(self.cache) > max(1,min(64, 8388608//(self.bx*self.by*8))):
            self.cache.popitem(last=False)
        return data

    def write(self, path, check):
        xyz = np.zeros((self.ny,self.nx,3))
        for row in range(0,self.ny,16):
            check()
            end = min(row+16,self.ny)
            u,v = np.meshgrid(np.linspace(0,1,self.nx),np.arange(row,end)/(self.ny-1))
            x = self.a[0]+self.dx[0]*u.ravel()+self.dy[0]*v.ravel()
            y = self.a[1]+self.dx[1]*u.ravel()+self.dy[1]*v.ravel()
            px,py = self.pixel(x,y)
            ix = np.floor(px*self.band.XSize/self.base.XSize).astype('i8')
            iy = np.floor(py*self.band.YSize/self.base.YSize).astype('i8')
            valid = (ix>=0)&(iy>=0)&(ix<self.band.XSize)&(iy<self.band.YSize)
            blocks = ix//self.bx + (iy//self.by)*math.ceil(self.band.XSize/self.bx)
            z = self.grid[row:end].reshape(-1)
            for block in np.unique(blocks[valid]):
                check()
                sel = valid & (blocks == block)
                k = np.flatnonzero(sel)[0]
                data = self.read((int(ix[k]//self.bx),int(iy[k]//self.by)))
                z[sel] = data[iy[sel]%self.by,ix[sel]%self.bx]
            sx,sy = transform_xy(self.frame.crs,self.frame.scene,x,y)
            pts = xyz[row:end].reshape(-1,3)
            pts[:,0],pts[:,1],pts[:,2] = sx-self.frame.origin.x(),sy-self.frame.origin.y(),z
        valid = np.isfinite(self.grid)
        rows,cols = np.nonzero(valid[:-1,:-1]&valid[1:,:-1]&valid[:-1,1:]&valid[1:,1:])
        if not len(rows):
            raise ValueError('No complete terrain cells within the view.')
        lower = rows*self.nx+cols
        cells = np.column_stack((lower,lower+self.nx,lower+self.nx+1,lower+1))
        used, remap = np.unique(cells,return_inverse=True)
        poly(path,xyz.reshape(-1,3)[used],'Polys',remap.ravel(),np.arange(1,len(cells)+1)*4)
        self.audit['cells'] = len(cells)
        self.audit['native_estimate'] = list(map(int,self.native_dims))
        self.cache.clear()

    def elevation(self,x,y):
        p = self.to_map.transform(QgsPointXY(x,y))
        mx = p.x()
        if not self.frame.local_grid and self.frame.crs.isGeographic():
            mx += 360*round((self.a[0]-mx)/360)
        u,v = np.linalg.solve(np.column_stack((self.dx,self.dy)),[mx-self.a[0],p.y()-self.a[1]])
        i,j = round(u*(self.nx-1)),round(v*(self.ny-1))
        return self.grid[j,i] if 0<=i<self.nx and 0<=j<self.ny else float('nan')
