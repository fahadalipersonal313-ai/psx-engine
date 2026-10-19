import json
import os
import tempfile
import unittest

import market_eod


def bar(sym, c, ldcp=None, flags=""):
    return {"symbol": sym, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 100.0, "ldcp": ldcp, "flags": flags}


class MarketEodTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "market_eod.json")

    def tearDown(self):
        self.dir.cleanup()

    def load(self):
        with open(self.path) as fh:
            return json.load(fh)

    def test_no_bars_writes_nothing(self):
        self.assertIsNone(market_eod.publish("2026-10-19", [], path=self.path, index_close=lambda d: 1.0))
        self.assertFalse(os.path.exists(self.path))

    def test_session_is_written_with_ldcp_and_index_close(self):
        out = market_eod.publish("2026-10-19", [bar("PRL", 108.81, 106.95, "XD")], path=self.path,
                                 index_close=lambda d: 165966.09)
        self.assertEqual(out["symbols"], 1)
        s = self.load()["sessions"]["2026-10-19"]
        self.assertEqual(s["kse100"], 165966.09)
        self.assertEqual(s["stocks"]["PRL"], [108.81, 109.81, 107.81, 108.81, 100.0, 106.95, "XD"])

    def test_missing_index_close_stays_null_and_is_filled_by_a_later_run(self):
        market_eod.publish("2026-10-19", [bar("PRL", 108.81)], path=self.path, index_close=lambda d: None)
        self.assertIsNone(self.load()["sessions"]["2026-10-19"]["kse100"])
        market_eod.publish("2026-10-19", [bar("PRL", 108.81)], path=self.path, index_close=lambda d: 165966.09)
        self.assertEqual(self.load()["sessions"]["2026-10-19"]["kse100"], 165966.09)

    def test_a_duplicated_ticker_is_refused_not_resolved(self):
        with self.assertRaisesRegex(ValueError, "more than once"):
            market_eod.publish("2026-10-19", [bar("PRL", 108.81), bar("PRL", 108.0)], path=self.path,
                               index_close=lambda d: 1.0)
        self.assertFalse(os.path.exists(self.path))

    def test_only_the_newest_sessions_are_kept(self):
        for i in range(1, 14):
            market_eod.publish("2026-10-%02d" % i, [bar("PRL", 100 + i)], path=self.path,
                               keep=10, index_close=lambda d: 1.0)
        days = sorted(self.load()["sessions"])
        self.assertEqual(len(days), 10)
        self.assertEqual(days[0], "2026-10-04")
        self.assertEqual(days[-1], "2026-10-13")

    def test_republishing_the_same_session_is_byte_identical(self):
        args = ("2026-10-19", [bar("PRL", 108.81), bar("ATRL", 1243.81)])
        market_eod.publish(*args, path=self.path, index_close=lambda d: 1.0)
        first = open(self.path, "rb").read()
        market_eod.publish(*args, path=self.path, index_close=lambda d: 1.0)
        self.assertEqual(first, open(self.path, "rb").read())


if __name__ == "__main__":
    unittest.main()
