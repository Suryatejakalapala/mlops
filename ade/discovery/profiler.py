"""Dataset profiling: column types, null rates, cardinality, numeric stats.

Operates on a sample of rows (list of dicts) so it works identically on
CSV/JSON pulled from S3 or rows fetched from a database cursor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnProfile:
    name: str
    inferred_type: str
    null_rate: float
    distinct_count: int
    sample_values: list[Any] = field(default_factory=list)
    mean: float | None = None
    stddev: float | None = None
    minimum: float | None = None
    maximum: float | None = None


@dataclass
class DatasetProfile:
    row_count: int
    columns: list[ColumnProfile]

    def schema(self) -> dict[str, str]:
        """Column -> type map; this is what feeds the schema registry."""
        return {c.name: c.inferred_type for c in self.columns}


def _infer_type(values: list[Any]) -> str:
    non_null = [v for v in values if v is not None and v != ""]
    if not non_null:
        return "unknown"
    if all(isinstance(v, bool) for v in non_null):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        return "integer"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "double"
    # strings that all parse as numbers are treated as numeric
    try:
        for v in non_null:
            float(v)
        return "double"
    except (TypeError, ValueError):
        return "string"


def _numeric_values(values: list[Any]) -> list[float]:
    out = []
    for v in values:
        if v is None or v == "" or isinstance(v, bool):
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            return []
    return out


def profile_rows(rows: list[dict[str, Any]], sample_limit: int = 5) -> DatasetProfile:
    if not rows:
        return DatasetProfile(row_count=0, columns=[])
    column_names: list[str] = []
    for row in rows:
        for name in row:
            if name not in column_names:
                column_names.append(name)

    columns: list[ColumnProfile] = []
    for name in column_names:
        values = [row.get(name) for row in rows]
        non_null = [v for v in values if v is not None and v != ""]
        nums = _numeric_values(values)
        mean = stddev = minimum = maximum = None
        if nums:
            mean = sum(nums) / len(nums)
            if len(nums) > 1:
                variance = sum((x - mean) ** 2 for x in nums) / (len(nums) - 1)
                stddev = math.sqrt(variance)
            minimum, maximum = min(nums), max(nums)
        columns.append(
            ColumnProfile(
                name=name,
                inferred_type=_infer_type(values),
                null_rate=round(1 - len(non_null) / len(values), 4),
                distinct_count=len({repr(v) for v in non_null}),
                sample_values=non_null[:sample_limit],
                mean=mean,
                stddev=stddev,
                minimum=minimum,
                maximum=maximum,
            )
        )
    return DatasetProfile(row_count=len(rows), columns=columns)
