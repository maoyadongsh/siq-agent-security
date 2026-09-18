#!/usr/bin/env python3
"""D08 service-level acceptance: Python enterprise service real API -> OpenShell
gateway apply / rollback / timeout / permission.

Ledger constraint this driver exists to satisfy:
    "不能将单独 Python runner 直接调用标成服务级"

所以本驱动 **不** 直接调用 OpenShellCliBackend。它启动真实的 uvicorn 进程
(app.main:app)，只通过 HTTP 打生产路由 POST /api/v1/deployments、
POST /api/v1/deployments/{id}/receipt-verify、POST /api/v1/deployments/{id}/rollback，
再由 **独立** 的 openshell CLI 读回（source scripts/openshell/env.sh，与适配器
SIQ_AS_OPENSHELL_ENV_SH 分支同一调用形态）交叉验证。

四个服务（同一 batch 自有 sqlite + 稳定签名种子）：
  A backend=none          真实企业链路 + 权限/SoD 否定项；部署必须 409 enforcement_backend_disabled
  B backend=openshell-cli apply -> 外部读回 -> receipt-verify -> rollback -> 外部读回回到原 Hash
                          再 apply 第二条策略（D2），保持后端已变更后被停掉
  C backend=openshell-cli 全新进程：回滚 D2 必须 502 openshell_rollback_failed（operation_unknown），
                          外部读回证明后端零变更
  D CLI 指向 batch 自有的黑洞监听端口：部署必须 502 openshell_preflight_failed，外部读回证明零变更
  收尾：服务之外一次 CLI 还原，最终 Hash 回到 pristine 并记录为"服务外清理"

约束：不重启共享 gateway(pid 4009810)、不 pkill/killall、不读/输出密钥、
不调用付费模型或生产业务端点、不改 hosts/代理/系统 DNS。
证据：结果 JSON 到 evidence 根，服务 stdout/stderr 与含原文的读回放 *-private/ (0700/0600)。
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]
CONTROL_API = WORKTREE / "apps" / "control-api"
sys.path.insert(0, str(CONTROL_API))  # app.tests.edge_helpers / app.evidence_signing
VENV_PY = CONTROL_API / ".venv" / "bin" / "python"
# Assigned only from explicit operator arguments; never reuse a historical sandbox.
ENV_SH = None
CLI_BIN = None
SANDBOX = None
PRISTINE_HASH = None

TENANT = "tnt-d08"
OWNER = "d08-owner"
APPROVER = "d08-approver"
VIEWER = "d08-viewer"
OTHER_TENANT = "tnt-d08-other"
OTHER_USER = "d08-other"

ROLES_OWNER = "tenant_admin,security_admin,agent_owner,platform_operator"
ROLES_APPROVER = "security_admin"
ROLES_VIEWER = "viewer"
ROLES_OTHER = "tenant_admin,security_admin,agent_owner,platform_operator"

SERVICE_BOOT_TIMEOUT = 90
SERVICE_STOP_TIMEOUT = 20

CHECKS = []


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Check(Exception):
    pass


def check(cond, label):
    if not cond:
        raise Check(label)


def record(leg, expected, actual, ok, note=""):
    row = {
        "leg": leg,
        "expected": expected,
        "actual": actual,
        "ok": bool(ok),
        "note": note,
        "at": utcnow(),
    }
    CHECKS.append(row)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {leg} | expect={expected} | actual={actual}" + (f" | {note}" if note else ""), flush=True)
    return row


def clean_env():
    """Drop inherited XDG_*/OPENSHELL_*/SIQ_AS_* so nothing leaks in from a
    previously sourced shell (this is exactly the class of bug that produced the
    bogus CertificateRequired probe earlier in the batch)."""
    keep = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "TMPDIR")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


class Http:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def __call__(self, method, path, body=None, headers=None, timeout=120):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"_raw": raw[:2000]}
            return exc.code, parsed


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    @property
    def text(self):
        return json.dumps(self._body, ensure_ascii=False)


class ClientAdapter:
    """requests-like shim so app.tests.edge_helpers can drive real HTTP."""

    def __init__(self, http):
        self.http = http

    def post(self, path, json=None, headers=None, **kw):
        status, body = self.http("POST", path, json, headers)
        return _Resp(status, body)

    def get(self, path, headers=None, **kw):
        status, body = self.http("GET", path, None, headers)
        return _Resp(status, body)

    def patch(self, path, json=None, headers=None, **kw):
        status, body = self.http("PATCH", path, json, headers)
        return _Resp(status, body)


def ident(tenant, user, roles):
    return {
        "X-Dev-Tenant-Id": tenant,
        "X-Dev-User-Id": user,
        "X-Dev-Roles": roles,
    }


OWNER_H = ident(TENANT, OWNER, ROLES_OWNER)
APPROVER_H = ident(TENANT, APPROVER, ROLES_APPROVER)
VIEWER_H = ident(TENANT, VIEWER, ROLES_VIEWER)
OTHER_H = ident(OTHER_TENANT, OTHER_USER, ROLES_OTHER)


def err_code(payload):
    # A successful list endpoint (e.g. GET /api/v1/candidates) hands us a plain
    # JSON list, so never assume the body is a mapping.
    if not isinstance(payload, dict):
        return None
    d = payload.get("detail")
    if isinstance(d, dict):
        return d.get("code")
    return d if isinstance(d, str) else None


def detail_str(payload):
    if not isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False)[:400]
    d = payload.get("detail")
    if isinstance(d, dict):
        return d.get("code") or json.dumps(d, ensure_ascii=False)
    return d if isinstance(d, str) else json.dumps(payload, ensure_ascii=False)[:400]


class Service:
    """A real uvicorn process serving app.main:app."""

    def __init__(self, name, backend, db_path, signing_seed, log_path, extra_env=None):
        self.name = name
        self.backend = backend
        self.db_path = db_path
        self.signing_seed = signing_seed
        self.log_path = Path(log_path)
        self.extra_env = dict(extra_env or {})
        self.port = free_port()
        self.proc = None
        self.http = Http(self.port)
        self._log = None

    def env(self):
        env = clean_env()
        env.update(
            {
                "SIQ_AS_DEV": "1",
                "SIQ_AS_ALLOW_SQLITE": "1",
                "SIQ_AS_DATABASE_URL": f"sqlite:///{self.db_path}",
                "SIQ_AS_SIGNING_KEY_FILE": str(self.signing_seed),
                "SIQ_AS_ENFORCEMENT_BACKEND": self.backend,
                "PYTHONPATH": str(CONTROL_API),
                "PYTHONUNBUFFERED": "1",
            }
        )
        env.update(self.extra_env)
        return env

    def start(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.log_path.parent, 0o700)
        self._log = open(self.log_path, "wb")
        os.chmod(self.log_path, 0o600)
        self.proc = subprocess.Popen(
            [
                str(VENV_PY), "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1", "--port", str(self.port),
                "--log-level", "info",
            ],
            cwd=str(CONTROL_API),
            env=self.env(),
            stdout=self._log,
            stderr=subprocess.STDOUT,
            umask=0o077,
        )
        deadline = time.time() + SERVICE_BOOT_TIMEOUT
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise Check(f"service {self.name} exited rc={self.proc.returncode} during boot")
            try:
                status, body = self.http("GET", "/health", timeout=5)
                if status == 200:
                    print(f"[svc] {self.name} up on 127.0.0.1:{self.port} pid={self.proc.pid}", flush=True)
                    return self
            except Exception:
                pass
            time.sleep(0.4)
        self.stop()
        raise Check(f"service {self.name} did not become healthy in {SERVICE_BOOT_TIMEOUT}s")

    def stop(self):
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=SERVICE_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=SERVICE_STOP_TIMEOUT)
        if self._log:
            self._log.close()
        print(f"[svc] {self.name} stopped rc={self.proc.returncode}", flush=True)
        self.proc = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


class BlackHole:
    """Loopback listener that accepts and then never answers -> adapter timeout."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self._held = []
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        self.sock.settimeout(0.5)
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
                self._held.append(conn)  # accepted, never answered
            except socket.timeout:
                continue
            except OSError:
                break

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass
        for c in self._held:
            try:
                c.close()
            except OSError:
                pass


