"""LLM-backed planning with hard guardrails.

The planner asks Claude for a plan (list of actions) given an event and the
agent's memory, then validates the plan against the action allowlist before
anything executes. The LLM proposes; deterministic code disposes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ade.llm import PlannerClient

# Allowlist: action name -> (description, destructive?)
# Destructive actions always require human approval regardless of what the
# model says. Anything not listed here is rejected outright.
ACTION_CATALOG: dict[str, tuple[str, bool]] = {
    "run_glue_crawler": ("Crawl a data source to refresh the Glue catalog.", False),
    "profile_dataset": ("Profile a dataset and store stats in the catalog.", False),
    "build_etl_pipeline": ("Generate and register an ETL pipeline for a source.", False),
    "start_etl_pipeline": ("Execute a registered ETL pipeline (Step Functions).", False),
    "run_quality_checks": ("Run data-quality rules against a dataset.", False),
    "quarantine_records": ("Move failing records to the quarantine prefix.", False),
    "trigger_retraining": ("Start the model retraining state machine.", True),
    "promote_model": ("Promote a model version to production.", True),
    "rollback_model": ("Roll production back to the previous model version.", True),
    "update_schema_registry": ("Record a new schema version for a dataset.", False),
    "apply_cost_recommendation": ("Apply a cost optimization (e.g. lifecycle rule).", True),
    "generate_docs": ("Regenerate documentation for the data platform.", False),
    "send_alert": ("Notify operators via SNS.", False),
    "request_approval": ("Ask a human to approve a pending destructive action.", False),
    "backfill_partition": ("Re-run ETL for a specific partition/date range.", False),
    "escalate": ("Stop autonomous handling and page a human.", False),
}

SYSTEM_PROMPT = """\
You are ADE, an autonomous AI data engineer operating an AWS data platform.
You receive one event at a time (source discovered, schema drift, pipeline
failure, data-drift alert, cost anomaly, scheduled scan) plus a snapshot of
platform memory, and you respond with a plan: an ordered list of actions.

Rules:
- Only use actions from the catalog below. Never invent actions.
- Prefer the smallest plan that resolves the event; an empty action list is
  a valid plan when no action is needed.
- Mark requires_approval=true for anything destructive or customer-facing:
  model promotion/rollback, retraining, applying cost changes.
- If the same failure has already been remediated repeatedly, escalate
  instead of retrying.
- Breaking schema changes (removed columns, type changes) must never flow
  downstream silently: quarantine, alert, and update the registry.

Action catalog:
{catalog}
"""


@dataclass
class PlannedAction:
    name: str
    params: dict[str, Any]
    requires_approval: bool


@dataclass
class Plan:
    reasoning: str
    risk: str
    actions: list[PlannedAction] = field(default_factory=list)


class PlanValidationError(Exception):
    pass


def _catalog_text() -> str:
    lines = []
    for name, (desc, destructive) in sorted(ACTION_CATALOG.items()):
        tag = " [DESTRUCTIVE — always requires approval]" if destructive else ""
        lines.append(f"- {name}: {desc}{tag}")
    return "\n".join(lines)


def build_system_prompt() -> str:
    return SYSTEM_PROMPT.format(catalog=_catalog_text())


def build_user_prompt(event: dict[str, Any], memory_snapshot: dict[str, Any]) -> str:
    return (
        "Event:\n"
        + json.dumps(event, sort_keys=True, default=str)
        + "\n\nPlatform memory snapshot:\n"
        + json.dumps(memory_snapshot, sort_keys=True, default=str)
    )


def validate_plan(raw: dict[str, Any], max_actions: int) -> Plan:
    """Enforce guardrails on a raw plan from the LLM."""
    actions_raw = raw.get("actions", [])
    if len(actions_raw) > max_actions:
        raise PlanValidationError(
            f"Plan has {len(actions_raw)} actions; limit is {max_actions}."
        )
    actions: list[PlannedAction] = []
    for item in actions_raw:
        name = item.get("name", "")
        if name not in ACTION_CATALOG:
            raise PlanValidationError(f"Action '{name}' is not in the allowlist.")
        _, destructive = ACTION_CATALOG[name]
        requires_approval = bool(item.get("requires_approval", False)) or destructive
        params = item.get("params") or {}
        if not isinstance(params, dict):
            raise PlanValidationError(f"Action '{name}' params must be an object.")
        actions.append(PlannedAction(name=name, params=params, requires_approval=requires_approval))
    risk = raw.get("risk", "high")
    if risk not in ("low", "medium", "high"):
        risk = "high"
    return Plan(reasoning=str(raw.get("reasoning", "")), risk=risk, actions=actions)


def plan_for_event(
    client: PlannerClient,
    event: dict[str, Any],
    memory_snapshot: dict[str, Any],
    max_actions: int = 5,
) -> Plan:
    raw = client.complete_plan(
        system=build_system_prompt(),
        user=build_user_prompt(event, memory_snapshot),
    )
    return validate_plan(raw, max_actions=max_actions)
