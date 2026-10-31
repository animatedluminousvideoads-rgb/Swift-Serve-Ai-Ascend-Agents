import dataclasses
from datetime import timedelta

from ascend_agents.models import Review
from ascend_agents.outcomes import classify_call, heuristic_outcome
from ascend_agents.pipeline import Pipeline
from ascend_agents.report import render_report
from ascend_agents.sites.render import site_exists

from .conftest import IN_HOURS, WEEKEND, make_lead


def pipeline(campaign, settings, fake_ghl, now=IN_HOURS, **settings_overrides):
    s = dataclasses.replace(settings, **settings_overrides)
    return Pipeline(campaign, s, ghl=fake_ghl, claude=None, now=now)


def test_choose_searches_only_open_markets(campaign, settings, fake_ghl):
    p = pipeline(campaign, settings, fake_ghl)
    picks = p.choose_searches()
    assert len(picks) == campaign.limits["searches_per_run"]
    assert pipeline(campaign, settings, fake_ghl, now=WEEKEND).choose_searches() == []


def test_prospect_builds_site_and_loads_ghl(campaign, settings, fake_ghl):
    p = pipeline(campaign, settings, fake_ghl)
    lead = make_lead()
    built = p.prospect([lead])
    assert len(built) == 1
    assert site_exists(lead, campaign)
    upsert = fake_ghl.named("upsert_contact")[0][1]
    assert upsert["companyName"] == "Cool Air Pros"
    assert "tags" not in upsert
    assert {"id": "f-site_url", "field_value": f"https://example.test/sites/{lead.slug}/"} in upsert["customFields"]
    # No Twilio creds + default "hold" policy -> Needs Review, not auto-dialed.
    opp = fake_ghl.named("create_opportunity")[0][1]
    assert opp["pipelineStageId"] == "st-review"
    assert p.stats.held_for_review == 1
    # Second run: the committed site is the ledger, so nothing is reprocessed.
    p2 = pipeline(campaign, settings, fake_ghl)
    assert p2.prospect([make_lead()]) == []
    assert p2.stats.already_processed == 1


def test_prospect_ready_stage_when_line_verified(campaign, settings, fake_ghl, monkeypatch):
    monkeypatch.setattr("ascend_agents.pipeline.lookup_line_type", lambda *a, **k: "landline")
    p = pipeline(campaign, settings, fake_ghl, twilio_sid="AC1", twilio_token="t")
    p.prospect([make_lead()])
    assert fake_ghl.named("create_opportunity")[0][1]["pipelineStageId"] == "st-ready"


def test_failed_ghl_push_leaves_no_site_so_it_retries(campaign, settings, fake_ghl):
    fake_ghl.fail_upsert = True
    lead = make_lead()
    p = pipeline(campaign, settings, fake_ghl)
    assert p.prospect([lead]) == []
    assert not site_exists(lead, campaign)
    assert p.stats.errors


def test_unqualified_leads_skipped(campaign, settings, fake_ghl):
    lead = make_lead(website="https://great.example", rating=4.9, reviews=[Review(5, "Perfect!")])
    p = pipeline(campaign, settings, fake_ghl)
    assert p.prospect([lead]) == []
    assert p.stats.unqualified == 1


def _ready_contact(fake_ghl, cid="c1", **extra):
    fake_ghl.contacts[cid] = {
        "id": cid,
        "phone": "+16025550143",
        "timezone": "America/Phoenix",
        "tags": ["ascend-prospect"],
        "customFields": [{"id": "f-line_type", "value": "landline"}],
        **extra,
    }
    fake_ghl.opps.append({"id": f"o-{cid}", "contactId": cid, "pipelineStageId": "st-ready"})


def test_dial_enrolls_callable_leads(campaign, settings, fake_ghl):
    _ready_contact(fake_ghl)
    p = pipeline(campaign, settings, fake_ghl)
    assert p.dial() == 1
    assert fake_ghl.named("add_to_workflow") == [("add_to_workflow", "c1", "wf-1")]
    assert ("add_tags", "c1", ["ascend-attempt-1"]) in fake_ghl.calls
    assert fake_ghl.opps[0]["pipelineStageId"] == "st-queued"


def test_dial_respects_hours_dnd_and_mobile(campaign, settings, fake_ghl):
    _ready_contact(fake_ghl, "c1")
    assert pipeline(campaign, settings, fake_ghl, now=WEEKEND).dial() == 0
    assert fake_ghl.opps[0]["pipelineStageId"] == "st-ready"  # just waits for hours

    _ready_contact(fake_ghl, "c2", dnd=True)
    _ready_contact(fake_ghl, "c3", customFields=[{"id": "f-line_type", "value": "mobile"}])
    p = pipeline(campaign, settings, fake_ghl)
    p.campaign.limits["max_calls_per_run"] = 10
    assert p.dial() == 1  # only c1
    stages = {o["contactId"]: o["pipelineStageId"] for o in fake_ghl.opps}
    assert stages == {"c1": "st-queued", "c2": "st-dnc", "c3": "st-review"}