def cli_policy_full():
    """Independent readback through the same external surface the adapter uses."""
    cmd = [
        "bash", "-c", 'source "$1" && shift && exec openshell "$@"',
        "openshell-env", str(ENV_SH), "policy", "get", SANDBOX, "--full",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=clean_env())
    return proc.returncode, proc.stdout, proc.stderr


def parse_full(out):
    version = None
    digest = None
    body = out
    for line in out.splitlines():
        if line.startswith("Version:"):
            try:
                version = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("Hash:"):
            digest = line.split(":", 1)[1].strip()
    marker = "\n---\n"
    if marker in out:
        body = out.split(marker, 1)[1]
    return version, digest, body


def outside_service_cleanup(private_dir, state):
    """Restore the batch-owned sandbox directly through the CLI.

    This is *not* a service capability claim: the service legitimately refuses to
    touch an operation it no longer knows about (service C proved exactly that).
    The batch therefore cleans up its own sandbox from outside the service and
    records the fact, along with the final Hash proof."""
    import yaml  # local import: only needed for cleanup

    rc, out, err = cli_policy_full()
    version, digest, body = parse_full(out)
    check(rc == 0 and version is not None and digest,
          "cleanup readback failed; no policy write attempted")
    doc = yaml.safe_load(body)
    check(isinstance(doc, dict), "cleanup readback malformed; no policy write attempted")
    if "network_policies" not in doc:
        record("Z1-outside-service-cleanup", "no network_policies left to remove",
               f"Hash={(digest or '?')[:12]}… already clean", digest == PRISTINE_HASH,
               "nothing to restore")
        return {"skipped": True, "hash": digest}

    check(state.get("applied2_version") == version
          and state.get("applied2_hash") == digest,
          "cleanup ownership/drift unconfirmed; manual restoration required")
    check(state.get("pristine_body"), "missing initial policy; no restoration attempted")
    target_file = private_dir / "cleanup-restore-policy.yaml"
    target_file.write_text(state["pristine_body"])
    os.chmod(target_file, 0o600)
    proc = subprocess.run(
        ["bash", "-c", 'source "$1" && shift && exec openshell "$@"',
         "openshell-env", str(ENV_SH), "policy", "set", SANDBOX,
         "--policy", str(target_file), "--wait", "--timeout", "120"],
        capture_output=True, text=True, env=clean_env(), timeout=240,
    )
    with open(private_dir / "z-cleanup-set.txt", "w") as fh:
        fh.write(proc.stdout + "\n---stderr---\n" + proc.stderr)
    os.chmod(private_dir / "z-cleanup-set.txt", 0o600)

    rc2, out2, err2 = cli_policy_full()
    v2, d2, body2 = parse_full(out2)
    with open(private_dir / "z-cleanup-final.txt", "w") as fh:
        fh.write(out2)
    os.chmod(private_dir / "z-cleanup-final.txt", 0o600)
    ok = proc.returncode == 0 and rc2 == 0 and d2 == PRISTINE_HASH and "network_policies" not in body2
    record("Z1-outside-service-cleanup",
           f"CLI-side restore returns Hash to {PRISTINE_HASH[:12]}…",
           f"set_rc={proc.returncode} hash={(d2 or '?')[:12]}… version={v2}",
           ok, "performed outside the service by the batch; the service itself "
               "correctly refuses to replay an unknown operation")
    return {"set_rc": proc.returncode, "hash_after": d2, "version_after": v2, "ok": ok}


