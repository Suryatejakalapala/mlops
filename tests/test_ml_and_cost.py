from ade.cost.optimizer import (
    CostRecord,
    detect_anomalies,
    recommend,
    total_potential_savings,
)
from ade.ml.registry import Guardrail, PromotionGate, evaluate_promotion
from ade.ml.retraining import RetrainPolicy, TrainingJobSpec, decide_retrain

# --- retraining ------------------------------------------------------------

POLICY = RetrainPolicy()


def test_retrain_on_significant_drift():
    decision = decide_retrain(POLICY, "significant", 0.9, 0.89, 10, 5000)
    assert decision.retrain and decision.triggered_by == "drift"


def test_retrain_on_metric_degradation():
    decision = decide_retrain(POLICY, "stable", 0.90, 0.80, 10, 5000)
    assert decision.retrain and decision.triggered_by == "performance"


def test_no_retrain_in_cooldown_or_with_few_samples():
    assert not decide_retrain(POLICY, "significant", 0.9, 0.5, 0.5, 5000).retrain
    assert not decide_retrain(POLICY, "significant", 0.9, 0.5, 10, 10).retrain


def test_training_job_spec_spot_config():
    spec = TrainingJobSpec(
        job_name="j", image_uri="img", role_arn="arn:role",
        train_s3_uri="s3://b/train/", output_s3_uri="s3://b/out/",
    )
    req = spec.to_sagemaker_request()
    assert req["EnableManagedSpotTraining"] is True
    assert req["StoppingCondition"]["MaxWaitTimeInSeconds"] == 7200
    assert req["CheckpointConfig"]["S3Uri"].startswith("s3://b/out/")


# --- registry --------------------------------------------------------------

GATE = PromotionGate(
    primary_metric="auc", min_relative_improvement=0.01,
    guardrails=[Guardrail(metric="latency_p99_ms", max_value=200)],
)


def test_promotion_requires_improvement():
    verdict = evaluate_promotion(GATE, {"auc": 0.92, "latency_p99_ms": 150}, {"auc": 0.90})
    assert verdict.promote

    verdict = evaluate_promotion(GATE, {"auc": 0.901, "latency_p99_ms": 150}, {"auc": 0.90})
    assert not verdict.promote


def test_guardrail_blocks_promotion():
    verdict = evaluate_promotion(GATE, {"auc": 0.99, "latency_p99_ms": 500}, {"auc": 0.90})
    assert not verdict.promote
    assert "guardrail" in verdict.reason


def test_first_model_promotes_on_guardrails():
    verdict = evaluate_promotion(GATE, {"auc": 0.85, "latency_p99_ms": 100}, {})
    assert verdict.promote


# --- cost ------------------------------------------------------------------

def test_cost_anomaly_detection():
    records = [CostRecord(f"2026-06-{d:02d}", "AWS Glue", 10.0) for d in range(1, 9)]
    records.append(CostRecord("2026-06-09", "AWS Glue", 35.0))
    anomalies = detect_anomalies(records)
    assert len(anomalies) == 1
    assert anomalies[0].ratio == 3.5

    # steady spend: no anomaly
    steady = [CostRecord(f"2026-06-{d:02d}", "AmazonS3", 10.0) for d in range(1, 10)]
    assert detect_anomalies(steady) == []


def test_recommendations_ranked_by_savings():
    usage = {
        "idle_sagemaker_endpoints": [{"name": "ep1", "monthly_usd": 250, "invocations_7d": 0}],
        "glue_jobs": [{"name": "g1", "allocated_dpus": 10,
                       "avg_dpu_utilization": 0.2, "monthly_usd": 100}],
        "s3_buckets": [{"name": "b1", "standard_gb": 1000,
                        "last_access_days": 200, "monthly_usd": 23}],
        "lambda_functions": [{"name": "f1", "memory_mb": 1024,
                              "max_memory_used_mb": 200, "monthly_usd": 40}],
    }
    recs = recommend(usage)
    assert [r.kind for r in recs][0] == "delete_idle_endpoint"
    assert len(recs) == 4
    assert total_potential_savings(recs) > 300
