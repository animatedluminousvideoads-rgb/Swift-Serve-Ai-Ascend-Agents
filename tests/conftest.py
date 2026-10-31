from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from ascend_agents.config import Settings, load_campaign
from ascend_agents.ghl.client import GHLError
from ascend_agents.ghl.setup import FIELD_SPECS
from ascend_agents.models import Lead, Review

# A Tuesday, 11:00 in Phoenix (UTC-7, no DST) and 14:00 in New York.
IN_HOURS = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
# A Sunday.
WEEKEND = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def campaign(tmp_path):
    c = load_campaign()
    targeting = {**c.targeting, "audit_websites": False}
    sites = {**c.sites, "output_dir": str(tmp_path / "sites"), "base_url": "https://example.test/sites"}
    return dataclasses.replace(c, targeting=targeting, sites=sites)


@pytest.fixture
def settings():
    return Settings(ghl_token="t", ghl_location_id="loc1", google_places_key="")


def make_lead(**overrides) -> Lead:
    base = dict(
        source_id="place-123",
        name="Cool Air Pros",
        niche_key="hvac",
        niche_label="HVAC",
        market="Phoenix, AZ",
        timezone="America/Phoenix",
        phone="+16025550143",
        phone_display="(602) 555-0143",
        city="Phoenix",
        state="AZ",
        rating=4.0,
        review_count=40,
        reviews=[Review(rating=1, text="Good techs. But I called twice and nobody answered, so I went elsewhere.")],
    )
    base.update(overrides)
    return Lead(**base)


class FakeGHL:
    """In-memory stand-in for GHLClient that records every write."""

    STAGES = {
        "Site Built": "st-ready",
        "Needs Review": "st-review",
        "AI Call Queued": "st-queued",
        "Called - No Decision": "st-called",
        "Interested": "st-interested",
        "Booked Call": "st-booked",
        "Not Interested": "st-not",
        "Do Not Call": "st-dnc",
    }

    def __init__(self):
        self.location_id = "loc1"
        self.calls: list[tuple] = []
        self.contacts: dict[str, dict] = {}
        self.opps: list[dict] = []
        self.notes: dict[str, list[dict]] = {}
        self.call_logs: list[dict] = []
        self.fields = [
            {"id": f"f-{k}", "name": name, "fieldKey": f"contact.{k}"} for k, (name, _) in FIELD_SPECS.items()
        ]
        self.workflows = [{"id": "wf-1", "name": "Ascend AI Cold Call", "status": "published"}]
        self.agents = [{"id": "ag-1", "agentName": "Ascend Cold Caller"}]
        self.fail_upsert = False

    # reads
    def list_custom_fields(self, model="contact"):
        return self.fields

    def create_custom_field(self, name, data_type="TEXT", model="contact"):
        f = {"id": f"new-{name}", "name": name, "fieldKey": "contact.x"}
        self.fields.append(f)
        self.calls.append(("create_custom_field", name))
        return f

    def list_pipelines(self):
        return [
            {
                "id": "pl-1",
                "name": "Ascend AI Outbound",
                "stages": [{"id": v, "name": k} for k, v in self.STAGES.items()],
            }
        ]

    def list_workflows(self):
        return self.workflows

    def list_voice_agents(self, query=""):
        return self.agents

    def get_contact(self, cid):
        return self.contacts[cid]

    def list_notes(self, cid):
        return self.notes.get(cid, [])

    def search_opportunities(self, **f):
        out = self.opps
        if "pipeline_stage_id" in f:
            out = [o for o in out if o["pipelineStageId"] == f["pipeline_stage_id"]]
        if "contact_id" in f:
            out = [o for o in out if o["contactId"] == f["contact_id"]]
        return out

    def list_call_logs(self, agent_id, page=1, page_size=50):
        return self.call_logs if page == 1 else []

    # writes
    def upsert_contact(self, fields):
        if self.fail_upsert:
            raise GHLError(500, "POST", "/contacts/upsert", "boom")
        cid = f"c{len(self.contacts) + 1}"
        contact = {"id": cid, "tags": [], **fields}
        self.contacts[cid] = contact
        self.calls.append(("upsert_contact", fields))
        return contact, True

    def update_contact(self, cid, fields):
        self.contacts[cid].update(fields)
        self.calls.append(("update_contact", cid, fields))
        return self.contacts[cid]

    def add_tags(self, cid, tags):
        self.contacts.setdefault(cid, {"id": cid, "tags": []}).setdefault("tags", []).extend(tags)
        self.calls.append(("add_tags", cid, tags))

    def add_note(self, cid, body):
        self.notes.setdefault(cid, []).append({"body": body})
        self.calls.append(("add_note", cid, body))

    def create_task(self, cid, title, body, due):
        self.calls.append(("create_task", cid, title))

    def create_opportunity(self, fields):
        opp = {"id": f"o{len(self.opps) + 1}", **fields}
        self.opps.append(opp)
        self.calls.append(("create_opportunity", fields))
        return opp

    def update_opportunity(self, oid, fields):
        opp = next(o for o in self.opps if o["id"] == oid)
        opp.update(fields)
        self.calls.append(("update_opportunity", oid, fields))
        return opp

    def add_to_workflow(self, cid, wf):
        self.calls.append(("add_to_workflow", cid, wf))

    def send_sms(self, cid, message):
        self.calls.append(("send_sms", cid, message))

    def send_email(self, cid, subject, html):
        self.calls.append(("send_email", cid, subject))

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def fake_ghl():
    return FakeGHL()
