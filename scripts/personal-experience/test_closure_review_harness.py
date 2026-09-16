"""Behavioral regressions for GLM acceptance false positives and side effects."""
import importlib.util
import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = load("driver_review", "installed_user_service_driver.py")
b02 = load("b02_review", "closure-b02-installed-journey-runner.py")
exports = load("export_review", "closure-b04-export-runner.py")


def test_cli_credentials_never_enter_records_or_logs(tmp_path):
    drv = driver.InstalledUserServiceDriver(str(tmp_path / "state"), 12345, str(tmp_path / "logs"))
    secret = "Bearer PRIVATE_CANARY 1234-5678-abcd-ef01"
    rec = drv.run_cli("/bin/echo", [secret], redact=False)
    assert secret in rec["stdout"]  # callers still get the CLI response in memory
    # command is an allowlisted category, even if run_cli gets unexpected args.
    assert secret not in json.dumps(drv.records)
    for path in (tmp_path / "logs").iterdir():
        assert secret not in path.read_text()
        assert "1234-5678-abcd-ef01" not in path.read_text()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_cli_failure_does_not_expose_arguments_or_stderr(tmp_path):
    drv = driver.InstalledUserServiceDriver(str(tmp_path), 12345)
    with pytest.raises(driver.InstalledServiceError) as caught:
        drv.run_cli("/bin/sh", ["-c", "echo PRIVATE_CANARY >&2; exit 7"])
    assert "PRIVATE_CANARY" not in str(caught.value)
    assert "PRIVATE_CANARY" not in json.dumps(drv.records)


def test_log_collision_does_not_overwrite_unknown_file(tmp_path):
    target = tmp_path / "unknown"
    target.write_text("keep")
    link = tmp_path / "logs"
    link.symlink_to(tmp_path, target_is_directory=True)
    drv = driver.InstalledUserServiceDriver(str(tmp_path), 12345, str(link))
    with pytest.raises(driver.InstalledServiceError):
        drv.run_cli("/bin/echo", ["fixture"])
    assert target.read_text() == "keep"


@pytest.mark.parametrize("home,expected", [("/daily/home", False), ("/fixture/home", True)])
def test_manager_home_check_is_read_only(monkeypatch, home, expected):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command == ["systemctl", "--user", "show-environment"]
        return subprocess.CompletedProcess(command, 0, f"HOME={home}\nSECRET=must-not-log\n", "")

    monkeypatch.setattr(b02.subprocess, "run", run)
    guard = b02.ManagerHomeOverride("/fixture/home", lambda _msg: pytest.fail("environment logging"))
    if expected:
        with guard:
            pass
    else:
        with pytest.raises(AssertionError, match="B02 blocked"), guard:
            pytest.fail("unsafe prerequisite accepted")
    assert len(calls) == 1


def test_not_exercised_is_not_pass():
    runner = object.__new__(b02.B01.Runner)
    runner.checks, runner.failures = [], []
    note = runner.note("expired", "not actually exercised")
    assert note["ok"] is None
    assert note["status"] == "not_exercised"


def test_replay_uses_real_consumed_code():
    calls = []
    class Fixture:
        _pair_code = "abcd-abcd-abcd-abcd"
        def pairing_code(self, binary):
            return self._pair_code
        def api(self, method, path, **kwargs):
            calls.append(kwargs["payload"]["code"])
            if len(calls) == 2 and calls[-1] == self._pair_code:
                return 200, {"session": "fixture-session"}
            return 401, {}
    runner = object.__new__(b02.B01.Runner)
    runner.driver, runner.checks, runner.failures = Fixture(), [], []
    runner.args = SimpleNamespace(skip_pair_expiry=True)
    runner.lc02_pairing("fixture")
    assert calls == ["dead-beef-dead-beef", Fixture._pair_code, Fixture._pair_code]
    assert not runner.failures


def test_export_scope_check_detects_foreign_receipt():
    def api(path):
        if path == "/v1/task-activities":
            return {"items": [{"activity_id": "a"}, {"activity_id": "b"}],
                    "snapshot": "snapshot", "next_offset": None}
        if "/export?" in path:
            return {"activity_id": "a", "snapshot": "snapshot",
                    "receipts": [{"seq": 9, "source_hash": "foreign"}]}
        return {"next_offset": None, "receipts": [{"seq": 0, "hash": "own"}]}
    def check(name, ok):
        assert ok, name
    with pytest.raises(AssertionError, match="_export_scope"):
        exports.check_exports(SimpleNamespace(api=api), check, "fixture", [])


