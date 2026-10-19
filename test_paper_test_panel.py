import unittest

import paper_test_panel as pp

STATUS = {
    "updated_pkt": "2026-10-20T16:45+05:00", "official_through": "2026-10-19", "official_note": "No new official session",
    "last_scan": {"date": "2026-10-19", "orders_placed": 0,
                  "gates": {"kse100": 165966.09, "low20": 164776.44, "gate1_level": 169719.74, "bounce_pct": 0.72,
                            "gate1_open": False, "breadth": 23.6, "breadth_prev": 16.29,
                            "breadth_prev_date": "2026-10-12", "gate2_open": True},
                  "signals": [{"book": "B", "sym": "PRL", "list": "Shariah", "signal_close": 108.81, "stop": 92.2, "atr": 5.5}]},
    "orders": [], "positions": [], "closed": {"n": 0}, "live": {"ok": False, "error": "403"},
}


class PaperTestPanel(unittest.TestCase):
    def test_missing_status_is_shown_as_unavailable(self):
        self.assertIsNone(pp.summarize(None))
        self.assertIsNone(pp.summarize({"official_through": "2026-10-19"}))

    def test_gates_are_described_from_the_status_only(self):
        s = pp.summarize(STATUS)
        self.assertFalse(s["gate1"]["open"])
        self.assertIn("169,720", s["gate1"]["text"])
        self.assertIn("164,776", s["gate1"]["text"])
        self.assertTrue(s["gate2"]["open"])
        self.assertIn("24% of Shariah stocks", s["gate2"]["text"])
        self.assertIn("12 Oct 2026", s["gate2"]["text"])
        self.assertIn("buys nothing", s["verdict"])
        self.assertEqual(s["through"], "19 Oct 2026")

    def test_signal_rows_and_no_live_line_when_live_failed(self):
        s = pp.summarize(STATUS)
        self.assertEqual(s["signals"][0]["Stock"], "PRL")
        self.assertEqual(s["signals"][0]["Risk %"], 15.3)
        self.assertEqual(s["live"], "")
        self.assertEqual(s["problem"], "")
        self.assertIn("judged after 30", s["closed"])

    def test_orders_positions_and_problems_are_passed_through(self):
        st = dict(STATUS, official_note="OFFICIAL DATA UNAVAILABLE: 404",
                  orders=[{"book": "B", "sym": "ATRL", "signal_close": 1252.0, "stop": 1156.0, "atr": 30.0}],
                  positions=[{"book": "B", "sym": "NRL", "entry_date": "2026-10-21", "entry": 690.0, "stop": 640.0,
                              "last_close": 700.0, "days": 2, "shares": 50}],
                  closed={"n": 2, "total_R": 1.5, "pf": 2.5, "win_pct": 50, "pnl_rs": 3750})
        st["last_scan"] = dict(STATUS["last_scan"], gates=dict(STATUS["last_scan"]["gates"], gate1_open=True))
        s = pp.summarize(st)
        self.assertIn("1 paper order", s["verdict"])
        self.assertEqual(s["orders"][0]["Won't buy above"], 1261.0)
        self.assertEqual(s["positions"][0]["Bought"], "21 Oct 2026")
        self.assertIn("2 closed: total +1.50R, profit factor 2.5, 50% winners, Rs +3,750", s["closed"])
        self.assertIn("could not read PSX's official end-of-day file", s["problem"])
        self.assertTrue(s["problem_detail"].startswith("OFFICIAL DATA UNAVAILABLE"))

    def test_fetch_reads_the_paper_trading_branch(self):
        import remote_data
        seen = {}

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return STATUS

        def get(url, **kw):
            seen["url"] = url
            return R()
        remote_data.clear_json_cache()
        self.assertEqual(pp.fetch_status(get=get), STATUS)
        self.assertIn("/paper-trading/state/status.json", seen["url"])
        remote_data.clear_json_cache()


if __name__ == "__main__":
    unittest.main()
