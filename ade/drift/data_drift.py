"""Statistical data drift: PSI for distributions, KS for numeric samples.

Pure-Python (no numpy) so it runs in a slim Lambda. Conventional
thresholds: PSI < 0.1 stable, 0.1–0.25 moderate, > 0.25 significant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PSI_MODERATE = 0.1
PSI_SIGNIFICANT = 0.25


@dataclass
class DriftResult:
    metric: str          # psi | ks
    value: float
    severity: str        # stable | moderate | significant

    @property
    def drifted(self) -> bool:
        return self.severity != "stable"


def _histogram(values: list[float], edges: list[float]) -> list[float]:
    counts = [0] * (len(edges) + 1)
    for v in values:
        placed = False
        for i, edge in enumerate(edges):
            if v <= edge:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    total = max(len(values), 1)
    return [c / total for c in counts]


def population_stability_index(
    baseline: list[float], current: list[float], bins: int = 10
) -> DriftResult:
    """PSI over quantile bins derived from the baseline."""
    if not baseline or not current:
        return DriftResult("psi", 0.0, "stable")
    ordered = sorted(baseline)
    edges = []
    for i in range(1, bins):
        idx = int(len(ordered) * i / bins)
        edges.append(ordered[min(idx, len(ordered) - 1)])
    # Deduplicate edges (constant features yield identical quantiles)
    edges = sorted(set(edges))
    base_dist = _histogram(baseline, edges)
    cur_dist = _histogram(current, edges)
    epsilon = 1e-4
    psi = 0.0
    for b, c in zip(base_dist, cur_dist, strict=True):  # same edges -> same length
        b = max(b, epsilon)
        c = max(c, epsilon)
        psi += (c - b) * math.log(c / b)
    severity = (
        "significant" if psi > PSI_SIGNIFICANT
        else "moderate" if psi > PSI_MODERATE
        else "stable"
    )
    return DriftResult("psi", round(psi, 6), severity)


def kolmogorov_smirnov(
    baseline: list[float], current: list[float], alpha: float = 0.05
) -> DriftResult:
    """Two-sample KS statistic with the asymptotic critical value."""
    if not baseline or not current:
        return DriftResult("ks", 0.0, "stable")
    a, b = sorted(baseline), sorted(current)
    i = j = 0
    d = 0.0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            i += 1
        else:
            j += 1
        d = max(d, abs(i / len(a) - j / len(b)))
    c_alpha = math.sqrt(-0.5 * math.log(alpha / 2))
    critical = c_alpha * math.sqrt((len(a) + len(b)) / (len(a) * len(b)))
    if d > critical * 1.5:
        severity = "significant"
    elif d > critical:
        severity = "moderate"
    else:
        severity = "stable"
    return DriftResult("ks", round(d, 6), severity)


def feature_drift_event(
    dataset: str, feature: str, psi: DriftResult, ks: DriftResult
) -> dict:
    worst = max((psi, ks), key=lambda r: ("stable", "moderate", "significant").index(r.severity))
    return {
        "type": "data_drift",
        "id": f"data-drift-{dataset}-{feature}",
        "incident_id": f"data-drift-{dataset}",
        "dataset": dataset,
        "feature": feature,
        "psi": psi.value,
        "ks": ks.value,
        "severity": worst.severity,
    }
