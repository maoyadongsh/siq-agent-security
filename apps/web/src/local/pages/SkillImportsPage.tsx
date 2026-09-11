import ImportPermissionPanel from "../components/ImportPermissionPanel";
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import { domainLabel, severityLabel, severityTag, verdictLabel, verdictTag } from '../format';
import { importIdPattern, newImportId, skillImportErrorText } from '../skillImports';
import type { SkillImportListItem, SkillImportRequest, SkillImportResult, SkillImportSourceKind } from '../types';

const sourceLabel = (kind: string) => kind === 'https_zip' ? 'HTTPS ZIP' : kind === 'local_zip' ? '本地 ZIP' : '本地目录';
const formatTime = (time: string) => new Date(time).toLocaleString();
const bytesLabel = (bytes: number) => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MiB` : bytes >= 1024 ? `${(bytes / 1024).toFixed(1)} KiB` : `${bytes} B`;

export default function SkillImportsPage() {
  const { actorId, setActorId, status } = useLocalSession();
  const [search, setSearch] = useSearchParams();
  const selected = search.get('import') ?? '';
  const [path, setPath] = useState('');
  const [url, setUrl] = useState('');
  const [archivePath, setArchivePath] = useState('');
  const [expectedSHA256, setExpectedSHA256] = useState('');
  const [kind, setKind] = useState<SkillImportSourceKind>('local_dir');
  const [items, setItems] = useState<SkillImportListItem[]>([]);
  const [result, setResult] = useState<SkillImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'read' | 'create' | null>('read');
  const [refresh, setRefresh] = useState(0);
  const request = useRef<SkillImportRequest | null>(null);
  const active = useRef<AbortController | null>(null);
  const creating = useRef(false);

  useEffect(() => () => { active.current?.abort(); }, []);

  useEffect(() => {
    // The submit handler owns this query change and will display its response.
    if (creating.current && request.current?.import_id === selected) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const current = () => active.current === controller && !controller.signal.aborted;
    setBusy('read'); setResult(null); setError(null); setHistoryError(null);
    void (async () => {
      try {
        const list = await localApi.skillImports(controller.signal);
        if (!current()) return;
        setItems(list.items);
      } catch (err) {
        if (!current()) return;
        setItems([]); setHistoryError(skillImportErrorText(err));
      }
      if (selected && current()) {
        if (!importIdPattern.test(selected)) { setError('导入记录编号无效。请从历史记录打开，或开始新的导入。'); return; }
        try {
          const detail = await localApi.skillImport(selected, controller.signal);
          if (current()) setResult(detail);
        } catch (err) { if (current()) setError(skillImportErrorText(err)); }
      }
    })().finally(() => { if (current()) setBusy(null); });
    return () => { controller.abort(); };
  }, [selected, refresh]);

  const create = async (body: SkillImportRequest) => {
    if (creating.current || busy) return;
    creating.current = true;
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    const current = () => active.current === controller && !controller.signal.aborted;
    request.current = body;
    setBusy('create'); setResult(null); setError(null); setHistoryError(null);
    setSearch({ import: body.import_id });
    try {
      const detail = await localApi.createSkillImport(body, controller.signal);
      if (!current()) return;
      setResult(detail);
      try {
        const list = await localApi.skillImports(controller.signal);
        if (current()) setItems(list.items);
      } catch (err) { if (current()) setHistoryError(skillImportErrorText(err)); }
    } catch (err) { if (current()) setError(skillImportErrorText(err)); }
    finally { creating.current = false; if (current()) setBusy(null); }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || creating.current || !(kind === 'https_zip' ? url.trim() : path.trim()) || !actorId.trim()) return;
    if (selected) return;
    if (kind === 'https_zip') {
      void create({ schema_version: 'local-skill-import-remote-create/v1', import_id: newImportId(), url: url.trim(), archive_path: archivePath.trim(), expected_sha256: expectedSHA256.trim(), actor_id: actorId.trim() });
      return;
    }
    void create({ schema_version: 'local-skill-import-create/v1', import_id: newImportId(), source_kind: kind, path: path.trim(), actor_id: actorId.trim() });
  };
  const reset = () => { request.current = null; setSearch({}); setResult(null); setError(null); };
  const pending = request.current?.import_id === selected ? request.current : null;
  const locked = !!busy || !!selected;

  return <section className="local-imports-page">
    <PageHeader title="导入 Skill" kicker="AGENTSHIELD" icon="shield"
      description="先保存一份独立副本并检查内容，了解它声明的权限需求。导入不会自动授权或安装到智能体。"
      connection={historyError ? 'disconnected' : status ? 'connected' : 'loading'} connectionError={historyError}
      actions={<><Link className="btn btn-sm" to="/installed-skills">查看已安装 Skill</Link><button type="button" className="btn btn-sm" disabled={!!busy} onClick={() => setRefresh((n) => n + 1)}>刷新记录</button></>} />
    <div className="import-columns">
      <section className="panel import-panel" aria-labelledby="import-source-heading">
        <h2 id="import-source-heading">{selected ? '当前导入' : '添加 Skill'}</h2>
        <p className="page-desc">从本机目录、ZIP 或 HTTPS 下载链接添加 Skill。所选 Skill 目录须包含 SKILL.md。</p>
        {selected ? <p className="import-identity">导入编号 <code>{selected}</code></p> : null}
        {!selected ? <form onSubmit={submit}>
          <fieldset disabled={locked} className="import-fields">
            <div className="field"><label htmlFor="import-kind">来源类型</label>
              <select id="import-kind" value={kind} onChange={(e) => setKind(e.target.value as SkillImportSourceKind)}>
                <option value="local_dir">本地目录</option><option value="local_zip">本地 ZIP</option><option value="https_zip">HTTPS ZIP 下载链接</option>
              </select></div>
            {kind === 'https_zip' ? <>
              <div className="field"><label htmlFor="import-url">HTTPS ZIP 下载链接</label>
                <input id="import-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} required maxLength={4096} autoComplete="off" spellCheck={false} placeholder="https://example.com/skill.zip" aria-describedby="import-url-help" />
                <small id="import-url-help" className="muted-text">填写直接下载 ZIP 的公网链接，暂不支持仓库首页或需要登录的来源。</small></div>
              <div className="field"><label htmlFor="import-archive-path">ZIP 内的 Skill 目录（可选）</label>
                <input id="import-archive-path" value={archivePath} onChange={(e) => setArchivePath(e.target.value)} maxLength={512} autoComplete="off" spellCheck={false} placeholder="例如 repo-main/skills/my-skill" />
                <small className="muted-text">SKILL.md 在 ZIP 根层时留空。</small></div>
              <div className="field"><label htmlFor="import-sha256">预期 SHA256（可选）</label>
                <input id="import-sha256" value={expectedSHA256} onChange={(e) => setExpectedSHA256(e.target.value)} pattern="[a-f0-9]{64}" maxLength={64} autoComplete="off" spellCheck={false} />
                <small className="muted-text">填写来源方提供的 64 位小写摘要；不一致时停止导入。</small></div>
            </> : <div className="field"><label htmlFor="import-path">本机绝对路径</label>
              <input id="import-path" value={path} onChange={(e) => setPath(e.target.value)} required maxLength={4096} autoComplete="off" spellCheck={false}
                placeholder={kind === 'local_zip' ? '例如 /home/me/Downloads/skill.zip' : '例如 /home/me/skills/my-skill'} aria-describedby="import-path-help" />
              <small id="import-path-help" className="muted-text">Windows 可填写 C:\Users\你的用户名\Downloads\my-skill；此处填写路径，不上传文件。</small></div>}
            <div className="field"><label htmlFor="import-actor">操作者</label>
              <input id="import-actor" value={actorId} onChange={(e) => setActorId(e.target.value)} required maxLength={128} autoComplete="off" /></div>
          </fieldset>
          {!selected ? <button type="submit" className="btn btn-primary" disabled={!!busy || !(kind === 'https_zip' ? url.trim() : path.trim()) || !actorId.trim()}>导入并检查</button> : null}
        </form> : null}
        {busy ? <p role="status" className="page-desc">{busy === 'create' ? '正在保存副本并检查…' : '正在读取记录并校验…'}</p> : null}
        {error ? <p role="alert" className="action-error">{error}</p> : null}
        {selected ? <div className="import-actions">
          <button type="button" className="btn" disabled={!!busy} onClick={() => setRefresh((n) => n + 1)}>查询导入结果</button>
          {error && pending ? <button type="button" className="btn" disabled={!!busy} onClick={() => void create(pending)}>以原请求重试</button> : null}
          <button type="button" className="btn" disabled={!!busy} onClick={reset}>开始新的导入</button>
        </div> : null}
      </section>
      <section className="panel import-panel" aria-labelledby="import-history-heading">
        <h2 id="import-history-heading">已保存的导入记录</h2>
        <p className="page-desc">打开记录会重新校验完整副本。列表中的历史记录不代表当前内容仍一致。</p>
        {historyError ? <p role="alert" className="action-error">{historyError}</p> : null}
        {!items.length && !busy && !historyError ? <p className="page-desc">还没有导入记录。先添加一个 Skill。</p> : null}
        <ul className="import-history">
          {items.map((item) => <li key={item.import_id}>
            <button type="button" className="import-history-button" disabled={!!busy} aria-current={item.import_id === selected ? 'true' : undefined}
              onClick={() => item.import_id === selected ? setRefresh((n) => n + 1) : setSearch({ import: item.import_id })}>
              <strong>{item.summary ? `${sourceLabel(item.summary.source_kind)} · ${formatTime(item.summary.created_at)}` : '记录无法验证'}</strong>
              <span>{item.summary ? `${item.summary.file_count} 个文件 · ${bytesLabel(item.summary.total_bytes)} · ${item.summary.actor_id}` : '未展示未经验证的内容'}</span>
              <code>{item.import_id}</code>
            </button>
          </li>)}
        </ul>
      </section>
    </div>
    {result ? <section className="panel import-panel import-result" aria-labelledby="import-result-heading">
      <div className="import-result-heading"><h2 id="import-result-heading">检查结果：{result.admission.skill_name}</h2>
        <span className={verdictTag(result.admission.verdict)}>{verdictLabel(result.admission.verdict)}</span></div>
      <p className="page-desc">副本已校验 · 尚未安装。检查结论基于保存的内容，不代表已经授予运行权限。</p>
      {result.admission.verdict === 'quarantine' ? <p className="action-error">此候选被隔离。请检查发现项，在修复来源后重新导入。</p> : null}
      <p className="page-desc">{result.import.files.length} 个文件 · {bytesLabel(result.import.files.reduce((total, file) => total + file.bytes, 0))} · {sourceLabel(result.import.source_kind)} · {formatTime(result.import.created_at)}</p>
      {result.import.excluded_git_metadata ? <p className="page-desc">已排除 .git 元数据及钩子。</p> : null}
      {result.import.remote ? <p className="page-desc">已固定本次下载 · {bytesLabel(result.import.remote.archive_bytes)} · Skill 目录：{result.import.remote.archive_path || 'ZIP 根层'} · {result.import.remote.expected_sha256 ? '预期 SHA256 已匹配' : '未提供预期 SHA256，发布者身份尚未确认'}</p> : null}
      <h3>声明的权限需求</h3>
      <p className="page-desc">以下是内容声明和静态检查得到的需求，尚未批准。</p>
      {result.admission.declared_facts.length ? <ul className="import-facts">{result.admission.declared_facts.map((fact, index) => <li key={index}>
        <strong>{domainLabel(fact.domain)} · {fact.action}</strong> <code>{fact.resource.value}</code>
      </li>)}</ul> : <p className="page-desc">未提取到明确的权限声明；这不代表运行时无需权限。</p>}
      {result.admission.verdict !== 'quarantine' ? <ImportPermissionPanel key={result.import.import_id} result={result} /> : null}
      <h3>检查发现</h3>
      {result.admission.findings?.length ? <ul className="import-facts">{result.admission.findings.map((finding) => <li key={finding.finding_id}>
        <span className={severityTag(finding.severity)}>{severityLabel(finding.severity)}</span> <strong>{finding.disposition === 'quarantine' ? '需隔离的内容' : finding.disposition === 'declare' ? '检测到权限需求' : '检查提示'}</strong> <code>{finding.rule_id}</code>
        {finding.location?.path ? <span> · {finding.location.path}{finding.location.line ? `:${finding.location.line}` : ''}</span> : null}
        {finding.excerpt ? <p className="page-desc">内容摘录（不可信文本）：<span>{finding.excerpt}</span></p> : null}
      </li>)}</ul> : <p className="page-desc">本次检查未报告发现项。</p>}
      <details><summary>查看文件清单与内容摘要</summary>
        {result.import.remote ? <p>下载时归档 SHA256 <code>{result.import.remote.archive_sha256}</code></p> : null}
        <p>制品摘要 <code>{result.import.artifact_digest}</code></p>
        <p>准入内容摘要 <code>{result.admission.content_hash}</code></p>
        <ul className="import-files">{result.import.files.map((file) => <li key={file.path}>
          <strong>{file.path}</strong><span>{bytesLabel(file.bytes)}{file.executable ? ' · 包含可执行标记，未执行' : ''}</span>
          <code>{file.sha256}</code>
        </li>)}</ul>
      </details>
    </section> : null}
  </section>;
}
