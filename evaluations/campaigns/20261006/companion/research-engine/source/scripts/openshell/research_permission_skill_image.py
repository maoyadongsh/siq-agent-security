"""Build a separate analysis image with exact installed evaluation Skills.

Reuses the owning project's image verification and offline smoke gates. Does
not replace the daily candidate pointer or import any sibling implementation.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

import yaml

from scripts.openshell import build_qwen38_candidate_image as images

PLUGIN = 'research-permission-sync'
PROFILE = images.ROOT / 'data/hermes/home/profiles/siq_analysis'
SYNC = images.ROOT / 'scripts/openshell/fixtures/research_skill_sync.py'
OBSERVER_PATCH = images.ROOT / 'infra/openshell/patches/hermes-post-tool-observer-serialization.patch'
OBSERVER_PATCH_SHA = '7d5e82c64a4d3f103fa59b0123454a40b8738313255dc4ab4606012011029a24'
OBSERVER_SOURCE_SHA = '42be01f01014ae1a65b3dc879df687058b312c0226d596f902e03a3c1247c431'
OBSERVER_FIXED_SHA = 'e7bc316eab6cb8a4f9108a9537869138489dcd710a0fbf42d6c7e31908399112'


def patched_observer_source(raw):
    """Apply the reviewed Hermes export while retaining required policy gates."""
    if hashlib.sha256(raw).hexdigest() != OBSERVER_SOURCE_SHA:
        raise images.CandidateImageError('research_observer_base_source_mismatch')
    patch = images._file(OBSERVER_PATCH)
    if hashlib.sha256(patch).hexdigest() != OBSERVER_PATCH_SHA:
        raise images.CandidateImageError('research_observer_patch_mismatch')
    with tempfile.TemporaryDirectory(prefix='research-observer-patch-') as temporary:
        root = Path(temporary)
        source = root / 'hermes_cli/plugins.py'
        source.parent.mkdir()
        source.write_bytes(raw)
        result = subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], input=patch,
                                cwd=root, capture_output=True, timeout=15, check=False)
        fixed = source.read_bytes()
        if result.returncode or hashlib.sha256(fixed).hexdigest() != OBSERVER_FIXED_SHA:
            raise images.CandidateImageError('research_observer_patch_application_mismatch')
        return fixed


def installed_bytes(path, expected_sha256):
    # The public SIQ installer publishes read-only hardlinks. Validate their
    # pinned content without importing the generic image-source nlink=1 rule.
    if path.resolve(strict=True) != path:
        raise images.CandidateImageError('research_skill_installed_path_invalid')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= 65536:
            raise images.CandidateImageError('research_skill_installed_file_invalid')
        raw = os.read(fd, 65537)
        after = os.fstat(fd)
        current = path.lstat()
        def identity(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
        if (identity(before) != identity(after) or identity(after) != identity(current)
                or len(raw) != before.st_size or hashlib.sha256(raw).hexdigest() != expected_sha256):
            raise images.CandidateImageError('research_skill_installed_source_changed')
        return raw
    finally:
        os.close(fd)


def _docker(arguments, *, timeout=45):
    result = subprocess.run(['docker', *arguments], capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise images.CandidateImageError('research_skill_image_command_failed')
    return result.stdout


def build(state, installations):
    base_ref, base_id = images.verified_candidate()
    original = images._json_file(images.STATE_ROOT / 'current-image.json')
    config_bytes = _docker(['run', '--rm', '--network=none', '--read-only', '--entrypoint', '/bin/cat',
                           base_id, str(PROFILE / 'config.yaml')])
    if hashlib.sha256(config_bytes).hexdigest() != original['runtime_config_sha256']:
        raise images.CandidateImageError('research_skill_base_config_mismatch')
    config = yaml.safe_load(config_bytes)
    config['plugins']['enabled'].append(PLUGIN)
    config['plugins']['required_pre_tool_call'].append(PLUGIN)
    images.validate_config(config)
    config_bytes = yaml.safe_dump(config, sort_keys=False).encode()
    files = {'config.yaml': config_bytes, 'sync.py': images._file(SYNC),
             'plugin.yaml': ('name: ' + PLUGIN + '\nversion: 1.0.0\n'
                 'description: Evaluation-only installed Skill and SEC synchronization.\n'
                 'provides_hooks: [pre_llm_call, pre_tool_call, post_tool_call, pre_api_request, post_llm_call]\n'
                 'hooks: [pre_llm_call, pre_tool_call, post_tool_call, pre_api_request, post_llm_call]\n').encode()}
    files['plugins.py'] = patched_observer_source(_docker([
        'run', '--rm', '--network=none', '--read-only', '--entrypoint', '/bin/cat',
        base_id, '/opt/hermes-agent/hermes_cli/plugins.py']))
    files['observer.sha256'] = (
        OBSERVER_FIXED_SHA + '  /opt/hermes-agent/hermes_cli/plugins.py\n').encode()
    manifest = {'schema_version': 'siq.research-permission-skills.v1', 'skills': {}}
    if {r['name'] for r in installations} != {'research-permissions-reader', 'research-permissions-writer'}:
        raise images.CandidateImageError('research_skill_image_selection_invalid')
    for row in installations:
        raw = installed_bytes(Path(row['installed_path']) / 'SKILL.md', row['skill_file_sha256'])
        files['skills/' + row['name'] + '/SKILL.md'] = raw
        manifest['skills'][row['name']] = {'sha256': row['skill_file_sha256'], 'source_digest': row['source_digest']}
    files['skills.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    config_sha = hashlib.sha256(config_bytes).hexdigest()
    files['config.sha256'] = f'{config_sha}  {PROFILE}/config.yaml\n'.encode()
    dockerfile = (
        'ARG BASE\nFROM ${BASE}\nUSER root\nARG INPUT_SHA\nARG CONFIG_SHA\n'
        'LABEL ai.siq.qwen38.candidate-input-sha256="$INPUT_SHA"\n'
        'LABEL ai.siq.qwen38.compiled-config-sha256="$CONFIG_SHA"\n'
        f'COPY skills/ {PROFILE}/skills/\n'
        f'COPY sync.py {PROFILE}/plugins/{PLUGIN}/__init__.py\n'
        f'COPY plugin.yaml {PROFILE}/plugins/{PLUGIN}/plugin.yaml\n'
        f'COPY config.yaml {PROFILE}/config.yaml\n'
        'COPY config.sha256 /opt/siq/qwen38-config.sha256\n'
        'COPY skills.json /opt/siq/research-permission-skills.json\n'
        'COPY plugins.py /opt/hermes-agent/hermes_cli/plugins.py\n'
        'COPY observer.sha256 /opt/siq/research-observer.sha256\n'
        f'RUN chown -R root:root {PROFILE}/skills {PROFILE}/plugins/{PLUGIN} '
        f'&& chmod -R a-w,a+rX {PROFILE}/skills {PROFILE}/plugins/{PLUGIN} '
        f'&& chmod 0444 {PROFILE}/config.yaml /opt/siq/qwen38-config.sha256 '
        '/opt/siq/research-permission-skills.json '
        '&& chmod 0444 /opt/hermes-agent/hermes_cli/plugins.py /opt/siq/research-observer.sha256 '
        '&& sha256sum -c /opt/siq/qwen38-config.sha256 '
        '&& sha256sum -c /opt/siq/research-observer.sha256\nUSER sandbox:sandbox\n')
    files['Dockerfile'] = dockerfile.encode()
    digest = hashlib.sha256(json.dumps({'base_image_id': base_id,
        'files': {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}, sort_keys=True).encode()).hexdigest()
    context = state / 'image-context'
    context.mkdir(mode=0o700)
    for name, raw in files.items():
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    image_ref = images.IMAGE_PREFIX + digest[:24]
    _docker(['build', '--pull=false', '--network=none', '--build-arg', 'BASE=' + base_id,
             '--build-arg', 'INPUT_SHA=' + digest, '--build-arg', 'CONFIG_SHA=' + config_sha,
             '--tag', image_ref, str(context)], timeout=180)
    image_id = images._verify_image(image_ref, input_sha=digest, config_sha=config_sha,
                                   manifest_sha=original['snapshot_manifest_sha256'])
    for row in installations:
        actual = _docker(['run', '--rm', '--network=none', '--read-only', '--entrypoint', '/bin/cat',
                          image_id, str(PROFILE / 'skills' / row['name'] / 'SKILL.md')])
        if hashlib.sha256(actual).hexdigest() != row['skill_file_sha256']:
            raise images.CandidateImageError('research_skill_image_copy_mismatch')
    images._smoke(image_ref)
    images._pg_query_smoke(image_ref, expected_sha256=original['pg_query_sha256'])
    images._report_smoke(image_ref)
    images._resolver_smoke(image_ref)
    images._dispatcher_fail_closed_smoke(image_ref)
    images._gateway_smoke(image_ref)
    if config.get('mcp_servers'):
        images._business_mcp_smoke(image_ref)
    _docker(['run', '--rm', '--network=none', '--read-only', '--entrypoint', '/usr/bin/sha256sum',
             image_id, '-c', '/opt/siq/qwen38-agentshield-adapter.sha256'])
    _docker(['run', '--rm', '--network=none', '--read-only', '--entrypoint', '/usr/bin/sha256sum',
             image_id, '-c', '/opt/siq/research-observer.sha256'])
    record = {**original, 'image_ref': image_ref, 'image_id': image_id, 'candidate_input_sha256': digest,
              'runtime_config_sha256': config_sha, 'evaluation_base_image_id': base_id,
              'evaluation_base_image_ref': base_ref, 'evaluation_skill_bundle': manifest,
              'evaluation_sync_sha256': hashlib.sha256(files['sync.py']).hexdigest(),
              'evaluation_observer_patch_sha256': OBSERVER_PATCH_SHA,
              'evaluation_observer_base_sha256': OBSERVER_SOURCE_SHA,
              'evaluation_observer_fixed_sha256': OBSERVER_FIXED_SHA,
              'model_inference_verified': False, 'openshell_sandbox_verified': False}
    output = state / 'candidate-image.json'
    with output.open('x') as stream:
        json.dump(record, stream, sort_keys=True, indent=2)
    output.chmod(0o600)
    images.verified_candidate(record_path=output)
    return output
