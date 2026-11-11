"""Capture QGIS state on its GUI thread, then export from the frozen snapshot."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from qgis.core import QgsMapSettings, QgsRasterLayer, QgsTask, QgsVectorLayer
from .browser import write_browser_view
from .spatial import Frame
from .terrain import Terrain, CELL_LIMIT
from .vector import capture_vector, vector_file
from .vtkio import scene


def capture(canvas, options, allow_local_metres=False):
    settings = QgsMapSettings(canvas.mapSettings())
    if not settings.hasValidSettings() or settings.clippingRegions():
        raise ValueError('A valid 2D canvas without extra clipping regions is required.')
    if not settings.zRange().isInfinite():
        raise ValueError('Canvas elevation range filtering is unsupported.')
    frame = Frame(settings, allow_local_metres)
    data, skipped = [], []
    for layer in settings.layers():
        if not layer.isInScaleRange(settings.scale()):
            continue
        temporal = layer.temporalProperties()
        if settings.isTemporal() and temporal and temporal.isActive():
            if not temporal.isVisibleInTemporalRange(settings.temporalRange()):
                continue
        opts = dict(options.get(layer.id(),{}))
        if opts.get('omit'):
            continue
        name = layer.name()
        try:
            if not layer.isValid() or not layer.crs().isValid():
                raise ValueError('Layer or CRS is invalid.')
            if frame.local_grid and layer.crs() != frame.crs:
                raise ValueError('Local-grid export requires the same coordinate label as the canvas.')
            entry = dict(name=name,id=layer.id(),vertical_crs=layer.verticalCrs().description()
                         if hasattr(layer,'verticalCrs') else '',opts=opts)
            if isinstance(layer,QgsRasterLayer):
                if settings.isTemporal() and temporal and temporal.isActive():
                    raise ValueError('Time-dependent rasters are unsupported.')
                if not opts.get('dem',layer.elevationProperties().isEnabled()):
                    raise ValueError('Choose an elevation band in Layer settings to use this raster as terrain.')
                if layer.providerType()!='gdal' or not os.path.isfile(layer.source()):
                    raise ValueError('Only local GeoTIFF terrain supports audited block reads.')
                override = settings.layerStyleOverrides().get(layer.id())
                manager = layer.styleManager()
                if override and not manager.setOverrideStyle(override):
                    raise ValueError('The raster theme style could not be resolved.')
                try:
                    band = opts.get('band',max(1,layer.elevationProperties().bandNumber()))
                    renderer = layer.renderer()
                    transparency = renderer.rasterTransparency() if renderer else None
                    provider = layer.dataProvider()
                    if layer.opacity()<=0 or (renderer and (renderer.opacity()<=0 or renderer.alphaBand()>0
                         or (transparency and not transparency.isEmpty()))) or provider.userNoDataValues(band):
                        raise ValueError('Custom transparency, zero opacity or custom NoData rules.')
                    if not provider.useSourceNoDataValue(band) and provider.sourceHasNoDataValue(band):
                        raise ValueError('The raster disables the source NoData filter.')
                finally:
                    if override:
                        manager.restoreOverrideStyle()
                if provider.crs() != layer.crs():
                    raise ValueError('The assigned raster CRS differs from its source CRS.')
                entry.update(kind='terrain',path=layer.source(),band=band)
            elif isinstance(layer,QgsVectorLayer):
                entry.update(kind='vector',vector=capture_vector(layer,settings,opts))
            else:
                raise ValueError('Unsupported layer type.')
            data.append(entry)
        except (ValueError,RuntimeError) as exc:
            skipped.append(dict(layer=name,reason=str(exc)))
    tr=settings.temporalRange()
    audit=dict(created=datetime.now(timezone.utc).isoformat(),theme=canvas.theme(),scale=settings.scale(),
               canvas=[frame.width,frame.height],corners=[[p.x(),p.y()] for p in frame.corners],
               canvas_crs=frame.crs.toWkt(),scene_crs=None if frame.local_grid else frame.scene.toWkt(),
               coordinate_mode="user_confirmed_local_metres" if frame.local_grid else "georeferenced",origin=[frame.origin.x(),frame.origin.y(),0],
               horizontal_units='metres',vertical_units='metres',vertical_datum_transform=False,
               temporal=[tr.begin().toString('yyyy-MM-ddTHH:mm:ss.zzz t'),tr.end().toString('yyyy-MM-ddTHH:mm:ss.zzz t')]
               if settings.isTemporal() else None,skipped=skipped,layers=[])
    return frame,data,audit


class Cancelled(Exception):
    pass


class ExportTask(QgsTask):
    def __init__(self,snapshot,folder,callback,browser_view=False):
        super().__init__('Send current view to ParaView',QgsTask.CanCancel)
        self.frame,self.entries,self.audit = snapshot
        self.folder,self.callback = Path(folder),callback
        self.result_path,self.error = None,''
        self.browser_view = browser_view
        self.browser_error = ''
        self.setProgress(0)

    def check(self):
        if self.isCanceled():
            raise Cancelled()

    def run(self):
        stage = None
        try:
            self.folder.mkdir(parents=True,exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix='.staging-',dir=self.folder))
            blocks, terrain = [],None
            entries = sorted(self.entries,key=lambda e:e['kind']!='terrain')
            total_cells = 0
            for i,e in enumerate(entries):
                self.check()
                filename = f'layer_{i:03d}.vtp'
                start = time.monotonic()
                try:
                    opts=e['opts']
                    if e['kind']=='terrain':
                        t = Terrain(e['path'],self.frame,e['band'],opts.get('factor',1),opts.get('native',False),
                                    CELL_LIMIT//max(1,opts.get('coarsening',1)**2))
                        t.write(stage/filename,self.check)
                        metric=t.audit
                        if terrain is None:
                            terrain=t
                    else:
                        metric=vector_file(stage/filename,e['vector'],self.frame,terrain,self.check)
                    total_cells += metric['cells']
                    if total_cells>1500000 or sum(p.stat().st_size for p in stage.iterdir())>256*1024**2:
                        raise RuntimeError('Scene exceeds the aggregate budget. Zoom in or omit layers.')
                    self.audit['layers'].append(dict(name=e['name'],source_layer_id=e['id'],file=filename,
                        vertical_crs=e['vertical_crs'] or 'unknown',settings=opts,seconds=time.monotonic()-start,**metric))
                    blocks.append((e['name'],filename))
                except ValueError as exc:
                    (stage/filename).unlink(missing_ok=True)
                    self.audit['skipped'].append(dict(layer=e['name'],reason=str(exc)))
                self.setProgress(100*(i+1)/max(1,len(entries)))
            if not blocks:
                raise ValueError('No exportable layers. '+ ' '.join(x['layer']+': '+x['reason'] for x in self.audit['skipped']))
            styles = {m['file']:dict(m['settings'].get('display', {})) for m in self.audit['layers']}
            for m in self.audit['layers']:
                styles[m['file']].update({k:m[k] for k in ('tube_file','points_file') if k in m})
            blocks.sort(key=lambda b:styles[b[1]].get('order', 0))
            scene(stage,blocks,styles)
            if self.browser_view:
                self.browser_error = write_browser_view(stage,blocks,self.check,styles,self.audit.get("vertical_scale", 1))
            (stage/'snapshot.json').write_text(json.dumps(self.audit,indent=2),encoding='utf-8')
            self.check()
            final=self.folder/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
            stage.rename(final)
            self.result_path=final/'scene.vtm'
            return True
        except Cancelled:
            self.error='Export cancelled.'
        except Exception as exc:
            self.error=str(exc) or type(exc).__name__
        finally:
            if stage and stage.exists():
                shutil.rmtree(stage,ignore_errors=True)
        return False

    def finished(self,success):
        self.callback(self,success)
