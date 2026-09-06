"""DEV14-A：分类输出合同校验与受控降级（合成 MockTransport）。"""

from __future__ import annotations

import json
import math

import httpx
import pytest

from app.classification import (
    ClassificationContractError,
    classify_asset,
    provider_classify,
    validate_provider_output,
)
from app.db import session_scope
from app.models import AgentAsset, PermissionFact


def _provider_ok_response(content: dict | str) -> object:
    if isinstance(content, dict):
        content = json.dumps(content)
    return {"choices": [{"message": {"content": content}}]}


def _valid_output(**overrides) -> dict:
    base = {
        "is_agent_candidate": True,
        "role": {"value": "legal-advisor", "confidence": 0.94, "evidence_ids": []},
        "system_candidates": [],
        "capability_hints": ["document.read"],
        "unresolved_questions": [],
    }
    base.update(overrides)
    return base


def test_validate_rejects_non_object_and_extra_is_stripped():
    with pytest.raises(ClassificationContractError) as ei:
        validate_provider_output("not-json-object", [])
    assert ei.value.reason == "non_object_output"

    raw = _valid_output()
    raw["extra_attack"] = {"grant_effective": True}
    out = validate_provider_output(raw, [])
    assert "extra_attack" not in out


def test_validate_confidence_matrix():
    with pytest.raises(ClassificationContractError) as ei:
        validate_provider_output(
            _valid_output(role={"value": "x", "confidence": "0.9", "evidence_ids": []}),
            [],
        )
    assert ei.value.reason == "confidence_type_invalid"

    with pytest.raises(ClassificationContractError) as ei:
        validate_provider_output(
            _valid_output(role={"value": "x", "confidence": True, "evidence_ids": []}),
            [],
        )
    assert ei.value.reason == "confidence_type_invalid"

    with pytest.raises(ClassificationContractError) as ei:
        validate_provider_output(
            _valid_output(role={"value": "x", "confidence": 1.5, "evidence_ids": []}),
            [],
        )
    assert ei.value.reason == "confidence_out_of_range"

    with pytest.raises(ClassificationContractError) as ei:
        validate_provider_output(
            _valid_output(role={"value": "x", "confidence": math.nan, "evidence_ids": []}),
            [],
        )
    assert ei.value.reason == "non_finite_confidence"


def test_validate_forged_evidence_ids():
    with pytest.raises(ClassificationContractError) as ei:
        validate_provider_output(
            _valid_output(
                role={"value": "x", "confidence": 0.9, "evidence_ids": ["ev-forged"]}
            ),
            ["ev-real"],
        )
    assert ei.value.reason == "forged_evidence"

    out = validate_provider_output(
        _valid_output(role={"value": "x", "confidence": 0.9, "evidence_ids": ["ev-real"]}),
        ["ev-real"],
    )
    assert out["role"]["evidence_ids"] == ["ev-real"]


def test_provider_contract_failures_via_mock(monkeypatch):
    monkeypatch.setenv("SIQ_AS_CLASSIFIER_ENDPOINT", "https://model.example.com/v1")
    asset = AgentAsset(
        tenant_id="t",
        name="legal-advisor",
        framework="hermes",
        evidence_ids=["ev-1"],
    )

    cases = [
        (_valid_output(role={"value": "x", "confidence": "high", "evidence_ids": []}), "confidence_type_invalid"),
        (
            _valid_output(role={"value": "x", "confidence": 0.9, "evidence_ids": ["ev-forged"]}),
            "forged_evidence",
        ),
        ({"is_agent_candidate": True}, "schema_invalid"),
    ]
    for payload, reason in cases:

        def handler(request: httpx.Request, _payload=payload) -> httpx.Response:
            return httpx.Response(200, json=_provider_ok_response(_payload))

        with pytest.raises(ClassificationContractError) as ei:
            provider_classify(asset, transport=httpx.MockTransport(handler))
        assert ei.value.reason == reason


