import io
import json
import sys

from test_adapter import load


def test_windows_waits_for_installation_validation_and_still_bounds_timeout(server, monkeypatch):
    srv, token = server
    monkeypatch.setattr(sys, "platform", "win32")
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    seen = []

    class Response(io.BytesIO):
        status = 200

    class InstallationValidation:
        def open(self, request, timeout):
            seen.append(timeout)
            # Model a response after the server's 5s validation plus HTTP overhead.
            if timeout <= 5:
                raise TimeoutError("installation response not yet received")
            return Response(json.dumps({"action": "allow", "receipt_id": "rcp-fixture"}).encode())

    monkeypatch.setattr(mod.urllib.request, "build_opener", lambda *a: InstallationValidation())
    assert mod._post("/v1/decide", {})["action"] == "allow"
    assert seen == [20]
    assert mod._post("/v1/decide", {}, timeout_s=0.25) is None
    assert seen[-1] == 0.25
    mod._CFG["timeout_s"] = 0.1
    assert mod._pre_tool_call("read_file", {"path": "C:/fixture/a"}, session_id="s", tool_call_id="t") is not None
    assert seen[-1] == 0.1


def test_non_windows_default_is_unchanged(server, monkeypatch):
    srv, token = server
    monkeypatch.setattr(sys, "platform", "linux")
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._DEFAULTS["timeout_s"] == 5
