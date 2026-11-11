"""Project display preferences for the visible part of the QGIS layer tree."""
import json
import re
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget)

KEY = 'currentViewParaView/display'
PALETTE = ['#69afce', '#eba342', '#5bc099', '#c885b4', '#ddc963', '#999ee1']


def layers_in_tree(canvas):
    visible = {layer.id() for layer in canvas.mapSettings().layers()}
    return [node for node in QgsProject.instance().layerTreeRoot().findLayers()
            if node.layerId() in visible and isinstance(node.layer(), (QgsVectorLayer, QgsRasterLayer))]


def style(node, index):
    parent = node.parent()
    path = []
    while parent and parent.parent():
        path.insert(0, parent.name())
        parent = parent.parent()
    group = ' / '.join(path) or 'Layers'
    result = dict(group=group, color=PALETTE[index % len(PALETTE)], opacity=1.,
                  size=3, radius=0., field='', order=index)
    result.update(json.loads(str(node.layer().customProperty(KEY, '{}'))))
    return result


def exaggeration():
    return QgsProject.instance().readDoubleEntry('CurrentViewParaView', '/verticalScale', 1.)[0]


def spin(low, high, value, decimals):
    widget = QDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


def configure(canvas, parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle('Configure 3D view')
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    layout.addLayout(form)
    z = spin(0.1, 100, exaggeration(), 1)
    form.addRow('Vertical exaggeration (×)', z)
    preset = QPushButton('Apply geological survey preset')
    layout.addWidget(preset)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    panel = QWidget()
    rows = QVBoxLayout(panel)
    scroll.setWidget(panel)
    layout.addWidget(scroll)
    editors = []
    nodes = layers_in_tree(canvas)
    for i, node in enumerate(nodes):
        layer = node.layer()
        settings = style(node, i)
        title = QLabel()
        title.setTextFormat(Qt.PlainText)
        title.setText(layer.name())
        rows.addWidget(title)
        row = QHBoxLayout()
        rows.addLayout(row)
        group = QComboBox()
        group.setEditable(True)
        group.addItems(list(dict.fromkeys(style(n, j)['group'] for j,n in enumerate(nodes))))
        group.setCurrentText(settings['group'])
        row.addWidget(group)
        color = QPushButton(settings['color'])
        def choose(_checked, button=color):
            selected = QColorDialog.getColor(QColor(button.text()), dialog)
            if selected.isValid():
                button.setText(selected.name())
        color.clicked.connect(choose)
        row.addWidget(color)
        opacity = spin(0, 100, settings['opacity'] * 100, 0)
        opacity.setPrefix('Opacity ')
        opacity.setSuffix('%')
        row.addWidget(opacity)
        size = spin(1, 30, settings['size'], 0)
        size.setPrefix('Size ')
        size.setSuffix(' px')
        row.addWidget(size)
        radius = spin(0, 10000, settings['radius'], 2)
        radius.setSpecialValueText('Line')
        radius.setPrefix('Tube ')
        radius.setSuffix(' m')
        radius.setEnabled(isinstance(layer, QgsVectorLayer) and layer.geometryType() == 1)
        row.addWidget(radius)
        field = QComboBox()
        field.addItem('Solid colour', '')
        if isinstance(layer, QgsVectorLayer):
            for name in layer.fields().names():
                field.addItem('Colour by '+name, name)
        field.setCurrentIndex(max(0, field.findData(settings['field'])))
        row.addWidget(field)
        editors.append((layer, group, color, opacity, size, radius, field))
    def apply_preset():
        for layer, group, color, opacity, size, radius, field in editors:
            name = layer.name().lower()
            if isinstance(layer, QgsRasterLayer):
                group.setCurrentText('Geological surfaces')
                opacity.setValue(45)
            elif re.search(r'borehole|^bh[_0-9]|well', name):
                group.setCurrentText('Boreholes')
                if radius.isEnabled():
                    radius.setValue(1)
                size.setValue(7)
                for name in layer.fields().names():
                    if name.casefold() in ("strata", "lithology", "material"):
                        field.setCurrentIndex(field.findData(name))
                        break
            elif 'profile' in name or 'seismic' in name:
                group.setCurrentText('Seismic profiles')
                color.setText('#e88730')
                size.setValue(4)
    preset.clicked.connect(apply_preset)
    copy = QPushButton('Apply colour and opacity to this group')
    source = QComboBox()
    source.addItems([row[0].name() for row in editors])
    def copy_selected():
        if editors:
            _, first, colour, alpha, *_ = editors[source.currentIndex()]
            for _, group, button, opacity, *_ in editors:
                if group.currentText().strip() == first.currentText().strip():
                    button.setText(colour.text())
                    opacity.setValue(alpha.value())
    copy.clicked.connect(copy_selected)
    form.addRow(source, copy)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(900, 550)
    if dialog.exec_() == QDialog.Accepted:
        for layer, group, color, opacity, size, radius, field in editors:
            settings = dict(group=group.currentText().strip() or 'Layers', color=color.text(),
                            opacity=opacity.value()/100, size=size.value(), radius=radius.value(),
                            field=field.currentData())
            layer.setCustomProperty(KEY, json.dumps(settings))
        project = QgsProject.instance()
        project.writeEntryDouble('CurrentViewParaView', '/verticalScale', z.value())
        project.setDirty(True)