def test_provider_oversized_body_degrades(monkeypatch):
    monkeypatch.setenv("SIQ_AS_CLASSIFIER_ENDPOINT", "https://model.example.com/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        huge = "x" * (65 * 1024)
        return httpx.Response(200, content=huge.encode(), headers={"content-type": "application/json"})

    with pytest.raises(ClassificationContractError) as ei:
        provider_classify(
            AgentAsset(tenant_id="t", name="x", framework="hermes"),
            transport=httpx.MockTransport(handler),
        )
    assert ei.value.reason == "response_too_large"


def test_classify_asset_contract_failure_needs_review_no_permission_fact(client, monkeypatch):
    monkeypatch.setenv("SIQ_AS_CLASSIFIER", "provider")

    def bad_provider(asset, transport=None):
        raise ClassificationContractError("forged_evidence", "ev-x")

    monkeypatch.setattr("app.classification.provider_classify", bad_provider)

    with session_scope() as session:
        from app.models import Tenant

        if session.query(Tenant).filter(Tenant.id == "tnt-A").count() == 0:
            session.add(Tenant(id="tnt-A", name="Tenant A"))
            session.commit()
        asset = AgentAsset(
            tenant_id="tnt-A",
            name="contract-fail",
            framework="hermes",
            status="candidate",
            source_type="siq_hub",
            source_locator="hub://contract-fail",
        )
        session.add(asset)
        session.flush()
        before_pf = session.query(PermissionFact).count()
        run = classify_asset(session, "tnt-A", asset)
        session.commit()
        session.refresh(asset)
        assert asset.status == "needs_review"
        assert run.output["is_agent_candidate"] is None
        assert run.output["degradation_reason"] == "forged_evidence"
        assert run.output["unresolved_questions"][0].startswith("classification_degraded:forged_evidence:")
        assert session.query(PermissionFact).count() == before_pf
        assert run.classifier == "provider_error:forged_evidence"


def test_model_off_marks_needs_review(client, monkeypatch):
    monkeypatch.setenv("SIQ_AS_CLASSIFIER", "model-off")
    with session_scope() as session:
        from app.models import Tenant

        if session.query(Tenant).filter(Tenant.id == "tnt-A").count() == 0:
            session.add(Tenant(id="tnt-A", name="Tenant A"))
            session.commit()
        asset = AgentAsset(
            tenant_id="tnt-A",
            name="model-off-asset",
            framework="hermes",
            status="candidate",
            source_type="siq_hub",
            source_locator="hub://model-off-asset",
        )
        session.add(asset)
        session.flush()
        classify_asset(session, "tnt-A", asset)
        session.commit()
        session.refresh(asset)
        assert asset.status == "needs_review"


def test_provider_happy_path_persists_trace_metadata(client, monkeypatch):
    """DEV14-B：成功路径落库 model_ref/temperature=0/seed=null/input_summary/tokens。"""
    import httpx

    from app.models import Tenant

    monkeypatch.setenv("SIQ_AS_CLASSIFIER", "provider")
    monkeypatch.setenv("SIQ_AS_CLASSIFIER_ENDPOINT", "https://model.example.com/v1")
    monkeypatch.setenv("SIQ_AS_CLASSIFIER_MODEL", "trace-model-v1")

    output = _valid_output()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(output)}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34},
            },
        )

    real = provider_classify

    def wrapped(asset, transport=None):
        return real(asset, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.classification.provider_classify", wrapped)

    with session_scope() as session:
        if session.query(Tenant).filter(Tenant.id == "tnt-A").count() == 0:
            session.add(Tenant(id="tnt-A", name="A"))
            session.commit()
        asset = AgentAsset(
            tenant_id="tnt-A",
            name="legal-trace-secret-name",
            framework="hermes",
            status="candidate",
            source_type="siq_hub",
            source_locator="hub://legal-trace",
        )
        session.add(asset)
        session.flush()
        run = classify_asset(session, "tnt-A", asset)
        session.commit()
        assert run.model_ref == "trace-model-v1"
        assert run.temperature == 0.0
        assert run.seed is None
        assert run.input_summary is not None
        assert run.input_summary["framework"] == "hermes"
        assert "legal-trace-secret-name" not in str(run.input_summary)
        assert run.prompt_tokens == 12
        assert run.completion_tokens == 34
        assert run.latency_ms is not None
        assert run.error_ref is None


def test_provider_failure_persists_error_ref(client, monkeypatch):
    monkeypatch.setenv("SIQ_AS_CLASSIFIER", "provider")

    def fail_provider(asset, transport=None):
        raise ClassificationContractError("parse_error", "boom")

    monkeypatch.setattr("app.classification.provider_classify", fail_provider)
    with session_scope() as session:
        from app.models import Tenant

        if session.query(Tenant).filter(Tenant.id == "tnt-A").count() == 0:
            session.add(Tenant(id="tnt-A", name="A"))
            session.commit()
        asset = AgentAsset(
            tenant_id="tnt-A",
            name="err-ref",
            framework="hermes",
            status="candidate",
            source_type="siq_hub",
            source_locator="hub://err-ref",
        )
        session.add(asset)
        session.flush()
        run = classify_asset(session, "tnt-A", asset)
        session.commit()
        assert run.error_ref is not None
        assert "error_code" in run.error_ref and "error_digest" in run.error_ref
        assert run.temperature == 0.0
        assert run.seed is None
        assert run.model_ref
