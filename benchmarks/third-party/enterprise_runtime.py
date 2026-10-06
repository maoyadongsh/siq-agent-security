"""Owned receiver evidence for actual sandbox network policy transitions."""
import json
import os
import secrets
import time

import yaml
from openshell_fixture import OpenShellFixture

IMAGE = 'sha256:4f8d1afed6d58037c680221ca6dd9fb4737b7ecfa7d4809ca809fdc0c7d9b786'
ASSERTIONS = ['enterprise_effect_before', 'enterprise_effect_blocked', 'enterprise_effect_restored', 'enterprise_same_receiver']
SERVER = '''from http.server import BaseHTTPRequestHandler,HTTPServer
import json
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  print(json.dumps({'path':self.path}),flush=True)
  body=self.path.encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
print(json.dumps({'ready':True}),flush=True)
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
'''


def evaluate(o):
    rows = [o['effect_' + n] for n in ('before', 'applied', 'rolled_back')]
    values = []
    for r, permitted in zip(rows, (True, False, True), strict=True):
        seen = [json.loads(line) for line in r['receiver_stdout'].splitlines()]
        control = sum(x.get('path') == r['control_path'] for x in seen)
        delivered = sum(x.get('path') == r['business_path'] for x in seen)
        health = r['control_exit_code'] == 0 and control == 1
        values.append(health and ((r['exit_code'] == 0 and delivered == 1 and r['stdout'].strip() == r['business_path']) if permitted else (r['exit_code'] != 0 and delivered == 0)))
    return dict(zip(ASSERTIONS, [*values, len({r['receiver_id'] for r in rows}) == 1 and len({r['target'] for r in rows}) == 1 and len({r['business_path'] for r in rows}) == 3], strict=True))


class EnterpriseRuntime(OpenShellFixture):
    def __init__(self, campaign, root, candidate):
        super().__init__(campaign, root, candidate)
        self.receiver_id = None

    def create_sandbox(self):
        result = super().create_sandbox()
        if result.returncode:
            return result
        server = self.root / 'receiver.py'
        server.write_text(SERVER)
        launched = self.command(['docker', 'run', '-d', '--network', self.name, '--network-alias', 'effect-sink', '--label', 'siq.evaluation=' + self.name,
                                 '--user', f'{os.getuid()}:{os.getgid()}',
                                 '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only', '--pids-limit', '32', '--memory', '64m',
                                 '--mount', f'type=bind,src={server},dst=/receiver.py,readonly', IMAGE, 'python', '-B', '/receiver.py'])
        if launched.returncode:
            raise RuntimeError('receiver_launch_failed')
        self.receiver_id = launched.stdout.decode().strip()
        for _ in range(30):
            response = self.command(['docker', 'logs', self.receiver_id])
            if '"ready": true' in response.stdout.decode():
                break
            time.sleep(.1)
        else:
            raise RuntimeError('receiver_readiness_failed')
        policy = yaml.safe_load((self.root / 'baseline.yaml').read_text())
        policy['network_policies'] = {'evaluation_baseline': {'name': 'evaluation-baseline', 'endpoints': [{'host': 'effect-sink', 'port': 8080}], 'binaries': [{'path': '/usr/bin/curl'}]}}
        path = self.root / 'baseline-allow-receiver.yaml'
        path.write_text(yaml.safe_dump(policy))
        applied = self.cli('policy', 'set', self.target, '--policy', str(path), '--wait', '--timeout', '20')
        if applied.returncode:
            raise RuntimeError('baseline_network_policy_failed')
        return result

    def effect(self, stage):
        nonce = stage + '-' + secrets.token_hex(12)
        control, business = '/control/' + nonce, '/business/' + nonce
        healthy = self.command(['docker', 'exec', self.receiver_id, 'python', '-c',
                                "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080" + control + "',timeout=3).read().decode())"])
        execution = self.cli('sandbox', 'exec', '--name', self.target, '--timeout', '10', '--no-tty', '--', '/usr/bin/curl', '--fail', '--max-time', '5', '--silent', '--show-error', 'http://effect-sink:8080' + business, timeout=20)
        logs = self.command(['docker', 'logs', self.receiver_id])
        if logs.returncode:
            raise RuntimeError('receiver_observation_failed')
        return {'stage': stage, 'receiver_id': self.receiver_id, 'target': self.target, 'control_path': control, 'business_path': business,
                'control_exit_code': healthy.returncode, 'exit_code': execution.returncode, 'stdout': execution.stdout.decode(), 'stderr': execution.stderr.decode(), 'receiver_stdout': logs.stdout.decode()}

    def close(self):
        if self.receiver_id:
            result = self.command(['docker', 'rm', '-f', self.receiver_id])
            self.cleanup['receiver_removed'] = result.returncode == 0
        super().close()
