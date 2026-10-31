"""Import leads from a CSV (Apollo export, scraped list, manual list...).

Recognized columns (case-insensitive, extra columns ignored):
  name / company / business_name   (required)
  phone                            (required)
  niche          one of the niche keys in campaign.yaml (default: first niche)
  city, state, postal_code, address, website, email, first_name
  timezone       IANA name, e.g. America/Chicago (default: matching market, else first market)
  rating, review_count, review       (a review snippet used for personalization)
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from ..compliance import normalize_phone
from ..config import Campaign
from ..models import Lead, Review

NAME_KEYS = ("name", "company", "business_name", "company_name", "organization")


def _get(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v:
            return str(v).strip()
    return ""


def read_csv_leads(path: str | Path, campaign: Campaign) -> list[Lead]:
    leads: list[Lead] = []
    default_niche = next(iter(campaign.niches.values()))
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            row = {(k or "").strip().lower(): v for k, v in raw.items()}
            name = _get(row, *NAME_KEYS)
            phone = normalize_phone(_get(row, "phone", "phone_number", "company_phone"))
            if not name or not phone:
                continue
            niche = campaign.niches.get(_get(row, "niche").lower(), default_niche)
            city = _get(row, "city")
            state = _get(row, "state")
            market = next(
                (m for m in campaign.markets if city and m.city.lower().startswith(city.lower())),
                campaign.markets[0],
            )
            rating = _get(row, "rating")
            review = _get(row, "review", "review_snippet")
            leads.append(
                Lead(
                    source_id="csv:" + hashlib.sha1(f"{name}|{phone}".encode()).hexdigest(),
                    name=name,
                    niche_key=niche.key,
                    niche_label=niche.label,
                    market=f"{city}, {state}".strip(", ") or market.city,
                    timezone=_get(row, "timezone") or market.timezone,
                    phone=phone,
                    phone_display=_get(row, "phone", "phone_number", "company_phone"),
                    address=_get(row, "address"),
                    city=city,
                    state=state,
                    postal_code=_get(row, "postal_code", "zip"),
                    website=_get(row, "website", "website_url"),
                    rating=float(rating) if rating else None,
                    review_count=int(float(_get(row, "review_count") or 0)),
                    reviews=[Review(rating=float(rating or 0), text=review)] if review else [],
                    first_name=_get(row, "first_name"),
                    email=_get(row, "email"),
                )
            )
    return leads
