#!/usr/bin/env python3
"""Inspect an owned real OpenShell sandbox without changing a daily gateway."""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

import tomllib
from build_native_overlay import IMAGE

RESEARCH = Path('/home/maoyd/siq-research-engine')
CLI = RESEARCH / 'var/openshell/toolchains/v0.0.83/bin/openshell'
GATEWAY = RESEARCH / 'var/openshell/toolchains/v0.0.83/bin/openshell-gateway'
TEMPLATE = RESEARCH / 'var/openshell/gateway/siq-openshell-scope-validation/gateway.toml'
XDG = RESEARCH / 'var/openshell/xdg'
NAME = 'siq-openshell-scope-validation'
PYTHON = '/opt/siq/hermes/venv/bin/python'
PROBE = '''import errno,hashlib,json,os,stat,time
status={}
for line in open('/proc/self/status'):
    key,_,value=line.partition(':')
    if key in ('Uid','Gid','NSpid','CapEff','CapPrm','CapAmb','NoNewPrivs','Seccomp'):
        status[key]=value.split()
files=[]
for path in ['/opt/hermes-agent/run_agent.py','/opt/hermes-agent/tools/registry.py','/opt/siq/hermes/venv/bin/python']:
    info=os.stat(path)
    denied=None
    try:
        fd=os.open(path,os.O_WRONLY)
        os.close(fd)
    except OSError as error:
        denied=error.errno
    files.append({'path':path,'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode),'write_open_errno':denied})
print(json.dumps({'native_probe_ready':True,'pid':os.getpid(),'status':status,'files':files}),flush=True)
time.sleep(40)
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(output, *, image_profile=False):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    original = sha(TEMPLATE)
    config = tomllib.loads(TEMPLATE.read_text())
    namespace = 'siq-opt08-' + uuid.uuid4().hex[:12]
    sandbox = namespace + '-hermes'
    ports = []
    for _ in range(2):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            ports.append(listener.getsockname()[1])
    gateway = config['openshell']['gateway']
    driver = config['openshell']['drivers']['docker']
    gateway['bind_address'], gateway['health_bind_address'] = f'127.0.0.1:{ports[0]}', f'127.0.0.1:{ports[1]}'
    gateway['sandbox_namespace'] = namespace
    driver['sandbox_namespace'], driver['network_name'] = namespace, namespace
    driver['enable_bind_mounts'] = False
    driver.pop('bind_mount_contract', None)
    driver.pop('bind_mount_project_root', None)
    baseline_tls = {name: sha(gateway['tls'][name]) for name in ('cert_path', 'key_path', 'client_ca_path')}
    result = {'schema_version': 'siq.openshell-native-runtime-inspection/v1', 'namespace': namespace,
              'base_image_id': IMAGE, 'model_calls': 0, 'daily_gateway_modified': False}

    def command(argv, *, env=None, timeout=30, required=True):
        completed = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
        if required and completed.returncode:
            # Save only to this private local probe directory, never publish raw
            # service logs or credentials as evidence.
            (output / 'last-command.log').write_bytes(completed.stdout + completed.stderr)
            raise RuntimeError('owned_openshell_command_failed')
        return completed

    prepared = None
    if image_profile:
        from openshell_image_probe import prepare
        prepared = prepare(output, command)
    image = prepared['image'] if prepared else IMAGE
    argv = prepared['argv'] if prepared else [PYTHON, '-I', '-B', '-c', PROBE]

    certificates = output / 'certs'
    command([str(GATEWAY), 'generate-certs', '--output-dir', str(certificates), '--server-san', '127.0.0.1', '--server-san', 'host.openshell.internal'])
    for key, name in (('kid_path', 'kid'), ('public_key_path', 'public.pem'), ('signing_key_path', 'signing.pem')):
        gateway['gateway_jwt'][key] = str(certificates / 'jwt' / name)

    def render(table, prefix=()):
        lines = ['[' + '.'.join(json.dumps(p) for p in prefix) + ']'] if prefix else []
        for key, value in table.items():
            if not isinstance(value, dict):
                lines.append(json.dumps(key) + ' = ' + json.dumps(value))
        for key, value in table.items():
            if isinstance(value, dict):
                lines.extend(render(value, (*prefix, key)))
        return lines

    rendered = '\n'.join(render(config)) + '\n'
    assert tomllib.loads(rendered) == config
    candidate = output / 'gateway.toml'
    candidate.write_text(rendered)
    candidate.chmod(0o600)
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'USER')}
    for name in ('home', 'config', 'state', 'cache', 'data'):
        (output / name).mkdir(mode=0o700)
    env.update(HOME=str(output / 'home'), OPENSHELL_GATEWAY_CONFIG=str(candidate),
               OPENSHELL_DB_URL='sqlite:' + str(output / 'gateway.db'), OPENSHELL_TELEMETRY_ENABLED='false')
    for key in ('CONFIG', 'STATE', 'CACHE', 'DATA'):
        env['XDG_' + key + '_HOME'] = str(output / key.lower())
    metadata_dir = output / 'config/openshell/gateways' / NAME
    metadata_dir.mkdir(parents=True, mode=0o700)
    original_metadata = XDG / 'config/openshell/gateways' / NAME / 'metadata.json'
    metadata_digest = sha(original_metadata)
    metadata = json.loads(original_metadata.read_text())
    metadata['gateway_endpoint'] = f'https://127.0.0.1:{ports[0]}'
    metadata['gateway_port'] = ports[0]
    (metadata_dir / 'metadata.json').write_text(json.dumps(metadata))
    (metadata_dir / 'mtls').symlink_to(original_metadata.parent / 'mtls', target_is_directory=True)
    (output / 'state/openshell').mkdir(mode=0o700)
    (output / 'state/openshell/tls').symlink_to(XDG / 'state/openshell/tls', target_is_directory=True)
    policy = output / 'policy.yaml'
    policy.write_text('''version: 1
