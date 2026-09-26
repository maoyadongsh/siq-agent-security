"""R06：合同版本链只读审计工具。

回答"完整版本化引用链是否闭合"这一问题，并对不闭合的情况给出精确位置：

1. **发出但未建档**：代码里出现 `<family>/v<n>` 字面量，且该 family 在 packages/contracts
   下已有其它版本建档，但没有本版本文件。这是最危险的一类缺口——生产者已按新版本输出，
   消费者若按旧版本严格校验就会拒绝（R02 的 snapshot-comparison v2 即此形态）。
2. **建档但未发出**：某个已建档版本在代码中没有任何字面量引用（仅提示，不作为失败）。
3. **版本导航链接断裂**：合同文档里的 markdown 链接指向不存在的文件。

只读边界：只按固定文本扩展名读取源码与合同文件；不联网、不写库、不执行仓库内任何文件、
不读取 `.private`/`.seed`/`.pem`/`.key` 等敏感后缀，也不读取 `.git`/`node_modules`/.venv
等目录。报告独占创建，已存在即拒绝覆盖。

`--out` 报告表示"本次扫描的引用链状态快照"，不是发布授权，也不代表源码已冻结。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

TOOL_VERSION = "contract-version-chain-audit/0.1.0"
SCHEMA_VERSION = "siq-contract-version-chain-audit/v1"

EXIT_PASS = 0
EXIT_GAPS = 1
EXIT_USAGE = 2
EXIT_REPORT_WRITE_FAILED = 3

SKIP_DIR_SEGMENTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", "dist", "build", "coverage", ".next",
    "var", "backups", ".tmp", "tmp", ".build",
}
SKIP_SUFFIXES = (".private", ".seed", ".pem", ".key", ".p12", ".pfx", ".kdbx", ".pyc")

# 只扫描这些后缀的文本文件；其余一律不读。
TEXT_SUFFIXES = (".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".md", ".json")

SOURCE_ROOTS = ("apps", "edge", "connectors", "packages", "platforms", "scripts")
CONTRACTS_DIR = PurePosixPath("packages/contracts")

# 测试文件可以刻意引用将来版本、非法版本或哨兵版本（例如 v99 表示"未知的未来版本"），
# 因此单独归类，不计入阻塞性缺口，避免把断言当生产者。
TEST_FILE_PATTERNS = (
    re.compile(r"(^|/)tests?/"),
    # Go 的 testdata 目录不参与编译，其中的合同样本是夹具而不是生产者。
    re.compile(r"(^|/)testdata/"),
    re.compile(r"(^|/)test_[^/]*\.py$"),
    re.compile(r"(^|/)[^/]*_test\.(py|go)$"),
    re.compile(r"(^|/)[^/]*\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$"),
    re.compile(r"(^|/)conftest\.py$"),
)

# 构建产物：哈希命名的打包 JS 不是源码，其中的字面量不代表当前生产者。
BUILT_ASSET = re.compile(r"\.(js|mjs|cjs)$")

# `<family>/v<n>`：family 为小写字母数字加连字符，版本为十进制。
VERSION_LITERAL = re.compile(r"""["'`]([a-z0-9][a-z0-9-]*)/v(\d+)["'`]""")
CONTRACT_FILE = re.compile(r"^(?P<family>.+)\.v(?P<version>\d+)\.(?:md|schema\.json)$")
MD_LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)\)")


def _iter_text_files(root: Path, base: PurePosixPath):
    """按固定后缀与排除规则只读枚举；跳过敏感后缀与目录，绝不读取其正文。"""
    directory = root.joinpath(*base.parts)
    if any(root.joinpath(*base.parts[:index]).is_symlink() for index in range(1, len(base.parts) + 1)):
        return
    if not directory.is_dir():
        return
    for current, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(name for name in dirnames
                             if name not in SKIP_DIR_SEGMENTS and not (Path(current) / name).is_symlink())
        for filename in sorted(filenames):
            if not filename.endswith(TEXT_SUFFIXES) or filename.endswith(SKIP_SUFFIXES):
                continue
            if filename == ".env" or filename.startswith(".env."):
                continue
            try:
                if not stat.S_ISREG((Path(current) / filename).lstat().st_mode):
                    continue
            except OSError:
                continue
            relative = Path(current).relative_to(root).joinpath(filename)
            posix = PurePosixPath(relative.as_posix())
            # 跳过打包进二进制的 assets 目录下的构建 JS。
            if "assets" in posix.parts[:-1] and BUILT_ASSET.search(posix.name):
                continue
            yield posix


def is_test_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in TEST_FILE_PATTERNS)


def _read_text(path: Path) -> str | None:
    try:
        if any(parent.is_symlink() for parent in path.parents) or not stat.S_ISREG(path.lstat().st_mode):
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def collect_documented(root: Path) -> dict:
    """已建档版本：family -> {version -> [相对路径]}。"""
    documented: dict[str, dict[int, list[str]]] = {}
    for relative in _iter_text_files(root, CONTRACTS_DIR):
        match = CONTRACT_FILE.match(relative.name)
        if match is None:
            continue
        documented.setdefault(match.group("family"), {}).setdefault(
            int(match.group("version")), []).append(str(relative))
    return documented


def collect_emitted(root: Path) -> dict:
    """代码中出现的版本字面量：family/vN -> [相对路径]。"""
    emitted: dict[tuple[str, int], list[str]] = {}
    for base in SOURCE_ROOTS:
        for relative in _iter_text_files(root, PurePosixPath(base)):
            if relative.parts[:2] == ("packages", "contracts"):
                continue
            text = _read_text(root.joinpath(*relative.parts))
            if text is None:
                continue
            for match in VERSION_LITERAL.finditer(text):
                key = (match.group(1), int(match.group(2)))
                location = emitted.setdefault(key, [])
                if str(relative) not in location:
                    location.append(str(relative))
    return emitted


