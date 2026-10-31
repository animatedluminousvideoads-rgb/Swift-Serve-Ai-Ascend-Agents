"""Find local businesses with the Google Places API (New) Text Search."""

from __future__ import annotations

import logging

import requests

from ..compliance import normalize_phone
from ..config import Market, Niche
from ..models import Lead, Review

log = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.addressComponents",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.reviews",
        "places.businessStatus",
        "places.googleMapsUri",
        "nextPageToken",
    ]
)


def search_places(
    api_key: str,
    text_query: str,
    pages: int = 1,
    session: requests.Session | None = None,
) -> list[dict]:
    http = session or requests.Session()
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}
    body: dict = {"textQuery": text_query, "pageSize": 20, "regionCode": "US"}
    places: list[dict] = []
    for _ in range(max(1, pages)):
        resp = http.post(SEARCH_URL, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        places.extend(data.get("places", []))
        token = data.get("nextPageToken")
        if not token:
            break
        body = {**body, "pageToken": token}
    return places


def _component(place: dict, kind: str, short: bool = False) -> str:
    for comp in place.get("addressComponents", []):
        if kind in comp.get("types", []):
            return comp.get("shortText" if short else "longText", "")
    return ""


def place_to_lead(place: dict, niche: Niche, market: Market) -> Lead:
    raw_phone = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or ""
    reviews = []
    for r in place.get("reviews", []) or []:
        text = (r.get("text") or r.get("originalText") or {}).get("text", "")
        if text:
            reviews.append(Review(rating=float(r.get("rating") or 0), text=text))
    return Lead(
        source_id=place["id"],
        name=(place.get("displayName") or {}).get("text", "").strip(),
        niche_key=niche.key,
        niche_label=niche.label,
        market=market.city,
        timezone=market.timezone,
        phone=normalize_phone(raw_phone) or "",
        phone_display=place.get("nationalPhoneNumber", ""),
        address=place.get("formattedAddress", ""),
        city=_component(place, "locality") or market.city.split(",")[0],
        state=_component(place, "administrative_area_level_1", short=True),
        postal_code=_component(place, "postal_code"),
        website=place.get("websiteUri", ""),
        rating=place.get("rating"),
        review_count=int(place.get("userRatingCount") or 0),
        maps_url=place.get("googleMapsUri", ""),
        business_status=place.get("businessStatus", "OPERATIONAL"),
        reviews=reviews,
    )


def find_leads(
    api_key: str,
    niche: Niche,
    market: Market,
    pages: int = 1,
    session: requests.Session | None = None,
) -> list[Lead]:
    query = f"{niche.query} in {market.city}"
    places = search_places(api_key, query, pages=pages, session=session)
    log.info("places search %r returned %d results", query, len(places))
    return [place_to_lead(p, niche, market) for p in places if p.get("id")]
