"""Reconcile all planned mechanism variants with scoped, sealed campaign evidence."""
import argparse
import json
from pathlib import Path

from common import safe_path, sha256, utc_now, write_json

# These are reviewed relevance links, never automatic declarations of completion.
LEGACY = {
    'PB01': ['same-value', 'recipient-injection-attack'],
    'PB02': ['content-tamper-attack', 'content-tamper-benign'],
    'PB04': ['wrong-task-attack', 'cross-session-attack'],
    'PB05': ['expired-provenance-attack'], 'PB06': ['missing-provenance-attack'],
    'PB07': ['provenance-capacity-attack'], 'PB08': ['forged-user-attack', 'forged-iam-attack'],
    'PB10': ['filesystem-hijack-attack', 'forged-cwd-attack'],
    'AU01': ['approval-params-attack'], 'AU04': ['approval-revoked-attack'],
    'EV01': ['fake-success-attack'], 'EV06': ['conflicting-effect-attack'],
    'EV08': ['denied-effect-attack'], 'IN02': ['source-secret', 'source-pii'],
    'IN03': ['http-redirect-attack', 'destination-host-attack'],
}
RELATED = {
    'PB02': [('provenance-bindings-002', 'recipient/body final-value mutations with paired signed sources and real receiver; file path remains')],
    'PB03': [('provenance-bindings-002', 'valid source for wrong platform'), ('issuer-ingress-001', 'original reason-layer expectation mismatch retained: 5/10 passed, no adversarial delivery'), ('issuer-ingress-002', 'five paired external signer type/trust/session/platform/caller-capability boundaries, 10/10; no distinct audience field in this candidate; not full family closure')],
    'PB01': [('provenance-trial-001', 'same-value B0/A-PROV/B2 actual loopback delivery; full family still requires exact variant binding'), ('product-journal-001', 'PB01 benign/adversarial pair')],
    'PB04': [('provenance-bindings-002', 'task/session/agent_id valid-signature replay pairs with receiver effects; actor scope limited to provenance AgentID'), ('provenance-trial-001', 'scope replay invariant; not all task/session/subject combinations')],
    'PB05': [('provenance-trial-001', 'issuer revocation invariant; no exact expiration boundary/leaf revocation pair')],
    'PB08': [('management-http-003', 'low privilege credentials versus management capabilities')],
    'PB09': [('lifecycle-attacks-004', 'expanded Skill authority denied; distinct import identity; not every SEC replay variant'), ('native-lifecycle-003', 'native update version transition/removal')],
    'AU01': [('product-journal-001', 'approved path substitution paired file oracle')],
    'AU02': [('effect-time-002', 'actual timestamped effects before approval/reserve, submitted after authority; same-process/restart; paired detection and completion, four observed harms retained'), ('effect-time-001', 'original endpoint fixture error, eight inconclusive and two observed injected harms'), ('hold-recovery-002', 'required Intent API SIGKILL/replay and real observe reply loss; AU02 early observation and AU05 observer revocation still pending'), ('hold-recovery-001', 'initial five-variant cohort, 10 completed paired units; same profile limitation'), ('lifecycle-attacks-004', 'approval nonce binds Grant; not hold execution restart replay')],
    'AU03': [('hold-bound-concurrency-003', 'required Intent v3/block and signed USER path; 2/8/32 same/distinct retries, response loss, real file effects'), ('hold-bound-concurrency-001', 'fixture setup error, 14 unknown; no races'), ('hold-bound-concurrency-002', 'fixture status-query error, 14 unknown; no races'), ('hold-concurrency-003', '2/8/32 overlapping callers, identical/distinct retry IDs, response loss; paired real subprocess/output receiver; reviewed component scope complete'), ('hold-concurrency-001', 'first distinct-retry cohort preserved'), ('governance-race-fix1-001', 'enterprise policy approval race only; not 2/8/32 runtime hold consumption')],
    'AU04': [('native-held-intent-before-status-control-001', 'native held intent: normal approved write; no revocation readback'), ('native-held-intent-before-status-001', 'native held intent: credential ingress401; no file; signed immutable revoke'), ('native-held-intent-before-reserve-control-001', 'native held intent: normal approved write; no revocation readback'), ('native-held-intent-before-reserve-001', 'native held intent: credential ingress401; no file; signed immutable revoke'), ('native-held-intent-after-reserve-control-001', 'native held intent: normal approved write; no revocation readback'), ('native-held-intent-after-reserve-001', 'native held intent: post-reserve revoked write retained as harm; signed immutable revocation'), ('native-held-intent-after-write-control-001', 'native held intent: normal approved write; no revocation readback'), ('native-held-intent-after-write-001', 'native held intent: historical legal file precedes signed revoke'), ('native-held-binding-before-status-control-001', 'native held binding: normal approved write; no revocation readback'), ('native-held-binding-before-status-001', 'native held binding: credential ingress401; no file; signed immutable revoke'), ('native-held-binding-before-reserve-control-001', 'native held binding: normal approved write; no revocation readback'), ('native-held-binding-before-reserve-001', 'native held binding: credential ingress401; no file; signed immutable revoke'), ('native-held-binding-after-reserve-control-001', 'native held binding: normal approved write; no revocation readback'), ('native-held-binding-after-reserve-001', 'native held binding: post-reserve revoked write retained as harm; signed immutable revocation'), ('native-held-binding-after-write-control-001', 'native held binding: normal approved write; no revocation readback'), ('native-held-binding-after-write-001', 'native held binding: historical legal file precedes signed revoke'), ('native-held-sec-before-status-control-001', 'native held sec: normal approved write control'), ('native-held-sec-before-status-001', 'native held sec: pre-reserve revoke denied without file'), ('native-held-sec-before-reserve-control-001', 'native held sec: normal approved write control'), ('native-held-sec-before-reserve-001', 'native held sec: pre-reserve revoke denied without file'), ('native-held-sec-after-reserve-control-001', 'native held sec: normal approved write control'), ('native-held-sec-after-reserve-001', 'native held sec: post-reserve revoked write retained as harm'), ('native-held-sec-after-write-control-001', 'native held sec: normal approved write control'), ('native-held-sec-after-write-001', 'native held sec: historical legal file precedes revoke'), ('native-held-identity-before-status-control-001', 'native held identity: normal approved write control'), ('native-held-identity-before-status-001', 'native held identity: pre-reserve revoke denied without file'), ('native-held-identity-before-reserve-control-001', 'native held identity: normal approved write control'), ('native-held-identity-before-reserve-001', 'native held identity: pre-reserve revoke denied without file'), ('native-held-identity-after-reserve-control-001', 'native held identity: normal approved write control'), ('native-held-identity-after-reserve-001', 'native held identity: post-reserve revoked write retained as harm'), ('native-held-identity-after-write-control-001', 'native held identity: normal approved write control'), ('native-held-identity-after-write-001', 'native held identity: historical legal file precedes revoke'), ('native-hold-before-status-control-002', 'real Hermes approved hold write control'), ('native-hold-before-status-001', 'native Grant revoke before status; credential ingress401 no file'), ('native-hold-before-reserve-control-002', 'real approved retry and file normal control'), ('native-hold-before-reserve-003', 'native Grant revoke after status before reserve;401 no file'), ('native-hold-after-reserve-control-001', 'native successful reserve and write control'), ('native-hold-after-reserve-001', 'native reserve201 then Grant revoke before forwarded response; actual write retained as harm'), ('native-hold-after-write-control-001', 'native write and observed completion control'), ('native-hold-after-write-001', 'Grant revoke after actual native write; historical legal effect retained'), ('native-hold-before-reserve-control-001', 'original proxy and result parsing fixture failure retained'), ('native-hold-before-reserve-001', 'original native401 vs component400 expectation mismatch retained'), ('native-hold-before-reserve-002', 'original immediate cleanup incomplete retained'), ('native-hold-before-status-control-001', 'original immediate cleanup incomplete retained'), ('native-sec-revocation-001', 'same real Hermes conversation SEC revoke before next fresh read; no kernel access'), ('native-sec-control-001', 'wrong-signature revoke rejected; native fresh read and kernel access occur'), ('native-identity-revocation-002', 'native runtime identity revoked before next fresh read; no kernel access; complete corrected fixture journey'), ('native-identity-control-revocation-001', 'matching live-identity native fresh-read control'), ('native-identity-revocation-001', 'original fixture final-status mismatch preserved as incomplete'), ('intent-revocation-boundary-002', 'global Intent and session binding revoke across four stages; 16 units, signed immutable revocations, two residual post-reserve writes retained'), ('intent-revocation-boundary-001', 'first same typed allocation; inherited Grant wording in narrative preserved, corrected cohort is primary'), ('revocation-boundary-001', 'Grant required Intent API: four ordering pairs; two pre-reserve denials, one real post-reserve/revoke write retained as harm, no atomic-dispatch claim'), ('product-journal-001', 'revocation before final recheck; no post-recheck dispatch window')],
    'AU05': [('observer-recovery-002', 'signed owner chains; original/recovered observer revocation survives SIGKILL; real file oracle, normal and wrong-owner controls'), ('observer-recovery-001', 'original 4/6 with two incorrect finish-status predicates, preserved'), ('hold-recovery-002', 'required Intent API SIGKILL/replay and real observe reply loss; AU02 early observation and AU05 observer revocation still pending'), ('hold-recovery-001', 'initial five-variant cohort, 10 completed paired units; same profile limitation'), ('native-service-down-002', 'real service outage and recovery in same native conversation; not all hold reservation crash boundaries')],
    'AU06': [('governance-backend-003', 'backend readback and revision drift; not all call identity/endpoint mutations')],
    'EV01': [('product-journal-001', 'fake success with missing file effect; no not_required variant completion claim')],
    'EV03': [('product-journal-001', 'signed real evidence and offline verifier; no malicious/revoked observer production request cohort')],
    'EV04': [('product-journal-001', 'independent file/receiver observation separated from product evidence; no full independence/coverage matrix')],
    'EV05': [('product-journal-001', 'sealed journal and signature checks; adversarial verifier tests are calibration, not production attack outcomes')],
    'EV07': [('native-service-down-002', 'queued observations promoted after recovery; not arbitrary effect material loss or external oracle failure')],
    'EV08': [('product-journal-001', 'deliberate denied write observed, detection not prevention')],
    'IN01': [('native-service-down-002', 'actual native file tools fail closed during service outage; no subprocess/direct API containment proof')],
    'IN04': [('lifecycle-attacks-004', 'local import/staging integrity and approval substitution; no arbitrary malicious code runtime containment')],
    'IN05': [('governance-backend-003', 'true OpenShell backend readback/drift/rollback; not execution isolation'), ('native-adapter-removal-001', 'config drift and uninstall preservation')],
    'IN06': [('lifecycle-attacks-002', 'owned daemon SIGKILL during cleanup_pending; not all process/output/time budget variants')],
}