def test_b02_missing_isolation_blocks_before_build_or_install(tmp_path):
    runner = object.__new__(b02.B02Runner)
    runner.run_dir, runner.out_dir = str(tmp_path / "run"), str(tmp_path)
    class Blocked:
        def __enter__(self):
            raise AssertionError("unsafe HOME")
        def __exit__(self, *_):
            return False
    runner.manager_home = lambda: Blocked()
    runner.prepare_test_trust = lambda: pytest.fail("build prerequisites reached")
    assert runner.run() is False
    report = json.loads((tmp_path / "blocked.json").read_text())
    assert report["status"] == "blocked"
    assert report["product_actions"] == 0
    assert report["manager_environment_modified"] is False


def test_failed_child_cannot_pass_by_report_and_does_not_leak(tmp_path, monkeypatch):
    runner = object.__new__(b02.B02Runner)
    runner.out_dir = str(tmp_path)
    runner.args = SimpleNamespace(openclaw_root="fixture", node="fixture")
    (tmp_path / "direct-process-raw-report.json").write_text('{"passed":true}')
    monkeypatch.setattr(b02.subprocess, "run", lambda *a, **kw:
        subprocess.CompletedProcess(a, 1, "PRIVATE_STDOUT", "PRIVATE_STDERR"))
    assert runner.run_direct_leg({"linux_arm64":"fixture"}) is None
    diagnostic = (tmp_path / "direct-process-diagnostic.json").read_text()
    assert "PRIVATE_" not in diagnostic
    assert json.loads(diagnostic)["exit"] == 1


def test_export_signature_requires_external_anchor_and_untampered_projection():
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    doc = {"public_key_base64": public, "activity_id": "synthetic-中文-🚲", "receipts": []}
    encoded = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    doc["signature"] = key.sign(encoded).hex()
    assert exports.verify_export(doc, public)
    other = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    assert not exports.verify_export(doc, base64.b64encode(other).decode())
    doc["activity_id"] = "forged"
    assert not exports.verify_export(doc, public)


@pytest.mark.parametrize("inherited", [False, True])
def test_b05_executes_selected_binary_instead_of_rebuilding_head(tmp_path, inherited):
    b05 = load("b05_selected_candidate", "closure-b05-service-down-side-effects.py")
    selected = tmp_path / "selected"
    selected.write_bytes(b"explicit-candidate-fixture")
    selected.chmod(0o700)
    destination = tmp_path / "execution-copy"
    selected_class = b05.Harness if inherited else b05.managed.Harness
    runner = object.__new__(selected_class)
    runner.args = SimpleNamespace(binary=selected)
    runner.binary = destination
    runner.command = lambda *a, **k: pytest.fail("unexpected compilation")
    runner.build()
    assert destination.read_bytes() == selected.read_bytes()
    assert destination.stat().st_mode & 0o100


def test_ambiguous_unit_ownership_is_never_selected(tmp_path):
    for suffix in ("one", "two"):
        (tmp_path / f"siq-agent-security-{suffix}.service").write_text("fixture")
    drv = driver.InstalledUserServiceDriver(str(tmp_path), 12345)
    with pytest.raises(driver.InstalledServiceError):
        drv.unit_name()


def test_unit_home_guard_never_sets_manager_environment(monkeypatch):
    calls = []
    def read(argv, **kwargs):
        calls.append(argv)
        return b"HOME=/daily/home\n"
    monkeypatch.setattr(b02.subprocess, "check_output", read)
    with b02.ManagerEnvironmentUnchanged():
        pass
    assert calls == [["systemctl", "--user", "show-environment"]] * 2


def test_unit_home_guard_detects_manager_mutation(monkeypatch):
    values = iter([b"HOME=/daily/home", b"HOME=/changed"])
    monkeypatch.setattr(b02.subprocess, "check_output", lambda *a, **k: next(values))
    with pytest.raises(AssertionError, match="environment changed"), b02.ManagerEnvironmentUnchanged():
        pass


def test_installed_journey_uses_status_and_rejects_inconsistent_summary():
    assert b02.journey_passed({"passed": True, "results": [{"status": "pass"}]})
    assert not b02.journey_passed({"passed": True, "results": [{"status": "fail"}]})
    assert not b02.journey_passed({"passed": True, "results": []})
