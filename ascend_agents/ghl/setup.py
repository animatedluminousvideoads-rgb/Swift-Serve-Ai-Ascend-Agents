"""Resolve (and where the API allows, create) everything the pipeline needs in GHL.

Created automatically via the API:
  * contact custom fields (demo site URL, audit finding, ...)
  * the Voice AI cold-calling agent (prompt, greeting, settings)
  * an appointment-booking action on the agent, if a booking calendar is named

GHL's API can't create pipelines or workflows, so those are checked by name and
reported with exact instructions when missing (see docs/SETUP.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import Campaign
from .client import GHLClient, GHLError
from .voice_agent import agent_settings

log = logging.getLogger(__name__)

# our key -> (GHL field name, data type)
FIELD_SPECS: dict[str, tuple[str, str]] = {
    "site_url": ("Ascend Demo Site URL", "TEXT"),
    "audit": ("Ascend Audit Finding", "LARGE_TEXT"),
    "niche": ("Ascend Niche", "TEXT"),
    "score": ("Ascend Lead Score", "TEXT"),
    "loss": ("Ascend Weekly Revenue At Risk", "TEXT"),
    "rating": ("Ascend Google Rating", "TEXT"),
    "line_type": ("Ascend Line Type", "TEXT"),
    "outcome": ("Ascend Call Outcome", "TEXT"),
    "source_id": ("Ascend Source ID", "TEXT"),
}

BOOKING_ACTION_NAME = "Book discovery call"


@dataclass
class GHLContext:
    client: GHLClient
    field_ids: dict[str, str] = field(default_factory=dict)   # our key -> GHL field id
    field_keys: dict[str, str] = field(default_factory=dict)  # our key -> "contact.xxx"
    pipeline_id: str = ""
    stage_ids: dict[str, str] = field(default_factory=dict)   # our stage key -> GHL stage id
    workflow_id: str = ""
    agent_id: str = ""
    calendar_id: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def can_push(self) -> bool:
        return bool(self.field_ids)

    @property
    def can_dial(self) -> bool:
        return bool(self.workflow_id and self.pipeline_id and self.stage_ids.get("ready"))

    def custom_fields(self, values: dict[str, object]) -> list[dict[str, str]]:
        return [
            {"id": self.field_ids[k], "field_value": str(v)}
            for k, v in values.items()
            if k in self.field_ids and v not in (None, "")
        ]

    def stage_key_for(self, stage_id: str) -> str:
        return next((k for k, v in self.stage_ids.items() if v == stage_id), "")


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def ensure_fields(client: GHLClient, ctx: GHLContext, create: bool) -> None:
    existing = {_norm(f.get("name", "")): f for f in client.list_custom_fields("contact")}
    for key, (name, dtype) in FIELD_SPECS.items():
        found = existing.get(_norm(name))
        if not found and create:
            found = client.create_custom_field(name, dtype, "contact")
            log.info("created GHL custom field %r", name)
        if found:
            ctx.field_ids[key] = found["id"]
            ctx.field_keys[key] = found.get("fieldKey") or ""
        else:
            ctx.problems.append(f"Custom field '{name}' is missing (run `ascend setup`).")


def resolve_pipeline(client: GHLClient, campaign: Campaign, ctx: GHLContext) -> None:
    want = campaign.ghl["pipeline_name"]
    pipeline = next((p for p in client.list_pipelines() if _norm(p.get("name", "")) == _norm(want)), None)
    if not pipeline:
        ctx.problems.append(
            f"Pipeline '{want}' not found. Create it in GHL (Opportunities > Pipelines) with stages: "
            + ", ".join(campaign.stages.values())
        )
        return
    ctx.pipeline_id = pipeline["id"]
    by_name = {_norm(s.get("name", "")): s.get("id") for s in pipeline.get("stages", []) if isinstance(s, dict)}
    for key, name in campaign.stages.items():
        if _norm(name) in by_name:
            ctx.stage_ids[key] = by_name[_norm(name)]
        else:
            ctx.problems.append(f"Pipeline '{want}' is missing stage '{name}'.")


def resolve_workflow(client: GHLClient, campaign: Campaign, ctx: GHLContext) -> None:
    want = campaign.ghl["call_workflow_name"]
    wf = next((w for w in client.list_workflows() if _norm(w.get("name", "")) == _norm(want)), None)
    if not wf:
        ctx.problems.append(
            f"Workflow '{want}' not found. Create it in GHL (Automation > Workflows) with a single "
            f"Voice AI outbound call action using agent '{campaign.ghl['voice_agent_name']}', then publish it."
        )
        return
    if str(wf.get("status", "")).lower() != "published":
        ctx.problems.append(f"Workflow '{want}' exists but isn't published yet.")
        return
    ctx.workflow_id = wf["id"]


def find_agent(client: GHLClient, campaign: Campaign) -> dict | None:
    want = _norm(campaign.ghl["voice_agent_name"][:40])
    for agent in client.list_voice_agents(query=campaign.ghl["voice_agent_name"]):
        if _norm(agent.get("agentName", "")) == want:
            return agent
    return None


def resolve(client: GHLClient, campaign: Campaign, create_fields: bool = True) -> GHLContext:
    """Look up IDs by name. Called at the start of every pipeline run."""
    ctx = GHLContext(client=client)
    steps = [
        ("custom fields", lambda: ensure_fields(client, ctx, create_fields)),
        ("pipeline", lambda: resolve_pipeline(client, campaign, ctx)),
        ("workflow", lambda: resolve_workflow(client, campaign, ctx)),
    ]
    for label, step in steps:
        try:
            step()
        except GHLError as exc:
            ctx.problems.append(f"Couldn't read {label} from GHL: {exc}")
    try:
        agent = find_agent(client, campaign)
        if agent:
            ctx.agent_id = agent["id"]
        else:
            ctx.problems.append(f"Voice AI agent '{campaign.ghl['voice_agent_name']}' not found (run `ascend setup`).")
    except GHLError as exc:
        ctx.problems.append(f"Couldn't read Voice AI agents from GHL: {exc}")
    return ctx


def setup(client: GHLClient, campaign: Campaign) -> tuple[GHLContext, list[str]]:
    """Create/update the Voice AI agent and custom fields, then report what's left to do."""
    done: list[str] = []
    ctx = resolve(client, campaign, create_fields=True)
    if ctx.field_ids:
        done.append(f"Custom fields ready ({len(ctx.field_ids)}/{len(FIELD_SPECS)}).")

    settings = agent_settings(campaign, ctx.field_keys)
    try:
        agent = find_agent(client, campaign)
        if agent:
            client.patch_voice_agent(agent["id"], settings)
            ctx.agent_id = agent["id"]
            done.append(f"Updated Voice AI agent '{settings['agentName']}' with the latest script.")
        else:
            created = client.create_voice_agent(settings)
            ctx.agent_id = created.get("id", "")
            done.append(f"Created Voice AI agent '{settings['agentName']}'.")
        ctx.problems = [p for p in ctx.problems if "Voice AI agent" not in p]
    except GHLError as exc:
        ctx.problems.append(f"Couldn't create/update the Voice AI agent: {exc}")

    cal_name = campaign.ghl.get("booking_calendar_name") or ""
    if ctx.agent_id and cal_name:
        try:
            cal = next((c for c in client.list_calendars() if _norm(c.get("name", "")) == _norm(cal_name)), None)
            if not cal:
                ctx.problems.append(f"Booking calendar '{cal_name}' not found.")
            else:
                ctx.calendar_id = cal["id"]
                actions = client.get_voice_agent(ctx.agent_id).get("actions") or []
                if not any(a.get("name") == BOOKING_ACTION_NAME for a in actions):
                    client.create_voice_action(
                        ctx.agent_id,
                        "APPOINTMENT_BOOKING",
                        BOOKING_ACTION_NAME,
                        {"calendarId": cal["id"], "daysOfOfferingDates": 3, "slotsPerDay": 3, "hoursBetweenSlots": 2},
                    )
                    done.append(f"Added '{BOOKING_ACTION_NAME}' action using calendar '{cal_name}'.")
        except GHLError as exc:
            ctx.problems.append(f"Couldn't attach the booking action: {exc}")
    return ctx, done
