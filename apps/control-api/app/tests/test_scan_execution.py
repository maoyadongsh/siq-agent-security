"""Real worker failure and isolation, not only timeout mocks."""
import base64
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from sqlalchemy import func, select

from app import scan_execution, scan_transport, threat_analysis
from app.db import session_scope
from app.models import AgentAsset, AuditEvent, Finding, OutboxEvent
from app.scan_isolation import command
from app.scan_transport import ScanFailure, exchange
from app.tests.binding_helpers import make_instance


@pytest.mark.parametrize("raw,filename", [
    (b"echo hello", "x.sh"), (b"cat /etc/shadow", "x.sh"),
    (b"import os\nos.system('hello')", "x.py"),
    (b"def broken(:", "x.py"), (b"MZ\x00\xff", "x.bin"),
])
def test_worker_matches_existing_analyzer(raw, filename):
    result = scan_execution.analyze(raw, filename=filename, scope="synthetic")
    expected = asdict(threat_analysis.analyze(raw, filename=filename))
    assert {k: v for k, v in asdict(result).items() if k != "analyzer_version"} == expected
    assert result.analyzer_version == threat_analysis.ANALYZER_VERSION


def test_worker_protocol_and_parent_rejects_misbound_results(monkeypatch):
    original, messages = scan_execution.exchange, []

    def capture(argv, payload):
        output = original(argv, payload)
        messages.append((json.loads(payload), json.loads(output)))
        return output

    monkeypatch.setattr(scan_execution, "exchange", capture)
    scan_execution.analyze(b"cat /etc/shadow", filename="x.sh", scope="tenant-task-A")
    request, response = messages[0]
    path = Path(__file__).parents[4] / 'packages/contracts/threat-scan-worker.v1.schema.json'
    schema = json.loads(path.read_text())
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    validator.validate(request)
    validator.validate(response)
    for key in ("schema_version", "task_id", "scope_sha256", "input_sha256", "rules_sha256", "analyzer_version"):
        with pytest.raises(ScanFailure, match="result_invalid"):
            scan_execution.parse_response(json.dumps({**response, key: "other"}).encode(), request)
    for result in ({**response['result'], 'sha256': '0'*64},
                   {**response['result'], 'matches': [{'rule_id': 'missing'}]},
                   {**response['result'], 'detected_type': []}):
        with pytest.raises(ScanFailure, match="result_invalid"):
            scan_execution.parse_response(json.dumps({**response, 'result': result}).encode(), request)
    with pytest.raises(ScanFailure, match="result_invalid"):
        scan_execution.parse_response(b'null', request)


def test_loaded_external_rule_snapshot_is_used_without_signing_credentials(monkeypatch):
    from app.rulepack import _parse_rulepack
    snapshot = scan_execution.rule_snapshot()
    snapshot['version'] += 1
    snapshot['rules'][0]['patterns'] = ['synthetic-worker-rule-marker']
    version, rules, redactions = _parse_rulepack(snapshot)
    monkeypatch.setattr(threat_analysis, 'RULEPACK_VERSION', version)
    monkeypatch.setattr(threat_analysis, '_RULES', rules)
    monkeypatch.setattr(threat_analysis, '_REDACTION_RULES', redactions)
    monkeypatch.setenv('SIQ_AS_TASK_SIGNING_KEY_SEED', base64.b64encode(bytes(32)).decode())
    result = scan_execution.analyze(b'synthetic-worker-rule-marker', filename='x.sh')
    assert result.analyzer_version == f'siq.threat-static.v{version}'
    assert snapshot['rules'][0]['rule_id'] in {match.rule_id for match in result.matches}
    code = "import os; print(os.getenv('SIQ_AS_TASK_SIGNING_KEY_SEED', 'absent'))"
    assert exchange(command('process', code=code), b'') == b'absent\n'


