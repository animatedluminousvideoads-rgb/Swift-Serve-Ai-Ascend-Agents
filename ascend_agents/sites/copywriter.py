"""Website copy for a prospect's demo site: written by Claude, with a template fallback."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import Campaign
from ..llm import Claude, LLMUnavailable
from ..models import Lead

log = logging.getLogger(__name__)

COPY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "subheadline": {"type": "string"},
        "services": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "description": {"type": "string"}},
                "required": ["title", "description"],
                "additionalProperties": False,
            },
        },
        "why_us": {"type": "array", "items": {"type": "string"}},
        "about": {"type": "string"},
        "cta_label": {"type": "string"},
        "assistant_greeting": {"type": "string"},
        "sample_customer_question": {"type": "string"},
        "sample_assistant_reply": {"type": "string"},
        "meta_description": {"type": "string"},
    },
    "required": [
        "headline",
        "subheadline",
        "services",
        "why_us",
        "about",
        "cta_label",
        "assistant_greeting",
        "sample_customer_question",
        "sample_assistant_reply",
        "meta_description",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You write website copy for small local service businesses. The copy goes on a \
free concept website that an agency builds to show the owner what a modern site for them could \
look like. The page is clearly labeled as a concept, so the owner will read it as a proposal.

Write warm, plain-spoken, conversion-focused copy a local customer would trust. Keep it specific \
to the trade and the city. Short sentences; no buzzwords or hype.

Accuracy matters more than polish, because the owner will judge the concept on whether it is \
true to their business. Only state facts given to you. Do not invent years in business, \
licenses, certifications, awards, guarantees, prices, staff names, testimonials or review quotes. \
Services should be the standard services of the trade, phrased so they read as typical offerings \
rather than claims about this specific shop.

Field guidance:
- headline: under 10 words.
- subheadline: one or two sentences.
- services: 4 to 6 items, each description one sentence.
- why_us: 3 short benefit statements that are true of any well-run shop in the trade, e.g. clear \
communication and fast replies.
- about: 2 or 3 sentences, written about the business in third person, using only the facts given.
- cta_label: a short call-to-action button label.
- assistant_greeting, sample_customer_question, sample_assistant_reply: a short demo exchange \
showing a 24/7 AI assistant on the site answering an after-hours customer and offering to book \
them in. The assistant should not quote prices.
- meta_description: under 155 characters."""

FALLBACK_SERVICES: dict[str, list[tuple[str, str]]] = {
    "hvac": [
        ("AC Repair", "Fast diagnosis and repair when your cooling stops keeping up."),
        ("Heating Repair", "Furnace and heat pump repairs to get your home warm again."),
        ("System Installation", "Right-sized, efficient systems installed cleanly."),
        ("Maintenance Plans", "Seasonal tune-ups that prevent surprise breakdowns."),
    ],
    "plumbing": [
        ("Leak Repair", "Find and fix leaks before they turn into water damage."),
        ("Drain Cleaning", "Clear slow and clogged drains the right way."),
        ("Water Heaters", "Repair and replacement for tank and tankless heaters."),
        ("Emergency Plumbing", "Help when something can't wait until Monday."),
    ],
    "electrical": [
        ("Electrical Repairs", "Troubleshooting for outlets, switches and breakers."),
        ("Panel Upgrades", "Modern panels for today's power needs."),
        ("Lighting", "Indoor and outdoor lighting installed safely."),
        ("EV Chargers", "Home charger installation done to code."),
    ],
    "roofing": [
        ("Roof Repair", "Stop leaks and fix storm damage fast."),
        ("Roof Replacement", "Full replacements with clear timelines."),
        ("Inspections", "Know the real condition of your roof."),
        ("Gutters", "Gutter repair and installation to protect your home."),
    ],
    "dental": [
        ("Cleanings & Exams", "Routine care that keeps your smile healthy."),
        ("Fillings & Crowns", "Restorative care to repair damaged teeth."),
        ("Cosmetic Dentistry", "Whitening and smile improvements."),
        ("Emergency Visits", "Prompt care for toothaches and broken teeth."),
    ],
    "law": [
        ("Free Case Review", "Talk through what happened and your options."),
        ("Car Accidents", "Help with claims after a crash."),
        ("Slip & Fall", "Guidance when you're hurt on someone else's property."),
        ("Insurance Negotiation", "Someone in your corner when dealing with insurers."),
    ],
    "med_spa": [
        ("Injectables", "Consultations for wrinkle relaxers and fillers."),
        ("Skin Treatments", "Facials and resurfacing for healthier skin."),
        ("Laser Services", "Laser hair removal and skin treatments."),
        ("Body Contouring", "Non-surgical options to help you feel your best."),
    ],
}


FALLBACK_HEADLINES = {
    "law": "Injury lawyers who pick up the phone in {city}",
    "dental": "Gentle, modern dental care in {city}",
    "med_spa": "Look and feel your best in {city}",
}


def fallback_copy(lead: Lead, campaign: Campaign) -> dict[str, Any]:
    trade = lead.niche_label
    city = lead.city or lead.market
    services = FALLBACK_SERVICES.get(
        lead.niche_key, [("Our Services", f"Professional {trade} services in {city}.")]
    )
    headline = FALLBACK_HEADLINES.get(lead.niche_key, "Trusted {trade} service in {city}")
    return {
        "headline": headline.format(trade=trade, city=city),
        "subheadline": f"{lead.name} serves {city} and nearby neighborhoods. Call or message any time to get started.",
        "services": [{"title": t, "description": d} for t, d in services],
        "why_us": [
            "Clear, upfront communication",
            "Fast replies, day or night",
            "Easy online booking",
        ],
        "about": f"{lead.name} is a local {trade} business serving {city}.",
        "cta_label": "Book a Visit",
        "assistant_greeting": f"Hi! You've reached {lead.name}. I can answer questions and get you booked, 24/7.",
        "sample_customer_question": "Hi, are you open? I need someone to take a look as soon as possible.",
        "sample_assistant_reply": "Thanks for reaching out! I can get you on the schedule. What's the best day and time for you?",
        "meta_description": f"{lead.name}: {trade} in {city}. Call or book online any time."[:155],
    }


def write_copy(lead: Lead, campaign: Campaign, claude: Claude | None) -> dict[str, Any]:
    if claude is None:
        return fallback_copy(lead, campaign)
    facts = {
        "business_name": lead.name,
        "trade": lead.niche_label,
        "city": lead.city or lead.market,
        "state": lead.state,
        "service_area": lead.market,
        "google_rating": lead.rating,
        "google_review_count": lead.review_count,
        "has_existing_website": lead.website_status in ("ok", "weak"),
    }
    prompt = (
        "Write the concept website copy for this business. Facts you may use:\n"
        + json.dumps(facts, indent=2)
    )
    try:
        copy = claude.structured(system=SYSTEM_PROMPT, prompt=prompt, schema=COPY_SCHEMA)
    except LLMUnavailable as exc:
        log.warning("copywriter fell back to template for %s: %s", lead.slug, exc)
        return fallback_copy(lead, campaign)
    if not copy.get("services"):
        copy["services"] = fallback_copy(lead, campaign)["services"]
    copy["services"] = copy["services"][:6]
    copy["why_us"] = copy["why_us"][:4]
    return copy
