"""Versioned case journal with exclusive writers and conservative recovery.

This module never dispatches a tool. A started attempt is not scheduled again;
interrupted attempts require separate resource reconciliation before retry.
"""
import copy
import fcntl
import hashlib
import json
import os
import re
import time
from pathlib import Path

import jsonschema
from common import canonical, safe_path, sha256, utc_now, write_json

SCHEMA = Path(__file__).parent / "schemas/case.v1.schema.json"
TERMINAL = {"finished", "interrupted"}


def process_identity():
    return {"pid": os.getpid(), "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "start_ticks": Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]}


def process_state(ref):
    if ref["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        return "different_boot"
    try:
        fields = Path(f"/proc/{ref['pid']}/stat").read_text().rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return "absent"
    if fields[19] != ref["start_ticks"]:
        return "pid_reused"
    return "zombie" if fields[0] == "Z" else "alive"


def validate(record):
    try:
        jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text())).validate(record)
    except jsonschema.ValidationError as exc:
        raise ValueError("canonical case schema invalid: " + exc.json_path) from None
    for field in ("harm_observed", "utility_completed"):
        reason = record[field.replace("observed", "unknown_reason").replace("completed", "unknown_reason")]
        if (record[field] is None) != (isinstance(reason, str) and bool(reason)):
            raise ValueError("unknown value/reason mismatch")
    if record["harm_observed"] is True and not record["harm_evidence_refs"]:
        raise ValueError("known harm requires evidence")
    if record["utility_completed"] is True and not record["utility_evidence_refs"]:
        raise ValueError("known completion requires evidence")
    if record["lifecycle"] == "scheduled" and (record["execution_status"] != "not_started" or record["process_ref"] is not None):
        raise ValueError("scheduled attempt already executed")
    if record["lifecycle"] == "started" and record["execution_status"] != "running":
        raise ValueError("started execution status differs")
    if record["lifecycle"] == "interrupted" and (record["execution_status"] != "interrupted" or
            record["measurement_status"] != "indeterminate" or record["assertion_status"] not in ("fail", "inconclusive")):
        raise ValueError("interrupted state inconsistent")
    if record["assertion_status"] == "pass" and (record["lifecycle"] != "finished" or
            record["execution_status"] != "completed" or record["measurement_status"] != "determinate"):
        raise ValueError("incomplete attempt cannot pass")
    if (record["attempt"] == 1) != (record["retry_of"] is None):
        raise ValueError("retry linkage required")


def initial(unit, run_id, protocol_digest, candidate_digest, attempt=1, retry_of=None):
    row = {"schema_version": "siq-third-party-case/v1", "run_id": run_id, "unit_id": unit["unit_id"],
           "case_id": unit["case_id"], "pair_id": unit["pair_id"], "task_block_id": unit["task_block_id"],
           "track": unit["track"], "group": unit["group"], "family_id": unit["family_id"],
           "claim_ids": unit["claim_ids"], "product_group_ids": unit["product_group_ids"],
           "candidate_digest": candidate_digest, "protocol_digest": protocol_digest,
           "attempt": attempt, "attempt_id": unit["unit_id"] + "#" + str(attempt), "retry_of": retry_of,
           "lifecycle": "scheduled", "execution_status": "not_started", "measurement_status": "not_evaluated",
           "assertion_status": "not_evaluated", "decision_action": None, "tool_executed": None,
           "harm_observed": None, "utility_completed": None, "harm_unknown_reason": "not_started",
           "utility_unknown_reason": "not_started", "harm_evidence_refs": [], "utility_evidence_refs": [],
           "siq_completion": None, "siq_reason_code": None, "ui_completion_claim": None,
           "agent_completion_claim": None, "lab_boundary_intervened": False,
           "oracle": {"source": "not_evaluated", "coverage": "not_evaluated", "healthy": None,
                      "window_start": None, "window_end": None, "materials": []},
           "receipt_refs": [], "product_observer_refs": [], "event_trace_refs": [], "error": None,
           "process_ref": None, "cleanup_confirmed": False}
    validate(row)
    return row


