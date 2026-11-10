"""Regression for metric survey coordinates labelled as geographic."""
from probe import *
from view_to_paraview.spatial import LocalGridRequired
from osgeo import ogr

def test():
    app=QgsApplication([],True)
    app.setPrefixPath('/usr',True)
    app.initQgis()
    root=Path(tempfile.mkdtemp())
    ds=ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(str(root/'survey.shp'))
    srs=osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    src=ds.CreateLayer('survey',srs,ogr.wkbLineString25D,options=['SPATIAL_INDEX=YES'])
    f=ogr.Feature(src.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt('LINESTRING Z (1400001 7008001 20,1400501 7008001 30)'))
    assert src.CreateFeature(f)==0
    f=src=ds=None
    layer=QgsVectorLayer(str(root/'survey.shp'),'survey','ogr')
    canvas=QgsMapCanvas()
    canvas.setDestinationCrs(layer.crs())
    canvas.setExtent(QgsRectangle(1399900,7007900,1400600,7008100))
    canvas.setLayers([layer])
    try:
        capture(canvas,{})
    except LocalGridRequired:
        pass
    else:
        raise AssertionError('Local metres must be explicitly confirmed')
    frame,entries,audit=capture(canvas,{},True)
    assert audit['scene_crs'] is None and audit['coordinate_mode']=='user_confirmed_local_metres'
    t=ExportTask((frame,entries,audit),root,lambda *_:None)
    assert t.run(),t.error
    import vtk
    reader=vtk.vtkXMLMultiBlockDataReader()
    reader.SetFileName(str(t.result_path))
    reader.Update()
    block=reader.GetOutput().GetBlock(0)
    a,b=block.GetPoint(0),block.GetPoint(1)
    assert abs(b[0]-a[0]-500)<1e-8 and (a[2],b[2])==(20,30)
    print('PASS explicit local metres, indexed shapefile, original XY spacing and Z',flush=True)
    os._exit(0)

if __name__=='__main__': test()
