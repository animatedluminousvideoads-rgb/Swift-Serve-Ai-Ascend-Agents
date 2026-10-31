"""Calling guardrails: who the AI agent may call, and when.

Rules enforced before any contact is enrolled in the GHL call workflow:
  * US/Canada numbers only, normalized to E.164.
  * Only inside the campaign calling window, in the business's local time zone
    (config validation also pins it inside the TCPA 8am-9pm range).
  * Never contacts marked DND in GHL, tagged do-not-call, or listed in
    ASCEND_SUPPRESS_NUMBERS.
  * AI voices are "artificial voice" under the TCPA (FCC, Feb 2024), which needs
    prior express consent for mobile numbers. Mobile lines are held for human
    review; unverifiable lines follow calling.unverified_line_policy.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .config import CallingWindow

log = logging.getLogger(__name__)

TWILIO_LOOKUP = "https://lookups.twilio.com/v2/PhoneNumbers/{number}"

DNC_TAG = "ascend-dnc"


def normalize_phone(raw: str) -> str | None:
    """Normalize a North American number to E.164 (+1XXXXXXXXXX); None if not NANP."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01" or digits[3] in "01":
        return None
    return "+1" + digits


def mask_phone(e164: str) -> str:
    return f"{e164[:2]}******{e164[-4:]}" if e164 and len(e164) > 6 else "***"


def in_calling_window(window: CallingWindow, tz: str, now: datetime | None = None) -> bool:
    local = (now or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo(tz))
    if local.weekday() not in window.days:
        return False
    return window.start <= local.time().replace(second=0, microsecond=0) < window.end


def lookup_line_type(
    e164: str, sid: str, token: str, session: requests.Session | None = None
) -> str:
    """Twilio Lookup v2 line type (mobile, landline, fixedVoip, ...). '' if unknown."""
    http = session or requests.Session()
    try:
        resp = http.get(
            TWILIO_LOOKUP.format(number=e164),
            params={"Fields": "line_type_intelligence"},
            auth=(sid, token),
            timeout=15,
        )
        resp.raise_for_status()
        info = resp.json().get("line_type_intelligence") or {}
        return info.get("type") or ""
    except requests.RequestException as exc:
        log.warning("line type lookup failed for %s: %s", mask_phone(e164), exc)
        return ""


def line_type_hold_reason(line_type: str, window: CallingWindow) -> str:
    """Why a number must not be auto-called based on its line type ('' = OK)."""
    if not line_type:
        if window.unverified_line_policy == "call":
            return ""
        return "line type unverified (add Twilio Lookup credentials or review manually)"
    if line_type in window.auto_call_line_types:
        return ""
    if line_type == "mobile":
        return "mobile number: AI-voice calls need prior consent (TCPA); call manually"
    return f"line type '{line_type}' not in auto_call_line_types"


def contact_block_reason(contact: dict, suppressed: frozenset[str]) -> str:
    """Why a GHL contact must never be called ('' = OK)."""
    if contact.get("dnd"):
        return "DND enabled in GHL"
    call_dnd = ((contact.get("dndSettings") or {}).get("Call") or {}).get("status")
    if call_dnd in ("active", "permanent"):
        return "call DND enabled in GHL"
    if DNC_TAG in [t.lower() for t in contact.get("tags") or []]:
        return "tagged do-not-call"
    if contact.get("phone") and normalize_phone(contact["phone"]) in suppressed:
        return "number is on the suppression list"
    return ""
