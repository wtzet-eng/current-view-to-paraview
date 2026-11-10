"""Exercise in-flight cancellation, bounded failure and native/overview reads."""
from probe import *
from view_to_paraview.terrain import Terrain
from view_to_paraview.spatial import Frame

def main():
    app=QgsApplication([],True);app.setPrefixPath('/usr',True);app.initQgis()
    root=Path(tempfile.mkdtemp())
    canvas=QgsMapCanvas();canvas.resize(640,480);canvas.show();app.processEvents()
    layers,opts=build(root)
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
    canvas.setExtent(QgsRectangle(-.3,-.3,.3,.3));canvas.setLayers(layers)
    good=run_scene(canvas,opts,root/'out')
    before=set((root/'out').iterdir())
    dense=vector('Dense','Point',[])
    feats=[]
    for i in range(20100):
        f=QgsFeature(dense.fields());f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY((i%100)*.0001,(i//100)*.0001)))
        feats.append(f)
    assert dense.dataProvider().addFeatures(feats)[0]
    dense.updateExtents()
    canvas.setLayers([dense])
    snapshot=capture(canvas,{})
    task=ExportTask(snapshot,root/'out',lambda *_:None)
    class CountingTask(ExportTask):
        calls=0
        def check(self):
            self.calls+=1
            if self.calls==301: self.cancel()
            super().check()
    cancel=CountingTask(capture(canvas,{}),root/'out',lambda *_:None)
    assert not cancel.run() and 'cancelled' in cancel.error and cancel.calls==301
    assert not task.run() and 'Candidate feature limit' in task.error
    assert set((root/'out').iterdir())==before and good.result_path.exists()
    # Check overview choice on a small local tile with known coarser levels.
    tif=str(root/'overview.tif')
    ds=gdal.GetDriverByName('GTiff').Create(tif,2048,2048,1,gdal.GDT_Int16,options=['TILED=YES'])
    s=osr.SpatialReference();s.ImportFromEPSG(4326);ds.SetProjection(s.ExportToWkt())
    ds.SetGeoTransform((-1,2/2048,0,1,0,-2/2048))
    ds.GetRasterBand(1).Fill(112)
    ds.BuildOverviews('NEAREST',[2,4,8]);ds=None
    canvas.setExtent(QgsRectangle(-1,-1,1,1))
    frame=Frame(canvas.mapSettings())
    terrain=Terrain(tif,frame,1,1,False)
    terrain.write(root/'overview.vtp',lambda: None)
    assert terrain.audit['overview'][0]<2048
    try: Terrain(tif,frame,1,1,True)
    except ValueError as exc: assert 'Native terrain needs' in str(exc)
    else: raise AssertionError('native budget bypass')
    print('PASS active dense cancellation, candidate limit, prior scene preservation, overview and native budget',flush=True)
    os._exit(0)
if __name__=='__main__': main()
