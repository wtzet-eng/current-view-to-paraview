"""Run with pvpython SCENE.vtm (and optionally a second snapshot)."""
from paraview.simple import OpenDataFile, Delete
from paraview import servermanager
import sys
for path in sys.argv[1:]:
    reader=OpenDataFile(path)
    reader.UpdatePipeline()
    scene=servermanager.Fetch(reader)
    blocks={scene.GetMetaData(i).Get(scene.NAME()):scene.GetBlock(i) for i in range(scene.GetNumberOfBlocks())}
    well=blocks['Wells']
    assert well.GetNumberOfPoints()>=1
    assert well.GetPoint(0)[2]==108
    fields=well.GetCellData()
    assert fields.GetAbstractArray('field.label').GetValue(0)=='A'
    assert fields.GetArray('source_fid').GetValue(0)==1
    poly=blocks['Geology']
    # Local origin at (0,0). No triangle may cover the centre of the hole.
    for i in range(poly.GetNumberOfCells()):
        tri=poly.GetCell(i)
        xy=[tri.GetPoints().GetPoint(j)[:2] for j in range(3)]
        sides=[x*y2-y*x2 for (x,y),(x2,y2) in zip(xy,xy[1:]+xy[:1])]
        assert min(sides)<0<max(sides)
    print(path, 'blocks', list(blocks), 'water', well.GetPoint(0), 'fid', fields.GetArray('source_fid').GetValue(0),flush=True)
    Delete(reader)
