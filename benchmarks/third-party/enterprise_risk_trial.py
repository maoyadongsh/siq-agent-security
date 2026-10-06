"""Freeze native enterprise discovery, risk lifecycle and OCSF evidence export."""
import argparse
import json
import subprocess
from pathlib import Path

import governance_trial
from common import sha256, utc_now, write_json
from enterprise_native_edge import ASSERTIONS as NATIVE_ASSERTIONS
from enterprise_native_edge import CASES as NATIVE_CASES
from enterprise_risk import ASSERTIONS, CASES

RUNTIME_QUERY = "import sys,json,hashlib,importlib.metadata;from pathlib import Path;print(json.dumps({'version':sys.version,'binary_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),'packages':sorted((x.metadata['Name'],x.version) for x in importlib.metadata.distributions())}))"


def freeze(campaign, protocol_id, candidate=None):
    candidate = candidate or campaign/'private/candidates/5470ab3780f2-governancefix1'
    governance_trial.freeze(campaign, protocol_id, include_edge=True, candidate_root=candidate)
    path=campaign/'protocols'/protocol_id/'protocol.json';p=json.loads(path.read_text())
    p.update(risk_assertions=ASSERTIONS,native_enterprise_assertions=NATIVE_ASSERTIONS,
             native_build=json.loads((campaign/'inventory/enterprise-native-build-001.json').read_text()))
    p['expected_status'].update(NATIVE_CASES);p['expected_status'].update(CASES)
    p['scope']='native Edge/Hermes asset -> actual rule engine -> risk acknowledgement/acceptance/expiry/resolve -> exact finding pagination and OCSF export; real production HTTP/PostgreSQL and real reaper subprocess'
    p['limits']=['author run with ephemeral RS256/JWKS issuer, not real customer IdP or external witness',
                 'controlled invocation of actual reaper, not continuous worker scheduling or webhook notification',
                 'known native config fixture creates governance findings; no natural model attack or runtime enforcement claim',
                 'timezones tested against actual wall clock; worker must finish early before expiry or timing assertion fails',
                 'OCSF mapping follows product contract; no claim of external OCSF schema certification']
    registration=campaign/'plan'/(protocol_id.removesuffix('-protocol')+'.md')
    p['registration']={'path':str(registration),'sha256':sha256(registration)};p['frozen_at']=utc_now()
    p['risk_python_runtime'] = json.loads(subprocess.check_output([str(candidate/'apps/control-api/.venv/bin/python'), '-c', RUNTIME_QUERY], text=True))
    for folder in ('edge/agent','connectors/hermes'):
        for f in (candidate/folder).rglob('*'):
            if f.is_file() and (f.suffix=='.go' or f.name in ('go.mod','go.sum')):p['candidate_sources'][str(f.relative_to(candidate))]=sha256(f)
    for name in ('enterprise_native_edge.py','enterprise_risk.py','enterprise_risk_trial.py','verify_governance.py'):
        (path.parent/'harness-source'/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    p['harness_sources']={f.name:sha256(f) for f in (path.parent/'harness-source').glob('*.py')}
    write_json(path,p,exclusive=False);write_json(path.parent/'local-anchor.json',{'sha256':sha256(path)},exclusive=False)
    print(json.dumps({'protocol':str(path),'HTTP':len(p['expected_status']),'risk_assertions':len(ASSERTIONS)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('freeze','run'))
    parser.add_argument('--campaign',type=Path,required=True);parser.add_argument('--protocol-id',required=True);parser.add_argument('--run-id')
    parser.add_argument('--candidate',type=Path)
    args=parser.parse_args()
    if args.action=='freeze':freeze(args.campaign.resolve(),args.protocol_id,args.candidate.resolve() if args.candidate else None)
    else:raise SystemExit(governance_trial.run(args.campaign.resolve(),args.protocol_id,args.run_id))
