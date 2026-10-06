"""Prepare synthetic publication using the original external publisher CLI."""
import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

ROOT = '/sandbox/siq-business'
TOOL = 'mcp__siq_business__research_verify_published_report'
KEY = 'evaluation-synthetic-report'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def snapshot(root):
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob('*')) if f.is_file()}


def build_inputs(root):
    fixture = root / 'fixtures'
    fixture.mkdir(mode=0o700)
    company = 'EVALUATION-SYNTHETIC'
    assets = {
        'input_preflight': ('application/json', b'{"ok":true}\n'),
        'input_metric_snapshot': ('application/json', b'{"metrics":3}\n'),
        'input_evidence_package': ('application/json', b'{"evidence":8}\n'),
        'report_markdown': ('text/markdown', b'# Synthetic verified report\n'),
        'report_json': ('application/json', canonical({'report_meta': {'company_id': company, 'report_year': 2026}}) + b'\n'),
        'report_html': ('text/html', b'<!doctype html><title>Synthetic verified report</title>\n'),
    }
    bindings = {role: {'sha256': hashlib.sha256(assets['report_' + role][1]).hexdigest(), 'size': len(assets['report_' + role][1])}
                for role in ('markdown', 'json', 'html')}
    warnings = ['synthetic_non_production_fixture']
    quality = {'ok': True, 'contract_pass': True, 'publish_ready': False, 'pass_with_review': True,
               'publication_status': 'pass_with_review', 'failures': [], 'warnings': warnings,
               'factcheck': {'verdict': 'approve'}, 'report_artifacts': bindings}
    factcheck = {'verdict': 'approve', 'company_id': company,
                 'report_artifacts': {k: v for k, v in bindings.items() if k in ('markdown', 'json')}}
    assets['quality_receipt'] = ('application/json', canonical(quality) + b'\n')
    assets['factcheck_receipt'] = ('application/json', canonical(factcheck) + b'\n')
    artifacts = []
    for role, (media, data) in assets.items():
        file = fixture / (role + '.artifact')
        file.write_bytes(data)
        file.chmod(0o600)
        artifacts.append({'role': role, 'path': str(file.relative_to(root)), 'media_type': media,
                          'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)})
    request = {'schema_version': 'siq.report-publication-request/v1', 'request_id': 'evaluation-request-001',
               'task_id': 'evaluation-task-001', 'company_id': company, 'report_id': KEY, 'report_year': 2026,
               'data_classification': 'confidential', 'target': {'channel': 'non_production_test_fixture',
               'report_key': KEY, 'expected_version': 0}, 'artifacts': artifacts}
    workspace = root / 'var/openshell/task-workspaces/evaluation-task-001'
    workspace.mkdir(parents=True, mode=0o700)
    for d in [root / 'var', root / 'var/openshell', workspace.parent, workspace]:
        d.chmod(0o700)
    request_path = workspace / 'publication-request.json'
    request_path.write_bytes(canonical(request) + b'\n')
    request_path.chmod(0o600)
    projection = [{k: a[k] for k in ('role', 'media_type', 'sha256', 'size')} for a in sorted(artifacts, key=lambda a: a['role'])]
    now = datetime.now(timezone.utc)
    approval = {'schema_version': 'siq.report-publication-approval/v1', 'approval_id': 'evaluation-approval-001',
                'approval_kind': 'non_production_test_fixture', 'approval_authority': 'evaluation-local-test-authority',
                'decision': 'approve_with_review', 'request_id': request['request_id'],
                'request_sha256': hashlib.sha256(request_path.read_bytes()).hexdigest(),
                'artifact_set_sha256': digest(projection), 'target_sha256': digest(request['target']),
                'quality_receipt_sha256': next(a['sha256'] for a in artifacts if a['role'] == 'quality_receipt'),
                'factcheck_receipt_sha256': next(a['sha256'] for a in artifacts if a['role'] == 'factcheck_receipt'),
                'warnings_sha256': digest(sorted(warnings)), 'production_eligible': False,
                'approved_at': (now - timedelta(minutes=1)).isoformat().replace('+00:00', 'Z'),
                'expires_at': (now + timedelta(hours=1)).isoformat().replace('+00:00', 'Z')}
    approval_path = workspace / 'publication-approval.json'
    approval_path.write_bytes(canonical(approval) + b'\n')
    approval_path.chmod(0o600)
    return request_path.relative_to(root).as_posix(), approval_path.relative_to(root).as_posix()


class PublisherFixture:
    def __init__(self, protocol, unit, path):
        self.p, self.unit, self.path = protocol, unit, path
        self.root = path / 'publication'
        self.root.mkdir(mode=0o700)
        self.cid = None
        request, approval = build_inputs(self.root)
        source = protocol['publisher_source']['frozen_root']
        self.common = ['--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                       '--user', f'{os.getuid()}:{os.getgid()}', '--memory', '256m', '--cpus', '1', '--pids-limit', '64',
                       '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', '--mount', f'type=bind,src={source},dst=/opt/business-source,readonly']
        run = subprocess.run(['docker', 'run', '--rm', *self.common, '--mount', f'type=bind,src={self.root},dst={ROOT}',
            protocol['publisher_source']['image_id'], 'python', '/opt/business-source/scripts/openshell/publish_verified_report.py',
            '--project-root', ROOT, '--request', request, '--approval', approval], capture_output=True, text=True, timeout=60, check=False)
        self.preparation = {'exit_code': run.returncode, 'stdout': run.stdout, 'stderr': run.stderr}
        if run.returncode:
            raise ValueError('original publisher preparation failed: ' + run.stdout[:200])
        self.publication = json.loads(run.stdout)
        if not self.publication['ok'] or not self.publication['readback_verified']:
            raise ValueError('publisher readback not verified')
        self.before = snapshot(self.root)
        self.label = protocol['run_id'] + '-' + unit['unit_id']
        create = ['docker', 'create', '-i', *self.common, '--label', 'siq-evaluation-owner=' + self.label,
                  '--mount', f'type=bind,src={self.root},dst={ROOT},readonly',
                  '--mount', f'type=bind,src={protocol["mcp_sdk_root"]},dst=/opt/mcp-sdk,readonly',
                  '--env', 'PYTHONPATH=/opt/mcp-sdk', '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'SIQ_PROJECT_ROOT=' + ROOT,
                  protocol['publisher_source']['image_id'], 'python', '/opt/business-source/scripts/openshell/research_business_tools_mcp.py', '--serve']
        self.cid = subprocess.check_output(create, text=True, timeout=30).strip()
        self.inspection = self.inspect()
        (path / 'owned-container.json').write_text(json.dumps({'id': self.cid, 'label': self.label}))

    def inspect(self):
        data = json.loads(subprocess.check_output(['docker', 'inspect', self.cid], text=True, timeout=15))[0]
        if data['Config']['Labels'].get('siq-evaluation-owner') != self.label:
            raise ValueError('container ownership differs')
        return {'Id': data['Id'], 'Image': data['Image'], 'State': data['State'], 'Mounts': data['Mounts'],
                'User': data['Config']['User'], 'ReadonlyRootfs': data['HostConfig']['ReadonlyRootfs'],
                'NetworkMode': data['HostConfig']['NetworkMode'], 'CapDrop': data['HostConfig']['CapDrop'],
                'Label': self.label}

    def finish(self):
        after = self.inspect()
        subprocess.run(['docker', 'rm', '-f', self.cid], check=True, capture_output=True, timeout=20)
        absent = subprocess.run(['docker', 'inspect', self.cid], capture_output=True, timeout=15, check=False).returncode != 0
        return {'preparation': self.preparation, 'publication': self.publication, 'before': self.before,
                'after': snapshot(self.root), 'container_before': self.inspection, 'container_after': after,
                'removed': absent, 'root': ROOT, 'scope': 'original source in owned no-network Docker process; not an OpenShell deployment or SIQ-enforced container isolation'}
