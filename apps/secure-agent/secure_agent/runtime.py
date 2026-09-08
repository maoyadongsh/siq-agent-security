"""Task orchestration and UI state. It never decides authorization or completion."""

from collections.abc import Callable
from time import perf_counter

from .contracts import AgentError, TaskState, UserTask
from .gateway import Blocked, WaitingForApproval
from .models import ModelProvider
from .security import EvidenceClient
from .skills import SkillRegistry, SkillRunner


class AgentRuntime:
    def __init__(self, model: ModelProvider, runner: SkillRunner, evidence: EvidenceClient,
                 state: TaskState, *, changed: Callable[[TaskState], None] | None = None):
        self._model, self._runner, self._evidence = model, runner, evidence
        self.state, self._changed = state, changed

    def _publish(self):
        if self._changed:
            self._changed(self.state)

    def run(self, task: UserTask) -> TaskState:
        if self.state.status != "planning" or self.state.actions:
            raise AgentError("task_already_started")
        started = perf_counter()
        try:
            self._publish()
            planned = perf_counter()
            plan = self._model.plan(task, SkillRegistry.catalog())
            self.state.timings_ms["model_planning"] = [(perf_counter() - planned) * 1000]
            self.state.status = "running"
            for call in plan.skills:
                self.state.current_skill, self.state.current_step = call.name, "executing skill"
                self._publish()
                self._runner.run(call)
            self.state.current_step = "checking independent evidence"
            self._publish()
            self.state.completion = self._evidence.completion(self.state.task_id)
            self.state.status = self.state.completion["status"]
            self.state.current_step = "finished"
        except WaitingForApproval:
            self.state.status, self.state.current_step = "waiting_approval", "human approval required"
        except Blocked as exc:
            self.state.status, self.state.error_code = "blocked", str(exc)
        except AgentError as exc:
            self.state.status, self.state.error_code = "failed", str(exc)
        except Exception:  # noqa: BLE001 -- redact arbitrary tool/provider exceptions at the UI boundary
            # No model text, tool data, credentials or arbitrary exception string
            # is exposed to task observers.
            self.state.status, self.state.error_code = "failed", "agent_internal_error"
        finally:
            self.state.timings_ms["e2e_task"] = [(perf_counter() - started) * 1000]
            self._publish()
        return self.state
