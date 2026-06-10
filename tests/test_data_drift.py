import random

from ade.drift.data_drift import (
    feature_drift_event,
    kolmogorov_smirnov,
    population_stability_index,
)

random.seed(7)
BASELINE = [random.gauss(0, 1) for _ in range(2000)]
SAME = [random.gauss(0, 1) for _ in range(2000)]
SHIFTED = [random.gauss(2.5, 1) for _ in range(2000)]


def test_psi_stable_for_same_distribution():
    result = population_stability_index(BASELINE, SAME)
    assert result.severity == "stable"
    assert not result.drifted


def test_psi_significant_for_shifted_distribution():
    result = population_stability_index(BASELINE, SHIFTED)
    assert result.severity == "significant"


def test_ks_detects_shift():
    assert kolmogorov_smirnov(BASELINE, SHIFTED).severity == "significant"
    assert kolmogorov_smirnov(BASELINE, SAME).severity == "stable"


def test_empty_inputs_are_stable():
    assert population_stability_index([], BASELINE).severity == "stable"
    assert kolmogorov_smirnov(BASELINE, []).severity == "stable"


def test_event_takes_worst_severity():
    psi = population_stability_index(BASELINE, SAME)
    ks = kolmogorov_smirnov(BASELINE, SHIFTED)
    event = feature_drift_event("orders", "amount", psi, ks)
    assert event["severity"] == "significant"
    assert event["type"] == "data_drift"
