# One-time setup (about 20 minutes)

After these steps the system runs on its own: GitHub Actions runs it every business hour, with nothing for you to host.

The only things automation can't do for you are creating accounts and API keys, plus two GHL pieces that GHL's API can't create (a pipeline and a workflow). Everything else, including the Voice AI agent and its script, is created for you by the **GHL setup** action.

---

## 1. Turn on GitHub Pages (hosts the demo sites)

Repository **Settings → Pages → Build and deployment → Source: GitHub Actions**.

Sites are served at `https://animatedluminousvideoads-rgb.github.io/Swift-Serve-Ai-Ascend-Agents/<business>/`. To use your own domain, set it up in the same Pages screen and set the `ASCEND_SITE_BASE_URL` secret, or edit `sites.base_url` in `config/campaign.yaml`.

## 2. Create a GHL Private Integration token

In the GHL **sub-account** you sell from: **Settings → Private Integrations → Create new integration**. Name it "Ascend Agents" and give it these scopes:

| Area | Scopes |
|---|---|
| Contacts | `contacts.readonly`, `contacts.write` |
| Opportunities | `opportunities.readonly`, `opportunities.write` |
| Locations | `locations.readonly`, `locations/customFields.readonly`, `locations/customFields.write` |
| Workflows / calendars | `workflows.readonly`, `calendars.readonly` |
| Conversations | `conversations/message.write` (texts/emails the preview link) |
| Voice AI | `voice-ai-agents.readonly`, `voice-ai-agents.write`, `voice-ai-agent-goals.readonly`, `voice-ai-agent-goals.write`, `voice-ai-dashboard.readonly` |

Copy the token. Also copy the **Location ID** from **Settings → Business Profile**; it's also the ID in the sub-account's URL.

## 3. Create the pipeline in GHL

**Opportunities → Pipelines → Create new pipeline** named exactly `Ascend AI Outbound`, with these stages in this order:

1. `Site Built`
2. `Needs Review`
3. `AI Call Queued`
4. `Called - No Decision`
5. `Interested`
6. `Booked Call`
7. `Not Interested`
8. `Do Not Call`

(To use other names, edit `ghl.stages` in `config/campaign.yaml` so they match.)

## 4. Phone number

You need a GHL (LC Phone) number for the agent to call from. To text preview links you also need the sub-account's A2P 10DLC registration approved. Calls still work without it, but texts won't send.

## 5. Add GitHub secrets

Repository **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Required? | Where to get it |
|---|---|---|
| `GHL_API_TOKEN` | Yes | Step 2 |
| `GHL_LOCATION_ID` | Yes | Step 2 |
| `GOOGLE_PLACES_API_KEY` | Yes | Google Cloud Console → enable **Places API (New)** → Credentials → Create API key (restrict it to Places API). Billed per search by Google. |
| `ANTHROPIC_API_KEY` | Recommended | console.anthropic.com. Claude writes each site's copy and reads call transcripts. Without it, sites use template copy and calls are sorted by keywords. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Recommended | twilio.com console. Used only for Lookup (line type), costing a fraction of a cent to about a cent per number. **Without it no lead is auto-called** (see Compliance below). |
| `ASCEND_TEST_PHONE` | Optional | Your own cell, for test calls. |
| `ASCEND_SUPPRESS_NUMBERS` | Optional | Comma-separated numbers that must never be called. |

## 6. Run "GHL setup"

**Actions → GHL setup → Run workflow.** It:

- creates the contact custom fields (`Ascend Demo Site URL`, `Ascend Audit Finding`, `Ascend Weekly Revenue At Risk`, …),
- creates the Voice AI agent **Ascend Cold Caller** with the full cold-call script (run `ascend show-agent` to read it),
- adds a booking action if you set `ghl.booking_calendar_name` in `config/campaign.yaml`,
- checks the pipeline and workflow and lists anything still missing in the run summary.

Run it again any time you change `config/campaign.yaml`. It updates the agent's script in place.

## 7. Build the call workflow in GHL

GHL's API can't create workflows, so this one is by hand. It's a single action:

1. Open **AI Agents → Voice AI → Ascend Cold Caller**. Pick a voice you like, and listen to the script if you want to tweak it. (Edits made here are overwritten the next time GHL setup runs. Permanent changes go in `ascend_agents/ghl/voice_agent.py`.)
2. **Automation → Workflows → Create workflow → Start from scratch**, named exactly `Ascend AI Cold Call`.
3. No trigger is needed: the pipeline adds contacts to the workflow through the API.
4. Add the Voice AI **outbound call** action. GHL labels it "Voice AI Outbound Call" or "Call an AI Agent" depending on the account. Choose agent **Ascend Cold Caller** and your LC Phone number.
5. **Publish** the workflow.

## 8. Test call

**Actions → GHL setup → Run workflow** with **Test call** ticked. The agent calls `ASCEND_TEST_PHONE` using a sample HVAC prospect. Check two things on the call:

- **Merge fields work**: the agent should say the business name, not a literal `{{contact.company_name}}`. If it doesn't, your GHL account may not support contact fields in Voice AI prompts. In that case, replace the `{{contact.…}}` tags in `ascend_agents/ghl/voice_agent.py` with general wording and re-run GHL setup.
- **The flow**: it should disclose that it's an AI, pitch, then offer the meeting or the text.

## 9. Live

That's it. **Acquire clients** runs hourly on weekdays during US business hours, and **Sync AI call outcomes** runs every 15 minutes. You'll see:

- new prospects arriving in GHL under **Site Built**, with an audit note and the site link,
- **AI Call Queued → Interested / Booked Call / …** as calls complete,
- GHL tasks for every interested or booked prospect,
- a short report on every run's summary page (counts only).

**Pause everything:** Settings → Secrets and variables → Actions → Variables → add `ASCEND_PAUSED` = `true`.
**Do a dry run:** Actions → Acquire clients → Run workflow → tick *dry run*. It builds preview sites only, with no GHL writes or calls.
**Import your own leads** (Apollo export, etc.): `ascend prospect --csv leads.csv`. See `ascend_agents/sources/csv_source.py` for the columns.

---

## Compliance notes (read before scaling)

- **AI disclosure and opt-out.** The agent says it's an AI in its opening line, and ends the call when asked not to be contacted. The sync step then sets DND on that contact and tags it `ascend-dnc`, so it's never called or texted again.
- **Calling hours.** Monday–Friday, 9:30–16:30 in the business's own time zone. Config validation refuses any window outside 8am–9pm local time.
- **Mobile numbers.** The FCC treats AI-generated voices as "artificial voice" under the TCPA, which requires prior express consent for calls to mobile numbers, even business-owned ones. The pipeline therefore auto-calls only line types in `calling.auto_call_line_types` (landline and business VoIP by default). Mobile numbers, and any number it couldn't verify, go to **Needs Review** for you to call personally. Changing `unverified_line_policy` to `call` is your decision to make.
- **Texts** are sent only when the prospect clearly agreed on the call, and always include "Reply STOP to opt out".
- **State laws** (for example Florida's and Oklahoma's telemarketing acts) can be stricter. Check the markets in `config/campaign.yaml` with a professional.
- **Google data.** Google Maps Platform terms limit storing Places data. If that's a concern, use CSV import from your own lead source.

This isn't legal advice.
