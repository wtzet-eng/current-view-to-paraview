import numpy as np
from osgeo import osr
from qgis.core import (QgsCoordinateReferenceSystem as CRS, QgsCoordinateTransform,
                       QgsGeometry, QgsRectangle, QgsUnitTypes)


def transform_xy(src, dst, x, y):
    if src == dst:
        return np.asarray(x), np.asarray(y)
    refs = []
    for crs in (src, dst):
        ref = osr.SpatialReference()
        ref.ImportFromWkt(crs.toWkt())
        ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        refs.append(ref)
    converted = np.asarray(osr.CoordinateTransformation(*refs).TransformPoints(np.column_stack((x, y))))
    if not np.isfinite(converted[:, :2]).all():
        raise ValueError('The view extends outside the coordinate transformation domain.')
    return converted[:, 0], converted[:, 1]


class LocalGridRequired(ValueError):
    """A geographic canvas contains coordinate values incompatible with latitude."""


class Frame:
    def __init__(self, settings, allow_local_metres=False):
        self.crs = settings.destinationCrs()
        self.context = settings.transformContext()
        self.width = settings.outputSize().width()
        self.height = settings.outputSize().height()
        mapping = settings.mapToPixel()
        pixels = [(0, 0), (self.width, 0), (self.width, self.height), (0, self.height)]
        self.corners = [mapping.toMapCoordinates(x, y) for x, y in pixels]
        self.footprint = QgsGeometry.fromPolygonXY([self.corners + self.corners[:1]])
        self.scene = self.crs
        center = self.footprint.centroid().asPoint()
        self.local_grid = self.crs.isGeographic() and abs(center.y()) > 90
        if self.local_grid:
            if not allow_local_metres:
                raise LocalGridRequired(
                    f'The canvas uses {self.crs.description()}, but its centre is '
                    f'X {center.x():,.2f}, Y {center.y():,.2f}. This Y is outside the latitude range.'
                )
            self.origin = center
            return
        if self.crs.mapUnits() != QgsUnitTypes.DistanceMeters or self.crs.isGeographic() or self.crs.authid()=='EPSG:3857':
            geo = QgsCoordinateTransform(self.crs, CRS('EPSG:4326'), self.context).transform(center)
            self.scene = CRS()
            if not self.scene.createFromProj(f'+proj=aeqd +lat_0={geo.y():.12f} +lon_0={(geo.x()+180)%360-180:.12f} +datum=WGS84 +units=m +type=crs'):
                raise ValueError('Could not create a local metric scene CRS.')
        self.origin = QgsCoordinateTransform(self.crs, self.scene, self.context).transform(center)

    def windows(self, dest):
        rect = self.footprint.boundingBox()
        if self.local_grid:
            return [rect]
        tx = QgsCoordinateTransform(self.crs, dest, self.context)
        if self.crs != dest:
            rect = tx.transformBoundingBox(rect, handle180Crossover=dest.isGeographic())
        if not dest.isGeographic():
            return [rect]
        x, end = rect.xMinimum(), rect.xMaximum()
        if end < x:
            end += 360
        if end - x >= 360:
            return [QgsRectangle(-180, rect.yMinimum(), 180, rect.yMaximum())]
        left = (x + 180) % 360 - 180
        right = left + end - x
        pieces = [(left, min(180, right))]
        if right > 180:
            pieces.append((-180, right - 360))
        return [QgsRectangle(a, rect.yMinimum(), b, rect.yMaximum()) for a, b in pieces]
