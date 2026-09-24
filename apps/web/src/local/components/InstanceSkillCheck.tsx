import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { LocalApiError, localApi } from '../api';
import type { Admission, LedgerAsset } from '../types';

/** Checks an existing installation; it never creates or approves a grant. */
export default function InstanceSkillCheck({ disabled, onChecked }: {
  disabled: boolean; onChecked: (admission: Admission) => void;
}) {
  const [skills, setSkills] = useState<LedgerAsset[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  const submitting = useRef(false);
  const mounted = useRef(false);
  const selected = skills.find((skill) => skill.id === selectedId);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    localApi.assets().then((result) => {
      if (!active) return;
      const items = (result.assets ?? []).filter((asset) => asset.source_type === 'skill_dir' && !!asset.admit_path);
      setSkills(items);
      setSelectedId((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? '');
    }).catch(() => { if (active) setError('无法读取已发现的 Skill，请重新读取。'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [attempt]);
  const check = async () => {
    if (disabled || loading || submitting.current || !selected?.admit_path) return;
    submitting.current = true; setChecking(true); setError('');
    try {
      const result = await localApi.admit(selected.admit_path);
      if (!mounted.current) return;
      if (result.admission.verdict === 'quarantine') {
        setError('此 Skill 未通过安全检查，不能作为权限参考。可查看检查结果或选择其他 Skill。');
      } else onChecked(result.admission);
    } catch (err) {
      if (mounted.current) setError(err instanceof LocalApiError && err.status === 400
        ? '无法读取此 Skill 目录。请确认目录仍存在且可读取，再重试或重新发现。'
        : err instanceof LocalApiError && [401, 403].includes(err.status)
          ? '当前管理会话无权执行检查，请重新建立管理会话后重试。'
          : '检查未完成，请确认本地服务可用后重试；所选 Skill 已保留。');
    } finally {
      submitting.current = false;
      if (mounted.current) setChecking(false);
    }
  };
  return <section aria-label="检查已发现的 Skill" aria-busy={loading || checking}>
    {loading ? <p role="status">正在读取已发现的 Skill…</p> : skills.length ? <>
      <div className="field"><label htmlFor="instance-skill">已发现的 Skill</label>
        <select id="instance-skill" value={selectedId} disabled={disabled || checking} onChange={(event) => { setSelectedId(event.target.value); setError(''); }}>
          {skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.name} · {skill.source_locator}</option>)}
        </select>
      </div>
      <button className="btn" type="button" disabled={disabled || checking || !selected} onClick={() => { void check(); }}>{checking ? '正在检查…' : '检查并继续'}</button>
      <p className="page-desc">检查后继续编辑和批准权限。此操作不会运行 Skill 或自动授权。</p>
    </> : <p>尚未发现可检查的 Skill。<Link to="/agents?kind=skills">去发现 Skill</Link></p>}
    {error ? <p className="action-error" role="alert">{error}</p> : null}
    <button className="btn btn-sm" type="button" disabled={disabled || checking || loading} onClick={() => setAttempt((value) => value + 1)}>重新读取 Skill</button>
    {error ? <p><Link to="/agents?kind=skills">查看 Skill 与检查结果</Link></p> : null}
  </section>;
}
