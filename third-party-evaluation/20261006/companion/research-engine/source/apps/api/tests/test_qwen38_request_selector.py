import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from tests.test_qwen38_request_runtime import owned as _owned, request_case as _request

from services import agent_chat_runtime as api, qwen38_request_selector as selector

owned, request_case = _owned, _request


@pytest.fixture
def case(request_case, monkeypatch, tmp_path):
    c = request_case
    c.scope_id = selector.pool_registry._scope_id("cn", c.company.name)
    c.claim = api.DurableProvisionalClaim("siq_analysis", c.owned.binding.session_id,
        "claim-" + "c" * 32, c.owned.binding.owner_id)
    with c.factory() as session:
        grant = session.get(selector.authority.OpenShellDataGrant, c.grant_id)
        grant.project_id = "company:" + c.scope_id
        record = session.get(selector.builder.admission.coordination.ActiveRunLease, c.owned.row.id)
        record.run_id = c.claim.provisional_run_id
        for field in selector.builder.admission.POOL_FIELDS:
            setattr(record, field, None)
        session.add_all([record, grant])
        session.commit()
    c.context = {"company": {"market": "cn", "dir": c.company.name},
                 "tenant_id": "ignored-client-tenant", "user_id": "999"}
    c.root_binding = selector.roots.AuthorityBinding("ri-" + "1" * 32,
        "hi-" + "2" * 32, "hri-" + "2" * 32, "grt-synthetic", 1,
        tmp_path / "root.token", c.scope_id, tmp_path / "relay", "3" * 64,
        "fixture:image", "sha256:" + "4" * 64, "5" * 64)
    c.calls = []
    monkeypatch.setenv("SIQ_OPENSHELL_REQUEST_BACKEND", "qwen38")
    monkeypatch.setenv("SIQ_OPENSHELL_DATA_CLASSIFICATION", "confidential_local")
    monkeypatch.setattr(selector, "session_factory", lambda: c.factory)
    monkeypatch.setattr(selector.recovery, "readiness_snapshot", lambda: {"ready": True})
    def load(root, *, expected_scope_id):
        assert root == selector.builder.runtime.ROOT and expected_scope_id == c.scope_id
        c.calls.append("root")
        return c.root_binding
    monkeypatch.setattr(selector.roots, "load", load)
    monkeypatch.setattr(selector.builder.issuer.client.self_api.SelfIdentityClient,
                        "inspect", lambda self, root: c.calls.append("inspect"))
    c.result = object()
    async def build(factory, **kwargs):
        assert factory is c.factory and kwargs["provisional_run_id"] == c.claim.provisional_run_id
        c.build_args = kwargs
        c.calls.append("build")
        return c.result
    monkeypatch.setattr(selector.builder, "build", build)
    return c


async def select(c, **kwargs):
    values = dict(profile="siq_analysis", requested_target=None, session_id=c.claim.session_id,
        context=c.context, tenant_id="tenant-a", user_id="2")
    values.update(kwargs)
    return await selector.select(**values)


async def activate(c, plan, **kwargs):
    values = dict(profile="siq_analysis", session_id=c.claim.session_id, tenant_id="tenant-a", user_id="2")
    values.update(kwargs)
    return await selector.activate(plan, c.claim, **values)


def row(c):
    with c.factory() as session:
        return session.get(selector.builder.admission.coordination.ActiveRunLease, c.owned.row.id).model_dump()


@pytest.mark.asyncio
async def test_selection_is_read_only_and_real_attach_uses_verified_principal(case):
    c = case
    before = row(c)
    plan = await select(c)
    assert row(c) == before and not list(c.root.iterdir())
    assert c.owner.status() is None
    assert plan.tenant_id == "tenant-a" and plan.user_id == "2"
    assert plan.pool_market == "cn" and plan.pool_company == c.company.name
    assert repr(plan) == "RequestSelection(execution_permitted=False)"
    assert await activate(c, plan) is c.result
    assert row(c)["pool_binding_run_id"].startswith("qwen-request-")
    assert row(c)["run_id"] == c.claim.provisional_run_id and row(c)["status"] == "running"
    assert c.build_args["binding"].pool_scope_id == c.scope_id
    assert c.build_args["authorized"] is plan.authorized
    assert c.build_args["isolated_candidate"] is False


