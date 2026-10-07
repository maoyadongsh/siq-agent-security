#!/usr/bin/env python3
"""New API process rolls back one deployment owned by the ephemeral live harness."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get('SIQ_OWNED_GATEWAY_RECOVERY_FIXTURE') == 'ephemeral-harness-only'
    assert os.environ.get('SIQ_AS_DEV') == '1'
    from sqlalchemy.engine import make_url

    database = make_url(os.environ['SIQ_AS_DATABASE_URL'])
    assert database.drivername == 'sqlite'
    path = Path(database.database).resolve(strict=True)
    assert path.name == 'control.db' and path.parent.name.startswith('siq-live-deployment-')
    sys.path.insert(0, str(ROOT / 'apps/control-api'))
    from app.main import app
    from fastapi.testclient import TestClient

    headers = {'X-Dev-Tenant-Id': 'dev-tenant', 'X-Dev-User-Id': 'live-owner',
               'X-Dev-Roles': 'platform_operator,security_admin,agent_owner,auditor'}
    with TestClient(app) as client:
        response = client.post('/api/v1/deployments/' + args.deployment + '/rollback', headers=headers, json={})
        result = {'api_process_pid': os.getpid(), 'rollback_status_code': response.status_code, 'passed': False}
        if response.status_code == 200:
            result['deployment_status'] = response.json()['status']
            recovery = client.get('/api/v1/deployments/' + args.deployment + '/recovery', headers=headers)
            result['recovery_state'] = recovery.json().get('state')
            result['passed'] = result['deployment_status'] == 'rolled_back' and result['recovery_state'] == 'rolled_back'
        args.out.write_text(json.dumps(result, indent=2) + '\n')
        assert result['passed'], 'independent API process rollback was not confirmed'


if __name__ == '__main__':
    main()
