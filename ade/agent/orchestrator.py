"""Agent loop: event -> plan -> validate -> execute -> record -> measure.

The orchestrator is deliberately thin. All intelligence is in the planner
(LLM) and all side effects are in the executor (allowlisted, dry-run aware,
approval-gated). Every decision is written to the audit log in memory and
emitted as CloudWatch metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ade.agent.actions import ActionExecutor, ActionResult
from ade.agent.memory import MemoryStore
from ade.agent.planner import Plan, PlanValidationError, plan_for_event
from ade.config import Settings
from ade.llm import PlannerClient
from ade.monitoring.metrics import MetricsSink

logger = logging.getLogger("ade.orchestrator")


@dataclass
class AgentRunReport:
    event_type: str
    plan: Plan | None
    results: list[ActionResult] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.error == "" and all(r.status != "failed" for r in self.results)


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        planner_client: PlannerClient,
        memory: MemoryStore,
        executor: ActionExecutor | None = None,
        metrics: MetricsSink | None = None,
    ) -> None:
        self.settings = settings
        self.planner_client = planner_client
        self.memory = memory
        self.executor = executor or ActionExecutor(settings)
        self.metrics = metrics or MetricsSink(settings.metrics_namespace, enabled=False)

    def handle_event(self, event: dict[str, Any]) -> AgentRunReport:
        event_type = str(event.get("type", "unknown"))
        report = AgentRunReport(event_type=event_type, plan=None)

        # Circuit breaker: stop replanning incidents that keep failing.
        incident_id = event.get("incident_id")
        if incident_id and (
            self.memory.remediation_attempts(str(incident_id))
            >= self.settings.max_remediation_attempts
        ):
            logger.warning("incident %s exceeded retry budget; escalating", incident_id)
            result = self.executor.execute(
                "escalate",
                {"incident_id": incident_id, "reason": "remediation retry budget exhausted"},
                requires_approval=False,
            )
            report.results.append(result)
            self.metrics.count("EscalationsTriggered")
            return report

        try:
            plan = plan_for_event(
                self.planner_client,
                event,
                self.memory.snapshot(),
                max_actions=self.settings.max_actions_per_plan,
            )
        except PlanValidationError as exc:
            report.error = f"plan rejected: {exc}"
            logger.error(report.error)
            self.metrics.count("PlansRejected")
            self.executor.execute(
                "send_alert",
                {"subject": "ADE plan rejected", "event": event, "reason": str(exc)},
                requires_approval=False,
            )
            return report
        except Exception as exc:
            report.error = f"planner unavailable: {exc}"
            logger.exception("planner call failed")
            self.metrics.count("PlannerErrors")
            return report

        report.plan = plan
        self.metrics.count("PlansAccepted")
        self.metrics.gauge("PlanActionCount", len(plan.actions))

        for action in plan.actions:
            result = self.executor.execute(
                action.name, action.params, action.requires_approval
            )
            report.results.append(result)
            self.metrics.count(f"Action.{result.status}")
            if incident_id and result.status in ("executed", "dry_run"):
                self.memory.record_remediation(str(incident_id), action.name, result.status)

        self.memory.record_decision(
            event,
            {
                "reasoning": plan.reasoning,
                "risk": plan.risk,
                "actions": [
                    {"name": r.action, "status": r.status} for r in report.results
                ],
            },
        )
        return report
