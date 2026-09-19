#!/usr/bin/env python3
"""Isolated production-shape Control API check with PostgreSQL and local RS256 JWKS.

The issuer is a loopback test fixture, not a customer IdP. Requires a locally
available postgres:17-alpine Docker image; never pulls an image or uses an
existing database. The exact container and API child process are removed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps/control-api"
IMAGE = "postgres:17-alpine"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def require(ok: bool, label: str) -> None:
    if not ok:
        raise AssertionError(label)


def private_file(path: Path):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8")


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="new private JSON report path")
    args = parser.parse_args()
    out = args.out.resolve()
    require(not out.exists(), "output_exists")

    checks: list[dict[str, object]] = []
    failure = None
    container_id = None
    server = None
    server_log = None
    jwks_server = None
    jwks_thread = None
    resources: dict[str, object] = {"container_removed": False, "api_stopped": False, "jwks_stopped": False}

    def check(label: str, ok: bool) -> None:
        checks.append({"id": label, "passed": bool(ok)})
        require(ok, label)

    def child(command: list[str], env: dict[str, str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, cwd=API, env=env, text=True, capture_output=True,
                              timeout=timeout, check=False)

    try:
        image = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
        check("local_postgres_image_available_without_pull", image.returncode == 0)
        db_port = free_port()
        api_port = free_port()
        password = secrets.token_hex(24)
        name = "siq-lx07-" + secrets.token_hex(6)
        docker_env = dict(os.environ, POSTGRES_PASSWORD=password, POSTGRES_USER="siq_fixture",
                          POSTGRES_DB="siq_lx07")
        created = subprocess.run([
            "docker", "run", "-d", "--rm", "--name", name,
            "--label", "siq.batch=lx07-postgres-oidc", "-p", f"127.0.0.1:{db_port}:5432",
            "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_USER", "-e", "POSTGRES_DB", IMAGE,
        ], env=docker_env, text=True, capture_output=True, timeout=30, check=False)
        require(created.returncode == 0, "isolated_postgres_start")
        container_id = created.stdout.strip()
        require(bool(re.fullmatch(r"[a-f0-9]{64}", container_id)), "owned_container_id")
        conninfo = f"postgresql://siq_fixture:{password}@127.0.0.1:{db_port}/siq_lx07"
        deadline = time.monotonic() + 45
        while True:
            try:
                with psycopg.connect(conninfo, connect_timeout=2) as con:
                    con.execute("SELECT 1").fetchone()
                break
            except psycopg.OperationalError:
                require(time.monotonic() < deadline, "postgres_ready_timeout")
                time.sleep(0.3)
        check("isolated_postgres_ready", True)

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
        public_jwk.update({"kid": "lx07-local-kid", "alg": "RS256", "use": "sig"})
        next_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        next_public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(next_private_key.public_key()))
        next_public_jwk.update({"kid": "lx07-rotated-kid", "alg": "RS256", "use": "sig"})
        jwks_lock = threading.Lock()
        jwks_state = {"body": json.dumps({"keys": [public_jwk]}).encode(), "unavailable": False}

        class JWKSHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler API
                if self.path != "/jwks":
                    self.send_error(404)
                    return
                with jwks_lock:
                    body = jwks_state["body"]
                    unavailable = jwks_state["unavailable"]
                if unavailable:
                    self.send_error(503)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        jwks_server = HTTPServer(("127.0.0.1", 0), JWKSHandler)
        jwks_thread = threading.Thread(target=jwks_server.serve_forever, daemon=True)
        jwks_thread.start()
        issuer = f"http://127.0.0.1:{jwks_server.server_port}/issuer"
        env = dict(os.environ)
        env.update({
            "SIQ_AS_DEV": "0",
            "SIQ_AS_DATABASE_URL": conninfo.replace("postgresql://", "postgresql+psycopg://", 1),
            "SIQ_AS_OIDC_JWKS_URL": f"http://127.0.0.1:{jwks_server.server_port}/jwks",
            "SIQ_AS_OIDC_ISSUER": issuer,
            "SIQ_AS_JWT_AUDIENCE": "siq-lx07-test",
            "SIQ_AS_JWKS_TTL_SECONDS": "5",
            "SIQ_AS_TASK_SIGNING_KEY_SEED": base64.b64encode(secrets.token_bytes(32)).decode(),
            "SIQ_AS_BOOTSTRAP_TENANT_ID": "lx07-a",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        })
        env.pop("SIQ_AS_ALLOW_SQLITE", None)
        env.pop("SIQ_AS_DEV_JWT_SECRET", None)
        sqlite_env = dict(env, SIQ_AS_DATABASE_URL="sqlite:////tmp/lx07-forbidden.db")
        denied = child([sys.executable, "-c", "from app.config import load_settings; load_settings()"], sqlite_env)
        check("production_rejects_sqlite", denied.returncode != 0 and "仅允许 PostgreSQL" in denied.stderr)

        migrate = [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"]
        first = child(migrate, env)
        check("postgres_migration_from_empty_database", first.returncode == 0)
        second = child(migrate, env)
        check("postgres_migration_replay_idempotent", second.returncode == 0)
        with psycopg.connect(conninfo) as con:
            version = con.execute("SELECT version_num FROM alembic_version").fetchone()
        check("postgres_alembic_head_recorded", version == ("0016",))

        base_url = f"http://127.0.0.1:{api_port}"

        starts = 0

        def start_api():
            nonlocal server, server_log, starts
            starts += 1
            server_log = private_file(out.parent / (out.stem + f".api.{starts}.log"))
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                       "--port", str(api_port), "--no-access-log"], cwd=API, env=env,
                                      stdin=subprocess.DEVNULL, stdout=server_log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 30
            with httpx.Client(trust_env=False, timeout=2) as probe:
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        break
                    try:
                        if probe.get(base_url + "/health").status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
            raise RuntimeError("production_api_start")

        def stop_api():
            nonlocal server, server_log
            if server is not None:
                server.terminate()
                try:
                    server.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
                server = None
            if server_log is not None:
                server_log.close()
                server_log = None

        def token(tenant: str, roles: list[str], **overrides) -> str:
            signing_key = overrides.pop("signing_key", private_key)
            key_id = overrides.pop("kid", "lx07-local-kid")
            now = int(time.time())
            claims = {"sub": "lx07-operator", "tenant_id": tenant, "type": "access", "role_codes": roles,
                      "iss": issuer, "aud": "siq-lx07-test", "iat": now, "exp": now + 3600}
            claims.update(overrides)
            return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": key_id})

        start_api()
        check("production_api_serves_after_migration", True)
        a = {"Authorization": "Bearer " + token("lx07-a", ["tenant_admin", "auditor"])}
        b = {"Authorization": "Bearer " + token("lx07-b", ["tenant_admin", "auditor"])}
        b_viewer = {"Authorization": "Bearer " + token("lx07-b", ["viewer"])}
        with httpx.Client(base_url=base_url, trust_env=False, timeout=10) as client:
            check("production_rejects_dev_header", client.get("/api/v1/overview", headers={
                "X-Dev-Tenant-Id": "lx07-a", "X-Dev-Roles": "tenant_admin"}).status_code == 401)
            check("production_rejects_missing_token", client.get("/api/v1/overview").status_code == 401)
            for label, bad in [
                ("wrong_issuer", token("lx07-a", ["tenant_admin"], iss="http://wrong.invalid/")),
                ("wrong_audience", token("lx07-a", ["tenant_admin"], aud="other-service")),
                ("expired", token("lx07-a", ["tenant_admin"], iat=int(time.time()) - 7200,
                                  exp=int(time.time()) - 3600)),
                ("wrong_signature", token("lx07-a", ["tenant_admin"], signing_key=next_private_key)),
                ("wrong_alg", jwt.encode({"sub": "x", "tenant_id": "lx07-a", "aud": "siq-lx07-test"},
                                          secrets.token_hex(32), algorithm="HS256")),
            ]:
                check("production_rejects_" + label,
                      client.get("/api/v1/overview", headers={"Authorization": "Bearer " + bad}).status_code == 401)
            created = client.post("/api/v1/environments", json={"name": "lx07-controlled-host"}, headers=a)
            check("signed_jwt_can_create_environment", created.status_code == 201)
            environment_id = created.json()["id"]
            check("tenant_derived_from_signed_claim", created.json()["tenant_id"] == "lx07-a")
            second_tenant = client.get("/api/v1/environments", headers=b)
            check("second_tenant_list_isolated", second_tenant.status_code == 200 and second_tenant.json() == [])
            check("cross_tenant_id_hidden_as_404", client.post(
                f"/api/v1/environments/{environment_id}/edge-enrollment", json={}, headers=b).status_code == 404)
            check("viewer_cannot_mutate", client.post("/api/v1/environments", json={"name": "denied"},
                                                        headers=b_viewer).status_code == 403)
            audit_a = client.get("/api/v1/audit-events", headers=a)
            audit_b = client.get("/api/v1/audit-events", headers=b)
            check("audit_tenant_isolated", audit_a.status_code == 200 and audit_b.status_code == 200
                  and any(row["action"] == "environment.create" for row in audit_a.json())
                  and not any(row["action"] == "environment.create" for row in audit_b.json()))

            # Exercise the real HTTP verifier and its JWKS cache across a key
            # change. A new kid must become usable without restarting the API.
            with jwks_lock:
                jwks_state["body"] = json.dumps({"keys": [public_jwk, next_public_jwk]}).encode()
            rotated = {"Authorization": "Bearer " + token(
                "lx07-a", ["tenant_admin", "auditor"],
                signing_key=next_private_key, kid="lx07-rotated-kid")}
            check("jwks_new_kid_refreshes_without_api_restart",
                  client.get("/api/v1/overview", headers=rotated).status_code == 200)

            # Trust in a removed old key lasts no longer than the configured
            # five-second cache TTL. This uses real elapsed time, not a clock
            # injection or a process restart.
            with jwks_lock:
                jwks_state["body"] = json.dumps({"keys": [next_public_jwk]}).encode()
            time.sleep(5.5)
            removed = client.get("/api/v1/overview", headers=a)
            check("jwks_removed_kid_rejected_after_real_ttl",
                  removed.status_code == 401 and removed.json().get("detail") == "unknown_kid")
            check("jwks_remaining_kid_still_accepted",
                  client.get("/api/v1/overview", headers=rotated).status_code == 200)

            with jwks_lock:
                jwks_state["unavailable"] = True
            time.sleep(5.5)
            unavailable = client.get("/api/v1/overview", headers=rotated)
            check("expired_jwks_cache_fails_closed_on_upstream_503",
                  unavailable.status_code == 401
                  and unavailable.json().get("detail") == "jwks_unavailable")
            with jwks_lock:
                jwks_state["body"] = json.dumps({"keys": [public_jwk, next_public_jwk]}).encode()
                jwks_state["unavailable"] = False
            check("jwks_recovery_restores_signed_access",
                  client.get("/api/v1/overview", headers=rotated).status_code == 200)

        stop_api()
        start_api()
        with httpx.Client(base_url=base_url, trust_env=False, timeout=10) as client:
            listed = client.get("/api/v1/environments", headers=a)
            check("postgres_state_survives_api_restart", listed.status_code == 200
                  and any(row["id"] == environment_id for row in listed.json()))
            check("tenant_isolation_survives_api_restart", client.get("/api/v1/environments", headers=b).json() == [])
    except Exception as exc:  # noqa: BLE001 -- report only the category; secrets remain in private memory
        failure = type(exc).__name__
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        if server_log is not None:
            server_log.close()
        resources["api_stopped"] = server is None or server.poll() is not None
        if jwks_server is not None:
            jwks_server.shutdown()
            jwks_server.server_close()
        if jwks_thread is not None:
            jwks_thread.join(timeout=2)
        resources["jwks_stopped"] = jwks_thread is None or not jwks_thread.is_alive()
        if container_id:
            removed = subprocess.run(["docker", "rm", "-f", container_id], capture_output=True,
                                     text=True, timeout=30, check=False)
            resources["container_removed"] = removed.returncode == 0
        else:
            resources["container_removed"] = True

    report = {
        "schema_version": "lx07-postgres-oidc-production-shape/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "evidence_level": "isolated_postgres_and_loopback_test_jwks_over_real_http",
        "image": IMAGE,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "passed": failure is None and all(row["passed"] for row in checks) and all(resources.values()),
        "error_type": failure,
        "checks": checks,
        "resources": resources,
        "limitations": ["loopback JWKS is a local RS256 issuer fixture, not a customer IdP",
                        "single PostgreSQL container, not production HA/backup/operations",
                        "no customer data, cloud gateway, or Windows/macOS validation"],
    }
    with private_file(out) as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks), "error_type": failure}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
