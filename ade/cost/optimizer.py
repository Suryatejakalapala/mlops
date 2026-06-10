"""AWS cost analysis: anomaly detection + rule-based recommendations.

Inputs are normalized CostRecord rows (pulled from Cost Explorer daily by
the cost Lambda). Anomalies feed the agent as `cost_anomaly` events;
recommendations are surfaced for approval (applying one is destructive).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CostRecord:
    date: str          # YYYY-MM-DD
    service: str
    usd: float


@dataclass
class CostAnomaly:
    service: str
    date: str
    usd: float
    expected_usd: float
    ratio: float

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "cost_anomaly",
            "id": f"cost-{self.service}-{self.date}",
            "incident_id": f"cost-{self.service}",
            "service": self.service,
            "date": self.date,
            "usd": round(self.usd, 2),
            "expected_usd": round(self.expected_usd, 2),
            "ratio": round(self.ratio, 2),
        }


def detect_anomalies(
    records: list[CostRecord],
    min_ratio: float = 1.5,
    min_usd: float = 5.0,
    window: int = 14,
) -> list[CostAnomaly]:
    """Flag the latest day per service when it exceeds the trailing median."""
    by_service: dict[str, list[CostRecord]] = {}
    for r in records:
        by_service.setdefault(r.service, []).append(r)

    anomalies = []
    for service, rows in by_service.items():
        rows.sort(key=lambda r: r.date)
        if len(rows) < 4:
            continue
        *history, latest = rows
        baseline = [r.usd for r in history[-window:]]
        expected = statistics.median(baseline)
        if latest.usd < min_usd:
            continue
        if expected <= 0:
            if latest.usd >= min_usd:
                anomalies.append(CostAnomaly(service, latest.date, latest.usd,
                                             expected, float("inf")))
            continue
        ratio = latest.usd / expected
        if ratio >= min_ratio:
            anomalies.append(CostAnomaly(service, latest.date, latest.usd, expected, ratio))
    return anomalies


@dataclass
class Recommendation:
    kind: str
    target: str
    estimated_monthly_savings_usd: float
    detail: str
    params: dict[str, Any] = field(default_factory=dict)


def recommend(usage: dict[str, Any]) -> list[Recommendation]:
    """Rule-based recommendations from a normalized usage snapshot.

    Expected keys (all optional):
      idle_sagemaker_endpoints: [{name, monthly_usd, invocations_7d}]
      glue_jobs: [{name, allocated_dpus, avg_dpu_utilization, monthly_usd}]
      s3_buckets: [{name, standard_gb, last_access_days, monthly_usd}]
      lambda_functions: [{name, memory_mb, max_memory_used_mb, monthly_usd}]
    """
    recs: list[Recommendation] = []

    for ep in usage.get("idle_sagemaker_endpoints", []):
        if ep.get("invocations_7d", 1) == 0:
            recs.append(Recommendation(
                kind="delete_idle_endpoint",
                target=ep["name"],
                estimated_monthly_savings_usd=float(ep.get("monthly_usd", 0)),
                detail="Endpoint had zero invocations in 7 days; delete or move to serverless.",
                params={"endpoint_name": ep["name"]},
            ))

    for job in usage.get("glue_jobs", []):
        utilization = float(job.get("avg_dpu_utilization", 1.0))
        if utilization < 0.5 and job.get("allocated_dpus", 0) > 2:
            savings = float(job.get("monthly_usd", 0)) * (1 - utilization)
            recs.append(Recommendation(
                kind="rightsize_glue_job",
                target=job["name"],
                estimated_monthly_savings_usd=round(savings, 2),
                detail=f"DPU utilization {utilization:.0%}; halve allocated DPUs.",
                params={"job_name": job["name"],
                        "new_dpus": max(2, int(job["allocated_dpus"] / 2))},
            ))

    for bucket in usage.get("s3_buckets", []):
        if bucket.get("last_access_days", 0) > 90 and bucket.get("standard_gb", 0) > 100:
            # STANDARD ~$0.023/GB vs GLACIER_IR ~$0.004/GB
            savings = float(bucket["standard_gb"]) * (0.023 - 0.004)
            recs.append(Recommendation(
                kind="s3_lifecycle_to_glacier_ir",
                target=bucket["name"],
                estimated_monthly_savings_usd=round(savings, 2),
                detail="No access in 90+ days; add lifecycle rule to Glacier IR.",
                params={"bucket": bucket["name"], "transition_days": 90},
            ))

    for fn in usage.get("lambda_functions", []):
        memory = float(fn.get("memory_mb", 128))
        used = float(fn.get("max_memory_used_mb", memory))
        if memory >= 512 and used / memory < 0.4:
            new_memory = max(128, int(used * 1.5 / 64) * 64)
            savings = float(fn.get("monthly_usd", 0)) * (1 - new_memory / memory)
            recs.append(Recommendation(
                kind="rightsize_lambda_memory",
                target=fn["name"],
                estimated_monthly_savings_usd=round(savings, 2),
                detail=f"Peak memory {used:.0f}MB of {memory:.0f}MB; lower allocation.",
                params={"function_name": fn["name"], "new_memory_mb": new_memory},
            ))

    recs.sort(key=lambda r: r.estimated_monthly_savings_usd, reverse=True)
    return recs


def total_potential_savings(recs: list[Recommendation]) -> float:
    return round(sum(r.estimated_monthly_savings_usd for r in recs), 2)
