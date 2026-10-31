"""Turn a Voice AI call log into a structured outcome."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from .llm import Claude, LLMUnavailable

log = logging.getLogger(__name__)

OUTCOMES = (
    "booked",             # a meeting was booked
    "interested",         # wants to learn more / asked for the link / call back later
    "not_interested",
    "do_not_call",        # asked not to be called again / to be removed
    "wrong_number",
    "gatekeeper",         # couldn't reach the decision maker, no clear answer
    "voicemail",
    "no_answer",
    "other",
)

# outcome -> pipeline stage key from campaign.yaml
STAGE_FOR_OUTCOME = {
    "booked": "booked",
    "interested": "interested",
    "not_interested": "not_interested",
    "do_not_call": "dnc",
    "wrong_number": "dnc",
    "gatekeeper": "called",
    "voicemail": "called",
    "no_answer": "called",
    "other": "called",
}

OUTCOME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": list(OUTCOMES)},
        "sms_link_consent": {
            "type": "boolean",
            "description": "True only if the person clearly agreed to receive a text with the link.",
        },
        "email": {"type": "string", "description": "Email the person gave for the link, or empty."},
        "decision_maker_name": {"type": "string", "description": "Owner/decision maker name if mentioned, or empty."},
        "callback_time": {"type": "string", "description": "When they asked to be called back, or empty."},
        "summary": {"type": "string", "description": "One-sentence summary for the sales rep."},
    },
    "required": ["outcome", "sms_link_consent", "email", "decision_maker_name", "callback_time", "summary"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You review transcripts of short outbound sales calls placed by an AI \
assistant to local businesses, and record what happened for the sales rep's CRM.

Pick the single outcome that best fits:
- booked: a meeting time was agreed.
- interested: they want the link, more info, or a call back later.
- not_interested: they declined.
- do_not_call: they asked not to be called again, to be removed from a list, or similar. When \
in doubt between not_interested and do_not_call, choose do_not_call, because calling someone \
again after they asked us to stop is the costlier mistake.
- wrong_number: not the business we were trying to reach.
- gatekeeper: reached staff but not the decision maker, with no clear yes or no.
- voicemail: the call went to voicemail or an answering machine.
- no_answer: nobody really engaged (silence, immediate hang-up).
- other: anything else.

sms_link_consent is true only when the person clearly said yes to receiving a text message. An \
email address counts only if they actually gave one. Lines prefixed "bot:" are the AI \
assistant; lines prefixed "human:" are the person called."""


@dataclass
class CallOutcome:
    outcome: str
    sms_link_consent: bool = False
    email: str = ""
    decision_maker_name: str = ""
    callback_time: str = ""
    summary: str = ""

    @property
    def stage_key(self) -> str:
        return STAGE_FOR_OUTCOME.get(self.outcome, "called")


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def heuristic_outcome(log_entry: dict[str, Any]) -> CallOutcome:
    """Conservative keyword fallback used when Claude isn't configured or fails."""
    transcript = (log_entry.get("transcript") or "").lower()
    human = " ".join(
        line.split(":", 1)[1] for line in transcript.splitlines() if line.strip().startswith("human:")
    )
    summary = (log_entry.get("summary") or "").strip()
    if any(p in human for p in ("don't call", "do not call", "stop calling", "remove", "take me off", "never call")):
        return CallOutcome("do_not_call", summary=summary)
    if "wrong number" in human:
        return CallOutcome("wrong_number", summary=summary)
    if not human.strip():
        if any(p in transcript for p in ("voicemail", "leave a message", "after the tone", "after the beep")):
            return CallOutcome("voicemail", summary=summary)
        return CallOutcome("no_answer", summary=summary)
    if any(p in human for p in ("not interested", "no thanks", "no thank you", "we're good", "we are good")):
        return CallOutcome("not_interested", summary=summary)
    email = _EMAIL.search(human)
    if any(p in human for p in ("interested", "sounds good", "send it", "send me", "call me back", "tell me more")):
        return CallOutcome("interested", email=email.group(0) if email else "", summary=summary)
    return CallOutcome("other", summary=summary)


def classify_call(log_entry: dict[str, Any], claude: Claude | None) -> CallOutcome:
    actions = log_entry.get("executedCallActions") or []
    booked = any((a or {}).get("actionType") == "APPOINTMENT_BOOKING" for a in actions)
    if claude is None:
        result = heuristic_outcome(log_entry)
    else:
        prompt = (
            f"Call summary from the phone system:\n{log_entry.get('summary') or '(none)'}\n\n"
            f"Transcript:\n{log_entry.get('transcript') or '(empty)'}"
        )
        try:
            data = claude.structured(system=SYSTEM_PROMPT, prompt=prompt, schema=OUTCOME_SCHEMA, effort="low")
            result = CallOutcome(**data)
        except (LLMUnavailable, TypeError) as exc:
            log.warning("call classification fell back to keywords: %s", exc)
            result = heuristic_outcome(log_entry)
    if booked and result.outcome not in ("do_not_call", "wrong_number"):
        result.outcome = "booked"
    if result.outcome not in OUTCOMES:
        result.outcome = "other"
    return result
