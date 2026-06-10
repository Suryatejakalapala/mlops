"""Schema drift detection.

Compares the registered schema (column -> type) against the freshly
profiled one and classifies each change:

    added column          -> additive   (safe; backfill optional)
    removed column        -> breaking   (downstream consumers break)
    type change           -> breaking unless a safe widening (int -> double)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

SAFE_WIDENINGS = {("integer", "double")}


@dataclass
class SchemaChange:
    column: str
    change: str        # added | removed | type_changed
    old_type: str = ""
    new_type: str = ""
    breaking: bool = False


@dataclass
class DriftReport:
    dataset: str
    changes: list[SchemaChange] = field(default_factory=list)

    @property
    def drifted(self) -> bool:
        return bool(self.changes)

    @property
    def breaking(self) -> bool:
        return any(c.breaking for c in self.changes)

    def to_event(self, incident_id: str = "") -> dict:
        return {
            "type": "schema_drift",
            "id": f"drift-{self.dataset}",
            "incident_id": incident_id or f"schema-{self.dataset}",
            "dataset": self.dataset,
            "breaking": self.breaking,
            "changes": [
                {
                    "column": c.column,
                    "change": c.change,
                    "old_type": c.old_type,
                    "new_type": c.new_type,
                    "breaking": c.breaking,
                }
                for c in self.changes
            ],
        }


def fingerprint(schema: dict[str, str]) -> str:
    """Stable hash of a schema; equal fingerprints mean no drift."""
    canonical = json.dumps(sorted(schema.items()))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def detect(dataset: str, registered: dict[str, str], observed: dict[str, str]) -> DriftReport:
    report = DriftReport(dataset=dataset)
    for column, new_type in observed.items():
        if column not in registered:
            report.changes.append(
                SchemaChange(column=column, change="added", new_type=new_type, breaking=False)
            )
    for column, old_type in registered.items():
        if column not in observed:
            report.changes.append(
                SchemaChange(column=column, change="removed", old_type=old_type, breaking=True)
            )
            continue
        new_type = observed[column]
        if new_type != old_type and new_type != "unknown" and old_type != "unknown":
            breaking = (old_type, new_type) not in SAFE_WIDENINGS
            report.changes.append(
                SchemaChange(
                    column=column,
                    change="type_changed",
                    old_type=old_type,
                    new_type=new_type,
                    breaking=breaking,
                )
            )
    return report
