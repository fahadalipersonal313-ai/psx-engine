import unittest
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

# The production workflow installs requests; unit tests exercise pure parsing
# and guard logic and therefore do not need the network package itself.


import news_claude
import news_feed
import news_fetcher
import mettis_scraper


class FreshnessTests(unittest.TestCase):
    def test_as_of_fails_closed(self):
        now = datetime(2026, 8, 30, 8, tzinfo=timezone.utc)
        self.assertEqual(news_feed._fresh_as_of({}, now)[1], "malformed")
        self.assertEqual(news_feed._fresh_as_of({"as_of": "bad"}, now)[1], "malformed")
        future = (now + timedelta(minutes=6)).isoformat()
        self.assertEqual(news_feed._fresh_as_of({"as_of": future}, now)[1], "future")
        stale = (now - timedelta(hours=25)).isoformat()
        self.assertEqual(news_feed._fresh_as_of({"as_of": stale}, now)[1], "stale")

    def test_missing_scoring_fields_are_rejected(self):
        incomplete = {"rating": "positive", "sources": ["https://example.test/a"]}
        self.assertFalse(news_feed._valid_scoring_rating(incomplete))
        complete = dict(incomplete, causality="causal", confidence=0.7)
        self.assertTrue(news_feed._valid_scoring_rating(complete))
        self.assertFalse(news_feed._valid_scoring_rating(dict(complete, confidence=True)))

    def test_noise_and_missing_news_cannot_move(self):
        noise = {"rating": "highly_positive", "causality": "noise", "confidence": 1.0,
                 "sources": ["https://example.test/a"]}
        with mock.patch.object(news_feed, "glm_rating", return_value=noise), \
             mock.patch.object(news_feed, "_rating_in_session", return_value=True):
            self.assertEqual(news_feed.news_score("PSO"), 50.0)
        with mock.patch.object(news_feed, "glm_rating", return_value=None):
            self.assertIsNone(news_feed.news_score("PSO"))


class ContractTests(unittest.TestCase):
    def test_digest_provenance_is_deterministic(self):
        evidence = {"PSO": [{"url": "https://example.test/a",
                              "published": "2026-08-30T06:00:00+00:00",
                              "depth": "full"}]}
        raw = {"PSO": {"rating": "positive", "reason": "direct margin benefit",
                       "causality": "causal", "confidence": 0.8,
                       "horizon": "single_session"}}
        result = news_claude._sanitize_group(raw, evidence)["PSO"]
        self.assertEqual(result["sources"], ["https://example.test/a"])
        self.assertEqual(result["text_depth"], "full")
        self.assertEqual(result["source_published"],
                         ["2026-08-30T06:00:00+00:00"])

    def test_empty_http_200_feed_is_a_failure(self):
        import xml.etree.ElementTree as ET
        failures = []
        with mock.patch.object(news_fetcher, "MACRO_FEEDS", [("Desk", "url")]), \
             mock.patch.object(news_fetcher, "_fetch_rss",
                               return_value=ET.fromstring("<rss><channel/></rss>")):
            self.assertEqual(news_fetcher.fetch_macro(datetime.now(timezone.utc), failures), [])
        self.assertEqual(failures, ["Desk:empty"])

    def test_mettis_drops_missing_publisher_title(self):
        class Match:
            def group(self, _):
                return "story-12345"
        class Pattern:
            @staticmethod
            def finditer(_):
                return [Match()]
        now = datetime.now(timezone.utc)
        with mock.patch.object(mettis_scraper, "LISTING_PAGES", [""]), \
             mock.patch.object(mettis_scraper, "_get", return_value="listing"), \
             mock.patch.object(mettis_scraper, "ARTICLE_RE", Pattern()), \
             mock.patch.object(mettis_scraper, "_article_meta",
                               return_value=(now, None)), \
             mock.patch.object(mettis_scraper.time, "sleep"):
            items, _ = mettis_scraper.fetch(now - timedelta(hours=1))
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
