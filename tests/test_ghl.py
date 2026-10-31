import pytest

from ascend_agents.ghl.client import GHLClient, GHLError
from ascend_agents.ghl.setup import resolve, setup


class Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.content = b"x"
        self.text = str(payload)

    def json(self):
        return self._payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.sent = []

    def request(self, method, url, **kw):
        self.sent.append((method, url, kw))
        return self.responses.pop(0)


def client(responses):
    s = Session(responses)
    return GHLClient("tok", "loc1", session=s, sleep=lambda _: None), s


def test_auth_and_version_headers():
    c, s = client([Resp(200, {"workflows": []}), Resp(200, {"agents": []})])
    c.list_workflows()
    c.list_voice_agents()
    assert s.headers["Authorization"] == "Bearer tok"
    assert s.sent[0][2]["headers"] == {"Version": "2021-07-28"}
    assert s.sent[0][2]["params"] == {"locationId": "loc1"}
    assert s.sent[1][2]["headers"] == {"Version": "2021-04-15"}


def test_retries_rate_limits_then_succeeds():
    c, s = client([Resp(429, headers={"Retry-After": "1"}), Resp(502), Resp(200, {"contact": {"id": "c1"}})])
    assert c.get_contact("c1") == {"id": "c1"}
    assert len(s.sent) == 3


def test_client_errors_raise_without_retry():
    c, s = client([Resp(401, {"message": "bad token"})])
    with pytest.raises(GHLError) as err:
        c.get_contact("c1")
    assert err.value.status == 401
    assert len(s.sent) == 1


def test_upsert_never_sends_tags():
    c, s = client([Resp(200, {"new": True, "contact": {"id": "c9"}})])
    contact, is_new = c.upsert_contact({"phone": "+16025550143", "tags": ["x"]})
    body = s.sent[0][2]["json"]
    assert "tags" not in body
    assert body["locationId"] == "loc1"
    assert (contact["id"], is_new) == ("c9", True)


def test_resolve_finds_everything(fake_ghl, campaign):
    ctx = resolve(fake_ghl, campaign)
    assert ctx.problems == []
    assert ctx.pipeline_id == "pl-1"
    assert ctx.stage_ids["ready"] == "st-ready"
    assert ctx.workflow_id == "wf-1"
    assert ctx.agent_id == "ag-1"
    assert ctx.can_push and ctx.can_dial
    assert ctx.custom_fields({"site_url": "https://x", "score": ""}) == [{"id": "f-site_url", "field_value": "https://x"}]


def test_resolve_reports_missing_pieces(fake_ghl, campaign):
    fake_ghl.workflows = [{"id": "wf-1", "name": "Ascend AI Cold Call", "status": "draft"}]
    fake_ghl.fields = fake_ghl.fields[1:]
    ctx = resolve(fake_ghl, campaign, create_fields=False)
    assert not ctx.can_dial
    assert any("isn't published" in p for p in ctx.problems)
    assert any("Custom field" in p for p in ctx.problems)


def test_setup_creates_agent_when_missing(fake_ghl, campaign):
    created = {}
    fake_ghl.agents = []
    fake_ghl.create_voice_agent = lambda fields: created.update(fields) or {"id": "ag-new"}
    ctx, done = setup(fake_ghl, campaign)
    assert ctx.agent_id == "ag-new"
    assert created["agentName"] == "Ascend Cold Caller"
    assert "an AI assistant" in created["welcomeMessage"]
    assert "{{contact.site_url}}" in created["agentPrompt"]
    assert not any("Voice AI agent" in p for p in ctx.problems)
