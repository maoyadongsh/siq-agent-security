import json
import sys
import time
from pathlib import Path

import pytest

from app.adapters.openshell.bounded_command import run_bounded
from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError


def test_exact_shared_byte_budget():
    source = "import os; os.write(1,b'a'*512); os.write(2,b'b'*512)"
    rc, out, err = run_bounded([sys.executable, "-c", source], limit=1024)
    assert (rc, len(out), len(err)) == (0, 512, 512)


@pytest.mark.parametrize("source,timeout,code", [
    ("import os; os.write(1,b'a'*512); os.write(2,b'b'*513)", 3, "openshell_output_limit"),
    ("import os\nwhile True: os.write(1,b'x'*8192)", 3, "openshell_output_limit"),
    ("import time; time.sleep(0.6)", 0.05, "openshell_command_timeout"),
    ("import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(0.6)'])",
     3, "openshell_pipe_timeout"),
])
def test_bounded_failures(source, timeout, code):
    started = time.monotonic()
    with pytest.raises(AdapterError, match=f"^{code}$"):
        run_bounded([sys.executable, "-c", source], timeout=timeout, limit=1024)
    assert time.monotonic() - started < 2


def test_environment_and_error_privacy(monkeypatch):
    for key in ("SIQ_AS_SECRET", "OPENSHELL_SECRET", "BASH_ENV"):
        monkeypatch.setenv(key, "CANARY_DO_NOT_DISCLOSE")
    source = "import os; print([k for k in os.environ if k.startswith(('SIQ_AS_', 'OPENSHELL_')) or k=='BASH_ENV'])"
    rc, out, err = run_bounded([sys.executable, "-c", source])
    assert (rc, out.strip(), err) == (0, "[]", "")
    result = run_bounded([sys.executable, "-c", "import sys; sys.stderr.write('CANARY_DO_NOT_DISCLOSE'); sys.exit(2)"])
    assert result == (2, "", "openshell_command_failed")
    backend = OpenShellCliBackend(runner=lambda args: (1, "", "CANARY_DO_NOT_DISCLOSE"))
    with pytest.raises(AdapterError, match="^openshell_command_failed$"):
        backend._cli("policy", "get", "PRIVATE_TARGET")
    with pytest.raises(AdapterError) as failure:
        backend._parse_policy_yaml("[CANARY_DO_NOT_DISCLOSE")
    assert "CANARY" not in str(failure.value)


def test_explicit_environment_is_filtered_and_not_reloaded(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/fixture/later")
    supplied = {"XDG_CONFIG_HOME": "/fixture/frozen", "BASH_ENV": "private", "PRIVATE_TOKEN": "private"}
    source = ("import os; print(os.getenv('XDG_CONFIG_HOME')); "
              "print('BASH_ENV' in os.environ or 'PRIVATE_TOKEN' in os.environ)")
    rc, out, err = run_bounded([sys.executable, "-c", source], environment=supplied)
    assert rc == 0 and err == "" and out.splitlines() == ["/fixture/frozen", "False"]
    assert supplied["BASH_ENV"] == "private"  # caller snapshot not mutated


@pytest.mark.parametrize("case", json.loads(
    (Path(__file__).resolve().parents[4] / "testdata/openshell-command-budget.v1.json").read_text()
), ids=lambda case: case["name"])
def test_shared_output_vectors(case):
    source = "import os,sys; os.write(1,sys.argv[1].encode()); os.write(2,sys.argv[2].encode())"
    argv = [sys.executable, "-c", source, case["stdout"], case["stderr"]]
    if case["allowed"]:
        assert run_bounded(argv, limit=case["limit"]) == (0, case["stdout"], case["stderr"])
    else:
        with pytest.raises(AdapterError, match="^openshell_output_limit$"):
            run_bounded(argv, limit=case["limit"])
