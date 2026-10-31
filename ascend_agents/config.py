"""Campaign config (config/campaign.yaml) and runtime settings (env vars)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CAMPAIGN = REPO_ROOT / "config" / "campaign.yaml"

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass(frozen=True)
class Niche:
    key: str
    query: str
    label: str
    avg_ticket: int


@dataclass(frozen=True)
class Market:
    city: str
    timezone: str


@dataclass(frozen=True)
class CallingWindow:
    days: tuple[int, ...]  # 0=Mon ... 6=Sun
    start: time
    end: time
    auto_call_line_types: tuple[str, ...]
    unverified_line_policy: str  # "hold" | "call"


@dataclass(frozen=True)
class Campaign:
    agency: dict[str, Any]
    niches: dict[str, Niche]
    markets: list[Market]
    targeting: dict[str, Any]
    limits: dict[str, int]
    calling: CallingWindow
    ghl: dict[str, Any]
    sites: dict[str, Any]

    @property
    def stages(self) -> dict[str, str]:
        return self.ghl["stages"]


def _parse_time(value: str) -> time:
    hh, mm = str(value).split(":")
    return time(int(hh), int(mm))


def load_campaign(path: str | Path | None = None) -> Campaign:
    path = Path(path or os.environ.get("ASCEND_CAMPAIGN", DEFAULT_CAMPAIGN))
    raw = yaml.safe_load(path.read_text())

    niches = {
        key: Niche(key=key, query=v["query"], label=v["label"], avg_ticket=int(v["avg_ticket"]))
        for key, v in raw["niches"].items()
    }
    markets = [Market(city=m["city"], timezone=m["timezone"]) for m in raw["markets"]]

    c = raw["calling"]
    start, end = _parse_time(c["start"]), _parse_time(c["end"])
    if start < time(8, 0) or end > time(21, 0) or start >= end:
        raise ValueError("calling window must sit inside 08:00-21:00 local time (TCPA)")
    policy = c.get("unverified_line_policy", "hold")
    if policy not in ("hold", "call"):
        raise ValueError("calling.unverified_line_policy must be 'hold' or 'call'")
    calling = CallingWindow(
        days=tuple(WEEKDAYS.index(d.lower()[:3]) for d in c["days"]),
        start=start,
        end=end,
        auto_call_line_types=tuple(c.get("auto_call_line_types", [])),
        unverified_line_policy=policy,
    )

    site_base = os.environ.get("ASCEND_SITE_BASE_URL") or raw["sites"]["base_url"]
    sites = {**raw["sites"], "base_url": site_base.rstrip("/")}

    return Campaign(
        agency=raw["agency"],
        niches=niches,
        markets=markets,
        targeting=raw["targeting"],
        limits={k: int(v) for k, v in raw["limits"].items()},
        calling=calling,
        ghl=raw["ghl"],
        sites=sites,
    )


@dataclass(frozen=True)
class Settings:
    """Secrets and switches, read from the environment (GitHub Actions secrets)."""

    ghl_token: str = ""
    ghl_location_id: str = ""
    google_places_key: str = ""
    anthropic_key: str = ""
    twilio_sid: str = ""
    twilio_token: str = ""
    claude_model: str = "claude-opus-5-5"
    suppressed_numbers: frozenset[str] = field(default_factory=frozenset)
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        suppressed = frozenset(
            n.strip() for n in env.get("ASCEND_SUPPRESS_NUMBERS", "").split(",") if n.strip()
        )
        return cls(
            ghl_token=env.get("GHL_API_TOKEN", ""),
            ghl_location_id=env.get("GHL_LOCATION_ID", ""),
            google_places_key=env.get("GOOGLE_PLACES_API_KEY", ""),
            anthropic_key=env.get("ANTHROPIC_API_KEY", ""),
            twilio_sid=env.get("TWILIO_ACCOUNT_SID", ""),
            twilio_token=env.get("TWILIO_AUTH_TOKEN", ""),
            claude_model=env.get("ASCEND_CLAUDE_MODEL", "claude-opus-5-5"),
            suppressed_numbers=suppressed,
            dry_run=env.get("ASCEND_DRY_RUN", "").lower() in ("1", "true", "yes"),
        )

    @property
    def has_ghl(self) -> bool:
        return bool(self.ghl_token and self.ghl_location_id)

    @property
    def has_twilio(self) -> bool:
        return bool(self.twilio_sid and self.twilio_token)

    @property
    def has_claude(self) -> bool:
        return bool(self.anthropic_key)
