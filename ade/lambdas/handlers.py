"""Lambda entrypoints.

Each handler is a thin adapter: parse the trigger, build domain objects,
hand off to the orchestrator or capability module, flush metrics. Handlers
are mapped to functions in terraform/lambda.tf.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ade.config import load_settings

logging.getLogger().setLevel(logging.INFO)


def _orchestrator():
    from ade.agent.memory import DynamoMemoryStore
    from ade.agent.orchestrator import Orchestrator
    from ade.llm import BedrockPlannerClient
    from ade.monitoring.metrics import MetricsSink

    settings = load_settings()
    return Orchestrator(
        settings=settings,
        planner_client=BedrockPlannerClient(settings.planner_model, settings.planner_max_tokens),
        memory=DynamoMemoryStore(settings.state_table),
        metrics=MetricsSink(settings.metrics_namespace,
                            dimensions={"Environment": settings.environment}),
    )


def agent_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Central agent loop — target of every EventBridge rule."""
    detail = event.get("detail", event)
    orchestrator = _orchestrator()
    report = orchestrator.handle_event(detail)
    orchestrator.metrics.flush()
    return {
        "ok": report.ok,
        "event_type": report.event_type,
        "error": report.error,
        "actions": [{"name": r.action, "status": r.status} for r in report.results],
    }


def discovery_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Scheduled scan: find new sources and emit source_discovered events."""
    import boto3

    from ade.agent.memory import DynamoMemoryStore
    from ade.discovery.scanner import SourceScanner

    settings = load_settings()
    memory = DynamoMemoryStore(settings.state_table)
    scanner = SourceScanner()

    sources = scanner.scan_bucket(settings.data_lake_bucket, prefix="raw/")
    sources += scanner.scan_glue_catalog()
    sources += scanner.scan_rds()

    events_client = boto3.client("events")
    emitted = 0
    for source in sources:
        if memory.get(f"SOURCE#{source.source_id}", "META"):
            continue  # already known
        memory.put(f"SOURCE#{source.source_id}", "META", source.to_event())
        events_client.put_events(Entries=[{
            "Source": "ade.discovery",
            "DetailType": "source_discovered",
            "Detail": json.dumps(source.to_event(), default=str),
            "EventBusName": settings.event_bus_name,
        }])
        emitted += 1
    return {"scanned": len(sources), "new": emitted}


def drift_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Scheduled drift check for a dataset (event carries dataset + sample)."""
    import boto3

    from ade.agent.memory import DynamoMemoryStore
    from ade.discovery.profiler import profile_rows
    from ade.drift.schema_drift import detect

    settings = load_settings()
    memory = DynamoMemoryStore(settings.state_table)
    detail = event.get("detail", event)
    dataset = detail["dataset"]
    rows = detail.get("sample_rows", [])

    observed = profile_rows(rows).schema()
    registered_entry = memory.latest_schema(dataset)
    if registered_entry is None:
        version = memory.record_schema(dataset, observed)
        return {"dataset": dataset, "first_seen": True, "version": version}

    report = detect(dataset, dict(registered_entry["schema"]), observed)
    if report.drifted:
        boto3.client("events").put_events(Entries=[{
            "Source": "ade.drift",
            "DetailType": "schema_drift",
            "Detail": json.dumps(report.to_event(), default=str),
            "EventBusName": settings.event_bus_name,
        }])
    return {"dataset": dataset, "drifted": report.drifted, "breaking": report.breaking}


def pipeline_failure_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Step Functions 'execution failed' events -> agent incident."""
    import boto3

    from ade.recovery.self_healing import FailureEvent

    settings = load_settings()
    detail = event.get("detail", event)
    execution_arn = detail.get("executionArn", "unknown")
    pipeline_id = detail.get("stateMachineArn", "unknown").split(":")[-1]
    failure = FailureEvent(
        incident_id=f"sfn-{pipeline_id}",
        pipeline_id=pipeline_id,
        error_text=str(detail.get("cause") or detail.get("error") or ""),
        context={"execution_arn": execution_arn},
    )
    boto3.client("events").put_events(Entries=[{
        "Source": "ade.recovery",
        "DetailType": "pipeline_failed",
        "Detail": json.dumps(failure.to_event(), default=str),
        "EventBusName": settings.event_bus_name,
    }])
    return {"forwarded": True, "incident_id": failure.incident_id}


def cost_handler(_event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Daily Cost Explorer pull -> anomalies as agent events."""
    import datetime as dt

    import boto3

    from ade.cost.optimizer import CostRecord, detect_anomalies

    settings = load_settings()
    end = dt.date.today()
    start = end - dt.timedelta(days=21)
    response = boto3.client("ce").get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    records: list[CostRecord] = []
    for day in response.get("ResultsByTime", []):
        date = day["TimePeriod"]["Start"]
        for group in day.get("Groups", []):
            records.append(CostRecord(
                date=date,
                service=group["Keys"][0],
                usd=float(group["Metrics"]["UnblendedCost"]["Amount"]),
            ))
    anomalies = detect_anomalies(records)
    events_client = boto3.client("events")
    for anomaly in anomalies:
        events_client.put_events(Entries=[{
            "Source": "ade.cost",
            "DetailType": "cost_anomaly",
            "Detail": json.dumps(anomaly.to_event(), default=str),
            "EventBusName": settings.event_bus_name,
        }])
    return {"records": len(records), "anomalies": len(anomalies)}


def docs_handler(_event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Regenerate the platform handbook from agent memory."""
    from ade.agent.memory import DynamoMemoryStore
    from ade.docsgen.generator import publish, render_catalog

    settings = load_settings()
    memory = DynamoMemoryStore(settings.state_table)
    snapshot = memory.snapshot()
    sources = [memory.get(pk, "META") or {} for pk in snapshot["known_sources"]]
    schemas: dict[str, dict[str, str]] = {}
    for pk in snapshot["known_sources"]:
        dataset = pk.split("#", 1)[1]
        entry = memory.latest_schema(dataset)
        if entry:
            schemas[dataset] = dict(entry["schema"])
    pipelines = [memory.get(pk, "META") or {} for pk in snapshot["registered_pipelines"]]
    markdown = render_catalog(sources, schemas, pipelines)
    uri = publish(markdown, settings.docs_bucket)
    return {"published": uri}
