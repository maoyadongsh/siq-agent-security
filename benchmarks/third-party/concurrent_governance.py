"""Controlled PostgreSQL lock windows expose overlapping real HTTP mutations.

The lock barrier is an explicit laboratory intervention, not a workload estimate.
No product functions are imported by the oracle or replaced during execution.
"""
import concurrent.futures
import threading
import time

import httpx
import psycopg
from common import write_json

CASES = {"race_policy": 201}
GROUPS = {"legacy_approve": 8, "legacy_mixed": 2, "review_approve": 8, "create_idempotency": 8}
ASSERTIONS = ["race_" + name for name in GROUPS]


def evaluate(o):
    result = {}
    for name, count in GROUPS.items():
        g = o.get(name, {})
        responses = g.get("responses", [])
        database = g.get("database", {})
        ok = len(responses) == count and len(g.get("blocked", [])) == count
        ok &= len({row[0] for row in g.get("blocked", [])}) == count
        ok &= all(row[1] == "Lock" for row in g.get("blocked", []))
        if name == "create_idempotency":
            ids = {r["body"].get("id") for r in responses if r["status"] == 201}
            ok &= all(r["status"] == 201 for r in responses) and len(ids) == 1 and None not in ids
            ok &= len(database.get("changes", [])) == 1 and len(database.get("audit", [])) == 1
            ok &= len(database.get("outbox", [])) == 1
            if len(database.get("changes", [])) == 1:
                cid = database["changes"][0][0]
                ok &= ids == {cid} and database.get("audit") == [[cid, "change.request.create"]]
                ok &= all(row[1]["payload"]["change_request_id"] == cid for row in database.get("outbox", []))
        else:
            winners = [r for r in responses if r["status"] == 200]
            ok &= len(winners) == 1 and all(r["status"] in (200, 409) for r in responses)
            if len(winners) == 1:
                winner = winners[0]
                action = winner["action"]
                expected = "approved" if action == "approve" else "rejected"
                ok &= database.get("change") == [[expected, winner["actor"]]]
                ok &= database.get("audit") == [["change." + action, winner["actor"]]]
                ok &= len(database.get("outbox", [])) == (1 if action == "approve" else 0)
                ok &= all(row[1]["payload"]["approver"] == winner["actor"] for row in database.get("outbox", []))
                reason = "review_changed" if name == "review_approve" else "invalid_state"
                ok &= all(row["body"].get("detail") == reason for row in responses if row["status"] == 409)
            else:
                ok = False
        result["race_" + name] = bool(ok)
    return result


