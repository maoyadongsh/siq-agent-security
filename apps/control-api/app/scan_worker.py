"""Private one-shot scan worker. No sample code is executed or imported."""
from __future__ import annotations

import base64
import hashlib
import json
import resource
import sys
from dataclasses import asdict

MAX_INPUT = 4 * 1024 * 1024
MAX_OUTPUT = 2 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def main():
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        message = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(message) > MAX_INPUT:
            raise ValueError("input_limit")
        request = json.loads(message)
        if request["schema_version"] != "threat-scan-worker/v1":
            raise ValueError("schema")
        raw = base64.b64decode(request["content_base64"], validate=True)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != request["input_sha256"]:
            raise ValueError("input_binding")
        rules = request["rules"]
        if hashlib.sha256(canonical(rules)).hexdigest() != request["rules_sha256"]:
            raise ValueError("rule_binding")
        from app import threat_analysis as analysis
        from app.rulepack import _parse_rulepack

        version, parsed, redactions = _parse_rulepack(rules)
        analyzer_version = f"siq.threat-static.v{version}"
        if analyzer_version != request["analyzer_version"]:
            raise ValueError("version")
        analysis._RULES, analysis._REDACTION_RULES = parsed, redactions
        result = analysis.analyze(raw, filename=request["filename"])
        response = {key: request[key] for key in (
            "schema_version", "task_id", "scope_sha256", "input_sha256", "rules_sha256", "analyzer_version")}
        response["result"] = asdict(result)
        output = canonical(response)
        if len(output) > MAX_OUTPUT:
            raise ValueError("output_limit")
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
    except Exception:
        # No traceback, sample, rule text, private path or free-form exception escapes.
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
