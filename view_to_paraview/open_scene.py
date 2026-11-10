"""Executed inside the separately installed ParaView GUI."""
import os
from paraview.simple import GetActiveViewOrCreate, OpenDataFile, Render, ResetCamera, Show

reader = OpenDataFile(os.environ['QGIS_PARAVIEW_SNAPSHOT'])
reader.UpdatePipeline()
view = GetActiveViewOrCreate('RenderView')
display = Show(reader, view)
display.PointSize = 6
display.LineWidth = 2
view.CameraPosition = [1, -1, 0.85]
view.CameraFocalPoint = [0, 0, 0]
view.CameraViewUp = [0, 0, 1]
ResetCamera(view)
Render(view)
