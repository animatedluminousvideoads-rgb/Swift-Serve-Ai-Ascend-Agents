"""Score leads: who is most likely losing customers to slow responses or a weak web presence."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import requests

from .config import Campaign
from .models import Lead

log = logging.getLogger(__name__)

# Listing/social pages that businesses use instead of a real website.
DIRECTORY_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "yelp.com",
    "linktr.ee",
    "business.site",
    "sites.google.com",
    "nextdoor.com",
    "angi.com",
    "homeadvisor.com",
    "thumbtack.com",
    "yellowpages.com",
    "bbb.org",
    "mapquest.com",
    "linkedin.com",
    "tiktok.com",
)
# Free-builder subdomains: a site exists, but usually a thin one.
FREE_BUILDER_SUFFIXES = (".wixsite.com", ".weebly.com", ".godaddysites.com", ".square.site", ".carrd.co")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def classify_website(url: str) -> str:
    """Return none | directory | weak | ok based on the URL alone."""
    if not url:
        return "none"
    host = (urlparse(url if "://" in url else f"http://{url}").hostname or "").lower()
    if any(host == d or host.endswith("." + d) for d in DIRECTORY_DOMAINS):
        return "directory"
    if host.endswith(FREE_BUILDER_SUFFIXES):
        return "weak"
    return "ok"


def check_website(url: str, session: requests.Session | None = None) -> list[str]:
    """Light live check of a business website. Returns a list of issues found."""
    http = session or requests.Session()
    try:
        resp = http.get(
            url,
            timeout=8,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AscendSiteAudit/1.0)"},
        )
    except requests.RequestException:
        return ["Website didn't load when we checked"]
    issues = []
    if resp.status_code >= 400:
        issues.append(f"Website returned an error (HTTP {resp.status_code})")
        return issues
    if not resp.url.startswith("https://"):
        issues.append("Website isn't secure (no https)")
    if 'name="viewport"' not in resp.text and "name='viewport'" not in resp.text:
        issues.append("Website isn't mobile-friendly (no responsive viewport)")
    return issues


def find_complaint(lead: Lead, phrases: list[str]) -> tuple[str, int]:
    """Return (best quote, number of complaining reviews)."""
    phrases = [p.lower() for p in phrases]
    quote, hits = "", 0
    for review in lead.reviews:
        text = " ".join(review.text.split())
        lowered = text.lower()
        matched = next((p for p in phrases if p in lowered), None)
        if not matched:
            continue
        hits += 1
        if quote:
            continue
        sentence = next(
            (s for s in _SENTENCE_SPLIT.split(text) if matched in s.lower()), text
        ).strip()
        if len(sentence) > 160:
            idx = sentence.lower().index(matched)
            start = max(0, idx - 60)
            sentence = ("…" if start else "") + sentence[start : start + 150].strip() + "…"
        quote = sentence
    return quote, hits


def score_lead(lead: Lead, campaign: Campaign, session: requests.Session | None = None) -> Lead:
    t = campaign.targeting
    niche = campaign.niches[lead.niche_key]
    score, signals = 0, []

    status = classify_website(lead.website)
    if status == "ok" and t.get("audit_websites") and lead.website:
        issues = check_website(lead.website, session=session)
        if issues:
            status = "weak"
            signals.extend(issues[:2])
            score += min(2, len(issues))
    lead.website_status = status
    if status == "none":
        score += 3
        signals.insert(0, "No website on their Google listing")
    elif status == "directory":
        score += 2
        signals.insert(0, "Only a social/directory page instead of a real website")
    elif status == "weak" and not signals:
        score += 1
        signals.append("Thin free-builder website")

    low, high = t.get("rating_sweet_spot", [3.5, 4.5])
    if lead.rating is not None and low <= lead.rating <= high:
        score += 2
        signals.append(f"{lead.rating}★ on Google ({lead.review_count} reviews): room to grow")

    quote, hits = find_complaint(lead, t.get("complaint_phrases", []))
    if hits:
        score += 3 + min(2, hits - 1)
        lead.complaint_quote = quote
        signals.insert(0, f"{hits} recent review(s) mention slow or missed responses")

    lead.score = score
    lead.signals = signals
    lead.est_weekly_loss = niche.avg_ticket * int(t.get("missed_leads_per_week", 1))
    return lead


def qualifies(lead: Lead, campaign: Campaign) -> tuple[bool, str]:
    if lead.business_status != "OPERATIONAL":
        return False, "not operational"
    if not lead.phone:
        return False, "no US phone number"
    if lead.score < int(campaign.targeting.get("min_score", 0)):
        return False, f"score {lead.score} below minimum"
    return True, ""
