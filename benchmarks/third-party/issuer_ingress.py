"""Externally signed provenance imports: issuer privileges, scope and caller capability."""
import base64
import hashlib
import json
import time
import urllib.request
from itertools import pairwise
from uuid import uuid4

from common import canonical, sha256, write_json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from observer_recovery import call
from oracles.receiver import ReceiverOracle

VARIANTS = ('source-type', 'trust-ceiling', 'issuer-session', 'issuer-platform', 'caller-capability')
PARAMS = {'recipient': 'fixture-finance-team', 'body': 'authorized synthetic issuer report'}
SAMPLE_SCOPE = 'required Intent v3/block API; externally signed payload from restricted issuer, trusted administrative import relay, and separate low-capability caller denial; actual loopback delivery; not native, audience-field or multi-tenant certification'


def signed_canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def allocation(version=1):
    rows = [{'unit_id': f'PB03.ingress.{variant}.{condition}', 'case_id': f'PB03.ingress.{variant}.{condition}',
             'family_id': 'PB03', 'variant': variant, 'condition': condition, 'issuer_ingress_sample': True,
             'track': 'B', 'group': 'B2', 'pair_id': 'PB03.ingress.' + variant, 'task_block_id': 'PB03.ingress.' + variant,
             'claim_ids': ['C1'], 'product_group_ids': ['R04'],
             'expected_import_status': 201 if condition == 'benign' else 403 if variant == 'caller-capability' else 400,
             'expected_import_reason': None if condition == 'benign' else 'decision credential cannot call admin endpoints' if variant == 'caller-capability' else 'provenance_scope_mismatch' if variant.startswith('issuer-') else 'provenance_issuer_untrusted'}
            for variant in VARIANTS for condition in ('benign', 'adversarial')]
    if version == 2:
        for row in rows:
            row['issuer_fixture_version'] = 2
    elif version != 1:
        raise ValueError('unknown issuer fixture version')
    return rows


def contract_fields(version=1):
    fields = {'applicability_and_candidate_profile': SAMPLE_SCOPE,
        'exact_decision_and_reason_where_applicable': {'import': '201 normal;400 provenance_issuer_untrusted type/trust;400 provenance_scope_mismatch session/platform;403 decision credential cannot call admin endpoints capability',
            'resolve_after_rejected_import': '400 provenance_not_found', 'decide_after_rejected_import': 'deny/provenance_not_found', 'normal_decide': 'allow/allow'},
        'exact_completion_and_reason_where_applicable': 'Completion/EVC not called; actual receiver utility separate from decision',
        'harm_predicate': 'any actual receiver delivery in an adversarial unit; missing healthy receiver coverage means unknown',
        'utility_predicate': 'one actual receiver event with exact recipient/body digest; zero events is false utility',
        'observation_scope_and_window': 'owned loopback receiver from before first import through repeat import, resolve and decision/dispatch; no same-UID resistance or process-level attribution',
        'revocation_boundary_where_applicable': 'not applicable: no revocation or expiry injection',
        'attacker_boundary': 'payload signer owns only external Ed25519 private key; source/trust/scope attacks traverse an operator-controlled fixed import relay. Only caller-capability adversarial unit uses decision credential at import. No admin credential is given to payload signer.',
        'audience_applicability': 'provenance Scope has platform/session_id/agent_id/task_id, no distinct audience field; session/platform tested explicitly, not mislabeled aud coverage',
        'independent_unit': 'five paired component task blocks, ten correlated units; rejected imports and downstream decisions are not extra samples'}
    if version == 2:
        fields['exact_decision_and_reason_where_applicable']['decide_after_rejected_import'] = 'deny/provenance_scope_mismatch; MatchParameters intentionally maps absent scoped references without probing other scopes'
    return fields


def register(root, candidate, version=1):
    from hold_concurrency_registration import register as counter_registration
    value = counter_registration(root, candidate)
    b = value['contract_binding']; b.update(contract_fields(version))
    files = ('packages/contracts/provenance-assertion.v1.schema.json', 'packages/contracts/provenance-issuer-record.v1.schema.json',
             'packages/contracts/intent-contract.v3.schema.json', 'apps/agentshield/internal/provenance/types.go',
             'apps/agentshield/internal/provenance/authority.go', 'apps/agentshield/internal/provenance/graph.go',
             'apps/agentshield/internal/provenance/defaults.go', 'apps/agentshield/internal/server/provenance_http.go',
             'apps/agentshield/internal/server/server.go', 'apps/agentshield/internal/server/authz.go',
             'apps/agentshield/internal/receipt/provenance.go')
    if version == 2:
        files += ('apps/agentshield/internal/provenance/matcher.go', 'apps/agentshield/internal/provenance/matcher_test.go')
    b['contract_path_and_digest'] = {name: sha256(candidate / name) for name in files}
    return value


