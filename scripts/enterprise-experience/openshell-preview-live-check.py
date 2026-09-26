#!/usr/bin/env python3
"""Read-only real OpenShell preview with an isolated dev control plane; never apply.

身份 id 全部来自**算子预先声明的授权目录**：tenant / environment / asset / agent_instance /
backend_target 都取 `--target-authority` 指向的 `enterprise-runtime-target-authority/v1` 文件，
不再由本工具在运行期现造。原因见证据 README §五：`prepare_deployment` 无条件经过
`require_target_authority`，该闸对授权条目做**精确元组相等**判定；运行期现造的 id 不可能出现在
算子运行前写好的目录里，因此本工具在闸生效后**结构性**无法通过预览断言。目录只读；执行的 CLI
命令仅限 gateway info / status / --version / policy get，不写策略、不落凭据、不输出路径。
"""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def write_failure(out_dir, reason, **observed):
    """有界失败留痕：只写固定判别码与摘要，不写路径、策略正文、证书或凭据。"""
    result = {'schema_version': 'openshell-preview-live-check/v1', 'passed': False, 'reason': reason,
              'production_eligible': False, 'runtime_policy_mutated': False, 'enforcement_verified': False}
    result.update(observed)
    (out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': False, 'reason': reason}), file=sys.stderr)
    raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--xdg-root', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--target-authority', type=Path, required=True)
    parser.add_argument('--assignment-id')
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    endpoint = urlparse(args.endpoint)
    if (endpoint.scheme != 'https' or not ipaddress.ip_address(endpoint.hostname).is_loopback
            or endpoint.username or endpoint.password or endpoint.path not in ('', '/')
            or endpoint.query or endpoint.fragment or not endpoint.port):
        parser.error('An explicit HTTPS loopback gateway is required')
    if not args.cli.is_absolute() or not args.cli.is_file() or not args.xdg_root.is_absolute():
        parser.error('Explicit absolute CLI and XDG root are required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', args.target):
        parser.error('Invalid sandbox target')
    # 这里只挡明显写错的路径；真正的描述符逐组件校验（无符号链接、属主、权限位、单硬链接、上限）
    # 由 app.target_authority 在门禁处完成，本处不复制那套判定，避免两套规则漂移。
    if (not args.target_authority.is_absolute() or args.target_authority.is_symlink()
            or not args.target_authority.is_file()):
        parser.error('An explicit absolute operator authority catalog is required')
    if args.assignment_id is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}',
                                                          args.assignment_id):
        parser.error('Invalid assignment id')
    for name in ('config', 'state'):
        if not (args.xdg_root / name).is_dir():
            parser.error('Existing XDG config and TLS state directories are required')
    args.out_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='siq-e149-preview-') as raw:
        root = Path(raw)
        # No inherited provider credentials or unrelated control-plane settings.
        baseline = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL')}
        os.environ.clear()
        os.environ.update(baseline)
        os.environ.update({
            'SIQ_AS_DEV': '1', 'SIQ_AS_ALLOW_SQLITE': '1',
            'SIQ_AS_DATABASE_URL': 'sqlite:///' + str(root / 'control.db'),
            'SIQ_AS_SIGNING_KEY_FILE': str(root / 'signing.seed'),
            'SIQ_AS_ENFORCEMENT_BACKEND': 'openshell-cli',
            'SIQ_AS_OPENSHELL_CLI_BIN': str(args.cli),
            'SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT': args.endpoint,
            'SIQ_AS_OPENSHELL_GATEWAY_INSECURE': '0',
            # 门禁读的就是这个变量；白名单清空环境后必须由本工具显式设回。
            'SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE': str(args.target_authority),
        })
        for name in ('CONFIG', 'STATE', 'DATA', 'CACHE'):
            os.environ['XDG_' + name + '_HOME'] = str(args.xdg_root / name.lower())
        sys.path.insert(0, str(ROOT / 'apps/control-api'))
        from app.adapters.openshell.cli_backend import OpenShellCliBackend
        from app.adapters.openshell.contracts import AdapterError
        from app.db import session_scope
        from app.main import app
        from app.models import (
            AgentAsset,
            AgentInstance,
            AuditEvent,
            Deployment,
            DeploymentSubmission,
            EdgeTask,
            Environment,
            OutboxEvent,
        )
        from app.routers import policies

        # 故意复用门禁自己的读取/解析实现：工具与门禁对"安全目录"和"重复键"的判定必须完全一致，
        # 各写一套必然漂移。符号若被改名会立刻 ImportError（响亮失败），不会静默放宽。
        from app.target_authority import (
            TargetAuthority,
            TargetAuthorityError,
            _read_authority_bytes,
            _unique_object,
        )
        from fastapi.testclient import TestClient
        from sqlalchemy import func, select

        commands = []

        class ReadOnlyBackend(OpenShellCliBackend):
            def __init__(self):
                super().__init__(env_script='', runner=self.read_only_runner)

            def read_only_runner(self, argv):
                allowed = [
                    ['gateway', 'info'], ['status'], ['--version'],
                    ['policy', 'get', args.target, '--full'],
                ]
                if argv not in allowed:
                    raise AdapterError('live_check_write_command_forbidden')
                commands.append(argv[0])
                return self._subprocess_runner(argv)

        # Guard only restricts commands; all permitted responses come from the real CLI.
        policies.OpenShellCliBackend = ReadOnlyBackend
        backend = ReadOnlyBackend()
        caps = backend.probe()
        assert caps.handshake_verified and caps.gateway_version != 'unknown'
        # 算子授权目录是身份 id 的唯一来源。先按 --target（或 --assignment-id）选中唯一条目，
        # 再把这组 id 落到隔离库里——这样门禁的精确元组判定才可能成立。
        try:
            raw = _read_authority_bytes(str(args.target_authority))
            catalog = TargetAuthority.model_validate(
                json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object))
        except TargetAuthorityError as exc:
            write_failure(args.out_dir, 'authority_unusable', authority_error=str(exc))
        except (ValueError, RecursionError):
            write_failure(args.out_dir, 'authority_invalid')
        if args.assignment_id is not None:
            candidates = [item for item in catalog.assignments if item.id == args.assignment_id]
            if not candidates:
                write_failure(args.out_dir, 'authority_assignment_absent')
        else:
            candidates = [item for item in catalog.assignments if item.backend_target_id == args.target]
            if not candidates:
                write_failure(args.out_dir, 'authority_target_absent')
            if len(candidates) > 1:
                write_failure(args.out_dir, 'authority_target_ambiguous', matching_assignments=len(candidates))
        assignment = candidates[0]
        # 两个观测摘要都带上：条目填错时算子一次就能看全需要写进目录的真实值，不必反复试。
        gateway_name_sha256 = hashlib.sha256(caps.handshake_gateway.encode('utf-8')).hexdigest()
        observed = {'observed_endpoint_fingerprint': caps.endpoint_fingerprint,
                    'observed_gateway_name_sha256': gateway_name_sha256}
        if caps.endpoint_fingerprint != assignment.endpoint_fingerprint:
            write_failure(args.out_dir, 'authority_endpoint_mismatch', **observed)
        if gateway_name_sha256 != assignment.gateway_name_sha256:
            write_failure(args.out_dir, 'authority_gateway_mismatch', **observed)
        tenant_id = assignment.tenant_id
        first = backend.read_effective_policy(args.target)
        headers = {'X-Dev-Tenant-Id': tenant_id, 'X-Dev-User-Id': 'preview-owner',
                   'X-Dev-Roles': 'platform_operator,security_admin,agent_owner,auditor'}
        reviewer = {**headers, 'X-Dev-User-Id': 'preview-reviewer', 'X-Dev-Roles': 'reviewer,viewer'}
        checks = {'live_tls_handshake': True, 'live_version_observed': True,
                  'authority_tuple_matches_live_gateway': True}
        with TestClient(app) as client:
            def post(path, body, status=200, identity=None):
                response = client.post('/api/v1' + path, headers=identity or headers, json=body)
                assert response.status_code == status, (path, response.status_code)
                return response.json()

            def counts():
                with session_scope() as session:
                    # 预留行与 outbox 同样计入：它们也是"预览不该产生"的持久写入。
                    return [session.scalar(select(func.count()).select_from(model))
                            for model in (Deployment, EdgeTask, AuditEvent, DeploymentSubmission, OutboxEvent)]

            # 环境/资产/实例按算子声明的 id 直接落隔离库：`POST /environments` 的服务端生成 id
            # 无法与运行前写好的授权目录对齐（这正是本工具此前无法通过预览断言的第二层根因）。
            # 代价是这一支不再经过环境创建 API；E149 验收的对象是预览路由与真实 CLI 读回，不受影响。
            with session_scope() as session:
                session.add(Environment(id=assignment.environment_id, tenant_id=tenant_id,
                                        name='真实网关只读验收', env_type='host', mode='enforce'))
                session.add(AgentAsset(id=assignment.asset_id, tenant_id=tenant_id,
                                       name='只读预览验收对象', status='confirmed'))
                session.add(AgentInstance(id=assignment.agent_instance_id, tenant_id=tenant_id,
                                          asset_id=assignment.asset_id,
                                          environment_id=assignment.environment_id, runtime='hermes'))
                session.commit()
            binding = post('/runtime-bindings', {'agent_instance_id': assignment.agent_instance_id,
                'environment_id': assignment.environment_id, 'backend': 'openshell-cli',
                'backend_target_id': args.target}, 201)
            # A proposed network restriction exists only in the isolated DB.
            policy = post('/policies', {'name': '只读验收提案（不执行）',
                                       'selector': {'agent_ids': [assignment.asset_id]},
                                       'enforcement_mode': 'block', 'network': []}, 201)
            change = post('/change-requests', {'policy_id': policy['id'],
                                             'idempotency_key': 'live-preview-only'}, 201)
            review = client.get('/api/v1/change-requests/' + change['id'] + '/review', headers=reviewer)
            assert review.status_code == 200
            post('/change-requests/' + change['id'] + '/review-decision', {
                'schema_version': 'change-review-decision/v1', 'decision': 'approve',
                'review_digest': review.json()['review_digest']}, identity=reviewer)
            checks['isolated_api_binding_and_review'] = True
            checks['operator_declared_identity_used'] = True
            body = {'schema_version': 'deployment-preview-request/v1', 'change_request_id': change['id'],
                    'environment_id': assignment.environment_id, 'binding_id': binding['id']}
            before = counts()
            value = post('/deployment-preview', body)
            assert value['backend'] == 'openshell-cli' and value['action'] == 'dynamic_update'
            assert value['target'] == args.target and value['base_revision'] == first.revision
            assert counts() == before
            checks['real_preview_no_state_or_audit_write'] = True
            second = post('/deployment-preview', body)
            assert second['preview_digest'] == value['preview_digest']
            checks['unchanged_context_has_stable_preview'] = True
            # Cache context changes without replacing live TLS state; stale submit
            # must stop before apply even though the real gateway is still reachable.
            os.environ['XDG_CACHE_HOME'] = str(root / 'other-cache')
            rejected = post('/deployment-preview/submit', {**body,
                'schema_version': 'deployment-preview-submit/v1',
                'preview_digest': value['preview_digest']}, 409)
            assert counts() == before, (before, counts())
            # **拒绝发生在哪一层是候选相关的**：上下文一变，调用指纹随之改变，算子授权目录里的
            # 条目即不再匹配，`_prepare` 内的 `require_target_authority` 先于摘要比对失败——
            # 因此这里观测到 `deployment_target_authority_unverified`，而不是
            # `deployment_preview_changed`（后者在 deployment_preview.py:252，本路径不可达）。
            # 本工具只钉「被拒 + 零写入」，并把实际判别码如实记下，不假装机制仍是旧的。
            checks['changed_context_refused_without_writes'] = True
            changed_context_detail = rejected['detail']
            os.environ['XDG_CACHE_HOME'] = str(args.xdg_root / 'cache')
            final = backend.read_effective_policy(args.target)
            assert (first.revision, first.policy_digest) == (final.revision, final.policy_digest)
            checks['live_policy_revision_and_digest_unchanged'] = True
            checks['only_allowlisted_read_commands_executed'] = True
            result = {'schema_version': 'openshell-preview-live-check/v1', 'passed': all(checks.values()),
                'checks': checks, 'identity': 'operator_declared_authority', 'real_gateway': True,
                'production_eligible': False, 'runtime_policy_mutated': False,
                'enforcement_verified': False, 'gateway_version': caps.gateway_version,
                'cli_version': caps.cli_version, 'tls_insecure': False,
                'assignment_id': assignment.id, 'authority_sha256': hashlib.sha256(raw).hexdigest(),
                'target_digest': hashlib.sha256(args.target.encode()).hexdigest(),
                'gateway_scope_digest': caps.endpoint_fingerprint,
                'before_revision': first.revision, 'after_revision': final.revision,
                'before_policy_digest': first.policy_digest, 'after_policy_digest': final.policy_digest,
                'preview_digest': value['preview_digest'], 'command_count': len(commands),
                'changed_context_detail': changed_context_detail,
                'post_preview_counts': {'deployments': before[0], 'edge_tasks': before[1]},
                'cli_sha256': hashlib.sha256(args.cli.read_bytes()).hexdigest()}
            (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps({'passed': result['passed'], 'checks': len(checks), 'runtime_policy_mutated': False}))


if __name__ == '__main__':
    main()
