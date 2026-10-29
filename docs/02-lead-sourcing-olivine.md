# 02 — Lead Sourcing with Olivine (replaces Google Maps scraping)

The reference workflow pulls businesses from Google Maps and filters for ones with
no or outdated websites. This kit swaps the source to **Olivine (useolivine.com)**;
everything after the export (audit, scoring, GHL push, outreach) is automated.

## 1. Create the Olivine account (you do this — needs your Google login)
1. Go to https://useolivine.com and choose **Sign in with Google**.
2. Pick the Google account you want tied to the agency (a separate business Gmail
   is a good idea, so prospecting stays separate from personal mail).
3. Complete onboarding / plan selection.

## 2. Search
Target niches that buy websites and have local intent: plumbers, roofers, HVAC,
landscapers, cleaners, auto repair, salons/barbers, restaurants, dentists, contractors.
- Location: one city or metro at a time
- If Olivine offers a "no website" or "website" filter, run the **no website** search
  first (hottest leads), then a second search with websites for the dated-site audit.
- Prefer businesses with **10+ reviews and 4+ stars**: they're real, busy, and can pay.

## 3. Export
Export to CSV and save it as `data/olivine_<city>_<niche>.csv`. Column names don't
need to match exactly — `audit_leads.py` recognises common variants
("Business Name", "Phone Number", "Website URL", …). If a column isn't picked up,
add its header to `COLUMN_ALIASES` in `scripts/audit_leads.py`.

## 4. Score and push
```bash
python scripts/audit_leads.py data/olivine_austin_plumbers.csv -o data/scored.csv
python scripts/push_to_ghl.py data/scored.csv --dry-run
python scripts/push_to_ghl.py data/scored.csv --limit 25   # start small
```
`audit_leads.py` visits each website and flags: no site, Facebook/Yelp-only,
site down, no HTTPS, not mobile-friendly, old copyright year, jQuery 1.x,
legacy HTML, Flash, old WordPress, slow load. Score 0–100; `hot` ≥ 70, `warm` ≥ 40.
Leads under 40 (modern sites) are dropped.

Run this on your own computer (Python 3.9+, no installs needed); it needs normal
internet access to visit the prospects' websites.