def cli_snapshot(leg, note=""):
    rc, out, err = cli_policy_full()
    version, digest, body = parse_full(out)
    snap = {
        "leg": leg,
        "note": note,
        "rc": rc,
        "version": version,
        "hash": digest,
        "has_network_policies": "network_policies" in body,
        "at": utcnow(),
    }
    return snap, body, out


# --------------------------------------------------------------------------- #
# Service A: governance chain + permission negatives on backend=none
# --------------------------------------------------------------------------- #

def leg_service_a(svc, state, private_dir):
    http = svc.http
    legs = []

    status, env_body = http("POST", "/api/v1/environments",
                            {"name": "d08-service-env", "env_type": "host", "mode": "discovery"},
                            OWNER_H)
    check(status == 201, f"A env create -> {status} {detail_str(env_body)}")
    env_id = env_body["id"]
    record("A1-env-create", 201, status, True, f"env_id={env_id}")

    status, body = http("PATCH", f"/api/v1/environments/{env_id}/mode",
                        {"mode": "enforce", "reason": "d08 service-level acceptance"}, OWNER_H)
    record("A2-env-mode-enforce", 200, status, status == 200, detail_str(body))
    check(status == 200, f"A env mode -> {status} {detail_str(body)}")

    from app.tests.edge_helpers import (  # noqa: E402  (PYTHONPATH added at module import)
        candidate as edge_candidate,
        create_scan_task,
        edge_private_key,
        register_edge,
        signed_batch,
        signed_evidence,
    )

    client = ClientAdapter(http)
    identity = "d08-edge-01"
    edge_headers, _pk = register_edge(client, OWNER_H, env_id, identity)
    record("A3-edge-register", "device_secret issued", "issued",
           bool(edge_headers.get("Authorization")), f"edge_identity={identity}")
    check(edge_headers.get("Authorization"), "A edge register produced no device_secret")

    task_id = create_scan_task(client, OWNER_H, env_id, connector="hermes")
    record("A4-scan-task", "task created", task_id, bool(task_id), f"task_id={task_id}")

    pk = edge_private_key(identity)
    eid = "ev-d08-0001"
    ev = signed_evidence(pk, identity, eid, source_type="manifest",
                         source_locator="hermes://d08-agent/profile.json")
    cand = edge_candidate("d08-agent", [eid], source_type="hermes_profile")
    batch = signed_batch(pk, task_id, candidates=[cand], evidence=[ev], permission_facts=[])
    status, body = http("POST", "/edge/v1/batches", batch, edge_headers)
    record("A5-edge-batch-ingest", "200/201/202", status, status in (200, 201, 202),
           detail_str(body) if status >= 400 else f"accepted={json.dumps(body, ensure_ascii=False)[:160]}")
    check(status in (200, 201, 202), f"A edge batch -> {status} {detail_str(body)}")

    status, body = http("GET", "/api/v1/candidates", None, OWNER_H)
    check(status == 200, f"A candidates -> {status} {detail_str(body)}")
    items = body if isinstance(body, list) else body.get("items", [])
    mine = [c for c in items if c.get("name") == "d08-agent"]
    check(mine, "A edge-ingested candidate not visible via GET /api/v1/candidates")
    asset_id = mine[0]["id"]
    record("A6-candidate-visible", "edge-ingested candidate listed", f"1 of {len(items)}",
           True, f"asset_id={asset_id}")

    status, body = http("POST", f"/api/v1/candidates/{asset_id}/confirm",
                        {"role": "d08-agent-role"}, OWNER_H)
    check(status == 200, f"A confirm -> {status} {detail_str(body)}")
    record("A7-candidate-confirm", 200, status, True, f"status={body.get('status')}")

    status, inst = http("GET", f"/api/v1/assets/{asset_id}/instances", None, OWNER_H)
    check(status == 200 and inst, f"A instances -> {status}")
    inst_items = inst if isinstance(inst, list) else inst.get("items", [])
    check(inst_items, "A confirm did not auto-create an AgentInstance")
    instance_id = inst_items[0]["id"]
    record("A8-instance-autocreated", ">=1 instance", len(inst_items), True,
           f"instance_id={instance_id} runtime={inst_items[0].get('runtime')}")

    status, binding = http("POST", "/api/v1/runtime-bindings",
                           {"environment_id": env_id, "agent_instance_id": instance_id,
                            "backend": "openshell-cli", "backend_target_id": SANDBOX}, OWNER_H)
    check(status == 201, f"A binding -> {status} {detail_str(binding)}")
    binding_id = binding["id"]
    record("A9-binding", 201, status, True, f"binding_id={binding_id} target={SANDBOX}")

    status, policy = http("POST", "/api/v1/policies",
                          {"name": "d08-service-policy",
                           "selector": {"agent_ids": [asset_id]},
                           "enforcement_mode": "block",
                           "network": [{"endpoint": "api.openai.com:443", "effect": "allow",
                                        "binary_paths": ["/usr/bin/curl"]}]},
                          OWNER_H)
    check(status == 201, f"A policy -> {status} {detail_str(policy)}")
    policy_id = policy["id"]
    record("A10-policy-create", 201, status, True, f"policy_id={policy_id}")

    status, cr = http("POST", "/api/v1/change-requests",
                      {"policy_id": policy_id, "idempotency_key": "d08-cr-1"}, OWNER_H)
    check(status == 201, f"A cr -> {status} {detail_str(cr)}")
    cr_id = cr["id"]

    # SoD negative: the requester cannot approve their own request.
    status, body = http("POST", f"/api/v1/change-requests/{cr_id}/approve", {}, OWNER_H)
    sod_ok = status == 409 and "segregation_of_duties" in json.dumps(body)
    record("A11-sod-self-approve", "409 segregation_of_duties", f"{status} {detail_str(body)}",
           sod_ok, "approver == requester must be refused")
    check(sod_ok, f"A SoD -> {status} {detail_str(body)}")

    status, body = http("POST", f"/api/v1/change-requests/{cr_id}/approve", {}, APPROVER_H)
    check(status == 200, f"A approve -> {status} {detail_str(body)}")
    record("A12-approve-by-other", 200, status, True, f"approver={APPROVER}")

    # backend=none gate must refuse the deployment *after* a fully approved CR.
    status, body = http("POST", "/api/v1/deployments",
                        {"change_request_id": cr_id, "environment_id": env_id, "binding_id": binding_id},
                        OWNER_H)
    gate_ok = status == 409 and "enforcement_backend_disabled" in json.dumps(body)
    record("A13-backend-none-gate", "409 enforcement_backend_disabled", f"{status} {detail_str(body)}",
           gate_ok, "fully approved CR still cannot deploy when enforcement backend is none")
    check(gate_ok, f"A backend-none gate -> {status} {detail_str(body)}")

    # Permission negatives over real HTTP.
    status, body = http("POST", "/api/v1/deployments",
                        {"change_request_id": cr_id, "environment_id": env_id, "binding_id": binding_id},
                        {})  # no X-Dev-Tenant-Id -> dev branch skipped
    missing_ok = status == 401 and "missing_credentials" in json.dumps(body)
    record("A14-missing-credentials", "401 missing_credentials", f"{status} {detail_str(body)}",
           missing_ok, "no X-Dev-Tenant-Id header")
    check(missing_ok, f"A missing creds -> {status} {detail_str(body)}")

    status, body = http("POST", "/api/v1/deployments",
                        {"change_request_id": cr_id, "environment_id": env_id, "binding_id": binding_id},
                        VIEWER_H)
    record("A15-viewer-forbidden", "403 forbidden", f"{status} {detail_str(body)}",
           status == 403, "viewer lacks policy:manage")

    status, body = http("POST", f"/api/v1/candidates/{asset_id}/confirm",
                        {"role": "d08-agent-role"}, OTHER_H)
    cross_ok = status == 404
    record("A16-cross-tenant-404", "404 not_found", f"{status} {detail_str(body)}", cross_ok,
           "another tenant cannot resolve this tenant's asset id")

    state.update({"env_id": env_id, "asset_id": asset_id, "instance_id": instance_id,
                  "binding_id": binding_id, "policy_id": policy_id, "cr_id": cr_id})
    return legs


