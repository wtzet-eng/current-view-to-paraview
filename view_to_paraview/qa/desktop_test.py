"""Run in a new QGIS desktop profile using --code. QPV_QA_DIR must be set."""
import json
import os
from pathlib import Path
import sys
import traceback
from qgis.PyQt.QtCore import QTimer, QSettings
from qgis.core import QgsProject, QgsRectangle, QgsCoordinateReferenceSystem, QgsMapThemeCollection
import qgis.utils as qu
from qgis.utils import iface
root=Path(os.environ['QPV_QA_DIR'])
sys.path.insert(0,str(root))
log=root/'desktop.log'
def record(msg):
    with log.open('a') as f: print(msg,file=f,flush=True)

def start():
    try:
        from pyplugin_installer import instance
        instance().installFromZipFile(str(root/'current_view_to_paraview.zip'))
        if 'view_to_paraview' not in qu.plugins:
            qu.loadPlugin('view_to_paraview')
            assert qu.startPlugin('view_to_paraview')
        plugin=qu.plugins['view_to_paraview']
        from probe import build,vector
        project=QgsProject.instance()
        layers,opts=build(root)
        hidden=vector('Hidden','Point',[('POINT(0 0)',['hidden',1,1])])
        scale=vector('Scale hidden','Point',[('POINT(0 0)',['scale',1,1])])
        scale.setScaleBasedVisibility(True)
        scale.setMinimumScale(100)
        layers+=[hidden,scale]
        for l in layers:
            project.addMapLayer(l)
            if l.id() in opts:
                l.setCustomProperty('currentViewParaView/options',json.dumps(opts[l.id()]))
        project.layerTreeRoot().findLayer(hidden.id()).setItemVisibilityChecked(False)
        canvas=iface.mapCanvas()
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        canvas.setRotation(24)
        canvas.setExtent(QgsRectangle(-.35,-.25,.35,.25))
        canvas.refresh()
        model=iface.layerTreeView().layerTreeModel()
        theme=QgsMapThemeCollection.createThemeFromCurrentState(project.layerTreeRoot(),model)
        project.mapThemeCollection().insert('Site view',theme)
        canvas.setTheme('Site view')
        plugin.settings.setValue('currentViewParaView/folder',str(root/'scenes'))
        plugin.settings.setValue('currentViewParaView/exe',os.environ.get('QPV_TEST_EXE','/no/such/paraview'))
        state=[0,None,None]
        def step():
            try:
                if state[0]==0:
                    canvas.setExtent(QgsRectangle(-.22,-.16,.22,.16))
                    canvas.refresh()
                    state[0]=1
                    plugin.actions[0].trigger()
                    assert plugin.task,iface.messageBar().currentItem().text()
                    state[1]=plugin.task
                    canvas.setExtent(QgsRectangle(-2,-1.5,2,1.5))
                    canvas.refresh()
                elif state[0]==1 and plugin.task is None:
                    assert plugin.last_scene,state[1].error
                    p=Path(plugin.last_scene)
                    state[2]=p
                    a=json.loads((p.parent/'snapshot.json').read_text())
                    assert {l['name'] for l in a['layers']}=={'Wells','River','Geology','Global DEM'},a
                    assert a['theme']=='Site view'
                    assert max(abs(x) for x,y in a['corners'])<1
                    record('FIRST '+str(p))
                    state[0]=2
                    plugin.actions[0].trigger()
                    plugin.task.cancel()
                elif state[0]==2 and plugin.task is None:
                    assert Path(plugin.last_scene)==state[2] and state[2].exists()
                    state[0]=3
                    plugin.actions[0].trigger()
                elif state[0]==3 and plugin.task is None:
                    p=Path(plugin.last_scene)
                    assert p!=state[2] and state[2].exists()
                    a=json.loads((p.parent/'snapshot.json').read_text())
                    assert max(abs(x) for x,y in a['corners'])>1
                    record('REFRESH '+str(p))
                    plugin.settings.setValue('currentViewParaView/exe','/no/such/paraview')
                    state[0]=4
                    plugin.actions[0].trigger()
                elif state[0]==4 and plugin.task is None:
                    msg=iface.messageBar().currentItem().text()
                    assert 'Glance' in msg,msg
                    assert Path(plugin.last_scene).with_name('view.html').is_file()
                    record('PASS clean ZIP, toolbar, theme, hidden/scale, fixed frame, cancellation, refresh, missing executable')
                    os._exit(0)
                QTimer.singleShot(150,step)
            except BaseException:
                record(traceback.format_exc())
                os._exit(2)
        QTimer.singleShot(800,step)
    except BaseException:
        record(traceback.format_exc())
        os._exit(2)
QTimer.singleShot(800,start)