def test_dial_retries_stale_no_decision_up_to_max(campaign, settings, fake_ghl):
    old = (IN_HOURS - timedelta(days=3)).isoformat()
    _ready_contact(fake_ghl, "c1", tags=["ascend-prospect", "ascend-attempt-1"])
    fake_ghl.opps[0].update(pipelineStageId="st-called", lastStageChangeAt=old)
    _ready_contact(fake_ghl, "c2", tags=["ascend-attempt-2"])
    fake_ghl.opps[1].update(pipelineStageId="st-called", lastStageChangeAt=old)
    p = pipeline(campaign, settings, fake_ghl)
    assert p.dial() == 1
    assert p.stats.retries == 1
    assert ("add_tags", "c1", ["ascend-attempt-2"]) in fake_ghl.calls


def _call(fake_ghl, transcript, cid="c1", call_id="call-1", **extra):
    fake_ghl.call_logs.append(
        {"id": call_id, "contactId": cid, "createdAt": IN_HOURS.isoformat(), "duration": 95,
         "transcript": transcript, "summary": "summary", **extra}
    )


def test_sync_do_not_call_sets_dnd_and_stage(campaign, settings, fake_ghl):
    _ready_contact(fake_ghl, customFields=[{"id": "f-site_url", "value": "https://x/site/"}])
    fake_ghl.opps[0]["pipelineStageId"] = "st-queued"
    _call(fake_ghl, "bot: Hi, this is Ava, an AI assistant.\nhuman: Please don't call us again.")
    p = pipeline(campaign, settings, fake_ghl)
    assert p.sync_calls() == 1
    contact = fake_ghl.contacts["c1"]
    assert contact["dnd"] is True
    assert "ascend-dnc" in contact["tags"]
    assert fake_ghl.opps[0]["pipelineStageId"] == "st-dnc"
    assert fake_ghl.opps[0]["status"] == "lost"
    assert not fake_ghl.named("send_sms")
    # Idempotent: the note marker prevents reprocessing.
    assert pipeline(campaign, settings, fake_ghl).sync_calls() == 0


def test_sync_interested_with_consent_texts_link_and_creates_task(campaign, settings, fake_ghl, monkeypatch):
    from ascend_agents.outcomes import CallOutcome

    _ready_contact(fake_ghl, companyName="Cool Air Pros", customFields=[{"id": "f-site_url", "value": "https://x/site/"}])
    _call(fake_ghl, "human: sure, text it to me")
    monkeypatch.setattr(
        "ascend_agents.pipeline.classify_call",
        lambda entry, claude: CallOutcome("interested", sms_link_consent=True, decision_maker_name="Maria Lopez",
                                          summary="Owner wants to see the site."),
    )
    p = pipeline(campaign, settings, fake_ghl)
    p.sync_calls()
    sms = fake_ghl.named("send_sms")[0][2]
    assert sms.startswith("Hi Maria,")
    assert "https://x/site/" in sms and "Reply STOP" in sms
    assert fake_ghl.named("create_task")
    assert fake_ghl.opps[0]["pipelineStageId"] == "st-interested"


def test_sync_ignores_old_and_trial_calls(campaign, settings, fake_ghl):
    _ready_contact(fake_ghl)
    _call(fake_ghl, "human: hi", call_id="trial", trialCall=True)
    old = (IN_HOURS - timedelta(days=5)).isoformat()
    _call(fake_ghl, "human: hi", call_id="old", createdAt=old)
    assert pipeline(campaign, settings, fake_ghl).sync_calls() == 0


def test_heuristic_outcomes():
    assert heuristic_outcome({"transcript": "bot: please leave a message after the tone"}).outcome == "voicemail"
    assert heuristic_outcome({"transcript": ""}).outcome == "no_answer"
    assert heuristic_outcome({"transcript": "human: we're not interested"}).outcome == "not_interested"
    assert heuristic_outcome({"transcript": "human: take me off your list"}).outcome == "do_not_call"
    got = heuristic_outcome({"transcript": "human: sounds good, send me it at bob@coolair.test"})
    assert (got.outcome, got.email, got.sms_link_consent) == ("interested", "bob@coolair.test", False)


def test_booking_action_marks_booked_unless_dnc():
    entry = {"transcript": "human: sounds good", "executedCallActions": [{"actionType": "APPOINTMENT_BOOKING"}]}
    assert classify_call(entry, None).outcome == "booked"


def test_report_has_counts_but_no_pii(campaign, settings, fake_ghl):
    p = pipeline(campaign, settings, fake_ghl)
    p.prospect([make_lead()])
    text = render_report(p.stats, campaign, "prospect", IN_HOURS)
    assert "DEMO SITES BUILT: 1" in text
    assert "Cool Air Pros" not in text and "555" not in text