def run(request, identity, sql, check, events, out, base_url, conninfo, a):
    policy = request("race_policy", "POST", "/api/v1/policies", a,
                     {"name": "concurrency-fixture", "selector": {"agent_ids": ["fixture-only"]},
                      "enforcement_mode": "block"})
    observed = {}
    lock = threading.Lock()

    def fetch(group, index, method, path, auth, body=None, actor="operator-a", action=None):
        with lock:
            events.add("race_http_started", group=group, index=index, method=method, path=path)
        start = time.monotonic_ns()
        with httpx.Client(base_url=base_url, timeout=25, trust_env=False) as client:
            response = client.request(method, path, headers=auth, json=body)
        try:
            data = response.json()
        except ValueError:
            data = {"non_json": response.text[:100]}
        row = {"index": index, "method": method, "path": path, "actor": actor, "action": action,
               "status": response.status_code, "body": data, "elapsed_ns": time.monotonic_ns() - start}
        with lock:
            events.add("race_http_finished", group=group, **row)
        return row

    def state(cr_id):
        return {"change": sql("SELECT status,approver_user_id FROM change_request WHERE id=%s", (cr_id,)),
                "audit": sql("SELECT action,actor_id FROM audit_event WHERE resource_id=%s AND action IN ('change.approve','change.reject') ORDER BY action,actor_id", (cr_id,)),
                "outbox": sql("SELECT event_type,payload FROM outbox_event WHERE event_type='policy.change.approved.v1' AND payload->'payload'->>'change_request_id'=%s ORDER BY id", (cr_id,))}

    try:
        for name, count in GROUPS.items():
            key = "tp07-concurrent-" + name
            g = observed[name] = {"responses": [], "blocked": []}
            body = {"policy_id": policy["id"], "idempotency_key": key}
            if name != "create_idempotency":
                setup = fetch(name, "setup", "POST", "/api/v1/change-requests", a, body)
                g["setup"] = setup
                if setup["status"] != 201:
                    raise RuntimeError("race_fixture_creation_failed")
                cr_id = setup["body"]["id"]
                g["before"] = state(cr_id)
            jobs = []
            for i in range(count):
                actor = "race-reviewer-" + str(i)
                auth = identity(actor=actor, roles=["reviewer", "auditor"])
                action = "reject" if name == "legacy_mixed" and i == 1 else "approve"
                path = f"/api/v1/change-requests/{cr_id}/{action}" if name != "create_idempotency" else "/api/v1/change-requests"
                payload = None
                if name == "review_approve":
                    review = fetch(name, "review-" + str(i), "GET", f"/api/v1/change-requests/{cr_id}/review", auth, actor=actor)
                    g.setdefault("reviews", []).append(review)
                    payload = {"schema_version": "change-review-decision/v1", "decision": "approve", "review_digest": review["body"]["review_digest"]}
                    path = f"/api/v1/change-requests/{cr_id}/review-decision"
                if name == "create_idempotency":
                    auth, payload, actor, action = a, body, "operator-a", "create"
                jobs.append((name, i, "POST", path, auth, payload, actor, action))
            guard = psycopg.connect(conninfo)
            futures = []
            try:
                if name == "create_idempotency":
                    sql("CREATE FUNCTION tp07_create_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                        "IF NEW.action='change.request.create' THEN PERFORM pg_advisory_xact_lock(8712345); END IF; RETURN NEW; END $$")
                    sql("CREATE TRIGGER tp07_create_lock BEFORE INSERT ON audit_event FOR EACH ROW EXECUTE FUNCTION tp07_create_barrier()")
                    guard.execute("SELECT pg_advisory_xact_lock(8712345)")
                else:
                    guard.execute("SELECT id FROM change_request WHERE id=%s FOR UPDATE", (cr_id,))
                events.add("race_barrier_held", group=name, kind="advisory audit INSERT" if name == "create_idempotency" else "change row lock")
                with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                    try:
                        futures = [pool.submit(fetch, *job) for job in jobs]
                        deadline = time.monotonic() + 12
                        while time.monotonic() < deadline:
                            blocked = sql("SELECT pid,wait_event_type,wait_event,left(query,500) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' ORDER BY pid")
                            if len(blocked) == count:
                                g["blocked"] = blocked
                                break
                            time.sleep(0.03)
                    finally:
                        guard.rollback()
                        with lock:
                            events.add("race_barrier_released", group=name, blocked=g["blocked"])
                    g["responses"] = [future.result() for future in futures]
            finally:
                guard.close()
                if name == "create_idempotency":
                    sql("DROP TRIGGER IF EXISTS tp07_create_lock ON audit_event")
            if name == "create_idempotency":
                changes = sql("SELECT id,status FROM change_request WHERE idempotency_key=%s", (key,))
                ids = [x[0] for x in changes]
                g["database"] = {"changes": changes,
                                 "audit": sql("SELECT resource_id,action FROM audit_event WHERE resource_id=ANY(%s) AND action='change.request.create'", (ids,)),
                                 "outbox": sql("SELECT event_type,payload FROM outbox_event WHERE event_type='policy.change.requested.v1' AND payload->'payload'->>'change_request_id'=ANY(%s)", (ids,))}
            else:
                g["database"] = state(cr_id)
            events.add("race_observation", name=name, value=g)
    finally:
        write_json(out / "race-observations.json", observed)
    for name, passed in evaluate(observed).items():
        check(name, passed, {"source": "race-observations.json", "predicate": name})
