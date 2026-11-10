"""Run using the same PyQGIS environment as probe.py."""
from probe import *

def one(layer, extent, opts=None, rotation=0):
    canvas.setRotation(rotation)
    canvas.setExtent(extent)
    canvas.setLayers([layer])
    snap=capture(canvas,{layer.id():opts or {}})
    task=ExportTask(snap,root,lambda *_:None)
    assert task.run(),task.error
    return task.audit['layers'][0],task.result_path

def load(path):
    import vtk
    r=vtk.vtkXMLMultiBlockDataReader()
    r.SetFileName(str(path)); r.Update()
    return r.GetOutput().GetBlock(0)

if __name__=='__main__':
    from qgis.PyQt.QtCore import QDateTime, Qt
    QgsApplication.setPrefixPath('/usr',True)
    app=QgsApplication([],True); app.initQgis()
    root=Path(tempfile.mkdtemp())
    canvas=QgsMapCanvas()
    canvas.resize(640,480); canvas.show(); app.processEvents()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
    area=QgsRectangle(-1,-1,1,1)
    attrs=['A',112,4]
    layer=vector('Cross date line','Point',[(f'POINT({x} 0)',attrs) for x in (179.9,-179.9,0)])
    a,p=one(layer,QgsRectangle(179.6,-.3,180.4,.3))
    assert a['cells']==2 and len(a['windows'])==2 and max(w[2]-w[0] for w in a['windows'])<2,a
    layer=vector('Filters','Point',[(f'POINT({x} 0)',[k,112,x]) for x,k in [(.2,'A'),(.4,'A'),(.6,'B')]])
    layer.setSubsetString('"depth" < 0.5')
    layer.selectByIds([1])
    a,p=one(layer,area)
    assert a['cells']==2
    renderer=QgsRuleBasedRenderer(QgsMarkerSymbol.createSimple({}))
    rule=renderer.rootRule().children()[0]
    rule.setFilterExpression('"depth" > 0.3')
    layer.setRenderer(renderer)
    a,p=one(layer,area)
    assert a['cells']==1 and load(p).GetCellData().GetArray('source_fid').GetValue(0)==2
    # Two records at different times; the canvas is inside the second record's day.
    timed=QgsVectorLayer('Point?crs=epsg:4326&index=yes&field=observed:datetime','Time','memory')
    def dt(s): return QDateTime.fromString(s,Qt.ISODate)
    for day in ('2025-01-01','2025-02-01'):
        f=QgsFeature(timed.fields());f.setGeometry(QgsGeometry.fromWkt('POINT(0 0)'))
        f.setAttributes([dt(day+'T12:00:00Z')]);timed.dataProvider().addFeatures([f])
    timed.updateExtents()
    temp=timed.temporalProperties()
    temp.setIsActive(True);temp.setMode(temp.ModeFeatureDateTimeInstantFromField);temp.setStartField('observed')
    canvas.setTemporalRange(QgsDateTimeRange(dt('2025-02-01T00:00:00Z'),dt('2025-02-02T00:00:00Z')))
    a,p=one(timed,area)
    assert a['cells']==1 and load(p).GetCellData().GetArray('source_fid').GetValue(0)==2
    line=vector('Rotated clip','LineStringZ',[('LINESTRING Z(-4 0 10,4 0 50)',attrs)])
    a,p=one(line,area,rotation=32)
    block=load(p); frame=capture(canvas,{})[0]
    back=QgsCoordinateTransform(frame.scene,frame.crs,frame.context)
    for i in range(2):
        x,y,z=block.GetPoint(i)
        mapped=back.transform(QgsPointXY(x+frame.origin.x(),y+frame.origin.y()))
        # Distance to an edge of the exact rotated rectangle.
        assert frame.footprint.constGet().exteriorRing().asWkt()
        edges=QgsGeometry.fromPolylineXY(frame.corners+frame.corners[:1])
        assert edges.distance(QgsGeometry.fromPointXY(mapped))<1e-7
        assert abs(z-(30+5*mapped.x()))<1e-6
    interval=vector('Intervals','Point',[('POINT(0 0)',['clay',112,4])])
    opts=dict(mode='interval',elevation='collar',top='depth',base='collar',attributes=['label'])
    a,p=one(interval,area,opts)
    b=load(p)
    assert [b.GetPoint(i)[2] for i in range(2)]==[108,0]
    assert b.GetCellData().GetAbstractArray('field.label').GetValue(0)=='clay'
    print('PASS split date line, subset, selection, rule, temporal filter, rotated edges, clipped Z, interval',flush=True)
    os._exit(0)
