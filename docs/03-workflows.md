# 03 — GHL Workflows to Build (Automation > Workflows)

Build each one from **Create Workflow > Start from scratch**. Templates for the
messages are in `docs/04-outreach-scripts.md`.

> **Compliance first.** Texting scraped numbers without prior consent can violate
> the TCPA (US fines are per message) and carriers will block your A2P campaign.
> These workflows therefore open with **email + a manual call task**, and only text
> people who replied or booked. Every email must include your business address and
> an opt-out line (CAN-SPAM). Tag `do-not-contact` on anyone who opts out.

## W1 — Outreach: No Website
- **Trigger:** Contact Tag Added = `no-website`
- **Filter:** tag is not `do-not-contact`
1. Add tag `outreach-started`; move opportunity to `Contacted`
2. If email exists → Send Email "No-site #1"; else → Create Task "Call {{contact.company_name}}" (due today)
3. Wait 2 days → If no reply: Send Email "No-site #2" (with demo link if built)
4. Wait 3 days → If no reply: Create Task "Call – follow-up"
5. Wait 4 days → If no reply: Send Email "Breakup"
6. Wait 7 days → If no reply: move opportunity to `Lost`, remove `outreach-started`

Use **Goal Event: Customer Replied** on the workflow so any reply jumps to W3.

## W2 — Outreach: Dated Website
Same as W1, trigger tag `dated-website` / `site-unreachable`, using the "Dated-site"
emails, which quote the issues from `{{contact.website_issues}}`.

## W3 — Reply Handler
- **Trigger:** Customer Replied (email or SMS)
1. Remove from W1/W2; add tag `replied`; move opportunity to `Replied / Interested`
2. Internal notification (SMS/app push) to you: "{{contact.company_name}} replied"
3. Send booking link email/SMS "Book a 15-min call: {{custom_values.booking_link}}"
   (SMS is fine here — they started the conversation)

## W4 — Booked / Won
- **Trigger:** Appointment Status = booked (calendar "Website Strategy Call")
  → move to `Demo Booked`, send confirmation + reminder 1 day and 1 hour before
- **Trigger:** Payment Received (product "Website Setup")
  → move to `Won`, send onboarding form, create sub-account from your snapshot
  (Agency > SaaS / "Create sub-account" action), start build tasks

## Demo-site step (what makes this convert)
For hot leads, before email #2: clone your niche template in Sites, swap in the
business name, phone, city and services, publish to
`demo.youragency.com/<business-slug>`, and paste the URL into the contact's
**Demo Site URL** field. Email #2 then links to their site already built.
