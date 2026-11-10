# Current View to ParaView · 0.1.3

Frame a site in QGIS and click **Send current view to ParaView**. Each click creates a local 3D snapshot. Panning and zooming are free of export work.

## Install and try it

1. Install QGIS 3.34 or later in the 3.x series and a WebGL-capable browser. Desktop ParaView with Python support is optional. The plugin uses the NumPy and GDAL Python bindings supplied with common QGIS distributions. Polygon triangulation needs GEOS 3.11 or newer.
2. In QGIS open **Plugins → Manage and Install Plugins → Install from ZIP**. Select the downloaded ZIP without extracting it. Enable **Current View to ParaView**.
3. Add a local elevation GeoTIFF. Select it in the Layers panel and choose **Plugins → Current View to ParaView → Configure active layer**. Tick **Use as elevation terrain**, choose the elevation band and units, and press **OK**. A raster already marked as elevation in QGIS is recognised automatically. Review the settings when using multiband data. Terrain comes from the elevation samples, with the raster scale and offset applied.
4. Add a spatially indexed local GeoPackage or shapefile of points, lines or polygons. A QGIS memory layer with a provider spatial index also works. Select each layer and configure its height and any attributes to include. By default, a feature keeps its geometry Z in metres. Ordinary 2D geometry sits on a flat 0 m reference plane. Select **Sample displayed terrain** to drape the vertices. Save the QGIS project to retain the mappings.
5. For the browser, choose **Plugins → Current View to ParaView → Open current view in browser (Glance)**. All successfully exported layers open together. Use the eye beside each layer to toggle it and drag the 3D view to rotate. The toolbar chooses the browser automatically when it cannot find a desktop ParaView executable.
6. Pan to a new site and click again for a fresh snapshot. Progress and cancellation are available in the QGIS task manager. Use **Choose export folder** to change the default **Documents/QGIS ParaView**.

The browser snapshot is a self-contained **view.html** with the layer data and Kitware Glance viewer embedded. Double-click it later, including offline. It requires a WebGL-capable browser and permits no network connections from the page. The viewer and licence notices are included in the ZIP. The browser preview accepts up to 96 MiB of VTP input per snapshot. A larger export retains its VTK files and gives a message to reduce the extent or omit layers.

For desktop viewing, use **Choose ParaView executable** to select an installed ParaView program. The toolbar then opens it by default, and the browser menu action remains available. The **scene.vtm** index works with its adjacent VTP files. Copy the entire folder for desktop use. Glance's numeric handling of 64-bit integer attributes is limited. Use the original VTK files for exact large integer IDs. See **snapshot.json** for skipped layers, coordinate origin and measurements.

## Vertical borehole example

For a surveyed vertical well, select **Water observation below collar**. Map the collar field to the surveyed elevation and the water-depth field to the positive distance below that same collar. A collar at 112 m and water 4 m below it gives a point at 108 m. Include the well label, depth, collar and observation date as attributes if desired. Leaving the collar field set to **Use displayed terrain** uses the nearest exported terrain sample. The snapshot records which method you selected.

For a log with one point record per material interval, choose **Vertical logged interval below collar**, map top and base depths, and include the material attribute. Use one consistent vertical reference per scene. The source-unit setting applies to the configured fields on that layer. Terrain-derived collar elevations are already in metres. Missing heights, invalid intervals and negative depths are counted and omitted. Deviated wells require trajectory processing outside this release.

## Scope and limits

- Layer visibility comes from the captured canvas, including its theme, scale and supported temporal and renderer filters. Simple field-based rules are supported. Unsupported renderers, data-defined visibility, expression-based temporal intervals, joins, virtual fields and active edit sessions produce a reason in the export summary. QGIS symbols and labels are outside the geometry export.
- Geometry Z, chosen height attributes and terrain samples are separate height choices. Flat placement can put vectors under the terrain. For a surface overlay, select terrain sampling explicitly. With several terrain layers, sampling uses the first successfully exported visible terrain in canvas layer order. Vertical datum conversions and QGIS display exaggeration are outside this version.
- The horizontal scene uses projected metres and a local XY origin. For geographic, non-metre or Web Mercator canvases the plugin builds a local azimuthal equidistant CRS centred on the view. Add the recorded origin to scene XY to recover projected map coordinates. Mixed horizontal CRSs are supported. The primary use is a local site view.
- GeoTIFF input uses bounded block reads, masks and available overviews. The screen setting caps detail at the estimated native spacing and 350,000 samples. Coarse preview uses an 87,500-sample cap. Native mode estimates source spacing near the view centre and resamples to the canvas orientation. Terrain cells with a missing corner are omitted. The budget is 64 MiB of requested uncompressed raster blocks per layer. Use tiled GeoTIFFs with overviews for large sources.
- The vector budget is 20,000 candidate features, 30,000 coordinates per input feature and 150,000 exported vertices per layer. The worker checks large individual geometries after the provider returns them. The physical cost of reading one unusually large feature still depends on its storage. Scene limits are 1.5 million cells and 256 MiB of staged layer files.
- Web imagery, WMS, remote rasters, point clouds, general databases and unindexed sources are skipped. Export eligible vectors to a spatially indexed GeoPackage to use them here. Save raster terrain as a local tiled GeoTIFF. Unsupported or over-budget layers appear in the summary. A scene with no eligible data is reported without creating a replacement.
- Snapshots use binary arrays in VTK XML, with a VTM index, a VTP per layer and a JSON record. Numeric nulls use NaN or a companion validity array. Source IDs remain 64-bit integers. Geometry positions and scalar elevations use metres.
- This is a standalone experimental plugin. The ZIP contains its complete Python source, test scripts, results and GPL-2.0-or-later licence. No GroundSurf account or service is required.


## Local survey grids

When a canvas labelled in degrees has a centre outside the latitude range, the export asks whether the displayed X and Y are metres. Confirm only if the survey grid uses metres. The snapshot preserves raw XY spacing, records a local origin and leaves the geographic CRS unspecified. Layers with a different CRS label are skipped. The project and source metadata are unchanged. For a shapefile without a spatial index, QGIS Processing → Create spatial index adds an index alongside the original file.

The viewer assets in glance/ are from Kitware's published Glance app at https://kitware.github.io/glance/app/. The content-hashed filenames identify the builds. The file icon.woff2 is their e9db4005489e24809b62.woff2 asset. Upstream notices accompany the viewer and are embedded in each generated page.


## Showing multiple survey layers

The export uses the layers visible in the current QGIS canvas. In Glance each layer has its own visibility control. Mixed scenes start with a palette of colours and larger survey points. If a surface obscures a borehole or log, lower the surface opacity or toggle its eye.

Indexed local delimited-text layers with XY or XYZ columns are supported. For a local table up to 1 MiB, the plugin can build its index in memory. Larger tables need an index enabled in the layer settings. For shapefiles, use QGIS Processing → Create spatial index once. It creates a sidecar beside the source.

An unconfigured single-band floating-point raster can be included as a surface when the user confirms its values are heights in metres. For feet or other mappings use Configure active layer. Local Arc/Info ASCII grids up to 8 MiB and two million cells are supported alongside GeoTIFF terrain. Large ASCII grids should be converted to tiled GeoTIFFs for windowed access.
