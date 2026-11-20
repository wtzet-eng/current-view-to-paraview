"""Optional, bounded Three.js browser preview of an already exported VTP scene.

The preview is deliberately separate from ParaView and offline Kitware Glance.
It does not upload geometry; the browser retrieves a pinned JavaScript library
from jsDelivr only when the user explicitly opens the Three.js preview.
For confidential/offline scenes, use the bundled Glance viewer instead.
"""
from base64 import b64decode
from pathlib import Path
import json
import math
import re
import struct
import xml.etree.ElementTree as ET

MAX_VTP_BYTES = 12 * 1024 * 1024
MAX_POINTS_PER_LAYER = 100_000
MAX_POINTS_TOTAL = 160_000
MAX_ELEMENTS_TOTAL = 650_000
MAX_OUTPUT_BYTES = 20 * 1024 * 1024
THREE_VERSION = "0.187.0"

HTML_HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'unsafe-inline'; connect-src 'none'; img-src data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'">
<title>GroundSurf | Quick 3D preview</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#212121;color:#e4ede6;font:14px system-ui,sans-serif;overflow:hidden}
canvas{display:block}aside{position:absolute;z-index:2;top:16px;left:16px;width:min(310px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;background:#1b2621ef;border:1px solid #4d7258;border-radius:12px;padding:18px;box-shadow:0 10px 40px #0008}
h1{font-size:19px;margin:0 0 5px;color:#a8d5ac}p{line-height:1.5;color:#b9c9bc}small{color:#8ca995}
label{display:block;padding:7px 0;border-top:1px solid #344a3b;word-break:break-word}
input{accent-color:#80bc88;vertical-align:middle;margin-right:10px}
button{background:#315c40;color:#f0fff1;border:1px solid #6aa47b;border-radius:6px;padding:8px 12px;cursor:pointer}
.status{color:#bbdebd;font-size:12px}#legend{margin:10px 0}
#help{position:absolute;bottom:12px;right:12px;color:#b6c5b9;background:#19251fbd;padding:7px;border-radius:5px}
</style></head><body><aside><h1>GroundSurf · Quick 3D</h1>
<p>Lightweight local scene preview. Rotate by dragging; scroll to zoom. For detailed work, open the same snapshot in ParaView or offline Kitware Glance.</p>
<div id="status" class="status">Loading Three.js… (internet required for this preview only)</div>
<div id="legend"></div><button id="reset" type="button">Reset view</button>
<p><small>Preview geometry is simplified for speed, not a design model. Data stay in this HTML file; a pinned Three.js module is downloaded from jsDelivr when opened. Use bundled Glance for confidential/offline work.</small></p>
</aside><div id="view"></div><div id="help">Drag · rotate &nbsp; Scroll · zoom</div>
<script>window.addEventListener('error',()=>{document.querySelector('#status').textContent='Three.js unavailable. Check connectivity/WebGL, or use offline Glance.'});</script>
<script id="scene-data" type="application/json">"""

HTML_TAIL = """
</script>
<script type="module">
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.187.0/build/three.module.js';
const sceneData=JSON.parse(document.getElementById('scene-data').textContent);
const scene=new THREE.Scene();scene.background=new THREE.Color('#212121');
const camera=new THREE.PerspectiveCamera(47,innerWidth/innerHeight,0.1,1e9);
camera.up.set(0,0,1);
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});
renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));
renderer.setSize(innerWidth,innerHeight);
document.getElementById('view').appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff,0x516758,2.25));
const directional=new THREE.DirectionalLight(0xffffff,2.0);directional.position.set(1,-2,3);scene.add(directional);
const aggregate=new THREE.Group();scene.add(aggregate);
const bounds=new THREE.Box3();
const legend=document.getElementById('legend');
for(let i=0;i<sceneData.layers.length;i++){
 const layer=sceneData.layers[i],points=layer.points,index=layer.indices;
 const geometry=new THREE.BufferGeometry();
 geometry.setAttribute('position',new THREE.Float32BufferAttribute(points,3));
 if(index.length)geometry.setIndex(index);
 const color=new THREE.Color(layer.color||(['#82ba95','#b5c7ac','#80c4d1','#dfb56e'][i%4]));
 let object;
 if(layer.family==='Polys'){
   geometry.computeVertexNormals();
   object=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,side:THREE.DoubleSide,transparent:true,opacity:0.91,roughness:0.87}));
 }else if(layer.family==='Lines'){
   object=new THREE.LineSegments(geometry,new THREE.LineBasicMaterial({color}));
 }else{
   object=new THREE.Points(geometry,new THREE.PointsMaterial({color,size:4,sizeAttenuation:false}));
 }
 object.name=layer.name;aggregate.add(object);
 const row=document.createElement('label'),cb=document.createElement('input');
 cb.type='checkbox';cb.checked=true;cb.addEventListener('change',()=>{object.visible=cb.checked;});
 row.append(cb,document.createTextNode(layer.name));legend.append(row);
 bounds.expandByObject(object);
}
if(!sceneData.layers.length)throw Error('No renderable layers');
const center=bounds.getCenter(new THREE.Vector3()),size=bounds.getSize(new THREE.Vector3()).length()||1;
aggregate.position.sub(center);
const target=new THREE.Vector3(0,0,0);
let distance=Math.max(size*1.35,1),azimuth=-0.8,elevation=0.62;
function cameraUpdate(){
 elevation=Math.max(-1.45,Math.min(1.45,elevation));
 camera.position.set(distance*Math.cos(elevation)*Math.cos(azimuth),distance*Math.cos(elevation)*Math.sin(azimuth),distance*Math.sin(elevation));
 camera.lookAt(target);renderer.render(scene,camera);
}
const reset=()=>{distance=Math.max(size*1.35,1);azimuth=-0.8;elevation=0.62;cameraUpdate();};
document.getElementById('reset').addEventListener('click',reset);
const canvas=renderer.domElement;let previous=null;
canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;previous=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(!previous)return;azimuth+=(e.clientX-previous[0])*0.006;elevation+=(e.clientY-previous[1])*0.006;previous=[e.clientX,e.clientY];cameraUpdate();});
canvas.addEventListener('pointerup',()=>{previous=null;});canvas.addEventListener('pointercancel',()=>{previous=null;});
canvas.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(size*0.04,Math.min(size*100,distance*Math.exp(e.deltaY*0.001)));cameraUpdate();},{passive:false});
window.addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);cameraUpdate();});
document.getElementById('status').textContent=sceneData.layers.length+' layer(s) · '+sceneData.points.toLocaleString()+' vertices'+(sceneData.skipped.length?' · Preview omitted: '+sceneData.skipped.join(', '):'');
reset();
</script></body></html>
"""


def _typed_array(piece, section, name, kind):
    target = piece.find('./' + section + '/DataArray[@Name="' + name + '"]')
    if target is None and section == 'Points' and name == 'Points':
        target = piece.find('./Points/DataArray')
    if target is None or target.get('format') != 'binary':
        raise ValueError('Missing or non-binary VTP array: ' + section + '/' + name)
    raw = b64decode((target.text or '').strip(), validate=True)
    if len(raw) < 8:
        raise ValueError('Truncated VTP array')
    nbytes = struct.unpack_from('<Q', raw)[0]
    data = raw[8:]
    expected_type = {'d': 'Float64', 'i': 'Int32'}[kind]
    if target.get('type') != expected_type or len(data) != nbytes or nbytes % struct.calcsize(kind):
        raise ValueError('Invalid VTP type or byte count')
    return [v[0] for v in struct.iter_unpack('<' + kind, data)]


def read_polydata(path, scale=1.0):
    """Extract only VTK geometry (no labels, source fields or remote calls)."""
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_VTP_BYTES:
        raise ValueError('Layer is not a local lightweight VTP file')
    doc = ET.parse(path)
    piece = doc.find('./PolyData/Piece')
    if piece is None:
        raise ValueError('Not VTK XML PolyData')
    count = int(piece.get('NumberOfPoints', '0'))
    if count <= 0 or count > MAX_POINTS_PER_LAYER:
        raise ValueError('Point budget exceeded')
    values = _typed_array(piece, 'Points', 'Points', 'd')
    if len(values) != count * 3 or not all(math.isfinite(x) and abs(x) < 1e9 for x in values):
        raise ValueError('Invalid VTP point coordinates')
    if not math.isfinite(scale) or not 0 < scale <= 1000:
        raise ValueError('Invalid vertical exaggeration')
    family = next((kind for kind in ('Polys', 'Lines', 'Verts')
                   if int(piece.get('NumberOf' + kind, '0')) > 0), None)
    if not family:
        raise ValueError('No supported polydata cells')
    connectivity = _typed_array(piece, family, 'connectivity', 'i')
    offsets = _typed_array(piece, family, 'offsets', 'i')
    indices = []
    start = 0
    for end in offsets:
        if end <= start or end > len(connectivity):
            raise ValueError('Invalid VTP cell offset')
        cell = connectivity[start:end]
        if any(index < 0 or index >= count for index in cell):
            raise ValueError('VTP connectivity index out of range')
        if family == 'Polys':
            if len(cell) >= 3:
                for j in range(1, len(cell) - 1):
                    indices.extend((cell[0], cell[j], cell[j + 1]))
        elif family == 'Lines':
            for j in range(1, len(cell)):
                indices.extend((cell[j - 1], cell[j]))
        else:
            indices.extend(cell)
        start = end
        if len(indices) > MAX_ELEMENTS_TOTAL:
            raise ValueError('Preview primitive budget exceeded')
    if start != len(connectivity):
        raise ValueError('Orphaned connectivity values')
    points = [round(values[i] * (scale if i % 3 == 2 else 1), 3) for i in range(len(values))]
    return dict(family=family, points=points, indices=indices), count


def write_three_preview(folder, blocks, check, styles=None, scale=1.0):
    """Create local quick-preview.html; report failure without damaging VTK export."""
    folder = Path(folder)
    styles = styles or {}
    layers, skipped, total = [], [], 0
    try:
        for name, filename in blocks:
            check()
            style = styles.get(filename, {})
            selected = Path(style.get('tube_file', filename))
            if selected.name != str(selected) or selected.suffix.lower() != '.vtp':
                skipped.append(name)
                continue
            try:
                geometry, count = read_polydata(folder / selected, scale)
                if total + count > MAX_POINTS_TOTAL:
                    raise ValueError('Aggregate point budget')
                total += count
                geometry.update(name=str(name)[:150], color=style.get('color', '#80b78c'))
                if not isinstance(geometry['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', geometry['color']):
                    geometry['color'] = '#80b78c'
                layers.append(geometry)
            except (ValueError, OSError, ET.ParseError):
                skipped.append(name)
        if not layers:
            return 'No small VTP layers suitable for the Three.js preview. Use offline Glance or desktop ParaView.'
        payload = json.dumps(dict(layers=layers, skipped=skipped, points=total), ensure_ascii=True,
                             separators=(',', ':')).replace('<', r'\u003c')
        if len(payload.encode('utf-8')) > MAX_OUTPUT_BYTES:
            return 'Three.js preview exceeds 20 MiB. Use offline Glance or ParaView.'
        target = folder / 'quick-preview.html'
        target.write_text(HTML_HEAD + payload + HTML_TAIL, encoding='utf-8')
    except (OSError, TypeError, ValueError) as exc:
        (folder / 'quick-preview.html').unlink(missing_ok=True)
        return 'Could not prepare Three.js preview: ' + str(exc)
    return ''
