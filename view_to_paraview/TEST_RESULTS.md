# Verification · Current View to ParaView 0.1.0

## Global terrain benchmark

A synthetic, north-up global GeoTIFF covers 360° × 180° at 0.01° spacing. Its 36,000 × 18,000 band contains 648 million signed 16-bit samples, equivalent to 1,296,000,000 bytes unpacked. The compressed sparse fixture is about 629 KiB on disk. A central patch has elevation 112 m and a NoData hole. This isolates spatial access behaviour from download speed. The source is local.

The 800 × 600 test widget used a 24° rotation. Each snapshot included terrain, surveyed wells, a 3D line and a polygon with a hole in a different CRS. Results below come from a sequential run in Debian 13.6, QGIS 3.40.6 and GDAL 3.10.3.

| Measurement | Site view | Wider view |
|---|---:|---:|
| Requested extent before canvas fitting | 0.7° × 0.5° | 14° × 10.5° |
| Terrain sample grid | 71 × 54 | 683 × 512 |
| Valid terrain quads | 3,657 | 232,863 |
| Raster block requests, 128 × 128 each | 1 | 117 |
| Upper bound on uncompressed requested samples and masks | 48 KiB | 5.48 MiB |
| Whole snapshot folder | 269,129 bytes | 16,206,242 bytes |
| Worker export time | 0.047 s | 0.855 s |
| Process peak resident memory | 177.3 MiB | 260.7 MiB |

For the site view the only raster sample request started at source column 17,920 and row 8,960, with width and height 128. Both outputs were below the 350,000-sample budget. Where source resolution was coarser than the screen, the exporter avoided creating extra vertices. The test records GDAL band and mask requests made by the exporter. Physical disk traffic, QGIS's own map rendering and network transfer were not measured. Worker timing excludes GUI startup and opening ParaView. Peak memory includes the QGIS Python process and is cumulative across the run.

## Behaviour checked

- **Ubuntu 24.04.5 LTS, QGIS 3.34.4 and ParaView 5.11.2 desktop.** Used the QGIS ZIP installer in an isolated profile. Triggered the installed toolbar action. The theme included visible terrain, mixed-CRS geology, a 3D river and wells. A hidden layer and a scale-ineligible layer stayed out. Panning while the first task ran preserved the captured extent.
- A manual refresh produced a separate scene, and the original remained readable. An immediately cancelled refresh preserved the previous result. The real ParaView GUI rendered the original and refreshed scenes. An in-session inspection read all four block names and the well at 108 m, source feature 1, label A. The missing-executable test preserved the scene and displayed its path. The desktop check used programmatic inspection, rather than a mouse pick.
- **Debian 13.6, QGIS 3.40.6 and ParaView 5.13.2 pvpython.** Opened both benchmark snapshots. Checked groundwater elevation, feature ID, string attributes and the empty centre of the triangulated polygon. Checked clipped river endpoint positions against the rotated canvas edges and their interpolated geometry Z values.
- Verified an indexed on-disk GeoPackage and indexed memory vectors. Checked a subset expression, partial selection, rule filter, temporal instant filtering, split longitude queries around ±180°, interval depths and retained material labels. A missing collar stayed missing. Terrain had a visible NoData gap.
- Cancelled during traversal of a 20,100-feature dense layer. A second run reached the candidate limit. Both removed staging data and preserved the prior snapshot. An overview fixture selected an existing coarser band, and an over-budget native export returned the estimated sample count.
- Windows, macOS and QGIS 4 were not tested. Desktop frame rate and remote-source throughput were not benchmarked. The supported input and renderer limits are in README.md.

## Reproduce

The qa folder contains the fixture, benchmark and checks. From a working directory containing the view_to_paraview package, run these with a Python interpreter that can import QGIS, GDAL and NumPy. The geometry verification scripts also use VTK Python. On a headless Linux machine set QT_QPA_PLATFORM=offscreen. Set PYTHONPATH to the working directory.

- Run qa/probe.py and use the printed scene paths with pvpython qa/read_scene.py.
- Run qa/edge_cases.py, qa/budgets.py and qa/disk_vector.py.
- For a desktop run, place probe.py, desktop_test.py and the installable ZIP (named current_view_to_paraview.zip for the harness) in a fresh test directory. Set QPV_QA_DIR to it and QPV_TEST_EXE to a ParaView executable. Start a separate QGIS process with a fresh --profiles-path, --profile and --code pointing to desktop_test.py. The harness creates synthetic data and closes that test process when finished.

## 0.1.1 regression checks

Reproduced the original CRS failure with a geographic canvas containing survey-grid coordinates in the millions. In QGIS 3.34.4 on Ubuntu, explicit local-metre mode exported the indexed profile in the affected project with 27 cells. Other visible unindexed sources were reported. An independent test with an indexed 3D shapefile checked that a 500-unit segment remained 500 m long, elevations remained 20 and 30 m, and the scene had no inferred geographic CRS. The existing longitude wrap, rotated clipping, subset, rule and temporal tests passed.

## 0.1.2 browser verification

On Ubuntu with QGIS 3.34.4, a four-layer snapshot opened in Firefox 149.0.2 with no desktop ParaView involved. All four names appeared in Glance, the terrain rendered with its NoData hole, and the browser resource log contained zero HTTP or HTTPS requests. The VTP writer now uses an eight-byte array length header to align Float64 coordinates for the browser reader. ParaView 5.13.2 also read the new VTP files and returned the test well at 108 m with its source ID and label. The survey local-grid, antimeridian and clipping checks passed.

## 0.1.3 verification

In a local survey regression test, QGIS 3.34.4 exported all 13 visible layers. The scene contained ten indexed 3D borehole paths, 50 points from a local delimited-text table, 27 seismic profile cells and 129,506 Cretaceous surface cells. The surface used signed band values as metres. Its source had a .tif extension and was identified by GDAL as an Arc/Info ASCII grid. Firefox 149.0.2 loaded all 13 named datasets with no skipped layers or network requests. Local-grid geometry, filtering, clipping, cancellation and budget tests also passed.
