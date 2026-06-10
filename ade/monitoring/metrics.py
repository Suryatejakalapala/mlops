"""CloudWatch metrics sink with buffering and a disabled mode for tests."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ade.metrics")


class MetricsSink:
    def __init__(self, namespace: str, enabled: bool = True,
                 dimensions: dict[str, str] | None = None) -> None:
        self.namespace = namespace
        self.enabled = enabled
        self.dimensions = dimensions or {}
        self._buffer: list[dict[str, Any]] = []

    def count(self, name: str, value: float = 1.0) -> None:
        self._add(name, value, "Count")

    def gauge(self, name: str, value: float, unit: str = "None") -> None:
        self._add(name, value, unit)

    def millis(self, name: str, value: float) -> None:
        self._add(name, value, "Milliseconds")

    def _add(self, name: str, value: float, unit: str) -> None:
        datum: dict[str, Any] = {"MetricName": name, "Value": value, "Unit": unit}
        if self.dimensions:
            datum["Dimensions"] = [
                {"Name": k, "Value": v} for k, v in sorted(self.dimensions.items())
            ]
        self._buffer.append(datum)
        if len(self._buffer) >= 20:  # CloudWatch caps 1000/call; flush early
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        if not self.enabled:
            self._buffer.clear()
            return
        import boto3

        try:
            boto3.client("cloudwatch").put_metric_data(
                Namespace=self.namespace, MetricData=self._buffer
            )
        except Exception:
            logger.exception("failed to flush metrics")  # metrics must never crash the agent
        finally:
            self._buffer.clear()

    @property
    def pending(self) -> list[dict[str, Any]]:
        return list(self._buffer)
