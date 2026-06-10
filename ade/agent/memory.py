"""Agent memory — durable state in DynamoDB with an in-memory fallback.

Single-table layout (pk, sk):
    SOURCE#<id>        / META            -> discovered source record
    SCHEMA#<dataset>   / V#<n>           -> schema version (fingerprint + columns)
    PIPELINE#<id>      / META            -> registered pipeline spec
    INCIDENT#<id>      / ATTEMPT#<n>     -> remediation attempts
    DECISION#<ts>      / EVENT#<id>      -> audit log of every plan executed
"""

from __future__ import annotations

import json
import time
from typing import Any


class MemoryStore:
    """In-memory store; base class and test double."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], dict[str, Any]] = {}

    def put(self, pk: str, sk: str, item: dict[str, Any]) -> None:
        self._items[(pk, sk)] = {**item, "pk": pk, "sk": sk, "updated_at": int(time.time())}

    def get(self, pk: str, sk: str) -> dict[str, Any] | None:
        return self._items.get((pk, sk))

    def query(self, pk: str) -> list[dict[str, Any]]:
        return sorted(
            (v for (p, _), v in self._items.items() if p == pk),
            key=lambda v: v["sk"],
        )

    # -- domain helpers ----------------------------------------------------

    def record_decision(self, event: dict[str, Any], plan_summary: dict[str, Any]) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        event_id = str(event.get("id", "unknown"))
        self.put(f"DECISION#{ts}", f"EVENT#{event_id}", {"event": event, "plan": plan_summary})

    def remediation_attempts(self, incident_id: str) -> int:
        return len(self.query(f"INCIDENT#{incident_id}"))

    def record_remediation(self, incident_id: str, action: str, outcome: str) -> None:
        attempt = self.remediation_attempts(incident_id) + 1
        self.put(
            f"INCIDENT#{incident_id}",
            f"ATTEMPT#{attempt:03d}",
            {"action": action, "outcome": outcome},
        )

    def latest_schema(self, dataset: str) -> dict[str, Any] | None:
        versions = self.query(f"SCHEMA#{dataset}")
        return versions[-1] if versions else None

    def record_schema(self, dataset: str, schema: dict[str, Any]) -> int:
        versions = self.query(f"SCHEMA#{dataset}")
        version = len(versions) + 1
        self.put(f"SCHEMA#{dataset}", f"V#{version:06d}", {"schema": schema, "version": version})
        return version

    def snapshot(self) -> dict[str, Any]:
        """Compact view of memory passed to the planner (keep token cost low)."""
        sources = [k[0] for k in self._items if k[0].startswith("SOURCE#")]
        pipelines = [k[0] for k in self._items if k[0].startswith("PIPELINE#")]
        open_incidents = sorted({k[0] for k in self._items if k[0].startswith("INCIDENT#")})
        return {
            "known_sources": sorted(set(sources)),
            "registered_pipelines": sorted(set(pipelines)),
            "open_incidents": [
                {"incident": pk, "attempts": self.remediation_attempts(pk.split("#", 1)[1])}
                for pk in open_incidents
            ],
        }


class DynamoMemoryStore(MemoryStore):
    """DynamoDB-backed store used in Lambda."""

    def __init__(self, table_name: str) -> None:
        super().__init__()
        import boto3  # lazy: keeps unit tests dependency-free

        self._table = boto3.resource("dynamodb").Table(table_name)

    def put(self, pk: str, sk: str, item: dict[str, Any]) -> None:
        record = {**item, "pk": pk, "sk": sk, "updated_at": int(time.time())}
        # DynamoDB rejects floats; round-trip through JSON keeps types simple.
        self._table.put_item(Item=json.loads(json.dumps(record, default=str), parse_float=str))

    def get(self, pk: str, sk: str) -> dict[str, Any] | None:
        resp = self._table.get_item(Key={"pk": pk, "sk": sk})
        return resp.get("Item")

    def query(self, pk: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        resp = self._table.query(KeyConditionExpression=Key("pk").eq(pk))
        return resp.get("Items", [])

    def snapshot(self) -> dict[str, Any]:
        # Bounded scan: enough context for the planner without unbounded cost.
        resp = self._table.scan(
            ProjectionExpression="pk", Limit=500
        )
        pks = {item["pk"] for item in resp.get("Items", [])}
        return {
            "known_sources": sorted(p for p in pks if p.startswith("SOURCE#")),
            "registered_pipelines": sorted(p for p in pks if p.startswith("PIPELINE#")),
            "open_incidents": [
                {"incident": p, "attempts": self.remediation_attempts(p.split("#", 1)[1])}
                for p in sorted(p for p in pks if p.startswith("INCIDENT#"))
            ],
        }
