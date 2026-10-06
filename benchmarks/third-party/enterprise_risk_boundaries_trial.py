"""Freeze standalone risk boundaries with native discovery and explicit controls."""
import argparse
import json
from pathlib import Path

import enterprise_risk_trial as base
import governance_trial
from common import sha256, write_json
from enterprise_risk import CASES as OLD_CASES
from enterprise_risk_boundaries import ASSERTIONS, CASES


def freeze(campaign,protocol_id,candidate):
    base.freeze(campaign,protocol_id,candidate)
    path=campaign/'protocols'/protocol_id/'protocol.json';p=json.loads(path.read_text())
    for name in OLD_CASES:del p['expected_status'][name]
    p['expected_status'].update(CASES);p['risk_assertions']=ASSERTIONS;p['risk_boundary_profile']=True
    p['scope']='native discovery plus actual rule findings: risk acceptance field validation, object-before-permission, accepted/resolved terminal states and legitimate open/acknowledged controls'
    p['limits']=['author run; test issuer, isolated production API/PostgreSQL','resolved control uses a signed synthetic asset; native asset supplies input and open/acknowledged controls',
                 'sequential requests; no concurrency, continuous worker, UI or natural attack claim','invalid old-product writes may contaminate later control; never reset state via SQL or erase failure']
    for name in ('enterprise_risk_boundaries.py','enterprise_risk_boundaries_trial.py'):(path.parent/'harness-source'/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    p['harness_sources']={f.name:sha256(f) for f in (path.parent/'harness-source').glob('*.py')}
    write_json(path,p,exclusive=False);write_json(path.parent/'local-anchor.json',{'sha256':sha256(path)},exclusive=False)
    print(json.dumps({'HTTP':len(p['expected_status']),'boundary_assertions':len(ASSERTIONS)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['freeze','run']);parser.add_argument('--campaign',type=Path,required=True);parser.add_argument('--protocol-id',required=True);parser.add_argument('--run-id');parser.add_argument('--candidate',type=Path,required=True);args=parser.parse_args()
    if args.action=='freeze':freeze(args.campaign.resolve(),args.protocol_id,args.candidate.resolve())
    else:raise SystemExit(governance_trial.run(args.campaign.resolve(),args.protocol_id,args.run_id))