def project(run):
    protocol = json.loads(safe_path(run, "protocol.json").read_text())
    allocation = protocol["allocation"]
    ids = [u["unit_id"] for u in allocation]
    if not ids or len(ids) != len(set(ids)) or any(not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", x) for x in ids):
        raise ValueError("invalid allocation")
    raw = safe_path(run, "journal.jsonl").read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError("torn journal tail; preserve bytes, do not auto-truncate")
    events = [json.loads(line) for line in raw.splitlines()]
    states, previous, clocks = {}, "0" * 64, {}
    for sequence, event in enumerate(events, 1):
        digest = event.pop("event_sha256")
        if event["sequence"] != sequence or event["previous_sha256"] != previous or hashlib.sha256(canonical(event)).hexdigest() != digest:
            raise ValueError("journal chain mismatch")
        previous = digest
        boot = event["writer"]["boot_id"]
        if type(event["monotonic_ns"]) is not int or event["monotonic_ns"] < clocks.get(boot, -1):
            raise ValueError("journal clock reversed")
        clocks[boot] = event["monotonic_ns"]
        row = event["record"]
        validate(row)
        if row["run_id"] != protocol["run_id"] or row["protocol_digest"] != sha256(run / "protocol.json") or row["candidate_digest"] != protocol["candidate_digest"]:
            raise ValueError("journal identity mismatch")
        if row["unit_id"] not in ids:
            raise ValueError("unallocated attempt")
        unit = allocation[ids.index(row["unit_id"])]
        for field in ("case_id", "pair_id", "task_block_id", "track", "group", "family_id", "claim_ids", "product_group_ids"):
            if row[field] != unit[field]:
                raise ValueError("allocated case metadata differs")
        key = row["attempt_id"]
        before = states.get(key)
        if before is None:
            if event["kind"] != "scheduled" or row["lifecycle"] != "scheduled":
                raise ValueError("attempt missing schedule")
            peers = [s for s in states.values() if s["unit_id"] == row["unit_id"]]
            if row["attempt"] != len(peers) + 1 or row["attempt"] > protocol["max_attempts"]:
                raise ValueError("attempt replay or budget exceeded")
            if peers and (peers[-1]["attempt_id"] != row["retry_of"] or peers[-1]["lifecycle"] not in TERMINAL
                          or not peers[-1]["cleanup_confirmed"]):
                raise ValueError("retry before terminal resource reconciliation")
        else:
            transitions = {"started": ("scheduled", "started"), "observed": ("started", "started"),
                           "finished": ("started", "finished"), "interrupted": ("started", "interrupted"),
                           "cleanup_confirmed": ("interrupted", "interrupted")}
            if event["kind"] not in transitions or (before["lifecycle"], row["lifecycle"]) != transitions[event["kind"]]:
                raise ValueError("invalid lifecycle transition")
            if before["harm_observed"] is True and (row["harm_observed"] is not True or not set(before["harm_evidence_refs"]) <= set(row["harm_evidence_refs"])):
                raise ValueError("confirmed harm erased")
            if before["assertion_status"] == "fail" and row["assertion_status"] != "fail":
                raise ValueError("confirmed assertion failure erased")
            if before["tool_executed"] is True and row["tool_executed"] is not True:
                raise ValueError("known dispatch erased")
            if before["process_ref"] is not None and row["process_ref"] != before["process_ref"]:
                raise ValueError("process identity replaced")
            if row["retry_of"] != before["retry_of"] or row["attempt"] != before["attempt"]:
                raise ValueError("attempt identity changed")
        if row["lifecycle"] != "scheduled" and row["process_ref"] is None:
            raise ValueError("started attempt lacks process identity")
        if key != row["unit_id"] + "#" + str(row["attempt"]):
            raise ValueError("attempt ID differs")
        states[key] = row
    if {s["unit_id"] for s in states.values()} != set(ids):
        raise ValueError("scheduled allocation incomplete")
    return protocol, states, events, previous


class Journal:
    def __init__(self, root, protocol=None):
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("symlink run root")
        if protocol is not None:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
            write_json(self.root / "protocol.json", protocol)
            safe_path(self.root, "journal.jsonl").touch(mode=0o600)
        path = safe_path(self.root, ".writer.lock")
        self.lock = path.open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise ValueError("another evaluator owns this run") from None
        if protocol is not None:
            self.protocol, self.states, self.events, self.previous = protocol, {}, [], "0" * 64
            for unit in protocol["allocation"]:
                self.append("scheduled", initial(unit, protocol["run_id"], sha256(self.root / "protocol.json"), protocol["candidate_digest"]))
        else:
            if safe_path(self.root, "manifest.json").exists():
                self.close()
                raise ValueError("sealed journal is immutable")
            try:
                self.protocol, self.states, self.events, self.previous = project(self.root)
            except Exception:
                self.close()
                raise

    def close(self):
        self.lock.close()

    def append(self, kind, row):
        validate(row)
        event = {"sequence": len(self.events) + 1, "previous_sha256": self.previous,
                 "kind": kind, "utc": utc_now(), "monotonic_ns": time.monotonic_ns(),
                 "writer": process_identity(), "record": row}
        digest = hashlib.sha256(canonical(event)).hexdigest()
        with safe_path(self.root, "journal.jsonl").open("ab") as stream:
            stream.write(canonical({**event, "event_sha256": digest}) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.events.append(event)
        self.previous = digest
        self.states[row["attempt_id"]] = copy.deepcopy(row)

    def transition(self, attempt_id, kind, **changes):
        row = copy.deepcopy(self.states[attempt_id])
        before = row["lifecycle"]
        allowed = {"started": "scheduled", "observed": "started", "finished": "started",
                   "interrupted": "started", "cleanup_confirmed": "interrupted"}
        if allowed.get(kind) != before:
            raise ValueError("attempt cannot be replayed")
        if row["harm_observed"] is True and changes.get("harm_observed", True) is not True:
            raise ValueError("confirmed harm cannot be erased")
        if row["harm_observed"] is True and not set(row["harm_evidence_refs"]) <= set(changes.get("harm_evidence_refs", row["harm_evidence_refs"])):
            raise ValueError("confirmed harm references cannot be erased")
        if row["assertion_status"] == "fail" and changes.get("assertion_status", "fail") != "fail":
            raise ValueError("confirmed failure cannot be erased")
        if row["tool_executed"] is True and changes.get("tool_executed", True) is not True:
            raise ValueError("known dispatch cannot be erased")
        immutable = {"schema_version", "run_id", "unit_id", "case_id", "pair_id", "task_block_id", "track", "group",
                     "family_id", "claim_ids", "product_group_ids", "candidate_digest", "protocol_digest", "attempt", "attempt_id", "retry_of", "lifecycle"}
        if immutable & set(changes):
            raise ValueError("immutable attempt metadata")
        if row["process_ref"] is not None and changes.get("process_ref", row["process_ref"]) != row["process_ref"]:
            raise ValueError("process identity cannot change")
        row.update(changes)
        if kind in ("started", "finished", "interrupted"):
            row["lifecycle"] = kind
        self.append(kind, row)

    def retry(self, unit_id):
        peers = [s for s in self.states.values() if s["unit_id"] == unit_id]
        if not peers:
            raise ValueError("unallocated retry")
        old = peers[-1]
        if old["lifecycle"] not in TERMINAL or not old["cleanup_confirmed"] or len(peers) >= self.protocol["max_attempts"]:
            raise ValueError("retry needs reconciled terminal attempt and remaining budget")
        unit = next(u for u in self.protocol["allocation"] if u["unit_id"] == unit_id)
        self.append("scheduled", initial(unit, self.protocol["run_id"], sha256(self.root / "protocol.json"),
                                         self.protocol["candidate_digest"], len(peers) + 1, old["attempt_id"]))

    def reconcile_dead_writers(self):
        for key, row in list(self.states.items()):
            if row["lifecycle"] != "started":
                continue
            state = process_state(row["process_ref"])
            if state == "alive":
                continue
            self.transition(key, "interrupted", execution_status="interrupted", measurement_status="indeterminate",
                            assertion_status="fail" if row["assertion_status"] == "fail" else "inconclusive",
                            error={"type": "writer_interrupted", "detail": state}, cleanup_confirmed=False)


def summarize(states):
    first = [s for s in states.values() if s["attempt"] == 1]
    failed = sum(s["assertion_status"] == "fail" for s in first)
    unknown = sum(s["assertion_status"] not in ("pass", "fail") for s in first)
    return {"allocated": len(first), "attempts": len(states), "first_attempt_pass": sum(s["assertion_status"] == "pass" for s in first),
            "first_attempt_fail": failed, "first_attempt_unknown": unknown,
            "known_harm_first_attempt": sum(s["harm_observed"] is True for s in first),
            "harm_unknown_first_attempt": sum(s["harm_observed"] is None for s in first),
            "selection_rule": "first_attempt_only; retry never replaces original",
            "outcome_exit_code": 1 if failed else 2 if unknown else 0}
