"""Offline, read-only verification of retained Hermes r6 evidence. No host imports."""
import base64
import copy
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf8").splitlines() if line]


def require(condition, code):
    if not condition:
        raise AssertionError(code)


def main(root):
    report = read(root / "report.json")
    plan = read(root / "plan.json")
    require(report["plan"] == plan and report["status"] == "pass", "run-plan-and-status")
    # Only derive the verification key in memory; no seed, token, or hash thereof is output.
    public = Ed25519PrivateKey.from_private_bytes(base64.b64decode(
        (root / "state/keys/signing.seed").read_bytes().strip(), validate=True
    )).public_key()
    verified = []

    def signed(doc, label):
        unsigned = {k: v for k, v in doc.items() if k != "signature"}
        public.verify(bytes.fromhex(doc["signature"]), canon(unsigned))
        verified.append(label)
        return unsigned

    for label, entry in plan["files"].items():
        raw = Path(entry["path"]).read_bytes()
        require(len(raw) == entry["bytes"] and sha(raw) == entry["sha256"], "pinned-file-" + label)
    source = Path(plan["candidate_source"])
    source_hashes = {}
    for subdir in ("apps/agentshield", "adapters/runtime/hermes-agentshield", "packages/contracts"):
        for path in sorted((source / subdir).rglob("*")):
            if path.is_file() and path.suffix in (".go", ".py", ".json", ".yaml", ".mod", ".sum"):
                source_hashes[path.relative_to(source).as_posix()] = sha(path.read_bytes())
    require(len(source_hashes) == plan["source_files"] and sha(json.dumps(source_hashes, sort_keys=True).encode()) == plan["source_files_digest"], "frozen-source")

    receipts = []
    for path in sorted((root / "state/receipts/local").glob("*.jsonl")):
        receipts.extend(lines(path))
    previous = "0" * 64
    for seq, receipt in enumerate(receipts):
        require(receipt["seq"] == seq and receipt["prev_hash"] == previous, "receipt-link-" + str(seq))
        digest = sha(canon({k: v for k, v in receipt.items() if k not in ("hash", "sig")}))
        require(receipt["hash"] == digest, "receipt-hash-" + str(seq))
        public.verify(bytes.fromhex(receipt["sig"]), digest.encode())
        previous = digest
    checkpoint = read(root / "state/checkpoints/local.json")
    signed(checkpoint, "checkpoint")
    require(checkpoint["tip_hash"] == previous and checkpoint["max_seq"] == len(receipts) - 1, "checkpoint-tip")

    identity = read(next((root / "state/runtime-identities").glob("*.json")))
    identity_unsigned = signed(identity, "identity")
    identity_digest = sha(canon(identity_unsigned))
    revocation = read(next((root / "state/runtime-identity-revocations").glob("*.json")))
    signed(revocation, "identity-revocation")
    require(revocation["identity_id"] == identity["identity_id"] and revocation["identity_digest"] == identity_digest, "revocation-reference")
    grants = [read(path) for path in (root / "state/grants").glob("*.json")]
    for index, grant in enumerate(grants):
        signed(grant, "grant-revision-" + str(index))
    grant = next(g for g in reversed(grants) if g.get("status") in ("deployed", "effective"))
    permission = copy.deepcopy(grant)
    for key in ("status", "effective_readback", "signature", "signing_schema"):
        permission.pop(key, None)
    for fact in permission["facts"]:
        if fact["domain"] == "tool":
            if fact.get("state") in ("declared", "effective"):
                fact["state"] = "runtime_eligible"
        else:
            fact.pop("state", None)
        for key in ("authority", "authority_revision", "readback_evidence_id"):
            fact.pop(key, None)
    permission["digest_schema"] = "grant-permissions/v2"
    require(sha(canon(permission)) == identity["grant_ref"]["permission_digest"], "grant-permission-digest")
    require(grant["schema_version"] == "grant/v2" and grant["filesystem_profile"] == "windows-local-drive/v1", "grant-profile")

    native_sessions = set()
    marker = b"SIQ_WINDOWS_MANAGED_SYNTHETIC_MARKER\n"
    cases = []
    expected_files = {}
    denied_error = "siq-agent-security: decision service unavailable (instance session could not be verified); blocked (fail-closed)"
    for row in report["cases"]:
        case = row["case"]
        native = root / ("native-" + case)
        target = root / row["target_relative"]
        provider = read(native / "provider.private.json")
        events = lines(native / "guard-events.private.jsonl")
        require(provider["complete"] is True and not provider["errors"], case + "-provider")
        require(not any(e.get("event") in ("denied_external_write", "denied_configuration_read", "denied_network", "denied_dns") for e in events), case + "-guard-interference")
        sessions = {e["session_id"] for e in events if e.get("path") == "/v1/runtime-sessions"}
        require(len(sessions) == 1 and not sessions.intersection(native_sessions), case + "-unique-session")
        session = next(iter(sessions))
        native_sessions.update(sessions)
        require(sha(session.encode()) == row["native_session_sha256"], case + "-session-report")
        require(row["workspace_before"] == expected_files, case + "-before-files")
        tool_results = provider["results"]
        result = json.loads(tool_results[0]["content"])
        decisions = [r for r in receipts if r.get("session_id") == session and r.get("record_type") == "decision"]
        if case in ("B01", "B04"):
            require(len(tool_results) == 2 and target.read_bytes() == marker, case + "-real-marker")
            require(result["bytes_written"] == len(marker) and result["verified"] is True and Path(result["resolved_path"]) == target and result["files_modified"] == [str(target)], case + "-write-result")
            require(json.loads(tool_results[1]["content"])["content"] == "1|SIQ_WINDOWS_MANAGED_SYNTHETIC_MARKER", case + "-read-back")
            require(len(decisions) == 2 and all(r["action"] == "allow" for r in decisions), case + "-allow-decisions")
            for decision in decisions:
                observed = [r for r in receipts if r.get("action_id") == decision["action_id"] and r.get("record_type") == "observation"]
                require(len(observed) == 1, case + "-observations")
            expected_files[target.relative_to(root / "workspace").as_posix()] = {"bytes": len(marker), "sha256": sha(marker)}
        elif case == "B02":
            require(len(decisions) == 1 and decisions[0]["action"] == "deny" and decisions[0]["reason_code"] == "grant_scope_violation", "B02-real-scope-deny")
            expected = "siq-agent-security denied: " + decisions[0]["reason"] + " (receipt " + decisions[0]["receipt_id"] + ")"
            require(result == {"error": expected} and not target.exists(), "B02-exact-result-no-side-effect")
        else:
            require(result == {"error": denied_error} and not decisions and not target.exists(), case + "-exact-fail-closed")
            require(not any(e.get("path") == "/v1/decide" for e in events), case + "-no-decide")
            pending = read(native / "pending.private.json")
            require(any(p.get("session_id") == session and p.get("outcome") == "deny" and p.get("enforcement_mode") == "block" for p in pending), case + "-pending-deny")
        for decision in decisions:
            intent = read(root / "state/intents" / (decision["intent_id"] + ".json"))
            signed(intent, case + "-intent-" + decision["tool_call_id"])
            require(sha(canon({k: v for k, v in intent.items() if k not in ("digest", "signature")})) == intent["digest"] == decision["intent_digest"], case + "-intent-digest")
            matching = [read(p) for p in (root / "state/intent-bindings").glob("*.json")]
            matching = [b for b in matching if b["intent_id"] == intent["intent_id"] and b["session_id"] == session]
            require(len(matching) == 1, case + "-binding-unique")
            binding = matching[0]
            signed(binding, case + "-binding-" + decision["tool_call_id"])
            require(intent["schema_version"] == "intent/v4" and intent["authority_kind"] == "instance_permission" and intent["filesystem_profile"] == "windows-local-drive/v1", case + "-intent-profile")
            require(binding["schema_version"] == "intent-grant-binding/v2" and binding["grant_ref"] == identity["grant_ref"] and binding["intent_digest"] == intent["digest"], case + "-binding-grant")
            require(intent["authority"]["revision"] == binding["authority_revision"] == decision["authority_revision"] == identity_digest, case + "-authority-reference")
            require(decision["intent_binding"] == "bound" and decision["agent_id"] == identity["agent_id"] == binding["agent_id"] == intent["agent"]["id"], case + "-agent")
            when = datetime.fromisoformat(decision["issued_at"].replace("Z", "+00:00"))
            require(datetime.fromisoformat(intent["issued_at"].replace("Z", "+00:00")).replace(microsecond=0) <= when < datetime.fromisoformat(intent["expires_at"].replace("Z", "+00:00")), case + "-valid-at-decision")
        require(row["workspace_after"] == expected_files, case + "-reported-side-effects")
        require(any(x["label"] == case + "-hermes" and x["job_closed"] is True and x["exit_code"] == 0 and x["job_before_close"]["active_processes"] == 0 for x in report["cleanup"]), case + "-owned-job-closed")
        cases.append({"case": case, "verified": True, "receipt_decisions": len(decisions), "guard_denied_subprocess_count": sum(e.get("event") == "denied_subprocess" for e in events)})
    actual_files = {p.relative_to(root / "workspace").as_posix(): {"bytes": p.stat().st_size, "sha256": sha(p.read_bytes())} for p in (root / "workspace").rglob("*") if p.is_file()}
    require(actual_files == expected_files, "final-actual-workspace")
    require(all(c["job_closed"] is True and c["exit_code"] == 0 for c in report["cleanup"]), "all-owned-jobs-closed")
    http = lines(root / "http.private.jsonl")
    require(any(r["method"] == "GET" and r["path"] == "/v1/runtime-identities" and any(i["identity_id"] == identity["identity_id"] and i["status"] == "revoked" for i in r["response"]["items"]) for r in http), "revocation-readback")
    require(report["adapter_cleanup"] == "uninstalled-from-isolated-profile" and any(r["path"] == "/v1/adapter/uninstall" and r["status"] == 200 for r in http), "adapter-uninstalled")
    return {"status": "pass", "method": "independent-offline-evidence-verification", "source_files_verified": len(source_hashes), "pinned_files_verified": len(plan["files"]), "receipt_chain_count": len(receipts), "signed_documents_verified": verified, "public_key_sha256": sha(public.public_bytes(Encoding.Raw, PublicFormat.Raw)), "cases": cases, "owned_jobs_closed": len(report["cleanup"]), "workspace_files": actual_files, "ledger_fully_supported": ["P02-HM-A04-01", "P02-HM-A04-02", "P02-HM-A05-01"], "ledger_partial": {"P02-HM-A05-04": "B04 recovery allows valid authority; B05 later revocation denies. No restart after revocation, so invalid-authority persistence across recovery is not demonstrated."}, "limitations": ["No host/service/model was launched by verification.", "Retained controller observations are verified, not a second independent native rerun.", "The private fixture signing seed was used only to derive an in-memory verification public key; no signing performed or secret emitted.", "Guard rejected ancillary subprocess attempts; exact SIQ denial and real allow file effects distinguish security results from those guard rejections.", "This is managed Hermes v4 evidence, not product runtime-check v5, paid-model evidence, or final whole-project acceptance."]}


if __name__ == "__main__":
    result = main(Path(sys.argv[1]))
    output = Path(sys.argv[2])
    output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf8", newline="\n")
    print(json.dumps(result, ensure_ascii=True))
