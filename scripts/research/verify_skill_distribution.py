#!/usr/bin/env python3
"""Compare static Skill trees as data; this proves distribution equality only.

No candidate code is executed or imported. Symlinks and special files are refused,
and observed changes during reads fail closed. This is not a race-free boundary
against a hostile process running as the same user. Empty directories do not affect
file equality, but all entries consume a traversal budget of twice max_files.
"""

import argparse
import hashlib
import json
import os
import stat
import sys
import unicodedata
from pathlib import Path


class DistributionError(ValueError):
    """A categorized failure containing only a validated relative path, if any."""

    def __init__(self, category, path=None):
        self.category = category
        self.path = path
        super().__init__(category + (": " + path if path else ""))


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _check_type(info, relative):
    if stat.S_ISLNK(info.st_mode):
        raise DistributionError("symlink", relative)
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise DistributionError("nonregular", relative)


def _read_file(path, relative, before, remaining):
    if before.st_size > remaining:
        raise DistributionError("byte_limit", relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
            raise DistributionError("tree_changed", relative)
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, remaining - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > remaining:
                raise DistributionError("byte_limit", relative)
            digest.update(chunk)
        if (size != before.st_size or _identity(os.fstat(descriptor)) != _identity(before)
                or _identity(path.lstat()) != _identity(before)):
            raise DistributionError("tree_changed", relative)
        return {"path": relative, "sha256": digest.hexdigest(), "bytes": size,
                "executable_bits": before.st_mode & 0o111 if os.name == "posix" else None}
    finally:
        os.close(descriptor)


def snapshot_tree(path, *, max_files=2048, max_bytes=32 * 1024 * 1024, max_depth=16):
    """Return deterministic file metadata; reject unsafe, changing or oversized trees.

    Depth counts relative path components (root files have depth 1). POSIX execute
    bits are compared individually; they are null on other operating systems.
    Root symlinks are rejected, while symlink ancestors such as macOS /tmp work.
    """
    limits = ((max_files, 1), (max_bytes, 0), (max_depth, 1))
    if any(type(value) is not int or value < minimum for value, minimum in limits):
        raise DistributionError("invalid_limit")
    root = Path(path)
    files = []
    entries_seen = 0
    total_bytes = 0

    def walk(directory, parts, before):
        nonlocal entries_seen, total_bytes
        entries = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                entries_seen += 1
                if entries_seen > max_files * 2:
                    raise DistributionError("entry_limit")
                if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in entry.name):
                    raise DistributionError("invalid_path")
                if len(parts) + 1 > max_depth:
                    raise DistributionError("depth_limit")
                entries.append(entry.name)
        for name in sorted(entries):
            child_parts = (*parts, name)
            relative = "/".join(child_parts)
            child = directory / name
            info = child.lstat()
            _check_type(info, relative)
            if stat.S_ISDIR(info.st_mode):
                walk(child, child_parts, info)
            else:
                if len(files) >= max_files:
                    raise DistributionError("file_limit", relative)
                item = _read_file(child, relative, info, max_bytes - total_bytes)
                total_bytes += item["bytes"]
                files.append(item)
        if _identity(directory.lstat()) != _identity(before):
            raise DistributionError("tree_changed", "/".join(parts) or None)

    try:
        info = root.lstat()
        _check_type(info, None)
        if not stat.S_ISDIR(info.st_mode):
            raise DistributionError("not_directory")
        walk(root, (), info)
    except OSError as error:
        raise DistributionError("io_error") from error
    files.sort(key=lambda item: item["path"])
    if not any(item["path"] == "SKILL.md" for item in files):
        raise DistributionError("missing_skill")
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {"files": files, "file_count": len(files), "total_bytes": total_bytes,
            "tree_sha256": hashlib.sha256(encoded).hexdigest()}


def verify_distribution(source, installed):
    """Return a redacted comparison report; no manifest supplied by a tree is trusted."""
    report = {"scope": "distribution_only", "result": "failed", "source": None,
              "installed": None, "differences": [], "errors": []}
    for label, path in (("source", source), ("installed", installed)):
        try:
            report[label] = snapshot_tree(path)
        except DistributionError as error:
            item = {"tree": label, "category": error.category}
            if error.path:
                item["path"] = error.path
            report["errors"].append(item)
    if report["errors"]:
        return report
    expected = {item["path"]: item for item in report["source"]["files"]}
    actual = {item["path"]: item for item in report["installed"]["files"]}
    for path in sorted(expected.keys() | actual.keys()):
        category = None
        if path not in actual:
            category = "missing"
        elif path not in expected:
            category = "extra"
        elif expected[path] != actual[path]:
            category = "changed"
        if category:
            report["differences"].append({"path": path, "category": category})
    if not report["differences"]:
        report["result"] = "passed"
    return report


def _check_output(output, inputs):
    try:
        destination = output.resolve()
        if any(destination.is_relative_to(path.resolve()) for path in inputs):
            raise DistributionError("output_in_input")
        if os.path.lexists(output):
            raise DistributionError("output_exists")
    except (OSError, RuntimeError) as error:
        raise DistributionError("output_path_error") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inputs = (args.source, args.installed)
        _check_output(args.out, inputs)
        report = verify_distribution(*inputs)
        _check_output(args.out, inputs)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(args.out, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except DistributionError as error:
        print("distribution_only: " + error.category, file=sys.stderr)
        return 2
    except FileExistsError:
        print("distribution_only: output_exists", file=sys.stderr)
        return 2
    except OSError:
        print("distribution_only: output_io_error", file=sys.stderr)
        return 2
    categories = sorted({item["category"] for item in report["errors"] + report["differences"]})
    print("distribution_only: " + report["result"] + (" (" + ", ".join(categories) + ")" if categories else ""))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
