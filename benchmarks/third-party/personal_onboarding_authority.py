"""Independent signed and byte-level joins for one personal onboarding journey."""
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from native_business_scoring import transcript


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sec_grant_digest(grant):
    # The fixed candidate's skillcontext.GrantDigest uses json.Unmarshal into
    # map[string]any (float64), unlike canon.Decode used for signed documents.
    # Preserve that exact wire contract; do not apply this to signatures.
    def decoded(value):
        if type(value) is int:
            return float(value)
        if isinstance(value, dict):
            return {k: decoded(v) for k, v in value.items()}
        if isinstance(value, list):
            return [decoded(v) for v in value]
        return value
    return digest(decoded(grant))


def verify_authority(raw, *, owners=True):
    obs, http = raw['onboarding_observation'], raw['management_http']
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['receipts']['public_key'], validate=True))
    signed_count = 0

    def signed(document):
        nonlocal signed_count
        key.verify(bytes.fromhex(document['signature']), canonical({k: v for k, v in document.items() if k != 'signature'}))
        signed_count += 1

    def unique(predicate):
        matches = [(i, row) for i, row in enumerate(http) if predicate(row)]
        require(len(matches) == 1, 'unique management transition required')
        return matches[0]

    discover_index, _ = unique(lambda r: r['route'] == '/v1/discovery/scan')
    imports = {}
    for kind, stage in [('normal', 'good_import'), ('quarantined', 'bad_import')]:
        result = obs['stages'][stage]
        record, admission = result['import'], result['admission']
        signed(record)
        signed(admission)
        index, row = unique(lambda r, rid=record['import_id']: r['route'] == '/v1/skill-imports' and r.get('request', {}).get('import_id') == rid)
        source = str(Path(obs['source_root']) / kind / 'intent-fixture')
        import_path = source
        if 'zip_sources' in obs:
            from zip_source_authority import verify_archive_source
            import_path = verify_archive_source(obs, kind, record)
        asset = obs['selected_assets'][kind]
        require(row['response'] == result and discover_index < index and row['request']['path'] == import_path, 'discovery/import order or actual source path differs')
        require(asset in obs['stages']['discovery']['assets']['assets'] and asset['source_locator'] == 'local://skills/' + source, 'import is not the actually discovered asset')
        require(record['source_locator_digest'] == hashlib.sha256(import_path.encode()).hexdigest(), 'signed source locator digest differs')
        actual = {f['path']: {k: v for k, v in f.items() if k != 'path'} for f in record['files']}
        require(actual == obs['sources_before'][kind] == obs['sources_after'][kind], 'signed import files differ from actual source bytes')
        require(record['artifact_digest'] == digest({'directories': record['directories'], 'files': record['files']}), 'signed artifact tree digest differs')
        manifest = [{k: f[k] for k in ('path', 'sha256', 'bytes')} for f in record['files']]
        require(admission['file_manifest'] == manifest, 'admission manifest differs from imported files')
        content = ''.join(f"{f['path']}\n{f['sha256']}\n{f['bytes']}\n" for f in manifest)
        require(admission['content_hash'] == hashlib.sha256(content.encode()).hexdigest(), 'admission content hash differs')
        imports[kind] = (record, admission, index)
    good, admission, good_index = imports['normal']
    bad, _, bad_index = imports['quarantined']
    reject_index, reject = unique(lambda r: r['route'] == '/v1/skill-imports/' + bad['import_id'] + '/permissions')
    require(bad_index < reject_index < good_index and reject['response'] == obs['stages']['bad_permission'], 'quarantine rejection is not linked to the bad import')
    permission_index, permission = unique(lambda r: r['route'] == '/v1/skill-imports/' + good['import_id'] + '/permissions')
    source = permission['response']['source']
    require(source == {'schema_version': 'local-skill-import-permission-source/v1', 'import_id': good['import_id'], 'artifact_digest': good['artifact_digest'], 'analysis_sha256': good['analysis_sha256']}, 'permission source identity differs')
    pending = permission['response']['grant']
    signed(pending)
    require(pending['status'] == 'pending_approval' and pending['admission_id'] == 'adm-si-' + digest(source), 'discovered/imported content inherited approval')
    gid = pending['grant_id']
    challenge_index, challenge = unique(lambda r: r['route'] == '/v1/grants/' + gid + '/challenge')
    approve_index, approve = unique(lambda r: r['route'] == '/v1/grants/' + gid + '/approve')
    grant = approve['response']['grant']
    signed(grant)
    require(good_index < permission_index < challenge_index < approve_index and approve['request']['challenge_id'] == challenge['response']['challenge']['challenge_id'], 'approval challenge not linked in order')
    require(grant['status'] == 'approved' and grant['admission_id'] == pending['admission_id'] and grant['skill']['content_hash'] == admission['content_hash'], 'approved grant not bound to imported content')
    public = str(Path(raw['gold']['source_path']).parent)
    expected = {('tool', 'tool.invoke', 'read_file'), ('tool', 'tool.invoke', 'write_file'), ('filesystem', 'fs.read', public), ('filesystem', 'fs.write', public)}
    actual = {(f['domain'], f['action'], f['resource']['value']) for f in grant['facts'] if f['effect'] == 'allow'}
    require(actual == expected and len(grant['facts']) == 4 and grant['default_effect'] == 'deny' and grant['enforcement_mode'] == 'block', 'approved permissions widened')
    install_index, installed = unique(lambda r: r['route'] == '/v1/skill-installations/apply')
    installed = installed['response']
    plan, operation = installed['plan'], installed['operation']
    signed(plan)
    signed(operation)
    require(approve_index < install_index and plan['source'] == source and plan['grant_id'] == gid and plan['grant_signature'] == grant['signature'], 'install is not the approved source/grant')
    require(operation['install_id'] == installed['install_id'] and operation['plan_id'] == plan['plan_id'] and operation['claim_signature'] == installed['claim_signature'], 'operation identity differs')
    activation_index, activation = unique(lambda r: r['route'] == '/v1/skill-installations/operations/' + installed['install_id'] + '/activate')
    binding = activation['response']['binding']
    signed(binding)
    require(install_index < activation_index and binding['source'] == source and binding['plan_signature'] == plan['signature'] and binding['operation_signature'] == operation['signature'] and binding['approved_signature'] == grant['signature'], 'activation lineage differs')
    identity_index, identity_row = unique(lambda r: r['route'] == '/v1/runtime-identities' and r.get('request'))
    identity = identity_row['response']['identity']
    require(activation_index < identity_index and identity['instance_id'] == plan['instance_id'] == binding['instance_id'] and identity['grant_ref']['grant_id'] == gid and identity['grant_ref']['admission_id'] == grant['admission_id'], 'runtime identity differs from installed grant')
    sec_index, sec_row = unique(lambda r: r['route'] == '/v1/skill-contexts')
    sec = sec_row['response']
    signed(sec)
    require(identity_index < sec_index and sec['install'] == {'install_id': installed['install_id'], 'claim_signature': installed['claim_signature']} and sec['authority'] == {'grant_id': gid, 'grant_digest': sec_grant_digest(grant)} and sec['skill']['content_hash'] == admission['content_hash'], 'SEC is not bound to the actual installation/grant')
    calls, _, _ = transcript(raw)
    decisions = [r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision']
    for d in decisions:
        require(sec['subject'] == {'platform': d['platform'], 'instance_id': identity['instance_id'], 'agent_id': d['agent_id'], 'session_id': d['session_id'], 'task_id': d['runtime_task_id']}, 'native SEC subject differs from actual signed call')
        attribution = d['skill_attribution']
        payload = {k: d[k] for k in ('platform', 'session_id', 'agent_id', 'tool', 'tool_call_id')}
        payload.update(task_id=d['runtime_task_id'], params=calls[d['tool_call_id']]['params'])
        require(attribution['context_id'] == sec['context_id'] and attribution['content_hash'] == admission['content_hash'] and attribution['call_binding'] == digest(payload), 'signed call attribution differs from actual parameters/source')
    records = obs['stages']['final_installations']['items']
    require(len(records) == 1 and records[0]['install_id'] == installed['install_id'] and records[0]['plan'] == plan, 'unexpected installation or different final readback')
    if owners:
        for name, capture in obs['owner_records'].items():
            doc, raw_owner = capture['document'], capture['raw']
            require(json.loads(raw_owner) == doc and hashlib.sha256(raw_owner.encode()).hexdigest() == obs['installed_snapshot'][name]['sha256'], 'owner bytes differ from installed file')
            signed(doc)
            relative = str(Path(name).parent)
            require(doc['relative_directory'] == ('' if relative == '.' else relative) and doc['install_id'] == installed['install_id'] and doc['claim_signature'] == installed['claim_signature'], 'owner signature is from another installation/directory')
    return {'signed_documents_verified': signed_count, 'actual_decisions_bound': len(decisions), 'discovery_asset_ids': {k: v['id'] for k, v in obs['selected_assets'].items()},
            'import_id': good['import_id'], 'grant_id': gid, 'install_id': installed['install_id'], 'runtime_identity_id': identity['identity_id'], 'SEC_id': sec['context_id'],
            'scope': 'same actual source bytes and signed lineage; discovery observations and HTTP are author-captured; no nonce-equality or third-party identity claim'}
