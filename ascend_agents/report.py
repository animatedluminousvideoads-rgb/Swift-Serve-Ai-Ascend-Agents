"""Session report in the client-acquisition playbook format (counts only).

Run logs and summaries are public on a public GitHub repo, so this report holds
no business names, phone numbers or call details. Those live in GHL.
"""

from __future__ import annotations

import os
from datetime import datetime

from .config import Campaign
from .pipeline import RunStats


def render_report(stats: RunStats, campaign: Campaign, step: str, now: datetime) -> str:
    a = campaign.agency
    lines = [
        f"### {a['name']}: {step} ({now:%Y-%m-%d %H:%M} UTC)",
        "",
        "```",
        "=== CLIENT ACQUISITION SESSION REPORT ===",
        f"Agent: {a['rep_name']} / {a['name']}",
    ]
    if stats.searches or stats.found:
        lines += [
            f"SEARCHES: {', '.join(stats.searches) or 'CSV import'}",
            f"BUSINESSES FOUND: {stats.found}  (already processed: {stats.already_processed}, "
            f"below score threshold: {stats.unqualified})",
            f"DEMO SITES BUILT: {stats.sites_built}",
            f"LOADED INTO GHL: {stats.pushed_to_ghl}  (held for review, not auto-called: {stats.held_for_review})",
        ]
    if step == "dial" or stats.enrolled:
        lines.append(f"AI CALLS QUEUED IN GHL: {stats.enrolled}  (retries: {stats.retries})")
    if stats.calls_synced or step == "sync":
        outcomes = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(stats.outcomes.items())) or "none"
        lines += [
            f"CALLS PROCESSED: {stats.calls_synced}  ({outcomes})",
            f"FOLLOW-UPS: preview links texted {stats.links_texted}, emailed {stats.links_emailed}, "
            f"rep tasks created {stats.tasks_created}",
        ]
    lines.append("```")
    if stats.problems:
        lines += ["", "**Setup items to fix:**"] + [f"- {p}" for p in dict.fromkeys(stats.problems)]
    if stats.errors:
        lines += ["", f"**Errors ({len(stats.errors)}):**"] + [f"- {e}" for e in stats.errors[:20]]
    return "\n".join(lines) + "\n"


def publish_report(markdown: str) -> None:
    print(markdown)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
