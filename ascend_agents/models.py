"""The Lead record that flows through the pipeline."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any


def slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "business"


@dataclass
class Review:
    rating: float
    text: str


@dataclass
class Lead:
    source_id: str              # Google place id, or a stable hash for CSV rows
    name: str
    niche_key: str
    niche_label: str
    market: str                 # "Phoenix, AZ"
    timezone: str               # IANA tz of the business
    phone: str = ""             # E.164 (+15551234567) once normalized
    phone_display: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    website: str = ""
    rating: float | None = None
    review_count: int = 0
    maps_url: str = ""
    business_status: str = "OPERATIONAL"
    reviews: list[Review] = field(default_factory=list)
    first_name: str = ""
    email: str = ""

    # Filled by the audit step.
    score: int = 0
    signals: list[str] = field(default_factory=list)
    complaint_quote: str = ""
    website_status: str = ""    # none | directory | weak | ok
    est_weekly_loss: int = 0

    # Filled later in the pipeline.
    site_url: str = ""
    line_type: str = ""         # Twilio line type, "" if unverified
    hold_reason: str = ""       # why this lead won't be auto-called (empty = callable)
    ghl_contact_id: str = ""

    @property
    def slug(self) -> str:
        digest = hashlib.sha1(self.source_id.encode()).hexdigest()[:6]
        return f"{slugify(self.name)}-{digest}"

    @property
    def audit_finding(self) -> str:
        """One-line, human-readable reason we're reaching out."""
        if self.complaint_quote:
            return f'A recent Google review says: "{self.complaint_quote}"'
        if self.signals:
            return self.signals[0]
        return ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["slug"] = self.slug
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Lead":
        d = dict(d)
        d.pop("slug", None)
        d["reviews"] = [Review(**r) for r in d.get("reviews", [])]
        return cls(**d)
