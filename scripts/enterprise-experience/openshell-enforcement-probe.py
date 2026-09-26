#!/usr/bin/env python3
"""行为 fixture 通道的一次性执行工具（P0：实现完成，**未在真实目标上运行过**）。

它把方案 `docs/development/deepseek-enterprise-mainline-closeout-behaviour-fixture-plan-20260926.md`
§3 的三臂差分落成一次可复核的运行：

  允许臂（边界内，路径 A，同一 endpoint）→ 必须 `connected`
  拒绝臂（边界内，路径 B，**同一个** endpoint）→ 必须被拦
  可达性对照（**边界外**，控制面主机）→ 必须 `connected`

A 与 B 是**同一份探针脚本**的两个副本（上传两次、路径不同、内容摘要相同），
所以"差别"只可能来自策略按 binary 路径做的归因。三段齐、且与读回的
revision/digest/指纹**逐项绑定**，证据才可能被校验器接受。

**本工具不是门禁、不接线、无默认开启**，且：

- 默认是**计划模式**：只把"将要执行的 argv"打出来，**不调用任何网关命令**；
- 真正执行需要同时给出 `--execute` 与 `--confirm-behaviour-probe`，以及
  **算子授权目录**里与本目标匹配的条目；
- 本工具**不写策略**：允许臂那条规则必须**已经**在生效策略里（运行前由算子按
  部署路径写入），工具只读回确认；不在即拒绝（`probe_allow_rule_absent`）；
- 它**不产生** `enforcement_verified` 这个事实本身——它只产出一份**候选证据**，
  采信与否由 `validate_enforcement_probe_evidence` 判定，且部署路径是否使用该证据
  由 `verify(probe_evidence=...)` 的调用方决定。

天花板（写进报告，不藏）：P0 阶段该工具**从未在真实目标上跑过**；能给出的最强结论是
"在本机合成件上，检测器能区分被拦 / 目标已死 / 夹具撒谎"。
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
AGENT_SOURCE = ROOT / 'scripts/enterprise-experience/probe/enforcement_probe_agent.py'
REPORT_SCHEMA = 'siq.openshell.enforcement-probe-run/v1'
ENV_BASELINE_KEYS = ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL')


def write_report(out_dir: Path, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    (out_dir / 'report.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def refuse(out_dir: Path, code: str, **observed) -> 'SystemExit':
    """有界失败留痕：只写固定判别码 + 实测摘要，不写路径/策略正文/凭据。"""
    write_report(out_dir, {
        'schema': REPORT_SCHEMA,
        'conclusion': code,
        'production_eligible': False,
        'runtime_policy_mutated': False,
        'enforcement_verified': False,
        'recorded_at': datetime.now(UTC).isoformat(),
        **observed,
    })
    return SystemExit(1)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cli', type=Path, required=True, help='openshell CLI 的绝对路径')
    parser.add_argument('--endpoint', required=True, help='网关 URL（非回环强制 HTTPS）')
    parser.add_argument('--xdg-root', type=Path, required=True, help='XDG 隔离根（绝对路径）')
    parser.add_argument('--target', required=True, help='沙箱名（= 授权目录里的 backend_target_id）')
    parser.add_argument('--endpoint-address', required=True, help='被观测的 host:port')
    parser.add_argument('--allow-path', required=True, help='允许臂所用探针副本的沙箱内绝对路径')
    parser.add_argument('--deny-path', required=True, help='拒绝臂所用探针副本的沙箱内绝对路径')
    parser.add_argument('--operator-authority', type=Path, required=True, help='算子授权目录（绝对路径）')
    parser.add_argument('--agent', type=Path, default=AGENT_SOURCE)
    parser.add_argument('--attempts', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=5.0)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='真正执行（默认只打印计划）')
    parser.add_argument('--confirm-behaviour-probe', action='store_true',
                        help='确认这是对指定目标的一次真实行为探针（含 upload 与 exec）')
    return parser.parse_args(argv)


def agent_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_authority_assignments(path: Path):
    """复用门禁自己的安全读取与解析（各写一套必然漂移；符号改名即响亮 ImportError）。"""
    sys.path.insert(0, str(ROOT / 'apps/control-api'))
    from app.target_authority import TargetAuthority, _read_authority_bytes, _unique_object

    raw = _read_authority_bytes(str(path))
    return TargetAuthority.model_validate(json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object))


def isolated_environment(cli: Path, endpoint: str, xdg_root: Path) -> dict:
    """与既有 E149 工具同款：清成白名单后只注入本工具需要的最小变量。"""
    baseline = {k: v for k, v in os.environ.items() if k in ENV_BASELINE_KEYS}
    env = dict(baseline)
    env.update({
        'SIQ_AS_OPENSHELL_CLI_BIN': str(cli),
        'SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT': endpoint,
        'SIQ_AS_DEV': '1',
    })
    for name in ('CONFIG', 'STATE', 'DATA', 'CACHE', 'RUNTIME'):
        env['XDG_' + name + '_HOME'] = str(xdg_root / name.lower())
    return env


def main():
    args = parse_args()

    # ---- 输入校验（全部在触网之前） ----
    if not args.cli.is_absolute() or not args.cli.is_file():
        raise SystemExit('probe_cli_must_be_absolute_file')
    if not args.xdg_root.is_absolute() or not args.operator_authority.is_absolute():
        raise SystemExit('probe_paths_must_be_absolute')
    if not args.allow_path.startswith('/') or not args.deny_path.startswith('/'):
        raise SystemExit('probe_binary_paths_must_be_absolute')
    if args.allow_path == args.deny_path:
        raise SystemExit('probe_binary_paths_must_differ')
    parsed = urlparse(args.endpoint)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise SystemExit('probe_endpoint_invalid')
    if parsed.hostname not in ('127.0.0.1', 'localhost', '::1') and parsed.scheme != 'https':
        raise SystemExit('probe_endpoint_requires_https')
    if args.attempts < 3 or args.timeout <= 0:
        raise SystemExit('probe_attempts_below_minimum')
    if not args.endpoint_address.rpartition(':')[0] or not args.endpoint_address.rpartition(':')[2].isdigit():
        raise SystemExit('probe_endpoint_address_invalid')
    if not args.agent.is_file():
        raise SystemExit('probe_agent_missing')
    out_dir = args.out_dir
    if out_dir.exists():
        # 独占输出目录：不复用、不覆盖任何既有证据。
        print(json.dumps({'conclusion': 'out_dir_exists', 'out_touched': False}), file=sys.stderr)
        raise SystemExit(2)

    sys.path.insert(0, str(ROOT / 'apps/control-api'))
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.enforcement_probe import (
        DIFFERENTIAL_SAME_ENDPOINT,
        EnforcementProbeEvidence,
        EnforcementProbeExpectation,
        validate_enforcement_probe_evidence,
    )
    from app.adapters.openshell.probe_channel import (
        SandboxExecProbeChannel,
        build_exec_args,
        build_upload_args,
        reachability_control,
        sha256_file,
    )

    os.environ.clear()
    os.environ.update(isolated_environment(args.cli, args.endpoint, args.xdg_root))

    backend = OpenShellCliBackend(env_script='')
    digest = agent_sha256(args.agent)
    # 计划必须是**将要真正发出**的那条 argv：子命令形态复用通道的构建器
    # （单一事实源；否则计划与实际 dispatch 会悄然分叉）。
    planned = {
        'upload_allow': backend._build_command(
            build_upload_args(args.target, str(args.agent.resolve()), args.allow_path)),
        'upload_deny': backend._build_command(
            build_upload_args(args.target, str(args.agent.resolve()), args.deny_path)),
        'exec': [
            backend._build_command(build_exec_args(
                args.target,
                [path, '--endpoint', args.endpoint_address,
                 '--attempts', str(args.attempts), '--timeout', str(args.timeout)],
                timeout=int(args.timeout * args.attempts) + 60,
            ))
            for path in (args.allow_path, args.deny_path)
        ],
        'agent_sha256': digest,
        'read_only': False,
    }

    # ---- 计划模式：只打印将要执行的 argv，**不调用任何网关命令** ----
    if not args.execute or not args.confirm_behaviour_probe:
        write_report(out_dir, {
            'schema': REPORT_SCHEMA,
            'conclusion': 'probe_plan_only',
            'planned_argv': planned,
            'executed': False,
            'production_eligible': False,
            'runtime_policy_mutated': False,
            'enforcement_verified': False,
            'note': '需要 --execute 与 --confirm-behaviour-probe 才会真正执行；本模式不触网。',
            'recorded_at': datetime.now(UTC).isoformat(),
        })
        print('plan written; nothing was executed')
        return 0

    # ---- 算子授权：目标必须被**预先声明**过，不是命令行说了算 ----
    try:
        catalog = load_authority_assignments(args.operator_authority)
    except Exception:
        raise refuse(out_dir, 'probe_authority_unusable') from None
    matches = [item for item in catalog.assignments if item.backend_target_id == args.target]
    if len(matches) != 1:
        raise refuse(out_dir, 'probe_target_not_authorized', match_count=len(matches))
    assignment = matches[0]

    channel = SandboxExecProbeChannel(backend._build_command)
    executed: list[dict] = []

    caps = backend.probe()  # 只读握手
    if caps.endpoint_fingerprint != assignment.endpoint_fingerprint:
        raise refuse(out_dir, 'probe_authority_endpoint_mismatch',
                     authority_fingerprint=assignment.endpoint_fingerprint,
                     observed_fingerprint=caps.endpoint_fingerprint)

    # 所有**只读**前提必须先成立，再动边界：拒绝路径上不许留下任何已发生的写动作。
    snapshot = backend.read_effective_policy(args.target)  # 只读
    allow_pairs = [
        (rule.get('endpoint'), path)
        for rule in snapshot.network
        for path in (rule.get('binary_paths') or [])
        if rule.get('effect') != 'deny'
    ]
    if (args.endpoint_address, args.allow_path) not in allow_pairs:
        raise refuse(out_dir, 'probe_allow_rule_absent',
                     allow_pairs_shown=[[e, p] for e, p in allow_pairs])
    if (args.endpoint_address, args.deny_path) in allow_pairs:
        raise refuse(out_dir, 'probe_deny_path_present_in_allow_set')

    # 上传同一份内容到两个路径（摘要相同 ⇒ 允许臂与拒绝臂只差路径这一个变量）
    channel.upload(args.target, args.agent, args.allow_path)
    channel.upload(args.target, args.agent, args.deny_path)

    allow_arm, allow_result = channel.run_arm(
        args.target, endpoint=args.endpoint_address, binary_path=args.allow_path,
        binary_sha256=digest, attempts=args.attempts, timeout_seconds=args.timeout)
    deny_arm, deny_result = channel.run_arm(
        args.target, endpoint=args.endpoint_address, binary_path=args.deny_path,
        binary_sha256=digest, attempts=args.attempts, timeout_seconds=args.timeout)
    executed.append({'allow_exit': allow_result.exit_code, 'deny_exit': deny_result.exit_code})

    evidence = EnforcementProbeEvidence(
        schema='siq.openshell.enforcement-probe/v1',
        target=args.target,
        endpoint_fingerprint=caps.endpoint_fingerprint,
        policy_revision=snapshot.revision,
        applied_policy_digest=snapshot.policy_digest,
        enforcement_mode=snapshot.enforcement_mode,
        differential=DIFFERENTIAL_SAME_ENDPOINT,
        allow_rule_pairs=allow_pairs,
        allow_arm=allow_arm,
        deny_arm=deny_arm,
        reachability_controls=[reachability_control(args.endpoint_address, timeout=args.timeout)],
        probe_script_sha256s=[digest],
        observed_at=datetime.now(UTC).isoformat(),
    )
    accepted, reason = validate_enforcement_probe_evidence(
        evidence,
        EnforcementProbeExpectation(
            endpoint_fingerprint=caps.endpoint_fingerprint,
            policy_revision=snapshot.revision,
            applied_policy_digest=snapshot.policy_digest,
        ),
    )
    write_report(out_dir, {
        'schema': REPORT_SCHEMA,
        'conclusion': 'probe_discriminated' if accepted else f'probe_not_accepted:{reason}',
        'evidence': evidence.to_dict(),
        'validator_reason': reason,
        'executions': executed,
        'cli_sha256': sha256_file(args.cli),
        'agent_sha256': digest,
        'production_eligible': False,
        'runtime_policy_mutated': False,
        'enforcement_verified': False,
        'note': ('本报告只是**候选证据**：是否采信由部署路径决定，'
                 '且本工具不写策略、不使任何门禁变绿。'),
        'recorded_at': datetime.now(UTC).isoformat(),
    })
    print(f'{args.out_dir}/report.json conclusion=probe_discriminated={accepted} reason={reason}')
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
