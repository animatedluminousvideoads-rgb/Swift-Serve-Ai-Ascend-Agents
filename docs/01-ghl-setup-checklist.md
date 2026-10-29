# 01 — GHL Account Setup Checklist (to 100%)

Work top to bottom. Items marked **[script]** are done by `scripts/ghl_bootstrap.py`;
everything else must be clicked in the GHL UI (the GHL API cannot create
pipelines, workflows, calendars, phone numbers or A2P registrations).

## A. Agency level (Agency View)
- [ ] Agency Settings > Company: legal name, address, logo, support email/phone
- [ ] Agency Settings > Team: add yourself with 2FA turned on
- [ ] Billing: confirm plan; turn on **SaaS Configurator / Rebilling** if you will resell GHL to clients
- [ ] Agency Settings > Stripe: connect Stripe so you can charge clients (setup fee + monthly)
- [ ] Create a sub-account for **your own agency** (this is where your sales pipeline lives)

## B. Your agency sub-account
1. **Business Profile** – name, address, timezone, logo, website. Copy the **Location ID**.
2. **Private Integration** – Settings > Private Integrations > New. Grant the scopes in
   `.env.example`, copy the token into `.env` with the Location ID.
3. **Phone number** – Settings > Phone Numbers > buy a local number in your target area.
4. **A2P 10DLC** – Settings > Phone Numbers > Trust Center: register your brand and a
   "Marketing"/"Customer care" campaign. No US SMS will deliver until this is approved
   (usually several days, so start it first).
5. **Email** – Settings > Email Services: add a dedicated sending subdomain
   (e.g. `mail.youragency.com`), add the SPF/DKIM/DMARC records it shows at your DNS
   host and verify. Do **not** cold email from your main domain.
6. **Domain** – Settings > Domains: connect `youragency.com` (for funnels/sites) and
   a subdomain for client demo sites, e.g. `demo.youragency.com`.
7. **Calendar** – Calendars > New > "Website Strategy Call", 15–20 min, with Google
   Calendar sync on. Put its link in Custom Value `booking_link`.
8. **Pipeline** – Opportunities > Pipelines > New: **Website Sales** with stages
   (exact names, the scripts look them up):
   `New Lead (No Site)`, `New Lead (Dated Site)`, `Contacted`, `Replied / Interested`,
   `Demo Booked`, `Proposal Sent`, `Won`, `Lost`
9. **[script]** Custom fields, tags, custom values:
   ```bash
   python scripts/ghl_bootstrap.py --dry-run   # preview
   python scripts/ghl_bootstrap.py             # apply + verify pipeline
   ```
   Then edit Custom Values (`sender_name`, `agency_name`, `booking_link`, prices).
10. **Payments** – Payments > Products: "Website Setup" ($997 one-time) and
    "Website Care Plan" ($97/mo). Create a payment link / order form for each.
11. **Website template** – Sites > Websites: build one niche template (e.g. home
    services). You'll clone it per prospect as their demo (see docs/03).
12. **Conversation AI / Reviews (upsell)** – optional: enable Conversation AI and
    Reputation Management; these are add-ons you can bundle into the monthly plan.
13. **Snapshot** – once the sub-account is complete, Agency > Snapshots > create a
    snapshot so each new client sub-account starts fully built.
14. **Workflows** – build the four workflows in `docs/03-workflows.md`.
15. **Mobile app** – install the LeadConnector app so replies reach your phone.

## Done check
`python scripts/ghl_bootstrap.py` prints `pipeline OK`, a test contact you push gets
tagged and lands in `New Lead (No Site)`, and the "Outreach – No Website" workflow
fires for it.
