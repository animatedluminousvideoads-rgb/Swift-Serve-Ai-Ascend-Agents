import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit_leads import analyze_html, audit, normalize_row, tier  # noqa: E402
from push_to_ghl import build_contact  # noqa: E402

MODERN = """<html><head><meta name="viewport" content="width=device-width">
<meta name="description" content="Plumbing"></head>
<body><footer>&copy; 2026 Joe's Plumbing</footer></body></html>"""

DATED = """<html><head><script src="/js/jquery-1.7.2.min.js"></script></head>
<body><center><font size=2>Welcome!</font></center>
<embed src="intro.swf"><p>Copyright 2014 Joe's Plumbing</p></body></html>"""


class AnalyzeHtmlTest(unittest.TestCase):
    def test_modern_site_scores_low(self):
        score, issues = analyze_html(MODERN, "https://joes.com/", 0.5, now_year=2026)
        self.assertEqual(score, 0)
        self.assertEqual(issues, [])

    def test_dated_site_scores_high(self):
        score, issues = analyze_html(DATED, "http://joes.com/", 5.0, now_year=2026)
        self.assertEqual(score, 80)  # capped
        self.assertIn("no HTTPS", issues)
        self.assertIn("copyright 2014", issues)
        self.assertIn("uses Flash", issues)


class AuditTest(unittest.TestCase):
    def test_no_website(self):
        r = audit({"website": ""})
        self.assertEqual((r["website_status"], r["lead_score"]), ("none", 100))

    def test_facebook_only(self):
        r = audit({"website": "https://www.facebook.com/joesplumbing"})
        self.assertEqual(r["website_status"], "social-only")


class HelpersTest(unittest.TestCase):
    def test_normalize_aliases(self):
        row = normalize_row({"Business Name": "Joe's", "Phone Number": "555", "Website URL": "joes.com"})
        self.assertEqual((row["name"], row["phone"], row["website"]), ("Joe's", "555", "joes.com"))

    def test_tier(self):
        self.assertEqual([tier(100), tier(50), tier(10)], ["hot", "warm", "cold"])

    def test_build_contact(self):
        lead = {"name": "Joe's", "phone": "+15551234567", "email": "", "website": "", "address": "",
                "city": "Austin", "state": "TX", "category": "Plumber", "rating": "4.8", "reviews": "52",
                "website_status": "none", "website_issues": "no website", "lead_score": "100", "tier": "hot"}
        c = build_contact(lead, {"Lead Score": "f1", "Business Category": "f2"})
        self.assertNotIn("email", c)
        self.assertEqual(sorted(c["tags"]), ["hot-lead", "lead-olivine", "no-website"])
        self.assertEqual(c["customFields"], [{"id": "f1", "field_value": "100"},
                                             {"id": "f2", "field_value": "Plumber"}])


if __name__ == "__main__":
    unittest.main()
