import math
import os
from qgis.PyQt.QtCore import QUrl
from qgis.core import (NULL, QgsCoordinateTransform, QgsExpression, QgsExpressionContextUtils,
                       QgsFeatureRequest, QgsGeometry, QgsRenderContext, QgsVectorLayerFeatureSource,
                       QgsVectorLayerTemporalContext, QgsWkbTypes, QgsPointXY)
from .vtkio import poly

VERTEX_LIMIT = 150000
FEATURE_LIMIT = 20000


def capture_vector(layer, settings, opts):
    provider = layer.dataProvider()
    kind = layer.providerType()
    if kind == 'delimitedtext':
        path = QUrl(layer.source()).toLocalFile()
        if not path or not os.path.isfile(path):
            raise ValueError('Delimited text requires a local file.')
        if provider.hasSpatialIndex() != provider.SpatialIndexPresent:
            if os.path.getsize(path) > 1024**2 or not provider.createSpatialIndex():
                raise ValueError('Enable a spatial index in the delimited-text layer settings.')
    elif kind not in ('ogr','memory'):
        raise ValueError('This vector provider does not support audited spatial queries.')
    if provider.hasSpatialIndex() != provider.SpatialIndexPresent:
        raise ValueError('Spatial index required. For a local shapefile, run QGIS Processing → Create spatial index.')
    if layer.providerType() == 'ogr':
        from qgis.core import QgsProviderRegistry
        uri = QgsProviderRegistry.instance().decodeUri('ogr',layer.source())
        path = uri.get('path','')
        if not os.path.isfile(path) or layer.storageType() not in ('GPKG', 'ESRI Shapefile'):
            raise ValueError('Use an indexed local GeoPackage, shapefile, or memory layer.')
    if layer.vectorJoins() or any(layer.fields().fieldOrigin(i) == layer.fields().OriginExpression for i in range(len(layer.fields()))):
        raise ValueError('Joined and virtual fields require project access during export.')
    if layer.isEditable():
        raise ValueError('Finish the edit session before exporting this layer.')
    ctx = QgsRenderContext.fromMapSettings(settings)
    ctx.expressionContext().appendScope(QgsExpressionContextUtils.layerScope(layer))
    manager = layer.styleManager()
    override = settings.layerStyleOverrides().get(layer.id())
    if override and not manager.setOverrideStyle(override):
        raise ValueError('The canvas style override could not be resolved.')
    try:
        renderer = layer.renderer().clone()
        if renderer.type() not in ('singleSymbol','categorizedSymbol','graduatedSymbol','RuleRenderer'):
            raise ValueError('This renderer changes feature representation and is unsupported.')
        if hasattr(renderer,'dataDefinedProperties') and renderer.dataDefinedProperties().hasActiveProperties():
            raise ValueError('Data-defined renderer properties are unsupported.')
        expressions = []
        if renderer.type() in ('categorizedSymbol','graduatedSymbol'):
            expr = renderer.classAttribute()
            if layer.fields().indexFromName(expr) < 0:
                expressions.append(expr)
        if renderer.type() == 'RuleRenderer':
            rules = [renderer.rootRule()]
            while rules:
                rule = rules.pop()
                rules.extend(rule.children())
                if rule.filterExpression() and not rule.isElse():
                    expressions.append(rule.filterExpression())
        for expression in expressions:
            expr = QgsExpression(expression)
            if expr.hasParserError() or expr.referencedFunctions() or '@' in expression or '$' in expression:
                raise ValueError('The visibility expression needs context outside simple field comparisons.')
        for symbol in renderer.symbols(ctx):
            if symbol.hasDataDefinedProperties():
                raise ValueError('Data-defined symbol visibility is unsupported.')
            for sl in symbol.symbolLayers():
                if sl.layerType() in ('GeometryGenerator','MaskMarker') or sl.dataDefinedProperties().hasActiveProperties():
                    raise ValueError('Generated geometry or data-defined symbol layers are unsupported.')
        if layer.opacity() <= 0:
            raise ValueError('Layer is fully transparent.')
    finally:
        if override:
            manager.restoreOverrideStyle()
    temporal = layer.temporalProperties()
    predicate = ''
    if settings.isTemporal() and temporal.isActive():
        tc = QgsVectorLayerTemporalContext()
        tc.setLayer(layer)
        predicate = temporal.createFilterString(tc, settings.temporalRange())
        if temporal.mode() == temporal.ModeFeatureDateTimeStartAndEndFromExpressions:
            raise ValueError('Expression-based temporal intervals are unsupported.')
    geometry_type = layer.geometryType()
    if geometry_type not in (0,1,2):
        raise ValueError('Unsupported geometry family.')
    return dict(source=QgsVectorLayerFeatureSource(layer),fields=layer.fields(),crs=layer.crs(),
                renderer=renderer,context=ctx,predicate=predicate,opts=opts,kind=geometry_type)


