import SkillRemovalDialog from '../components/SkillRemovalDialog';
import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import { localApi } from '../api';
import { skillInstallErrorText } from '../skillInstall';
import { useLocalSession } from '../session';
import type { SkillContentChange, SkillInstallationCatalog, SkillInstallationInspection, SkillRemovalView } from '../types';

const recordedLabel = { installed_unverified: '记录显示已安装', rolled_back: '已记录回滚', recovery_required: '需要恢复' };
const stateLabel = { matched: '与安装时的内容和归属一致', changed: '检测到安装内容或归属变化', missing: '未找到原安装目标', unavailable: '本次未能完成检查' };
const changeLabel: Record<SkillContentChange['change'], string> = { added: '新增', modified: '内容或执行权限变化', removed: '缺失', type_changed: '文件类型变化', ownership_changed: '安装归属变化' };
const kindLabel = { file: '文件', directory: '目录', other: '其他对象' };

export default function InstalledSkillsPage() {
  const { status } = useLocalSession();
  const [params, setParams] = useSearchParams();
  const [catalog, setCatalog] = useState<SkillInstallationCatalog | null>(null);
  const [listError, setListError] = useState('');
  const [listBusy, setListBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [inspectRefresh, setInspectRefresh] = useState(0);
  const [visible, setVisible] = useState(() => document.visibilityState === 'visible');
  const [inspection, setInspection] = useState<SkillInstallationInspection | null>(null);
  const [inspectError, setInspectError] = useState('');
  const [checking, setChecking] = useState(false);
  const [removal, setRemoval] = useState<SkillRemovalView | null>(null);
  const [removalError, setRemovalError] = useState('');
  const [removalOpen, setRemovalOpen] = useState(false);
  const refreshDetails = useCallback(() => setInspectRefresh((n) => n + 1), []);
  const items = [...(catalog?.items ?? [])].sort((a, b) => b.plan.created_at.localeCompare(a.plan.created_at));
  const selected = params.get('install_id') ?? items[0]?.install_id ?? '';
  const record = catalog?.items.find((r) => r.install_id === selected);
  const result = inspection?.record.install_id === selected ? inspection : null;
  useEffect(() => {
    const listener = () => setVisible(document.visibilityState === 'visible');
    document.addEventListener('visibilitychange', listener);
    return () => document.removeEventListener('visibilitychange', listener);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setListBusy(true); setCatalog(null); setListError('');
    localApi.skillInstallations(controller.signal).then((data) => { if (!controller.signal.aborted) setCatalog(data); })
      .catch((err: unknown) => { if (!controller.signal.aborted) setListError(skillInstallErrorText(err)); })
      .finally(() => { if (!controller.signal.aborted) setListBusy(false); });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    if (removalOpen) return;
    setInspection(null); setRemoval(null); setRemovalError(''); setInspectError(''); setChecking(false);
    if (!record || !visible) return;
    let stopped = false;
    let controller: AbortController | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      controller = new AbortController();
      setChecking(true); setInspection(null); setRemoval(null); setRemovalError(''); setInspectError('');
      try {
        if (record.recorded_status === 'installed_unverified') {
          try {
            const current = await localApi.skillRemoval(record.install_id, controller.signal);
            if (current.record.plan.signature !== record.plan.signature || current.record.claim_signature !== record.claim_signature) throw new Error('skill_install_incompatible_response');
            if (!stopped) setRemoval(current);
            if (current.status === 'removed') return;
          } catch (err) { if (!stopped) setRemovalError(skillInstallErrorText(err)); }
        }
        if (stopped) return;
        const data = await localApi.inspectSkillInstallation(record.install_id, controller.signal);
        if (data.record.plan.signature !== record.plan.signature || data.record.claim_signature !== record.claim_signature) throw new Error('skill_install_incompatible_response');
        if (!stopped) setInspection(data);
      } catch (err) { if (!stopped) setInspectError(skillInstallErrorText(err)); }
      finally { if (!stopped) { setChecking(false); timer = setTimeout(() => void check(), 30000); } }
    };
    void check();
    return () => { stopped = true; controller?.abort(); clearTimeout(timer); };
  }, [record, visible, inspectRefresh, removalOpen]);
  return <section className="local-imports-page">
    <PageHeader title="已安装 Skill" kicker="AGENTSHIELD" icon="shield"
      description="找回通过 SIQ 安装的记录，核对当前文件与安装时的内容。检查不会更新、恢复或删除文件。"
      connection={listError ? 'disconnected' : status ? 'connected' : 'loading'} connectionError={listError || undefined}
      actions={<><Link className="btn btn-sm" to="/skill-imports">导入新 Skill</Link><button type="button" className="btn btn-sm" disabled={listBusy || removalOpen} onClick={() => setRefresh((n) => n + 1)}>刷新安装记录</button></>} />
    <div className="import-columns">
      <section className="panel import-panel" aria-labelledby="installed-records-heading">
        <h2 id="installed-records-heading">安装记录</h2>
        <p className="page-desc">列表显示历史记录，当前内容以检查结果为准。其他方式安装的 Skill 可从智能体资产中发现。</p>
        {listBusy ? <p role="status">正在读取安装记录…</p> : null}
        {listError ? <p className="action-error" role="alert">{listError}</p> : null}
        {catalog?.issues.length ? <p role="alert">有 {catalog.issues.length} 项安装记录无法核验，未把它们显示为正常安装。请保留状态目录并检查服务诊断。</p> : null}
        {!listBusy && catalog && !items.length ? <p>还没有可读取的 SIQ 安装记录。<Link to="/skill-imports">从导入 Skill 开始</Link></p> : null}
        <ul className="import-history">{items.map((r) => <li key={r.install_id}>
          <button type="button" className="import-history-button" disabled={removalOpen} aria-current={r.install_id === selected} onClick={() => setParams({ install_id: r.install_id })}>
            <strong>{r.plan.directory_name}</strong><span>{recordedLabel[r.recorded_status]} · {new Date(r.operation?.recorded_at ?? r.plan.created_at).toLocaleString()}</span>
            <span>{r.plan.target_display}</span>
          </button>
        </li>)}</ul>
      </section>
      <section className="panel import-panel" aria-labelledby="installation-inspection-heading" aria-busy={checking}>
        <h2 id="installation-inspection-heading">当前内容检查</h2>
        {!record ? <p>{selected && !listBusy ? '未找到可核验的对应记录，请刷新列表后重新选择。' : '选择一份安装记录查看。'}</p> : <>
          <h3>{record.plan.directory_name}</h3><p>{record.plan.target_display}</p>
          <p className="page-desc">{visible ? '页面可见时每 30 秒检查所选安装；只比较原安装清单，不检查远端新版本。' : '页面不可见，自动检查已暂停。'}</p>
          {removal?.record.install_id === selected && removal.status === 'removed' ? <p role="status"><strong>已记录移除完成</strong>，原操作不再检查或清理同路径后来的内容。</p> : null}
          {removalError ? <p role="alert" className="action-error">{removalError} 当前移除状态无法确认。</p> : null}
          {checking ? <p role="status">正在核对文件内容与安装归属…</p> : null}
          {inspectError ? <p role="alert" className="action-error">{inspectError} 当前状态无法确认。</p> : null}
          {result ? <>
            <p role="status"><strong>{stateLabel[result.target_state]}</strong></p>
            <p>检查时间：{new Date(result.checked_at).toLocaleString()}</p>
            {result.target_state === 'matched' ? <p>本次文件检查一致。权限是否可用、平台接入和运行保护仍需独立验证。</p> : null}
            {result.target_state === 'missing' ? <p>目标可能被外部移动或删除，这不代表 SIQ 已完成卸载。</p> : null}
            {result.target_state === 'unavailable' ? <p role="alert">{result.issue_code === 'comparison_budget_exceeded' ? '目录项数量超过本次检查预算。' : '目标位置、目录或文件无法安全读取。'} 下方如有变化，仅代表已经观察到的部分。</p> : null}
            {result.changes_total > 0 ? <>
              <p>已发现 {result.changes_total} 项变化{result.changes_truncated ? '，仅展示前 200 项' : ''}。未知目录作为一个新增对象，不扫描其内部。</p>
              <ul className="import-files">{result.changes.map((change) => <li key={`${change.path_digest}:${change.change}`}>
                <span><strong>{changeLabel[change.change]}</strong> · {kindLabel[change.kind]}</span><code>{change.path_display === '.' ? '安装根目录' : change.path_display}</code>
              </li>)}</ul>
            </> : null}
          </> : null}
          <div className="import-actions"><button type="button" className="btn" disabled={checking || !visible || removalOpen} onClick={() => setInspectRefresh((n) => n + 1)}>立即检查内容</button>
            <Link className="btn" to={removal?.claim ? `/grants?grant=${encodeURIComponent(record.plan.grant_id)}` : `/grants?grant=${encodeURIComponent(record.plan.grant_id)}&install_id=${encodeURIComponent(record.install_id)}`}>{removal?.claim ? '查看授权记录' : '查看安装结果与权限'}</Link>
          </div>
          {record.recorded_status === 'installed_unverified' ? <SkillRemovalDialog key={record.install_id} current={removal?.record.install_id === selected ? removal : null} disabled={checking || !visible} onOpen={setRemovalOpen} onRefresh={refreshDetails} /> : null}
          {removal?.record.install_id === selected && removal.status === 'not_requested' && !checking && !removalOpen ? <div className="import-actions"><Link className="btn" to={`/skill-updates?install_id=${encodeURIComponent(record.install_id)}`}>审阅候选并更新</Link></div> : null}
          <details><summary>查看安装基线</summary><dl><dt>操作编号</dt><dd><code>{record.install_id}</code></dd><dt>副本摘要</dt><dd><code>{record.plan.source.artifact_digest}</code></dd><dt>实例编号</dt><dd><code>{record.plan.instance_id}</code></dd></dl></details>
        </>}
      </section>
    </div>
  </section>;
}
