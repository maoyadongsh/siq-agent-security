import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { localApi } from '../api';
import { isImportPermissionSource } from '../importPermissions';
import SkillInstallPreview from './SkillInstallPreview';
import type { Grant, ImportPermissionSource } from '../types';

export default function ImportGrantSource({ grant, onOperation }: { grant: Grant; onOperation: (message?: string, pending?: boolean) => void }) {
  const admissionId = grant.admission_id;
  const [skillName, setSkillName] = useState('');
  const [source, setSource] = useState<ImportPermissionSource | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let canceled = false;
    localApi.admission(admissionId).then(({ admission }) => {
      const value: unknown = JSON.parse(admission.source.ref ?? 'null');
      if (!isImportPermissionSource(value)) throw new Error('incompatible import source');
      if (!canceled) { setSource(value); setSkillName(admission.skill_name); }
    }).catch(() => { if (!canceled) setFailed(true); });
    return () => { canceled = true; };
  }, [admissionId]);
  return <div className="import-grant-source">
    <p className="page-desc">此权限绑定导入候选。批准后可预览并确认安装；安装后仍需完成平台识别与保护验证，不能直接作为运行权限使用。</p>
    {source ? <>
      <Link to={`/skill-imports?import=${source.import_id}`}>查看绑定的 Skill 候选</Link>
      <p>副本摘要 <code>{source.artifact_digest}</code></p>
      <p>检查摘要 <code>{source.analysis_sha256}</code></p>
      {grant.status === 'approved' && grant.platform === 'hermes' && /^hri-[a-f0-9]{32}$/.test(grant.subject.id) ? <SkillInstallPreview key={`${grant.grant_id}:${grant.state_revision}`} grant={grant} source={source} skillName={skillName} onOperation={onOperation} /> : null}
    </> : failed ? <p role="alert" className="action-error">无法读取候选来源，请重新打开此授权。批准时服务还会完整复验副本。</p> : <p role="status">正在读取候选来源…</p>}
  </div>;
}
