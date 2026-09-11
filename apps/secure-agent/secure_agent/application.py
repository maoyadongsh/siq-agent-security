"""Runnable application: model preparation, committed replay, actual scoped effects."""

import hashlib
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

from .authority import LocalDaemon, TaskAuthority, deploy_application_grant
from .confidential import NOTE
from .contracts import (
    AgentError,
    DataSensitivity,
    TaskState,
    UserTask,
    canonical,
    digest,
)
from .fixtures import FixtureServices
from .gateway import ToolGateway
from .models import ModelProvider
from .routing import application_router
from .runtime import AgentRuntime
from .security import EvidenceClient, Identity
from .skills import SkillRegistry, SkillRunner, render_report
from .tools import EffectObservers, ToolAdapters


class CommittedProvider:
    """Reuse actual model output only after a full, authorized source replay.

    It delegates recipient selection to the original provider and is never a
    substitute for a failed/missing StepFun response.
    """

    def __init__(self, provider, plan, research):
        self.name, self.provider, self._plan, self._research = provider.name, provider, plan, research

    def plan(self, _task, _catalog):
        return self._plan

    def research(self, _question, sources):
        if sources != self._research.sources:
            raise AgentError("source_changed_after_commitment")
        return self._research

    def recipient(self, contact, candidates, context):
        return self.provider.recipient(contact, candidates, context)


def effect_requirements(report, url):
    endpoint = urlsplit(url)
    payload = canonical({"body": report.content})
    return [
        {"requirement_id": "report", "effect_type": "file.write",
         "resource_ref": "filesystem:sha256:" + digest({"domain": "filesystem", "value": report.path}),
         "expected_digest": report.digest, "minimum_independence": "host_independent", "minimum_coverage": "partial"},
        {"requirement_id": "delivery", "effect_type": "network.request",
         "resource_ref": "network:sha256:" + digest({"domain": "network", "value": endpoint.hostname}),
         "expected_digest": digest({"method": "POST", "uri": endpoint.path, "body_digest": hashlib.sha256(payload).hexdigest()}),
         "minimum_independence": "external_independent", "minimum_coverage": "partial",
         "expected_endpoint": {"scheme": endpoint.scheme, "host": endpoint.hostname, "port": str(endpoint.port)}}]