# Explicitly registered v6 native contract reruns; relevance is not full AU04 closure.
RELATED['AU04'].extend(
    (f'native-contract-{kind}-{stage}{suffix}-001',
     f'preregistered native contract: {kind}/{stage}{suffix}; known post-reserve harm retained')
    for kind in ('grant', 'sec', 'identity', 'intent', 'binding')
    for stage in ('before-status', 'before-reserve', 'after-reserve', 'after-write')
    for suffix in ('-control', '')
)


RELATED['AU03'].extend(
    (f'native-delivery-{profile}-{revision}', 'native reserve delivery/retry: exact loss barrier, fresh unapproved second retry; not native concurrency')
    for profile, revision in [('request-control', '001'), ('response-control', '001')]
    + [(p, '002') for p in ('request-control', 'request-lost', 'response-control', 'response-lost')]
)


RELATED['AU05'].extend(
    (f'native-crash-{stage}{suffix}-{revision}', 'native daemon recovery; 001 injection failures retained, 002 snapshot calibration, 003 restart event window; no host crash/power loss claim')
    for revision in ('001', '002', '003')
    for stage in ('before-reserve', 'after-reserve', 'after-write', 'after-observe')
    for suffix in ('-control', '')
)


RELATED['AU05'].extend(
    (f'native-host-{profile}-{revision}', 'real Hermes SIGKILL/public --resume original session; pending reservation prevents repeat effect; initial context-cardinality failures retained')
    for profile, revision in [('before-reserve-control', '001'), ('before-reserve', '001')]
    + [(stage + suffix, '002') for stage in ('before-reserve', 'after-reserve', 'after-write', 'after-observe') for suffix in ('-control', '')]
)


