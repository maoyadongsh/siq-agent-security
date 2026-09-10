const root = document.getElementById('diagram-root');
const toc = document.getElementById('toc');
const identity = document.getElementById('source-identity');
const repository = 'https://github.com/maoyadongsh/siq-agent-security';

async function fetchFile(path, json = false) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return json ? response.json() : response.text();
}

function addDiagramControls(canvas, frame, title) {
  const svg = canvas.querySelector('svg');
  if (!svg) return;
  const { width, height } = svg.viewBox.baseVal;
  if (!(width > 0 && height > 0)) return;

  const controls = document.createElement('div');
  controls.className = 'diagram-controls';
  controls.setAttribute('role', 'group');
  controls.setAttribute('aria-label', title + '的查看工具');
  const percentage = document.createElement('output');
  percentage.className = 'diagram-scale';
  percentage.setAttribute('aria-label', '显示比例');
  percentage.setAttribute('aria-live', 'polite');
  let scale = 1;
  let sizing = 'fit';

  function button(label, path, action) {
    const control = document.createElement('button');
    control.type = 'button';
    control.title = label;
    control.setAttribute('aria-label', label);
    if (path) {
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('viewBox', '0 0 24 24');
      icon.setAttribute('aria-hidden', 'true');
      const shape = document.createElementNS(icon.namespaceURI, 'path');
      shape.setAttribute('d', path);
      icon.append(shape);
      control.append(icon);
    } else {
      control.textContent = '1:1';
    }
    control.addEventListener('click', action);
    return control;
  }

  function availableSpace() {
    const style = getComputedStyle(frame);
    const left = parseFloat(style.paddingLeft);
    const top = parseFloat(style.paddingTop);
    return {
      left, top,
      width: frame.clientWidth - left - parseFloat(style.paddingRight),
      height: frame.clientHeight - top - parseFloat(style.paddingBottom),
    };
  }

  function fitScale() {
    const space = availableSpace();
    return Math.min(1, space.width / width, space.height / height);
  }

  function sizeViewport() {
    const style = getComputedStyle(frame);
    const availableWidth = frame.parentElement.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const fittedHeight = height * Math.min(1, availableWidth / width);
    frame.style.setProperty('--diagram-height', `${fittedHeight + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)}px`);
  }

  function resize(next, reset = false) {
    const space = availableSpace();
    const viewport = frame.getBoundingClientRect();
    const before = svg.getBoundingClientRect();
    const centerX = viewport.left + frame.clientLeft + space.left + space.width / 2;
    const centerY = viewport.top + frame.clientTop + space.top + space.height / 2;
    const anchorX = (centerX - before.left) / scale;
    const anchorY = (centerY - before.top) / scale;
    const minimum = Math.min(0.02, fitScale());
    scale = Math.min(3, Math.max(minimum, next));
    svg.style.width = `${width * scale}px`;
    svg.style.height = `${height * scale}px`;
    percentage.textContent = `${Math.round(scale * 100)}%`;
    smaller.disabled = scale <= minimum;
    larger.disabled = scale >= 3;
    const after = svg.getBoundingClientRect();
    frame.scrollLeft = reset ? 0 : frame.scrollLeft + after.left + anchorX * scale - centerX;
    frame.scrollTop = reset ? 0 : frame.scrollTop + after.top + anchorY * scale - centerY;
    frame.classList.toggle('is-pannable', frame.scrollWidth > frame.clientWidth + 1 || frame.scrollHeight > frame.clientHeight + 1);
  }

  function fit() {
    sizing = 'fit';
    resize(fitScale(), true);
    // Reclaim any space freed by the scrollbars after returning from a zoomed view.
    if (fitScale() !== scale) resize(fitScale(), true);
  }

  function zoom(multiplier) {
    sizing = 'manual';
    resize(scale * multiplier);
  }

  const fitButton = button('显示全图', 'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5', fit);
  const original = button('原始尺寸', null, () => {
    sizing = 'manual';
    resize(1, true);
  });
  const smaller = button('缩小', 'M5 12h14', () => zoom(1 / 1.25));
  const larger = button('放大', 'M12 5v14m-7-7h14', () => zoom(1.25));
  const presets = document.createElement('div');
  presets.className = 'diagram-presets';
  presets.append(fitButton, original);
  const zoomControls = document.createElement('div');
  zoomControls.className = 'diagram-zoom';
  zoomControls.append(smaller, percentage, larger);
  controls.append(zoomControls, presets);
  frame.parentElement.append(controls);

  const hint = document.createElement('p');
  hint.className = 'diagram-hint';
  hint.textContent = '默认显示全图；放大后可拖动或用方向键查看细节。';
  frame.parentElement.after(hint);

  let drag;
  frame.addEventListener('pointerdown', (event) => {
    // Touch devices retain native scrolling, including normal page scrolling.
    if (event.pointerType !== 'mouse' || event.button !== 0 || !frame.classList.contains('is-pannable')) return;
    event.preventDefault();
    frame.focus({ preventScroll: true });
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, left: frame.scrollLeft, top: frame.scrollTop };
    frame.setPointerCapture(event.pointerId);
    frame.classList.add('is-dragging');
  });
  frame.addEventListener('pointermove', (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    frame.scrollLeft = drag.left + drag.x - event.clientX;
    frame.scrollTop = drag.top + drag.y - event.clientY;
  });
  function endDrag(event) {
    if (!drag || event.pointerId !== drag.id) return;
    drag = undefined;
    frame.classList.remove('is-dragging');
    if (frame.hasPointerCapture(event.pointerId)) frame.releasePointerCapture(event.pointerId);
  }
  frame.addEventListener('pointerup', endDrag);
  frame.addEventListener('pointercancel', endDrag);
  frame.addEventListener('lostpointercapture', endDrag);

  sizeViewport();
  fit();
  let previousWidth = frame.clientWidth;
  let previousHeight = frame.clientHeight;
  new ResizeObserver(() => {
    sizeViewport();
    const currentWidth = frame.clientWidth;
    const currentHeight = frame.clientHeight;
    if (currentWidth !== previousWidth || currentHeight !== previousHeight) {
      previousWidth = currentWidth;
      previousHeight = currentHeight;
      if (sizing === 'fit') fit();
      else resize(scale);
    }
  }).observe(frame);
}