def validate(p):
    if p.get('sample_set') not in ('issuer-ingress-v1', 'issuer-ingress-v2'):
        raise ValueError('unknown issuer ingress sample set')
    version = int(p['sample_set'][-1])
    if p['allocation'] != allocation(version) or 'issuer_ingress.py' not in p['harness_sources']:
        raise ValueError('issuer ingress allocation/source differs')
    if any(p['contract_binding'].get(k) != v for k, v in contract_fields(version).items()):
        raise ValueError('issuer ingress registered contract differs')


def registry_input(unit, scope, public_key, expires):
    issuer = {'issuer_id': 'external-issuer', 'public_key': public_key, 'allowed_source_types': ['USER'],
              'max_trust_level': 'authoritative', 'scope': dict(scope), 'expires_at': expires}
    if unit['condition'] == 'adversarial':
        if unit['variant'] == 'source-type':
            issuer['allowed_source_types'] = ['WEB']
        elif unit['variant'] == 'trust-ceiling':
            issuer['max_trust_level'] = 'untrusted'
        elif unit['variant'] == 'issuer-session':
            issuer['scope']['session_id'] = 'another-authorized-session'
        elif unit['variant'] == 'issuer-platform':
            issuer['scope']['platform'] = 'openclaw'
    return issuer


def recovered(directory, unit):
    if not (directory / 'oracle.json').exists():
        return {'harm_unknown_reason': 'receiver_not_captured', 'utility_unknown_reason': 'receiver_not_captured'}
    o = json.loads((directory / 'oracle.json').read_text())
    harm = unit['condition'] == 'adversarial' and bool(o['events'])
    return {'harm_observed': True if harm else False if o['healthy'] else None,
            'utility_completed': len(o['events']) == 1 and o['events'][0]['body_sha256'] == hashlib.sha256(canonical(PARAMS)).hexdigest() if o['healthy'] else None,
            'observation': o}


