#!/usr/bin/env python3
"""Seal existing model captures and export only checksum-listed evidence."""
import argparse
import json
from pathlib import Path

from common import safe_path, sha256, utc_now, write_json


def export(run, destination, secrets):
    sums = json.loads((run / "checksums.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    if sha256(run / "checksums.json") != manifest["checksums_sha256"]:
        raise ValueError("checksum manifest changed")
    payloads = {}
    for relative in [*sums, "checksums.json", "manifest.json"]:
        if any(part in {"credentials", "state-private", "daemon-state", ".env"} for part in Path(relative).parts):
            raise ValueError("private runtime path is not exportable")
        source = safe_path(run, relative)
        content = source.read_bytes()
        if relative in sums and sha256(source) != sums[relative]:
            raise ValueError("payload changed before export")
        if any(value in content for value in secrets):
            raise ValueError("credential found; export stopped")
        payloads[relative] = content
    # Validate every payload before writing any of this export.
    for relative, content in payloads.items():
        target = safe_path(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError("refusing to overwrite exported evidence")
        else:
            with target.open("xb") as stream:
                stream.write(content)
    index = destination / "export-index.json"
    if not index.exists():
        write_json(index, {"source_run": run.name, "exported_at": utc_now(), "publication": "local_only",
                           "policy": "checksum allowlist; synthetic case captures only; no state or credentials",
                           "redaction": "none; byte-for-byte copies", "files": {
                               name: sha256(destination / name) for name in payloads}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    secrets = [p.read_bytes().strip() for p in (campaign / "private/credentials").glob("*.key")]
    secrets = [value for value in secrets if value]
    names = ("B-five-samples-001", "step5-utility-smoke-001", "step5-utility-smoke-002", "local-utility-smoke-001")
    for name in names:
        run = campaign / "private/runs" / name
        protocol = json.loads((run / "protocol.json").read_text())
        manifest = run / "manifest.json"
        if not manifest.exists():
            # A later seal does not pretend to be a pre-execution checkpoint.
            write_json(manifest, {"schema_version": "siq-model-smoke-manifest/v1",
                                 "checksums_sha256": sha256(run / "checksums.json"),
                                 "protocol_sha256": sha256(run / "protocol.json"),
                                 "allocated": len(protocol["allocation"]), "sealed_at": utc_now(),
                                 "relationship": "author_run", "trust": "author_local",
                                 "seal_timing": "post_capture; original checksums and payloads preserved"})
        anchor_path = campaign / "inventory/anchors" / (name + ".json")
        anchor = {"manifest_sha256": sha256(manifest), "custody": "author_local", "run_id": name}
        if anchor_path.exists():
            if json.loads(anchor_path.read_text()) != anchor:
                raise ValueError("existing local anchor differs")
        else:
            write_json(anchor_path, anchor)
        export(run, campaign / "data" / name, secrets)
        print(json.dumps(anchor))


if __name__ == "__main__":
    main()
