import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import anyio
import httpcore
import httpx
import pytest
from tests import test_qwen38_request_endpoint as fixtures

from services import hermes_client as hermes, qwen38_request_http as transport

endpoint = transport.endpoint
forward = endpoint.forward
owned = fixtures.owned
request_case = fixtures.request_case
prepared_case = fixtures.prepared_case
created_case = fixtures.created_case
supervision_case = fixtures.supervision_case
case = fixtures.case
relay_case = fixtures.relay_case
gateway_case = fixtures.gateway_case
endpoint_case = fixtures.endpoint_case


@pytest.fixture
def server(monkeypatch):
    state = SimpleNamespace(requests=[], redirect=False, stream_delay=False)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.respond()

        def do_GET(self):
            self.respond()

        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state.requests.append((self.command, self.path, dict(self.headers), body))
            if self.path == "/v1/runs":
                value = {"run_id": "run-owned"}
            else:
                value = {"object": "hermes.run", "run_id": "run-owned", "status": "completed", "quiesced": True}
            raw = json.dumps(value).encode()
            if self.path.endswith("/events"):
                raw = (b'data: {"event":"message.delta","delta":"synthetic"}\n\n'
                       b'data: {"event":"run.completed","output":"synthetic"}\n\n')
            self.send_response(302 if state.redirect else 200)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Location", "/unexpected")
            self.end_headers()
            self.wfile.write(raw)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(forward, "PORT", http.server_port)
    monkeypatch.setattr(forward, "BASE", "http://127.0.0.1:" + str(http.server_port))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        yield state
    finally:
        http.shutdown()
        http.server_close()
        thread.join(2)


@pytest.fixture
def route(endpoint_case, server, monkeypatch):
    c = endpoint_case
    monkeypatch.setattr(forward, "assert_supervised", lambda *args: os.getpid())
    ready = endpoint.connect(c.gateway, c.factory, **c.kwargs)
    return hermes.qwen_request_route(ready, c.factory, **c.kwargs)


def test_all_business_client_operations_use_owned_tcp(route, server):
    async def run():
        session = hermes.route_session_id(route, "siq_analysis", route.request_http.execution_binding.session_id)
        run_id = await hermes.create_run("synthetic", [], profile="siq_analysis", route=route, session_id=session)
        events = [event async for event in hermes.stream_run(run_id, profile="siq_analysis", route=route)]
        status = await hermes.get_run_status(run_id, profile="siq_analysis", route=route)
        stopped = await hermes.stop_run(run_id, profile="siq_analysis", route=route)
        assert events[0].text == "synthetic" and events[-1].type == "done"
        assert status.write_quiesced and stopped["quiesced"]

    anyio.run(run)
    assert [r[1] for r in server.requests] == ["/v1/runs", "/v1/runs/run-owned/events",
        "/v1/runs/run-owned", "/v1/runs/run-owned/stop"]
    assert all(r[2]["Authorization"] == route.authorization for r in server.requests)
    assert route.authorization not in repr(route) + repr(route.request_http)
    assert route.canary_run_id is None and route.runtime_backend == "qwen_request"


def test_create_conveys_trusted_request_output_directory(route, server):
    async def run():
        return await hermes.create_run("write an analysis", [], profile="siq_analysis", route=route,
            session_id=route.session_namespace, instructions="Retain the financial evidence requirements.")

    anyio.run(run)
    payload = json.loads(server.requests[0][3])
    plan = route.request_http.endpoint.gateway.supervised.created.launch.staged.plan
    assert payload['instructions'].startswith("Retain the financial evidence requirements.")
    assert plan.company_relative + '/analysis/runs/' + plan.run_id in payload['instructions']
    assert '不授予工具权限' in payload['instructions']
    assert route.authorization not in payload['instructions']


def test_forged_output_scope_never_reaches_hermes(route, server):
    forged = replace(route, pool_write_relative_path='analysis/runs/another-task')

    async def run():
        await hermes.create_run("write an analysis", [], profile="siq_analysis", route=forged,
            session_id=route.session_namespace)

    with pytest.raises(hermes.HermesRuntimeSelectionError, match='qwen_request_route_mismatch'):
        anyio.run(run)
    assert not server.requests


