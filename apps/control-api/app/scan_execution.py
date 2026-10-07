"""Parent authority for a bounded scan; results cannot select tenant or task identity."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass

from app import threat_analysis as analysis
from app.config import load_settings
from app.scan_isolation import command
from app.scan_transport import ScanFailure, exchange
from app.scan_worker import MAX_INPUT, canonical


@dataclass(frozen=True)
class ScanResult(analysis.AnalysisResult):
    analyzer_version: str


def rule_snapshot():
    # Snapshot already-verified in-process rules. No signing key crosses into the worker.
    with analysis.RULEPACK_LOCK:
        return {"version": analysis.RULEPACK_VERSION,
                "rules": [{**{k: v for k, v in asdict(rule).items() if k != "patterns"},
                           "patterns": [p.pattern for p in rule.patterns]} for rule in analysis._RULES],
                "redaction_patterns": [{"pattern": r.pattern.pattern, "replacement": r.replacement}
                                       for r in analysis._REDACTION_RULES]}


def parse_response(output, request):
    try:
        response = json.loads(output)
        expected = {"schema_version", "task_id", "scope_sha256", "input_sha256", "rules_sha256",
                    "analyzer_version", "result"}
        if not isinstance(response, dict) or set(response) != expected:
            raise ValueError("shape")
        for key in ("schema_version", "task_id", "scope_sha256", "input_sha256", "rules_sha256", "analyzer_version"):
            if response[key] != request[key]:
                raise ValueError("binding")
        result = response["result"]
        if not isinstance(result, dict) or set(result) != {"sha256", "detected_type", "matches"}:
            raise ValueError("result_shape")
        if result["sha256"] != request["input_sha256"]:
            raise ValueError("input")
        if result["detected_type"] not in {"shell", "python", "javascript", "powershell", "binary", "unknown"}:
            raise ValueError("type")
        if not isinstance(result["matches"], list) or len(result["matches"]) > 1024:
            raise ValueError("matches")
        matches = [analysis.RuleMatch(**m) for m in result["matches"]]
        for match in matches:
            if (match.severity not in {"critical", "high", "medium", "low"}
                    or not isinstance(match.rule_id, str) or not 1 <= len(match.rule_id) <= 256
                    or type(match.confidence) not in (int, float) or not 0 <= match.confidence <= 1
                    or not isinstance(match.excerpt, str) or len(match.excerpt) > 40
                    or not isinstance(match.excerpt_sha256, str)
                    or re.fullmatch(r"[0-9a-f]{64}", match.excerpt_sha256) is None
                    or any(not isinstance(value, str) or len(value) > 8192
                           for value in (match.description, match.impact, match.remediation))
                    or (match.line is not None and (type(match.line) is not int or not 1 <= match.line <= 1048577))):
                raise ValueError("match")
        return ScanResult(result["sha256"], result["detected_type"], matches, response["analyzer_version"])
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise ScanFailure("threat_scan_result_invalid") from None


def analyze(content, filename=None, *, scope=""):
    rules = rule_snapshot()
    request = {"schema_version": "threat-scan-worker/v1", "task_id": uuid.uuid4().hex,
               "scope_sha256": hashlib.sha256(scope.encode()).hexdigest(),
               "input_sha256": hashlib.sha256(content).hexdigest(),
               "rules_sha256": hashlib.sha256(canonical(rules)).hexdigest(),
               "analyzer_version": f"siq.threat-static.v{rules['version']}",
               "content_base64": base64.b64encode(content).decode("ascii"), "filename": filename,
               "rules": rules}
    payload = canonical(request)
    if len(payload) > MAX_INPUT:
        raise ScanFailure("threat_scan_input_limit")
    output = exchange(command(load_settings().threat_scan_isolation), payload)
    return parse_response(output, request)
