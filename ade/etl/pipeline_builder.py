"""ETL pipeline generation.

A PipelineSpec describes extract -> validate -> transform -> load with a
quality gate. The spec compiles to an AWS Step Functions definition (ASL)
whose task states invoke the ADE worker Lambda; heavy transforms can be
swapped to Glue jobs by changing the resource on the Transform state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class PipelineSpecError(Exception):
    pass


@dataclass
class PipelineSpec:
    pipeline_id: str
    source: str                      # e.g. s3://bucket/raw/orders/
    destination: str                 # e.g. s3://bucket/curated/orders/
    format: str                      # csv | json | parquet ...
    transforms: list[dict[str, Any]] = field(default_factory=list)
    quality_rules: list[dict[str, Any]] = field(default_factory=list)
    schedule: str = "rate(1 day)"

    def validate(self) -> None:
        if not self.pipeline_id:
            raise PipelineSpecError("pipeline_id is required")
        if not self.source.startswith(("s3://", "glue://", "rds://")):
            raise PipelineSpecError(f"unsupported source: {self.source}")
        if not self.destination.startswith("s3://"):
            raise PipelineSpecError(f"destination must be s3://: {self.destination}")
        if self.source == self.destination:
            raise PipelineSpecError("source and destination must differ")
        known_ops = {"rename", "cast", "drop", "filter", "dedupe", "derive"}
        for t in self.transforms:
            if t.get("op") not in known_ops:
                raise PipelineSpecError(f"unknown transform op: {t.get('op')}")


def build_spec_from_profile(
    pipeline_id: str,
    source: str,
    destination: str,
    fmt: str,
    schema: dict[str, str],
    null_rates: dict[str, float] | None = None,
) -> PipelineSpec:
    """Derive a sensible default pipeline from a dataset profile.

    Numeric-looking string columns get cast; columns observed as fully
    non-null get not_null rules; everything gets a dedupe.
    """
    null_rates = null_rates or {}
    transforms: list[dict[str, Any]] = [{"op": "dedupe", "subset": None}]
    rules: list[dict[str, Any]] = []
    for column, col_type in schema.items():
        if col_type in ("integer", "double"):
            transforms.append({"op": "cast", "column": column, "to": col_type})
        if null_rates.get(column, 1.0) == 0.0:
            rules.append({"rule": "not_null", "column": column})
    spec = PipelineSpec(
        pipeline_id=pipeline_id,
        source=source,
        destination=destination,
        format=fmt,
        transforms=transforms,
        quality_rules=rules,
    )
    spec.validate()
    return spec


def compile_to_asl(spec: PipelineSpec, worker_lambda_arn: str) -> dict[str, Any]:
    """Compile a PipelineSpec into a Step Functions state machine definition."""
    spec.validate()

    def task(
        name: str, step: str, next_state: str | None, catch_to: str = "Quarantine"
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "Type": "Task",
            "Resource": worker_lambda_arn,
            "Parameters": {
                "step": step,
                "pipeline_id": spec.pipeline_id,
                "spec.$": "$.spec",
                "execution_input.$": "$$.Execution.Input",
            },
            "ResultPath": f"$.{step}_result",
            "Retry": [
                {
                    "ErrorEquals": ["States.TaskFailed", "Lambda.ServiceException"],
                    "IntervalSeconds": 10,
                    "MaxAttempts": 3,
                    "BackoffRate": 2.0,
                }
            ],
            "Catch": [
                {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": catch_to}
            ],
        }
        if next_state:
            state["Next"] = next_state
        else:
            state["End"] = True
        return state

    return {
        "Comment": f"ADE ETL pipeline {spec.pipeline_id}",
        "StartAt": "Extract",
        "States": {
            "Extract": task("Extract", "extract", "Validate"),
            "Validate": task("Validate", "validate", "Transform"),
            "Transform": task("Transform", "transform", "QualityGate"),
            "QualityGate": {
                "Type": "Task",
                "Resource": worker_lambda_arn,
                "Parameters": {
                    "step": "quality_gate",
                    "pipeline_id": spec.pipeline_id,
                    "rules": spec.quality_rules,
                    "spec.$": "$.spec",
                },
                "ResultPath": "$.quality_result",
                "Next": "QualityChoice",
                "Catch": [
                    {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Quarantine"}
                ],
            },
            "QualityChoice": {
                "Type": "Choice",
                "Choices": [
                    {
                        "Variable": "$.quality_result.passed",
                        "BooleanEquals": True,
                        "Next": "Load",
                    }
                ],
                "Default": "Quarantine",
            },
            "Load": task("Load", "load", None),
            "Quarantine": {
                "Type": "Task",
                "Resource": worker_lambda_arn,
                "Parameters": {
                    "step": "quarantine",
                    "pipeline_id": spec.pipeline_id,
                    "spec.$": "$.spec",
                    "error.$": "$.error",
                },
                "Next": "FailPipeline",
            },
            "FailPipeline": {
                "Type": "Fail",
                "Error": "PipelineFailed",
                "Cause": "Quality gate failed or a step errored; records quarantined.",
            },
        },
    }


def asl_json(spec: PipelineSpec, worker_lambda_arn: str) -> str:
    return json.dumps(compile_to_asl(spec, worker_lambda_arn), indent=2, sort_keys=False)
