"""Automatic data-source discovery.

Scans the accounts' S3 buckets (tag-filtered), Glue catalog, and RDS
instances for datasets the agent does not yet know about, and emits a
`source_discovered` event per new source so the planner can decide whether
to profile it and build a pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DATA_FILE_SUFFIXES = (".csv", ".json", ".jsonl", ".parquet", ".avro", ".orc", ".tsv")


@dataclass
class DiscoveredSource:
    source_id: str
    kind: str  # s3 | glue_table | rds
    location: str
    format_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "source_discovered",
            "id": self.source_id,
            "kind": self.kind,
            "location": self.location,
            "format_hint": self.format_hint,
            "metadata": self.metadata,
        }


def infer_format(key: str) -> str:
    lower = key.lower()
    for suffix in DATA_FILE_SUFFIXES:
        if lower.endswith(suffix):
            return suffix.lstrip(".")
    return ""


def discover_s3_prefixes(objects: list[dict[str, Any]], bucket: str) -> list[DiscoveredSource]:
    """Group object listings into dataset-level prefixes.

    `objects` is a list of {"Key": str, "Size": int} dicts (the shape boto3
    returns), so the grouping logic is testable without AWS.
    """
    prefixes: dict[str, dict[str, Any]] = {}
    for obj in objects:
        key = obj.get("Key", "")
        fmt = infer_format(key)
        if not fmt:
            continue
        prefix = key.rsplit("/", 1)[0] + "/" if "/" in key else ""
        entry = prefixes.setdefault(
            prefix, {"format": fmt, "files": 0, "bytes": 0}
        )
        entry["files"] += 1
        entry["bytes"] += int(obj.get("Size", 0))
    sources = []
    for prefix, stats in sorted(prefixes.items()):
        source_id = f"s3://{bucket}/{prefix}"
        sources.append(
            DiscoveredSource(
                source_id=source_id,
                kind="s3",
                location=source_id,
                format_hint=stats["format"],
                metadata={"files": stats["files"], "bytes": stats["bytes"]},
            )
        )
    return sources


class SourceScanner:
    """AWS-backed scanner. Each scan_* method returns DiscoveredSource items."""

    def __init__(self) -> None:
        import boto3

        self._s3 = boto3.client("s3")
        self._glue = boto3.client("glue")
        self._rds = boto3.client("rds")

    def scan_bucket(self, bucket: str, prefix: str = "") -> list[DiscoveredSource]:
        paginator = self._s3.get_paginator("list_objects_v2")
        objects: list[dict[str, Any]] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects.extend(page.get("Contents", []))
        return discover_s3_prefixes(objects, bucket)

    def scan_glue_catalog(self) -> list[DiscoveredSource]:
        sources = []
        for db_page in self._glue.get_paginator("get_databases").paginate():
            for db in db_page.get("DatabaseList", []):
                for tbl_page in self._glue.get_paginator("get_tables").paginate(
                    DatabaseName=db["Name"]
                ):
                    for table in tbl_page.get("TableList", []):
                        sources.append(
                            DiscoveredSource(
                                source_id=f"glue://{db['Name']}/{table['Name']}",
                                kind="glue_table",
                                location=table.get("StorageDescriptor", {}).get("Location", ""),
                                metadata={"database": db["Name"], "table": table["Name"]},
                            )
                        )
        return sources

    def scan_rds(self) -> list[DiscoveredSource]:
        sources = []
        for page in self._rds.get_paginator("describe_db_instances").paginate():
            for db in page.get("DBInstances", []):
                tags = {t["Key"]: t["Value"] for t in db.get("TagList", [])}
                if tags.get("ade:discover", "").lower() != "true":
                    continue  # opt-in only — never crawl databases by default
                sources.append(
                    DiscoveredSource(
                        source_id=f"rds://{db['DBInstanceIdentifier']}",
                        kind="rds",
                        location=db.get("Endpoint", {}).get("Address", ""),
                        metadata={"engine": db.get("Engine", "")},
                    )
                )
        return sources
