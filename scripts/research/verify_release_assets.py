#!/usr/bin/env python3
"""Reject release bytes that differ from the reviewed publication record."""

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(directory, record, tag, source_sha):
    if not re.fullmatch(r"research-v[0-9]+\.[0-9]+\.[0-9]+-rc\.[1-9][0-9]*", tag):
        raise ValueError("invalid research release tag")
    if record["tag"] != tag or record["tag_source_sha"] != source_sha:
        raise ValueError("release tag/source differs from reviewed record")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("invalid source commit")
    archive = f"siq-agent-security-{tag}.tar.gz"
    expected = {item["name"]: item for item in record["fresh_download_verified"]}
    if set(expected) != {archive, "SOURCE-INFO.json"} or len(record["fresh_download_verified"]) != 2:
        raise ValueError("record must cover exactly the source archive and metadata")
    for name in [archive, "SOURCE-INFO.json", "SHA256SUMS"]:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing or nonregular release asset: " + name)
        if name in expected:
            item = expected[name]
            if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
                raise ValueError("asset differs from reviewed publication: " + name)
    checksums = "".join(f'{expected[name]["sha256"]}  {name}\n' for name in [archive, "SOURCE-INFO.json"])
    if (directory / "SHA256SUMS").read_bytes() != checksums.encode():
        raise ValueError("checksum manifest differs from reviewed publication")
    info = json.loads((directory / "SOURCE-INFO.json").read_text())
    if (info["version"] != tag or info["source_sha"] != source_sha
            or info["archive"] != archive or info["archive_sha256"] != expected[archive]["sha256"]):
        raise ValueError("source metadata identity mismatch")
    return {"tag": tag, "source_sha": source_sha, "sha256sums_sha256": digest(directory / "SHA256SUMS")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, json.loads(args.record.read_text()), args.tag, args.source_sha)))


if __name__ == "__main__":
    main()
