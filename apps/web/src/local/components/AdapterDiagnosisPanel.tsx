import type { AdapterDiagnosis } from '../types';

const checkLabel = { pass: '已检查', fail: '需处理', unknown: '待验证', not_applicable: '尚不支持' };

export default function AdapterDiagnosisPanel({ diagnosis }: { diagnosis?: AdapterDiagnosis }) {
  if (!diagnosis) return null;
  return <details className="block-gap" data-adapter-diagnosis={diagnosis.platform}>
    <summary>查看接入诊断</summary>
    <ul className="discovery-paths">{diagnosis.checks.map((check) => <li key={check.code}>
      <span className={check.status === 'fail' ? 'tag tag-warn' : 'tag tag-info'}>{checkLabel[check.status]}</span> {check.message}
    </li>)}</ul>
    {diagnosis.next_steps.map((step) => <p className="page-desc" key={step}>{step}</p>)}
  </details>;
}
