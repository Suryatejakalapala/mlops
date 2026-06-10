import pytest

from ade.agent.actions import ActionExecutor
from ade.agent.memory import MemoryStore
from ade.agent.orchestrator import Orchestrator
from ade.agent.planner import PlanValidationError, plan_for_event, validate_plan
from ade.config import Settings


class FakePlanner:
    """PlannerClient double returning a canned plan."""

    def __init__(self, plan: dict):
        self.plan = plan
        self.calls = []

    def complete_plan(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return self.plan


def settings(**overrides) -> Settings:
    base = dict(dry_run=True, state_table="t", alerts_topic_arn="arn:alerts",
                approvals_topic_arn="arn:approvals")
    base.update(overrides)
    return Settings(**base)


def test_validate_rejects_unknown_action():
    with pytest.raises(PlanValidationError):
        validate_plan({"reasoning": "", "risk": "low",
                       "actions": [{"name": "rm_rf_prod", "params": {}, "requires_approval": False}]},
                      max_actions=5)


def test_validate_rejects_oversized_plan():
    actions = [{"name": "send_alert", "params": {}, "requires_approval": False}] * 6
    with pytest.raises(PlanValidationError):
        validate_plan({"reasoning": "", "risk": "low", "actions": actions}, max_actions=5)


def test_destructive_action_forced_to_approval():
    plan = validate_plan(
        {"reasoning": "", "risk": "low",
         "actions": [{"name": "promote_model", "params": {"v": 2}, "requires_approval": False}]},
        max_actions=5,
    )
    assert plan.actions[0].requires_approval is True


def test_plan_for_event_passes_context():
    fake = FakePlanner({"reasoning": "ok", "risk": "low", "actions": []})
    plan = plan_for_event(fake, {"type": "scheduled_scan"}, {"known_sources": []})
    assert plan.actions == []
    system, user = fake.calls[0]
    assert "Action catalog" in system
    assert "scheduled_scan" in user


def test_orchestrator_dry_run_executes_plan():
    fake = FakePlanner({
        "reasoning": "new source",
        "risk": "low",
        "actions": [
            {"name": "profile_dataset", "params": {"source": "s3://x"}, "requires_approval": False},
            {"name": "generate_docs", "params": {}, "requires_approval": False},
        ],
    })
    memory = MemoryStore()
    orch = Orchestrator(settings(), fake, memory)
    report = orch.handle_event({"type": "source_discovered", "id": "s3://x"})
    assert report.ok
    assert [r.status for r in report.results] == ["dry_run", "dry_run"]
    # decision audited
    decisions = [k for k in memory._items if k[0].startswith("DECISION#")]
    assert len(decisions) == 1


def test_orchestrator_rejects_bad_plan_and_alerts():
    fake = FakePlanner({
        "reasoning": "evil", "risk": "low",
        "actions": [{"name": "drop_database", "params": {}, "requires_approval": False}],
    })
    orch = Orchestrator(settings(), fake, MemoryStore())
    report = orch.handle_event({"type": "schema_drift", "id": "d"})
    assert not report.ok
    assert "plan rejected" in report.error


def test_circuit_breaker_escalates_after_retry_budget():
    fake = FakePlanner({
        "reasoning": "retry", "risk": "low",
        "actions": [{"name": "start_etl_pipeline", "params": {}, "requires_approval": False}],
    })
    memory = MemoryStore()
    orch = Orchestrator(settings(max_remediation_attempts=2), fake, memory)
    event = {"type": "pipeline_failed", "id": "f1", "incident_id": "inc-1"}

    for _ in range(2):
        orch.handle_event(event)
    assert memory.remediation_attempts("inc-1") == 2

    report = orch.handle_event(event)  # third time: escalate, no planner call
    assert report.plan is None
    assert report.results[0].action == "escalate"


def test_approval_gated_action_not_executed_in_dry_run():
    executor = ActionExecutor(settings(dry_run=False))
    result = executor.execute("promote_model", {"v": 3}, requires_approval=True)
    # No AWS in tests: approval request itself hits SNS and fails, but the
    # promote must never run. Status must not be "executed".
    assert result.status != "executed"
