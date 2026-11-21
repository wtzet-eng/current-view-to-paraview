"""Small VTK XML writer. No ParaView or VTK Python module needed in QGIS."""
from base64 import b64encode
from pathlib import Path
from contextlib import contextmanager
from qgis.PyQt.QtCore import QIODevice, QSaveFile, QXmlStreamWriter
import struct
import numpy as np

TYPES = {'f8': 'Float64', 'i8': 'Int64', 'i4': 'Int32', 'u1': 'UInt8'}


@contextmanager
def element(writer, tag, **attributes):
    writer.writeStartElement(tag)
    for key, value in attributes.items():
        writer.writeAttribute(key, value)
    yield
    writer.writeEndElement()


@contextmanager
def document(path, kind):
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    writer = QXmlStreamWriter(output)
    writer.writeStartDocument()
    with element(writer, 'VTKFile', type=kind, version='1.0',
                 byte_order='LittleEndian', header_type='UInt64'):
        with element(writer, kind):
            yield writer
    writer.writeEndDocument()
    if writer.hasError() or not output.commit():
        raise OSError(f'Could not write {path}: {output.errorString()}')


def array(parent, name, data, kind, components=1):
    if kind == 'string':
        data = list(data)
        raw = b''.join(str(value).encode('utf-8').replace(b'\x00', b'') + b'\x00' for value in data)
        tag = 'Array'
        attributes = dict(type='String', NumberOfTuples=str(len(data)))
    else:
        raw = np.asarray(data, dtype='<' + kind).tobytes()
        tag = 'DataArray'
        attributes = dict(type=TYPES[kind])
    with element(parent, tag, Name=name, NumberOfComponents=str(components), format='binary', **attributes):
        parent.writeCharacters(b64encode(struct.pack('<Q', len(raw)) + raw).decode('ascii'))


def poly(path, points, family, links, ends, attributes=(), point_attributes=()):
    names = ('Verts', 'Lines', 'Strips', 'Polys')
    counts = {'NumberOf' + name: str(len(ends) if name == family else 0) for name in names}
    coords = np.asarray(points, dtype=float).reshape(-1, 3)
    with document(Path(path), 'PolyData') as writer:
        with element(writer, 'Piece', NumberOfPoints=str(len(points)), **counts):
            with element(writer, 'PointData'):
                array(writer, 'elevation_m', coords[:, 2], 'f8')
                for attribute in point_attributes:
                    array(writer, *attribute)
            with element(writer, 'CellData'):
                for attribute in attributes:
                    array(writer, *attribute)
            with element(writer, 'Points'):
                array(writer, 'Points', points, 'f8', 3)
            with element(writer, family):
                array(writer, 'connectivity', links, 'i4')
                array(writer, 'offsets', ends, 'i4')


def scene(folder, blocks, styles=None):
    groups = {}
    entries = []
    for name, file in blocks:
        group = (styles or {}).get(file, {}).get('group')
        dataset = dict(name=name, file=Path(file).name)
        if group:
            if group not in groups:
                groups[group] = []
                entries.append((group, groups[group]))
            groups[group].append(dataset)
        else:
            entries.append((None, dataset))

    with document(folder / 'scene.vtm', 'vtkMultiBlockDataSet') as writer:
        for index, (group, entry) in enumerate(entries):
            if group:
                with element(writer, 'Block', index=str(index), name=group):
                    for child_index, dataset in enumerate(entry):
                        with element(writer, 'DataSet', index=str(child_index), **dataset):
                            pass
            else:
                with element(writer, 'DataSet', index=str(index), **entry):
                    pass