@pytest.mark.asyncio
async def test_candidate_selection_pins_identity_service_and_rechecks_deployment(case, monkeypatch):
    c = case
    monkeypatch.setattr(selector.deployment, "isolated", lambda factory: True)
    clients = []
    class Client:
        def __init__(self, *, isolated_candidate):
            clients.append(isolated_candidate)
        def inspect(self, root):
            assert root == c.root_binding
    monkeypatch.setattr(selector.builder.issuer.client.self_api, "SelfIdentityClient", Client)
    plan = await select(c)
    assert plan.isolated_candidate is True
    assert await activate(c, plan) is c.result
    assert clients == [True, True] and c.build_args["isolated_candidate"] is True


@pytest.mark.asyncio
async def test_changed_candidate_deployment_cannot_attach_or_build(case, monkeypatch):
    c = case
    plan = await select(c)
    monkeypatch.setattr(selector.deployment, "isolated", lambda factory: True)
    with pytest.raises(selector.RequestSelectionError, match="activation_unconfirmed"):
        await activate(c, plan)
    assert "build" not in c.calls and row(c)["pool_binding_run_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [{"tenant_id": "other"}, {"user_id": "3"}, {"user_id": None},
    {"session_id": "user-3-analysis-wrong"}, {"requested_target": "host"},
    {"context": {}}, {"context": {"company": {"market": "cn", "dir": "../outside"}}},
    {"context": {"company": {"market": "cn", "dir": "600000-Synthetic", "code": "999999"}}}])
async def test_selection_denies_before_issuer_or_claim_write(case, override):
    c = case
    before = row(c)
    with pytest.raises(selector.RequestSelectionError, match="selection_denied"):
        await select(c, **override)
    assert not c.calls and row(c) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["revoked", "unready", "public", "symlink"])
async def test_selection_live_grant_readiness_classification_and_path_checks(case, monkeypatch, fault):
    c = case
    if fault == "revoked":
        from tests.test_qwen38_request_runtime import revoke
        revoke(c)
    elif fault == "unready":
        monkeypatch.setattr(selector.recovery, "readiness_snapshot", lambda: {"ready": False})
    elif fault == "public":
        monkeypatch.setenv("SIQ_OPENSHELL_DATA_CLASSIFICATION", "public_research")
    else:
        other = c.company.with_name("outside")
        c.company.rename(other)
        c.company.symlink_to(other, target_is_directory=True)
    with pytest.raises(selector.RequestSelectionError, match="selection_denied"):
        await select(c)
    assert not c.calls


@pytest.mark.asyncio
async def test_legacy_and_other_profile_do_not_read_grants_or_issuer(case, monkeypatch):
    c = case
    monkeypatch.delenv("SIQ_OPENSHELL_REQUEST_BACKEND")
    assert await select(c) is None
    monkeypatch.setenv("SIQ_OPENSHELL_REQUEST_BACKEND", "qwen38")
    assert await select(c, profile="siq_assistant") is None
    assert not c.calls
    monkeypatch.setenv("SIQ_OPENSHELL_REQUEST_BACKEND", "typo")
    with pytest.raises(selector.RequestSelectionError, match="backend_invalid"):
        await select(c)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["grant", "root", "claim", "user", "disabled"])
async def test_changed_selection_cannot_reach_builder(case, monkeypatch, fault):
    c = case
    plan = await select(c)
    if fault == "grant":
        from tests.test_qwen38_request_runtime import revoke
        revoke(c)
    elif fault == "root":
        c.root_binding = replace(c.root_binding, binding_sha256="f" * 64)
    elif fault == "claim":
        c.claim = replace(c.claim, owner_id="different-owner")
    elif fault == "disabled":
        monkeypatch.setenv("SIQ_OPENSHELL_REQUEST_BACKEND", "legacy")
    with pytest.raises(selector.RequestSelectionError):
        await activate(c, plan, **({"user_id": "3"} if fault == "user" else {}))
    assert "build" not in c.calls and row(c)["pool_binding_run_id"] is None


