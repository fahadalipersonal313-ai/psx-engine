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


class NewsMemoryTests(unittest.TestCase):
    """news_memory banks every read against an ISOLATED temp database; the
    tracked psx_engine.db is never touched (CLAUDE.md)."""

    def setUp(self):
        import tempfile, os, importlib
        import config, database
        self.tmp = tempfile.mkdtemp()
        self._old_db = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmp, "test.db")
        database.DB_PATH = config.DB_PATH
        database.init_db()
        self.ratings = os.path.join(self.tmp, "ratings.json")

    def tearDown(self):
        import shutil, config, database
        config.DB_PATH = self._old_db
        database.DB_PATH = self._old_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, blob):
        import json
        with open(self.ratings, "w", encoding="utf-8") as fh:
            json.dump(blob, fh)

    def test_remember_is_idempotent(self):
        import news_memory
        self._write({"as_of": "2026-09-09T09:00:00Z", "provider": "claude-routine",
                     "ratings": {"OGDC": {"rating": "positive", "causality": "causal",
                                          "confidence": 0.5, "horizon": "multi_session",
                                          "reason": "well online",
                                          "sources": ["https://x.test/a"]}}})
        self.assertEqual(news_memory.remember(self.ratings)["stored"], 1)
        self.assertEqual(news_memory.remember(self.ratings)["stored"], 0)
        self.assertEqual(len(news_memory.history_for("OGDC")), 1)

    def test_a_later_read_is_a_second_entry_not_an_overwrite(self):
        """The whole point: a running story keeps its earlier stages."""
        import news_memory
        base = {"rating": "positive", "causality": "causal", "confidence": 0.5,
                "horizon": "multi_session", "reason": "stage one",
                "sources": ["https://x.test/a"]}
        self._write({"as_of": "2026-09-01T09:00:00Z", "ratings": {"FTMM": base}})
        news_memory.remember(self.ratings)
        later = dict(base, reason="stage two", sources=["https://x.test/b"])
        self._write({"as_of": "2026-09-09T09:00:00Z", "ratings": {"FTMM": later}})
        news_memory.remember(self.ratings)
        hist = news_memory.history_for("FTMM")
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["reason"], "stage two")   # newest first
        self.assertIn("stage one", news_memory.thread_summary("FTMM"))

    def test_a_read_without_a_timestamp_is_refused(self):
        import news_memory
        self._write({"ratings": {"OGDC": {"rating": "positive"}}})
        out = news_memory.remember(self.ratings)
        self.assertEqual(out["stored"], 0)
        self.assertIn("as_of", out["reason"])

    def test_thread_summary_is_empty_when_nothing_is_known(self):
        import news_memory
        self.assertEqual(news_memory.thread_summary("NOSUCH"), "")
        self.assertEqual(news_memory.remembered_symbols(), [])

    def test_grade_measures_excess_over_the_cross_sectional_median(self):
        import news_memory, database, config
        days = [f"2026-06-{d:02d}" for d in range(1, 26)]
        # Rated name climbs 1%/session; the rest of the panel is flat, so the
        # median is 0 and the excess is the stock's own move.
        for i, d in enumerate(days):
            px = 100 * (1.01 ** i)
            database.save_hl_bar("OGDC", d, px, px, px, px, 1e7, "test")
            for peer in ("PSO", "MARI", "HUBC"):
                database.save_hl_bar(peer, d, 100, 100, 100, 100.0, 1e7, "test")
        old_stocks = config.STOCKS
        config.STOCKS = ["OGDC", "PSO", "MARI", "HUBC"]
        try:
            self._write({"as_of": "2026-06-02T09:00:00Z",
                         "ratings": {"OGDC": {"rating": "positive", "causality": "causal",
                                              "confidence": 0.6, "horizon": "multi_session",
                                              "reason": "r", "sources": ["https://x.test/a"]}}})
            news_memory.remember(self.ratings)
            self.assertEqual(news_memory.grade()["graded"], 1)
            row = news_memory.history_for("OGDC")[0]
            self.assertAlmostEqual(row["outcome_5d"], (1.01 ** 5 - 1) * 100, places=4)
            acc = news_memory.accuracy()
            self.assertEqual(acc["n"], 1)
            self.assertEqual(acc["causal"]["positive_5d"], 100.0)
        finally:
            config.STOCKS = old_stocks
