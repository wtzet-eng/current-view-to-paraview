"""Executed inside the separately installed ParaView GUI."""
import json
import os
from pathlib import Path
from paraview.simple import (ColorBy, GetActiveViewOrCreate, OpenDataFile, RenameSource,
                             Render, ResetCamera, Show, Tube)

scene = Path(os.environ['QGIS_PARAVIEW_SNAPSHOT'])
snapshot = json.loads(scene.with_name('snapshot.json').read_text(encoding='utf-8'))
view = GetActiveViewOrCreate('RenderView')
for layer in snapshot['layers']:
    style = layer['settings'].get('display', {})
    reader = OpenDataFile(str(scene.with_name(layer['file'])))
    reader.UpdatePipeline()
    RenameSource(layer['name'], reader)
    source = reader
    if layer.get('tube_file'):
        source = Tube(Input=reader)
        source.Radius = style['radius']
        source.VaryRadius = 'Off'
        source.UpdatePipeline()
    display = Show(source, view)
    display.ColorArrayName = ['POINTS', '']
    if style.get('field') and 'display_rgb' in source.CellData.keys():
        ColorBy(display, ('CELLS', 'display_rgb'))
        display.MapScalars = 0
    color = style.get('color', '#69afce')
    display.DiffuseColor = [int(color[i:i+2],16)/255 for i in (1,3,5)]
    display.Opacity = style.get('opacity',1)
    display.PointSize = style.get('size',6)
    display.LineWidth = style.get('size',2)
    display.Scale = [1,1,snapshot.get('vertical_scale',1)]
view.CameraPosition = [1, -1, 0.85]
view.CameraFocalPoint = [0, 0, 0]
view.CameraViewUp = [0, 0, 1]
ResetCamera(view)
Render(view)
