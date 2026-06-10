"""Retraining decisions and SageMaker job specs.

decide_retrain() is the deterministic policy: it converts drift severity
and live model performance into a yes/no with a reason. The agent planner
may *propose* retraining, but this policy is the final gate before the
state machine starts (and promotion is approval-gated on top).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrainPolicy:
    max_metric_degradation: float = 0.05   # relative drop vs. baseline
    drift_severity_trigger: str = "significant"
    min_days_between_retrains: int = 1
    min_new_samples: int = 1000


@dataclass
class RetrainDecision:
    retrain: bool
    reason: str
    triggered_by: str = ""   # drift | performance | schedule | none


def decide_retrain(
    policy: RetrainPolicy,
    drift_severity: str,
    baseline_metric: float,
    current_metric: float,
    days_since_last_retrain: float,
    new_samples: int,
    higher_is_better: bool = True,
) -> RetrainDecision:
    if days_since_last_retrain < policy.min_days_between_retrains:
        return RetrainDecision(False, "cooldown window active", "none")
    if new_samples < policy.min_new_samples:
        return RetrainDecision(
            False, f"only {new_samples} new samples (< {policy.min_new_samples})", "none"
        )

    severities = ("stable", "moderate", "significant")
    if severities.index(drift_severity) >= severities.index(policy.drift_severity_trigger):
        return RetrainDecision(True, f"data drift severity={drift_severity}", "drift")

    if baseline_metric > 0:
        delta = (baseline_metric - current_metric) / baseline_metric
        if not higher_is_better:
            delta = -delta
        if delta > policy.max_metric_degradation:
            return RetrainDecision(
                True,
                f"metric degraded {delta:.1%} (limit {policy.max_metric_degradation:.0%})",
                "performance",
            )
    return RetrainDecision(False, "no trigger met", "none")


@dataclass
class TrainingJobSpec:
    job_name: str
    image_uri: str
    role_arn: str
    train_s3_uri: str
    output_s3_uri: str
    instance_type: str = "ml.m5.xlarge"
    instance_count: int = 1
    max_runtime_seconds: int = 3600
    use_spot: bool = True
    hyperparameters: dict[str, str] = field(default_factory=dict)

    def to_sagemaker_request(self) -> dict[str, Any]:
        request: dict[str, Any] = {
            "TrainingJobName": self.job_name,
            "AlgorithmSpecification": {
                "TrainingImage": self.image_uri,
                "TrainingInputMode": "File",
            },
            "RoleArn": self.role_arn,
            "InputDataConfig": [
                {
                    "ChannelName": "train",
                    "DataSource": {
                        "S3DataSource": {
                            "S3DataType": "S3Prefix",
                            "S3Uri": self.train_s3_uri,
                            "S3DataDistributionType": "FullyReplicated",
                        }
                    },
                }
            ],
            "OutputDataConfig": {"S3OutputPath": self.output_s3_uri},
            "ResourceConfig": {
                "InstanceType": self.instance_type,
                "InstanceCount": self.instance_count,
                "VolumeSizeInGB": 50,
            },
            "StoppingCondition": {"MaxRuntimeInSeconds": self.max_runtime_seconds},
            "HyperParameters": self.hyperparameters,
        }
        if self.use_spot:
            # Managed spot cuts training cost up to ~70%.
            request["EnableManagedSpotTraining"] = True
            request["StoppingCondition"]["MaxWaitTimeInSeconds"] = self.max_runtime_seconds * 2
            request["CheckpointConfig"] = {
                "S3Uri": f"{self.output_s3_uri.rstrip('/')}/checkpoints/"
            }
        return request


def make_job_name(model_name: str) -> str:
    return f"ade-{model_name}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
