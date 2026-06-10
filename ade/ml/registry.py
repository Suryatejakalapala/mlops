"""Model registry promotion gate.

A candidate is promotable only when it beats production on the primary
metric by a minimum margin AND violates no guardrail metric. Promotion
itself is a destructive action and goes through human approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Guardrail:
    metric: str
    max_value: float | None = None
    min_value: float | None = None


@dataclass
class PromotionGate:
    primary_metric: str
    min_relative_improvement: float = 0.01
    higher_is_better: bool = True
    guardrails: list[Guardrail] = field(default_factory=list)


@dataclass
class PromotionVerdict:
    promote: bool
    reason: str


def evaluate_promotion(
    gate: PromotionGate,
    candidate_metrics: dict[str, float],
    production_metrics: dict[str, float],
) -> PromotionVerdict:
    if gate.primary_metric not in candidate_metrics:
        return PromotionVerdict(False, f"candidate missing metric {gate.primary_metric}")

    for guardrail in gate.guardrails:
        value = candidate_metrics.get(guardrail.metric)
        if value is None:
            return PromotionVerdict(False, f"candidate missing guardrail metric {guardrail.metric}")
        if guardrail.max_value is not None and value > guardrail.max_value:
            return PromotionVerdict(
                False, f"guardrail {guardrail.metric}={value} exceeds max {guardrail.max_value}"
            )
        if guardrail.min_value is not None and value < guardrail.min_value:
            return PromotionVerdict(
                False, f"guardrail {guardrail.metric}={value} below min {guardrail.min_value}"
            )

    candidate = candidate_metrics[gate.primary_metric]
    production = production_metrics.get(gate.primary_metric)
    if production is None:
        # First model for this slot: guardrails passing is sufficient.
        return PromotionVerdict(True, "no production baseline; guardrails passed")

    if gate.higher_is_better:
        improvement = (candidate - production) / abs(production) if production else float("inf")
    else:
        improvement = (production - candidate) / abs(production) if production else float("inf")

    if improvement >= gate.min_relative_improvement:
        return PromotionVerdict(
            True,
            f"{gate.primary_metric} improved {improvement:.2%} "
            f"(needs {gate.min_relative_improvement:.2%})",
        )
    return PromotionVerdict(
        False,
        f"{gate.primary_metric} improvement {improvement:.2%} "
        f"below threshold {gate.min_relative_improvement:.2%}",
    )
