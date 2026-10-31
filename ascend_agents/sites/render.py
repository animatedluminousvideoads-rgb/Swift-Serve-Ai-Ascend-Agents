"""Render and write demo websites to the sites/ directory (served by GitHub Pages)."""

from __future__ import annotations

from html import escape
from pathlib import Path
from string import Template
from typing import Any

from ..config import REPO_ROOT, Campaign
from ..models import Lead

TEMPLATE = Template((Path(__file__).parent / "template.html").read_text(encoding="utf-8"))

ACCENTS = {
    "hvac": "#0b6bcb",
    "plumbing": "#0a7c86",
    "electrical": "#c26a00",
    "roofing": "#a23b2a",
    "dental": "#1a7f5a",
    "law": "#2b3a67",
    "med_spa": "#9b4d83",
}

ROOT_INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Concept Previews</title>
<style>body{margin:0;font:16px/1.6 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;background:#f4f6f9;color:#14181f;padding:16px}
main{max-width:520px;text-align:center}</style></head>
<body><main><h1>Concept previews</h1>
<p>Each preview here was built for one specific business and is shared directly with its owner.</p>
</main></body></html>
"""


def _cap(text: str) -> str:
    """Capitalize the first letter only, so acronyms like HVAC survive."""
    return text[:1].upper() + text[1:]


def _call_button(lead: Lead, css: str, label: str) -> str:
    if not lead.phone:
        return ""
    shown = escape(lead.phone_display or lead.phone)
    return (
        f'<a class="btn {css}" href="tel:{escape(lead.phone)}">'
        f'{escape(label)} <span class="num">{shown}</span></a>'
    )


def render_site(lead: Lead, copy: dict[str, Any], campaign: Campaign) -> str:
    e = escape
    agency = campaign.agency["name"]
    city = lead.city or lead.market
    service_area = lead.market if lead.market else city

    services = "\n        ".join(
        f'<div class="card"><h3>{e(s["title"])}</h3><p>{e(s["description"])}</p></div>'
        for s in copy["services"]
    )
    why_us = "\n        ".join(f"<li>{e(item)}</li>" for item in copy["why_us"])

    rating_badge = ""
    if lead.rating:
        full = int(round(lead.rating))
        stars = "★" * full + "☆" * (5 - full)
        href = e(lead.maps_url) if lead.maps_url else "#"
        rating_badge = (
            f'<a class="rating" href="{href}" target="_blank" rel="noopener">'
            f'<span class="stars" aria-hidden="true">{stars}</span>'
            f"{lead.rating:.1f} on Google · {lead.review_count} reviews</a>"
        )

    booking = campaign.agency.get("booking_url") or ""
    claim_link = (
        f' · <a href="{e(booking)}" target="_blank" rel="noopener">Claim this site</a>' if booking else ""
    )

    return TEMPLATE.substitute(
        title=e(f"{lead.name} | {_cap(lead.niche_label)} in {city}"),
        meta_description=e(copy["meta_description"][:155]),
        accent=ACCENTS.get(lead.niche_key, "#0b6bcb"),
        name=e(lead.name),
        agency=e(agency),
        header_call=_call_button(lead, "btn-primary", "Call"),
        hero_call=_call_button(lead, "btn-primary", copy["cta_label"] + " ·"),
        band_call=_call_button(lead, "btn-primary", "Call"),
        headline=e(copy["headline"]),
        subheadline=e(copy["subheadline"]),
        rating_badge=rating_badge,
        services_lead=e(f"{_cap(lead.niche_label)} services for homes and businesses in {city}."),
        services=services,
        why_us=why_us,
        about=e(copy["about"]),
        assistant_greeting=e(copy["assistant_greeting"]),
        sample_question=e(copy["sample_customer_question"]),
        sample_reply=e(copy["sample_assistant_reply"]),
        service_area=e(service_area),
        claim_link=claim_link,
    )


def sites_dir(campaign: Campaign) -> Path:
    return REPO_ROOT / campaign.sites["output_dir"]


def site_exists(lead: Lead, campaign: Campaign) -> bool:
    """The committed sites/ folder doubles as the ledger of leads already processed."""
    return (sites_dir(campaign) / lead.slug / "index.html").exists()


def ensure_root_files(campaign: Campaign) -> None:
    root = sites_dir(campaign)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".nojekyll").touch()
    (root / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    index = root / "index.html"
    if not index.exists():
        index.write_text(ROOT_INDEX)


def write_site(lead: Lead, html: str, campaign: Campaign) -> str:
    ensure_root_files(campaign)
    target = sites_dir(campaign) / lead.slug
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text(html, encoding="utf-8")
    return f"{campaign.sites['base_url']}/{lead.slug}/"