try {
  const meta = await fetchFile('./diagrams/index.json', true);
  if (!/^[a-f0-9]{40}$/.test(meta.source_sha)) throw new Error('缺少可验证的源码提交身份');
  identity.textContent = '生成依据：';
  const commit = document.createElement('a');
  commit.href = `${repository}/commit/${meta.source_sha}`;
  commit.textContent = meta.source_sha.slice(0, 12);
  identity.append(commit, meta.source_dirty ? ' · 本地工作区含未提交修改' : ' · 干净 checkout');
  document.getElementById('facts-body').textContent = [
    'cli: ' + meta.cli.join(', '),
    'http: ' + meta.http_routes.join(', '),
    'packages: ' + meta.packages.join(', '),
    'adapters: ' + meta.adapters.join(', '),
    'grant: ' + meta.grant_transitions.map((e) => e.from + ' → ' + e.to).join(', '),
    'policy-exec: ' + meta.policy_exec.map((e) => e.verdict + ' → ' + e.decision).join(', '),
  ].join('\n\n');

  const diagrams = [];
  for (const diagram of meta.diagrams) {
    const nav = document.createElement('a');
    nav.href = '#' + diagram.id;
    nav.textContent = diagram.title;
    toc.append(nav);
    const section = document.createElement('section');
    section.className = 'section';
    section.id = diagram.id;
    const title = document.createElement('h2');
    title.textContent = diagram.title;
    const sources = document.createElement('p');
    sources.className = 'sources';
    sources.textContent = '提取范围：' + diagram.sources.join(' · ') + ' · ';
    const download = document.createElement('a');
    download.href = './diagrams/' + diagram.file;
    download.textContent = '查看 Mermaid 源文件';
    sources.append(download);
    const viewer = document.createElement('div');
    viewer.className = 'diagram-viewer';
    const frame = document.createElement('div');
    frame.className = 'diagram-frame';
    frame.tabIndex = 0;
    frame.setAttribute('role', 'region');
    frame.setAttribute('aria-label', diagram.title + '，可滚动查看');
    // A code-block font changes label widths after Mermaid measures them.
    // Keep the rendered diagram in the same font context as the renderer.
    const canvas = document.createElement('div');
    canvas.className = 'mermaid diagram-canvas';
    canvas.textContent = await fetchFile(download.getAttribute('href'));
    canvas.style.visibility = 'hidden';
    frame.append(canvas);
    viewer.append(frame);
    section.append(title, sources, viewer);
    root.append(section);
    diagrams.push({ canvas, frame, title: diagram.title });
  }

  const mermaid = window.mermaid;
  if (!mermaid) throw new Error('Mermaid 未能加载，请使用源文件链接');
  // 暖纸编辑风主题：象牙底、米色节点、墨蓝文字、深金连线
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme: 'base',
    themeVariables: {
      background: '#fdfcf9',
      mainBkg: '#f3eee2',
      secondBkg: '#faf7f0',
      tertiaryColor: '#f7f4ee',
      primaryColor: '#f3eee2',
      primaryBorderColor: '#d8d0c6',
      primaryTextColor: '#12203e',
      secondaryColor: '#faf7f0',
      secondaryBorderColor: '#e8e1d4',
      secondaryTextColor: '#12203e',
      tertiaryBorderColor: '#e8e1d4',
      tertiaryTextColor: '#12203e',
      lineColor: '#7c5a0c',
      textColor: '#12203e',
      nodeTextColor: '#12203e',
      edgeLabelBackground: '#fdfcf9',
      clusterBkg: '#faf7f0',
      clusterBorder: '#e8e1d4',
      titleColor: '#001840',
      fontFamily: getComputedStyle(root).fontFamily,
    },
    flowchart: { useMaxWidth: false, nodeSpacing: 20, rankSpacing: 28, padding: 10 },
    state: { useMaxWidth: false },
  });
  await document.fonts.ready;
  await mermaid.run({ nodes: diagrams.map(({ canvas }) => canvas) });
  for (const { canvas, frame, title } of diagrams) {
    canvas.style.visibility = '';
    addDiagramControls(canvas, frame, title);
  }
} catch (error) {
  if (identity.textContent.startsWith('正在')) identity.textContent = '暂时无法读取源码身份。';
  const message = document.createElement('p');
  message.className = 'note';
  message.setAttribute('role', 'alert');
  message.textContent = '图未能完整渲染：' + String(error.message || error) + '。请使用 Mermaid 源文件或图索引。';
  const index = document.createElement('a');
  index.href = './diagrams/index.json';
  index.textContent = '打开图索引';
  root.append(message, index);
}
