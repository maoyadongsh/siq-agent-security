"""威胁检测规则包加载：内置包 + 可选的外部签名更新包（P2）。

安全红线（fail-closed）：
- 外部规则包（SIQ_AS_THREAT_RULEPACK_PATH 指向的本地 JSON，即离线缓存）必须带
  控制面 Ed25519 签名：旁边同名 `<文件名>.sig` 文件，base64 编码，签名输入 =
  规则包 JSON 的规范序列化（sort_keys + 紧凑分隔符，与 app.signing 一致）；
- 验签失败 / 缺 .sig / JSON 畸形 / 字段缺漏 / 正则不可编译 / 版本低于内置包，
  一律拒绝并回退内置包，绝不加载未验签或降级的规则；
- 拒绝原因只记类别与路径，规则包内容不进日志；
- 内置包损坏是构建事故：直接 RuntimeError 拒绝启动，不静默。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature

from app.signing import _canonical_bytes, get_signing_key

logger = logging.getLogger(__name__)

# 外部更新包路径（离线缓存 = 本地文件路径；回滚 = 指回旧版本文件或移除该变量）
RULEPACK_PATH_ENV = "SIQ_AS_THREAT_RULEPACK_PATH"

_BUILTIN_PATH = Path(__file__).resolve().parent / "data" / "threat_rules.v1.json"

_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
_REQUIRED_FIELDS = ("rule_id", "severity", "confidence", "description", "impact", "remediation", "patterns")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: str  # critical|high|medium|low
    confidence: float  # 0-1
    description: str
    impact: str
    remediation: str
    patterns: tuple[re.Pattern[str], ...]


class RulepackError(ValueError):
    """规则包非法/验签失败。消息只含类别信息，不含规则内容（可安全进日志）。"""


def _parse_rulepack(data: Any) -> tuple[int, tuple[Rule, ...]]:
    """校验规则包结构并编译 patterns；任何非法都抛 RulepackError（整包拒绝）。"""
    if not isinstance(data, dict):
        raise RulepackError("rulepack root must be an object")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise RulepackError("rulepack 'version' must be a positive integer")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise RulepackError("rulepack 'rules' must be a non-empty array")
    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for idx, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise RulepackError(f"rule #{idx} must be an object")
        missing = [f for f in _REQUIRED_FIELDS if f not in raw]
        if missing:
            raise RulepackError(f"rule #{idx} missing required field(s): {', '.join(missing)}")
        rule_id = raw["rule_id"]
        if not isinstance(rule_id, str) or not rule_id or rule_id in seen_ids:
            raise RulepackError(f"rule #{idx} has invalid or duplicate rule_id")
        seen_ids.add(rule_id)
        if raw["severity"] not in _SEVERITIES:
            raise RulepackError(f"rule #{idx} has invalid severity")
        confidence = raw["confidence"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 < confidence <= 1:
            raise RulepackError(f"rule #{idx} has invalid confidence")
        if not all(isinstance(raw[f], str) for f in ("description", "impact", "remediation")):
            raise RulepackError(f"rule #{idx} has non-string text field")
        raw_patterns = raw["patterns"]
        if (
            not isinstance(raw_patterns, list)
            or not raw_patterns
            or not all(isinstance(p, str) for p in raw_patterns)
        ):
            raise RulepackError(f"rule #{idx} 'patterns' must be a non-empty array of strings")
        try:
            patterns = tuple(re.compile(p) for p in raw_patterns)
        except re.error as exc:
            raise RulepackError(f"rule #{idx} contains an uncompilable pattern") from exc
        rules.append(
            Rule(
                rule_id=rule_id,
                severity=raw["severity"],
                confidence=float(confidence),
                description=raw["description"],
                impact=raw["impact"],
                remediation=raw["remediation"],
                patterns=patterns,
            )
        )
    return version, tuple(rules)


def _load_builtin() -> tuple[int, tuple[Rule, ...]]:
    """加载内置包；损坏即构建事故，RuntimeError 拒绝启动（不静默回退）。"""
    try:
        data = json.loads(_BUILTIN_PATH.read_text(encoding="utf-8"))
        return _parse_rulepack(data)
    except (OSError, json.JSONDecodeError, RulepackError) as exc:
        raise RuntimeError(f"内置威胁规则包损坏或缺失（{_BUILTIN_PATH.name}），属构建事故，拒绝启动: {exc}") from exc


def _verify_signature(path: Path, data: dict) -> None:
    """用控制面签名公钥验签 `<文件名>.sig`；任何失败抛 RulepackError。"""
    sig_path = path.with_name(path.name + ".sig")
    try:
        sig_b64 = sig_path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise RulepackError("missing signature file (.sig)") from exc
    try:
        signature = base64.b64decode(sig_b64, validate=True)
    except ValueError as exc:
        raise RulepackError("signature file is not valid base64") from exc
    try:
        get_signing_key().public_key().verify(signature, _canonical_bytes(data))
    except InvalidSignature as exc:
        raise RulepackError("signature verification failed") from exc


def load_rulepack() -> tuple[int, tuple[Rule, ...]]:
    """加载生效规则包，返回 (version, rules)。可重复调用（热更新/测试）。

    默认内置包；SIQ_AS_THREAT_RULEPACK_PATH 指向的外部包经验签通过且
    version >= 内置版本才采用，否则回退内置包并 logging.warning（fail-closed）。
    """
    builtin = _load_builtin()
    raw_path = os.getenv(RULEPACK_PATH_ENV)
    if not raw_path:
        return builtin
    path = Path(raw_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        external = _parse_rulepack(data)
        _verify_signature(path, data)
    except (OSError, json.JSONDecodeError, RulepackError) as exc:
        logger.warning("外部威胁规则包被拒绝，回退内置包: path=%s reason=%s", path, exc)
        return builtin
    except RuntimeError as exc:  # 签名密钥不可用：fail-closed，不加载未验签规则
        logger.warning("外部威胁规则包验签密钥不可用，回退内置包: path=%s reason=%s", path, exc)
        return builtin
    if external[0] < builtin[0]:
        logger.warning(
            "外部威胁规则包版本低于内置包被拒绝（防回滚降级），回退内置包: path=%s", path
        )
        return builtin
    return external
