"""The autonomous acquisition loop.

  sync      Voice AI call logs -> outcome -> pipeline stage, notes, tasks, DND, link follow-ups
  prospect  Google Places / CSV -> audit + score -> demo website -> GHL contact + opportunity
  dial      "Site Built" (and due retries) -> compliance gates -> GHL call workflow

All state lives in GoHighLevel (pipeline stages, tags, notes) plus the committed
sites/ folder, which doubles as the ledger of businesses already processed.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import requests

from .audit import qualifies, score_lead
from .compliance import (
    DNC_TAG,
    contact_block_reason,
    in_calling_window,
    line_type_hold_reason,
    lookup_line_type,
    mask_phone,
)
from .config import REPO_ROOT, Campaign, Market, Niche, Settings
from .ghl.client import GHLClient, GHLError
from .ghl.setup import GHLContext, resolve
from .llm import Claude
from .models import Lead
from .outcomes import CallOutcome, classify_call
from .sites.copywriter import write_copy
from .sites.render import render_site, site_exists, write_site
from .sources.google_places import find_leads

log = logging.getLogger(__name__)

PREVIEW_DIR = REPO_ROOT / ".ascend" / "preview"
ATTEMPT_TAG = "ascend-attempt-"


@dataclass
class RunStats:
    searches: list[str] = field(default_factory=list)
    found: int = 0
    already_processed: int = 0
    unqualified: int = 0
    sites_built: int = 0
    pushed_to_ghl: int = 0
    held_for_review: int = 0
    enrolled: int = 0
    retries: int = 0
    calls_synced: int = 0
    outcomes: Counter = field(default_factory=Counter)
    links_texted: int = 0
    links_emailed: int = 0
    tasks_created: int = 0
    problems: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class Pipeline:
    def __init__(
        self,
        campaign: Campaign,
        settings: Settings,
        ghl: GHLClient | None = None,
        claude: Claude | None = None,
        http: requests.Session | None = None,
        now: datetime | None = None,
    ):
        self.campaign = campaign
        self.settings = settings
        if ghl is None and settings.has_ghl and not settings.dry_run:
            ghl = GHLClient(settings.ghl_token, settings.ghl_location_id)
        self.ghl = ghl
        if claude is None and settings.has_claude:
            claude = Claude(settings.anthropic_key, settings.claude_model)
        self.claude = claude
        self.http = http or requests.Session()
        self._now = now
        self._ctx: GHLContext | None = None
        self.stats = RunStats()

    # -- helpers -------------------------------------------------------------------

    def now(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    def context(self) -> GHLContext | None:
        if self.ghl is None:
            return None
        if self._ctx is None:
            self._ctx = resolve(self.ghl, self.campaign)
            self.stats.problems.extend(self._ctx.problems)
        return self._ctx

    def _error(self, msg: str) -> None:
        log.error(msg)
        self.stats.errors.append(msg)

    @staticmethod
    def _field_value(contact: dict, field_id: str) -> str:
        for f in contact.get("customFields") or []:
            if f.get("id") == field_id:
                return str(f.get("value") or f.get("field_value") or "")
        return ""

    # -- prospecting ---------------------------------------------------------------

    def choose_searches(self) -> list[tuple[Niche, Market]]:
        """Rotate through niche x market combos whose market is inside calling hours."""
        now = self.now()
        open_markets = [m for m in self.campaign.markets if in_calling_window(self.campaign.calling, m.timezone, now)]
        combos = [(n, m) for m in open_markets for n in self.campaign.niches.values()]
        if not combos:
            return []
        k = min(self.campaign.limits["searches_per_run"], len(combos))
        start = (int(now.timestamp() // 3600) * k) % len(combos)
        return [combos[(start + i) % len(combos)] for i in range(k)]

    def _check_line(self, lead: Lead) -> None:
        if lead.phone in self.settings.suppressed_numbers:
            lead.hold_reason = "number is on the suppression list"
            return
        if self.settings.has_twilio:
            lead.line_type = lookup_line_type(
                lead.phone, self.settings.twilio_sid, self.settings.twilio_token, session=self.http
            )
        lead.hold_reason = line_type_hold_reason(lead.line_type, self.campaign.calling)

    def prospect(self, leads: list[Lead] | None = None) -> list[Lead]:
        """Find, audit and build sites for new leads, and load them into GHL."""
        ctx = self.context()
        if self.ghl is not None and (ctx is None or not ctx.can_push):
            self.stats.problems.append("GHL isn't ready (see problems above); not prospecting this run.")
            return []

        candidates: list[Lead] = list(leads or [])
        if leads is None:
            if not self.settings.google_places_key:
                self.stats.problems.append("GOOGLE_PLACES_API_KEY is not set; nothing to search with.")
            searches = self.choose_searches()
            if not searches:
                log.info("no markets are inside calling hours right now; skipping search")
            for niche, market in searches if self.settings.google_places_key else []:
                self.stats.searches.append(f"{niche.label} in {market.city}")
                try:
                    candidates += find_leads(
                        self.settings.google_places_key,
                        niche,
                        market,
                        pages=self.campaign.limits.get("pages_per_search", 1),
                        session=self.http,
                    )
                except requests.RequestException as exc:
                    self._error(f"Places search failed for {niche.label} in {market.city}: {exc}")
        self.stats.found += len(candidates)

        preview_only = self.ghl is None
        built: list[Lead] = []
        seen: set[str] = set()
        for lead in candidates:
            if len(built) >= self.campaign.limits["max_new_leads_per_run"]:
                break
            if lead.source_id in seen or (not preview_only and site_exists(lead, self.campaign)):
                self.stats.already_processed += 1
                continue
            seen.add(lead.source_id)
            score_lead(lead, self.campaign, session=self.http)
            ok, why = qualifies(lead, self.campaign)
            if not ok:
                log.info("skip %s: %s", lead.slug, why)
                self.stats.unqualified += 1
                continue
            self._check_line(lead)

            html = render_site(lead, write_copy(lead, self.campaign, self.claude), self.campaign)
            lead.site_url = f"{self.campaign.sites['base_url']}/{lead.slug}/"
            if preview_only:
                out = PREVIEW_DIR / lead.slug
                out.mkdir(parents=True, exist_ok=True)
                (out / "index.html").write_text(html, encoding="utf-8")
                log.info("preview site written: %s", out / "index.html")
            else:
                try:
                    self.push_lead(lead)
                except GHLError as exc:
                    # No site file is written, so this lead is retried on a later run.
                    self._error(f"GHL push failed for {lead.slug}: {exc}")
                    continue
                write_site(lead, html, self.campaign)
            self.stats.sites_built += 1
            if lead.hold_reason:
                self.stats.held_for_review += 1
            built.append(lead)
        return built

    def lead_note(self, lead: Lead) -> str:
        lines = [
            f"Ascend prospect audit for {lead.name}",
            f"Niche: {lead.niche_label} · Market: {lead.market} · Lead score: {lead.score}",
            f"Demo site: {lead.site_url}",
        ]
        if lead.rating is not None:
            lines.append(f"Google: {lead.rating}★ ({lead.review_count} reviews) {lead.maps_url}")
        lines.append(f"Website: {lead.website or 'none'} ({lead.website_status})")
        if lead.complaint_quote:
            lines.append(f'Review quote: "{lead.complaint_quote}"')
        for s in lead.signals:
            lines.append(f"- {s}")
        lines.append(f"Estimated weekly revenue at risk: ~${lead.est_weekly_loss:,}")
        lines.append(f"Line type: {lead.line_type or 'unverified'}")
        if lead.hold_reason:
            lines.append(f"NOT auto-called: {lead.hold_reason}")
        return "\n".join(lines)

    def push_lead(self, lead: Lead) -> None:
        ctx = self.context()
        assert self.ghl is not None and ctx is not None
        fields: dict = {
            "companyName": lead.name,
            "phone": lead.phone,
            "website": lead.website or None,
            "address1": lead.address or None,
            "city": lead.city or None,
            "state": lead.state or None,
            "postalCode": lead.postal_code or None,
            "country": "US",
            "timezone": lead.timezone,
            "source": "Ascend AI Prospecting",
            "customFields": ctx.custom_fields(
                {
                    "site_url": lead.site_url,
                    "audit": lead.audit_finding,
                    "niche": lead.niche_label,
                    "score": lead.score,
                    "loss": f"${lead.est_weekly_loss:,}",
                    "rating": f"{lead.rating} ({lead.review_count} reviews)" if lead.rating else "",
                    "line_type": lead.line_type or "unverified",
                    "source_id": lead.source_id,
                }
            ),
        }
        if lead.first_name:
            fields["firstName"] = lead.first_name
        else:
            fields["name"] = lead.name
        if lead.email:
            fields["email"] = lead.email
        contact, is_new = self.ghl.upsert_contact({k: v for k, v in fields.items() if v is not None})
        cid = contact["id"]
        lead.ghl_contact_id = cid

        existing_tags = [t.lower() for t in contact.get("tags") or []]
        if not is_new and any(t.startswith("ascend-") for t in existing_tags):
            log.info("contact for %s already in the Ascend pipeline; not duplicating", lead.slug)
            return
        block = contact_block_reason(contact, self.settings.suppressed_numbers)
        if block:
            lead.hold_reason = block

        tags = ["ascend-prospect", f"ascend-niche-{lead.niche_key.replace('_', '-')}"]
        if lead.hold_reason:
            tags.append("ascend-needs-review")
        self.ghl.add_tags(cid, tags)
        self.ghl.add_note(cid, self.lead_note(lead))
        if ctx.pipeline_id:
            stage = "review" if lead.hold_reason else "ready"
            self.ghl.create_opportunity(
                {
                    "pipelineId": ctx.pipeline_id,
                    "pipelineStageId": ctx.stage_ids.get(stage) or ctx.stage_ids.get("ready"),
                    "name": f"{lead.name} · {lead.niche_label} · {lead.city or lead.market}",
                    "status": "open",
                    "contactId": cid,
                }
            )
        self.stats.pushed_to_ghl += 1
        log.info("pushed %s to GHL (contact %s, phone %s)", lead.slug, cid, mask_phone(lead.phone))

    # -- dialing -------------------------------------------------------------------

    def call_block(self, contact: dict, ctx: GHLContext) -> tuple[str, bool]:
        """(reason, permanent). Empty reason means the AI agent may call now."""
        reason = contact_block_reason(contact, self.settings.suppressed_numbers)
        if reason:
            return reason, True
        line_type = self._field_value(contact, ctx.field_ids.get("line_type", ""))
        if line_type == "unverified":
            line_type = ""
        reason = line_type_hold_reason(line_type, self.campaign.calling)
        if reason:
            return reason, True
        tz = contact.get("timezone") or self.campaign.markets[0].timezone
        if not in_calling_window(self.campaign.calling, tz, self.now()):
            return "outside calling hours", False
        return "", False

    @staticmethod
    def attempts(contact: dict) -> int:
        nums = [
            int(t[len(ATTEMPT_TAG):])
            for t in (contact.get("tags") or [])
            if t.lower().startswith(ATTEMPT_TAG) and t[len(ATTEMPT_TAG):].isdigit()
        ]
        return max(nums, default=0)

    def dial(self) -> int:
        ctx = self.context()
        if ctx is None:
            self.stats.problems.append("GHL credentials not set; not dialing.")
            return 0
        if not ctx.can_dial:
            self.stats.problems.append("Call workflow or pipeline missing in GHL; not dialing.")
            return 0
        assert self.ghl is not None
        budget = self.campaign.limits["max_calls_per_run"]
        max_attempts = self.campaign.limits["max_call_attempts"]
        retry_after = timedelta(days=self.campaign.limits["retry_after_days"])

        try:
            queue: list[tuple[dict, bool]] = [
                (o, False)
                for o in self.ghl.search_opportunities(
                    pipeline_id=ctx.pipeline_id, pipeline_stage_id=ctx.stage_ids["ready"], status="open"
                )
            ]
            if ctx.stage_ids.get("called"):
                for o in self.ghl.search_opportunities(
                    pipeline_id=ctx.pipeline_id, pipeline_stage_id=ctx.stage_ids["called"], status="open"
                ):
                    changed = _parse_ts(o.get("lastStageChangeAt") or o.get("updatedAt"))
                    if changed and self.now() - changed >= retry_after:
                        queue.append((o, True))
        except GHLError as exc:
            self._error(f"couldn't read the GHL pipeline: {exc}")
            return 0

        for opp, is_retry in queue:
            if self.stats.enrolled >= budget:
                break
            cid = opp.get("contactId") or (opp.get("contact") or {}).get("id")
            if not cid:
                continue
            try:
                contact = self.ghl.get_contact(cid)
                n = self.attempts(contact)
                if n >= max_attempts:
                    continue
                reason, permanent = self.call_block(contact, ctx)
                if reason:
                    if permanent:
                        blocked = any(w in reason for w in ("DND", "do-not-call", "suppression"))
                        stage_id = ctx.stage_ids.get("dnc" if blocked else "review")
                        if stage_id:
                            self.ghl.update_opportunity(opp["id"], {"pipelineStageId": stage_id})
                            self.ghl.add_tags(cid, [DNC_TAG if blocked else "ascend-needs-review"])
                            self.ghl.add_note(cid, f"Not auto-called: {reason}")
                    continue
                self.ghl.add_to_workflow(cid, ctx.workflow_id)
                self.ghl.add_tags(cid, [f"{ATTEMPT_TAG}{n + 1}"])
                if ctx.stage_ids.get("queued"):
                    self.ghl.update_opportunity(opp["id"], {"pipelineStageId": ctx.stage_ids["queued"]})
                self.stats.enrolled += 1
                self.stats.retries += int(is_retry)
                log.info("enrolled contact %s in the AI call workflow (attempt %d)", cid, n + 1)
            except GHLError as exc:
                self._error(f"dial failed for contact {cid}: {exc}")
        return self.stats.enrolled

    # -- call sync -----------------------------------------------------------------

    def recent_call_logs(self, agent_id: str, lookback: timedelta) -> list[dict]:
        assert self.ghl is not None
        cutoff = self.now() - lookback
        logs: list[dict] = []
        for page in range(1, 21):
            batch = self.ghl.list_call_logs(agent_id, page=page, page_size=50)
            for entry in batch:
                created = _parse_ts(entry.get("createdAt"))
                if created and created < cutoff:
                    return logs
                logs.append(entry)
            if len(batch) < 50:
                break
        return logs

    def sync_calls(self, lookback_hours: int = 30) -> int:
        ctx = self.context()
        if ctx is None or not ctx.agent_id:
            self.stats.problems.append("No Voice AI agent resolved in GHL; nothing to sync.")
            return 0
        assert self.ghl is not None
        try:
            entries = self.recent_call_logs(ctx.agent_id, timedelta(hours=lookback_hours))
        except GHLError as exc:
            self._error(f"couldn't read Voice AI call logs: {exc}")
            return 0
        for entry in entries:
            cid = entry.get("contactId")
            if not cid or entry.get("trialCall"):
                continue
            marker = f"[ascend-call:{entry.get('id')}]"
            try:
                if any(marker in (n.get("body") or "") for n in self.ghl.list_notes(cid)):
                    continue
                outcome = classify_call(entry, self.claude)
                self.apply_outcome(cid, entry, outcome, ctx, marker)
                self.stats.calls_synced += 1
                self.stats.outcomes[outcome.outcome] += 1
            except GHLError as exc:
                self._error(f"sync failed for call {entry.get('id')}: {exc}")
        return self.stats.calls_synced

    def apply_outcome(self, cid: str, entry: dict, outcome: CallOutcome, ctx: GHLContext, marker: str) -> None:
        assert self.ghl is not None
        contact = self.ghl.get_contact(cid)
        company = contact.get("companyName") or contact.get("name") or "the business"
        site_url = self._field_value(contact, ctx.field_ids.get("site_url", ""))
        dnc = outcome.outcome in ("do_not_call", "wrong_number")

        # The note is written first: it's the marker that stops this call being processed twice.
        details = [
            marker,
            f"AI call outcome: {outcome.outcome.replace('_', ' ')} ({int(entry.get('duration') or 0)}s)",
            f"Summary: {outcome.summary or entry.get('summary') or '(none)'}",
        ]
        if outcome.decision_maker_name:
            details.append(f"Decision maker: {outcome.decision_maker_name}")
        if outcome.callback_time:
            details.append(f"Asked for a call back: {outcome.callback_time}")
        if outcome.email:
            details.append(f"Email given on the call: {outcome.email}")
        self.ghl.add_note(cid, "\n".join(details))

        updates: dict = {"customFields": ctx.custom_fields({"outcome": outcome.outcome})}
        if dnc:
            updates["dnd"] = True
        if outcome.email and not contact.get("email"):
            updates["email"] = outcome.email
        self.ghl.update_contact(cid, updates)
        tags = [f"ascend-{outcome.outcome.replace('_', '-')}"] + ([DNC_TAG] if dnc else [])
        self.ghl.add_tags(cid, tags)

        stage_id = ctx.stage_ids.get(outcome.stage_key)
        if ctx.pipeline_id and stage_id:
            opps = self.ghl.search_opportunities(contact_id=cid, pipeline_id=ctx.pipeline_id)
            if opps:
                status = "lost" if outcome.stage_key in ("not_interested", "dnc") else "open"
                self.ghl.update_opportunity(opps[0]["id"], {"pipelineStageId": stage_id, "status": status})

        if dnc:
            return
        rep = self.campaign.agency["rep_name"]
        if outcome.outcome in ("booked", "interested") or outcome.callback_time:
            due = (self.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            body = f"{outcome.summary}\nDemo site: {site_url}".strip()
            self.ghl.create_task(cid, f"Follow up with {company} ({outcome.outcome})", body, due)
            self.stats.tasks_created += 1
        if site_url and outcome.sms_link_consent:
            first = (outcome.decision_maker_name or "").split(" ")[0]
            greeting = f"Hi {first}" if first else "Hi"
            self.ghl.send_sms(
                cid,
                f"{greeting}, thanks for chatting with {self.campaign.agency['ai_caller_name']} from "
                f"{self.campaign.agency['name']} today. Here's the free website preview we built for "
                f"{company}: {site_url} {rep} will follow up. Reply STOP to opt out.",
            )
            self.stats.links_texted += 1
        if site_url and outcome.email:
            self.ghl.send_email(cid, f"{company}: your free website preview", self.preview_email(company, site_url))
            self.stats.links_emailed += 1

    def preview_email(self, company: str, site_url: str) -> str:
        a = self.campaign.agency
        e = escape
        return (
            f"<p>Hi,</p>"
            f"<p>Thanks for taking our call today. As promised, here's the free website preview we built "
            f"for {e(company)}:</p>"
            f'<p><a href="{e(site_url)}">{e(site_url)}</a></p>'
            f"<p>It also shows how our {e(a['offer'])} works: {e(a['offer_pitch'])}. In most local "
            f"businesses, the first company to respond wins the job, so every missed call or slow reply "
            f"is revenue going to a competitor.</p>"
            f"<p>If you'd like to see the numbers for {e(company)}, just reply to this email and we'll "
            f"set up {e(a['meeting'])}.</p>"
            f"<p>— {e(a['rep_name'])}<br>{e(a['name'])}</p>"
        )

    # -- test call -----------------------------------------------------------------

    def test_call(self, phone: str, name: str = "Ascend Test Call") -> str:
        """Enroll your own phone number to hear the agent end to end."""
        ctx = self.context()
        if ctx is None or not ctx.workflow_id:
            raise RuntimeError("GHL call workflow isn't resolved; run `ascend setup` and finish docs/SETUP.md first.")
        assert self.ghl is not None
        contact, _ = self.ghl.upsert_contact(
            {
                "name": name,
                "companyName": name,
                "phone": phone,
                "source": "Ascend test",
                "customFields": ctx.custom_fields(
                    {
                        "site_url": f"{self.campaign.sites['base_url']}/",
                        "audit": "A recent Google review says: \"Called twice and never got a callback.\"",
                        "niche": "HVAC",
                        "loss": "$2,750",
                    }
                ),
            }
        )
        self.ghl.add_tags(contact["id"], ["ascend-test"])
        self.ghl.add_to_workflow(contact["id"], ctx.workflow_id)
        return contact["id"]


def write_preview(lead: Lead, campaign: Campaign, claude: Claude | None, out_dir: Path = PREVIEW_DIR) -> Path:
    """Render one site to .ascend/preview without touching GHL or the sites/ ledger."""
    html = render_site(lead, write_copy(lead, campaign, claude), campaign)
    out = out_dir / lead.slug
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(html, encoding="utf-8")
    return path