@pytest.mark.parametrize("mode", ["post", "get", "revoked"])
def test_confirmation_uses_owned_post_only(route, server, endpoint_case, mode):
    if mode == "revoked":
        endpoint_case.identity_valid = False

    async def run():
        async with hermes._http_client(route, "siq_analysis", timeout=3) as client:
            return await client.request("GET" if mode == "get" else "POST", route.base + "/run-owned/approval",
                headers={"Authorization": route.authorization}, json={"request_id": "one", "choice": "once"})

    if mode == "post":
        assert anyio.run(run).status_code == 200
        assert len(server.requests) == 1 and server.requests[0][:2] == ("POST", "/v1/runs/run-owned/approval")
    else:
        with pytest.raises(endpoint.RequestEndpointError):
            anyio.run(run)
        assert not server.requests


@pytest.mark.parametrize("operation", ["create", "stream", "status", "stop"])
def test_each_operation_rejects_revoked_authority(route, server, endpoint_case, operation):
    endpoint_case.identity_valid = False

    async def run():
        args = {"profile": "siq_analysis", "route": route}
        if operation == "create":
            await hermes.create_run("synthetic", [], session_id=route.session_namespace, **args)
        elif operation == "stream":
            async for _ in hermes.stream_run("run-owned", **args):
                pass
        elif operation == "status":
            await hermes.get_run_status("run-owned", **args)
        else:
            await hermes.stop_run("run-owned", **args)

    with pytest.raises(endpoint.RequestEndpointError, match="authority_unconfirmed"):
        anyio.run(run)
    assert not server.requests
    # Cleanup needs no execution authority, including after HTTP stop is denied.
    endpoint.stop(route.request_http.endpoint)
    assert endpoint_case.service_stopped


@pytest.mark.parametrize("field,value", [("base", "http://127.0.0.1:1/v1/runs"),
    ("model", "other"), ("authorization", "wrong"), ("runtime_backend", "legacy"),
    ("request_http", None), ("session_namespace", "other"), ("target", "host"),
    ("canary_run_id", "canary-aaaaaaaaaaaa")])
def test_route_tampering_never_sends_http(route, server, field, value):
    async def run():
        await hermes.get_run_status("run-owned", profile="siq_analysis", route=replace(route, **{field: value}))
    with pytest.raises(hermes.HermesRuntimeSelectionError, match="route_mismatch"):
        anyio.run(run)
    assert not server.requests


@pytest.mark.parametrize("run_id", ["../other", "run?secret=x", "run#fragment", "run/events", "run%2fother"])
def test_invalid_run_paths_rejected(route, server, run_id):
    async def run():
        await hermes.get_run_status(run_id, profile="siq_analysis", route=route)
    with pytest.raises((endpoint.RequestEndpointError, hermes.HermesRuntimeSelectionError)):
        anyio.run(run)
    assert not server.requests


def test_redirect_is_not_followed(route, server):
    server.redirect = True
    async def run():
        await hermes.get_run_status("run-owned", profile="siq_analysis", route=route)
    with pytest.raises(httpx.HTTPStatusError):
        anyio.run(run)
    assert len(server.requests) == 1


def test_foreign_listener_gets_no_http_or_credentials(monkeypatch):
    received = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    monkeypatch.setattr(forward, "PORT", listener.getsockname()[1])
    monkeypatch.setattr(forward, "BASE", "http://127.0.0.1:" + str(forward.PORT))
    def accept():
        with listener.accept()[0] as connection:
            connection.settimeout(5)
            received.append(connection.recv(4096))
    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    binding = transport.RequestHTTPBinding(SimpleNamespace(authorization="Bearer synthetic-secret"), None, None, None)
    # A separate process with the same UID does not own the accepted socket.
    unrelated = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    monkeypatch.setattr(transport.RequestHTTPBinding, "check", lambda self: unrelated.pid)
    async def run():
        async with transport.client(binding, timeout=3) as client:
            await client.post(forward.BASE + "/v1/runs", headers={"Authorization": binding.endpoint.authorization},
                              json={"input": "synthetic-body"})
    try:
        with pytest.raises(endpoint.RequestEndpointError, match="peer_unconfirmed"):
            anyio.run(run)
        thread.join(3)
        assert received == [b""]
    finally:
        listener.close()
        unrelated.communicate(timeout=3)


