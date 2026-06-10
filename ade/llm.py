"""Claude planner client (Amazon Bedrock).

Single integration point with the LLM. The system prompt is frozen and
cached (prompt caching is a prefix match — keep volatile content in the
user turn). The model returns a strict-JSON plan enforced via
output_config.format, so downstream code never parses free text.

Bedrock model IDs carry the `anthropic.` provider prefix
(e.g. `anthropic.claude-opus-4-8`).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "Short justification for the chosen actions.",
        },
        "risk": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Overall blast-radius assessment for this plan.",
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Action name from the allowlist."},
                    "params": {
                        "type": "object",
                        "description": "Action parameters.",
                        "additionalProperties": True,
                    },
                    "requires_approval": {
                        "type": "boolean",
                        "description": "True if a human must approve before execution.",
                    },
                },
                "required": ["name", "params", "requires_approval"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reasoning", "risk", "actions"],
    "additionalProperties": False,
}


class PlannerClient(Protocol):
    """Anything that can turn (system, user) into a plan dict."""

    def complete_plan(self, system: str, user: str) -> dict[str, Any]: ...


class BedrockPlannerClient:
    """Production client — Claude on Amazon Bedrock via the Anthropic SDK."""

    def __init__(self, model: str, max_tokens: int = 16000) -> None:
        # Lazy import keeps unit tests free of the SDK dependency.
        from anthropic import AnthropicBedrockMantle

        self._client = AnthropicBedrockMantle()
        self._model = model
        self._max_tokens = max_tokens

    def complete_plan(self, system: str, user: str) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": PLAN_SCHEMA},
            },
            system=[
                {
                    "type": "text",
                    "text": system,
                    # Frozen prefix → ~90% input-cost reduction on repeat calls.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)
