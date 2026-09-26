#!/usr/bin/env python3
"""Read-only import-closure check for a git ref: can `import app.main` stand on that ref alone?

背景（R09.17）：R08 的冻结允许清单核验的是「路径是否存在、内容是否稳定、有没有冲突」，
**没有核验「被提交路径的导入闭包」**。于是一个提交可以只入库 `app/main.py` 的接线而不入库它
新导入的路由模块，清单仍然全绿，而该 ref 的干净检出**连导入都做不到**——从它发布起不了控制面，
在它上面跑 pytest 会收集期即失败。本工具把这件事变成**可重复的只读检查**。

做法：`git archive <ref> apps/control-api` 导出到临时目录 → 反复尝试在**只指向该临时目录**的
解释器环境里 `import app.main` → 若失败，从异常里解析出缺失的模块/符号，去**工作树**里定位该
模块文件，把它拷进临时树，再试一轮；直到导入成功、或轮次耗尽、或工作树也定位不到。

**只读**：不写任何仓库路径、不改共享工作树、不切换分支、不提交；临时目录在 finally 里删除。
**不读真实秘密**：子进程环境是白名单（PATH/HOME/LANG/LC_ALL/TZ + PYTHONDONTWRITEBYTECODE +
`SIQ_AS_DEV=1` 合成 dev 身份 + PYTHONPATH 指向临时树）；不读 .env / 私钥 / 种子。
**不产生** `enforcement_verified`：本工具与强制点无关，也不使任何门禁变绿。

产出结论（`conclusion`）：
  - `import_closure_closed_at_ref`：该 ref 自身即可导入，**无需**任何工作树文件（最健康）。
  - `import_closure_open`：需补入若干**工作树**路径才能导入 → 这些是「清单没覆盖到的闭包缺口」。
  - `import_closure_unresolvable`：缺的模块连工作树里都没有 → 不能靠"补工作树文件"解决。
  - `probe_environment_unsafe`：导入解析到的 `app` 不在临时树内（路径泄漏）→ 本次结论作废。
退出码：**0 只在 `import_closure_closed_at_ref` 时出现**，其余一律非 0（它不是门禁，但也不许把
「闭包开着」读成绿）。**核验通过只说明「这个 ref 的导入面是否自足」，不是发布授权、不是已冻结。**
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SUBTREE = 'apps/control-api'
SCHEMA = 'import-closure-check/v1'
# 子进程环境的白名单：只给合成 dev 身份与解释器必需项，不继承调用者的 SIQ_AS_* / 凭据类变量。
ENV_KEYS = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ')
MODULE_MISSING_RE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
NAME_MISSING_RE = re.compile(r"ImportError: cannot import name '([^']+)' from '([^']+)'")
APP_FILE_RE = re.compile(r'APP_FILE=(.+)')
MAX_ROUNDS_DEFAULT = 40


class BoundedFailure(Exception):
    """有界失败：只带固定判别码与少量摘要，正文一律不进留痕。"""

    def __init__(self, reason, **observed):
        super().__init__(reason)
        self.reason = reason
        self.observed = observed


def run_git(repo, *args, check=True):
    proc = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise BoundedFailure('git_command_failed', git_subcommand=args[0])
    return proc


def export_ref(repo, sha, dest):
    """把 ref 的 control-api 子树导出到 dest（只读；不触碰工作树）。"""
    archive = subprocess.run(['git', '-C', str(repo), 'archive', sha, SUBTREE],
                             capture_output=True, check=False).stdout
    if not archive:
        raise BoundedFailure('ref_subtree_absent', ref_sha=sha)
    tmp_tar = dest / '_ref.tar'
    tmp_tar.write_bytes(archive)
    with tarfile.open(tmp_tar) as handle:
        handle.extractall(dest, filter='data')
    tmp_tar.unlink()
    root = dest / SUBTREE
    if not (root / 'app' / 'main.py').is_file():
        raise BoundedFailure('ref_main_absent', ref_sha=sha)
    return root


def probe(root, python_exe):
    """在只指向 root 的环境里导入 app.main；返回 (ok, 合并输出, 解析到的 app 文件)。

    `app.__file__` 在**导入 app 之后立刻打印**，因此即使 `app.main` 失败也拿得到它——
    这正是"路径泄漏"守卫所需要的（曾真的撞到：cwd 下另有一个可导入的 `app`）。
    """
    code = ('import app, sys; sys.stdout.write("APP_FILE=" + str(app.__file__) + chr(10)); '
            'import app.main')
    env = {key: os.environ.get(key, '') for key in ENV_KEYS}
    env.update({'PYTHONDONTWRITEBYTECODE': '1', 'SIQ_AS_DEV': '1', 'PYTHONPATH': str(root)})
    proc = subprocess.run([str(python_exe), '-c', code], cwd=str(root), env=env,
                          capture_output=True, text=True, check=False)
    match = APP_FILE_RE.search(proc.stdout)
    return proc.returncode == 0, proc.stdout + proc.stderr, (match.group(1).strip() if match else None)


def module_file(root, dotted):
    """把点分模块名映射到工作树里的文件路径；找不到返回 None。"""
    parts = dotted.split('.')
    candidate = root.joinpath(*parts).with_suffix('.py')
    if candidate.is_file():
        return candidate
    package = root.joinpath(*parts) / '__init__.py'
    return package if package.is_file() else None


def classify_failure(output):
    """判出「下一批可尝试补入的模块」（按优先级排序，最多两个候选）；判不出返回空列表。

    两类失败要分开：
      - `No module named 'a.b.c'` → 就补 `a.b.c`。
      - `cannot import name 'Y' from 'X'` → **两种可能**：X 是旧版（缺该符号）→ 补 `X`；
        或者 Y 是 X 包下一个**没被提交的子模块**（`from app.routers import Y` 在 Y 子模块文件
        缺失时也报这个名字）→ 补 `X.Y`。先试 `X.Y` 再试 `X`，避免把包 `__init__` 反复重拷。
    """
    match = MODULE_MISSING_RE.search(output)
    if match:
        return [match.group(1)]
    match = NAME_MISSING_RE.search(output)
    if match:
        symbol, owner = match.group(1), match.group(2)
        return [f'{owner}.{symbol}', owner]
    return []


def last_line(output):
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    return lines[-1][:120] if lines else ''


def git_state(repo, rel_path):
    """返回该路径在**工作树**里的状态种类与增删行数（只读）。"""
    porcelain = run_git(repo, 'status', '--porcelain', '--', rel_path).stdout.strip()
    if porcelain.startswith('??'):
        return 'untracked_in_worktree', None, None
    numstat = run_git(repo, 'diff', '--numstat', '--', rel_path, check=False).stdout.strip()
    added = removed = None
    if numstat:
        added, removed = numstat.split('\t')[:2]
    kind = 'tracked_modified_in_worktree' if porcelain else 'tracked_clean_in_worktree'
    return kind, added, removed


def assert_app_under_root(app_file, root):
    """路径泄漏守卫：解析到的 app 必须落在临时树内，否则本次结论作废。"""
    if not app_file:
        return False
    try:
        Path(app_file).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repo', type=Path, required=True, help='仓库根（只读；不切换、不提交）')
    parser.add_argument('--ref', default='HEAD', help='要核验的 git ref（默认 HEAD）')
    parser.add_argument('--out', type=Path, required=True, help='证据目录（独占创建，已存在即拒绝）')
    parser.add_argument('--max-rounds', type=int, default=MAX_ROUNDS_DEFAULT)
    args = parser.parse_args()

    repo = args.repo.resolve()
    if run_git(repo, 'rev-parse', '--git-dir', check=False).returncode != 0:
        parser.error(f'{repo} is not a git repository')
    try:
        args.out.mkdir(parents=True, exist_ok=False, mode=0o700)
    except FileExistsError:
        # 独占创建：已存在即拒绝，且**不触碰**原目录（既有证据不被覆盖）
        print(json.dumps({'conclusion': 'out_dir_exists', 'out_touched': False}, ensure_ascii=False),
              file=sys.stderr)
        raise SystemExit(2) from None

    tmp_root = Path(tempfile.mkdtemp(prefix='siq-import-closure-'))
    report = {'schema_version': SCHEMA, 'conclusion': None, 'ref': args.ref, 'failed': False,
              'production_eligible': False, 'writes_to_repo': False, 'enforcement_verified': False,
              'temp_dir_removed': False}
    try:
        sha = run_git(repo, 'rev-parse', '--verify', f'{args.ref}^{{commit}}').stdout.strip()
        report['ref_sha'] = sha
        worktree = repo / SUBTREE
        extraction = export_ref(repo, sha, tmp_root)
        grafted, rounds = [], []
        for attempt in range(1, args.max_rounds + 1):
            ok, output, app_file = probe(extraction, sys.executable)
            if not assert_app_under_root(app_file, extraction):
                raise BoundedFailure('probe_environment_unsafe', rounds_used=attempt, grafted_paths=grafted)
            if ok:
                rounds.append({'round': attempt, 'result': 'import_ok'})
                report['conclusion'] = 'import_closure_closed_at_ref' if not grafted else 'import_closure_open'
                break
            candidates = classify_failure(output)
            if not candidates:
                raise BoundedFailure('unexpected_import_failure', rounds_used=attempt,
                                     grafted_paths=grafted, failure_line=last_line(output))
            source = picked = None
            for dotted in candidates:
                found = module_file(worktree, dotted)
                if found is not None:
                    source, picked = found, dotted
                    break
            if source is None:
                rounds.append({'round': attempt, 'result': 'unresolvable', 'candidates': candidates})
                report['conclusion'] = 'import_closure_unresolvable'
                break
            rel = str(source.relative_to(repo))
            # 同一份工作树文件再拷一次不可能改变结果 ⇒ 立刻停，不空转到轮次耗尽（曾真的空转过）
            if rel in [item['path'] for item in grafted]:
                raise BoundedFailure('no_progress', rounds_used=attempt, grafted_paths=grafted,
                                     repeated_path=rel, failure_line=last_line(output))
            kind, added, removed = git_state(repo, rel)
            grafted.append({'path': rel, 'kind': kind, 'insertions': added, 'deletions': removed})
            target = extraction / Path(rel).relative_to(SUBTREE)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            rounds.append({'round': attempt, 'result': 'grafted', 'module': picked, 'path': rel})
        else:
            raise BoundedFailure('rounds_exhausted', rounds_used=args.max_rounds, grafted_paths=grafted)
        report['rounds'] = rounds
        report['grafted_paths'] = grafted
        report['round_count'] = len(rounds)
    except BoundedFailure as failure:
        report['failed'] = True
        report['reason'] = failure.reason
        report['conclusion'] = report['conclusion'] or failure.reason
        report.update(failure.observed)
    finally:
        # 计数在正常路径与有界失败路径上都可见（失败时也要能看到"补到第几个"）
        report.setdefault('grafted_paths', [])
        report['grafted_count'] = len(report['grafted_paths'])
        shutil.rmtree(tmp_root, ignore_errors=True)
        report['temp_dir_removed'] = not tmp_root.exists()
        (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    print(json.dumps({'conclusion': report['conclusion'], 'ref_sha': report.get('ref_sha'),
                      'grafted_count': report.get('grafted_count', 0)}, ensure_ascii=False))
    raise SystemExit(0 if report['conclusion'] == 'import_closure_closed_at_ref' else 1)


if __name__ == '__main__':
    main()
