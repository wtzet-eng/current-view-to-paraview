// Supplement Glance's standard controls with the QGIS display groups.
function configureScene(manager, view, layers, initialScale) {
  const panel = document.createElement('details');
  panel.id = 'qgis-scene';
  panel.open = true;
  document.body.append(panel);
  const title = document.createElement('summary');
  title.textContent = 'QGIS 3D view';
  panel.append(title);
  const renderer = view.getRenderer();
  const render = () => manager.renderAllViews();
  let scale = initialScale;
  const groups = new Map();
  const label = document.createElement('label');
  label.textContent = 'Vertical scale × ';
  const factor = document.createElement('input');
  factor.type = 'number';
  factor.min = '0.1';
  factor.max = '100';
  factor.step = '0.1';
  factor.value = scale;
  const reset = document.createElement('button');
  reset.textContent = '1×';
  label.append(factor, reset);
  panel.append(label);
  function resize(value) {
    if (!(value >= .1 && value <= 100)) return;
    scale = value;
    factor.value = value;
    layers.forEach(layer => layer.actor.setScale(1, 1, scale));
    view.resetCamera();
    render();
  }
  factor.onchange = () => resize(factor.valueAsNumber);
  reset.onclick = () => resize(1);
  function checkbox(parent, name) {
    const label = document.createElement('label');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = true;
    label.append(box, document.createTextNode(name));
    parent.append(label);
    return box;
  }
  for (const layer of layers) {
    const style = layer.style;
    const rep = manager.getRepresentation(layer.source, view);
    layer.rep = rep;
    const actor = rep.getActors()[0];
    layer.actor = actor;
    const prop = actor.getProperty();
    actor.setScale(1,1,scale);
    const color = style.color || '#69afce';
    prop.setColor(...[1,3,5].map(i => parseInt(color.slice(i,i+2),16)/255));
    prop.setOpacity(style.opacity ?? 1);
    prop.setLineWidth(style.size || 2);
    prop.setPointSize(style.size || 6);
    const mapper = actor.getMapper();
    if (style.field && layer.source.getDataset().getCellData().getArrayByName('display_rgb')) {
      mapper.setScalarModeToUseCellFieldData();
      mapper.setColorByArrayName('display_rgb');
      mapper.setColorModeToDirectScalars();
      mapper.setScalarVisibility(true);
    } else mapper.setScalarVisibility(false);
    const name = style.group || 'Layers';
    if (!groups.has(name)) {
      const section = document.createElement('fieldset');
      const legend = document.createElement('legend');
      section.append(legend);
      panel.append(section);
      const box = checkbox(legend, name);
      const group = {section, box, members:[]};
      groups.set(name, group);
      box.onchange = () => {
        const visible = box.checked;
        group.members.forEach(m => m.rep.setVisibility(visible));
        render();
      };
    }
    const group = groups.get(name);
    layer.box = checkbox(group.section,layer.name);
    group.members.push(layer);
    const sync = () => {
      let visible = 0;
      for (const m of group.members) {
        m.box.checked = !!m.rep.getVisibility();
        if (m.box.checked) visible++;
      }
      group.box.checked = visible === group.members.length;
      group.box.indeterminate = visible > 0 && !group.box.checked;
    };
    layer.box.onchange = () => { rep.setVisibility(layer.box.checked); render(); };
    rep.onModified(sync);
    sync();
  }
  if (layers.some(layer => layer.points.length)) {
    const result = document.createElement('pre');
    result.textContent = 'Shift-click a log point to inspect it.';
    panel.append(result);
    const api = view.getRenderWindow().getViews()[0];
    const canvas = api.getCanvas();
    canvas.addEventListener('click', event => {
      if (!event.shiftKey) return;
      const bounds = canvas.getBoundingClientRect();
      const [width,height] = api.getSize();
      let nearest, best = 12**2, depth = Infinity;
      for (const layer of layers) {
        if (!layer.rep.getVisibility()) continue;
        for (const [p,id,fields] of layer.points) {
          const [x,y,z] = api.worldToDisplay(p[0],p[1],p[2]*scale,renderer);
          if (z < 0 || z > 1) continue;
          const d = (bounds.left+x*bounds.width/width-event.clientX)**2 +
                    (bounds.bottom-y*bounds.height/height-event.clientY)**2;
          if (d < best || (d === best && z < depth)) {
            nearest = [layer.name, 'ID '+id, 'Z '+p[2]+' m', ...Object.entries(fields).map(([k,v])=>k+' = '+(v??'—'))];
            best = d;
            depth = z;
          }
        }
      }
      result.textContent = nearest ? nearest.join('\n') : 'No visible point within 12 pixels.';
    });
  }
}
