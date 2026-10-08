"""Synthetic acceptance client executed inside an owned Control API container."""
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app import scan_execution, threat_analysis
from app.config import load_settings
from app.db import init_db, session_scope
from app.models import AgentAsset, AuditEvent, Finding, OutboxEvent
from app.rulepack import _parse_rulepack
from app.scan_transport import ScanFailure

HEADERS = {"X-Dev-Tenant-Id": "dev-tenant", "X-Dev-User-Id": "scan-acceptance",
           "X-Dev-Roles": "tenant_admin,security_admin", "Content-Type": "application/json"}
checks = {}


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:8600" + path, data=data, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def asset():
    with session_scope() as session:
        row = AgentAsset(tenant_id="dev-tenant", name="synthetic-scan-acceptance", status="confirmed")
        session.add(row)
        session.flush()
        return row.id


def counts():
    with session_scope() as session:
        return tuple(session.scalar(select(func.count()).select_from(model))
                     for model in (Finding, AuditEvent, OutboxEvent))


def failed_scan(raw, name):
    identifier = asset()
    before = counts()
    status, _ = request(f"/api/v1/assets/{identifier}/threat-scan", {"content": raw, "filename": name})
    assert status == 503, status
    assert counts() == before
    with session_scope() as session:
        assert session.get(AgentAsset, identifier).artifact_digest is None
    assert request("/health")[0] == 200


def main():
    phase = sys.argv[1]
    if phase == "ready":
        assert request("/health")[0] == 200
        return {"http_ready": True}
    init_db(load_settings())
    if phase in {"unavailable", "endpoint-drift"}:
        failed_scan("echo fail closed", "x.sh")
        return {f"{phase}_no_success_transaction": True, "governance_healthy": True}
    if phase == "recovered":
        status, _ = request(f"/api/v1/assets/{asset()}/threat-scan",
                            {"content": "echo recovered", "filename": "x.sh"})
        assert status == 200
        return {"scan_recovers_after_service_restart": True}
    assert phase == "normal"
    for raw, filename in [(b"echo harmless", "x.sh"), (b"cat /etc/shadow", "x.sh"),
                          (b"def broken(:", "x.py")]:
        result = scan_execution.analyze(raw, filename=filename, scope="synthetic-scope")
        expected = threat_analysis.analyze(raw, filename=filename)
        assert result.sha256 == expected.sha256 and result.matches == expected.matches
    checks["three_samples_match_static_analyzer"] = True
    for content, key in [("echo harmless", "normal_http"), ("cat /etc/shadow", "malicious_http")]:
        before = counts()
        status, body = request(f"/api/v1/assets/{asset()}/threat-scan", {"content": content, "filename": "x.sh"})
        assert status == 200, (status, body)
        assert counts()[1] > before[1]
        if key == "malicious_http":
            assert counts()[0] > before[0] and counts()[2] > before[2]
        checks[key] = True
    failed_scan(("print(1)\n" * 131072)[:1048576], "large.py")
    checks["memory_failure_no_success_transaction"] = True
    original = threat_analysis._RULES
    snapshot = scan_execution.rule_snapshot()
    snapshot["rules"][0]["patterns"] = ["^(a+)+$"]  # Request-local fault; never install into API.
    _, rules, _ = _parse_rulepack(snapshot)
    threat_analysis._RULES = rules
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(scan_execution.analyze, b"a" * 50 + b"!", filename="x.sh")
            time.sleep(.25)
            started = time.monotonic()
            assert request("/health")[0] == 200
            assert time.monotonic() - started < 1 and not future.done()
            try:
                future.result(timeout=8)
                raise AssertionError("CPU exhaustion accepted")
            except ScanFailure:
                pass
    finally:
        threat_analysis._RULES = original
    checks["cpu_failure_governance_responsive"] = True
    assert scan_execution.analyze(b"echo recovered", filename="x.sh").matches == []
    checks["scan_recovers_after_resource_failures"] = True
    return checks


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