class SecureApplication:
    def __init__(self, repo: Path, daemon: LocalDaemon, fixtures: FixtureServices, model: ModelProvider):
        self.repo, self.daemon, self.fixtures = repo, daemon, fixtures
        self.model = application_router(model)

    def run(self, prompt: str, *, repository: str, question: str, scope: tuple[str, ...],
            effect_mode: str = "normal", github_endpoint: str | None = None,
            before_execution=None, changed=None, approval_required=False, on_hold=None, trifecta=False,
            source_sensitivity=DataSensitivity.PUBLIC, requested_output="delivery",
            confidential_name: str = ".env") -> dict:
        started = perf_counter()
        model_call_start = len(getattr(self.model, "calls", []))
        transition_start = len(self.model.transitions)
        run_id = uuid4().hex
        root = self.daemon.directory / "runs" / run_id
        workspace, assets = root / "workspace", root / "assets"
        workspace.mkdir(parents=True, mode=0o700)
        assets.mkdir(mode=0o700)
        contact_path = assets / "contacts.json"
        contact_path.write_bytes(canonical(self.fixtures.contacts))
        contact_path.chmod(0o600)
        confidential_path = assets / confidential_name if trifecta else None
        if confidential_path is not None:
            with confidential_path.open("xb") as note:
                note.write(NOTE)
            confidential_path.chmod(0o600)
        task = UserTask(prompt, repository, question, scope, str(workspace / "report.md"),
                        source_sensitivity=source_sensitivity, requested_output=requested_output)
        github = github_endpoint or self.fixtures.endpoint + "/github"
        mcp = self.fixtures.endpoint + "/mcp"
        url = self.fixtures.endpoint + "/messages/" + digest(self.fixtures.contacts[task.contact])
        agent_id = "secure-agent-" + run_id
        # Grant network scope names explicit host:port endpoints; ports match
        # exactly (ADR-025), so the fixture's dynamic port must be granted as-is.
        def granted_endpoint(target):
            parts = urlsplit(target)
            return f"{parts.hostname}:{parts.port or (443 if parts.scheme == 'https' else 80)}"
        grant = deploy_application_grant(self.daemon.admin, self.repo, agent_id, workspace,
                                         contact_path, [granted_endpoint(github), granted_endpoint(self.fixtures.endpoint)],
                                         approval_required=approval_required)
        preview_id = Identity("hermes", "review-session-" + run_id, agent_id, "review-" + run_id)
        self.model.bind(preview_id.task_id, task.source_sensitivity)
        preview_state = TaskState(preview_id.task_id, prompt, self.model.name)
        def preview_changed(state):
            if changed:
                changed({"phase": "preparation", "task": asdict(state), "intent": None})

        preview_changed(preview_state)
        preview = TaskAuthority(self.daemon.admin, self.daemon.decision, preview_id, task,
            github=github, mcp=mcp, contacts_path=contact_path, contacts=self.fixtures.contacts, delivery_url=url)
        preview_tools = ToolAdapters(preview, self.fixtures)
        gateway = ToolGateway(preview.client, preview_tools.executors(), preview_state,
                              prepare=preview.prepare, observation=preview_tools.observation, changed=preview_changed,
                              describe_provenance=preview.describe_provenance)
        preview_tools.gateway = gateway
        planning = perf_counter()
        plan = self.model.plan(task, SkillRegistry.catalog())
        selected_skills = [call.name for call in plan.skills]
        preview_state.selected_skills = selected_skills
        planning_ms = (perf_counter() - planning) * 1000
        preview_state.current_skill = "secure-research"
        preview_state.current_step = "reading repository and preparing committed report"
        preview_state.status = "running"
        preview_changed(preview_state)
        runner = SkillRunner(gateway, self.model, preview.client, github_endpoint=github,
                             contacts_path=str(contact_path), mcp_endpoint=mcp, sensitivity=task.source_sensitivity)
        researching = perf_counter()
        research = runner.run(plan.skills[0])
        research_ms = (perf_counter() - researching) * 1000
        # The operator-fixed path is used for the commitment. A candidate plan
        # that substitutes a path later fails SIQ's provenance/resource checks.
        artifact = render_report(task.report_path, research) if "secure-report" in selected_skills else None
        requirements = effect_requirements(artifact, url)[:len(plan.skills)-1] if artifact else []
        identity = Identity("hermes", "execution-session-" + run_id, agent_id, "execution-" + run_id)
        self.model.bind(identity.task_id, task.source_sensitivity)
        authority = TaskAuthority(self.daemon.admin, self.daemon.decision, identity, task,
            github=github, mcp=mcp, contacts_path=contact_path, contacts=self.fixtures.contacts,
            delivery_url=url, requirements=requirements, revision=research.sources[0].revision,
            approval_required=approval_required, confidential_path=confidential_path, selected_skills=selected_skills)
        state = TaskState(identity.task_id, prompt, self.model.name)
        state.selected_skills = selected_skills
        def execution_changed(state):
            if changed:
                changed({"phase": "execution", "task": asdict(state), "intent": authority.intent})

        content = artifact.content if artifact else ""
        tools = ToolAdapters(authority, self.fixtures, effect_mode=effect_mode, expected_report=content)
        effects = EffectObservers(authority, self.fixtures, content)
        gateway = ToolGateway(authority.client, tools.executors(), state, observer=effects,
                              prepare=authority.prepare, observation=tools.observation, changed=execution_changed,
                              describe_provenance=authority.describe_provenance,
                              on_hold=(lambda request, decision: on_hold(request, decision, authority)) if on_hold else None)
        tools.gateway = gateway
        provider = CommittedProvider(self.model, plan, research)
        runner = SkillRunner(gateway, provider, authority.client, github_endpoint=github,
                             contacts_path=str(contact_path), mcp_endpoint=mcp, verify_report=approval_required,
                             confidential_path=str(confidential_path) if confidential_path else None,
                             sensitivity=task.source_sensitivity)
        if before_execution is not None:
            before_execution(authority)
        runtime = AgentRuntime(provider, runner, EvidenceClient(self.daemon.admin), state, changed=execution_changed)
        runtime.run(task)
        # Even a blocked attempt has a current, server-derived incomplete state.
        if state.completion is None:
            state.completion = EvidenceClient(self.daemon.admin).completion(identity.task_id)
        state.timings_ms["model_planning"] = [planning_ms]
        state.timings_ms["preparation_research"] = [research_ms]
        state.timings_ms["e2e_task"] = [(perf_counter() - started) * 1000]
        result = {"schema_version": "secure-agent-run/v1", "provider": self.model.name,
            "source_sensitivity": task.source_sensitivity.value,
            "provider_transitions": self.model.transitions[transition_start:],
            "source_mode": "live_github" if github_endpoint else "controlled_fixture",
            "model_calls": getattr(self.model, "calls", [])[model_call_start:],
            "task": asdict(state), "preparation": {"task_id": preview_id.task_id, "actions": preview_state.actions},
            "grant": grant, "intent": authority.intent,
            "report": {"path": artifact.path, "digest": artifact.digest} if artifact else None,
            "research": {"summary": research.summary, "findings": research.findings,
                         "source_digests": [s.digest for s in research.sources]},
            "messages": [m for m in self.fixtures.messages() if m["action_id"] in {a["action_id"] for a in state.actions}],
            "limitations": [
                "verification is scoped to the committed report bytes and controlled HTTP receiver",
                "routing-only observations contain signed provenance references and value digests; not universal semantic taint",
                "same-host test oracle is not an independently administered production attestor"]}
        (root / "result.json").write_bytes(canonical(result))
        (root / "result.json").chmod(0o600)
        return result
