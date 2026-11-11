import json
import os
from pathlib import Path
import shutil
from qgis.PyQt.QtCore import QProcess, QProcessEnvironment, QStandardPaths, QSettings, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (QAction, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QSpinBox)
from qgis.core import Qgis, QgsApplication, QgsRasterLayer, QgsVectorLayer
from .export import capture, ExportTask
from . import display
from .spatial import LocalGridRequired

KEY = 'currentViewParaView/'
MODES = [('flat','Geometry Z, otherwise flat reference at 0 m'),
         ('geometry','Geometry Z only'),('field','Height from field'),
         ('terrain','Sample displayed terrain'),('water','Water observation below collar'),
         ('interval','Vertical logged interval below collar')]


def layer_options(layer):
    return json.loads(str(layer.customProperty(KEY+'options','{}')))


def detect():
    found = shutil.which('paraview')
    if found:
        return found
    patterns = [('/Applications','ParaView*.app/Contents/MacOS/paraview'),
                (os.environ.get('ProgramFiles','C:/Program Files'),'ParaView*/bin/paraview.exe')]
    return next((str(p) for base,pattern in patterns for p in sorted(Path(base).glob(pattern),reverse=True)),'')


class ViewPlugin:
    def __init__(self,iface):
        self.iface,self.actions,self.task = iface,[],None
        self.settings=QSettings()
        self.last_scene=None

    def initGui(self):
        actions=[('Send current view to ParaView',self.send),('Open current view in browser (Glance)',self.send_browser),
                 ('Configure 3D view…',self.configure_display), ('Configure active layer…',self.configure),
                 ('Choose ParaView executable…',self.executable),('Choose export folder…',self.folder)]
        for label,fn in actions:
            action=QAction(label,self.iface.mainWindow())
            action.triggered.connect(fn)
            self.iface.addPluginToMenu('Current View to ParaView',action)
            self.actions.append(action)
        self.actions[0].setIcon(QgsApplication.getThemeIcon('/mActionNew3DMap.svg'))
        self.iface.addToolBarIcon(self.actions[0])

    def unload(self):
        if self.task:
            self.task.callback=lambda *args: None
            self.task.cancel()
        self.iface.removeToolBarIcon(self.actions[0])
        for action in self.actions:
            self.iface.removePluginMenu('Current View to ParaView',action)
            action.deleteLater()

    def executable(self):
        path,_=QFileDialog.getOpenFileName(self.iface.mainWindow(),'Choose ParaView executable')
        if path:
            self.settings.setValue(KEY+'exe',path)

    def folder(self):
        path=QFileDialog.getExistingDirectory(self.iface.mainWindow(),'Choose export folder')
        if path:
            self.settings.setValue(KEY+'folder',path)

    def configure_display(self):
        display.configure(self.iface.mapCanvas(), self.iface.mainWindow())

    def configure(self):
        layer=self.iface.activeLayer()
        if not isinstance(layer,(QgsRasterLayer,QgsVectorLayer)):
            self.iface.messageBar().pushWarning('ParaView','Select a vector or elevation raster layer first.')
            return
        opts=layer_options(layer)
        dialog=QDialog(self.iface.mainWindow())
        dialog.setWindowTitle('ParaView · '+layer.name())
        form=QFormLayout(dialog)
        omit=QCheckBox('Omit this layer')
        omit.setChecked(opts.get('omit',False))
        form.addRow(omit)
        units=QComboBox()
        units.addItems(['Metres','International feet'])
        units.setCurrentIndex(int(opts.get('factor',1)!=1))
        form.addRow('Source height and depth units',units)
        if isinstance(layer,QgsRasterLayer):
            dem=QCheckBox('Use as elevation terrain')
            dem.setChecked(opts.get('dem',layer.elevationProperties().isEnabled()))
            form.addRow(dem)
            band=QSpinBox()
            band.setRange(1,layer.bandCount())
            band.setValue(opts.get('band',layer.elevationProperties().bandNumber()))
            form.addRow('Elevation band',band)
            resolution=QComboBox()
            resolution.addItems(['Screen resolution','Coarse preview','Native resolution (budget applies)'])
            resolution.setCurrentIndex(2 if opts.get('native') else int(opts.get('coarsening',1)>1))
            form.addRow('Resolution',resolution)
            estimate=QLabel()
            estimate.setWordWrap(True)
            form.addRow(estimate)
            def estimate_native():
                from .terrain import Terrain
                from .spatial import Frame
                if not os.path.isfile(layer.source()) or layer.providerType() != 'gdal':
                    estimate.setText('Local GeoTIFF terrain required.')
                    return
                try:
                    grid=Terrain(layer.source(),Frame(self.iface.mapCanvas().mapSettings()),band.value(),1,False)
                    nx,ny=map(int,grid.native_dims)
                    estimate.setText(f'Native estimate for this view: {nx:,} × {ny:,} samples, about {nx*ny*70/1048576:.1f} MiB of scene data.')
                except (ValueError, RuntimeError, AttributeError) as exc:
                    estimate.setText(str(exc))
            band.valueChanged.connect(estimate_native)
            estimate_native()
        else:
            mode=QComboBox()
            for key,label in MODES:
                if layer.geometryType()==0 or key not in ('water','interval'):
                    mode.addItem(label,key)
            mode.setCurrentIndex(max(0,mode.findData(opts.get('mode','flat'))))
            form.addRow('Height source',mode)
            combos={}
            for key,label in [('elevation','Elevation / collar field'),('depth','Water depth below collar'),
                              ('top','Interval top below collar'),('base','Interval base below collar')]:
                box=QComboBox()
                box.addItem('Use displayed terrain' if key=='elevation' else 'Choose field','')
                for field in layer.fields():
                    if field.isNumeric():
                        box.addItem(field.name(),field.name())
                box.setCurrentIndex(max(0,box.findData(opts.get(key,''))))
                form.addRow(label,box)
                combos[key]=box
            def enable_fields():
                value=mode.currentData()
                for key,box in combos.items():
                    box.setEnabled(value in {'elevation':('field','water','interval'),'depth':('water',),
                                               'top':('interval',),'base':('interval',)}[key])
            mode.currentIndexChanged.connect(enable_fields)
            enable_fields()
            attrs=QListWidget()
            for name in layer.fields().names():
                item=QListWidgetItem(name,attrs)
                item.setCheckState(Qt.Checked if name in opts.get('attributes',[]) else Qt.Unchecked)
            form.addRow('Include attributes',attrs)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec_()!=QDialog.Accepted:
            return
        result=dict(omit=omit.isChecked(),factor=0.3048 if units.currentIndex() else 1.0)
        if isinstance(layer,QgsRasterLayer):
            result.update(dem=dem.isChecked(),band=band.value(),native=resolution.currentIndex()==2,
                          coarsening=2 if resolution.currentIndex()==1 else 1)
        else:
            result['mode']=mode.currentData()
            result.update({key:box.currentData() for key,box in combos.items() if box.isEnabled()})
            required={'field':['elevation'],'water':['depth'],'interval':['top','base']}.get(result['mode'],[])
            if any(not result[key] for key in required):
                QMessageBox.warning(dialog,'ParaView','Choose the required numeric fields.')
                return
            result['attributes']=[attrs.item(i).text() for i in range(attrs.count()) if attrs.item(i).checkState()==Qt.Checked]
        layer.setCustomProperty(KEY+'options',json.dumps(result))
        from qgis.core import QgsProject
        QgsProject.instance().setDirty(True)

    def send_browser(self):
        self.send(browser=True)

    def send(self, checked=False, *, browser=False):
        if self.task:
            return
        try:
            canvas=self.iface.mapCanvas()
            options={layer.id():layer_options(layer) for layer in canvas.mapSettings().layers()}
            for index,node in enumerate(display.layers_in_tree(canvas)):
                opts = options[node.layerId()]
                opts['display'] = display.style(node,index)
                field = opts['display']['field']
                if field and field not in opts.get('attributes', []):
                    opts['attributes'] = [*opts.get('attributes', []), field]
            for layer in canvas.mapSettings().layers():
                if not isinstance(layer,QgsRasterLayer) or not layer.isValid():
                    continue
                opts=options[layer.id()]
                if 'dem' in opts or opts.get('omit') or layer.elevationProperties().isEnabled():
                    continue
                if (layer.providerType()!='gdal' or layer.bandCount()!=1
                        or not layer.source().lower().endswith(('.tif','.tiff','.asc','.grd'))
                        or not os.path.isfile(layer.source()) or not layer.isInScaleRange(canvas.scale())
                        or layer.dataProvider().dataType(1) not in (Qgis.Float32,Qgis.Float64)):
                    continue
                answer=QMessageBox.question(self.iface.mainWindow(),'Include raster surface?',
                    f'Use band 1 of “{layer.name()}” as a surface with Z in metres for this view? '
                    'Choose No if its values represent something else.',
                    QMessageBox.Yes | QMessageBox.No,QMessageBox.No)
                opts.update(dem=answer==QMessageBox.Yes,band=1)
                if answer==QMessageBox.No:
                    opts['omit']=True
            try:
                snapshot=capture(canvas,options)
            except LocalGridRequired as exc:
                answer=QMessageBox.question(
                    self.iface.mainWindow(), 'Export using a local grid?',
                    str(exc)+'\n\nAre the displayed X and Y in metres? Choose Yes to preserve '
                    'their spacing in a local 3D scene. The geographic location will be unspecified.',
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                if answer != QMessageBox.Yes:
                    return
                snapshot=capture(canvas,options,allow_local_metres=True)
            snapshot[2]["vertical_scale"] = display.exaggeration()
            default=Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))/'QGIS ParaView'
            executable = self.settings.value(KEY+'exe','') or detect()
            use_browser = browser or not (executable and shutil.which(executable))
            self.task=ExportTask(snapshot,self.settings.value(KEY+'folder',str(default)),self.completed,use_browser)
            for action in self.actions[:2]:
                action.setEnabled(False)
            QgsApplication.taskManager().addTask(self.task)
        except Exception as exc:
            self.task=None
            for action in self.actions[:2]:
                action.setEnabled(True)
            self.iface.messageBar().pushWarning('ParaView',str(exc))

    def completed(self,task,success):
        self.task=None
        for action in self.actions[:2]:
            action.setEnabled(True)
        bar=self.iface.messageBar()
        if not success or not task.result_path:
            bar.pushWarning('ParaView',task.error or 'Export cancelled.')
            return
        self.last_scene=str(task.result_path)
        skipped=task.audit['skipped']
        if skipped:
            bar.pushWarning('ParaView',' · '.join(item['layer']+': '+item['reason'] for item in skipped))
        if task.browser_view:
            preview = task.result_path.with_name('view.html')
            if task.browser_error:
                bar.pushWarning('ParaView',task.browser_error+' '+self.last_scene)
            elif QDesktopServices.openUrl(QUrl.fromLocalFile(str(preview))):
                bar.pushInfo('ParaView','Opening Kitware Glance in your browser. '+str(preview))
            else:
                bar.pushWarning('ParaView','Open the saved browser view: '+str(preview))
            return
        exe=self.settings.value(KEY+'exe','') or detect()
        if exe:
            try:
                # Qt launches the selected executable directly, without a shell.
                # Give the ParaView script the saved scene through its environment.
                script = Path(__file__).with_name('open_scene.py')
                process = QProcess()
                process.setProgram(exe)
                process.setArguments(['--script=' + str(script)])
                environment = QProcessEnvironment.systemEnvironment()
                environment.insert('QGIS_PARAVIEW_SNAPSHOT', self.last_scene)
                process.setProcessEnvironment(environment)
                started, _pid = process.startDetached()
                if started:
                    bar.pushInfo('ParaView','Launching snapshot '+self.last_scene)
                    return
            except OSError:
                pass
        bar.pushWarning('ParaView','Scene saved. Choose a ParaView executable in the plugin menu, or open '+self.last_scene)