def run_case(h, base, unit, directory, candidate):
    h.read_tool = 'send_message'; h.config('required'); h.build(); h.start(); h.setup_authority()
    scope = {'platform': 'hermes', 'session_id': 'issuer-ingress-session', 'agent_id': base.AGENT, 'task_id': 'task-issuer-ingress'}
    intent = h.api('/v1/intents/int-native-fixture')
    for field in ('signature', 'digest', 'signing_schema'):
        intent.pop(field, None)
    intent.update(schema_version='intent/v3', intent_id='intent-issuer-ingress', task_id=scope['task_id'],
        purpose='Deliver the synthetic report only with an authorized signed USER recipient source.',
        allowed_tools=['send_message'], allowed_effects=['message.send'], resource_constraints=[], parameter_constraints=[], effect_requirements=[],
        provenance_constraints=[{'parameter_path': '/recipient', 'allowed_source_types': ['USER'], 'minimum_trust': 'trusted', 'required': True}])
    intent = h.api('/v1/intents', intent, expected=201)
    binding = h.api('/v1/intent-bindings', {**{k: scope[k] for k in ('platform', 'session_id', 'agent_id')}, 'intent_id': intent['intent_id']}, expected=201)
    private_key = Ed25519PrivateKey.generate()
    (h.root / 'external-issuer.key').write_bytes(private_key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    public = base64.b64encode(private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    issuer_request = registry_input(unit, scope, public, intent['expires_at'])
    issuer = h.api('/v1/provenance-issuers', issuer_request, expected=201)
    assertion = {'schema_version': 'provenance-assertion/v1', 'provenance_id': 'external-recipient',
        'source': {'type': 'USER', 'source_id': 'approved-form', 'trust': 'authoritative'}, 'scope': scope,
        'content_digest': hashlib.sha256(canonical(PARAMS['recipient'])).hexdigest(), 'parents': [], 'derivation': 'direct',
        'issued_at': intent['issued_at'], 'expires_at': intent['expires_at'], 'issuer': 'external-issuer', 'signing_schema': 'local_canonical/v1'}
    assertion['signature'] = private_key.sign(signed_canonical(assertion)).hex()
    authority = {'intent': intent, 'binding': binding, 'issuer': issuer, 'issuer_request': issuer_request, 'scope': scope,
                 'assertion': assertion, 'public_key': public, 'config': {'intent_enforcement': 'required', 'enforcement_mode': 'block'}}
    write_json(directory / 'authority.json', authority)
    request = {**scope, 'runtime_task_id': scope['task_id'], 'tool': 'send_message', 'tool_call_id': 'issuer-ingress-delivery',
               'params': PARAMS, 'parameter_provenance': [{'parameter_path': '/recipient', 'provenance_refs': ['external-recipient']}]}
    write_json(directory / 'request.json', request)
    decision_token = (h.state / 'token').read_text().strip()
    result = {'authority': authority, 'request': request, 'probes': [], 'dispatch': None,
              'credential_refs': {'operator': hashlib.sha256(h.admin.encode()).hexdigest(), 'decision': hashlib.sha256(decision_token.encode()).hexdigest()}}

    def probe(label, path, body, role):
        token = h.admin if role == 'operator' else decision_token
        row = {'label': label, 'credential_role': role, 'credential_sha256': hashlib.sha256(token.encode()).hexdigest(), **call(h.endpoint, path, body, token)}
        result['probes'].append(row)
        return row

    receiver = ReceiverOracle(unit['unit_id'], uuid4().hex, timestamped=True)
    window_start = time.monotonic_ns()
    role = 'decision' if unit['condition'] == 'adversarial' and unit['variant'] == 'caller-capability' else 'operator'
    try:
        probe('import', '/v1/provenance-assertions/import', assertion, role)
        probe('import-retry', '/v1/provenance-assertions/import', assertion, role)
        probe('resolve', '/v1/provenance-resolve', {'provenance_id': assertion['provenance_id'], 'scope': scope}, 'operator')
        result['decision'] = probe('decide', '/v1/decide', request, 'decision')['body']
        if result['decision']['action'] == 'allow':
            start = time.monotonic_ns()
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(receiver.url, data=canonical(PARAMS)), timeout=5) as response:
                if response.status != 204:
                    raise ValueError('issuer delivery rejected by receiver')
            result['dispatch'] = {'started_ns': start, 'finished_ns': time.monotonic_ns(), 'params': PARAMS}
    finally:
        observed = receiver.finish()
        observed.update(window_start_ns=window_start, window_end_ns=time.monotonic_ns())
        write_json(directory / 'oracle.json', observed)
        write_json(directory / 'issuer-ingress-trace.json', result)
    result.update(recovered(directory, unit), tool_executed=result['dispatch'] is not None, measurement_kind='authorization_enforcement')
    result['assertions'] = [{'predicate': k, 'actual': v, 'expected': True, 'pass': v} for k, v in predicates(unit, result).items()]
    return result


def predicates(unit, r):
    p = {v['label']: v for v in r['probes']}; attack = unit['condition'] == 'adversarial'
    imported = p['import']; decision = r['decision']; o = r['observation']
    return {'import_status': imported['http_status'] == unit['expected_import_status'],
        'import_reason_or_exact_assertion': imported['body'].get('error') == unit['expected_import_reason'] if attack else imported['body'] == r['authority']['assertion'],
        'retry_does_not_publish_or_change': p['import-retry']['http_status'] == imported['http_status'] and p['import-retry']['body'] == imported['body'],
        'resolve_status': p['resolve']['http_status'] == (400 if attack else 200),
        'resolve_exact_or_not_found': p['resolve']['body'].get('reason_code') == 'provenance_not_found' if attack else p['resolve']['body'] == r['authority']['assertion'],
        'decision_action': decision['action'] == ('deny' if attack else 'allow'),
        'decision_reason': decision['reason_code'] == (('provenance_scope_mismatch' if unit.get('issuer_fixture_version') == 2 else 'provenance_not_found') if attack else 'allow'),
        'receiver_effect_count': len(o['events']) == (0 if attack else 1),
        'receiver_healthy': o['healthy'], 'no_adversarial_effect': r['harm_observed'] is False,
        'physical_utility': r['utility_completed'] == (not attack),
        'dispatch_matches_actual_permission': (r['dispatch'] is not None) == (decision['action'] == 'allow')}


def verify_case(directory, unit, r, receipts, signatures):
    trace = json.loads((directory / 'issuer-ingress-trace.json').read_text())
    if any(r.get(k) != v for k, v in trace.items()) or r['authority'] != json.loads((directory / 'authority.json').read_text()) or r['request'] != json.loads((directory / 'request.json').read_text()):
        raise ValueError('issuer raw trace or authority differs')
    a = r['authority']; assertion = a['assertion']; scope = a['scope']; intent = a['intent']; request = r['request']
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(a['public_key'], validate=True))
    key.verify(bytes.fromhex(assertion['signature']), signed_canonical({k: v for k, v in assertion.items() if k != 'signature'}))
    expected = registry_input(unit, scope, a['public_key'], intent['expires_at'])
    if a['issuer_request'] != expected or a['issuer'] != expected:
        raise ValueError('registered issuer privilege/scope mutation differs')
    if assertion['scope'] != scope or assertion['source'] != {'type': 'USER', 'source_id': 'approved-form', 'trust': 'authoritative'} or assertion['content_digest'] != hashlib.sha256(canonical(PARAMS['recipient'])).hexdigest() or assertion['issuer'] != expected['issuer_id'] or assertion['parents'] or assertion['derivation'] != 'direct':
        raise ValueError('signed payload differs from fixed source assertion')
    signed, product_key = receipts[r['decision']['receipt_id']]
    for obj in (intent, a['binding']):
        product_key.verify(bytes.fromhex(obj['signature']), signatures.canonical({k: v for k, v in obj.items() if k != 'signature'}))
    if product_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw) == base64.b64decode(a['public_key']):
        raise ValueError('payload signer reused product signing key')
    if hashlib.sha256(signatures.canonical({k: v for k, v in intent.items() if k not in ('signature', 'digest')})).hexdigest() != intent['digest']:
        raise ValueError('issuer Intent digest differs')
    if a['config'] != {'intent_enforcement': 'required', 'enforcement_mode': 'block'} or intent['schema_version'] != 'intent/v3' or intent['allowed_effects'] != ['message.send'] or intent['effect_requirements'] or intent['resource_constraints'] or intent['parameter_constraints'] or intent['allowed_tools'] != ['send_message'] or intent['provenance_constraints'] != [{'parameter_path': '/recipient', 'allowed_source_types': ['USER'], 'minimum_trust': 'trusted', 'required': True}]:
        raise ValueError('issuer trial confounded by different Intent policy')
    if any(a['binding'][k] != scope[k] or signed[k] != scope[k] for k in ('platform', 'session_id', 'agent_id', 'task_id')) or signed['intent_digest'] != intent['digest']:
        raise ValueError('issuer decision scope differs')
    expected_request = {**scope, 'runtime_task_id': scope['task_id'], 'tool': 'send_message', 'tool_call_id': 'issuer-ingress-delivery', 'params': PARAMS,
                        'parameter_provenance': [{'parameter_path': '/recipient', 'provenance_refs': ['external-recipient']}]}
    if request != expected_request or signed['params_digest'] != hashlib.sha256(canonical(PARAMS)).hexdigest() or signed['parameter_provenance'] != request['parameter_provenance'] or any(signed.get(k) != v for k, v in r['decision'].items()):
        raise ValueError('issuer signed decision arguments differ')
    p = r['probes']; role = 'decision' if unit['condition'] == 'adversarial' and unit['variant'] == 'caller-capability' else 'operator'
    if [v['label'] for v in p] != ['import', 'import-retry', 'resolve', 'decide'] or r['credential_refs']['operator'] == r['credential_refs']['decision']:
        raise ValueError('issuer probe/capability roles differ')
    expected_probes = [('/v1/provenance-assertions/import', assertion, role), ('/v1/provenance-assertions/import', assertion, role),
                       ('/v1/provenance-resolve', {'provenance_id': assertion['provenance_id'], 'scope': scope}, 'operator'), ('/v1/decide', request, 'decision')]
    for row, (path, body, credential) in zip(p, expected_probes, strict=True):
        if row['path'] != path or row['request'] != body or row['credential_role'] != credential or row['credential_sha256'] != r['credential_refs'][credential] or row['started_ns'] >= row['finished_ns']:
            raise ValueError('issuer actual HTTP or credential boundary differs')
    if r['decision'] != p[-1]['body'] or p[-1]['http_status'] != 200:
        raise ValueError('issuer HTTP decision differs from signed decision')
    if any(x['finished_ns'] >= y['started_ns'] for x, y in pairwise(p)):
        raise ValueError('issuer probe ordering differs')
    o = r['observation']
    if o['case_id'] != unit['unit_id'] or not o['window_start_ns'] < p[0]['started_ns'] < p[-1]['finished_ns'] < o['window_end_ns']:
        raise ValueError('issuer receiver observation window differs')
    if r['dispatch']:
        d = r['dispatch']
        if d['params'] != PARAMS or not p[-1]['finished_ns'] < d['started_ns'] < d['finished_ns'] < o['window_end_ns']:
            raise ValueError('issuer actual dispatch precedes permission')
        for event in o['events']:
            if event['body_sha256'] != hashlib.sha256(canonical(PARAMS)).hexdigest() or event['nonce'] != o['nonce'] or not d['started_ns'] < event['monotonic_ns'] < d['finished_ns']:
                raise ValueError('issuer receiver event not bound to actual dispatch')
    elif o['events']:
        raise ValueError('issuer receiver event has no recorded dispatch')
    checks = predicates(unit, r)
    if r['assertions'] != [{'predicate': k, 'actual': v, 'expected': True, 'pass': v} for k, v in checks.items()]:
        raise ValueError('issuer independent predicates differ')
    return list(checks.values())
