from ascend_agents.audit import classify_website, find_complaint, qualifies, score_lead
from ascend_agents.models import Review
from ascend_agents.sources.csv_source import read_csv_leads
from ascend_agents.sources.google_places import place_to_lead

from .conftest import make_lead


def test_classify_website():
    assert classify_website("") == "none"
    assert classify_website("https://www.facebook.com/coolairpros") == "directory"
    assert classify_website("coolair.wixsite.com/home") == "weak"
    assert classify_website("https://coolairpros.com") == "ok"


def test_find_complaint_extracts_the_matching_sentence():
    lead = make_lead(
        reviews=[
            Review(5, "Amazing service!"),
            Review(2, "Prices were fine. I left a voicemail and never got a call back. Disappointed."),
            Review(1, "Called three times, no answer."),
        ]
    )
    quote, hits = find_complaint(lead, ["left a voicemail", "no answer"])
    assert hits == 2
    assert quote == "I left a voicemail and never got a call back."


def test_score_lead_rewards_complaints_missing_site_and_rating(campaign):
    lead = score_lead(make_lead(website=""), campaign)
    assert lead.website_status == "none"
    assert lead.score >= 8  # complaint 3 + no site 3 + rating sweet spot 2
    assert lead.complaint_quote
    assert lead.est_weekly_loss == campaign.niches["hvac"].avg_ticket
    assert lead.audit_finding.startswith("A recent Google review says")
    assert qualifies(lead, campaign) == (True, "")


def test_low_score_and_closed_businesses_do_not_qualify(campaign):
    strong = make_lead(website="https://coolairpros.com", rating=4.9, reviews=[])
    assert qualifies(score_lead(strong, campaign), campaign)[0] is False
    closed = score_lead(make_lead(business_status="CLOSED_PERMANENTLY"), campaign)
    assert qualifies(closed, campaign)[0] is False


def test_place_to_lead_maps_google_fields(campaign):
    place = {
        "id": "ChIJabc",
        "displayName": {"text": "Valley Plumbing Co"},
        "formattedAddress": "1 Main St, Phoenix, AZ 85004, USA",
        "addressComponents": [
            {"longText": "Phoenix", "shortText": "Phoenix", "types": ["locality", "political"]},
            {"longText": "Arizona", "shortText": "AZ", "types": ["administrative_area_level_1"]},
            {"longText": "85004", "shortText": "85004", "types": ["postal_code"]},
        ],
        "nationalPhoneNumber": "(602) 555-0199",
        "internationalPhoneNumber": "+1 602-555-0199",
        "rating": 3.9,
        "userRatingCount": 51,
        "reviews": [{"rating": 2, "text": {"text": "Nobody answered the phone."}}],
        "businessStatus": "OPERATIONAL",
        "googleMapsUri": "https://maps.google.com/?cid=1",
    }
    lead = place_to_lead(place, campaign.niches["plumbing"], campaign.markets[6])
    assert lead.name == "Valley Plumbing Co"
    assert lead.phone == "+16025550199"
    assert (lead.city, lead.state, lead.postal_code) == ("Phoenix", "AZ", "85004")
    assert lead.website == ""
    assert lead.reviews[0].text == "Nobody answered the phone."
    assert lead.timezone == "America/Phoenix"


def test_csv_import(tmp_path, campaign):
    path = tmp_path / "leads.csv"
    path.write_text(
        "Company,Phone,City,State,Niche,Email,First_Name\n"
        "Bright Smile Dental,(305) 555-0100,Miami,FL,dental,dr@brightsmile.test,Ana\n"
        "No Phone LLC,,Miami,FL,dental,,\n"
    )
    leads = read_csv_leads(path, campaign)
    assert len(leads) == 1
    lead = leads[0]
    assert lead.phone == "+13055550100"
    assert lead.niche_key == "dental"
    assert lead.timezone == "America/New_York"
    assert lead.first_name == "Ana"
