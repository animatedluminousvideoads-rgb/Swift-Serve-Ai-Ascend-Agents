"""Score local-business leads by how badly they need a new website.

Input: a CSV export of businesses (e.g. from Olivine). Column names are matched
loosely, so "Business Name", "name" or "Company" all work. Output adds:
website_status, website_issues, lead_score (0-100) and tier (hot/warm/cold).

    python scripts/audit_leads.py data/olivine_export.csv -o data/scored.csv
"""
import argparse
import csv
import datetime
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

COLUMN_ALIASES = {
    "name": ["name", "business name", "business", "company", "company name", "title"],
    "phone": ["phone", "phone number", "telephone", "mobile"],
    "email": ["email", "email address", "emails"],
    "website": ["website", "site", "url", "web", "domain", "website url"],
    "address": ["address", "full address", "street"],
    "city": ["city", "town", "locality"],
    "state": ["state", "region", "province"],
    "category": ["category", "categories", "type", "industry", "niche"],
    "rating": ["rating", "google rating", "stars"],
    "reviews": ["reviews", "review count", "reviews count", "number of reviews"],
}

SOCIAL_ONLY_HOSTS = (
    "facebook.com", "instagram.com", "yelp.com", "linktr.ee", "business.site",
    "tiktok.com", "x.com", "twitter.com", "nextdoor.com", "google.com", "g.page",
)

USER_AGENT = "Mozilla/5.0 (compatible; SiteAudit/1.0)"


def normalize_row(row):
    lowered = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
    out = {}
    for field, aliases in COLUMN_ALIASES.items():
        out[field] = next((lowered[a] for a in aliases if lowered.get(a)), "")
    return out


def analyze_html(html, final_url, elapsed, now_year=None):
    """Return (score, issues) for a fetched page. Higher score = more dated."""
    now_year = now_year or datetime.date.today().year
    lower = html.lower()
    score, issues = 0, []

    def flag(points, issue):
        nonlocal score
        score += points
        issues.append(issue)

    if final_url.startswith("http://"):
        flag(20, "no HTTPS")
    if 'name="viewport"' not in lower and "name='viewport'" not in lower:
        flag(25, "not mobile-friendly (no viewport)")
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)[^<]{0,40}?((?:19|20)\d\d)", lower)]
    if years and max(years) <= now_year - 3:
        flag(20, f"copyright {max(years)}")
    if re.search(r"jquery[.-]?1\.\d", lower):
        flag(10, "jQuery 1.x")
    if "<font" in lower or "<center" in lower or "<marquee" in lower:
        flag(15, "legacy HTML tags")
    if ".swf" in lower or "shockwave-flash" in lower:
        flag(15, "uses Flash")
    m = re.search(r'name="generator" content="wordpress (\d+)\.', lower)
    if m and int(m.group(1)) < 5:
        flag(10, f"WordPress {m.group(1)}.x")
    if '<meta name="description"' not in lower:
        flag(5, "no meta description")
    if elapsed > 4:
        flag(10, f"slow ({elapsed:.1f}s)")
    return min(score, 80), issues


def audit(lead, timeout=12):
    url = lead["website"]
    if not url:
        return dict(lead, website_status="none", website_issues="no website", lead_score=100)
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    host = re.sub(r"^https?://(www\.)?", "", url.lower()).split("/")[0]
    if any(host == h or host.endswith("." + h) for h in SOCIAL_ONLY_HOSTS):
        return dict(lead, website_status="social-only", website_issues=f"only {host}", lead_score=85)
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read(500_000).decode(errors="replace")
            final_url = resp.geturl()
    except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        return dict(lead, website_status="unreachable", website_issues=f"site down: {reason}", lead_score=90)
    score, issues = analyze_html(html, final_url, time.monotonic() - start)
    status = "dated" if score >= 30 else "modern"
    return dict(lead, website_status=status, website_issues="; ".join(issues), lead_score=score)


def tier(score):
    return "hot" if score >= 70 else "warm" if score >= 40 else "cold"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("-o", "--output", default="data/scored_leads.csv")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-score", type=int, default=40, help="drop leads below this score")
    args = parser.parse_args()

    with open(args.input, newline="", encoding="utf-8-sig") as f:
        leads = [normalize_row(r) for r in csv.DictReader(f)]
    leads = [l for l in leads if l["name"]]

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(audit, leads))
    for r in results:
        r["tier"] = tier(r["lead_score"])
    kept = sorted((r for r in results if r["lead_score"] >= args.min_score),
                  key=lambda r: r["lead_score"], reverse=True)

    fields = list(COLUMN_ALIASES) + ["website_status", "website_issues", "lead_score", "tier"]
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(kept)

    counts = {}
    for r in kept:
        counts[r["website_status"]] = counts.get(r["website_status"], 0) + 1
    print(f"audited {len(results)} leads, kept {len(kept)} -> {args.output}")
    for status, n in sorted(counts.items()):
        print(f"  {status}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
