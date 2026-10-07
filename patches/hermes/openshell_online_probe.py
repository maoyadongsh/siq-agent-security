"""Join real OpenShell, native Hermes tools and actual Go HTTP Authority."""

import concurrent.futures
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from build_native_overlay import IMAGE, build
from openshell_image_probe import ADAPTER, PYTHON, ROOT, digest, runtime_options

RUNTIME = "/opt/siq/native-business"
_owned = None


def wait_json(path, process, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
        if process.poll() is not None:
            raise RuntimeError("owned_authority_exited_before_ready")
        time.sleep(.05)
    raise RuntimeError("owned_authority_ready_timeout")


class OwnedAuthority:
    def __init__(self, output):
        self.process, self.verifier, self.log = None, None, None
        self.scratch = tempfile.TemporaryDirectory(prefix="siq-native-authority-")
        self.output = output
        self.root = Path(self.scratch.name) / "authority"
        self.root.mkdir(mode=0o700)
        spec = importlib.util.spec_from_file_location("siq_owned_online", ADAPTER / "host_online.py",
                                                    submodule_search_locations=[str(ADAPTER)])
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)
        self.config = self.root / "connection.json"
        self.write("connection.json", {"schema_version": "native-host-connection/v1",
            "credential": "nhp-" + secrets.token_hex(32), "verification_socket": str(Path(self.scratch.name) / "verify.sock")})
        self.verifier = self.module.Verifier(self.config).start()

    def write(self, name, value):
        fd = os.open(self.root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(value, file)

    def start(self, prepared):
        self.write("input.json", {"artifact": prepared["artifact"], "source": prepared["skill_source"],
            "runtime_root": RUNTIME + "/skills", "session": "owned-online:" + digest(b"owned-session")})
        self.log = (self.output / "authority-go-test.log").open("wb")
        env = os.environ.copy()
        env["SIQ_NATIVE_OPENSHELL_TEST_DIR"] = str(self.root)
        self.process = subprocess.Popen(["go", "test", "./internal/server", "-run", "^TestOwnedOpenShellNativeOnlineIntegration$",
            "-count=1", "-timeout=180s", "-v"], cwd=ROOT / "apps/agentshield", env=env,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        self.ready = wait_json(self.root / "ready.json", self.process)
        prepared["argv"].extend([self.ready["subject"]["agent_id"], "owned-online", "owned-session"])
        prepared["skill_roots"] = [{"source": m["host_root"], "target": m["runtime_root"]} for m in self.ready["installs"]]

    def close(self):
        if self.process is not None and self.process.poll() is None:
            # The test owns its temporary state and exits after this handshake.
            (self.root / "finish").touch(exist_ok=True)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
        if self.verifier is not None:
            self.verifier.close()
        authority = self.root / "authority-result.json"
        if authority.exists():
            shutil.copyfile(authority, self.output / "authority-result.json")
        if self.log is not None:
            self.log.close()
        self.scratch.cleanup()


def close():
    global _owned
    if _owned is not None:
        _owned.close()
        _owned = None


def prepare(output, command):
    global _owned
    context = output / "image-context"
    context.mkdir(mode=0o700)
    overlay = context / "overlay"
    manifest = build(ROOT / "var/optimization-20261007/opt08-native-source", overlay)
    # COPY preserves source modes, including newly overlaid ancestor dirs.
    # Do not overwrite protected image directories with a host umask's 0775.
    for path in (overlay, *overlay.rglob("*")):
        path.chmod(0o555 if path.is_dir() else 0o444)
    bootstrap = Path(__file__).with_name("openshell_online_bootstrap.py")
    shutil.copyfile(bootstrap, context / "bootstrap.py")
    skills = context / "skills"
    for name in ("reader", "writer"):
        path = skills / name
        path.mkdir(mode=0o755, parents=True)
        (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Work on an owned synthetic report.\nallowed-tools: read_file write_file skill_view\n---\nUse only the permissions approved for this {name} skill.\n")
    (context / "Dockerfile").write_text(f"FROM {IMAGE}\nUSER root\nCOPY --chown=0:0 overlay/ /opt/hermes-agent/\n"
        f"COPY --chown=0:0 bootstrap.py {RUNTIME}/bootstrap.py\nCOPY --chown=0:0 skills/ {RUNTIME}/skills/\n"
        f"RUN find {RUNTIME} /opt/hermes-agent/siq_native_runtime -type d -exec chmod 0555 {{}} + && "
        f"find {RUNTIME} /opt/hermes-agent/siq_native_runtime -type f -exec chmod 0444 {{}} + && "
        "chmod 0444 " + " ".join("/opt/hermes-agent/" + p for p in manifest["source_sha256"]) + "\nUSER sandbox\n")
    iid = output / "image-id"
    command(["/usr/bin/docker", "build", "--network=none", "--pull=false", "--iidfile", str(iid), str(context)], timeout=60)
    image = iid.read_text().strip()
    assert image.startswith("sha256:") and len(image) == 71
    # Fixed interpreter baseline was independently measured by the previous
    # owned image-profile probe; verify that evidence names this exact base.
    baseline = json.loads((ROOT / "var/optimization-20261007/opt08-openshell-image-profile-02/result.json").read_text())
    assert baseline["base_image_id"] == IMAGE and baseline["inspection_complete"]
    extractor = output / "extractor-id"
    try:
        executable = command(["/usr/bin/docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--cidfile", str(extractor),
            "--entrypoint", PYTHON, IMAGE, "-I", "-B", "-c",
            "import hashlib; print(hashlib.sha256(open('/proc/self/exe','rb').read()).hexdigest())"]).stdout.decode().strip()
    finally:
        if extractor.exists():
            cid = extractor.read_text().strip()
            if len(cid) == 64 and all(c in "0123456789abcdef" for c in cid):
                command(["/usr/bin/docker", "rm", "-f", cid], required=False)
    files = {"/opt/hermes-agent/" + p: h for p, h in manifest["overlay_sha256"].items()}
    files[RUNTIME + "/bootstrap.py"] = digest(bootstrap.read_bytes())
    for path in skills.rglob("SKILL.md"):
        files[RUNTIME + "/skills/" + path.relative_to(skills).as_posix()] = digest(path.read_bytes())
    artifact = digest(json.dumps({"image": image, "files": files, "executable": executable}, sort_keys=True).encode())
    prepared = {"image": image, "files": files, "artifact": artifact, "executable": executable,
                "argv": [PYTHON, "-I", "-B", RUNTIME + "/bootstrap.py"], "skill_source": str(skills)}
    _owned = OwnedAuthority(output)
    _owned.start(prepared)
    return prepared


def verify(prepared, *, peer, cid, namespace, sandbox, init_pid, init_groups, row, command, exec_log):
    module, channel, options = runtime_options(prepared, peer=peer, cid=cid, namespace=namespace,
        sandbox=sandbox, init_pid=init_pid, init_groups=init_groups, command=command)
    ready = _owned.ready
    credential = Path(ready["credential_path"]).read_text()
    trace = []

    def diagnostics(frame, event, arg):
        if event == "exception" and frame.f_code.co_filename == str(ADAPTER / "host_runtime.py"):
            trace.append({"function": frame.f_code.co_name, "line": frame.f_lineno, "exception_type": arg[0].__name__})
        return diagnostics

    previous = sys.gettrace()
    try:
        sys.settrace(diagnostics)
        guard = module.RuntimeGuard(**options)
    finally:
        sys.settrace(previous)
        if trace:
            (_owned.output / "guard-diagnostics.json").write_text(json.dumps(trace[-32:], indent=2))
    with guard:
        _owned.verifier.register(ready["subject"], guard, ready["installs"], lifetime=150)
        publisher = _owned.module.Publisher(_owned.config, ready["endpoint"], ready["subject"], guard)
        relay = _owned.module.DecisionRelay(publisher, credential)
        controls, events = {}, []

        def dispatch(event):
            # The test operator changes only this owned Authority fixture.
            # Actual events/decisions still traverse the unmodified relay.
            target = {"context-after-revoke": "context", "grant-after-revoke": "writer",
                      "baseline-after-revoke": "baseline"}.get(event.get("tool_call_id"))
            if event.get("kind") == "call_prepare" and target and target not in controls:
                (_owned.root / ("revoke-" + target)).touch(exist_ok=False)
                ack = wait_json(_owned.root / ("revoked-" + target + ".json"), _owned.process, timeout=3)
                assert ack == {"revoked": True}, "owned_revocation_failed"
                controls[target] = True
            answer = relay.dispatch(event)
            request = event.get("request", {})
            events.append({"kind": event.get("kind", "decision"),
                           "call": event.get("tool_call_id", request.get("tool_call_id")),
                           "accepted": answer.get("accepted"), "action": answer.get("action")})
            return answer

        with guard.namespace_channel_directory(row["channel_directory"]) as fd:
            with channel.NamespaceHostChannel(fd, guard.peer, timeout=5) as host, concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                deadline = time.monotonic() + 80
                while True:
                    rows = [json.loads(line) for line in exec_log.read_text(errors="replace").splitlines()
                            if line.startswith('{"native_online_verified":')]
                    if rows:
                        result = rows[-1]
                        break
                    assert time.monotonic() < deadline, "owned_online_result_timeout"
                    pending = pool.submit(host.serve_once, dispatch)
                    try:
                        pending.result(timeout=12)
                    except channel.ChannelError:
                        # A final idle accept timeout is expected after the
                        # client publishes its terminal result to stdout.
                        rows = [json.loads(line) for line in exec_log.read_text(errors="replace").splitlines()
                                if line.startswith('{"native_online_verified":')]
                        if not rows:
                            raise
                        result = rows[-1]
                        break
            (_owned.output / "runtime-result.json").write_text(json.dumps(result, indent=2) + "\n")
            assert result["native_online_verified"] and all(result["checks"].values()), "owned_native_online_check_failed"
            process_root = Path(f"/proc/{peer}/root")
            effect = process_root / "sandbox/native-business/writer-allowed.txt"
            assert digest(effect.read_bytes()) == result["output_sha256"]
            for name in ("reader-denied.txt", "switch-denied.txt", "replay-denied.txt", "ended-denied.txt",
                         "concurrent-reader.txt", "context-revoked-denied.txt", "grant-revoked-denied.txt"):
                assert not (effect.parent / name).exists()
            for name, content in {"concurrent-writer.txt": "concurrent-writer",
                                  "context-before.txt": "before-context-revocation",
                                  "grant-before.txt": "before-grant-revocation"}.items():
                assert (effect.parent / name).read_text() == content
            assert not (process_root / "sandbox/outside-denied.txt").exists()
            result["independent_host_effect_check"] = True
            assert controls == {"context": True, "writer": True, "baseline": True}
            assert not any(event["call"] == "after-task-end" for event in events)
            result["host_observed_events"] = events
            result["revocations"] = controls
        (_owned.root / "finish").touch()
        _owned.process.wait(timeout=10)
        assert _owned.process.returncode == 0, "owned_authority_verification_failed"
        authority = json.loads((_owned.root / "authority-result.json").read_text())
        (_owned.output / "authority-result.json").write_text(json.dumps(authority, indent=2) + "\n")
        result["authority"] = {k: authority[k] for k in ("signed_chain_verified", "receipt_count")}
        result["artifact_sha256"] = prepared["artifact"]
        result["image_id"] = prepared["image"]
        result["files"] = prepared["files"]
        return result
