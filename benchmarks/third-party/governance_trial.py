#!/usr/bin/env python3
"""Production HTTP/PostgreSQL governance probe; author-run, local test issuer.

Owns a disposable database and API process. Optional backend and browser probes
use only their owned fixtures. No customer IdP, existing DB or model is used.
SQL fault injection is restricted to the owned database and recorded explicitly.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import jwt
import psycopg
from common import Events, clean_environment, sha256, utc_now, write_json
from cryptography.hazmat.primitives.asymmetric import rsa

IMAGE = "postgres:17-alpine"
CASES = {
    "no_token": 401, "dev_header": 401, "wrong_issuer": 401,
    "wrong_audience": 401, "expired": 401, "wrong_signature": 401,
    "create_a": 201, "create_b": 201, "list_a": 200, "list_b": 200,
    "cross_read": 404, "absent_read": 404, "own_no_permission": 403,
    "cross_no_permission": 404, "cross_write": 404, "own_write_denied": 403,
    "policy_create": 201, "change_create": 201, "self_approve": 409,
    "model_approve": 403, "cross_approve": 404, "break_glass_denied": 403,
    "audit_failure_approve": 500, "separate_approve": 200,
    "repeat_approve": 409, "forged_effective": 422,
    "audit_failure_create": 500, "create_after_fault": 201,
    "audit_a": 200, "audit_b": 200,
}


def freeze(campaign: Path, protocol_id: str, include_edge=False, include_backend=False, include_ui=False,
           include_concurrency=False, candidate_root=None):
    include_edge = include_edge or include_backend or include_ui
    source = Path(__file__).resolve().parent
    candidate = candidate_root or campaign / "private/candidates/5470ab3780f2-fixturefix2"
    directory = campaign / "protocols" / protocol_id
    directory.mkdir(parents=True, exist_ok=False)
    files = {}
    for base in (candidate / "apps/control-api/app", candidate / "apps/control-api/migrations"):
        for path in sorted(base.rglob("*.py")):
            files[str(path.relative_to(candidate))] = sha256(path)
    for name in ("pyproject.toml", "uv.lock", "alembic.ini"):
        path = candidate / "apps/control-api" / name
        files[str(path.relative_to(candidate))] = sha256(path)
    runtime = {}
    names = ["governance_trial.py", "common.py"]
    if include_concurrency:
        names += ["concurrent_governance.py"]
    if include_edge:
        names += ["edge_governance.py", "edge_governance_scoring.py"]
    if include_backend:
        names += ["backend_governance.py", "openshell_fixture.py"]
    if include_ui:
        names += ["ui_governance.py"]
        for base in (candidate / "apps/web/src", candidate / "apps/web/dist"):
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    files[str(path.relative_to(candidate))] = sha256(path)
        for name in ("package.json", "package-lock.json", "vite.config.ts", "index.html"):
            path = candidate / "apps/web" / name
            files[str(path.relative_to(candidate))] = sha256(path)
    for name in names:
        target = directory / "harness-source" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source / name, target)
        runtime[name] = sha256(target)
    protocol = {"protocol_id": protocol_id, "frozen_at": utc_now(), "relationship": "author_run",
                    "candidate_root": str(candidate), "candidate_sources": files,
                    "harness_sources": runtime, "expected_status": CASES, "model_calls": 0,
                    "issuer": "ephemeral loopback RS256/JWKS test fixture, not customer IdP",
                    "database": "new owned PostgreSQL container; two fixture tenants seeded by SQL",
                    "image": IMAGE, "retries": 0, "scope": "G01 environment and policy boundaries; G02 approval and transaction rollback",
                    "limits": ["not full G01 asset/evidence coverage", "not G03 Edge or G04 backend readback",
                            "HTTP/SQL evidence is author-captured, not independently witnessed",
                            "ordered scenarios share fixtures; not independent statistical trials"]}
    if include_edge:
        from edge_governance import CASES as edge_cases
        from edge_governance_scoring import ASSERTIONS
        protocol["expected_status"] = {**CASES, **edge_cases}
        protocol["edge_assertions"] = ASSERTIONS
        protocol["scope"] += "; G03 synthetic Edge client; G01 asset/evidence boundaries"
        protocol["limits"][0:2] = ["synthetic Python Edge protocol client, not native Edge binary",
                                   "not G04 authenticated backend readback or UI journey"]
    if include_backend:
        from backend_governance import ASSERTIONS
        from backend_governance import CASES as backend_cases
        protocol["expected_status"].update(backend_cases)
        protocol["backend_assertions"] = ASSERTIONS
        protocol["backend_release_sha256"] = sha256(campaign / "inventory/openshell-v0104-release.json")
        protocol["scope"] += "; G04 real mTLS OpenShell apply/readback/rollback/stale preview/unreachable"
        protocol["limits"][1] = "configuration readback, not behavioral network enforcement; UI journey not included"
    if include_ui:
        from ui_governance import ASSERTIONS
        from ui_governance import CASES as ui_cases
        protocol["expected_status"] = {**protocol["expected_status"], **ui_cases}
        protocol["ui_assertions"] = ASSERTIONS
        protocol["limits"] = [item.replace(" or UI journey", "").replace("; UI journey not included", "")
                              for item in protocol["limits"]]
        protocol["ui_toolchain_sha256"] = sha256(campaign / "inventory/governance-ui-toolchain.json")
        protocol["scope"] += "; unchanged enterprise production browser build: self-review, approval, mobile, cross-tenant, disconnect"
        protocol["limits"] += ["test identity HTTP service is not real IAM login assurance",
                               "browser build VITE_DEV_MODE=false; model/host install and behavioral enforcement not exercised",
                               "Chromium sandbox unavailable on this host; browser sandbox disabled only for owned localhost fixture UI, no malicious pages or OS isolation claim"]
    if include_concurrency:
        from concurrent_governance import ASSERTIONS, GROUPS
        from concurrent_governance import CASES as race_cases
        protocol["expected_status"] = {**protocol["expected_status"], **race_cases}
        protocol["race_assertions"] = ASSERTIONS
        protocol["race_groups"] = GROUPS
        protocol["scope"] += "; concurrent legacy approve/reject, review-decision and idempotent create"
        protocol["limits"] += ["owned PostgreSQL row/advisory locks explicitly force overlap; not natural race incidence or throughput",
                               "one controlled burst per group, no side-effect exactly-once or native host claim"]
    write_json(directory / "protocol.json", protocol)
    write_json(directory / "local-anchor.json", {"sha256": sha256(directory / "protocol.json")})
    print(json.dumps({"protocol": str(directory / "protocol.json"), "cases": len(protocol["expected_status"])}))


def run(campaign: Path, protocol_id: str, run_id: str):
    os.umask(0o077)
    protocol_path = campaign / "protocols" / protocol_id / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    if protocol.get("ui_toolchain_sha256"):
        inventory_path = campaign / "inventory/governance-ui-toolchain.json"
        if sha256(inventory_path) != protocol["ui_toolchain_sha256"]:
            raise ValueError("UI toolchain inventory changed")
        for record in json.loads(inventory_path.read_text())["files"].values():
            if sha256(Path(record["path"])) != record["sha256"]:
                raise ValueError("UI toolchain changed")
    candidate = Path(protocol["candidate_root"])
    for name, digest in protocol["candidate_sources"].items():
        if sha256(candidate / name) != digest:
            raise ValueError("candidate source changed: " + name)
    for name, digest in protocol["harness_sources"].items():
        if sha256(Path(__file__).resolve().parent / name) != digest:
            raise ValueError("run frozen harness snapshot: " + name)
    out = campaign / "private/runs" / run_id
    out.mkdir(parents=True, exist_ok=False)
    events = Events(out / "events.jsonl", run_id)
    rows, checks = [], []
    container = api = jwks = log = backend_fixture = None
    cleanup = {}
    failure = None
    api_dir = candidate / "apps/control-api"
    python = api_dir / ".venv/bin/python"
    if protocol.get('risk_python_runtime'):
        from enterprise_risk_trial import RUNTIME_QUERY
        runtime = json.loads(subprocess.check_output([str(python), '-c', RUNTIME_QUERY], text=True))
        if runtime != protocol['risk_python_runtime']:
            raise ValueError('risk Python runtime differs from frozen inventory')
    environment = clean_environment()

    def command(argv, *, env=None, cwd=None):
        return subprocess.run(argv, env=env or environment, cwd=cwd, timeout=90,
                              capture_output=True, text=True, check=False)

    def check(case, condition, observed):
        row = {"id": case, "passed": bool(condition), "observed": observed}
        checks.append(row)
        events.add("assertion", **row)

    try:
        image = command(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"])
        if image.returncode:
            raise RuntimeError("local image required; no automatic pull")
        write_json(out / "image.json", {"tag": IMAGE, "id": image.stdout.strip()})
        password = secrets.token_hex(24)
        launched = command(["docker", "run", "--detach", "--rm", "--name", "siq-tp07-" + secrets.token_hex(6),
                            "--label", "siq.evaluation=tp07", "--memory", "512m", "--cpus", "1",
                            "--publish", "127.0.0.1::5432", "--tmpfs", "/var/lib/postgresql/data:rw,size=256m",
                            "--env", "POSTGRES_PASSWORD", IMAGE],
                           env={**environment, "POSTGRES_PASSWORD": password})
        if launched.returncode:
            raise RuntimeError("owned database launch failed")
        container = launched.stdout.strip()
        if len(container) != 64 or any(c not in "0123456789abcdef" for c in container):
            container = None
            raise RuntimeError("invalid container identity")
        events.add("owned_container", container_id=container)
        port = int(command(["docker", "port", container, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1])
        conninfo = f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"

        def sql(statement, parameters=()):
            with psycopg.connect(conninfo, connect_timeout=2) as connection:
                cursor = connection.execute(statement, parameters)
                return [list(row) for row in cursor.fetchall()] if cursor.description else []

        deadline = time.monotonic() + 35
        while True:
            try:
                sql("SELECT 1")
                break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise RuntimeError("owned database readiness timeout") from None
                time.sleep(0.2)
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
        public.update(kid="tp07-fixture", alg="RS256", use="sig")
        jwks_bytes = json.dumps({"keys": [public]}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/jwks" else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(jwks_bytes if self.path == "/jwks" else b"{}")

            def log_message(self, *_):
                pass

        jwks = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=jwks.serve_forever, daemon=True).start()
        issuer = f"http://127.0.0.1:{jwks.server_port}/issuer"
        write_json(out / "issuer.json", {"issuer": issuer, "keys": [public], "kind": "test_fixture"})
        env = {**environment, "SIQ_AS_DEV": "0", "SIQ_AS_ALLOW_SQLITE": "0",
               "SIQ_AS_DATABASE_URL": conninfo.replace("postgresql://", "postgresql+psycopg://"),
               "SIQ_AS_OIDC_JWKS_URL": f"http://127.0.0.1:{jwks.server_port}/jwks",
               "SIQ_AS_OIDC_ISSUER": issuer, "SIQ_AS_JWT_AUDIENCE": "tp07-evaluation",
               "SIQ_AS_BOOTSTRAP_TENANT_ID": "tp07-a",
               "SIQ_AS_TASK_SIGNING_KEY_SEED": base64.b64encode(secrets.token_bytes(32)).decode()}
        for attempt in (1, 2):
            result = command([str(python), "-m", "alembic", "upgrade", "head"], cwd=api_dir, env=env)
            (out / f"migration-{attempt}.log").write_text(result.stdout + result.stderr)
            check(f"migration_{attempt}", result.returncode == 0, {"exit_code": result.returncode})
            if result.returncode:
                raise RuntimeError("migration failed")
        version = sql("SELECT version_num FROM alembic_version")
        check("migration_head", version == [["0028"]], version)
        for tenant in ("tp07-a", "tp07-b"):
            sql("INSERT INTO tenant(id,name,status,data_residency,retention_days,created_at) "
                "VALUES (%s,%s,'active','default',180,now())", (tenant, tenant))
        events.add("fixture_seed", tenants=["tp07-a", "tp07-b"], via="owned DB SQL, setup only")
        if protocol.get("backend_assertions"):
            from openshell_fixture import OpenShellFixture
            if sha256(campaign / "inventory/openshell-v0104-release.json") != protocol["backend_release_sha256"]:
                raise ValueError("backend release identity changed")
            if protocol.get('native_enterprise_assertions'):
                from enterprise_runtime import EnterpriseRuntime
                backend_fixture = EnterpriseRuntime(campaign, out / 'backend-private', candidate)
            else:
                backend_fixture = OpenShellFixture(campaign, out / "backend-private", candidate)
            backend_fixture.start()
            created = backend_fixture.create_sandbox()
            if created.returncode or backend_fixture.product_probe().returncode:
                raise RuntimeError("owned_backend_not_ready")
            env.update({k: v for k, v in backend_fixture.environment.items() if k.startswith("XDG_")})
            env.update(SIQ_AS_ENFORCEMENT_BACKEND="openshell-cli",
                       SIQ_AS_OPENSHELL_CLI_BIN=str(backend_fixture.toolchain / "openshell"),
                       SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT=backend_fixture.endpoint,
                       SIQ_AS_OPENSHELL_GATEWAY_INSECURE="0",
                       SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE=str(backend_fixture.root / "operator-authority.json"))
        # Uvicorn inherits an already bound socket, avoiding a free-port race.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        api_port = listener.getsockname()[1]
        log = (out / "api-private.log").open("x")
        try:
            api = subprocess.Popen([str(python), "-m", "uvicorn", "app.main:app", "--fd", str(listener.fileno()),
                                    "--no-access-log"], cwd=api_dir, env=env, pass_fds=(listener.fileno(),),
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        finally:
            listener.close()
        events.add("api_started", child_pid=api.pid, production=True, transport="loopback HTTP")
        base_url = f"http://127.0.0.1:{api_port}"
        with httpx.Client(base_url=base_url, trust_env=False, timeout=10) as client:
            deadline = time.monotonic() + 25
            while True:
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if api.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("API readiness failed")
                time.sleep(0.15)

            def identity(tenant="tp07-a", actor="operator-a", roles=None, **overrides):
                signing_key = overrides.pop("signing_key", private_key)
                claims = {"sub": actor, "tenant_id": tenant, "type": "access", "role_codes": roles or [],
                              "iss": issuer, "aud": "tp07-evaluation", "iat": int(time.time()), "exp": int(time.time()) + 1800}
                claims.update(overrides)
                return {"Authorization": "Bearer " + jwt.encode(claims, signing_key, algorithm="RS256",
                                                                  headers={"kid": "tp07-fixture"})}

            def request(case, method, path, headers=None, body=None):
                started = time.monotonic_ns()
                events.add("http_attempt", case_id=case, method=method, path=path)
                response = client.request(method, path, headers=headers, json=body,
                                          timeout=90 if case.startswith("backend_") else 10)
                if protocol.get('risk_assertions') and case.startswith('risk_export_') and response.status_code == 200:
                    value = {'ndjson': response.text}
                else:
                    try:
                        value = response.json()
                    except ValueError:
                        value = {"non_json": response.text[:200]}
                def redact(item):
                    if isinstance(item, dict):
                        return {k: "[REDACTED]" if k in {"code", "enrollment_code", "device_secret"} else redact(v)
                                for k, v in item.items()}
                    if isinstance(item, list):
                        return [redact(v) for v in item]
                    return item
                row = {"case_id": case, "method": method, "path": path, "request_body": redact(body),
                           "status": response.status_code, "body": redact(value), "elapsed_ns": time.monotonic_ns() - started}
                if protocol.get('risk_assertions') and case.startswith('risk_'):
                    row['response_headers'] = {k: v for k, v in response.headers.items() if k.startswith('x-siq-') or k in ('content-type', 'cache-control')}
                rows.append(row)
                events.add("http", **row)
                check(case, response.status_code == protocol["expected_status"][case],
                      {"status": response.status_code, "expected": protocol["expected_status"][case]})
                return value

            roles = ["tenant_admin", "security_admin", "agent_owner", "platform_operator", "auditor"]
            a, b = identity(roles=roles), identity("tp07-b", "operator-b", roles)
            none_a, none_b = identity(actor="no-permission"), identity("tp07-b", "no-permission")
            request("no_token", "GET", "/api/v1/overview")
            request("dev_header", "GET", "/api/v1/overview", {"X-Dev-Tenant-Id": "tp07-a", "X-Dev-Roles": "tenant_admin"})
            for case, override in (("wrong_issuer", {"iss": "http://invalid.test"}),
                                   ("wrong_audience", {"aud": "another-service"}),
                                   ("expired", {"iat": int(time.time()) - 200, "exp": int(time.time()) - 100}),
                                   ("wrong_signature", {"signing_key": rsa.generate_private_key(public_exponent=65537, key_size=2048)})):
                request(case, "GET", "/api/v1/overview", identity(roles=roles, **override))
            ea = request("create_a", "POST", "/api/v1/environments", a, {"name": "tenant-a-environment", "mode": "discovery"})
            eb = request("create_b", "POST", "/api/v1/environments", b, {"name": "tenant-b-environment", "mode": "discovery"})
            for case, auth, own, foreign in (("list_a", a, ea, eb), ("list_b", b, eb, ea)):
                value = request(case, "GET", "/api/v1/environments", auth)
                check(case + "_isolated", isinstance(value, list) and [x["id"] for x in value] == [own["id"]],
                      {"ids": [x["id"] for x in value] if isinstance(value, list) else value, "foreign_id": foreign["id"]})
            path = f"/api/v1/environments/{ea['id']}"
            for case, suffix, auth in (("cross_read", path, b), ("absent_read", "/api/v1/environments/env-absent", b),
                                       ("own_no_permission", path, none_a), ("cross_no_permission", path, none_b)):
                request(case, "GET", suffix + "/onboarding", auth)
            before = sql("SELECT id,tenant_id,mode FROM environment ORDER BY id")
            for case, auth in (("cross_write", b), ("own_write_denied", none_a)):
                request(case, "PATCH", path + "/mode", auth, {"mode": "enforce", "reason": "evaluation"})
            after = sql("SELECT id,tenant_id,mode FROM environment ORDER BY id")
            check("denied_environment_writes_no_effect", before == after, {"before": before, "after": after})
            policy = request("policy_create", "POST", "/api/v1/policies", a,
                             {"name": "tp07-policy", "selector": {}, "enforcement_mode": "block"})
            cr = request("change_create", "POST", "/api/v1/change-requests", a,
                         {"policy_id": policy["id"], "idempotency_key": "tp07-standard-001"})
            approve_path = f"/api/v1/change-requests/{cr['id']}/approve"

            def approval_state():
                return {"change": sql("SELECT status,approver_user_id FROM change_request WHERE id=%s", (cr["id"],)),
                        "audit": sql("SELECT action,actor_id FROM audit_event WHERE resource_id=%s ORDER BY id", (cr["id"],)),
                        "outbox": sql("SELECT event_type,payload FROM outbox_event WHERE tenant_id='tp07-a' "
                                      "AND payload->'payload'->>'change_request_id'=%s ORDER BY id", (cr["id"],))}

            before = approval_state()
            for case, auth in (("self_approve", a), ("model_approve", identity(actor="model-service", roles=["agent_owner"], type="service")),
                               ("cross_approve", b)):
                request(case, "POST", approve_path, auth)
            request("break_glass_denied", "POST", "/api/v1/change-requests", identity(actor="proposer", roles=["agent_owner"]),
                    {"policy_id": policy["id"], "idempotency_key": "tp07-breakglass-001", "approval_policy": "break_glass"})
            after = approval_state()
            check("denied_approvals_no_effect", before == after, {"before": before, "after": after})
            # DB-level fault is independent of application mocks and prevents the actual INSERT.
            sql("CREATE FUNCTION tp07_reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'tp07 injected audit failure'; END $$")

            def fault(enabled):
                sql("CREATE TRIGGER tp07_audit_fault BEFORE INSERT ON audit_event FOR EACH ROW EXECUTE FUNCTION tp07_reject_audit()"
                    if enabled else "DROP TRIGGER tp07_audit_fault ON audit_event")
                events.add("lab_fault", target="owned PostgreSQL audit_event INSERT", enabled=enabled)

            reviewer = identity(actor="independent-reviewer", roles=["reviewer"])
            fault(True)
            try:
                request("audit_failure_approve", "POST", approve_path, reviewer)
            finally:
                fault(False)
            after = approval_state()
            check("approval_audit_failure_atomic_rollback", before == after, {"before": before, "after": after})
            request("separate_approve", "POST", approve_path, reviewer)
            approved = approval_state()
            check("approved_with_audit_and_outbox", approved["change"] == [["approved", "independent-reviewer"]]
                  and ["change.approve", "independent-reviewer"] in approved["audit"]
                  and sum(row[0] == "policy.change.approved.v1" for row in approved["outbox"]) == 1, approved)
            request("repeat_approve", "POST", approve_path, reviewer)
            check("repeat_approval_no_duplicate", approved == approval_state(), approval_state())
            request("forged_effective", "POST", "/api/v1/policies", a,
                    {"name": "forged", "selector": {}, "status": "effective"})
            before = sql("SELECT id FROM environment ORDER BY id")
            fault(True)
            try:
                request("audit_failure_create", "POST", "/api/v1/environments", a, {"name": "audit-fault-object"})
            finally:
                fault(False)
            after = sql("SELECT id FROM environment ORDER BY id")
            check("create_audit_failure_atomic_rollback", before == after, {"before": before, "after": after})
            request("create_after_fault", "POST", "/api/v1/environments", a, {"name": "audit-fault-object"})
            for case, auth, other_actor in (("audit_a", a, "operator-b"), ("audit_b", b, "operator-a")):
                value = request(case, "GET", "/api/v1/audit-events", auth)
                check(case + "_isolated", isinstance(value, list) and bool(value) and all(x["actor_id"] != other_actor for x in value), value)
            if protocol.get("edge_assertions"):
                from edge_governance import run as run_edge
                run_edge(request, identity, sql, check, fault, events, out, a, b, ea, eb)
            if protocol.get('risk_assertions'):
                from enterprise_native_edge import run as run_native_edge
                if protocol.get('rule_race_profile'):
                    from enterprise_rule_race import run as run_risk
                elif protocol.get('risk_race_profile'):
                    from enterprise_risk_race import run as run_risk
                elif protocol.get('risk_worker_cycle'):
                    from enterprise_risk_worker import run as run_risk
                elif protocol.get('risk_boundary_profile'):
                    from enterprise_risk_boundaries import run as run_risk
                elif protocol.get('risk_lifecycle_v2'):
                    from enterprise_risk_v2 import run as run_risk
                else:
                    from enterprise_risk import run as run_risk
                run_native_edge(request, sql, check, events, out, a, ea, base_url, protocol['native_build'])
                run_risk(request, identity, sql, check, fault, events, out, a, b, command, python, api_dir, env, rows)
            if protocol.get("backend_assertions"):
                from backend_governance import run as run_backend
                if protocol.get('native_enterprise_assertions'):
                    from enterprise_native_edge import ASSET_NAME
                    from enterprise_native_edge import run as run_native_edge
                    run_native_edge(request, sql, check, events, out, a, ea, base_url, protocol['native_build'])
                    run_backend(request, identity, sql, check, events, out, a, ea, backend_fixture, asset_name=ASSET_NAME, effects=True,
                                authority_boundaries=bool(protocol.get('enterprise_authority_assertions')))
                else:
                    run_backend(request, identity, sql, check, events, out, a, ea, backend_fixture)
            if protocol.get("ui_assertions"):
                from ui_governance import run as run_ui
                run_ui(request, identity, sql, check, events, out, candidate, base_url, a)
            if protocol.get("race_assertions"):
                from concurrent_governance import run as run_race
                run_race(request, identity, sql, check, events, out, base_url, conninfo, a)
            write_json(out / "database-final.json", {"environment": sql("SELECT id,tenant_id,name,mode FROM environment ORDER BY id"),
                       "approval": approval_state(), "migration": version})
    except Exception as exc:  # noqa: BLE001 -- preserve failed run and clean owned resources
        # Exception strings can include connection credentials; preserve type only.
        failure = type(exc).__name__
        events.add("runner_failure", exception_type=failure,
                   frames=[{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                           for frame in traceback.extract_tb(exc.__traceback__)])
    finally:
        if api is not None:
            api.terminate()
            try:
                api.wait(timeout=8)
            except subprocess.TimeoutExpired:
                api.kill()
                api.wait(timeout=5)
            cleanup["api_stopped"] = api.poll() is not None
        if log is not None:
            log.close()
        if jwks is not None:
            jwks.shutdown()
            jwks.server_close()
            cleanup["jwks_stopped"] = True
        if container is not None:
            removed = command(["docker", "rm", "--force", "--volumes", container])
            cleanup["owned_container_removed"] = removed.returncode == 0
        if backend_fixture is not None:
            backend_fixture.close()
            details = backend_fixture.cleanup
            write_json(out / "backend-cleanup.json", details)
            cleanup["openshell_cleaned"] = (details.get("gateway_stopped") is True and details.get("network_removed") is True
                                            and details.get("container_inventory_checked") is True and all(x["removed"] for x in details["containers"]))
            if protocol.get('native_enterprise_assertions'):
                cleanup['openshell_cleaned'] = cleanup['openshell_cleaned'] and details.get('receiver_removed') is True
        events.add("cleanup", **cleanup)
    missing = sorted(set(protocol["expected_status"]) - {r["case_id"] for r in rows})
    summary = {"run_id": run_id, "protocol_id": protocol_id, "protocol_sha256": sha256(protocol_path),
               "checks": checks, "http_case_count": len(rows), "missing": missing, "failure": failure,
               "cleanup": cleanup, "passed": not failure and not missing and all(c["passed"] for c in checks)
               and len(cleanup) == (4 if protocol.get("backend_assertions") else 3) and all(cleanup.values()), "scope": protocol["scope"], "limits": protocol["limits"]}
    write_json(out / "http.json", rows)
    write_json(out / "summary.json", summary)
    write_json(out / "protocol.json", protocol)
    manifest = {"run_id": run_id, "created_at": utc_now(), "artifacts": {
        p.name: sha256(p) for p in sorted(out.iterdir()) if p.is_file()}}
    if protocol.get("ui_assertions") and (out / "ui-observations.json").exists():
        manifest["artifacts"].update(json.loads((out / "ui-observations.json").read_text())["artifacts"])
    write_json(out / "manifest.json", manifest)
    print(json.dumps({"run_id": run_id, "passed": summary["passed"], "checks": len(checks),
                      "http_cases": len(rows), "failure": failure, "missing": missing,
                      "manifest_sha256": sha256(out / "manifest.json")}))
    return 0 if summary["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "run"])
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--protocol-id", default="governance-http-v1")
    parser.add_argument("--run-id", default="governance-http-001")
    parser.add_argument("--include-edge", action="store_true", help="freeze additional Edge and asset/evidence probes")
    parser.add_argument("--include-backend", action="store_true", help="freeze real owned mTLS OpenShell deployment probes")
    parser.add_argument("--include-ui", action="store_true", help="freeze production build browser governance probes")
    parser.add_argument("--include-concurrency", action="store_true", help="freeze controlled concurrent governance probes")
    parser.add_argument("--candidate-root", type=Path, help="explicit separate candidate directory when freezing a repair cohort")
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.campaign.resolve(), args.protocol_id, args.include_edge, args.include_backend, args.include_ui,
               args.include_concurrency, args.candidate_root.resolve() if args.candidate_root else None)
        return 0
    return run(args.campaign.resolve(), args.protocol_id, args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
