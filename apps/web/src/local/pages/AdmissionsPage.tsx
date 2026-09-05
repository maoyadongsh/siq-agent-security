/** 旧准入流水页；路由已重定向到 /agents，签发改走资产详情。 */
import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { localApi } from '../api';
import type { Admission } from '../types';
import { useLocalSession } from '../session';
import { verdictTag } from '../format';

export default function AdmissionsPage() {
  const { actorId } = useLocalSession();
  const [rows, setRows] = useState<Admission[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [card, setCard] = useState<string>('');
  const [detail, setDetail] = useState<Admission | null>(null);
  const [platform, setPlatform] = useState('hermes');
  const [subject, setSubject] = useState('local');
  const [grantMsg, setGrantMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    localApi
      .admissions()
      .then((data) => {
        setRows(data.admissions ?? []);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
  }, []);

  const open = (row: Admission) => {
    setSelected(row.admission_id);
    setGrantMsg(null);
    localApi
      .admission(row.admission_id)
      .then((data) => {
        setDetail(data.admission);
        setCard(data.skill_card || '');
      })
      .catch((err: unknown) => {
        setDetail(row);
        setCard(err instanceof Error ? err.message : '');
      });
  };

  const createGrant = () => {
    if (!selected) return;
    setGrantMsg(null);
    localApi
      .createGrant({
        admission_id: selected,
        platform,
        subject_id: subject.trim() || actorId,
      })
      .then((res) => setGrantMsg(`已创建 ${res.grant.grant_id}（${res.grant.status}），请到签发页批准。`))
      .catch((err: unknown) => setGrantMsg(err instanceof Error ? err.message : '签发失败'));
  };

  const columns: TableColumn<Admission>[] = [
    { key: 'name', header: 'Skill', render: (r) => r.skill_name },
    {
      key: 'verdict',
      header: '裁决',
      render: (r) => <span className={verdictTag(r.verdict)}>{r.verdict}</span>,
    },
    { key: 'trust', header: '信任', render: (r) => r.source?.trust_level ?? '—' },
    { key: 'when', header: '时间', render: (r) => r.decided_at },
  ];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="findings"
        title="准入"
        description="安装前静态裁决。quarantine 不能签发；模型不得改 verdict。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
        actions={
          <button type="button" className="btn btn-sm" onClick={load}>
            刷新
          </button>
        }
      />
      <div className="card">
        <SimpleTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.admission_id}
          emptyText="还没有准入记录。先到盘点页扫描或粘贴路径。"
          onRowClick={open}
        />
      </div>
      {detail ? (
        <div className="card">
          <h2>
            {detail.skill_name}{' '}
            <span className={verdictTag(detail.verdict)}>{detail.verdict}</span>
          </h2>
          <p className="mono page-desc">{detail.admission_id}</p>
          {detail.findings && detail.findings.length > 0 ? (
            <ul className="page-desc">
              {detail.findings.map((f) => (
                <li key={f.finding_id}>
                  {f.rule_id} · {f.disposition} · {f.severity}
                  {f.location?.path ? ` · ${f.location.path}` : ''}
                </li>
              ))}
            </ul>
          ) : (
            <p className="page-desc">无 finding。</p>
          )}
          {card ? <pre className="skill-card-pre">{card}</pre> : null}
          {detail.verdict === 'quarantine' ? (
            <p className="page-desc">隔离件不能签发 grant。</p>
          ) : (
            <div className="toolbar" style={{ marginTop: 16 }}>
              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="g-plat">平台</label>
                <select id="g-plat" value={platform} onChange={(e) => setPlatform(e.target.value)}>
                  <option value="hermes">hermes</option>
                  <option value="openclaw">openclaw</option>
                  <option value="codebuddy">codebuddy</option>
                </select>
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="g-sub">主体 ID</label>
                <input id="g-sub" value={subject} onChange={(e) => setSubject(e.target.value)} />
              </div>
              <button type="button" className="btn btn-primary" onClick={createGrant}>
                创建 grant
              </button>
            </div>
          )}
          {grantMsg ? <p className="page-desc">{grantMsg}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
