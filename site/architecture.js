const root = document.getElementById('diagram-root');
const toc = document.getElementById('toc');
const identity = document.getElementById('source-identity');
const repository = 'https://github.com/maoyadongsh/siq-agent-security';

async function fetchFile(path, json = false) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return json ? response.json() : response.text();
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

  const nodes = [];
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
    const pre = document.createElement('pre');
    pre.className = 'mermaid';
    pre.textContent = await fetchFile(download.getAttribute('href'));
    frame.append(pre);
    section.append(title, sources, frame);
    root.append(section);
    nodes.push(pre);
  }

  const mermaid = window.mermaid;
  if (!mermaid) throw new Error('Mermaid 未能加载，请使用源文件链接');
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base', flowchart: { useMaxWidth: false }, state: { useMaxWidth: false } });
  await mermaid.run({ nodes });
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
