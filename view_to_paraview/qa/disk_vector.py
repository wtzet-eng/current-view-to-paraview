from probe import *
from edge_cases import load
app=QgsApplication([],True);app.setPrefixPath('/usr',True);app.initQgis()
root=Path(tempfile.mkdtemp())
layers,opts=build(root)
out=root/'wells.gpkg'
msg=QgsVectorFileWriter.writeAsVectorFormatV3(layers[0],str(out),QgsProject.instance().transformContext(),QgsVectorFileWriter.SaveVectorOptions())
assert msg[0]==0,msg
disk=QgsVectorLayer(str(out),'Disk wells','ogr')
print('storage',disk.storageType(),flush=True)
canvas=QgsMapCanvas();canvas.resize(640,480);canvas.show();app.processEvents()
canvas.setLayers([disk]);canvas.setDestinationCrs(disk.crs());canvas.setExtent(QgsRectangle(-.3,-.3,.3,.3))
t=run_scene(canvas,{disk.id():opts[layers[0].id()]},root)
print(t.audit['layers'][0]['cells'],flush=True)
os._exit(0)