# --------------------------------------------------------------------------- #
# Service B: real apply -> external readback -> receipt-verify -> rollback
# --------------------------------------------------------------------------- #

def leg_service_b(svc, state, private_dir):
    http = svc.http

    with open(private_dir / "b-cli-before.txt", "w") as fh:
        snap_before, body_before, raw_before = cli_snapshot("B0-before")
        fh.write(raw_before)
    os.chmod(private_dir / "b-cli-before.txt", 0o600)
    pre_ok = snap_before["hash"] == PRISTINE_HASH and not snap_before["has_network_policies"]
    record("B0-pristine-precondition", f"Hash={PRISTINE_HASH[:12]}… no network_policies",
           f"Hash={(snap_before['hash'] or '?')[:12]}… net={snap_before['has_network_policies']}",
           pre_ok, f"version={snap_before['version']}")
    if not pre_ok:
        raise Check("sandbox is not pristine at D08 start; refusing to run destructive legs")

    # --- deploy #1 -------------------------------------------------------- #
    status, dep = http("POST", "/api/v1/deployments",
                       {"change_request_id": state["cr_id"], "environment_id": state["env_id"],
                        "binding_id": state["binding_id"]}, OWNER_H)
    dep_ok = status in (200, 201) and dep.get("status") in ("sent", "effective")
    record("B1-deploy-effective", "201 + status effective", f"{status} status={dep.get('status')}",
           dep_ok, f"target={dep.get('target')} err={detail_str(dep) if not dep_ok else ''}")
    check(dep_ok, f"B deploy -> {status} {detail_str(dep)}")
    dep1_id = dep["id"]
    target_ok = dep.get("target") == SANDBOX
    record("B2-deploy-target-binding", SANDBOX, dep.get("target"), target_ok,
           "deployment.target must equal binding.backend_target_id")

    status, listing = http("GET", "/api/v1/deployments", None, OWNER_H)
    rows = listing if isinstance(listing, list) else (listing or {}).get("items", [])
    detail = next((d for d in rows if d.get("id") == dep1_id), {})
    verification = (detail or {}).get("verification") or {}
    lvl = verification.get("level")
    method = verification.get("method")
    verify_ok = status == 200 and method == "config_readback"
    record("B3-verification-level", "method=config_readback (readback, NOT enforcement_verified)",
           f"level={lvl} method={method}", verify_ok,
           "readback proves config state only, never general behaviour protection")

    status, att = http("POST", f"/api/v1/deployments/{dep1_id}/receipt-verify", {}, OWNER_H)
    record("B4-receipt-verify", 200, status, status == 200,
           f"attestation={json.dumps(att, ensure_ascii=False)[:200]}")

    with open(private_dir / "b-cli-applied.txt", "w") as fh:
        snap_applied, body_applied, raw_applied = cli_snapshot("B5-after-apply")
        fh.write(raw_applied)
    os.chmod(private_dir / "b-cli-applied.txt", 0o600)
    applied_ok = (
        snap_applied["rc"] == 0
        and snap_applied["has_network_policies"]
        and "api.openai.com" in body_applied
        and snap_applied["hash"] != PRISTINE_HASH
    )
    record("B5-external-readback-applied",
           "independent CLI shows network_policies with api.openai.com:443 and a new Hash",
           f"rc={snap_applied['rc']} net={snap_applied['has_network_policies']} "
           f"version={snap_applied['version']} hash={(snap_applied['hash'] or '?')[:12]}…",
           applied_ok, "read back outside the service, via the same env.sh the adapter uses")

    # --- rollback --------------------------------------------------------- #
    status, rb = http("POST", f"/api/v1/deployments/{dep1_id}/rollback", {}, OWNER_H)
    rollback = ((rb or {}).get("verification") or {}).get("rollback") or {}
    rb_ok = status == 200 and rollback.get("result") == "restored"
    record("B6-rollback-restored", "200 + verification.rollback.result=restored",
           f"{status} result={rollback.get('result')} err={detail_str(rb) if not rb_ok else ''}",
           rb_ok, f"restored_revision={rollback.get('restored_revision')}")
    check(rb_ok, f"B rollback -> {status} {detail_str(rb)}")

    with open(private_dir / "b-cli-restored.txt", "w") as fh:
        snap_restored, body_restored, raw_restored = cli_snapshot("B7-after-rollback")
        fh.write(raw_restored)
    os.chmod(private_dir / "b-cli-restored.txt", 0o600)
    restored_ok = snap_restored["hash"] == PRISTINE_HASH and not snap_restored["has_network_policies"]
    record("B7-external-readback-restored",
           f"CLI content Hash returns to {PRISTINE_HASH[:12]}… and network_policies gone",
           f"hash={(snap_restored['hash'] or '?')[:12]}… net={snap_restored['has_network_policies']} "
           f"version={snap_restored['version']}",
           restored_ok, "independent proof the rollback really reached the gateway")

    # Re-rollback of a now rolled_back deployment must be refused.
    status, body = http("POST", f"/api/v1/deployments/{dep1_id}/rollback", {}, OWNER_H)
    record("B8-double-rollback", "409 invalid_state", f"{status} {detail_str(body)}",
           status == 409, "rollback is not idempotent-replayable")

    # --- deploy #2 (left applied on purpose for service C) ---------------- #
    status, policy2 = http("POST", "/api/v1/policies",
                           {"name": "d08-service-policy-2",
                            "selector": {"agent_ids": [state["asset_id"]]},
                            "enforcement_mode": "block",
                            "network": [{"endpoint": "api.anthropic.com:443", "effect": "allow",
                                         "binary_paths": ["/usr/bin/curl"]}]},
                           OWNER_H)
    check(status == 201, f"B policy2 -> {status} {detail_str(policy2)}")
    status, cr2 = http("POST", "/api/v1/change-requests",
                       {"policy_id": policy2["id"], "idempotency_key": "d08-cr-2"}, OWNER_H)
    check(status == 201, f"B cr2 -> {status} {detail_str(cr2)}")
    status, approved2 = http("POST", f"/api/v1/change-requests/{cr2['id']}/approve", {}, APPROVER_H)
    check(status == 200, f"B approve2 -> {status} {detail_str(approved2)}")

    status, dep2 = http("POST", "/api/v1/deployments",
                        {"change_request_id": cr2["id"], "environment_id": state["env_id"],
                         "binding_id": state["binding_id"]}, OWNER_H)
    dep2_ok = status in (200, 201) and dep2.get("status") in ("sent", "effective")
    record("B9-deploy2-effective", "201 + effective", f"{status} status={dep2.get('status')}",
           dep2_ok, f"deployment_id={dep2.get('id')}")
    check(dep2_ok, f"B deploy2 -> {status} {detail_str(dep2)}")

    with open(private_dir / "b-cli-applied2.txt", "w") as fh:
        snap2, body2, raw2 = cli_snapshot("B10-after-apply2")
        fh.write(raw2)
    os.chmod(private_dir / "b-cli-applied2.txt", 0o600)
    applied2_ok = snap2["rc"] == 0 and "api.anthropic.com" in body2
    record("B10-external-readback-applied2", "CLI shows api.anthropic.com:443",
           f"rc={snap2['rc']} net={snap2['has_network_policies']} version={snap2['version']}",
           applied2_ok, "deploy #2 deliberately left applied for the service-C leg")

    state.update({"dep1_id": dep1_id, "dep2_id": dep2["id"], "cr2_id": cr2["id"],
                  "applied2_version": snap2["version"], "applied2_hash": snap2["hash"]})
    return {"snapshot_before": snap_before, "snapshot_applied": snap_applied,
            "snapshot_restored": snap_restored, "snapshot_applied2": snap2}


