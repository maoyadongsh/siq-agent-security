#!/usr/bin/env python3
"""KIMI-001-R1-B1 变异复跑入口：旧草稿 handler 必须在 HTTP 门控回归上确定性失败。

在 HEAD 的临时 git worktree 内把 grant_draft.go 精确恢复为旧分支（对
ErrIncompleteCommit 立即 409），运行同一个已提交测试
TestGrantDraftHTTPInflightWriterConverges，核对失败签名；随后恢复正确逻辑并
验证通过。不修改用户工作区：所有写入只发生在临时 worktree。基线片段缺失或
出现多次匹配时拒绝继续，不做模糊替换。

用法（仓库根目录）：

    python3 scripts/personal-experience/grant-draft-inflight-mutation.py [--out PATH]
"""

import argparse
import json
import os
import subprocess
from pathlib import Path

TEST_NAME = "TestGrantDraftHTTPInflightWriterConverges"
TEST_RUN = ["go", "test", "./internal/server", "-run", TEST_NAME, "-count=2", "-v"]
HANDLER = "apps/agentshield/internal/server/grant_draft.go"
# 基线（修复后）与变异目标（旧行为）片段；缺失或非唯一即中止。
FIXED_FRAGMENT = "if !errors.Is(err, os.ErrNotExist) && !errors.Is(err, state.ErrIncompleteCommit) {"
MUTANT_FRAGMENT = "if !errors.Is(err, os.ErrNotExist) {"
# 旧行为下的预期失败签名：第二个请求在窗口内得到 409 而非等待收敛。
FAILURE_SIGNATURE = "duplicate returned inside the window instead of waiting: 409"
FORBIDDEN_SIGNATURES = ("build failed", "panic:", "test timed out")


def run(cmd, cwd, timeout):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="可选：把 JSON 证据写入该路径")
    args = parser.parse_args()
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True,
                               capture_output=True, text=True).stdout.strip())
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()
    go_version = subprocess.run(["go", "version"], check=True, capture_output=True, text=True).stdout.strip()
    worktree = root / ".tmp" / f"k001-r1b1-mutation-{os.getpid()}"
    summary = {"test": TEST_NAME, "head": head, "go_version": go_version,
               "worktree": str(worktree), "steps": []}
    try:
        code, out = run(["git", "worktree", "add", "--detach", str(worktree), "HEAD"], root, 120)
        summary["steps"].append({"cmd": "git worktree add --detach HEAD", "exit": code})
        if code != 0:
            raise SystemExit("worktree creation failed: " + out)
        target = worktree / HANDLER
        text = target.read_text()
        if text.count(FIXED_FRAGMENT) != 1 or text.count(MUTANT_FRAGMENT) != 0:
            raise SystemExit("baseline fragment missing or ambiguous; refusing fuzzy replacement")
        target.write_text(text.replace(FIXED_FRAGMENT, MUTANT_FRAGMENT))
        code, out = run(TEST_RUN, worktree / "apps/agentshield", 600)
        mutant = {"cmd": " ".join(TEST_RUN), "variant": "mutant(old 409 handler)", "exit": code}
        if code == 0:
            mutant["error"] = "mutant unexpectedly passed"
            summary["steps"].append(mutant)
            raise SystemExit(json.dumps(summary, indent=1))
        mutant["failure_signature_found"] = FAILURE_SIGNATURE in out
        mutant["forbidden_signatures_found"] = [s for s in FORBIDDEN_SIGNATURES if s in out]
        summary["steps"].append(mutant)
        if not mutant["failure_signature_found"] or mutant["forbidden_signatures_found"]:
            raise SystemExit(json.dumps(summary, indent=1))
        run(["git", "checkout", "--", HANDLER], worktree, 60)
        code, out = run(TEST_RUN, worktree / "apps/agentshield", 600)
        fixed = {"cmd": " ".join(TEST_RUN), "variant": "fixed handler", "exit": code,
                 "passed": code == 0 and ("--- PASS: " + TEST_NAME) in out}
        summary["steps"].append(fixed)
        if not fixed["passed"]:
            raise SystemExit(json.dumps(summary, indent=1))
        summary["result"] = "passed: mutant fails deterministically with the expected signature, fixed handler passes"
        print(json.dumps(summary, indent=1))
        if args.out:
            args.out.write_text(json.dumps(summary, indent=1) + "\n")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root,
                       capture_output=True, timeout=120, check=False)


if __name__ == "__main__":
    main()
