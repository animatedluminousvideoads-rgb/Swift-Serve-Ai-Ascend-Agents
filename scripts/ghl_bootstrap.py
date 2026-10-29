"""Create the custom fields, tags and custom values this kit needs in your GHL sub-account.

Idempotent: anything that already exists (matched by name) is skipped.
Pipelines and workflows cannot be created through the GHL API, so this script only
checks that the pipeline from ghl/config.json exists (build it by hand, see docs/01).

    python scripts/ghl_bootstrap.py            # apply
    python scripts/ghl_bootstrap.py --dry-run  # print requests only
"""
import argparse
import sys

from ghl_client import GHLClient, load_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    ghl = GHLClient(dry_run=args.dry_run)

    existing = {f["name"].lower() for f in ghl.custom_fields()}
    for field in cfg["custom_fields"]:
        if field["name"].lower() in existing:
            print(f"custom field exists: {field['name']}")
            continue
        ghl.create_custom_field(field["name"], field["dataType"])
        print(f"created custom field: {field['name']}")

    existing = {t["name"].lower() for t in ghl.tags()}
    for tag in cfg["tags"]:
        if tag.lower() in existing:
            print(f"tag exists: {tag}")
            continue
        ghl.create_tag(tag)
        print(f"created tag: {tag}")

    existing = {v["name"].lower() for v in ghl.custom_values()}
    for name, value in cfg["custom_values"].items():
        if name.lower() in existing:
            print(f"custom value exists: {name}")
            continue
        ghl.create_custom_value(name, value)
        print(f"created custom value: {name}")

    if args.dry_run:
        return 0
    want = cfg["pipeline"]["name"].lower()
    pipeline = next((p for p in ghl.pipelines() if p["name"].lower() == want), None)
    if not pipeline:
        print(f"\nMISSING pipeline '{cfg['pipeline']['name']}'. Create it in Opportunities > Pipelines "
              f"with stages: {', '.join(cfg['pipeline']['stages'])}")
        return 1
    stages = {s["name"] for s in pipeline.get("stages", [])}
    missing = [s for s in cfg["pipeline"]["stages"] if s not in stages]
    if missing:
        print(f"\nPipeline found but missing stages: {', '.join(missing)}")
        return 1
    print("\npipeline OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
