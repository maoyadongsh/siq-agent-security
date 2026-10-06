"""Run the frozen product cohort in a disposable Docker network with DoH DNS."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from common import sha256, utc_now, write_json

IMAGE = 'sha256:4f8d1afed6d58037c680221ca6dd9fb4737b7ecfa7d4809ca809fdc0c7d9b786'


def docker(args, *, check=True, timeout=30):
    return subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout, check=check)


def run(protocol):
    p = json.loads(protocol.read_text())
    campaign = Path(p['campaign_root'])
    repo = campaign.parents[1]
    for name, digest in p['harness_sources'].items():
        if sha256(protocol.parent / 'harness-source' / name) != digest:
            raise ValueError('container evaluator source changed')
    if p.get('container_image') != IMAGE or p.get('network_environment') != 'container_doh_dns':
        raise ValueError('network environment not frozen')
    image = json.loads(docker(['image', 'inspect', IMAGE]).stdout)[0]
    label = 'siq.evaluation=' + p['run_id']
    network = 'siq-eval-' + p['run_id']
    dns_name, product_name = network + '-dns', network + '-product'
    for name in (dns_name, product_name):
        if docker(['ps', '-aq', '--filter', 'name=^/' + name + '$']).stdout.strip():
            raise ValueError('owned container name already exists')
    if docker(['network', 'ls', '-q', '--filter', 'name=^' + network + '$']).stdout.strip():
        raise ValueError('owned network already exists')
    out = campaign / 'reports' / (p['run_id'] + '-container-environment.json')
    if out.exists():
        raise ValueError('environment record exists')
    record = {'run_id': p['run_id'], 'started_at': utc_now(), 'image_id': image['Id'], 'image_architecture': image['Architecture'],
              'network_environment': 'container_doh_dns', 'containers': [], 'error_type': None, 'product_exit_code': None, 'host_processes': []}
    net_id = None
    created = []
    exit_code = 1
    try:
        net_id = docker(['network', 'create', '--label', label, network]).stdout.strip()
        record['network_id'] = net_id
        limits = ['--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only', '--pids-limit', '128', '--memory', '512m', '--label', label,
                  '--user', f'{os.getuid()}:{os.getgid()}', '--network', network, '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m']
        relay = protocol.parent / 'harness-source/source_doh_relay.py'
        dns_id = docker(['run', '-d', '--name', dns_name, *limits, '--mount', f'type=bind,src={relay},dst=/relay.py,readonly', IMAGE, 'python', '-B', '/relay.py']).stdout.strip()
        created.append(dns_id)
        record['containers'].append({'role': 'dns', 'id': dns_id})
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            state = json.loads(docker(['inspect', dns_id]).stdout)[0]
            if not state['State']['Running']:
                raise ValueError('resolver exited')
            if 'dns_ready' in docker(['logs', dns_id]).stdout:
                break
            time.sleep(.1)
        else:
            raise TimeoutError('resolver readiness')
        dns_ip = state['NetworkSettings']['Networks'][network]['IPAddress']
        record['resolver_ip'] = dns_ip
        site = next((campaign / 'private/candidates/5470ab3780f2-governancefix1/apps/control-api/.venv/lib').glob('python*/site-packages'))
        command = ['run', '-d', '--name', product_name, *limits, '--dns', dns_ip,
                   '--mount', f'type=bind,src={repo},dst={repo},readonly', '--mount', f'type=bind,src={campaign},dst={campaign}',
                   '--workdir', str(repo), '--env', 'PYTHONPATH=' + str(site), '--env', 'PYTHONDONTWRITEBYTECODE=1',
                   IMAGE, 'python', str(protocol.parent / 'harness-source/remote_source_import.py'), 'run', '--protocol', str(protocol)]
        product_id = docker(command).stdout.strip()
        created.append(product_id)
        record['containers'].append({'role': 'product', 'id': product_id})
        seen = set()
        deadline = time.monotonic() + 510
        while time.monotonic() < deadline:
            state = json.loads(docker(['inspect', product_id]).stdout)[0]
            if not state['State']['Running']:
                exit_code = record['product_exit_code'] = state['State']['ExitCode']
                break
            top = docker(['top', product_id, '-eo', 'pid'], check=False)
            for value in top.stdout.splitlines()[1:]:
                if not value.strip().isdigit():
                    continue
                pid = int(value)
                try:
                    ticks = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
                except FileNotFoundError:
                    continue
                if (pid, ticks) not in seen:
                    seen.add((pid, ticks))
                    record['host_processes'].append({'pid': pid, 'start_ticks': ticks})
            time.sleep(.25)
        else:
            raise TimeoutError('container cohort deadline')
    except Exception as error:  # noqa: BLE001 -- all created objects cleaned, no daemon secrets in error text
        record['error_type'] = type(error).__name__
    finally:
        logs = {}
        for container in record['containers']:
            content = docker(['logs', container['id']], check=False)
            logs[container['role']] = {'stdout': content.stdout, 'stderr': content.stderr}
        write_json(campaign / 'reports' / (p['run_id'] + '-container-logs.json'), logs)
        record['removal'] = [{'id': cid, 'exit_code': docker(['rm', '-f', cid], check=False).returncode} for cid in reversed(created)]
        record['network_remove_exit_code'] = docker(['network', 'rm', net_id], check=False).returncode if net_id else None
        record['owned_containers_absent'] = not docker(['ps', '-aq', '--filter', 'label=' + label]).stdout.strip()
        record['owned_network_absent'] = not docker(['network', 'ls', '-q', '--filter', 'label=' + label]).stdout.strip()
        record['host_processes_absent'] = all(not Path(f'/proc/{ref["pid"]}/stat').exists() or Path(f'/proc/{ref["pid"]}/stat').read_text().rsplit(')', 1)[1].split()[19] != ref['start_ticks'] for ref in record['host_processes'])
        record['finished_at'] = utc_now()
        write_json(out, record)
    print(json.dumps({'run_id': p['run_id'], 'product_exit_code': record['product_exit_code'], 'error_type': record['error_type'], 'containers_absent': record['owned_containers_absent'], 'network_absent': record['owned_network_absent']}), flush=True)
    return exit_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.protocol.resolve()))