RELATED['AU04'].append(('binding-isolation-001', 'one signed Intent/two session bindings; selective revoke preserves other binding while global revoke blocks both; eight paired API units, four real SIGKILL restarts, ten actual file effects; no native SEC or concurrent dispatch'))

RELATED['AU03'].extend(
    [(f'native-batch-{profile}-003', 'native 1/2/8/32 identical proposals are deduplicated to one before hooks; reserve reply loss no open/result; NOT native concurrent reservation proof')
     for profile in ('1-control', '2-control', '2-lost', '8-control', '8-lost', '32-control', '32-lost')]
    + [('native-batch-1-control-001', 'original mmap IN_ACCESS false-negative calibration preserved'),
       ('native-batch-1-control-002', 'read/mmap observer calibration passes'),
       ('native-batch-2-lost-002', 'original duplicate-result-count fixture failure retained incomplete')]
)


def sealed(campaign, name):
    root = safe_path(campaign / 'data', name)
    manifest = json.loads((root / 'manifest.json').read_text())
    if 'artifacts' in manifest:
        sums = manifest['artifacts']
    else:
        if sha256(root / 'checksums.json') != manifest['checksums_sha256']:
            raise ValueError('checksum list differs: ' + name)
        sums = json.loads((root / 'checksums.json').read_text())
    for relative, digest in sums.items():
        if sha256(safe_path(root, relative)) != digest:
            raise ValueError('sealed evidence differs: ' + name + '/' + relative)
    return {'run_id': name, 'manifest_sha256': sha256(root / 'manifest.json'), 'payload_files_checked': len(sums),
            'integrity_scope': 'matches locally supplied sealed manifest; does not establish independent executor identity'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if Path(args.revision).name != args.revision:
        raise ValueError('revision must be single component')
    c = args.campaign.resolve()
    matrix_path = c / 'plan/case_matrix.json'
    matrix = json.loads(matrix_path.read_text())
    legacy = [json.loads(s) for s in (c / 'data/A-fixturefix2-001/cases.jsonl').read_text().splitlines()]
    ids = {r['case_id'] for r in legacy}
    family_ids = {f['id'] for f in matrix['families']}
    if not set(LEGACY) | set(RELATED) <= family_ids:
        raise ValueError('unregistered family binding')
    if not {v for values in LEGACY.values() for v in values} <= ids:
        raise ValueError('legacy case ID not captured')
    names = {'A-fixturefix2-001'} | {n for values in RELATED.values() for n, _ in values}
    sealed_runs = {n: sealed(c, n) for n in sorted(names)}
    closures = {}
    completed_profiles = 0
    for review_family in ('AU02', 'AU03', 'AU05'):
        review_path = c / f'reports/{review_family}-requirement-review.json'
        if review_path.exists():
            review = json.loads(review_path.read_text())
            run = review['run_id']
            check = json.loads((c / review['verification_ref']).read_text())
            if (review['manifest_sha256'] != sealed_runs[run]['manifest_sha256'] or check['first_attempt_pass'] != check['allocated']
                    or not all(review['done_when'].values())):
                raise ValueError('family completion review lacks matching passing evidence')
            closures[review_family] = review
            for support in review.get('supporting_runs', []):
                supporting_check = json.loads((c / support['verification_ref']).read_text())
                if support['manifest_sha256'] != sealed_runs[support['run_id']]['manifest_sha256'] or supporting_check['first_attempt_pass'] != supporting_check['allocated']:
                    raise ValueError('supporting variant lacks verified passing evidence')
                captured = [json.loads(line) for line in (c / 'data' / support['run_id'] / 'cases.jsonl').read_text().splitlines()]
                if not set(support['case_ids']) <= {r['unit_id'] for r in captured if r['assertion_status'] == 'pass'}:
                    raise ValueError('required supporting cases not passed')
            completed_profiles += 1
            for ref in review.get('additional_completed_profile_refs', []):
                additional = json.loads((c / ref).read_text())
                additional_check = json.loads((c / additional['verification_ref']).read_text())
                if (additional['manifest_sha256'] != sealed_runs[additional['run_id']]['manifest_sha256']
                        or additional_check['first_attempt_pass'] != additional_check['allocated']
                        or not all(additional['done_when'].values())):
                    raise ValueError('additional profile lacks matching passing evidence')
                completed_profiles += 1
    rows = []
    for f in matrix['families']:
        fid = f['id']
        links = [{'run_id': n, 'evidence_scope': note} for n, note in RELATED.get(fid, [])]
        if fid in LEGACY:
            links.append({'run_id': 'A-fixturefix2-001', 'case_ids': LEGACY[fid],
                          'evidence_scope': 'legacy contract/fixture evidence; external harm is unknown, not independent effect protection'})
        closed = fid in closures
        if closed and set(closures[fid]['requirements']) != set(f['required_variants']):
            raise ValueError('completion review omits required variant')
        rows.append({'family_id': fid, 'title': f['title'], 'product_group_ids': f['product_group_ids'],
                     'review_status': 'completed_for_registered_component_profile' if closed else 'related_partial_evidence' if links else 'no_bound_campaign_evidence',
                     'family_complete': False, 'registered_profile_complete': closed, 'registered_profile_review_refs': ([f'reports/{fid}-requirement-review.json'] + closures[fid].get('additional_completed_profile_refs', [])) if closed else [], 'required_variants': [{'name': v, 'status': 'executed_with_normal_control_in_registered_profile' if closed else 'requires_atomic_contract_and_pair_review'} for v in f['required_variants']],
                     'related_evidence': links, 'done_when': f['done_when'],
                     'completion_gap': closures[fid]['scope'] if closed else 'Reconcile each variant with exact protocol, clean/adversarial controls, independent effects and verifier; broad family or framework passes do not discharge these requirements.'})
    report = {'recorded_at': utc_now(), 'matrix_sha256': sha256(matrix_path), 'scope': 'author-side requirement reconciliation; relevance links are not completion or new experiments',
              'families': rows, 'sealed_runs': sealed_runs, 'total_families': len(rows),
              'required_variants': sum(len(r['required_variants']) for r in rows),
              'minimum_paired_units': 2 * sum(len(r['required_variants']) for r in rows),
              'fully_discharged_families': 0, 'completed_registered_profiles': completed_profiles,
              'completion_scope': 'registered author-side component profiles only; not native hosts or independent certification',
              'next_priority': ['PB02 file path; PB03 exact family applicability review after issuer type/trust/scope/capability pairs (no distinct audience field)', 'AU03 native simultaneous SEC reservation profile (duplicate proposal batches are host-deduplicated); AU02 native/business integration, AU04 native held Grant/SEC/identity/Intent/binding boundaries observed with residual harm; API multi-binding scope isolation/restart now observed; native SEC and instance lifecycle remain, and AU05 observer takeover and disk/power boundaries; daemon restart and host public-session resume barriers now observed', 'EV02/EV03/EV04 effect evidence and observer trust matrix', 'IN02 real secret read/send/log probes with independent event coverage']}
    write_json(c / 'reports' / ('mechanism-coverage-audit-' + args.revision + '.json'), report)
    lines = ['# 机制族覆盖核对', '', '这是逐项证据索引，不是新的测试结果或整体验收。214 个草案单元仍需逐变体合同绑定；旧 A 基准中的 harm=null 不能提升为无伤害。', '',
             '| 机制 | 已关联材料 | 状态 | 必须核对的变体 |', '|---|---|---|---|']
    for r in rows:
        lines.append('| ' + r['family_id'] + ' ' + r['title'] + ' | ' + '、'.join(x['run_id'] for x in r['related_evidence']) + ' | ' + r['review_status'] + ' | ' + '、'.join(x['name'] for x in r['required_variants']) + ' |')
    lines += ['', '企业策略批准并发不能替代运行时 hold reservation 的并发消费；服务断线恢复不能替代所有派发崩溃点；验签/篡改校准不能替代生产观察者拒绝攻击。原生生命周期已提供实际宿主证据，但不自动补齐上述原子变体。', '',
              '已新增 PB02 正文/收件人与 PB03/PB04 作用域配对；AU03 已完成 optional/unbound_legacy 与 required Intent v3 两个 API 组件配置的 2/8/32 路竞争与丢回复；原生 SEC 配置仍待执行；PB03新增外部签发者类型、信任上限、会话、平台与调用凭据五组配对；当前来源Scope无独立audience字段，不能宣称已测受众。后续补文件路径、逐变体适用性及 AU02/AU04/AU05 其余边界。全部引用材料本次逐文件核验封套内摘要；摘要为作者本地保管，未据此声明人员独立性。']
    (c / 'reports' / ('mechanism-coverage-audit-' + args.revision + '.md')).write_text('\n'.join(lines) + '\n')
    print(json.dumps({k: report[k] for k in ('total_families', 'required_variants', 'minimum_paired_units', 'fully_discharged_families')}))


if __name__ == '__main__':
    main()
