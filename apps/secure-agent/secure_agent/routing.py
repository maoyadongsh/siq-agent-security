"""Constrained model routing; transitions are explicit, with no failure fallback."""

import os
from dataclasses import asdict, replace

from .contracts import (
    AgentError,
    DataSensitivity,
    TaskPlan,
    canonical,
    highest_sensitivity,
    strict_json,
)
from .model_policy import CALL_CONTEXT, CallContext, ModelPolicy
from .models import from_environment


class ModelRouter:
    def __init__(self, planner, *, local=None, local_factory=None, policy=None):
        self.planner, self.local, self.local_factory = planner, local, local_factory
        self.policy = policy or ModelPolicy()
        self.name = planner.name
        self.model = getattr(planner, "model", None)
        self.calls, self.transitions = [], []
        self.task_id, self.sensitivity = "unbound", DataSensitivity.PUBLIC

    def bind(self, task_id, sensitivity):
        self.task_id = task_id
        self.sensitivity = DataSensitivity.parse(sensitivity)

    def _local(self):
        if self.planner.capabilities.locality in ("local_dgx", "fixture"):
            return self.planner
        if self.local is None and self.local_factory:
            self.local = self.local_factory()
        if self.local is None or self.local.capabilities.locality != "local_dgx":
            raise AgentError("dgx_local_model_unavailable")
        return self.local

    def _invoke(self, provider, operation, *args, sensitivity):
        context = CALL_CONTEXT.set(CallContext(self.task_id, sensitivity,
                                               self.policy.internal_remote, self.policy.secret_local))
        before = len(getattr(provider, "calls", []))
        try:
            return getattr(provider, operation)(*args)
        finally:
            self.calls.extend(getattr(provider, "calls", [])[before:])
            CALL_CONTEXT.reset(context)

    def _select(self, sensitivity, *, reason):
        remote_allowed = sensitivity == DataSensitivity.PUBLIC or (
            sensitivity == DataSensitivity.INTERNAL and self.policy.internal_remote)
        use_local = not remote_allowed or self.policy.public_research_local
        target = self.planner
        allowed = sensitivity != DataSensitivity.SECRET or self.policy.secret_local
        if use_local:
            try:
                target = self._local()
            except AgentError:
                self.transitions.append({"event": "provider_transition", "from_provider": self.planner.name,
                    "to_provider": "ornith", "reason": "local_unavailable", "task_id": self.task_id,
                    "sensitivity": sensitivity.value, "allowed": False})
                raise
        if target is not self.planner or not allowed:
            self.transitions.append({"event": "provider_transition", "from_provider": self.planner.name,
                "to_provider": target.name, "reason": reason, "task_id": self.task_id,
                "sensitivity": sensitivity.value, "allowed": allowed})
        if not allowed:
            raise AgentError("model_egress_denied")
        return target

    def switch(self, provider, *, reason="operator_switch"):
        # Only operator code calls this method; there is no model/tool dispatch route.
        permitted = self.sensitivity in provider.capabilities.allowed_sensitivity
        if self.sensitivity == DataSensitivity.SECRET:
            permitted = permitted and self.policy.secret_local
        self.transitions.append({"event": "provider_transition", "from_provider": self.planner.name,
            "to_provider": provider.name, "reason": reason, "task_id": self.task_id,
            "sensitivity": self.sensitivity.value, "allowed": permitted})
        if not permitted:
            raise AgentError("model_egress_denied")
        self.planner, self.name = provider, provider.name

    def plan(self, task, catalog):
        # Public callers explicitly classify task metadata as public. For private
        # workloads even paths, repository name and free text stay off remote APIs.
        safe = task
        if task.source_sensitivity != DataSensitivity.PUBLIC and self.planner.capabilities.locality == "remote":
            description = {"research": "Only analyze selected files. Do not save or deliver a report.",
                "report": "Analyze selected files and save a report. Do not deliver it.",
                "delivery": "Analyze selected files, save a report and deliver it to Alice."}[task.requested_output]
            safe = replace(task, prompt=description,
                question="Review selected files for security issues", repository="private/repository",
                scope=tuple(f"source-{i}" for i in range(len(task.scope))), report_path="report.md",
                contact="Alice", source_sensitivity=DataSensitivity.PUBLIC)
        elif self.planner.capabilities.locality == "remote":
            safe = replace(task, report_path="report.md")
        plan = self._invoke(self.planner, "plan", safe, catalog, sensitivity=safe.source_sensitivity)
        plan = TaskPlan.parse(strict_json(canonical(asdict(plan))))
        limit = {"research": 1, "report": 2, "delivery": 3}[task.requested_output]
        if len(plan.skills) > limit:
            raise AgentError("plan_exceeds_task_scope")
        if len(plan.skills) < limit:
            raise AgentError("plan_goal_incomplete")
        # Bind only the exact operator-provided aliases, never repair arbitrary
        # model substitutions. The resulting proposal still faces SIQ authorization.
        calls = []
        for call in plan.skills:
            value = call.input
            if call.name == "secure-research" and safe is not task:
                value = replace(value,
                    repository=task.repository if value.repository == safe.repository else value.repository,
                    scope=task.scope if value.scope == safe.scope else value.scope,
                    question=task.question if value.question == safe.question else value.question)
            if call.name == "secure-report" and value.path == safe.report_path:
                value = replace(value, path=task.report_path)
            calls.append(replace(call, input=value))
        return TaskPlan(plan.goal, tuple(calls))

    def research(self, question, sources):
        sensitivity = highest_sensitivity(self.sensitivity, *(s.sensitivity for s in sources))
        provider = self._select(sensitivity, reason="sensitivity_policy")
        return self._invoke(provider, "research", question, sources, sensitivity=sensitivity)

    def recipient(self, contact, candidates, context):
        provider = self._select(self.sensitivity, reason="recipient_context_policy")
        return self._invoke(provider, "recipient", contact, candidates, context, sensitivity=self.sensitivity)


def application_router(provider):
    if isinstance(provider, ModelRouter):
        return provider
    def flag(name, default):
        value = os.environ.get(name, default)
        if value not in ("true", "false"):
            raise AgentError("model_policy_invalid")
        return value == "true"

    policy = ModelPolicy(public_research_local=flag("SIQ_PUBLIC_RESEARCH_LOCAL", "true"),
                         internal_remote=flag("SIQ_INTERNAL_REMOTE", "false"),
                         secret_local=flag("SIQ_SECRET_LOCAL", "false"))
    return ModelRouter(provider, local_factory=lambda: from_environment(provider="ornith"), policy=policy)
