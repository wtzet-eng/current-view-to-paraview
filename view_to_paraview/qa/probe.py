"""Run with distro QGIS Python. Uses a fresh temporary directory."""
import json
import os
from pathlib import Path
import tempfile
import time
import resource
import sys
from qgis.core import *
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import QVariant
from osgeo import gdal,osr
import numpy as np
from view_to_paraview.export import capture,ExportTask

def fixture(folder):
    path=str(folder/'global.tif')
    ds=gdal.GetDriverByName('GTiff').Create(path,36000,18000,1,gdal.GDT_Int16,
        options=['TILED=YES','BLOCKXSIZE=128','BLOCKYSIZE=128','SPARSE_OK=YES','COMPRESS=DEFLATE'])
    crs=osr.SpatialReference()
    crs.ImportFromEPSG(4326)
    ds.SetProjection(crs.ExportToWkt())
    ds.SetGeoTransform((-180,.01,0,90,0,-.01))
    band=ds.GetRasterBand(1)
    band.SetNoDataValue(-32768)
    patch=np.full((1024,1024),112,dtype='int16')
    patch[510:516,510:516]=-32768
    band.WriteArray(patch,17488,8488)
    band.SetStatistics(112,112,112,0)
    ds=None
    return QgsRasterLayer(path,'Global DEM')

def vector(name,kind,rows,crs='4326'):
    layer=QgsVectorLayer(kind+'?crs=epsg:'+crs+'&index=yes&field=label:string&field=collar:double&field=depth:double',name,'memory')
    provider=layer.dataProvider()
    for wkt,attrs in rows:
        f=QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromWkt(wkt))
        f.setAttributes(attrs)
        assert provider.addFeatures([f])[0]
    layer.updateExtents()
    return layer

def run_scene(canvas,opts,folder):
    snap=capture(canvas,opts)
    task=ExportTask(snap,folder,lambda *_:None)
    start=time.monotonic()
    if not task.run():
        raise AssertionError(task.error)
    print(json.dumps(dict(path=str(task.result_path),seconds=time.monotonic()-start,peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         skipped=task.audit['skipped'],metrics=[{k:v for k,v in m.items() if k in ('name','output','reads','bytes_upper_bound','cells','windows','candidates')} for m in task.audit['layers']])),flush=True)
    return task

def build(folder):
    dem=fixture(folder)
    a=['A',112,4]
    points=vector('Wells','Point',[('POINT(0.1 0.1)',a),('POINT(0.2 0.2)',['missing',None,4]),('POINT(2 2)',a)])
    river=vector('River','LineStringZ',[('LINESTRING Z(-1 0 10,1 0 30)',a)])
    shape=vector('Geology','Polygon',[('POLYGON((-20000 -20000,20000 -20000,20000 20000,-20000 20000,-20000 -20000),(-5000 -5000,-5000 5000,5000 5000,5000 -5000,-5000 -5000))',a)],'3857')
    opts={dem.id():{'dem':True},points.id():dict(mode='water',depth='depth',elevation='collar',attributes=['label','collar','depth'])}
    return [points,river,shape,dem],opts

if __name__=='__main__':
    QgsApplication.setPrefixPath('/usr',True)
    app=QgsApplication([],True)
    app.initQgis()
    folder=Path(os.environ.get('TEST_ROOT',tempfile.mkdtemp()))
    folder.mkdir(exist_ok=True)
    layers,opts=build(folder)
    canvas=QgsMapCanvas()
    canvas.resize(800,600)
    canvas.show()
    app.processEvents()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
    canvas.setLayers(layers)
    canvas.setRotation(24)
    canvas.setExtent(QgsRectangle(-.35,-.25,.35,.25))
    task=run_scene(canvas,opts,folder)
    assert len(task.audit['layers'])==4
    assert task.audit['layers'][1]['cells']==1
    canvas.setExtent(QgsRectangle(-7,-5.25,7,5.25))
    wide=run_scene(canvas,opts,folder)
    assert 345000 < np.prod(wide.audit['layers'][0]['output']) <= 350000
    print('PASS',flush=True)
    os._exit(0)