@pytest.mark.asyncio
async def test_activation_failure_retains_committed_original_claim(case, monkeypatch):
    c = case
    plan = await select(c)
    async def failed(*args, **kwargs):
        raise RuntimeError("private-diagnostic-must-not-escape")
    monkeypatch.setattr(selector.builder, "build", failed)
    with pytest.raises(selector.RequestSelectionError, match="^qwen_request_activation_unconfirmed$"):
        await activate(c, plan)
    assert row(c)["status"] == "running" and row(c)["pool_binding_run_id"].startswith("qwen-request-")


@pytest.mark.asyncio
async def test_actual_api_selection_never_falls_back_on_denial(case, monkeypatch):
    c = case
    async def forbidden(*args):
        pytest.fail("legacy provisioning called")
    monkeypatch.setattr(api, "_requested_run_route_with_scope_lifecycle", forbidden)
    plan = await api._requested_api_route("siq_analysis", None, c.claim.session_id, c.context,
        tenant_id="tenant-a", user_id="2")
    assert isinstance(plan, selector.RequestSelection)
    with pytest.raises(selector.RequestSelectionError):
        await api._requested_api_route("siq_analysis", None, c.claim.session_id, c.context,
            tenant_id="other", user_id="2")


@pytest.mark.asyncio
async def test_actual_api_failed_activation_never_uses_generic_release(case, monkeypatch):
    c = case
    plan = await select(c)
    async def failed(*args, **kwargs):
        raise RuntimeError("unknown")
    async def forbidden(*args, **kwargs):
        pytest.fail("generic release after attach")
    monkeypatch.setattr(selector.builder, "build", failed)
    monkeypatch.setattr(api, "_release_provisional_durable_claim", forbidden)
    with pytest.raises(selector.RequestSelectionError, match="activation_unconfirmed"):
        await api._claim_create_and_bind_routed_run("synthetic", [], profile="siq_analysis",
            session_id=c.claim.session_id, route=plan, provisional_claim=c.claim,
            tenant_id="tenant-a", user_id="2")
    assert row(c)["status"] == "running" and row(c)["pool_binding_run_id"] is not None


@pytest.mark.asyncio
async def test_plan_cannot_be_used_as_an_authenticated_transport(case):
    plan = await select(case)
    from services import qwen38_request_api
    assert qwen38_request_api.handles(plan)
    assert not await qwen38_request_api.current(plan, session_id=case.claim.session_id)
    with pytest.raises(selector.RequestSelectionError, match="plan_not_materialized"):
        await selector.builder.hermes.create_run("synthetic", [], profile="siq_analysis", route=plan)


