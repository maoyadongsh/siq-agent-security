"""Agent permission pair through the existing daily frontend and owning DB.

Creates two audited, temporary local accounts; authentication and business
grants use public HTTP. All SIQ approvals use its public authority API. No
dependency overrides, fabricated JWT, alternate API, or evaluation image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time

ROOT = Path(__file__).resolve().parents[2]


def owned_receipts(call, agent):
    """Export only this controller's agent from the shared authority ledger."""
    records, since = [], -1
    for _ in range(1000):
        page = call('/v1/receipts?since_seq=' + str(since))
        if page.get('verified') is not True:
            raise RuntimeError('daily_permissions_receipt_chain_unverified')
        rows = page['receipts']
        records.extend(row for row in rows if row.get('agent_id') == agent)
        if not rows:
            return {'receipts': records, 'verified': True,
                    'scope': 'Own agent subset; signatures require separate verification.'}
        if rows[-1]['seq'] <= since:
            raise RuntimeError('daily_permissions_receipt_cursor_invalid')
        since = rows[-1]['seq']
    raise RuntimeError('daily_permissions_receipt_limit')


def run(args):
    from scripts.openshell.prove_research_daily_entry import process_snapshot, disable_owned_account
    protocol = json.loads(args.protocol.read_text())
    if (not re.fullmatch(r'research-permissions-daily-permissions-[0-9]{3}', args.batch)
            or protocol['batch'] != args.batch or protocol['api_pid'] != args.api_pid
            or protocol['api_start_ticks'] != args.api_start_ticks):
        raise ValueError('daily_permissions_protocol_invalid')
    for name, digest in protocol['research_source_sha256'].items():
        path = ROOT / name
        if path.resolve() != path or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('daily_permissions_source_changed')
    environment = process_snapshot(args.api_pid, args.api_start_ticks)
    if (environment.get('SIQ_BACKEND_PORT') != '18081'
            or environment.get('SIQ_OPENSHELL_REQUEST_BACKEND') != 'qwen38'
            or environment.get('SIQ_OPENSHELL_REQUEST_DEPLOYMENT') != 'host'):
        raise RuntimeError('daily_permissions_wrong_deployment')
    os.environ.clear()
    os.environ.update(environment)
    os.umask(0o077)
    args.private.mkdir(mode=0o700, parents=True, exist_ok=False)
    if args.output.exists():
        raise ValueError('daily_permissions_output_exists')

    import httpx
    from sqlmodel import Session, select
    from database import engine
    from services.auth_service import AuditLog, AuthService, User, UserRole
    from scripts.openshell import prove_research_business_permissions as permissions
    from scripts.openshell.prove_qwen38_native_tool_security import SyntheticAuthority

    class DailyAuthority(SyntheticAuthority):
        def api(self, path, body=None, **kwargs):
            if path.startswith('/v1/receipts?'):
                if self.controller is None:
                    raise RuntimeError('daily_permissions_receipt_agent_missing')
                return owned_receipts(super().api, self.controller.binding.agent_id)
            return super().api(path, body, **kwargs)

    class DailyScenario(permissions.PermissionScenario):
        def __init__(self, options):
            super().__init__(options)
            self.factory = DailyAuthority(options)

        def request_body(self, marker, trace_marker, company):
            body = super().request_body(marker, trace_marker, company)
            # The daily API must select OpenShell itself; no request override.
            body.pop('runtime_target', None)
            return body

    result = {'schema_version': 'siq.research-daily-permission-proof.v1', 'batch': args.batch,
        'started_unix': time.time(), 'api_pid': args.api_pid, 'api_start_ticks': args.api_start_ticks,
        'frontend': 'http://127.0.0.1:15173', 'authority_endpoint': SyntheticAuthority.endpoint,
        'protocol_sha256': hashlib.sha256(args.protocol.read_bytes()).hexdigest(),
        'checks': {}, 'passed': False, 'accounts': {}, 'default_route_no_override': True}
    scenario = DailyScenario(args)
    accounts, headers = {}, {}
    grant_id = None
    nonce = secrets.token_hex(8)
    company = '600000-SyntheticDaily' + nonce
    result['company'] = company
    with httpx.Client(base_url=result['frontend'], trust_env=False, timeout=600) as client:
        try:
            for label, role in [('operator', UserRole.SUPER_ADMIN), ('analyst', UserRole.ANALYST)]:
                username = 'siq_perm_' + nonce + '_' + label
                password = secrets.token_urlsafe(32)
                with Session(engine) as session:
                    if session.exec(select(User).where(User.username == username)).first():
                        raise RuntimeError('daily_permissions_account_exists')
                    user = User(username=username, email=username + '@example.org',
                        full_name='SIQ synthetic permission evaluation', role=role,
                        hashed_password=AuthService.hash_password(password), approval_note=args.batch,
                        is_active=True, approval_status='approved')
                    session.add(user)
                    session.flush()
                    user_id = user.id
                    session.add(AuditLog(user_id=user_id, action='EVALUATION_ACCOUNT_CREATED',
                        resource_type='evaluation_account', resource_id=str(user_id),
                        details=json.dumps({'batch': args.batch, 'purpose': label})))
                    session.commit()
                accounts[label] = (user_id, username)
                result['accounts'][label] = {'user_id': user_id, 'username': username}
                response = client.post('/api/auth/login', json={'username': username, 'password': password})
                if response.status_code != 200 or response.json().get('user', {}).get('id') != user_id:
                    raise RuntimeError('daily_permissions_normal_login_failed')
                headers[label] = {'Authorization': 'Bearer ' + response.json()['access_token']}
                client.cookies.clear()
            result['checks']['normal_http_login'] = True
            scope = permissions.business.pool_registry._scope_id('cn', company)
            body = {'project_id': 'company:' + scope, 'market': 'cn', 'company_directory': company,
                'object_scopes': ['company_wiki', 'public_market_data'], 'ttl_seconds': 600}
            route = '/api/auth/openshell-data-grants/users/' + str(accounts['analyst'][0])
            key = args.batch + '-' + nonce
            response = client.post(route, json=body,
                headers={**headers['analyst'], 'Idempotency-Key': key})
            result['checks']['analyst_cannot_self_authorize'] = response.status_code == 403
            if not result['checks']['analyst_cannot_self_authorize']:
                raise RuntimeError('daily_permissions_self_authorization_not_denied')
            response = client.post(route, json=body,
                headers={**headers['operator'], 'Idempotency-Key': key})
            if response.status_code != 200:
                raise RuntimeError('daily_permissions_business_grant_failed')
            grant_id = response.json()['grant_id']
            result['business_grant_id'] = grant_id
            scenario.business_grant_id = grant_id
            scenario.exercise(client, headers['analyst'], company, environment, args.private, result)
            result['checks']['daily_process_unchanged'] = process_snapshot(args.api_pid, args.api_start_ticks) == environment
        except Exception as exc:
            result['failure_type'] = type(exc).__name__
            if isinstance(exc, RuntimeError) and re.fullmatch(r'(daily_permissions|candidate|qwen)_[a-z_0-9]+', str(exc)):
                result['failure_code'] = str(exc)
        finally:
            if grant_id is not None:
                try:
                    response = client.post('/api/auth/openshell-data-grants/' + str(grant_id) + '/revoke',
                        headers=headers['operator'], timeout=90)
                    result['checks']['owned_business_grant_revoked'] = response.status_code == 200 and response.json().get('revoked') is True
                except Exception as exc:
                    result['checks']['owned_business_grant_revoked'] = False
                    result['grant_cleanup_failure_type'] = type(exc).__name__
            try:
                scenario.settle_before_api_stop(result, timeout_seconds=60)
                # Existing API stays alive: only owned scope resources are finalized.
                result['checks']['owned_authority_cleanup'] = scenario.cleanup(result) is True
            except Exception as exc:
                result['checks']['owned_authority_cleanup'] = False
                result['authority_cleanup_failure_type'] = type(exc).__name__
            for label, (user_id, username) in accounts.items():
                try:
                    disable_owned_account(engine, user_id, username, args.batch)
                    result['checks'][label + '_disabled'] = True
                    if label in headers:
                        result['checks'][label + '_token_invalidated'] = client.get('/api/auth/me',
                            headers=headers[label], timeout=10).status_code in {401, 403}
                except Exception as exc:
                    result['checks'][label + '_disabled'] = False
                    result[label + '_cleanup_failure_type'] = type(exc).__name__
            result['finished_unix'] = time.time()
            result['passed'] = not result.get('failure_type') and bool(result.get('permission_phases')) and all(result['checks'].values())
            with args.output.open('x') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'report': str(args.output), 'passed': result['passed']}))
    return 0 if result['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--api-pid', type=int, required=True)
    parser.add_argument('--api-start-ticks', required=True)
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recovery-file', type=Path, required=True)
    parser.add_argument('--relay-binary', type=Path, required=True)
    parser.add_argument('--relay-sha256', required=True)
    parser.add_argument('--helper-image-ref', required=True)
    parser.add_argument('--helper-image-id', required=True)
    parser.add_argument('--relay-port', type=int, default=47710)
    parser.set_defaults(task='paired-analysis')
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
