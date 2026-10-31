"""Command line entry point: `ascend <command>`."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from datetime import datetime, timezone

from .compliance import normalize_phone
from .config import Settings, load_campaign
from .ghl.client import GHLClient
from .ghl.setup import setup
from .ghl.voice_agent import agent_prompt, welcome_message
from .llm import Claude
from .models import Lead, Review
from .pipeline import Pipeline, write_preview
from .report import publish_report, render_report
from .sources.csv_source import read_csv_leads

SAMPLE_LEAD = Lead(
    source_id="sample-preview",
    name="Desert Breeze Heating & Air",
    niche_key="hvac",
    niche_label="HVAC",
    market="Phoenix, AZ",
    timezone="America/Phoenix",
    phone="+16025550143",
    phone_display="(602) 555-0143",
    city="Phoenix",
    state="AZ",
    rating=4.1,
    review_count=86,
    maps_url="https://maps.google.com/",
    reviews=[Review(rating=2, text="Great work once they came out, but I called three times and nobody answered.")],
)


def _pipeline(args) -> Pipeline:
    settings = Settings.from_env()
    if getattr(args, "dry_run", False):
        settings = dataclasses.replace(settings, dry_run=True)
    return Pipeline(load_campaign(args.campaign), settings)


def cmd_setup(args) -> int:
    settings = Settings.from_env()
    campaign = load_campaign(args.campaign)
    if not settings.has_ghl:
        print("Set GHL_API_TOKEN and GHL_LOCATION_ID first (see docs/SETUP.md).")
        return 1
    ctx, done = setup(GHLClient(settings.ghl_token, settings.ghl_location_id), campaign)
    lines = ["### GoHighLevel setup", ""] + [f"- ✅ {d}" for d in done]
    lines += [f"- ⚠️ {p}" for p in ctx.problems] or ["- ✅ Everything is in place. The pipeline can dial."]
    publish_report("\n".join(lines) + "\n")
    return 1 if ctx.problems else 0


def _finish(p: Pipeline, step: str) -> int:
    publish_report(render_report(p.stats, p.campaign, step, datetime.now(timezone.utc)))
    # Errors (not setup items) fail the step, so GitHub notifies you of the failed run.
    return 1 if p.stats.errors else 0


def cmd_sync(args) -> int:
    p = _pipeline(args)
    p.sync_calls(lookback_hours=args.hours)
    return _finish(p, "sync")


def cmd_prospect(args) -> int:
    p = _pipeline(args)
    leads = read_csv_leads(args.csv, p.campaign) if args.csv else None
    p.prospect(leads)
    return _finish(p, "prospect")


def cmd_dial(args) -> int:
    p = _pipeline(args)
    p.dial()
    return _finish(p, "dial")


def cmd_run(args) -> int:
    p = _pipeline(args)
    if p.ghl is not None:
        p.sync_calls()
    p.prospect()
    if p.ghl is not None:
        p.dial()
    return _finish(p, "run")


def cmd_test_call(args) -> int:
    phone = normalize_phone(args.phone)
    if not phone:
        print("Give a US/Canada number, e.g. +16025550143")
        return 1
    p = _pipeline(args)
    cid = p.test_call(phone)
    print(f"Test contact {cid} enrolled in the AI call workflow. Your phone should ring shortly.")
    return 0


def cmd_preview(args) -> int:
    settings = Settings.from_env()
    campaign = load_campaign(args.campaign)
    claude = Claude(settings.anthropic_key, settings.claude_model) if settings.has_claude else None
    leads = read_csv_leads(args.csv, campaign) if args.csv else [SAMPLE_LEAD]
    for lead in leads[: args.limit]:
        print(write_preview(lead, campaign, claude))
    return 0


def cmd_show_agent(args) -> int:
    campaign = load_campaign(args.campaign)
    print("WELCOME MESSAGE:\n" + welcome_message(campaign) + "\n\nPROMPT:\n" + agent_prompt(campaign, {}))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ascend", description=__doc__)
    parser.add_argument("--campaign", help="path to campaign.yaml (default: config/campaign.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="create custom fields + Voice AI agent in GHL and check the rest").set_defaults(fn=cmd_setup)

    s = sub.add_parser("sync", help="process recent Voice AI calls into GHL stages, notes and follow-ups")
    s.add_argument("--hours", type=int, default=30)
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("prospect", help="find businesses, build demo sites, load them into GHL")
    s.add_argument("--csv", help="import leads from a CSV instead of searching Google")
    s.add_argument("--dry-run", action="store_true", help="build preview sites only; no GHL writes")
    s.set_defaults(fn=cmd_prospect)

    sub.add_parser("dial", help="queue eligible leads into the GHL AI call workflow").set_defaults(fn=cmd_dial)

    s = sub.add_parser("run", help="sync + prospect + dial in one go")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("test-call", help="have the AI agent call your own phone")
    s.add_argument("--phone", required=True)
    s.set_defaults(fn=cmd_test_call)

    s = sub.add_parser("preview", help="render demo sites locally to .ascend/preview (no GHL)")
    s.add_argument("--csv")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(fn=cmd_preview)

    sub.add_parser("show-agent", help="print the Voice AI agent script").set_defaults(fn=cmd_show_agent)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
