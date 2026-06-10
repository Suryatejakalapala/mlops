import json

import pytest

from ade.etl.pipeline_builder import (
    PipelineSpec,
    PipelineSpecError,
    build_spec_from_profile,
    compile_to_asl,
)

ARN = "arn:aws:lambda:us-east-1:123456789012:function:ade-worker"


def valid_spec() -> PipelineSpec:
    return PipelineSpec(
        pipeline_id="orders",
        source="s3://lake/raw/orders/",
        destination="s3://lake/curated/orders/",
        format="csv",
        quality_rules=[{"rule": "not_null", "column": "id"}],
    )


def test_spec_validation():
    valid_spec().validate()
    with pytest.raises(PipelineSpecError):
        PipelineSpec("", "s3://a/", "s3://b/", "csv").validate()
    with pytest.raises(PipelineSpecError):
        PipelineSpec("p", "ftp://a/", "s3://b/", "csv").validate()
    with pytest.raises(PipelineSpecError):
        PipelineSpec("p", "s3://a/", "s3://a/", "csv").validate()
    with pytest.raises(PipelineSpecError):
        PipelineSpec("p", "s3://a/", "s3://b/", "csv",
                     transforms=[{"op": "explode"}]).validate()


def test_build_spec_from_profile():
    spec = build_spec_from_profile(
        "orders", "s3://lake/raw/orders/", "s3://lake/curated/orders/", "csv",
        schema={"id": "integer", "name": "string", "price": "double"},
        null_rates={"id": 0.0, "name": 0.1, "price": 0.0},
    )
    ops = [t["op"] for t in spec.transforms]
    assert ops[0] == "dedupe"
    assert ops.count("cast") == 2
    rule_columns = {r["column"] for r in spec.quality_rules}
    assert rule_columns == {"id", "price"}


def test_asl_compiles_with_quality_gate_and_quarantine():
    asl = compile_to_asl(valid_spec(), ARN)
    assert asl["StartAt"] == "Extract"
    states = asl["States"]
    assert set(states) == {
        "Extract", "Validate", "Transform", "QualityGate",
        "QualityChoice", "Load", "Quarantine", "FailPipeline",
    }
    assert states["QualityChoice"]["Default"] == "Quarantine"
    assert states["Load"]["End"] is True
    # every task retries with backoff and catches to quarantine
    assert states["Extract"]["Retry"][0]["BackoffRate"] == 2.0
    assert states["Extract"]["Catch"][0]["Next"] == "Quarantine"
    json.dumps(asl)  # must be serializable
