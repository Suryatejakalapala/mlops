from ade.discovery.profiler import profile_rows
from ade.discovery.scanner import discover_s3_prefixes, infer_format
from ade.docsgen.generator import render_catalog
from ade.monitoring.alerting import Alert, Alerter
from ade.recovery.self_healing import classify, next_remediation

# --- self healing ----------------------------------------------------------

def test_failure_classification():
    assert classify("Rate exceeded for StartJobRun") == "throttled"
    assert classify("AccessDenied: not authorized to s3:GetObject") == "permissions"
    assert classify("container killed: exit code 137") == "resource_exhaustion"
    assert classify("NoSuchKey: file s3://x/y does not exist") == "missing_data"
    assert classify("cannot cast 'abc' to DOUBLE") == "bad_data"
    assert classify("???") == "unknown"


def test_playbook_progression_and_finality():
    first = next_remediation("connection refused", attempt=1)
    assert first.action == "start_etl_pipeline" and not first.final

    last = next_remediation("connection refused", attempt=3)
    assert last.action == "escalate" and last.final

    # attempts beyond playbook length stay on final step
    beyond = next_remediation("connection refused", attempt=10)
    assert beyond.action == "escalate" and beyond.final


def test_permissions_never_retries():
    assert next_remediation("AccessDenied", attempt=1).action == "escalate"


# --- profiler / scanner ----------------------------------------------------

def test_profile_rows_types_and_stats():
    rows = [
        {"id": 1, "price": "10.5", "name": "a", "flag": True},
        {"id": 2, "price": "20.5", "name": None, "flag": False},
        {"id": 3, "price": "30.5", "name": "c", "flag": True},
    ]
    profile = profile_rows(rows)
    schema = profile.schema()
    assert schema == {"id": "integer", "price": "double", "name": "string", "flag": "boolean"}
    price = next(c for c in profile.columns if c.name == "price")
    assert price.mean == 20.5
    name = next(c for c in profile.columns if c.name == "name")
    assert round(name.null_rate, 2) == 0.33


def test_discover_s3_prefixes_groups_by_prefix():
    objects = [
        {"Key": "raw/orders/2026/01.parquet", "Size": 100},
        {"Key": "raw/orders/2026/02.parquet", "Size": 200},
        {"Key": "raw/users/u.csv", "Size": 50},
        {"Key": "raw/readme.txt", "Size": 5},  # not a data file
    ]
    sources = discover_s3_prefixes(objects, "lake")
    ids = [s.source_id for s in sources]
    assert ids == ["s3://lake/raw/orders/2026/", "s3://lake/raw/users/"]
    assert sources[0].metadata == {"files": 2, "bytes": 300}
    assert infer_format("x.JSONL") == "jsonl"


# --- docs ------------------------------------------------------------------

def test_render_catalog_contains_everything():
    md = render_catalog(
        sources=[{"source_id": "s3://lake/raw/orders/", "kind": "s3",
                  "location": "s3://lake/raw/orders/", "format_hint": "parquet"}],
        schemas={"orders": {"id": "integer", "price": "double"}},
        pipelines=[{"pipeline_id": "orders", "source": "s3://lake/raw/orders/",
                    "destination": "s3://lake/curated/orders/",
                    "schedule": "rate(1 day)", "quality_rules": [{}]}],
        lineage=[("s3://lake/raw/orders/", "s3://lake/curated/orders/")],
    )
    assert "# Data Platform Handbook" in md
    assert "| id | integer |" in md
    assert "mermaid" in md


def test_empty_catalog_renders():
    md = render_catalog([], {}, [])
    assert "_No sources discovered yet._" in md


# --- alerting --------------------------------------------------------------

def test_alert_dedupe_window():
    alerter = Alerter("arn:topic", dedupe_seconds=300, enabled=False)
    alert = Alert("critical", "pipeline down", {"p": 1})
    assert alerter.send(alert) is True
    assert alerter.send(alert) is False  # suppressed
    assert alerter.send(Alert("info", "pipeline down", {})) is True  # different severity
