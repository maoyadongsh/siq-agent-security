"""Gateway entry ordering and refusal; gateway execution is a separate live probe."""

import importlib.util
import json
import os
import sys
import types
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def entry(monkeypatch):
    name = "native_gateway_test_" + uuid.uuid4().hex
    directory = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location(name, directory / "native_gateway.py",
                                                 submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    for key in os.environ:
        if key.startswith("SIQ_AGENT_SECURITY_"):
            monkeypatch.delenv(key)
    monkeypatch.setattr(sys, "argv", ["hermes-gateway", "hri-" + "a" * 32, "request:namespace", "/tmp/private/channel"])
    calls = []

    class Bootstrap:
        def __init__(self, *args):
            calls.append(("initialize", args))

        def ready(self):
            calls.append("ready")
            return {"runtime_state": "unverified"}

        def configure(self, *, timeout):
            calls.append(("configure", timeout))

        def close(self):
            calls.append("close")

    gateway = types.ModuleType("gateway.run")

    def main():
        calls.append(("gateway", os.getpid(), list(sys.argv)))

    gateway.main = main
    monkeypatch.setattr(module, "ImageBootstrap", Bootstrap)
    monkeypatch.setitem(sys.modules, "gateway", types.ModuleType("gateway"))
    monkeypatch.setitem(sys.modules, "gateway.run", gateway)
    yield module, calls, gateway
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            del sys.modules[key]


def test_gateway_enters_same_process_after_configuration(entry, capsys):
    module, calls, _ = entry
    argv = tuple(sys.argv[1:])
    assert module.main() == 0
    assert calls == [("initialize", argv), "ready", ("configure", 60),
                     ("gateway", os.getpid(), ["gateway/run.py"]), "close"]
    out = capsys.readouterr()
    assert out.err == ""
    assert json.loads(out.out.removeprefix(module.MARKER)) == {"runtime_state": "unverified"}


@pytest.mark.parametrize("key", ["SIQ_AGENT_SECURITY_TOKEN_PATH", "SIQ_AGENT_SECURITY_MODE",
                                  "SIQ_AGENT_SECURITY_ENDPOINT", "SIQ_AGENT_SECURITY_UNKNOWN"])
def test_old_plugin_configuration_never_enters_gateway(entry, monkeypatch, capsys, key):
    module, calls, _ = entry
    monkeypatch.setenv(key, "secret-must-not-appear")
    assert module.main() == 1
    assert calls == []
    out = capsys.readouterr()
    assert out.out == "" and out.err == "native_gateway_unavailable\n"


@pytest.mark.parametrize("arguments", [[], ["hri-" + "a" * 32], ["a", "b", "c", "--config=arbitrary"]])
def test_missing_or_extra_parameters_refused(entry, monkeypatch, arguments):
    module, calls, _ = entry
    monkeypatch.setattr(sys, "argv", ["hermes-gateway", *arguments])
    assert module.main() == 1
    assert calls == []


@pytest.mark.parametrize("stage", ["ready", "configure"])
def test_initialization_failure_cannot_start_gateway(entry, monkeypatch, capsys, stage):
    module, calls, _ = entry

    def fail(*_args, **_kwargs):
        raise RuntimeError("secret-must-not-appear")

    monkeypatch.setattr(module.ImageBootstrap, stage, fail)
    assert module.main() == 1
    assert calls[-1] == "close"
    assert not any(isinstance(c, tuple) and c[0] == "gateway" for c in calls)
    out = capsys.readouterr()
    assert "secret-must-not-appear" not in out.out + out.err


@pytest.mark.parametrize("failure,expected", [
    (RuntimeError("secret"), 1), (KeyboardInterrupt(), 1),
    (SystemExit("secret"), 1), (SystemExit(75), 75), (SystemExit(None), 0),
])
def test_gateway_exit_closes_runtime_and_never_prints_exception(entry, capsys, failure, expected):
    module, calls, gateway = entry

    def fail():
        raise failure

    gateway.main = fail
    assert module.main() == expected
    assert calls[-1] == "close"
    out = capsys.readouterr()
    assert "secret" not in out.out + out.err
