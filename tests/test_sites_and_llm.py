from types import SimpleNamespace

import anthropic
import pytest

from ascend_agents.llm import Claude, LLMUnavailable
from ascend_agents.sites.copywriter import COPY_SCHEMA, fallback_copy, write_copy
from ascend_agents.sites.render import render_site, site_exists, write_site

from .conftest import make_lead


class FakeMessages:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.kwargs = response, exc, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def fake_claude(text='{"ok": true}', stop_reason="end_turn", exc=None):
    response = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
    messages = FakeMessages(response, exc)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return Claude(api_key="x", client=client), messages


def test_structured_sends_schema_effort_and_fallbacks():
    claude, messages = fake_claude()
    assert claude.structured(system="s", prompt="p", schema=COPY_SCHEMA, effort="low") == {"ok": True}
    kw = messages.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in kw["betas"]
    assert kw["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": COPY_SCHEMA}}


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_structured_raises_on_unusable_stop(stop_reason):
    claude, _ = fake_claude(stop_reason=stop_reason)
    with pytest.raises(LLMUnavailable):
        claude.structured(system="s", prompt="p", schema={})


def test_structured_wraps_connection_errors():
    exc = anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="https://x"))
    claude, _ = fake_claude(exc=exc)
    with pytest.raises(LLMUnavailable):
        claude.structured(system="s", prompt="p", schema={})


def test_copywriter_falls_back_when_claude_fails(campaign):
    claude, _ = fake_claude(stop_reason="refusal")
    lead = make_lead()
    assert write_copy(lead, campaign, claude) == fallback_copy(lead, campaign)


def test_copywriter_uses_claude_copy(campaign):
    copy = fallback_copy(make_lead(), campaign) | {"headline": "Cool homes, fast replies"}
    import json

    claude, messages = fake_claude(text=json.dumps(copy))
    assert write_copy(make_lead(), campaign, claude)["headline"] == "Cool homes, fast replies"
    assert "Cool Air Pros" in messages.kwargs["messages"][0]["content"]


def test_render_escapes_and_labels_the_concept(campaign):
    lead = make_lead(name='Bob\'s <script>alert("x")</script> Air', maps_url="https://maps.google.com/?cid=1")
    html = render_site(lead, fallback_copy(lead, campaign), campaign)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert "not the official website" in html
    assert 'href="tel:+16025550143"' in html
    assert "HVAC services" in html
    assert "4.0 on Google" in html


def test_write_site_creates_ledger_entry(campaign):
    lead = make_lead()
    assert not site_exists(lead, campaign)
    url = write_site(lead, "<html></html>", campaign)
    assert url == f"https://example.test/sites/{lead.slug}/"
    assert site_exists(lead, campaign)
