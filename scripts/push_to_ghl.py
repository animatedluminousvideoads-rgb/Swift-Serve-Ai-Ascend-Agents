"""Push scored leads into GHL: upsert each contact, tag it, and open an opportunity
in the Website Sales pipeline. Tags then trigger the outreach workflows (docs/03).

    python scripts/push_to_ghl.py data/scored_leads.csv --dry-run
    python scripts/push_to_ghl.py data/scored_leads.csv --limit 25
"""
import argparse
import csv
import sys

from ghl_client import GHLClient, GHLError, load_config

STATUS_TAG = {
    "none": "no-website",
    "social-only": "no-website",
    "unreachable": "site-unreachable",
    "dated": "dated-website",
}


def build_contact(lead, field_ids):
    tags = ["lead-olivine", f"{lead['tier']}-lead", STATUS_TAG.get(lead["website_status"], "dated-website")]
    values = {
        "Lead Score": lead["lead_score"],
        "Website Status": lead["website_status"],
        "Website Issues": lead["website_issues"],
        "Business Category": lead["category"],
        "Google Rating": lead["rating"],
        "Review Count": lead["reviews"],
        "Lead Source Detail": "Olivine",
    }
    contact = {
        "companyName": lead["name"],
        "name": lead["name"],
        "phone": lead["phone"] or None,
        "email": lead["email"] or None,
        "website": lead["website"] or None,
        "address1": lead["address"] or None,
        "city": lead["city"] or None,
        "state": lead["state"] or None,
        "source": "Olivine",
        "tags": tags,
        "customFields": [{"id": field_ids[k], "field_value": v}
                         for k, v in values.items() if v not in ("", None) and k in field_ids],
    }
    return {k: v for k, v in contact.items() if v is not None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="push at most N leads (0 = all)")
    args = parser.parse_args()

    cfg = load_config()
    ghl = GHLClient(dry_run=args.dry_run)

    field_ids = {f["name"]: f["id"] for f in ghl.custom_fields()}
    pipeline_id = stage_ids = None
    if not args.dry_run:
        want = cfg["pipeline"]["name"].lower()
        pipeline = next((p for p in ghl.pipelines() if p["name"].lower() == want), None)
        if not pipeline:
            print("Pipeline missing. Run scripts/ghl_bootstrap.py and follow docs/01 first.")
            return 1
        pipeline_id = pipeline["id"]
        stage_ids = {s["name"]: s["id"] for s in pipeline["stages"]}

    with open(args.input, newline="") as f:
        leads = list(csv.DictReader(f))
    if args.limit:
        leads = leads[:args.limit]

    pushed = skipped = failed = 0
    for lead in leads:
        if not (lead["phone"] or lead["email"]):
            skipped += 1
            continue
        try:
            contact = ghl.upsert_contact(build_contact(lead, field_ids))
            no_site = lead["website_status"] in ("none", "social-only", "unreachable")
            stage = cfg["pipeline"]["stages"][0 if no_site else 1]
            value = cfg["opportunity_value"]["no_site" if no_site else "dated_site"]
            if not args.dry_run:
                ghl.create_opportunity(pipeline_id, stage_ids[stage], contact["id"],
                                       f"{lead['name']} - Website", value)
            pushed += 1
        except GHLError as e:
            failed += 1
            print(f"FAILED {lead['name']}: {e}")

    print(f"pushed {pushed}, skipped {skipped} (no phone/email), failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
