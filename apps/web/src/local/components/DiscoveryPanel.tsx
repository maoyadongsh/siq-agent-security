import { useCallback, useEffect, useRef, useState } from 'react';
import { localApi } from '../api';
import type { DiscoveryInput, DiscoveryPreview, DiscoveryStatus } from '../types';

const runLabel = {
  idle: '当前没有扫描任务', running: '正在发现智能体与 Skill…', succeeded: '扫描完成',
  partial: '扫描完成，部分目录未能读取', failed: '本次扫描未完成',
};
const rootLabel = { available: '可扫描', missing: '未找到', unreadable: '无法读取' };

function issueText(issue: string): string {
  const split = issue.indexOf(':');
  const category = split >= 0 ? issue.slice(0, split) : issue;
  const labels: Record<string, string> = { symlink: '符号链接未跟随', limit: '达到扫描上限', unhashable: '无法确认 Skill 内容', unreadable: '无法读取' };
  return `${labels[category] || '已跳过'}：${split >= 0 ? issue.slice(split + 1) : ''}`;
}

export default function DiscoveryPanel({ onCompleted }: { onCompleted: () => void }) {
  const [status, setStatus] = useState<DiscoveryStatus | null>(null);
  const [path, setPath] = useState('');
  const [kind, setKind] = useState('project_dir');
  const [preview, setPreview] = useState<DiscoveryPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingRun = useRef<string>();
  const running = status?.run.state === 'running';

  const acceptStatus = useCallback((next: DiscoveryStatus) => {
    setStatus(next);
    if (next.run.state === 'running') pendingRun.current = next.run.run_id;
    else if (pendingRun.current && pendingRun.current === next.run.run_id) {
      pendingRun.current = undefined;
      onCompleted();
    }
  }, [onCompleted]);

  useEffect(() => {
    let active = true;
    void localApi.discoveryStatus().then((next) => { if (active) acceptStatus(next); })
      .catch(() => { if (active) setError('无法读取扫描状态，请重试。'); });
    return () => { active = false; };
  }, [acceptStatus]);

  useEffect(() => {
    if (!running) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await localApi.discoveryStatus();
        if (!active) return;
        setError(null);
        acceptStatus(next);
        if (next.run.state === 'running') timer = setTimeout(() => { void poll(); }, 700);
      } catch {
        if (!active) return;
        setError('暂时无法读取扫描进度，正在重新连接。');
        timer = setTimeout(() => { void poll(); }, 2000);
      }
    };
    timer = setTimeout(() => { void poll(); }, 400);
    return () => { active = false; clearTimeout(timer); };
  }, [running, acceptStatus]);

  const input = (): DiscoveryInput => path.trim() ? { [kind]: path.trim() } : {};
  const previewScope = async () => {
    setBusy(true); setError(null);
    try { setPreview(await localApi.discoveryPreview(input())); }
    catch (err) { setError(err instanceof Error ? err.message : '无法预览扫描范围'); }
    finally { setBusy(false); }
  };
  const scan = async () => {
    setBusy(true); setError(null);
    try {
      const next = await localApi.discoveryScan(input());
      acceptStatus(next);
      setPreview(null); setPath('');
    } catch (err) { setError(err instanceof Error ? err.message : '无法开始扫描'); }
    finally { setBusy(false); }
  };
  const roots = preview?.roots ?? status?.roots ?? [];
  const count = roots.filter((root) => root.status === 'available').length;

  return <div className="card" aria-busy={busy || running}>
    <h2>发现已有智能体与 Skill</h2>
    <p className="page-desc">先查看发现结果，再选择需要保护的对象。扫描只读取平台配置与 Skill 文件，不启用钩子或执行 Skill。</p>
    <div className="toolbar">
      <div className="field field-flush">
        <label htmlFor="discovery-kind">添加目录类型</label>
        <select id="discovery-kind" value={kind} disabled={running || busy} onChange={(event) => { setKind(event.target.value); setPreview(null); }}>
          <option value="project_dir">项目目录</option><option value="skill_dir">Skill 目录或集合</option>
        </select>
      </div>
      <div className="field field-flush field-grow">
        <label htmlFor="discovery-path">额外目录（可选）</label>
        <input id="discovery-path" value={path} disabled={running || busy} placeholder="本地绝对路径或 ~/…"
          onChange={(event) => { setPath(event.target.value); setPreview(null); }} />
      </div>
      <button type="button" className="btn" disabled={busy || running} onClick={() => { void previewScope(); }}>预览扫描范围</button>
      <button type="button" className="btn btn-primary" disabled={busy || running || Boolean(path.trim() && !preview)} onClick={() => { void scan(); }}>
        {running ? '扫描中…' : path.trim() ? '添加目录并扫描' : '重新扫描'}
      </button>
    </div>
    <details className="block-gap">
      <summary>扫描范围：{count} 个可读取位置（包括已登记的手动目录）</summary>
      <p className="page-desc">手动添加的目录会保留到后续扫描。未找到的平台目录属于正常情况；目录关联不代表运行权限已生效。</p>
      <ul className="discovery-paths">{roots.map((root) => <li key={`${root.kind}:${root.path}`}>
        <code>{root.path}</code> · {root.platform} · {rootLabel[root.status]}
      </li>)}</ul>
    </details>
    {status ? <p role="status" className="page-desc block-gap" data-scan-id={status.run.run_id} data-scan-state={status.run.state}>
      {runLabel[status.run.state]}
      {status.run.finished_at ? ` · ${new Date(status.run.finished_at).toLocaleString()} · ${status.run.asset_count} 项资产，${status.run.skill_count} 个 Skill` : ''}
      {status.run.issue_count > 0 ? ` · ${status.run.issue_count} 处跳过` : ''}
    </p> : null}
    {status?.run.issues?.length ? <details className="block-gap">
      <summary>查看未完成的扫描项（{status.run.issue_count}）</summary>
      <ul className="discovery-paths">{status.run.issues.map((issue, index) => <li key={`${index}:${issue}`}>{issueText(issue)}</li>)}</ul>
      {status.run.issue_count > status.run.issues.length ? <p className="page-desc">此处显示前 {status.run.issues.length} 项。</p> : null}
    </details> : null}
    {error || status?.run.error ? <p className="action-error" role="alert">{error || status?.run.error}</p> : null}
  </div>;
}
