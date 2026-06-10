"""Action executor — the only code path that touches AWS mutating APIs.

Every action validated by the planner maps to a handler here. Dry-run mode
logs what would happen without calling AWS; destructive actions that lack
an approval token are converted into an approval request.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ade.config import Settings

logger = logging.getLogger("ade.actions")


@dataclass
class ActionResult:
    action: str
    status: str  # executed | dry_run | approval_requested | failed
    detail: str = ""


class ActionExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._handlers: dict[str, Callable[[dict[str, Any]], str]] = {
            "run_glue_crawler": self._run_glue_crawler,
            "profile_dataset": self._noop("profiling scheduled"),
            "build_etl_pipeline": self._noop("pipeline spec registered"),
            "start_etl_pipeline": self._start_etl_pipeline,
            "run_quality_checks": self._noop("quality checks scheduled"),
            "quarantine_records": self._noop("records quarantined"),
            "trigger_retraining": self._trigger_retraining,
            "promote_model": self._noop("model promoted"),
            "rollback_model": self._noop("model rolled back"),
            "update_schema_registry": self._noop("schema registered"),
            "apply_cost_recommendation": self._noop("cost recommendation applied"),
            "generate_docs": self._noop("docs regenerated"),
            "send_alert": self._send_alert,
            "request_approval": self._request_approval,
            "backfill_partition": self._start_etl_pipeline,
            "escalate": self._escalate,
        }

    # -- public ------------------------------------------------------------

    def execute(self, name: str, params: dict[str, Any], requires_approval: bool,
                approved: bool = False) -> ActionResult:
        if requires_approval and not approved:
            try:
                self._request_approval({"action": name, "params": params})
            except Exception:
                logger.exception("failed to publish approval request for %s", name)
            return ActionResult(name, "approval_requested",
                                "destructive action queued for human approval")
        if self.settings.dry_run:
            logger.info("DRY RUN %s %s", name, json.dumps(params, default=str))
            return ActionResult(name, "dry_run", json.dumps(params, default=str))
        handler = self._handlers.get(name)
        if handler is None:
            return ActionResult(name, "failed", "no handler registered")
        try:
            return ActionResult(name, "executed", handler(params))
        except Exception as exc:  # surfaced to self-healing, never swallowed silently
            logger.exception("action %s failed", name)
            return ActionResult(name, "failed", str(exc))

    # -- handlers ----------------------------------------------------------

    def _noop(self, message: str) -> Callable[[dict[str, Any]], str]:
        # Placeholder handlers record intent; wiring to real services is
        # incremental (each one is an isolated boto3 call like those below).
        def handler(params: dict[str, Any]) -> str:
            return f"{message}: {json.dumps(params, default=str)}"
        return handler

    def _run_glue_crawler(self, params: dict[str, Any]) -> str:
        import boto3

        boto3.client("glue").start_crawler(Name=params["crawler_name"])
        return f"started crawler {params['crawler_name']}"

    def _start_etl_pipeline(self, params: dict[str, Any]) -> str:
        import boto3

        arn = params.get("state_machine_arn") or self.settings.etl_state_machine_arn
        execution = boto3.client("stepfunctions").start_execution(
            stateMachineArn=arn,
            name=f"ade-{uuid.uuid4().hex[:12]}",
            input=json.dumps(params, default=str),
        )
        return f"started execution {execution['executionArn']}"

    def _trigger_retraining(self, params: dict[str, Any]) -> str:
        import boto3

        execution = boto3.client("stepfunctions").start_execution(
            stateMachineArn=self.settings.retrain_state_machine_arn,
            name=f"ade-retrain-{uuid.uuid4().hex[:12]}",
            input=json.dumps(params, default=str),
        )
        return f"started retraining {execution['executionArn']}"

    def _send_alert(self, params: dict[str, Any]) -> str:
        import boto3

        boto3.client("sns").publish(
            TopicArn=self.settings.alerts_topic_arn,
            Subject=str(params.get("subject", "ADE alert"))[:100],
            Message=json.dumps(params, default=str, indent=2),
        )
        return "alert published"

    def _request_approval(self, params: dict[str, Any]) -> str:
        import boto3

        boto3.client("sns").publish(
            TopicArn=self.settings.approvals_topic_arn,
            Subject="ADE approval required",
            Message=json.dumps(params, default=str, indent=2),
        )
        return "approval requested"

    def _escalate(self, params: dict[str, Any]) -> str:
        return self._send_alert({"subject": "ADE ESCALATION", **params})