filesystem_policy:
  include_workdir: false
  read_only: [/]
  read_write: [/sandbox, /tmp, /dev/null]
landlock:
  compatibility: hard_requirement
process:
  run_as_user: sandbox
  run_as_group: sandbox
network_policies: {}
''')
    attempted, execution = False, None

    def cli(*args, **kwargs):
        return command([str(CLI), '--gateway', NAME, *args], env=env, **kwargs)

    with (output / 'gateway.log').open('wb') as log:
        process = subprocess.Popen([str(GATEWAY)], env=env, cwd=output, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('owned_openshell_gateway_unavailable')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{ports[1]}/healthz', timeout=.5) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.2)
            cli('gateway', 'select', NAME)
            inventory = cli('sandbox', 'list', '--limit', '1000', '--output', 'json')
            assert json.loads(inventory.stdout) == []
            attempted = True
            cli('sandbox', 'create', '--name', sandbox, '--from', image, '--cpu', '500m', '--memory', '512Mi',
                '--no-auto-providers', '--policy', str(policy), '--label', 'siq.acceptance=opt08-native', '--', '/bin/true', timeout=55)
            containers = command(['/usr/bin/docker', 'ps', '--filter', 'network=' + namespace, '--format', '{{.ID}}']).stdout.decode().split()
            assert len(containers) == 1
            cid = containers[0]
            fmt = '{{json .Image}}\n{{json .State.Pid}}\n{{json .HostConfig.ReadonlyRootfs}}\n{{json .Config.Labels}}'
            info = command(['/usr/bin/docker', 'inspect', '--format', fmt, cid]).stdout.decode().splitlines()
            assert json.loads(info[0]) == image
            labels = json.loads(info[3])
            assert labels['openshell.ai/sandbox-namespace'] == namespace
            assert labels['openshell.ai/sandbox-name'] == sandbox
            result['docker'] = {'image_matches': True, 'root_filesystem_readonly': json.loads(info[2]),
                                'label_keys': sorted(json.loads(info[3]))}
            exec_log = output / 'command.log'
            with exec_log.open('wb') as observed:
                execution = subprocess.Popen([str(CLI), '--gateway', NAME, 'sandbox', 'exec', '--name', sandbox,
                    '--no-tty', '--timeout', '50', '--', *argv], env=env,
                    stdin=subprocess.DEVNULL, stdout=observed, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 20
                while True:
                    rows = [json.loads(line) for line in exec_log.read_text(errors='replace').splitlines() if line.startswith('{"native_probe_ready":')]
                    if rows:
                        break
                    if execution.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('owned_openshell_process_unavailable')
                    time.sleep(.1)
                assert len(rows) == 1
                result['runtime'] = rows[0]
                target_pid = rows[0]['pid']
                candidates = command(['/usr/bin/docker', 'top', cid, '-eo', 'pid']).stdout.decode().splitlines()[1:]
                peers = []
                init_pid = json.loads(info[1])
                init_groups = Path(f'/proc/{init_pid}/cgroup').read_text()
                init_fields = dict(line.split(':', 1) for line in Path(f'/proc/{init_pid}/status').read_text().splitlines() if ':' in line)
                for candidate_pid in candidates:
                    pid = int(candidate_pid.strip())
                    try:
                        fields = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
                        if (int(fields['NSpid'].split()[-1]) == target_pid
                                and len(fields['NSpid'].split()) == len(init_fields['NSpid'].split())
                                and Path(f'/proc/{pid}/cgroup').read_text() == init_groups):
                            peers.append(pid)
                    except (FileNotFoundError, ProcessLookupError):
                        pass
                assert len(peers) == 1
                peer = peers[0]
                result['host_process'] = {'unique_container_cgroup_and_pid_depth_match': True}
                for name, path in {'status': f'/proc/{peer}/status', 'root_code': f'/proc/{peer}/root/opt/hermes-agent/run_agent.py', 'mountinfo': f'/proc/{peer}/mountinfo'}.items():
                    try:
                        with open(path, 'rb') as file:
                            file.read(1)
                        result['host_process'][name + '_readable'] = True
                    except PermissionError:
                        result['host_process'][name + '_readable'] = False
                if prepared:
                    from openshell_image_probe import verify
                    result['image_profile'] = verify(prepared, peer=peer, cid=cid, namespace=namespace,
                        sandbox=sandbox, init_pid=init_pid, init_groups=init_groups, row=rows[0],
                        command=command, exec_log=exec_log)
            result['inspection_complete'] = True
        finally:
            if attempted:
                deleted = cli('sandbox', 'delete', sandbox, required=False)
                result['owned_sandbox_delete_exit'] = deleted.returncode
            if execution is not None:
                try:
                    execution.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    execution.terminate()
                    execution.wait(timeout=5)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            remaining = command(['/usr/bin/docker', 'ps', '-a', '--filter', 'network=' + namespace, '--format', '{{.ID}}']).stdout.strip()
            result['owned_network_empty'] = not remaining
            if not remaining:
                result['network_cleanup_exit'] = command(['/usr/bin/docker', 'network', 'rm', namespace], required=False).returncode
            result['original_configuration_unchanged'] = sha(TEMPLATE) == original and sha(original_metadata) == metadata_digest
            result['original_tls_unchanged'] = all(sha(gateway['tls'][name]) == value for name, value in baseline_tls.items())
            result['gateway_binary_sha256'], result['cli_sha256'] = sha(GATEWAY), sha(CLI)
            (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image-profile', action='store_true')
    args = parser.parse_args()
    run(args.output.resolve(), image_profile=args.image_profile)