# --------------------------------------------------------------------------- #
# Service C: fresh process must not be able to replay the rollback
# --------------------------------------------------------------------------- #

def leg_service_c(svc, state, private_dir):
    http = svc.http

    status, body = http("POST", f"/api/v1/deployments/{state['dep2_id']}/rollback", {}, OWNER_H)
    blob = json.dumps(body, ensure_ascii=False)
    unknown_ok = status == 502 and "openshell_rollback_failed" in blob
    record("C1-fresh-process-operation-unknown",
           "502 openshell_rollback_failed (operation_unknown)",
           f"{status} {detail_str(body)}", unknown_ok,
           "in-process registry is not a cross-restart source of truth; "
           "a fresh process must refuse rather than replay")
    check(unknown_ok, f"C rollback -> {status} {detail_str(body)}")

    with open(private_dir / "c-cli-after-refused-rollback.txt", "w") as fh:
        snap, body_text, raw = cli_snapshot("C2-after-refused-rollback")
        fh.write(raw)
    os.chmod(private_dir / "c-cli-after-refused-rollback.txt", 0o600)
    untouched = (
        snap["rc"] == 0
        and "api.anthropic.com" in body_text
        and snap["version"] == state["applied2_version"]
        and snap["hash"] == state["applied2_hash"]
    )
    record("C2-backend-zero-mutation",
           "revision + Hash unchanged, deploy #2 policy still present",
           f"version={snap['version']} (was {state['applied2_version']}) "
           f"hash_match={snap['hash'] == state['applied2_hash']}",
           untouched, "a refused rollback must not have touched the gateway")
    return {"snapshot_after_refused_rollback": snap}