@pytest.mark.parametrize("fault", ["revoked_after_accept", "pid_changed", "cancelled"])
def test_auth_race_or_cancel_closes_socket_before_write(monkeypatch, fault):
    closed = []
    calls = []
    class Stream:
        def get_extra_info(self, key):
            return (forward.HOST, forward.PORT) if key == "server_addr" else ("127.0.0.1", 12345)
        async def aclose(self):
            closed.append(True)
    async def connect(*args, **kwargs):
        return Stream()
    def check(self):
        calls.append(True)
        if len(calls) == 2:
            if fault == "revoked_after_accept":
                raise endpoint.RequestEndpointError("revoked")
            return 124
        return 123
    monkeypatch.setattr(transport.RequestHTTPBinding, "check", check)
    binding = transport.RequestHTTPBinding(None, None, None, None)
    backend = transport._OwnedBackend(binding)
    monkeypatch.setattr(backend.backend, "connect_tcp", connect)
    monkeypatch.setattr(forward, "owns_connection", lambda *args: fault != "cancelled")
    async def run():
        if fault == "cancelled":
            with anyio.move_on_after(.05) as scope:
                await backend.connect_tcp(forward.HOST, forward.PORT)
            assert scope.cancel_called
        else:
            with pytest.raises(endpoint.RequestEndpointError):
                await backend.connect_tcp(forward.HOST, forward.PORT)
    anyio.run(run)
    assert closed == [True]


def test_network_errors_preserve_timeout_category_without_raw_details():
    with pytest.raises(httpx.TimeoutException, match="^qwen_request_http_timeout$"):
        with transport._network_errors():
            raise httpcore.ReadTimeout("synthetic-secret")


@pytest.mark.parametrize("fault", ["session", "profile"])
def test_create_rejects_cross_session_or_profile(route, server, fault):
    async def run():
        await hermes.create_run("synthetic", [], route=route,
            profile="siq_assistant" if fault == "profile" else "siq_analysis",
            session_id="other" if fault == "session" else route.session_namespace)
    with pytest.raises(hermes.HermesRuntimeSelectionError):
        anyio.run(run)
    assert not server.requests


@pytest.mark.parametrize("fault", ["cancel", "timeout", "truncated"])
def test_real_stream_failure_closes_accepted_socket(monkeypatch, fault):
    async def run():
        closed = asyncio.Event()
        received = []
        async def serve(reader, writer):
            try:
                received.append(await reader.readuntil(b"\r\n\r\n"))
                writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
                chunk = b'data: {"event":"message.delta","delta":"synthetic"}\n\n'
                writer.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                await writer.drain()
                if fault != "truncated":
                    assert await reader.read() == b""
            finally:
                writer.close()
                await writer.wait_closed()
                closed.set()
        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        monkeypatch.setattr(forward, "PORT", server.sockets[0].getsockname()[1])
        monkeypatch.setattr(forward, "BASE", "http://127.0.0.1:" + str(forward.PORT))
        monkeypatch.setattr(transport.RequestHTTPBinding, "check", lambda self: os.getpid())
        binding = transport.RequestHTTPBinding(SimpleNamespace(authorization="Bearer synthetic"), None, None, None)
        async def consume():
            timeout = httpx.Timeout(2, read=.05 if fault == "timeout" else 2)
            async with transport.client(binding, timeout=timeout) as client:
                async with client.stream("GET", forward.BASE + "/v1/runs/test/events",
                        headers={"Authorization": binding.endpoint.authorization}) as response:
                    chunks = response.aiter_bytes()
                    assert b"synthetic" in await anext(chunks)
                    await anext(chunks)
        try:
            if fault == "cancel":
                with anyio.move_on_after(.1) as scope:
                    await consume()
                assert scope.cancel_called
            else:
                with pytest.raises(httpx.TimeoutException if fault == "timeout" else httpx.TransportError):
                    await consume()
            await asyncio.wait_for(closed.wait(), 3)
            assert len(received) == 1
        finally:
            server.close()
            await server.wait_closed()
    anyio.run(run)
