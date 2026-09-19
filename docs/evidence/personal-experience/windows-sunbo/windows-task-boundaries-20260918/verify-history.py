import argparse
import base64
import hashlib
import json
import os
import pathlib
import subprocess

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

parser = argparse.ArgumentParser(description="Read-only verification of a retained native boundary fixture")
parser.add_argument("case", type=pathlib.Path, help="private fixture directory containing source.exe and state/")
args = parser.parse_args()
CASE = args.case.resolve()
STATE = CASE / "state"
seed = STATE / "keys/signing.seed"
before = (seed.stat().st_size, seed.stat().st_mtime_ns)
excluded = {
    "SIQ_AGENT_SECURITY_STATE_DIR", "AGENTSHIELD_STATE_DIR",
    "SIQ_AGENT_SECURITY_SIGNING_KEY_SEED", "AGENTSHIELD_SIGNING_KEY_SEED",
}
env = {k: v for k, v in os.environ.items() if k.upper() not in excluded}
env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(STATE)
probe = subprocess.run([str(CASE / "source.exe"), "pubkey"], env=env, capture_output=True, timeout=30)
assert probe.returncode == 0 and not probe.stderr
assert before == (seed.stat().st_size, seed.stat().st_mtime_ns)
public = base64.b64decode(probe.stdout.strip(), validate=True)
key = Ed25519PublicKey.from_public_bytes(public)


def verify(document):
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    key.verify(bytes.fromhex(document["signature"]), canonical)


grant_files = sorted((STATE / "grants").glob("*.json"))
assert len(grant_files) == 2
grants = [json.loads(path.read_bytes()) for path in grant_files]
for document in grants:
    verify(document)
assert grants[0]["status"] == "pending_approval" and grants[1]["status"] == "revoked"
assert grant_files[1].name.endswith(".1.json")
plans = []
for path in (STATE / "service-switches").glob("*.json"):
    if path.name.endswith(".done.json"):
        continue
    raw = path.read_bytes()
    plan = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == path.stem
    assert path.with_name(path.stem + ".done.json").read_bytes() == raw
    verify(plan)
    for side in ("source", "target"):
        verify(plan[side + "_record"])
        assert hashlib.sha256(plan[side + "_xml"].encode()).hexdigest() == plan[side + "_record"]["xml_sha256"]
    plans.append(plan)
assert len(plans) == 2
assert plans[0]["source_xml"] == plans[1]["target_xml"]
assert plans[0]["target_xml"] == plans[1]["source_xml"]
audit_count = revoke_count = 0
for path in (STATE / "commits").glob("*.prepare.json"):
    commit = json.loads(path.read_bytes())["commit"]
    audit_path = STATE / "commit-audit" / (path.name.removesuffix(".prepare.json") + ".json")
    audit = json.loads(audit_path.read_bytes())
    assert commit["audit"] == audit
    assert audit["target"] == commit["grant"]["grant_id"]
    audit_count += 1
    revoke_count += audit["event"] == "grant_revoke"
assert audit_count == 2 and revoke_count == 1
business_paths = [path for name in ("admissions", "grants", "policies", "commits")
                  for path in (STATE / name).rglob("*") if not path.is_dir()]
assert all(path.is_file() and not path.is_symlink() for path in business_paths)
business_files = len(business_paths)
assert business_files == 9
result = {
    "artifact_source_sha": "319d3ac4cf4f56a17f212ed45a927e7e29957490",
    "public_key_sha256": hashlib.sha256(public).hexdigest(),
    "private_key_not_exposed": True,
    "private_key_metadata_unchanged": True,
    "grant_versions": 2,
    "initial_grant_status": "pending_approval",
    "latest_grant_status": "revoked",
    "latest_revision": 1,
    "grant_signatures_verified_by_python": True,
    "task_switch_signatures_verified_by_python": True,
    "task_record_signatures_verified_by_python": True,
    "completed_switches": 2,
    "exact_reverse_pair": True,
    "commit_audit_records": 2,
    "matching_revocation_audits": 1,
    "business_files": business_files,
    "coverage_limit": "pending_approval declaration revoked via real CLI; no previously deployed effective permission asserted",
}
print(json.dumps(result, indent=2))