# --------------------------------------------------------------------------- #
# Service D: unreachable gateway -> preflight timeout, zero mutation
# --------------------------------------------------------------------------- #

def leg_service_d(svc, state, private_dir):
    http = svc.http

    status, dep3 = http("POST", "/api/v1/policies",
                        {"name": "d08-service-policy-3",
                         "selector": {"agent_ids": [state["asset_id"]]},
                         "enforcement_mode": "block",
                         "network": [{"endpoint": "api.example.com:443", "effect": "allow",
                                      "binary_paths": ["/usr/bin/curl"]}]},
                        OWNER_H)
    check(status == 201, f"D policy3 -> {status} {detail_str(dep3)}")
    status, cr3 = http("POST", "/api/v1/change-requests",
                       {"policy_id": dep3["id"], "idempotency_key": "d08-cr-3"}, OWNER_H)
    check(status == 201, f"D cr3 -> {status} {detail_str(cr3)}")
    status, approved3 = http("POST", f"/api/v1/change-requests/{cr3['id']}/approve", {}, APPROVER_H)
    check(status == 200, f"D approve3 -> {status} {detail_str(approved3)}")

    started = time.time()
    status, body = http("POST", "/api/v1/deployments",
                        {"change_request_id": cr3["id"], "environment_id": state["env_id"],
                         "binding_id": state["binding_id"]}, OWNER_H, timeout=600)
    elapsed = round(time.time() - started, 2)
    blob = json.dumps(body, ensure_ascii=False)
    timeout_ok = status == 502 and "openshell_preflight_failed" in blob
    record("D1-unreachable-gateway-preflight", "502 openshell_preflight_failed",
           f"{status} {detail_str(body)} ({elapsed}s)", timeout_ok,
           "unreachable backend is an explicit gateway failure, never a silent success")
    check(timeout_ok, f"D preflight -> {status} {detail_str(body)}")

    # A failed deployment must not have left a row behind nor touched the gateway.
    status, listing = http("GET", "/api/v1/deployments", None, OWNER_H)
    items = listing if isinstance(listing, list) else (listing or {}).get("items", [])
    leaked = [d for d in items if d.get("change_request_id") == cr3["id"]]
    record("D2-no-deployment-row-on-preflight-failure", "0 rows for the failed CR",
           len(leaked), not leaked, "preflight failure happens before the row is created")

    with open(private_dir / "d-cli-after-timeout.txt", "w") as fh:
        snap, body_text, raw = cli_snapshot("D3-after-timeout")
        fh.write(raw)
    os.chmod(private_dir / "d-cli-after-timeout.txt", 0o600)
    untouched = (
        snap["rc"] == 0
        and "api.example.com" not in body_text
        and snap["version"] == state["applied2_version"]
        and snap["hash"] == state["applied2_hash"]
    )
    record("D3-backend-zero-mutation",
           "api.example.com absent, revision + Hash unchanged",
           f"version={snap['version']} (was {state['applied2_version']}) "
           f"example_com_present={'api.example.com' in body_text}",
           untouched, "a timed-out preflight must not have touched the gateway")
    return {"snapshot_after_timeout": snap}


