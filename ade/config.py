"""Environment-driven configuration for ADE.

Every Lambda and the local CLI read the same Settings object. All values
come from environment variables so Terraform is the single source of truth
for wiring (bucket names, table names, topic ARNs, model id).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env(name: str, default: str = "") -> Any:
    return field(default_factory=lambda: os.environ.get(name, default))


def _env_int(name: str, default: int) -> Any:
    return field(default_factory=lambda: int(os.environ.get(name, str(default))))


def _env_bool(name: str, default: bool) -> Any:
    def parse() -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    return field(default_factory=parse)


@dataclass(frozen=True)
class Settings:
    # Identity
    project: str = _env("ADE_PROJECT", "ade")
    environment: str = _env("ADE_ENV", "dev")
    region: str = _env("AWS_REGION", "us-east-1")

    # Storage
    data_lake_bucket: str = _env("ADE_DATA_LAKE_BUCKET")
    artifacts_bucket: str = _env("ADE_ARTIFACTS_BUCKET")
    docs_bucket: str = _env("ADE_DOCS_BUCKET")
    state_table: str = _env("ADE_STATE_TABLE")

    # Messaging / orchestration
    alerts_topic_arn: str = _env("ADE_ALERTS_TOPIC_ARN")
    approvals_topic_arn: str = _env("ADE_APPROVALS_TOPIC_ARN")
    event_bus_name: str = _env("ADE_EVENT_BUS", "default")
    etl_state_machine_arn: str = _env("ADE_ETL_SFN_ARN")
    retrain_state_machine_arn: str = _env("ADE_RETRAIN_SFN_ARN")

    # LLM planner (Claude on Amazon Bedrock — note the `anthropic.` prefix)
    planner_model: str = _env("ADE_PLANNER_MODEL", "anthropic.claude-opus-4-8")
    planner_max_tokens: int = _env_int("ADE_PLANNER_MAX_TOKENS", 16000)

    # Guardrails
    dry_run: bool = _env_bool("ADE_DRY_RUN", True)
    max_actions_per_plan: int = _env_int("ADE_MAX_ACTIONS_PER_PLAN", 5)
    max_remediation_attempts: int = _env_int("ADE_MAX_REMEDIATION_ATTEMPTS", 3)
    monthly_llm_budget_usd: int = _env_int("ADE_MONTHLY_LLM_BUDGET_USD", 200)

    # CloudWatch
    metrics_namespace: str = _env("ADE_METRICS_NAMESPACE", "ADE")


def load_settings() -> Settings:
    return Settings()
