"""Documentation generator.

Renders a markdown data-platform handbook from the agent's memory: known
sources, registered schemas, pipelines, and lineage. Output is written to
the docs bucket and regenerated whenever the platform changes.
"""

from __future__ import annotations

import time
from typing import Any


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def render_catalog(
    sources: list[dict[str, Any]],
    schemas: dict[str, dict[str, str]],
    pipelines: list[dict[str, Any]],
    lineage: list[tuple[str, str]] | None = None,
) -> str:
    """Render the full handbook as a single markdown document."""
    generated = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    parts = [
        "# Data Platform Handbook",
        "",
        f"_Generated automatically by ADE on {generated}. Do not edit by hand._",
        "",
        "## Data Sources",
        "",
    ]
    if sources:
        parts.append(_table(
            ["Source", "Kind", "Location", "Format"],
            [[s.get("source_id", ""), s.get("kind", ""), s.get("location", ""),
              s.get("format_hint", "")] for s in sources],
        ))
    else:
        parts.append("_No sources discovered yet._")

    parts += ["", "## Schemas", ""]
    if schemas:
        for dataset, schema in sorted(schemas.items()):
            parts.append(f"### {dataset}")
            parts.append("")
            parts.append(_table(
                ["Column", "Type"],
                [[col, typ] for col, typ in sorted(schema.items())],
            ))
            parts.append("")
    else:
        parts.append("_No schemas registered yet._")

    parts += ["", "## Pipelines", ""]
    if pipelines:
        parts.append(_table(
            ["Pipeline", "Source", "Destination", "Schedule", "Quality rules"],
            [[p.get("pipeline_id", ""), p.get("source", ""), p.get("destination", ""),
              p.get("schedule", ""), str(len(p.get("quality_rules", [])))]
             for p in pipelines],
        ))
    else:
        parts.append("_No pipelines registered yet._")

    if lineage:
        parts += ["", "## Lineage", "", "```mermaid", "graph LR"]
        for src, dst in lineage:
            parts.append(f'    {_node_id(src)}["{src}"] --> {_node_id(dst)}["{dst}"]')
        parts += ["```", ""]

    return "\n".join(parts) + "\n"


def _node_id(name: str) -> str:
    return "n_" + "".join(c if c.isalnum() else "_" for c in name)[:48]


def publish(markdown: str, bucket: str, key: str = "handbook.md") -> str:
    import boto3

    boto3.client("s3").put_object(
        Bucket=bucket, Key=key, Body=markdown.encode(), ContentType="text/markdown"
    )
    return f"s3://{bucket}/{key}"