@pytest.mark.parametrize("kind", ['timeout', 'output', 'crash', 'cpu'])
def test_worker_faults_are_bounded_and_reaped(monkeypatch, kind):
    processes = []
    original = scan_transport.subprocess.Popen

    def tracked(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(scan_transport.subprocess, 'Popen', tracked)
    code = {
        'timeout': 'import time; time.sleep(30)',
        'output': 'import sys; sys.stdout.write("x"*100000)',
        'crash': 'import os; os._exit(7)',
        'cpu': 'import resource; resource.setrlimit(resource.RLIMIT_CPU,(1,1)); exec("while True: pass")',
    }[kind]
    start = time.monotonic()
    with pytest.raises(ScanFailure):
        exchange(command('process', code=code), b'', timeout=2 if kind=='cpu' else .3, output_limit=4096)
    assert time.monotonic() - start < 4
    assert len(processes) == 1 and processes[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


def test_memory_exhaustion_has_no_success_record_and_governance_recovers(client, tenant_a, env_a):
    asset_id, _ = make_instance(tenant_a['X-Dev-Tenant-Id'], env_a['id'])
    def counts():
        with session_scope() as session:
            return tuple(session.scalar(select(func.count()).select_from(model))
                         for model in (Finding, AuditEvent, OutboxEvent))
    before = counts()
    raw = ('print(1)\n'*131072)[:1048576]
    response = client.post(f'/api/v1/assets/{asset_id}/threat-scan', headers=tenant_a,
                           json={'content': raw, 'filename':'large.py'})
    assert response.status_code == 503, response.text
    assert response.json()['detail'] == 'threat_scan_worker_failed'
    assert counts() == before
    with session_scope() as session:
        assert session.get(AgentAsset, asset_id).artifact_digest is None
    assert client.get('/health').status_code == 200
    good = client.post(f'/api/v1/assets/{asset_id}/threat-scan', headers=tenant_a,
                       json={'content':'echo recovered', 'filename':'x.sh'})
    assert good.status_code == 200, good.text


def test_production_cannot_select_uncontained_process(monkeypatch):
    from app.config import load_settings
    monkeypatch.setenv('SIQ_AS_DEV', '0')
    monkeypatch.setenv('SIQ_AS_THREAT_SCAN_ISOLATION', 'process')
    with pytest.raises(RuntimeError, match='requires bwrap'):
        load_settings()


def test_real_bwrap_hides_files_and_host_network(tmp_path, monkeypatch):
    # Explicit opt-in keeps missing native sandbox prerequisites visible in the dedicated job.
    if os.getenv('SIQ_TEST_NATIVE_BWRAP') != '1':
        pytest.skip('native bwrap acceptance requires SIQ_TEST_NATIVE_BWRAP=1')
    marker = tmp_path / 'host-private-marker'
    marker.write_text('synthetic private host file')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        code = f'''import os, socket, json
assert not os.path.exists({str(marker)!r})
try:
 open('/scan/app/forbidden-write', 'w')
 raise AssertionError('sandbox code mount writable')
except OSError: pass
sock=socket.socket(); sock.settimeout(.3)
assert sock.connect_ex(('127.0.0.1',{port})) != 0
print(json.dumps({{'hidden':True,'readonly':True,'host_network_denied':True}}))'''
        argv = command('bwrap', code=code)
        try:
            result = json.loads(exchange(argv, b''))
        except ScanFailure as error:
            detail = subprocess.run(argv, input=b'', capture_output=True).stderr.decode('utf-8', 'replace')
            raise AssertionError(detail.strip() or str(error)) from None
        assert all(result.values())
    monkeypatch.setenv('SIQ_AS_THREAT_SCAN_ISOLATION', 'bwrap')
    assert scan_execution.analyze(b'echo hello', filename='x.sh').matches == []


def test_bwrap_preserves_python_origin():
    if sys.platform != 'linux' or not os.path.exists('/usr/bin/bwrap'):
        pytest.skip('bwrap argv check needs the Linux launcher')
    argv = command('bwrap', code='pass')
    executable = os.path.abspath(sys.executable)
    resolved = os.path.realpath(executable)
    binds = [(argv[i + 1], argv[i + 2]) for i, token in enumerate(argv) if token == '--ro-bind']
    assert (resolved, resolved) in binds
    if resolved != executable:
        links = [(argv[i + 1], argv[i + 2]) for i, token in enumerate(argv) if token == '--symlink']
        assert (resolved, executable) in links


def test_cpu_bound_worker_does_not_hold_governance_and_slot_is_released(client, tenant_a, env_a, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.routers import threat
    from app.rulepack import _parse_rulepack
    from app.scan_budget import ScanBudget

    # Test-only pathological regex: never installed as a shared product rule pack.
    snapshot = scan_execution.rule_snapshot()
    snapshot['rules'][0]['patterns'] = ['^(a+)+$']
    _, rules, _ = _parse_rulepack(snapshot)
    monkeypatch.setattr(threat_analysis, '_RULES', rules)
    budget = ScanBudget(concurrency=1)
    monkeypatch.setattr(threat, 'get_scan_budget', lambda: budget)
    original, entered = scan_execution.exchange, Event()

    def observe(argv, payload):
        entered.set()
        return original(argv, payload)

    monkeypatch.setattr(scan_execution, 'exchange', observe)
    asset_id, _ = make_instance(tenant_a['X-Dev-Tenant-Id'], env_a['id'])
    path = f'/api/v1/assets/{asset_id}/threat-scan'
    body = {'content': 'a'*50+'!', 'filename': 'x.sh'}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, path, headers=tenant_a, json=body)
        assert entered.wait(3)
        start = time.monotonic()
        assert client.get('/health').status_code == 200
        assert time.monotonic() - start < 1
        assert not future.done()
        rejected = client.post(path, headers=tenant_a, json=body)
        assert rejected.status_code == 429 and rejected.json()['detail'] == 'threat_scan_busy'
        failed = future.result(timeout=8)
        assert failed.status_code == 503
    assert budget.snapshot()['active'] == 0
