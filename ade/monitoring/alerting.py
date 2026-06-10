"""SNS alerting with severity routing and de-duplication window."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

SEVERITIES = ("info", "warning", "critical")


@dataclass
class Alert:
    severity: str
    subject: str
    body: dict

    def validate(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity {self.severity}")


class Alerter:
    def __init__(self, topic_arn: str, dedupe_seconds: int = 300, enabled: bool = True) -> None:
        self.topic_arn = topic_arn
        self.dedupe_seconds = dedupe_seconds
        self.enabled = enabled
        self._last_sent: dict[str, float] = {}
        self.sent: list[Alert] = []  # retained for tests/inspection

    def send(self, alert: Alert) -> bool:
        """Returns True if published, False if suppressed by dedupe."""
        alert.validate()
        key = f"{alert.severity}:{alert.subject}"
        now = time.time()
        if now - self._last_sent.get(key, 0) < self.dedupe_seconds:
            return False
        self._last_sent[key] = now
        self.sent.append(alert)
        if self.enabled:
            import boto3

            boto3.client("sns").publish(
                TopicArn=self.topic_arn,
                Subject=f"[ADE {alert.severity.upper()}] {alert.subject}"[:100],
                Message=json.dumps(alert.body, indent=2, default=str),
            )
        return True
