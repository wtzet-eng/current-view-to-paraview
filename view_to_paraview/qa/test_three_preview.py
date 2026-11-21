"""Pure-Python sanity tests for the optional Three.js VTP snapshot reader.

Run: python3 -m unittest discover -s view_to_paraview/qa -p test_three_preview.py
No QGIS, ParaView, browser, network or Python VTK dependency is needed.
"""
import base64
import json
import re
import struct
import tempfile
import unittest
from pathlib import Path

from view_to_paraview.three_preview import read_polydata, write_three_preview


def binary(kind, values):
    raw = struct.pack('<' + kind * len(values), *values)
    return base64.b64encode(struct.pack('<Q', len(raw)) + raw).decode('ascii')


def fixture(folder, family='Polys', bad=False):
    coords = binary('d', (0,0,0, 2,0,0, 2,2,1, 0,2,1))
    connectivity = (0, 1, 2, 3) if family in ('Polys','Lines') else (0, 1)
    ends = (4,) if family in ('Polys','Lines') else (1, 2)
    xml = f'''<?xml version="1.0"?><VTKFile type="PolyData"><PolyData>
<Piece NumberOfPoints="4" NumberOfVerts="{len(ends) if family == 'Verts' else 0}"
 NumberOfLines="{len(ends) if family == 'Lines' else 0}"
 NumberOfStrips="0" NumberOfPolys="{len(ends) if family == 'Polys' else 0}">
<Points><DataArray Name="Points" type="Float64" NumberOfComponents="3" format="binary">{coords}</DataArray></Points>
<{family}>
<DataArray Name="connectivity" type="Int32" format="binary">{binary('i', connectivity if not bad else (0, 1, 2, 999))}</DataArray>
<DataArray Name="offsets" type="Int32" format="binary">{binary('i', ends)}</DataArray>
</{family}></Piece></PolyData></VTKFile>'''
    path = folder / 'layer_000.vtp'
    path.write_text(xml, encoding='utf-8')
    return path


class ThreePreviewTests(unittest.TestCase):
    def test_polygon_triangulation_and_vertical_exaggeration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture(Path(directory))
            geometry, n = read_polydata(path, 2)
            self.assertEqual(n, 4)
            self.assertEqual(geometry['family'], 'Polys')
            self.assertEqual(geometry['indices'], [0,1,2,0,2,3])
            self.assertEqual(geometry['points'][11], 2)

    def test_lines_and_observation_points(self):
        for family, expected in [('Lines',[0,1,1,2,2,3]),('Verts',[0,1])]:
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                geometry, _ = read_polydata(fixture(Path(directory),family))
                self.assertEqual(geometry['indices'], expected)

    def test_bad_connectivity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'index out of range'):
                read_polydata(fixture(Path(directory),bad=True))

    def test_rejects_large_files_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            fixture(root)
            self.assertIn('No small VTP', write_three_preview(
                root,[('secret', '../layer_000.vtp')],lambda:None))
            (root/'layer_001.vtp').write_bytes(b'x'*(12*1024*1024+1))
            with self.assertRaisesRegex(ValueError,'not a local lightweight'):
                read_polydata(root/'layer_001.vtp')

    def test_preview_contains_local_geometry_no_remote_data_or_html_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            fixture(root)
            result=write_three_preview(root,[('</script><img src=evil>', 'layer_000.vtp')],
              lambda:None,{'layer_000.vtp':{'color':'#72ac86'}},1.5)
            self.assertEqual(result,'')
            html=(root/'quick-preview.html').read_text()
            self.assertIn("connect-src 'none'",html)
            self.assertIn('three@0.187.0',html)
            self.assertNotIn('</script><img src=evil>',html)
            embedded=re.search(r'<script id="scene-data" type="application/json">(.*?)</script>',html,re.S)
            self.assertIsNotNone(embedded)
            scene=json.loads(embedded.group(1))
            self.assertEqual(scene['points'],4)
            self.assertEqual(scene['layers'][0]['name'],'</script><img src=evil>')
            self.assertEqual(scene['layers'][0]['color'],'#72ac86')

    def test_rejects_doctype_internal_entities_and_external_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = fixture(root)
            good = path.read_text()
            payloads = [
                '<!DOCTYPE VTKFile [<!ENTITY bomb "BOMB">]>' + good,
                '<?xml version="1.0"?><!DOCTYPE VTKFile [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
                + good.split('?>', 1)[-1],
                '<!DOCTYPE VTKFile [<!ENTITY repeat "a" >]>' + good,
            ]
            for payload in payloads:
                with self.subTest(payload=payload[:95]):
                    path.write_text(payload)
                    with self.assertRaisesRegex(ValueError, 'DTD|entity'):
                        read_polydata(path)

    def test_rejects_multiple_pieces_and_deep_xml(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = fixture(root)
            valid = path.read_text()
            piece = valid.split('<Piece', 1)[1].split('</Piece>', 1)[0]
            path.write_text(valid.replace('</PolyData>', '<Piece' + piece + '</Piece></PolyData>'))
            with self.assertRaisesRegex(ValueError, 'Multiple VTP pieces'):
                read_polydata(path)
            path.write_text('<VTKFile type="PolyData">' + '<Extra>' * 21
                            + '</Extra>' * 21 + '</VTKFile>')
            with self.assertRaisesRegex(ValueError, 'parser limits'):
                read_polydata(path)

    def test_invalid_xml_does_not_abort_entire_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = fixture(root)
            path.write_text('<!DOCTYPE VTKFile [<!ENTITY bomb "x">]><VTKFile type="PolyData"/>')
            result = write_three_preview(root, [('untrusted XML', path.name)], lambda: None)
            self.assertIn('No small VTP', result)
            self.assertFalse((root / 'quick-preview.html').exists())

    def test_missing_layers_do_not_create_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertIn('No small VTP',write_three_preview(root,[('absent','missing.vtp')],lambda:None))
            self.assertFalse((root/'quick-preview.html').exists())


if __name__ == '__main__':
    unittest.main()
