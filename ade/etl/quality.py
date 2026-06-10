"""Data-quality rules and evaluation.

Rules are plain dicts (storable in DynamoDB / pipeline specs):
    {"rule": "not_null", "column": "id"}
    {"rule": "unique", "column": "id"}
    {"rule": "in_range", "column": "price", "min": 0, "max": 10000}
    {"rule": "matches", "column": "email", "pattern": "^[^@]+@[^@]+$"}
    {"rule": "allowed_values", "column": "status", "values": ["a", "b"]}
    {"rule": "row_count_min", "min": 1}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleResult:
    rule: dict[str, Any]
    passed: bool
    failing_rows: int = 0
    message: str = ""


@dataclass
class QualityReport:
    total_rows: int
    results: list[RuleResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def summary(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total_rows": self.total_rows,
            "failed_rules": [
                {"rule": r.rule, "failing_rows": r.failing_rows, "message": r.message}
                for r in self.results
                if not r.passed
            ],
        }


def _present(value: Any) -> bool:
    return value is not None and value != ""


def evaluate(rows: list[dict[str, Any]], rules: list[dict[str, Any]]) -> QualityReport:
    report = QualityReport(total_rows=len(rows))
    for rule in rules:
        kind = rule.get("rule")
        column = rule.get("column", "")
        if kind == "not_null":
            failing = sum(1 for r in rows if not _present(r.get(column)))
            report.results.append(RuleResult(rule, failing == 0, failing,
                                             f"{failing} null values in {column}"))
        elif kind == "unique":
            seen: dict[Any, int] = {}
            for r in rows:
                v = r.get(column)
                seen[v] = seen.get(v, 0) + 1
            failing = sum(c - 1 for c in seen.values() if c > 1)
            report.results.append(RuleResult(rule, failing == 0, failing,
                                             f"{failing} duplicate values in {column}"))
        elif kind == "in_range":
            lo, hi = rule.get("min"), rule.get("max")
            failing = 0
            for r in rows:
                v = r.get(column)
                if not _present(v):
                    continue
                try:
                    x = float(v)
                except (TypeError, ValueError):
                    failing += 1
                    continue
                if (lo is not None and x < lo) or (hi is not None and x > hi):
                    failing += 1
            report.results.append(RuleResult(rule, failing == 0, failing,
                                             f"{failing} out-of-range values in {column}"))
        elif kind == "matches":
            pattern = re.compile(rule.get("pattern", ""))
            failing = sum(
                1 for r in rows
                if _present(r.get(column)) and not pattern.search(str(r.get(column)))
            )
            report.results.append(RuleResult(rule, failing == 0, failing,
                                             f"{failing} pattern mismatches in {column}"))
        elif kind == "allowed_values":
            allowed = set(rule.get("values", []))
            failing = sum(
                1 for r in rows if _present(r.get(column)) and r.get(column) not in allowed
            )
            report.results.append(RuleResult(rule, failing == 0, failing,
                                             f"{failing} unexpected values in {column}"))
        elif kind == "row_count_min":
            minimum = int(rule.get("min", 1))
            ok = len(rows) >= minimum
            report.results.append(RuleResult(rule, ok, 0 if ok else 1,
                                             f"row count {len(rows)} < {minimum}"))
        else:
            report.results.append(RuleResult(rule, False, 0, f"unknown rule: {kind}"))
    return report


def _violates(rule: dict[str, Any], value: Any) -> bool:
    """True if a single value breaks a row-level rule."""
    kind = rule.get("rule")
    if kind == "not_null":
        return not _present(value)
    if not _present(value):
        return False  # remaining rules only judge present values
    if kind == "in_range":
        try:
            x = float(value)
        except (TypeError, ValueError):
            return True
        lo, hi = rule.get("min"), rule.get("max")
        return (lo is not None and x < lo) or (hi is not None and x > hi)
    if kind == "matches":
        return not re.search(rule.get("pattern", ""), str(value))
    if kind == "allowed_values":
        return value not in set(rule.get("values", []))
    return False  # dataset-level rules (unique, row_count_min) aren't row-attributable


def split_failing_rows(
    rows: list[dict[str, Any]], rules: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition rows into (clean, quarantined) for row-level rules."""
    quarantined_idx = {
        i
        for rule in rules
        for i, row in enumerate(rows)
        if _violates(rule, row.get(rule.get("column", "")))
    }
    clean = [r for i, r in enumerate(rows) if i not in quarantined_idx]
    quarantined = [r for i, r in enumerate(rows) if i in quarantined_idx]
    return clean, quarantined
