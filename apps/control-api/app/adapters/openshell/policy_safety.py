"""Lossless OpenShell policy parsing, canonical digests and network validation."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode
from yaml.tokens import (
    AliasToken,
    AnchorToken,
    DirectiveToken,
    FlowMappingEndToken,
    FlowMappingStartToken,
    FlowSequenceEndToken,
    FlowSequenceStartToken,
    ScalarToken,
    TagToken,
)

from app.adapters.openshell.contracts import AdapterError, UnsupportedCapability

_REVISION_RE = re.compile(r"[1-9][0-9]*\Z")
_SAFE_KEY_RE = re.compile(r"[A-Za-z0-9_.-]+\Z")
_CANONICAL_INT_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_AMBIGUOUS_SCALAR_RE = re.compile(
    r"(?:yes|no|on|off|y|n|null|~|true|false|"
    r"[-+]?(?:0[0-9]+|0x[0-9a-f]+|0o[0-7]+|0b[01]+|"
    r"(?:[0-9][0-9_]*)?\.[0-9_]+|[0-9][0-9_]*e[-+]?[0-9]+|\.inf|\.nan)|"
    r"[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}(?:[tT ].*)?|[0-9]+:[0-9]+(?::[0-9]+)?)\Z",
    re.IGNORECASE,
)
_NETWORK_RULE_KEYS = frozenset({"endpoint", "effect", "binary_paths", "rule_name"})
_GATEWAY_RULE_KEYS = frozenset({"name", "endpoints", "binaries"})
_GATEWAY_ENDPOINT_KEYS = frozenset({"host", "port"})
_GATEWAY_BINARY_KEYS = frozenset({"path"})


class _StrictPolicyLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise ConstructorError(None, None, "aliases are not supported", self.peek_event().start_mark)
        return super().compose_node(parent, index)


def _construct_mapping(loader: _StrictPolicyLoader, node: MappingNode, deep: bool = False) -> dict[str, Any]:
    if not isinstance(node, MappingNode):
        raise ConstructorError(None, None, "expected mapping", node.start_mark)
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or not _SAFE_KEY_RE.fullmatch(key):
            raise ConstructorError(None, None, "unsupported mapping key", key_node.start_mark)
        if key in mapping:
            raise ConstructorError(None, None, "duplicate mapping key", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictPolicyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def policy_digest(policy: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(policy)).hexdigest()


def static_policy_digest(policy: dict[str, Any]) -> str:
    static = copy.deepcopy(policy)
    static.pop("network_policies", None)
    return policy_digest(static)


def clone_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(policy)


def validate_revision(revision: str) -> str:
    if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
        raise AdapterError("openshell_revision_invalid")
    return revision


def parse_policy_output(out: str) -> tuple[dict[str, Any], str]:
    lines = out.splitlines()
    markers = [index for index, line in enumerate(lines) if line.strip() == "---"]
    if len(markers) != 1:
        raise AdapterError("openshell_policy_document_boundary_invalid")
    marker = markers[0]
    revisions: dict[str, str] = {}
    metadata_keys: set[str] = set()
    for raw in lines[:marker]:
        key, separator, value = raw.strip().partition(":")
        if not separator:
            continue
        key = key.strip()
        if key in metadata_keys:
            raise AdapterError("openshell_policy_metadata_duplicate_key")
        metadata_keys.add(key)
        if key in {"Active", "Version"}:
            revisions[key] = validate_revision(value.strip())
    if not revisions:
        raise AdapterError("openshell_revision_ambiguous")
    if "Active" in revisions and "Version" in revisions and revisions["Active"] != revisions["Version"]:
        raise AdapterError("openshell_revision_ambiguous")
    revision = revisions.get("Active", revisions.get("Version"))
    assert revision is not None
    body = "\n".join(lines[marker + 1 :])
    _validate_yaml_tokens(body)
    try:
        doc = yaml.load(body, Loader=_StrictPolicyLoader)
    except (yaml.YAMLError, ConstructorError):
        raise AdapterError("openshell_policy_yaml_unsupported") from None
    if not isinstance(doc, dict):
        raise AdapterError("openshell_policy_yaml_expected_mapping")
    _validate_policy_value(doc)
    return doc, revision


def _validate_yaml_tokens(body: str) -> None:
    try:
        tokens = list(yaml.scan(body))
    except yaml.YAMLError:
        raise AdapterError("openshell_policy_yaml_unsupported") from None
    for index, token in enumerate(tokens):
        if isinstance(token, (AliasToken, AnchorToken, DirectiveToken, TagToken)):
            raise AdapterError("openshell_policy_yaml_unsupported")
        if isinstance(token, FlowMappingStartToken):
            if index + 1 >= len(tokens) or not isinstance(tokens[index + 1], FlowMappingEndToken):
                raise AdapterError("openshell_policy_yaml_unsupported")
        if isinstance(token, FlowSequenceStartToken):
            if index + 1 >= len(tokens) or not isinstance(tokens[index + 1], FlowSequenceEndToken):
                raise AdapterError("openshell_policy_yaml_unsupported")
        if isinstance(token, ScalarToken) and token.style is None:
            value = token.value
            if value in {"true", "false", "null"} or _CANONICAL_INT_RE.fullmatch(value):
                continue
            if _AMBIGUOUS_SCALAR_RE.fullmatch(value):
                raise AdapterError("openshell_policy_yaml_ambiguous_scalar")


def _validate_policy_value(value: Any) -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        if value < -(2**63) or value > 2**63 - 1:
            raise AdapterError("openshell_policy_yaml_integer_out_of_range")
        return
    if isinstance(value, list):
        for item in value:
            _validate_policy_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not _SAFE_KEY_RE.fullmatch(key):
                raise AdapterError("openshell_policy_yaml_key_unsupported")
            _validate_policy_value(item)
        return
    raise AdapterError("openshell_policy_yaml_value_unsupported")


def validate_network_rules(rules: Any) -> list[dict[str, Any]]:
    if not isinstance(rules, list):
        raise UnsupportedCapability("openshell_network_rules_invalid")
    validated: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - _NETWORK_RULE_KEYS:
            raise UnsupportedCapability("openshell_network_rule_unsupported_fields")
        if rule.get("effect") != "allow":
            raise UnsupportedCapability("openshell_network_effect_unsupported")
        host, port = split_endpoint(rule.get("endpoint"))
        binaries = rule.get("binary_paths")
        if not isinstance(binaries, list) or not binaries:
            raise UnsupportedCapability("openshell_network_binary_required")
        if any(not isinstance(path, str) or not is_absolute_policy_path(path) for path in binaries):
            raise UnsupportedCapability("openshell_network_binary_must_be_absolute")
        name = rule.get("rule_name")
        if name is not None and (not isinstance(name, str) or not name):
            raise UnsupportedCapability("openshell_network_rule_name_invalid")
        validated.append(
            {
                "endpoint": format_endpoint(host, port),
                "effect": "allow",
                "binary_paths": list(binaries),
                **({"rule_name": name} if name else {}),
            }
        )
    return validated


def gateway_network_to_rules(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise AdapterError("openshell_gateway_network_invalid")
    result: list[dict[str, Any]] = []
    for key, rule in raw.items():
        if not isinstance(key, str) or not isinstance(rule, dict) or set(rule) - _GATEWAY_RULE_KEYS:
            raise AdapterError("openshell_gateway_network_unsupported")
        endpoints = rule.get("endpoints")
        binaries = rule.get("binaries")
        if not isinstance(endpoints, list) or not endpoints or not isinstance(binaries, list) or not binaries:
            raise AdapterError("openshell_gateway_network_unsupported")
        binary_paths: list[str] = []
        for binary in binaries:
            if not isinstance(binary, dict) or set(binary) != _GATEWAY_BINARY_KEYS:
                raise AdapterError("openshell_gateway_network_unsupported")
            path = binary.get("path")
            if not isinstance(path, str) or not is_absolute_policy_path(path):
                raise AdapterError("openshell_gateway_network_unsupported")
            binary_paths.append(path)
        for endpoint in endpoints:
            if not isinstance(endpoint, dict) or set(endpoint) != _GATEWAY_ENDPOINT_KEYS:
                raise AdapterError("openshell_gateway_network_unsupported")
            host = endpoint.get("host")
            port = endpoint.get("port")
            if not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool):
                raise AdapterError("openshell_gateway_network_unsupported")
            split_endpoint(format_endpoint(host, port))
            result.append(
                {
                    "endpoint": format_endpoint(host, port),
                    "effect": "allow",
                    "binary_paths": list(binary_paths),
                    "rule_name": rule.get("name", key),
                }
            )
    return result


def network_rules_to_gateway(rules: Any) -> dict[str, Any]:
    gateway: dict[str, Any] = {}
    for index, rule in enumerate(validate_network_rules(rules)):
        host, port = split_endpoint(rule["endpoint"])
        gateway[f"siq_as_rule_{index}"] = {
            "name": rule.get("rule_name", f"siq-as-rule-{index}"),
            "endpoints": [{"host": host, "port": port}],
            "binaries": [{"path": path} for path in rule["binary_paths"]],
        }
    return gateway


def split_endpoint(endpoint: Any) -> tuple[str, int]:
    if not isinstance(endpoint, str) or any(char in endpoint for char in "/?#@ \t\r\n"):
        raise UnsupportedCapability("openshell_network_endpoint_invalid")
    if endpoint.startswith("["):
        closing = endpoint.find("]")
        if closing <= 1 or closing + 1 >= len(endpoint) or endpoint[closing + 1] != ":":
            raise UnsupportedCapability("openshell_network_endpoint_invalid")
        host, port_text = endpoint[1:closing], endpoint[closing + 2 :]
    else:
        if endpoint.count(":") != 1:
            raise UnsupportedCapability("openshell_network_endpoint_invalid")
        host, port_text = endpoint.rsplit(":", 1)
    if not host or any(char in host for char in "/?#@[] \t\r\n"):
        raise UnsupportedCapability("openshell_network_endpoint_invalid")
    if not port_text.isdigit() or port_text.startswith("0"):
        raise UnsupportedCapability("openshell_network_endpoint_invalid")
    port = int(port_text)
    if port < 1 or port > 65535:
        raise UnsupportedCapability("openshell_network_endpoint_invalid")
    return host, port


def format_endpoint(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def is_absolute_policy_path(path: str) -> bool:
    return path.startswith("/") or (len(path) >= 3 and path[0].isalpha() and path[1] == ":" and path[2] in {"/", "\\"})
