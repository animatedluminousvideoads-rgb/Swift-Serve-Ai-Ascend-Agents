# Swift-Serve-Ai-Ascend-Agents
For Selling Agents

A kit to set up a GoHighLevel (GHL) agency account and run an automated "find local
businesses with no/dated websites → sell them a website through GHL" pipeline, using
**Olivine** as the lead source instead of Google Maps.

## Runbook
1. **Set up GHL** — follow [docs/01-ghl-setup-checklist.md](docs/01-ghl-setup-checklist.md),
   then fill in `.env` (copy `.env.example`) and run `python scripts/ghl_bootstrap.py`.
2. **Source leads** — sign in to Olivine with Google and export a CSV:
   [docs/02-lead-sourcing-olivine.md](docs/02-lead-sourcing-olivine.md).
3. **Score + push**
   ```bash
   python scripts/audit_leads.py data/olivine_export.csv -o data/scored.csv
   python scripts/push_to_ghl.py data/scored.csv --limit 25
   ```
4. **Outreach runs in GHL** — workflows in [docs/03-workflows.md](docs/03-workflows.md),
   copy in [docs/04-outreach-scripts.md](docs/04-outreach-scripts.md).

## Layout
| Path | What |
|---|---|
| `ghl/config.json` | Pipeline stages, custom fields, tags, custom values, deal values |
| `scripts/ghl_client.py` | Stdlib GHL API v2 client (Private Integration token) |
| `scripts/ghl_bootstrap.py` | Creates fields/tags/values, verifies pipeline |
| `scripts/audit_leads.py` | Visits each site, scores how much it needs a rebuild |
| `scripts/push_to_ghl.py` | Upserts contacts, tags them, opens opportunities |
| `tests/` | `python -m unittest discover -s tests` |

Python 3.9+, no third-party packages.
