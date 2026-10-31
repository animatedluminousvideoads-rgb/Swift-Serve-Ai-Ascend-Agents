# Swift Serve AI Ascend: Selling Agents

Autonomous client acquisition for **Swift Serve AI Ascend**. Every business hour it:

1. **Finds prospects**: local HVAC, plumbing, electrical, roofing, dental, law and med-spa businesses in your target cities (Google Places, or your own CSV).
2. **Audits them**: reviews that complain about missed calls or slow callbacks, no website or a weak one, ratings in the 3.5–4.5★ sweet spot, plus an estimate of the revenue at risk each week.
3. **Builds each one a free demo website**: copy written by Claude, published automatically on GitHub Pages, and clearly labeled as a concept preview. Each site also demos the 24/7 AI lead responder you sell.
4. **Loads them into your GoHighLevel**: contact, audit note, custom fields (site link, review quote, revenue at risk) and an opportunity in the *Ascend AI Outbound* pipeline.
5. **Has your GHL Voice AI agent cold-call them**, inside each business's local calling hours. The agent introduces itself as an AI and pitches the free site and the AI Inbound Lead Responder. It books a 15-minute call with Hiro, or offers to text the link.
6. **Follows up on every call**, every 15 minutes: moves the pipeline stage, logs a summary note, creates a follow-up task for you, texts or emails the preview link when the prospect agreed to it, honors do-not-call requests (DND), and retries voicemails once after 2 days.

```
 Google Places / CSV ──► audit + score ──► demo site (Claude) ──► GHL contact + opportunity
                                                │                         │
                                         GitHub Pages             "Site Built" stage
                                                                         │  (in calling hours,
                                                                         ▼   compliance gates)
  GHL tasks / SMS / email ◄── outcome ◄── Voice AI call log ◄── "Ascend AI Cold Call" workflow
```

All state lives in GoHighLevel. The committed `sites/` folder doubles as the record of which businesses have already been processed.

## Getting started

Follow **[docs/SETUP.md](docs/SETUP.md)**. It takes about 20 minutes, once. After that it runs by itself on GitHub Actions, with no server to host.

## Commands

```bash
pip install -e ".[dev]"
ascend preview                 # render a sample demo site to .ascend/preview/ (no keys needed)
ascend show-agent              # print the Voice AI agent's script
ascend setup                   # create GHL custom fields + Voice AI agent, check pipeline/workflow
ascend test-call --phone +1…   # have the agent call your phone
ascend prospect [--csv leads.csv] [--dry-run]
ascend dial                    # queue eligible leads into the GHL call workflow
ascend sync                    # process finished calls
ascend run                     # sync + prospect + dial
python -m pytest -q
```

## Configuration

Targeting, cities, niches, calling hours, limits, GHL names and your agency identity all live in [`config/campaign.yaml`](config/campaign.yaml). Secrets come from environment variables / GitHub Actions secrets ([`.env.example`](.env.example)).

## Safeguards built in

- The agent says it's an AI in its first sentence, never quotes prices, and ends the call when asked not to be contacted. Those contacts get DND in GHL and are never re-dialed.
- Calls only go out Monday–Friday, 9:30–16:30 in the business's own time zone. Config validation also refuses any window outside 8am–9pm.
- AI voices count as "artificial voice" under the TCPA, so **mobile numbers are never auto-called**. With Twilio Lookup configured, landlines and business VoIP lines are dialed. Mobile and unverified numbers go to a *Needs Review* stage for you to call personally.
- Demo sites carry a "concept preview, not the official website" banner and `noindex`. They never invent reviews, licenses or prices.
- This repo is public, so run logs and summaries hold only counts. Business details, transcripts and phone numbers stay in GHL.

This is not legal advice. Check federal and state telemarketing rules for your markets before scaling up.
