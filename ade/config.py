"""Environment-driven configuration for ADE.

Every Lambda and the local CLI read the same Settings object. All values
come from environment variables so Terraform is the single source of truth
for wiring (bucket names, table names, topic ARNs, model id).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # Identity
    project: str = field(default_factory=lambda: os.environ.get("ADE_PROJECT", "ade"))
    environment: str = field(default_factory=lambda: os.environ.get("ADE_ENV", "dev"))
    region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1"))

    # Storage
    data_lake_bucket: str = field(default_factory=lambda: os.environ.get("ADE_DATA_LAKE_BUCKET", ""))
    artifacts_bucket: str = field(default_factory=lambda: os.environ.get("ADE_ARTIFACTS_BUCKET", ""))
    docs_bucket: str = field(default_factory=lambda: os.environ.get("ADE_DOCS_BUCKET", ""))
    state_table: str = field(default_factory=lambda: os.environ.get("ADE_STATE_TABLE", ""))

    # Messaging / orchestration
    alerts_topic_arn: str = field(default_factory=lambda: os.environ.get("ADE_ALERTS_TOPIC_ARN", ""))
    approvals_topic_arn: str = field(default_factory=lambda: os.environ.get("ADE_APPROVALS_TOPIC_ARN", ""))
    event_bus_name: str = field(default_factory=lambda: os.environ.get("ADE_EVENT_BUS", "default"))
    etl_state_machine_arn: str = field(default_factory=lambda: os.environ.get("ADE_ETL_SFN_ARN", ""))
    retrain_state_machine_arn: str = field(default_factory=lambda: os.environ.get("ADE_RETRAIN_SFN_ARN", ""))

    # LLM planner (Claude on Amazon Bedrock — note the `anthropic.` prefix)
    planner_model: str = field(
        default_factory=lambda: os.environ.get("ADE_PLANNER_MODEL", "anthropic.claude-opus-4-8")
    )
    planner_max_tokens: int = field(
        default_factory=lambda: int(os.environ.get("ADE_PLANNER_MAX_TOKENS", "16000"))
    )

    # Guardrails
    dry_run: bool = field(default_factory=lambda: _bool("ADE_DRY_RUN", True))
    max_actions_per_plan: int = field(
        default_factory=lambda: int(os.environ.get("ADE_MAX_ACTIONS_PER_PLAN", "5"))
    )
    max_remediation_attempts: int = field(
        default_factory=lambda: int(os.environ.get("ADE_MAX_REMEDIATION_ATTEMPTS", "3"))
    )
    monthly_llm_budget_usd: float = field(
        default_factory=lambda: float(os.environ.get("ADE_MONTHLY_LLM_BUDGET_USD", "200"))
    )

    # CloudWatch
    metrics_namespace: str = field(
        default_factory=lambda: os.environ.get("ADE_METRICS_NAMESPACE", "ADE")
    )


def load_settings() -> Settings:
    return Settings()