# --------------------------------------------------------------------------- #

def prepare_private_materials(root):
    """Use an exclusive private directory so reruns never overwrite credentials."""
    private = root / "d08-private"
    private.mkdir(mode=0o700)
    db = private / "d08.db"
    fd = os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    return private, db, private / "d08-signing.seed"


def main():
    global ENV_SH, CLI_BIN, SANDBOX, PRISTINE_HASH
    # Evidence includes service logs and an isolated signing seed. The driver
    # must create even its public summary with owner-only permissions.
    os.umask(0o077)
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True, help="evidence run directory")
    ap.add_argument("--target", required=True, help="dedicated batch-owned sandbox")
    ap.add_argument("--confirm-target", required=True, help="repeat target; exclusive use required")
    ap.add_argument("--env-script", required=True)
    ap.add_argument("--cli-bin", required=True)
    ap.add_argument("--expected-policy-hash", required=True)
    args = ap.parse_args()
    if (args.target != args.confirm_target
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.target)
            or not re.fullmatch(r"[0-9a-f]{64}", args.expected_policy_hash)):
        ap.error("explicit target confirmation and full baseline hash required")
    ENV_SH = Path(args.env_script).resolve(strict=True)
    CLI_BIN = Path(args.cli_bin).resolve(strict=True)
    if not ENV_SH.is_file() or not CLI_BIN.is_file() or not os.access(CLI_BIN, os.X_OK):
        ap.error("environment script and executable CLI required")
    SANDBOX, PRISTINE_HASH = args.target, args.expected_policy_hash

    root = Path(args.evidence).resolve()
    root.mkdir(parents=True, exist_ok=True)
    private, db_path, signing_seed = prepare_private_materials(root)

    state = {}
    snapshots = {}
    result = {"started_at": utcnow(), "legs": [], "checks": CHECKS, "fatal": None}
    services = []

    def build(name, backend, extra_env=None):
        svc = Service(name, backend, db_path, signing_seed, private / f"{name}.console.log", extra_env)
        services.append(svc)
        return svc

    try:
        import yaml
        rc, initial, _ = cli_policy_full()
        revision, digest, initial_body = parse_full(initial)
        check(rc == 0 and revision is not None and digest == PRISTINE_HASH,
              "initial policy does not match explicit baseline")
        initial_doc = yaml.safe_load(initial_body)
        check(isinstance(initial_doc, dict) and "network_policies" not in initial_doc,
              "dedicated sandbox must start without network_policies")
        state["pristine_body"] = initial_body
        svc_a = build("svc-a-none", "none")
        with svc_a:
            leg_service_a(svc_a, state, private)

        svc_b = build("svc-b-cli", "openshell-cli", {"SIQ_AS_OPENSHELL_ENV_SH": str(ENV_SH)})
        with svc_b:
            snapshots = leg_service_b(svc_b, state, private)

        svc_c = build("svc-c-fresh", "openshell-cli", {"SIQ_AS_OPENSHELL_ENV_SH": str(ENV_SH)})
        with svc_c:
            snapshots.update(leg_service_c(svc_c, state, private))

        blackhole = BlackHole().start()
        try:
            svc_d = build("svc-d-timeout", "openshell-cli",
                          {"SIQ_AS_OPENSHELL_CLI_BIN": str(CLI_BIN),
                           "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT": f"http://127.0.0.1:{blackhole.port}",
                           "SIQ_AS_OPENSHELL_GATEWAY_INSECURE": "1"})
            with svc_d:
                snapshots.update(leg_service_d(svc_d, state, private))
        finally:
            blackhole.stop()

    except Exception as exc:  # noqa: BLE001
        result["fatal"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        for svc in services:
            try:
                svc.stop()
            except Exception:
                pass
        try:
            result["cleanup"] = outside_service_cleanup(private, state)
        except Exception as exc:  # noqa: BLE001
            record("Z1-outside-service-cleanup", "CLI-side restore succeeded",
                   f"{type(exc).__name__}: {exc}", False, "cleanup failed - sandbox may need manual restore")
            traceback.print_exc()

    result["finished_at"] = utcnow()
    result["state"] = {k: v for k, v in state.items() if k not in ("device_secret", "pristine_body")}
    result["snapshots"] = snapshots
    result["summary"] = {
        "total": len(CHECKS),
        "passed": sum(1 for c in CHECKS if c["ok"]),
        "failed": [c["leg"] for c in CHECKS if not c["ok"]],
    }

    out_path = root / "d08-service-gateway.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[d08] checks={result['summary']['total']} passed={result['summary']['passed']} "
          f"failed={result['summary']['failed']}", flush=True)
    print(f"[d08] result -> {out_path}", flush=True)
    return 0 if not result["summary"]["failed"] and not result["fatal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
