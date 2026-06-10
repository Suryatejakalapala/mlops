"""Failure classification and remediation playbooks.

Pipeline/job failures are classified from their error text into a failure
class; each class maps to an ordered remediation playbook. The orchestrator
executes one step per attempt and escalates once the retry budget is spent
(enforced in Orchestrator.handle_event).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Patterns are checked in order; first match wins.
CLASSIFIERS: list[tuple[str, str]] = [
    (r"(throttl|rate exceeded|too many requests|429)", "throttled"),
    (r"(access ?denied|forbidden|not authorized|403)", "permissions"),
    (r"(out of memory|oom|memoryerror|exit code 137)", "resource_exhaustion"),
    (r"(timed? ?out|deadline exceeded)", "timeout"),
    (r"(no such key|404|not found|file.*missing|does not exist)", "missing_data"),
    (r"(schema|column .* not found|type mismatch|cannot cast|parse error|malformed)", "bad_data"),
    (r"(connection (refused|reset)|network|dns|unreachable)", "transient_network"),
    (r"(disk full|no space left)", "storage_full"),
]

# Failure class -> ordered remediation steps (action names from the
# planner's allowlist; attempt N runs step min(N, len)-1).
PLAYBOOKS: dict[str, list[dict]] = {
    "throttled": [
        {"action": "start_etl_pipeline", "note": "retry with backoff"},
        {"action": "start_etl_pipeline", "note": "retry with backoff"},
        {"action": "escalate", "note": "persistent throttling"},
    ],
    "transient_network": [
        {"action": "start_etl_pipeline", "note": "retry"},
        {"action": "start_etl_pipeline", "note": "retry"},
        {"action": "escalate", "note": "network issue persists"},
    ],
    "timeout": [
        {"action": "start_etl_pipeline", "note": "retry once"},
        {"action": "escalate", "note": "likely needs bigger resources or smaller batches"},
    ],
    "missing_data": [
        {"action": "backfill_partition", "note": "re-run upstream extract"},
        {"action": "escalate", "note": "upstream data still missing"},
    ],
    "bad_data": [
        {"action": "quarantine_records", "note": "isolate offending records"},
        {"action": "run_quality_checks", "note": "verify remaining data"},
        {"action": "escalate", "note": "data contract violation"},
    ],
    "resource_exhaustion": [
        {"action": "escalate", "note": "needs resource resize (human decision)"},
    ],
    "storage_full": [
        {"action": "escalate", "note": "storage capacity issue"},
    ],
    "permissions": [
        {"action": "escalate", "note": "IAM change required — never self-modify permissions"},
    ],
    "unknown": [
        {"action": "start_etl_pipeline", "note": "single blind retry"},
        {"action": "escalate", "note": "unclassified failure"},
    ],
}


@dataclass
class Remediation:
    failure_class: str
    action: str
    note: str
    attempt: int
    final: bool


def classify(error_text: str) -> str:
    lowered = (error_text or "").lower()
    for pattern, failure_class in CLASSIFIERS:
        if re.search(pattern, lowered):
            return failure_class
    return "unknown"


def next_remediation(error_text: str, attempt: int) -> Remediation:
    """attempt is 1-based: the Nth time we've seen this incident."""
    failure_class = classify(error_text)
    playbook = PLAYBOOKS[failure_class]
    index = min(max(attempt, 1), len(playbook)) - 1
    step = playbook[index]
    return Remediation(
        failure_class=failure_class,
        action=step["action"],
        note=step["note"],
        attempt=attempt,
        final=index == len(playbook) - 1,
    )


@dataclass
class FailureEvent:
    incident_id: str
    pipeline_id: str
    error_text: str
    attempt: int = 1
    context: dict = field(default_factory=dict)

    def to_event(self) -> dict:
        return {
            "type": "pipeline_failed",
            "id": f"failure-{self.pipeline_id}",
            "incident_id": self.incident_id,
            "pipeline_id": self.pipeline_id,
            "failure_class": classify(self.error_text),
            "error_text": self.error_text[:2000],
            "attempt": self.attempt,
            "suggested_remediation": next_remediation(self.error_text, self.attempt).__dict__,
            **self.context,
        }
