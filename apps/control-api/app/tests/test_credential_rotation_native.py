"""Real Go CLI -> loopback bridge -> actual API, synthetic SQLite only.

This is not TLS, production IAM, PostgreSQL, or installed-service acceptance.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, EdgeCredentialRotation, OutboxEvent
from app.tests.edge_helpers import register_edge


@pytest.fixture(scope='module')
def rotation_binary(tmp_path_factory):
    assert shutil.which('go'), 'Go toolchain required for native rotation integration'
    root = Path(__file__).resolve().parents[4]
    binary = tmp_path_factory.mktemp('rotation-native-build') / 'edge-agent'
    build = subprocess.run(['go', 'build', '-o', str(binary), '.'],
                           cwd=root / 'edge/agent', capture_output=True, timeout=120)
    assert build.returncode == 0, 'native rotation build failed'
    return binary


def event_counts():
    with session_scope() as session:
        return tuple(session.scalar(select(func.count()).select_from(model))
                     for model in (EdgeCredentialRotation, AuditEvent, OutboxEvent))


@pytest.mark.parametrize('lose_response', [False, True])
def test_native_rotation_and_recovery(client, tenant_a, rotation_binary, tmp_path, lose_response):
    environment = client.post('/api/v1/environments', headers=tenant_a,
                              json={'name': 'native-rotation-' + uuid.uuid4().hex})
    assert environment.status_code == 201
    environment_id = environment.json()['id']
    identity = 'native-rotation-' + uuid.uuid4().hex
    old_headers, key = register_edge(client, tenant_a, environment_id, identity)
    old_secret = old_headers['Authorization'].removeprefix('Bearer ')
    requests = []
    statuses = []
    bridge_errors = []

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never log authentication, paths or response bodies.

        def do_POST(self):
            try:
                if self.path != '/edge/v1/credential-rotation':
                    bridge_errors.append('unexpected path')
                    self.send_error(404)
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    bridge_errors.append('invalid length')
                    self.send_error(400)
                    return
                raw = self.rfile.read(length)
                requests.append(raw)
                response = client.post(self.path, content=raw, headers={
                    name: self.headers[name] for name in
                    ('Authorization', 'X-Edge-Identity', 'X-Edge-Version', 'Content-Type')
                    if name in self.headers
                })
                statuses.append(response.status_code)
                # Backend really committed; discard its response at the bridge.
                if lose_response and len(requests) == 1 and response.status_code == 200:
                    self.close_connection = True
                    return
                self.send_response(response.status_code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)
            except Exception:
                bridge_errors.append('bridge failure')
                self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Bridge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tmp_path.chmod(0o700)
    state_dir = tmp_path / 'private'
    state_dir.mkdir(mode=0o700)
    state_path = state_dir / 'state.json'
    state = {
        'control_plane_url': f'http://127.0.0.1:{server.server_port}',
        'device_identity': identity, 'environment_id': environment_id, 'secret': old_secret,
        'public_key_pem': key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
        'signer_seed': base64.b64encode(key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption())).decode(),
    }
    with state_path.open('x') as stream:
        state_path.chmod(0o600)
        json.dump(state, stream)
    env = {**os.environ, 'SIQ_EDGE_STATE_DIR': str(state_dir)}
    command = [str(rotation_binary), 'rotate-credential', '--confirm-device', identity]
    before = event_counts()
    try:
        first = subprocess.run(command, env=env, capture_output=True, timeout=15)
        assert not bridge_errors
        assert statuses == [200]
        assert event_counts() == tuple(value + 1 for value in before)
        after_commit = event_counts()
        journal_path = state_dir / 'credential-rotation-pending.json'
        if lose_response:
            assert first.returncode != 0
            assert json.loads(state_path.read_text())['secret'] == old_secret
            pending = json.loads(journal_path.read_text())
            assert json.loads(requests[0]) == pending['request']
            second = subprocess.run(command + ['--resume'], env=env,
                                    capture_output=True, timeout=15)
            assert second.returncode == 0, 'native recovery failed'
            assert statuses == [200, 200]
            assert requests[0] == requests[1]
            assert event_counts() == after_commit
        else:
            assert first.returncode == 0, 'native rotation failed'
        activated = json.loads(state_path.read_text())
        assert activated['secret'] != old_secret
        assert {k: v for k, v in activated.items() if k != 'secret'} == {
            k: v for k, v in state.items() if k != 'secret'}
        assert not journal_path.exists()
        assert state_path.stat().st_mode & 0o777 == 0o600
        new_headers = {**old_headers, 'Authorization': 'Bearer ' + activated['secret']}
        assert client.post('/edge/v1/heartbeat', headers=old_headers,
                           json={'version': 'native-test'}).status_code == 401
        assert client.post('/edge/v1/heartbeat', headers=new_headers,
                           json={'version': 'native-test'}).status_code == 200
        body = json.loads(requests[0])
        assert body['new_secret_hash'] == hashlib.sha256(activated['secret'].encode()).hexdigest()
        output = first.stdout + first.stderr
        if lose_response:
            output += second.stdout + second.stderr
        for secret in (old_secret, activated['secret'], state['signer_seed']):
            assert secret.encode() not in output
        assert not bridge_errors
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
