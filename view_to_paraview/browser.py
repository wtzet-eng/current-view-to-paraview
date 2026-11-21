"""Build a portable, offline Glance page from this export's VTP blocks."""
from base64 import b64encode
from html import escape
from pathlib import Path
import json
import re

ASSETS = Path(__file__).with_name('glance')
# The larger VTK export remains available when a browser copy would be costly.
BROWSER_LIMIT = 96 * 1024**2
HEADER = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; worker-src blob:; connect-src 'none'">
<title>QGIS current view · Kitware Glance</title>
<style>html,body,#root-container{width:100%;height:100%;margin:0}
#qgis-scene{position:fixed;right:8px;bottom:8px;z-index:90;font:14px sans-serif;color:#203347;background:white;padding:8px;max-height:55vh;max-width:45vw;overflow:auto}#qgis-scene label{display:block}#qgis-scene input[type=number]{width:5em}#qgis-scene pre{white-space:pre-wrap}
#loading{position:fixed;z-index:99;top:1rem;left:1rem;background:white;color:#203347;padding:.7rem 1rem;font:15px sans-serif}</style>
"""
LOADER = """
<script>
async function openSnapshot() {
  const status = document.querySelector('#loading');
  try {
    const viewer = Glance.createViewer(document.querySelector('#root-container'));
    viewer.setSetting('noHistory', true);
    viewer.showApp();
    const manager = viewer.proxyManager;
    const sources = [];
    const layers = [];
    for (const node of document.querySelectorAll('script[data-layer]')) {
      status.textContent = 'Opening ' + node.dataset.layer;
      const raw = atob(node.textContent);
      const bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
      const file = new File([bytes], 'layer.vtp');
      const readers = await Glance.loadFiles([file]);
      readers[0].name = node.dataset.layer;
      sources.push(...Glance.registerReadersToProxyManager(readers, manager));
      const info = node.previousElementSibling;
      layers.push({source:sources[sources.length-1],name:node.dataset.layer,
        style:JSON.parse(node.dataset.style),points:info?.className === 'point-info' ? JSON.parse(info.textContent) : []});
      node.remove();
    }
    for (const view of manager.getViews()) {
      if (view.isA('vtkViewProxy') && view.getProxyName() === 'View3D') {
        configureScene(manager,view,layers,Number(document.body.dataset.scale));
        const camera = view.getRenderer().getActiveCamera();
        camera.setPosition(1,-1,0.85);
        camera.setFocalPoint(0,0,0);
        camera.setViewUp(0,0,1);
        view.resetCamera();
      }
    }
    manager.renderAllViews();
    if (!sources.length || sources.some(source => !source || !source.getDataset())) {
      throw new Error('A layer could not be read.');
    }
    document.documentElement.dataset.layersLoaded = String(sources.length);
    status.remove();
  } catch (error) {
    status.textContent = 'Could not display the scene. ' + error.message +
      ' Try a WebGL-enabled browser. The original VTK files are in this snapshot folder.';
  }
}
openSnapshot();
</script></body></html>
"""


def write_browser_view(folder, blocks, check, styles=None, scale=1):
    styles = styles or {}
    inputs = []
    for _, filename in blocks:
        style = styles.get(filename, {})
        inputs.append(folder / style.get('tube_file', filename))
        if 'points_file' in style:
            inputs.append(folder / style['points_file'])
    if sum(p.stat().st_size for p in inputs) > BROWSER_LIMIT:
        return 'Browser preview exceeds the 96 MiB input limit. Zoom in or omit layers. The VTK scene was saved.'
    destination = folder / 'view.html'
    try:
        with destination.open('w', encoding='utf-8', newline='\n') as output:
            output.write(HEADER)
            css = next(ASSETS.glob('vendors.*.css')).read_text(encoding='utf-8')
            # Use system text fonts and embed the icon font so the page stays portable.
            css = re.sub(r'@font-face\s*\{[^}]*\}', '', css)
            icon = b64encode((ASSETS / 'icon.woff2').read_bytes()).decode('ascii')
            output.write('<style>@font-face{font-family:"Material Design Icons";src:url(data:font/woff2;base64,')
            output.write(icon + ') format("woff2")}'+css)
            output.write(next(ASSETS.glob('glance.*.css')).read_text(encoding='utf-8')+'</style>')
            for pattern in ('runtime.*.js','vendors.*.js','glance.*.js'):
                check()
                script = next(ASSETS.glob(pattern)).read_text(encoding='utf-8')
                output.write('<script>'+re.sub(r'</script',r'<\\/script',script,flags=re.I)+'</script>')
            output.write('<script>'+Path(__file__).with_name('scene_controls.js').read_text(encoding='utf-8')+'</script>')
            output.write(f'</head><body data-scale="{float(scale)}"><div id="root-container"></div><div id="loading">Opening scene…</div>')
            notices = [path.read_text(encoding='utf-8') for path in sorted(ASSETS.glob('*.txt'))]
            output.write('<template id="third-party-notices">'+escape('\n'.join(notices))+'</template>')
            for name, filename in blocks:
                style = styles.get(filename, {})
                if 'points_file' in style:
                    points = (folder/style['points_file']).read_text(encoding='utf-8').replace('<',r'\u003c')
                    output.write('<script type="application/json" class="point-info">'+points+'</script>')
                filename = style.get('tube_file', filename)
                output.write('<script type="application/octet-stream" data-style="'+escape(json.dumps(style),quote=True)+'" data-layer="'+escape(name,quote=True)+'">')
                with (folder / filename).open('rb') as source:
                    # Each full chunk is divisible by three, so the stream has one base64 padding boundary.
                    for chunk in iter(lambda: source.read(3*65536), b''):
                        check()
                        output.write(b64encode(chunk).decode('ascii'))
                output.write('</script>')
            output.write(LOADER)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        return f'Could not write the browser preview: {exc}. The VTK scene was saved.'
    return ''
