"""CL-01-SOURCE-FREEZE-PREFLIGHT：源码冻结前只读工作树盘点工具。

对指定 Git 仓库做只读盘点：HEAD、分支、已跟踪改动、未跟踪条目、冲突状态。
默认只枚举路径与状态，不读取文件正文；仅对用户显式提供的允许清单中的
相对路径计算普通文件 SHA-256。报告表示"工作树审阅状态快照"，与
scripts/release 的 siq-release-source-inventory/v1（已提交源码身份）
是两种不同合同，本工具不生成也不替代发行来源清单。

边界：signed/installable/published 恒为 false；工具退出 0 仅表示
"所列文件快照检查通过"，不是发布授权，也不是源码已冻结的结论。

所有 Git 调用均为只读命令且带 --no-optional-locks，不写索引；
不使用 shell；不执行仓库内任何文件。
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

TOOL_VERSION = "source-freeze-preflight/0.1.0"
SCHEMA_VERSION = "siq-source-freeze-preflight/v1"
DEFAULT_MAX_CONTENT_BYTES = 1024 * 1024

EXIT_PASS = 0
EXIT_BLOCKED = 1
EXIT_USAGE = 2
EXIT_REPORT_WRITE_FAILED = 3
EXIT_GIT_FAILED = 4

SNAPSHOT_NOTE = (
    "本工具在扫描前后各比对一次 Git 状态与文件身份（dev/ino/大小/mtime），"
    "但这不是原子文件系统快照，不能消除所有并发写窗口。"
)

# 只做排除标记（不读取、不摘要、不打印正文）的路径规则。
SENSITIVE_DIR_SEGMENTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "backups", "var",
}
SENSITIVE_SUFFIXES = (".private", ".seed", ".pem", ".key", ".p12", ".pfx", ".kdbx")


class GitError(RuntimeError):
    pass


def run_git(repo: Path, args: list[str]) -> bytes:
    proc = subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=str(repo), capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise GitError(f"git {args[0]} failed (exit {proc.returncode}); no report produced")
    return proc.stdout


def repo_toplevel(repo: Path) -> Path:
    out = run_git(repo, ["rev-parse", "--show-toplevel"])
    text = out.decode("utf-8", errors="surrogateescape").removesuffix("\n")
    return Path(text).resolve()


def classify_sensitive(rel_posix: str) -> str | None:
    segments = rel_posix.split("/")
    for seg in segments[:-1]:
        if seg in SENSITIVE_DIR_SEGMENTS:
            return f"sensitive_directory:{seg}"
    name = segments[-1]
    if name == ".env":
        return "sensitive_file:.env"
    if name.startswith(".env.") and name != ".env.example":
        return "sensitive_file:.env-variant"
    for suffix in SENSITIVE_SUFFIXES:
        if name.endswith(suffix):
            return f"sensitive_suffix:{suffix}"
    return None


def parse_status_z(raw: bytes) -> list[dict]:
    entries: list[dict] = []
    tokens = raw.decode("utf-8", errors="surrogateescape").split("\0")
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if not token:
            continue
        entry = {"code": token[:2], "path": token[3:]}
        if entry["code"][0] in "RC":
            entry["orig_path"] = tokens[i] if i < len(tokens) else ""
            i += 1
        entries.append(entry)
    return entries


def parse_unmerged_z(raw: bytes) -> list[str]:
    paths: list[str] = []
    for record in raw.decode("utf-8", errors="surrogateescape").split("\0"):
        if not record:
            continue
        _, _, path = record.partition("\t")
        if path and path not in paths:
            paths.append(path)
    return paths


def git_state(repo: Path) -> dict:
    head: str | None
    try:
        head = run_git(repo, ["rev-parse", "HEAD"]).decode("ascii").strip()
    except GitError:
        head = None
    branch = run_git(repo, ["branch", "--show-current"]).decode("utf-8", errors="surrogateescape").strip()
    status_raw = run_git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    unmerged_raw = run_git(repo, ["ls-files", "-z", "--unmerged"])
    return {
        "head_commit": head,
        "branch": branch or None,
        "status_entries": parse_status_z(status_raw),
        "conflict_paths": parse_unmerged_z(unmerged_raw),
    }


def validate_allowlist_path(rel: str) -> PurePosixPath | None:
    if not rel or "\0" in rel or "\\" in rel or rel.startswith(("/", "~")):
        return None
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts or not pure.parts:
        return None
    return pure


def lstat_no_symlink(repo: Path, pure: PurePosixPath):
    """逐段 lstat，任一组件是符号链接即拒绝；返回 (最终 os.stat_result, None) 或 (None, 原因)。"""
    current = repo
    for seg in pure.parts:
        current = current / seg
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            return None, "missing"
        except OSError:
            return None, "unreadable"
        if stat.S_ISLNK(st.st_mode):
            return None, "symlink_rejected"
    if not stat.S_ISREG(st.st_mode):
        return None, "nonregular_rejected"
    return st, None


def verify_allowlist_file(repo: Path, rel: str, max_bytes: int) -> dict:
    """内容级核验：仅对普通文件计算 SHA-256；敏感路径一律排除标记，不读取。"""
    entry: dict = {"path": rel, "status": None, "sha256": None, "size_bytes": None,
                   "mtime_ns": None, "dev": None, "ino": None}
    pure = validate_allowlist_path(rel)
    if pure is None:
        entry["status"] = "invalid_path_rejected"
        return entry
    entry["path"] = pure.as_posix()
    reason = classify_sensitive(entry["path"])
    if reason:
        entry["status"] = "sensitive_excluded"
        entry["exclusion_reason"] = reason
        return entry
    st, reject = lstat_no_symlink(repo, pure)
    if reject:
        entry["status"] = reject
        return entry
    entry["size_bytes"] = st.st_size
    entry["mtime_ns"] = st.st_mtime_ns
    entry["dev"] = st.st_dev
    entry["ino"] = st.st_ino
    if st.st_size > max_bytes:
        entry["status"] = "too_large_unverified"
        return entry
    identity_before = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    directory_fd = None
    file_fd = None
    try:
        # 按目录描述符逐段打开；lstat 只是预检，不能承担防符号链接竞态的职责。
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_fd = os.open(repo, directory_flags)
        for part in pure.parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(pure.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                          dir_fd=directory_fd)
        opened = os.fstat(file_fd)
        opened_identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            entry["status"] = "nonregular_rejected"
            return entry
        if opened_identity != identity_before:
            entry["status"] = "changed_during_read"
            return entry
        chunks = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(file_fd, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            entry["status"] = "too_large_unverified"
            return entry
        data = b"".join(chunks)
        descriptor_after = os.fstat(file_fd)
        st_after = os.lstat(repo / pure)
    except (OSError, AttributeError) as exc:
        entry["status"] = "symlink_rejected" if getattr(exc, "errno", None) == errno.ELOOP else "unreadable"
        return entry
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)
    identity_after = (st_after.st_dev, st_after.st_ino, st_after.st_size, st_after.st_mtime_ns)
    descriptor_identity = (descriptor_after.st_dev, descriptor_after.st_ino,
                           descriptor_after.st_size, descriptor_after.st_mtime_ns)
    if identity_before != identity_after or identity_before != descriptor_identity:
        entry["status"] = "changed_during_read"
    else:
        entry["status"] = "verified"
        entry["sha256"] = hashlib.sha256(data).hexdigest()
    return entry


def build_report(repo: Path, allowlist_source: str | None, allowlist_sha: str | None,
                 max_bytes: int, before: dict, after: dict,
                 allowlist_results: list[dict]) -> dict:
    changed: dict[str, str] = {}
    for entry in before["status_entries"]:
        changed[entry["path"]] = entry["code"]
        if entry.get("orig_path"):
            changed.setdefault(entry["orig_path"], f"{entry['code']}(orig)")
    verified_paths = {r["path"] for r in allowlist_results if r["status"] == "verified"}
    excluded = [{"path": r["path"], "reason": r.get("exclusion_reason", "sensitive")}
                for r in allowlist_results if r["status"] == "sensitive_excluded"]
    excluded_paths = {r["path"] for r in excluded}
    # 状态枚举里命中敏感规则的路径同样只做排除标记
    for path in changed:
        reason = classify_sensitive(path)
        if reason and path not in excluded_paths and path not in verified_paths:
            excluded.append({"path": path, "reason": reason})
            excluded_paths.add(path)
    missing = [r["path"] for r in allowlist_results if r["status"] == "missing"]
    unreviewed = sorted(p for p in changed
                        if p not in verified_paths and p not in excluded_paths)
    unstable_files = [r["path"] for r in allowlist_results if r["status"] == "changed_during_read"]
    scan_stable = before == after
    conflicts = sorted(set(before["conflict_paths"]))

    blocking: list[str] = []
    if before["head_commit"] is None:
        blocking.append("head_unavailable")
    if unreviewed:
        blocking.append(f"unreviewed_paths:{len(unreviewed)}")
    if excluded:
        blocking.append(f"excluded_paths_require_review:{len(excluded)}")
    if conflicts:
        blocking.append(f"unresolved_conflicts:{len(conflicts)}")
    if not scan_stable:
        blocking.append("worktree_changed_during_scan")
    if unstable_files:
        blocking.append(f"files_changed_during_read:{len(unstable_files)}")
    if missing:
        blocking.append(f"allowlist_missing:{len(missing)}")
    unverified = [r["path"] for r in allowlist_results
                  if r["status"] in ("too_large_unverified", "unreadable",
                                     "invalid_path_rejected", "symlink_rejected",
                                     "nonregular_rejected")]
    if unverified:
        blocking.append(f"allowlist_unverified:{len(unverified)}")

    tracked_changes = sum(1 for e in before["status_entries"] if e["code"] != "??")
    untracked = sum(1 for e in before["status_entries"] if e["code"] == "??")
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo),
        "head_commit": before["head_commit"],
        "branch": before["branch"],
        "conclusion": "blocked" if blocking else "snapshot_check_passed",
        "signed": False,
        "installable": False,
        "published": False,
        "interpretation": (
            "工具通过仅表示所列文件快照检查通过，不是发布授权，"
            "不表示源码已冻结，也不是发行来源清单。"
        ),
        "worktree": {
            "tracked_changes": tracked_changes,
            "untracked_entries": untracked,
            "unresolved_conflicts": len(conflicts),
            "status_entries": before["status_entries"],
        },
        "allowlist": {
            "source": allowlist_source,
            "sha256": allowlist_sha,
            "max_content_bytes": max_bytes,
            "requested": len(allowlist_results),
            "verified": len(verified_paths),
            "unverified": len(unverified),
            "excluded": len(excluded_paths),
            "missing": len(missing),
            "results": allowlist_results,
        },
        "checked_files": [r for r in allowlist_results if r["status"] == "verified"],
        "excluded": excluded,
        "unreviewed": unreviewed,
        "missing": missing,
        "conflicts": conflicts,
        "unverified": unverified,
        "unstable": {
            "scan_stable": scan_stable,
            "files": unstable_files,
            "note": SNAPSHOT_NOTE,
        },
        "blocking_reasons": blocking,
    }


def load_allowlist(path: Path) -> tuple[list[str], str]:
    data = path.read_bytes()
    lines = []
    for line in data.decode("utf-8", errors="surrogateescape").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            lines.append(text)
    return lines, hashlib.sha256(data).hexdigest()


def write_report_exclusive(out_path: Path, report: dict) -> None:
    parent_fd = None
    try:
        absolute = out_path.absolute()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        parent_fd = os.open(absolute.anchor, flags)
        for part in absolute.parts[1:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(absolute.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
    except FileExistsError:
        raise RuntimeError(f"report path already exists; refusing to overwrite: {out_path}") from None
    except (OSError, AttributeError):
        raise RuntimeError("report directory unavailable or unsafe") from None
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        raise RuntimeError(f"failed to write report ({exc.__class__.__name__}); report incomplete") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="只读源码冻结前工作树盘点（路径级默认，内容级仅限显式允许清单）",
    )
    parser.add_argument("--repo", required=True, help="Git 仓库路径")
    parser.add_argument("--allowlist", help="相对路径允许清单文件（每行一个仓库相对路径）")
    parser.add_argument("--out", required=True, help="报告 JSON 输出路径（必须位于仓库外，独占创建）")
    parser.add_argument("--max-content-bytes", type=int, default=DEFAULT_MAX_CONTENT_BYTES,
                        help=f"允许清单文件内容核验大小上限（默认 {DEFAULT_MAX_CONTENT_BYTES}）")
    args = parser.parse_args(argv)

    if args.max_content_bytes < 1:
        parser.error("--max-content-bytes must be positive")
    repo_arg = Path(args.repo)
    out_path = Path(args.out)
    try:
        repo = repo_toplevel(repo_arg)
        out_resolved = out_path.resolve()
        if out_resolved == repo or repo in out_resolved.parents:
            print("error: report output path must be outside the repository", file=sys.stderr)
            return EXIT_REPORT_WRITE_FAILED
        allowlist_paths, allowlist_sha = (None, None)
        if args.allowlist:
            allowlist_paths, allowlist_sha = load_allowlist(Path(args.allowlist))

        before = git_state(repo)
        results = [verify_allowlist_file(repo, rel, args.max_content_bytes)
                   for rel in (allowlist_paths or [])]
        after = git_state(repo)
        # Git 的 M/?? 状态不反映内容变化；在结束点重新核验已摘要文件。
        for result in results:
            if result["status"] != "verified":
                continue
            checked_again = verify_allowlist_file(repo, result["path"], args.max_content_bytes)
            if checked_again != result:
                result["status"] = "changed_during_read"
                result["sha256"] = None
        report = build_report(repo, args.allowlist, allowlist_sha,
                              args.max_content_bytes, before, after, results)
        try:
            write_report_exclusive(out_path, report)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_REPORT_WRITE_FAILED
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED
    except (OSError, ValueError, RuntimeError):
        print("error: preflight input or filesystem unavailable", file=sys.stderr)
        return EXIT_USAGE

    summary = (f"preflight report written: {out_path} conclusion={report['conclusion']} "
               f"tracked_changes={report['worktree']['tracked_changes']} "
               f"untracked={report['worktree']['untracked_entries']} "
               f"conflicts={report['worktree']['unresolved_conflicts']}")
    print(summary)
    return EXIT_PASS if report["conclusion"] == "snapshot_check_passed" else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