def broken_navigation_links(root: Path) -> list[dict]:
    """合同文档内 markdown 链接指向不存在的文件**或目录**即断裂（外部 URL 与锚点不算）。"""
    broken = []
    for relative in _iter_text_files(root, CONTRACTS_DIR):
        if relative.suffix != ".md":
            continue
        text = _read_text(root.joinpath(*relative.parts))
        if text is None:
            continue
        for match in MD_LINK.finditer(text):
            target = match.group("target")
            if "://" in target or target.startswith("#"):
                continue
            resolved = root.joinpath(*relative.parent.joinpath(target).parts)
            if not resolved.exists():
                broken.append({"contract": str(relative), "link": target})
    return broken


def load_aliases(path: Path | None, root: Path) -> tuple[dict, list[str]]:
    """别名表：`family/vN` -> 实际承载该版本语义的合同文件（跨文件名建档）。

    返回 (别名映射, 失效别名列表)。别名是**显式声明**，不是猜测：只为"语义确实已建档、
    只是文件名 family 不同"的情况登记，且目标文件必须真实存在于仓库内。
    """
    if path is None:
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"别名表不可读或不是合法 JSON：{exc}") from None
    aliases = data.get("aliases")
    if not isinstance(aliases, dict):
        raise TypeError("别名表缺少 aliases 对象")
    stale = [key for key, target in aliases.items() if not _alias_target_ok(root, target)]
    return aliases, sorted(stale)


def _alias_target_ok(root: Path, target: object) -> bool:
    """别名目标必须是仓库内真实存在的合同文件（不接受 URL、绝对路径或目录）。"""
    if not isinstance(target, str) or not target:
        return False
    candidate = PurePosixPath(target)
    if candidate.is_absolute() or "://" in target or ".." in candidate.parts:
        return False
    resolved = root.joinpath(*candidate.parts)
    return (candidate.parts[:2] == ("packages", "contracts")
            and not any(root.joinpath(*candidate.parts[:index]).is_symlink()
                        for index in range(1, len(candidate.parts) + 1))
            and resolved.is_file())


def audit(root: Path, aliases: dict | None = None) -> dict:
    aliases = aliases or {}
    documented = collect_documented(root)
    emitted = collect_emitted(root)

    undocumented, test_only = [], []
    for (family, version), locations in sorted(emitted.items()):
        if family not in documented:
            # 该 family 在 packages/contracts 下没有任何建档：不是本工具的管辖范围
            # （例如随源码分发的协议版本），不计为缺口。
            continue
        if version in documented[family] or f"{family}/v{version}" in aliases:
            continue
        production = [item for item in locations if not is_test_path(item)]
        if production:
            undocumented.append({"family": family, "version": version, "locations": production,
                                 "test_locations": [i for i in locations if is_test_path(i)]})
        else:
            test_only.append({"family": family, "version": version, "locations": locations})

    used = set(emitted)
    documented_unused = [
        {"family": family, "version": version, "path": path}
        for family, versions in sorted(documented.items())
        for version, paths in sorted(versions.items())
        for path in paths
        if (family, version) not in used
    ]

    broken = broken_navigation_links(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "contracts_dir": str(CONTRACTS_DIR),
        "documented_family_count": len(documented),
        "documented_version_count": sum(len(versions) for versions in documented.values()),
        "emitted_version_count": len(emitted),
        "alias_count": len(aliases),
        "undocumented_versions": undocumented,
        "test_only_version_references": test_only,
        "documented_but_unemitted": documented_unused,
        "broken_navigation_links": broken,
        "closed_version_chain": not undocumented,
        "note": ("本报告是本次扫描的引用链状态快照，不是发布授权，也不代表源码已冻结；"
                 "'test_only_version_references'、'documented_but_unemitted' 与别名仅作提示，"
                 "不使审计失败；只有 'undocumented_versions'（生产代码发出但无建档、也无显式别名）"
                 "构成缺口。"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="合同版本链只读审计（R06）")
    parser.add_argument("--repo", required=True, help="仓库根路径")
    parser.add_argument("--out", required=True, help="报告 JSON 输出路径（独占创建，已存在即拒绝）")
    parser.add_argument("--aliases", help="显式别名表 JSON：{\"aliases\": {\"family/vN\": \"path\"}}")
    args = parser.parse_args(argv)

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"仓库路径不存在：{root}", file=sys.stderr)
        return EXIT_USAGE

    try:
        aliases, stale_aliases = load_aliases(Path(args.aliases) if args.aliases else None, root)
    except (TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    if stale_aliases:
        print(f"无效别名（目标不是仓库内合同文件）：{stale_aliases}", file=sys.stderr)
        return EXIT_USAGE

    report = audit(root, aliases)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    out_path = Path(args.out)
    try:
        # 独占创建：不覆盖已有报告，避免把上一次的结论悄悄换成这一次的。
        with open(out_path, "x", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    except FileExistsError:
        print(f"报告已存在，拒绝覆盖：{out_path}", file=sys.stderr)
        return EXIT_REPORT_WRITE_FAILED
    except OSError as exc:
        print(f"报告写入失败：{exc}", file=sys.stderr)
        return EXIT_REPORT_WRITE_FAILED

    print(f"undocumented_versions={len(report['undocumented_versions'])} "
          f"broken_navigation_links={len(report['broken_navigation_links'])} "
          f"documented_but_unemitted={len(report['documented_but_unemitted'])}")
    return EXIT_PASS if report["closed_version_chain"] else EXIT_GAPS


if __name__ == "__main__":
    sys.exit(main())