@pytest.mark.asyncio
async def test_activation_cancellation_retains_attached_claim(case, monkeypatch):
    c = case
    entered = asyncio.Event()
    async def wait(*args, **kwargs):
        entered.set()
        await asyncio.Future()
    monkeypatch.setattr(selector.builder, "build", wait)
    plan = await select(c)
    task = asyncio.create_task(activate(c, plan))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert row(c)["status"] == "running" and row(c)["pool_binding_run_id"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_both_chat_entries_select_scope_before_preflight_without_starting(case, monkeypatch, streaming):
    c = case
    released = []
    class PreflightStop(RuntimeError):
        pass
    async def envelope(*args, **kwargs):
        assert c.calls == ["root", "inspect"]
        return SimpleNamespace(all_attachments=[], message_hash="synthetic", user_display_message="synthetic")
    async def claim(*args):
        return c.claim
    async def release(*args, **kwargs):
        released.append(args)
    async def preflight(*args, **kwargs):
        assert kwargs["isolate_runtime_context"] is True
        assert (kwargs["tenant_id"], kwargs["user_id"]) == ("tenant-a", "2")
        assert kwargs["research_identity_scope"]["market"] == "CN"
        assert kwargs["research_identity_scope"]["company_id"] == "600000"
        assert row(c)["pool_binding_run_id"] is None
        assert "build" not in c.calls
        raise PreflightStop
    monkeypatch.setattr(api, "_prepare_chat_request_envelope", envelope)
    monkeypatch.setattr(api, "_acquire_durable_provisional_claim", claim)
    monkeypatch.setattr(api, "_release_provisional_durable_claim", release)
    monkeypatch.setattr(api, "_load_chat_run_preflight_context", preflight)
    def forbidden_shortcut(*args, **kwargs):
        pytest.fail("governed request must not read global catalog or unscoped reply cache")
    monkeypatch.setattr(api, "build_wiki_catalog_reply", forbidden_shortcut)
    monkeypatch.setattr(api, "_recent_duplicate_reply", forbidden_shortcut)
    monkeypatch.setattr(api, "has_active_run", lambda *_: False)
    monkeypatch.setattr(api, "_should_use_analysis_completion_guard", lambda *_: False)
    kwargs = dict(profile="siq_analysis", session_id=c.claim.session_id,
        context=c.context, tenant_id="tenant-a", user_id="2")
    with pytest.raises(PreflightStop):
        if streaming:
            async for _ in api._stream_chat_reply_impl("synthetic", object(), object(), **kwargs):
                pass
        else:
            await api._collect_chat_reply_impl("synthetic", object(), **kwargs)
    assert released == [(c.claim.profile, c.claim.session_id, c.claim.provisional_run_id, c.claim.owner_id)]
    assert row(c)["pool_binding_run_id"] is None and c.calls == ["root", "inspect"]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["root", "company", "report", "filing", "postgres", "resolved_period"])
async def test_hidden_foreign_company_selector_denied_before_host_preflight(case, source):
    c = case
    context = {**c.context, "company": dict(c.context["company"])}
    if source == "root":
        context["company_id"] = "600999"
    elif source == "company":
        context["company"]["id"] = "600999"
    else:
        context[source] = {"company_id": "600999"}
    before = row(c)
    with pytest.raises(selector.RequestSelectionError, match="selection_denied"):
        await select(c, context=context)
    assert c.calls == [] and row(c) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("market", "US"), ("company_id", "US:600000")])
async def test_nested_market_conflict_cannot_use_same_numeric_company_code(case, field, value):
    c = case
    context = {**c.context, "report": {field: value}}
    with pytest.raises(selector.RequestSelectionError, match="selection_denied"):
        await select(c, context=context)
    assert c.calls == []


@pytest.mark.asyncio
async def test_authorized_selection_binds_host_company_before_preflight(case):
    from services import agent_runtime_host_scope as host, confidential_auxiliary_models as auxiliary

    c = case
    with auxiliary.scope(True), host.scope():
        with pytest.raises(host.HostRetrievalDenied, match="scope_missing"):
            api._resolve_company_dir("foreign company", c.context)
        plan = await api._requested_api_route("siq_analysis", None, c.claim.session_id,
            c.context, tenant_id="tenant-a", user_id="2")
        assert host.company_dir() == c.company
        assert api._resolve_company_dir("foreign company", c.context) == c.company
        assert isinstance(plan, selector.RequestSelection)
        assert row(c)["pool_binding_run_id"] is None


