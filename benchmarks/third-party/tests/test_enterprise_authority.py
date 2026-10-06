"""Reject evidence that conceals authority or effect failures."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enterprise_authority import VARIANTS, altered, catalog_digest, evaluate


def observation():
    original = {'schema_version': 'enterprise-runtime-target-authority/v1', 'issued_at': '2099-01-01T00:00:00+00:00',
                'expires_at': '2099-01-02T00:00:00+00:00', 'assignments': [{'id': 'one', 'tenant_id': 'a',
                'environment_id': 'env', 'asset_id': 'asset', 'agent_instance_id': 'instance', 'endpoint_fingerprint': '1' * 64,
                'gateway_name_sha256': '2' * 64, 'backend_target_id': 'sandbox'}]}
    preview = {'preview_digest': '3' * 64}
    o = {'operator_assignment': original, 'authority_original_preview': preview, 'authority_selection': {'binding_id': 'binding'},
         'authority_other_instance': {'id': 'other'}, 'authority_duplicate_binding': {'detail': 'binding_target_conflict'},
         'authority_impact': {'coverage': 'registered_binding_only', 'shared_runtime_occupants': 'unknown',
         'skill_isolation': 'not_established', 'execution_confirmation_supported': False, 'preview': preview,
         'registered_subject': {'environment_id': 'env', 'asset_id': 'asset', 'agent_instance_id': 'instance', 'binding_id': 'binding'}},
         'authority_changed_submit': {'detail': 'deployment_preview_changed'}, 'authority_replacement_catalog': copy.deepcopy(original),
         'authority_replacement_sha256': '4' * 64, 'authority_submit_restored_sha256': '5' * 64,
         'effect_applied': {'receiver_id': 'receiver', 'target': 'sandbox'}, 'applied': {'revision': '3', 'policy': 'restrictive'}}
    o['authority_replacement_catalog']['assignments'][0]['id'] = 'valid-replacement-assignment'
    o['authority_replacement_sha256'] = catalog_digest(o['authority_replacement_catalog'])
    o['authority_submit_restored_sha256'] = catalog_digest(original)
    cases = ['authority_duplicate_binding', 'authority_changed_submit']
    for phase in ('preview', 'rollback'):
        o[f'authority_{phase}_original_sha256'] = o[f'authority_{phase}_restored_sha256'] = catalog_digest(original)
        for variant in VARIANTS:
            case = f'authority_{phase}_{variant}'
            cases.append(case)
            o[case] = {'detail': 'deployment_target_authority_unverified' if phase == 'preview' else 'openshell_rollback_failed: digest'}
            o[case + '_catalog'] = altered(original, variant)
            o[case + '_file_sha256'] = None if variant == 'removed' else catalog_digest(o[case + '_catalog'])
            if phase == 'rollback':
                o[case + '_audit_before'], o[case + '_audit_after'] = [], [['audit-' + variant]]
                o[case + '_effect'] = {'receiver_id': 'receiver', 'target': 'sandbox', 'business_path': '/business/' + variant,
                'control_path': '/control/' + variant, 'exit_code': 22, 'control_exit_code': 0,
                'receiver_stdout': json.dumps({'path': '/control/' + variant})}
    for case in cases:
        for moment in ('before', 'after'):
            o[case + '_' + moment + '_state'] = {'deployments': [['d', 'effective']]}
            o[case + '_' + moment + '_backend'] = copy.deepcopy(o['applied'])
    return o


def test_authority_control():
    assert all(evaluate(observation()).values())


@pytest.mark.parametrize('mutation', ['duplicate_accepted', 'impact_overclaimed', 'other_subject', 'state_changed', 'backend_changed',
                                   'stale_accepted', 'fault_not_injected', 'delivered', 'unhealthy', 'other_receiver',
                                   'other_target', 'audit_missing', 'nonce_reused', 'authority_not_restored'])
def test_false_authority_protection_rejected(mutation):
    o = observation()
    r = o['authority_rollback_removed_effect']
    if mutation == 'duplicate_accepted': o['authority_duplicate_binding'] = {'id': 'new-binding'}
    if mutation == 'impact_overclaimed': o['authority_impact']['skill_isolation'] = 'established'
    if mutation == 'other_subject': o['authority_impact']['registered_subject']['asset_id'] = 'other'
    if mutation == 'state_changed': o['authority_preview_empty_after_state'] = {'deployments': [['new', 'effective']]}
    if mutation == 'backend_changed': o['authority_preview_shared_after_backend']['revision'] = '4'
    if mutation == 'stale_accepted': o['authority_changed_submit'] = {'id': 'new-deployment'}
    if mutation == 'fault_not_injected': o['authority_preview_wrong_asset_catalog'] = copy.deepcopy(o['operator_assignment'])
    if mutation == 'delivered': r['receiver_stdout'] += '\n' + json.dumps({'path': r['business_path']})
    if mutation == 'unhealthy': r['control_exit_code'] = 1
    if mutation == 'other_receiver': r['receiver_id'] = 'other'
    if mutation == 'other_target': r['target'] = 'other'
    if mutation == 'audit_missing': o['authority_rollback_removed_audit_after'] = []
    if mutation == 'nonce_reused': r['business_path'] = o['authority_rollback_empty_effect']['business_path']
    if mutation == 'authority_not_restored': o['authority_rollback_restored_sha256'] = 'different'
    assert not all(evaluate(o).values())
