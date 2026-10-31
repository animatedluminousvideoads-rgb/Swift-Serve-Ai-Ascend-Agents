"""Thin wrapper around the Claude API for structured (JSON-schema) outputs."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(Exception):
    """Raised when Claude can't produce a usable answer; callers fall back to templates."""


class Claude:
    def __init__(self, api_key: str, model: str = "claude-opus-5-5", client: Any | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic(api_key=api_key)

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        effort: str = "medium",
        max_tokens: int = 16000,
    ) -> dict[str, Any]:
        """Return a dict that validates against `schema`, or raise LLMUnavailable."""
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=system,
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable(f"rate limited: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable(f"connection error: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMUnavailable("request declined")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("output truncated")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable("response was not valid JSON") from exc