@pytest.mark.asyncio
async def test_revoked_selection_never_binds_host_company(case):
    from tests.test_qwen38_request_runtime import revoke

    from services import agent_runtime_host_scope as host, confidential_auxiliary_models as auxiliary

    c = case
    revoke(c)
    with auxiliary.scope(True), host.scope():
        with pytest.raises(selector.RequestSelectionError, match="selection_denied"):
            await api._requested_api_route("siq_analysis", None, c.claim.session_id,
                c.context, tenant_id="tenant-a", user_id="2")
        with pytest.raises(host.HostRetrievalDenied, match="scope_missing"):
            api._resolve_company_dir("foreign company", c.context)


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_legacy_host_binding_checks_live_business_grant(case, monkeypatch, revoked):
    from tests.test_qwen38_request_runtime import revoke

    from services import agent_runtime_host_scope as host, confidential_auxiliary_models as auxiliary

    c = case
    if revoked:
        revoke(c)

    class AsyncFacade:
        async def __aenter__(self):
            self.session = c.factory()
            return self

        async def __aexit__(self, *args):
            self.session.close()

        async def exec(self, statement):
            return self.session.exec(statement)

    monkeypatch.setattr(api, "PROJECT_ROOT", selector.builder.runtime.ROOT)
    monkeypatch.setattr(api, "AsyncSession", lambda *_: AsyncFacade())
    route = SimpleNamespace(target="openshell", pool_market="cn", pool_company=c.company.name,
                            pool_binding=SimpleNamespace(scope_id=c.scope_id))
    with auxiliary.scope(True), host.scope():
        if revoked:
            with pytest.raises(selector.authority.DataScopeAuthorizationError, match="live_grant_denied"):
                await api._bind_host_retrieval_scope(route, tenant_id="tenant-a", user_id="2")
            with pytest.raises(host.HostRetrievalDenied, match="scope_missing"):
                host.company_dir()
        else:
            await api._bind_host_retrieval_scope(route, tenant_id="tenant-a", user_id="2")
            assert host.company_dir() == c.company


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("fault", ["revoked", "foreign_user", "missing_company"])
async def test_denied_qwen_entry_cannot_read_attachments_catalog_cache_or_claim(case, monkeypatch, streaming, fault):
    c = case
    before = row(c)
    if fault == "revoked":
        from tests.test_qwen38_request_runtime import revoke
        revoke(c)
    def forbidden(*args, **kwargs):
        pytest.fail("unapproved entry read a shortcut or created a provisional claim")
    for name in ("_prepare_chat_request_envelope", "build_wiki_catalog_reply", "_recent_duplicate_reply",
                 "_acquire_durable_provisional_claim", "has_active_run", "stream_active_run_events"):
        monkeypatch.setattr(api, name, forbidden)
    kwargs = dict(profile="siq_analysis", session_id=c.claim.session_id,
                  context={} if fault == "missing_company" else c.context,
                  tenant_id="tenant-a", user_id="3" if fault == "foreign_user" else "2")
    if streaming:
        import json
        events = [event async for event in api.stream_chat_reply("请列出所有公司", object(), object(), **kwargs)]
        assert [event['event'] for event in events] == ['error']
        error = json.loads(events[0]['data'])
        assert error['error_code'] == 'request_access_denied' and error['retryable'] is False
    else:
        with pytest.raises(selector.RequestSelectionError, match="selection_denied"):
            await api.collect_chat_reply("请列出所有公司", object(), **kwargs)
    assert row(c) == before and not c.calls


@pytest.mark.asyncio
async def test_governed_new_stream_does_not_replay_another_active_scope(case, monkeypatch):
    c = case
    async def envelope(*args, **kwargs):
        return SimpleNamespace(all_attachments=[], message_hash="synthetic", user_display_message="synthetic")
    def forbidden(*args, **kwargs):
        pytest.fail("new request reused an existing stream without its original scope")
    monkeypatch.setattr(api, "_prepare_chat_request_envelope", envelope)
    monkeypatch.setattr(api, "has_active_run", lambda *args: True)
    monkeypatch.setattr(api, "stream_active_run_events", forbidden)
    monkeypatch.setattr(api, "_acquire_durable_provisional_claim", forbidden)
    values = [v async for v in api.stream_chat_reply("synthetic", object(), object(),
        profile="siq_analysis", session_id=c.claim.session_id, context=c.context,
        tenant_id="tenant-a", user_id="2")]
    assert len(values) == 1 and values[0]["event"] == "error"
    assert '"active_run_conflict"' in values[0]["data"]
    assert c.calls == ["root", "inspect"]