def number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return math.nan


def vector_file(path, spec, frame, terrain, check):
    opts, fields = spec['opts'],spec['fields']
    renderer,ctx = spec['renderer'],spec['context']
    to_map = QgsCoordinateTransform(spec['crs'],frame.crs,frame.context)
    to_scene = QgsCoordinateTransform(frame.crs,frame.scene,frame.context)
    seen = set()
    points,links,ends,records = [],[],[],[]
    kind = spec['kind']
    family = ('Verts','Lines','Polys')[kind]
    mode = opts.get('mode','flat')
    if mode in ('water','interval') and kind != 0:
        raise ValueError('Vertical borehole mappings require point locations.')
    if mode == 'interval':
        family = 'Lines'
    selected = opts.get('attributes',[])
    names = set(fields.names())
    required = [opts[key] for key in ('elevation','depth','top','base') if opts.get(key)]
    if set(selected+required)-names:
        raise ValueError('A configured attribute is missing. Review layer settings.')
    stats = dict(candidates=0,missing_elevation=0,cells=0,windows=[],height_mode=mode,
                 vertical_factor=opts.get('factor',1),attributes=selected)
    cost = 0
    input_vertices = 0
    def cell(vertices, record):
        nonlocal cost
        if len(points)+len(vertices)>VERTEX_LIMIT:
            raise ValueError('Output vertex limit exceeded. Zoom in or omit this layer.')
        cost += len(vertices)*200 + 64 + record[-1]
        if cost > 48*1024**2:
            raise ValueError('Vector geometry and attribute budget exceeded. Zoom in or select fewer fields.')
        start = len(points)
        points.extend(vertices)
        links.extend(range(start,len(points)))
        ends.append(len(links))
        records.append(record)

    renderer.startRender(ctx,fields)
    try:
        for rect in frame.windows(spec['crs']):
            stats['windows'].append([rect.xMinimum(),rect.yMinimum(),rect.xMaximum(),rect.yMaximum()])
            req = QgsFeatureRequest().setFilterRect(rect)
            if spec['predicate']:
                req.setFilterExpression(spec['predicate'])
            req.setExpressionContext(ctx.expressionContext())
            iterator = spec['source'].getFeatures(req)
            for f in iterator:
                check()
                if f.id() in seen:
                    continue
                seen.add(f.id())
                if len(seen)>FEATURE_LIMIT:
                    raise ValueError('Candidate feature limit exceeded. Zoom in or omit this layer.')
                stats['candidates'] += 1
                ctx.expressionContext().setFeature(f)
                if not renderer.willRenderFeature(f,ctx):
                    continue
                symbols = renderer.symbolsForFeature(f,ctx)
                if not any(s.opacity()>0 and any(sl.enabled() for sl in s.symbolLayers()) for s in symbols if s):
                    continue
                geom = f.geometry()
                if geom.isEmpty():
                    continue
                n = geom.constGet().nCoordinates()
                input_vertices += n
                if n>30000 or input_vertices>350000 or f.approximateMemoryUsage()>8*1024**2:
                    raise ValueError('Source geometry exceeds the per-feature or cumulative budget. Subdivide or zoom in.')
                if QgsWkbTypes.isCurvedType(geom.wkbType()):
                    raise ValueError('Curved geometry requires segmentisation before export.')
                geom.transform(to_map)
                if not frame.local_grid and frame.crs.isGeographic():
                    center = frame.footprint.boundingBox().center().x()
                    bbox = geom.boundingBox()
                    shift = 360*round((center-bbox.center().x())/360)
                    if bbox.width()<180 and shift:
                        geom.translate(shift,0)
                    elif 180<bbox.width()<359.999 and abs((center+180)%360-180)>90:
                        # Move opposite-side vertices into the same longitude interval.
                        for index,p in enumerate(list(geom.vertices())):
                            offset=360*round((center-p.x())/360)
                            if offset:
                                p.setX(p.x()+offset)
                                geom.moveVertex(p,index)
                if not frame.footprint.contains(geom):
                    geom = geom.intersection(frame.footprint)
                    if geom.lastError():
                        raise ValueError(geom.lastError())
                if geom.isEmpty():
                    continue
                geom.transform(to_scene)
                values = [f[name] for name in selected]
                record = (f.id(),values,sum(len(str(v).encode('utf-8'))+16 for v in values))
                scale = opts.get('factor',1.0)
                def height(p):
                    if mode in ('water','interval','field') and opts.get('elevation'):
                        return number(f[opts['elevation']])*scale
                    if mode in ('terrain','water','interval'):
                        return terrain.elevation(p.x(),p.y()) if terrain else math.nan
                    if math.isfinite(p.z()):
                        return p.z()*scale
                    return 0.0 if mode == 'flat' and not QgsWkbTypes.hasZ(f.geometry().wkbType()) else math.nan
                parts = geom.asGeometryCollection() if geom.isMultipart() else [geom]
                for part in parts:
                    check()
                    if part.type()!=kind:
                        continue
                    pieces = [part]
                    if kind==2:
                        triangles = part.constrainedDelaunayTriangulation()
                        if triangles.isEmpty():
                            raise ValueError('Polygon triangulation failed. Check the geometry and GEOS version.')
                        pieces = triangles.asGeometryCollection()
                    for piece in pieces:
                        verts = list(piece.vertices())
                        if kind==2:
                            verts = verts[:3]
                        coords = []
                        for p in verts:
                            x,y = p.x()-frame.origin.x(),p.y()-frame.origin.y()
                            z = height(p)
                            if mode=='water':
                                d = number(f[opts['depth']])*scale
                                z = z-d if d>=0 else math.nan
                            if mode=='interval':
                                top,base = (number(f[opts[k]])*scale for k in ('top','base'))
                                if 0<=top<base:
                                    coords.extend([(x,y,z-top),(x,y,z-base)])
                                else:
                                    coords.append((x,y,math.nan))
                            else:
                                coords.append((x,y,z))
                        if not all(math.isfinite(p[2]) for p in coords):
                            stats['missing_elevation'] += 1
                            continue
                        cell(coords,record)
    finally:
        renderer.stopRender(ctx)
    if not ends:
        raise ValueError(f'No exportable cells. Missing height or depth in {stats["missing_elevation"]} parts.')
    attrs = [('source_fid',[r[0] for r in records],'i8')]
    for idx,name in enumerate(selected):
        values = [r[1][idx] for r in records]
        if fields[name].isNumeric():
            missing = [v is None or v==NULL for v in values]
            if all(m or isinstance(v,int) for v,m in zip(values,missing)):
                attrs.append(('field.'+name,[0 if m else int(v) for v,m in zip(values,missing)],'i8'))
                if any(missing):
                    attrs.append(('valid.'+name,[int(not m) for m in missing],'u1'))
            else:
                attrs.append(('field.'+name,[number(v) for v in values],'f8'))
        else:
            attrs.append(('field.'+name,['' if v is None or v==NULL else str(v) for v in values],'string'))
            if any(v is None or v==NULL for v in values):
                attrs.append(('valid.'+name,[int(v is not None and v!=NULL) for v in values],'u1'))
    poly(path,points,family,links,ends,attrs)
    stats['cells'] = len(ends)
    return stats
