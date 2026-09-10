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
  controls.setAttribute('aria-label', title + '的显示比例');
  const percentage = document.createElement('output');
  percentage.className = 'diagram-scale';
  percentage.setAttribute('aria-live', 'polite');
  let scale = 1;
  let sizing = 'readable';

  function button(label, action) {
    const control = document.createElement('button');
    control.type = 'button';
    control.textContent = label;
    control.addEventListener('click', action);
    return control;
  }

  function resize(next, reset = false) {
    const centerX = (frame.scrollLeft + frame.clientWidth / 2) / scale;
    const centerY = (frame.scrollTop + frame.clientHeight / 2) / scale;
    scale = Math.min(3, Math.max(0.02, next));
    svg.style.width = `${width * scale}px`;
    svg.style.height = `${height * scale}px`;
    percentage.textContent = `${Math.round(scale * 100)}%`;
    smaller.disabled = scale <= 0.02;
    larger.disabled = scale >= 3;
    frame.scrollLeft = reset ? 0 : centerX * scale - frame.clientWidth / 2;
    frame.scrollTop = reset ? 0 : centerY * scale - frame.clientHeight / 2;
  }

  function widthScale() {
    const style = getComputedStyle(frame);
    const available = frame.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    return Math.min(1, available / width);
  }

  function fit() {
    sizing = 'fit';
    resize(widthScale(), true);
  }

  function zoom(multiplier) {
    sizing = 'manual';
    resize(scale * multiplier);
  }

  const fitButton = button('适应宽度', fit);
  const original = button('原始尺寸', () => {
    sizing = 'manual';
    resize(1, true);
  });
  const smaller = button('缩小', () => zoom(1 / 1.25));
  const larger = button('放大', () => zoom(1.25));
  const presets = document.createElement('div');
  presets.className = 'diagram-presets';
  presets.append(fitButton, original);
  const zoomControls = document.createElement('div');
  zoomControls.className = 'diagram-zoom';
  zoomControls.append(smaller, percentage, larger);
  controls.append(presets, zoomControls);
  frame.before(controls);

  const hint = document.createElement('p');
  hint.className = 'diagram-hint';
  hint.textContent = '适应宽度可看整体，原始尺寸可看细节；聚焦图形后可用方向键滚动。';
  frame.after(hint);
  // Dense graphs need a readable starting scale; fitting the entire inventory
  // into a phone screen would otherwise reduce its labels to a few pixels.
  resize(Math.max(0.75, widthScale()), true);
  let previousWidth = frame.clientWidth;
  new ResizeObserver(() => {
    const currentWidth = frame.clientWidth;
    if (currentWidth !== previousWidth) {
      previousWidth = currentWidth;
      if (sizing === 'fit') fit();
      if (sizing === 'readable') resize(Math.max(0.75, widthScale()), true);
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
    section.append(title, sources, frame);
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
