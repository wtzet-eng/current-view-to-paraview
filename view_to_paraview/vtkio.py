"""Small VTK XML writer. No ParaView or VTK Python module needed in QGIS."""
from base64 import b64encode
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree  # nosec B405 - writer only; never parses untrusted XML
import struct
import numpy as np

TYPES = {'f8': 'Float64', 'i8': 'Int64', 'i4': 'Int32', 'u1': 'UInt8'}


def array(parent, name, data, kind, components=1):
    if kind == 'string':
        data = list(data)
        raw = b''.join(str(value).encode('utf-8').replace(b'\x00', b'') + b'\x00' for value in data)
        node = SubElement(parent, 'Array', type='String', NumberOfTuples=str(len(data)))
    else:
        raw = np.asarray(data, dtype='<' + kind).tobytes()
        node = SubElement(parent, 'DataArray', type=TYPES[kind])
    node.set('Name', name)
    node.set('NumberOfComponents', str(components))
    node.set('format', 'binary')
    node.text = b64encode(struct.pack('<Q', len(raw)) + raw).decode('ascii')


def document(kind):
    root = Element('VTKFile', type=kind, version='1.0', byte_order='LittleEndian', header_type='UInt64')
    return root, SubElement(root, kind)


def poly(path, points, family, links, ends, attributes=()):
    root, dataset = document('PolyData')
    names = ('Verts', 'Lines', 'Strips', 'Polys')
    counts = {'NumberOf' + name: str(len(ends) if name == family else 0) for name in names}
    piece = SubElement(dataset, 'Piece', NumberOfPoints=str(len(points)), **counts)
    coords = np.asarray(points,dtype=float).reshape(-1,3)
    array(SubElement(piece, 'PointData'), 'elevation_m', coords[:,2], 'f8')
    cell = SubElement(piece, 'CellData')
    for name, values, kind in attributes:
        array(cell, name, values, kind)
    array(SubElement(piece, 'Points'), 'Points', points, 'f8', 3)
    cells = SubElement(piece, family)
    array(cells, 'connectivity', links, 'i4')
    array(cells, 'offsets', ends, 'i4')
    ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def scene(folder, blocks):
    root, dataset = document('vtkMultiBlockDataSet')
    for i, (name, file) in enumerate(blocks):
        SubElement(dataset, 'DataSet', index=str(i), name=name, file=Path(file).name)
    ElementTree(root).write(folder / 'scene.vtm', encoding='utf-8', xml_declaration=True)
