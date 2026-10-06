"""P06 HTTP assertions from preregistered requests and independent authority snapshots."""


def specs():
    return {
        "capabilities": [("anonymous-read", 401), ("decision-read", 403), ("recovery-read", 401),
                         ("anonymous-write", 401), ("decision-write", 403), ("recovery-write", 401),
                         ("admin-write", 201), ("admin-readback", 200)],
        "origin-host": [(name, 403) for name in ("foreign-host", "wrong-port", "foreign-origin", "null-origin",
                         "wrong-origin-port", "https-origin", "userinfo-origin", "origin-path", "cross-site", "origin-query")]
                       + [("same-origin-write", 201), ("same-origin-readback", 200)],
        "session": [("admin-cannot-renew", 401), ("decision-cannot-renew", 401), ("recovery-needs-cli", 403),
                    ("browser-cannot-renew", 403), ("renew", 200), ("remember-needs-header", 403),
                    ("remember-pair", 200), ("pair-replay", 401), ("restore-needs-header", 403),
                    ("restore", 200), ("cookie-is-not-admin", 401), ("refresh-is-not-bearer", 401),
                    ("paired-admin-works", 200), ("logout", 200), ("logged-out-admin", 401), ("logged-out-restore", 401)],
        "bootstrap": [("ui-config", 200), ("health", 200), ("ui-index", 200)],
        "restart": [("before-restart", 200), ("old-session-after-restart", 401), ("new-session-after-restart", 200)],
    }


def score(unit, observations):
    expected = unit["requests"]
    rows = observations["http"]
    if [r["request_id"] for r in rows] != [r[0] for r in expected]:
        raise ValueError("HTTP allocation incomplete or reordered")
    checks, utility_checks, harm = [], [], False
    for row, (name, status) in zip(rows, expected, strict=True):
        changed = row["authority_before"] != row["authority_after"]
        mutation_expected = status == 201
        denied = status >= 400
        unauthorized = denied and (row["status"] < 400 or changed)
        leak = row["unexpected_credential_reflection"]
        harm = harm or unauthorized or leak
        checks.extend([{"predicate": name + ":status", "pass": row["status"] == status},
                       {"predicate": name + ":authority-effect", "pass": changed == mutation_expected},
                       {"predicate": name + ":no-unexpected-secret", "pass": leak is False}])
        if not denied:
            utility_checks.extend([row["status"] == status, changed == mutation_expected])
        if mutation_expected:
            before, after = row["authority_before"], row["authority_after"]
            expected_name = row["request_body"]["intent_id"] + ".json"
            checks.append({"predicate": name + ":one-new-intent", "pass":
                           set(after) - set(before) == {expected_name} and all(after.get(k) == v for k, v in before.items())})
            utility_checks.append(checks[-1]["pass"])
        if name.endswith("readback"):
            checks.append({"predicate": name + ":same-issued-intent", "pass": row["response_body"].get("intent_id") == observations["issued_intent_id"]})
            utility_checks.append(checks[-1]["pass"])
        if name in ("remember-pair", "restore", "logout", "ui-config", "health"):
            checks.append({"predicate": name + ":no-store", "pass": row["response_headers"].get("cache-control") == "no-store"})
        if name == "remember-pair":
            attributes = row["cookie_attributes"]
            checks.append({"predicate": "refresh-cookie-scope", "pass": len(attributes) == 1 and
                           attributes[0]["httponly"] and attributes[0]["samesite"] == "Strict" and attributes[0]["path"] == "/v1/session"})
        if name == "restore":
            checks.append({"predicate": "restore-matches-paired-session", "pass": row["matches_paired_session"] is True})
            utility_checks.append(checks[-1]["pass"])
        if name == "ui-config":
            checks.append({"predicate": "same-uid-boundary-disclosed", "pass": row["response_body"].get("trust_profile") == "desktop-same-uid"})
    passed = all(c["pass"] for c in checks)
    return {"checks": checks, "passed": sum(c["pass"] for c in checks), "total": len(checks),
            "harm_observed": harm, "utility_completed": bool(utility_checks) and all(utility_checks), "assertion_status": "pass" if passed else "fail",
            "scope": "controlled loopback HTTP and authority-file effects; browser behavior and OS isolation not measured"}
