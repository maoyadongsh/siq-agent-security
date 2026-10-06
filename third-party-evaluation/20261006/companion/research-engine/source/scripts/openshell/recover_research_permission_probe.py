"""Recover only an explicitly identified, retained synthetic evaluation run."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlmodel import create_engine

from scripts.openshell import prove_qwen38_business_api as business, prove_qwen38_postgresql_guard as database
from scripts.openshell.prove_research_business_permissions import PermissionScenario
from scripts.openshell.research_permission_skills import InstalledPermissionSkills
from services import qwen38_request_startup as startup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--proof-private', type=Path, required=True)
    parser.add_argument('--recovery-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--skill-proof', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError('recovery_output_preexists')
    if args.proof_private.parent != business.api.ROOT / 'var/openshell/qwen38':
        raise RuntimeError('recovery_proof_path_invalid')
    args.task = 'connectivity'
    scenario = PermissionScenario(args)
    handle = scenario.load_cleanup(args.run_id)
    root_bytes = (args.proof_private / 'authority' / business.roots.DEFAULT_RELATIVE).read_bytes()
    document = json.loads(root_bytes)
    if document['scope_id'] != handle.execution_binding.pool_scope_id:
        raise RuntimeError('recovery_scope_mismatch')
    directory = startup.location(args.run_id)
    url = make_url((directory / 'supervisor-database.url').read_text().strip())
    if re.fullmatch(r'siq_qwen_guard_[a-f0-9]{16}', url.database or '') is None:
        raise RuntimeError('recovery_database_identity_invalid')
    scenario.engine = create_engine(url.set(drivername='postgresql+psycopg'),
                                   connect_args={'connect_timeout': 5, 'options': '-c statement_timeout=5000'})
    scenario.scope = document['scope_id']
    rows = scenario.rows()
    if len(rows) != 1 or rows[0].pool_binding_run_id != args.run_id or rows[0].status == 'running':
        scenario.engine.dispose()
        raise RuntimeError('recovery_execution_identity_mismatch')
    scenario.root_path = business.api.ROOT / business.roots.SCOPED_RELATIVE / (scenario.scope + '.json')
    scenario.root_bytes = root_bytes
    if args.skill_proof:
        proof = json.loads(args.skill_proof.read_text())
        if 'proof' in proof:
            proof = proof['proof']
        contexts = proof['skill_sync_records']
        if len(contexts) != 1 or contexts[0]['business_run_id'] != args.run_id:
            raise RuntimeError('recovery_skill_run_mismatch')
        scenario.factory = InstalledPermissionSkills(args)
        scenario.factory.installations = proof['skill_installations']
    scenario.factory.login()
    scenario.factory.identity_id = document['runtime_identity_id']
    scenario.factory.grant = scenario.factory.api('/v1/grants/' + document['grant_id'])
    pattern = 'siq_qwen_skill_*' if args.skill_proof else 'siq_qwen_proof_*'
    profiles = [p for p in (Path.home() / '.hermes/profiles').glob(pattern)
                if 'hi-' + hashlib.sha256(str(p).encode()).hexdigest()[:32] == document['instance_id']]
    if len(profiles) != 1:
        raise RuntimeError('recovery_profile_identity_mismatch')
    scenario.factory.profile = profiles[0]
    if args.skill_proof:
        for row in scenario.factory.installations:
            path = profiles[0] / 'skills' / row['name'] / 'SKILL.md'
            if (Path(row['installed_path']) / 'SKILL.md' != path or path.resolve() != path
                    or hashlib.sha256(path.read_bytes()).hexdigest() != row['skill_file_sha256']):
                raise RuntimeError('recovery_skill_installation_changed')
    info = profiles[0].lstat()
    scenario.factory.profile_inode = (info.st_dev, info.st_ino)
    result = {'schema_version': 'siq.research.permission-recovery.v1', 'run_id': args.run_id, 'passed': False}
    result['runtime_and_authority_cleanup'] = scenario.cleanup(result)
    if result['runtime_and_authority_cleanup'] is True:
        database._docker(['exec', '-i', database.CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
                          '-X', '-v', 'ON_ERROR_STOP=1', '-c', 'DROP DATABASE ' + url.database])
        result['owned_temporary_database_removed'] = True
        result['passed'] = True
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
