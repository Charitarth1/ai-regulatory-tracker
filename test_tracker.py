import json
import os
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(__file__))
import tracker  # noqa: E402

AI_SRC = {"name": "Gov", "jur": "UK", "filter": "ai", "url": "https://example.gov/feed"}
LAB_SRC = {"name": "Lab", "jur": "Labs", "filter": "lab", "url": "https://example.ai/feed", "cap": 2}

RSS = b"""<rss><channel>
<item><title>New rules for artificial intelligence in hiring</title><link>https://example.gov/a</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Fisheries advisory board meeting</title><link>https://example.gov/b</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Minister to announce AI funding</title><link>https://example.gov/c</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>AI guidance over plain http</title><link>http://example.gov/d</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class FilterTests(unittest.TestCase):
    def test_ai_filter_matches_terms_and_exact_acronym(self):
        self.assertTrue(tracker.keep(AI_SRC, "UK sets out AI assurance roadmap", ""))
        self.assertTrue(tracker.keep(AI_SRC, "Consultation", "on machine learning in credit"))
        self.assertFalse(tracker.keep(AI_SRC, "Minister said aid will rise", ""))

    def test_media_advisories_are_dropped(self):
        self.assertFalse(tracker.keep(AI_SRC, "Minister Solomon to announce AI internships", ""))

    def test_lab_filter_keeps_safety_and_drops_marketing(self):
        self.assertTrue(tracker.keep(LAB_SRC, "Safety overview: GPT-6 Astra", ""))
        self.assertFalse(tracker.keep(LAB_SRC, "Airbnb widens access to our frontier models", ""))

    def test_parse_date_handles_rss_and_atom(self):
        self.assertEqual(tracker.parse_date("Mon, 12 Oct 2026 10:00:00 GMT").day, 12)
        self.assertEqual(tracker.parse_date("2026-10-12T10:14:06Z").hour, 10)
        self.assertIsNone(tracker.parse_date("not a date"))


class CollectTests(unittest.TestCase):
    def run_collect(self, src, body):
        now = tracker.parse_date("2026-10-13T00:00:00Z")
        with mock.patch.object(tracker, "SOURCES", [src]), mock.patch.object(tracker, "fetch", return_value=body):
            return tracker.collect(now)

    def test_keeps_only_https_ai_items(self):
        items, _ = self.run_collect(AI_SRC, RSS)
        self.assertEqual([i["url"] for i in items], ["https://example.gov/a"])
        self.assertEqual(items[0]["date"], "2026-10-12")

    def test_failed_source_is_reported_not_raised(self):
        now = tracker.parse_date("2026-10-13T00:00:00Z")
        with mock.patch.object(tracker, "SOURCES", [AI_SRC]), mock.patch.object(tracker, "fetch", side_effect=OSError("down")):
            items, report = tracker.collect(now)
        self.assertEqual(items, [])
        self.assertIn("FAILED", report[0])

    def test_entity_declarations_are_refused(self):
        with mock.patch("urllib.request.urlopen") as uo:
            uo.return_value.__enter__.return_value.read.return_value = b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>'
            with self.assertRaises(ValueError):
                tracker.fetch("https://example.gov/feed")


class MergeTests(unittest.TestCase):
    def test_previous_items_survive_and_all_failed_keeps_old_feed(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "feed.json")
            old = {"version": 1, "items": [{"id": "old1", "title": "Older AI item", "url": "https://x/1",
                                             "source": "Gov", "jurisdiction": "UK", "date": "2099-01-01"}]}
            with open(out, "w") as f:
                json.dump(old, f)
            new = [{"id": "new1", "title": "New AI item", "url": "https://x/2",
                    "source": "Gov", "jurisdiction": "UK", "date": "2099-01-02"}]
            with mock.patch.object(tracker, "collect", return_value=(new, ["Gov kept 1"])), \
                 mock.patch.object(sys, "argv", ["tracker.py", "--out", out]):
                tracker.main()
            with open(out) as f:
                ids = [i["id"] for i in json.load(f)["items"]]
            self.assertEqual(ids, ["new1", "old1"])

            with mock.patch.object(tracker, "collect", return_value=([], ["Gov FAILED down"])), \
                 mock.patch.object(sys, "argv", ["tracker.py", "--out", out]):
                with self.assertRaises(SystemExit):
                    tracker.main()
            with open(out) as f:
                self.assertEqual(len(json.load(f)["items"]), 2)


if __name__ == "__main__":
    unittest.main()
