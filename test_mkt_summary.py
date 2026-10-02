import unittest
from unittest import mock

import psx_mkt_summary as ms

SAMPLE = ("29SEP2026|786|0813|786 Invest Ltd|21.21|21.71|19.85|21.14|65265|21.21|||\r\n"
          "29SEP2026|AABS|0826|Al-Abbas Sugar|777.0|787.99|761|774.98|172|783.09|||\r\n"
          "29SEP2026|OGDC XD|0823|Oil & Gas Dev|321.0|323.9|317.5|318.69|1,234,567|319.53|||\r\n"
          "29SEP2026|DEAD|0801|Untraded Co|0.00|0.00|0.00|12.5|0|12.5|||\r\n")


class MktSummaryParse(unittest.TestCase):
    def test_fields_map_to_open_high_low_close_volume(self):
        bars = {b["symbol"]: b for b in ms.parse(SAMPLE, "2026-09-29")}
        self.assertEqual(bars["AABS"], {"symbol": "AABS", "open": 777.0, "high": 787.99,
                                        "low": 761.0, "close": 774.98, "volume": 172.0})

    def test_status_markers_are_not_part_of_the_symbol(self):
        bars = {b["symbol"]: b for b in ms.parse(SAMPLE, "2026-09-29")}
        self.assertIn("OGDC", bars)
        self.assertEqual(bars["OGDC"]["volume"], 1234567.0)   # thousands separators

    def test_a_session_with_no_trades_is_not_a_price(self):
        """O=H=L=0 with only a stale close is dropped, as in psx_historical."""
        self.assertNotIn("DEAD", {b["symbol"] for b in ms.parse(SAMPLE, "2026-09-29")})

    def test_a_file_for_another_date_is_refused_not_misfiled(self):
        with self.assertRaisesRegex(ValueError, "different date"):
            ms.parse(SAMPLE, "2026-09-28")

    def test_a_changed_format_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "format has changed"):
            ms.parse("Symbol,Open,High\nOGDC,1,2\n", "2026-09-29")

    def test_empty_file_is_an_empty_session(self):
        self.assertEqual(ms.parse("", "2026-09-29"), [])

    def test_the_real_download_is_a_zip_and_is_unpacked(self):
        """PSX serves mkt_summary .Z as a ZIP holding closing11.lis."""
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("closing11.lis", SAMPLE)
        text = ms._body(buf.getvalue()).decode("latin-1")
        bars = {b["symbol"] for b in ms.parse(text, "2026-09-29")}
        self.assertEqual(bars, {"786", "AABS", "OGDC"})

    def test_lzw_compressed_file_is_refused_with_a_reason(self):
        with self.assertRaisesRegex(ValueError, "LZW"):
            ms._body(b"\x1f\x9d\x90abc")

    def test_source_label_ranks_as_an_official_bar(self):
        from data_quality import source_priority
        self.assertEqual(source_priority(ms.SOURCE), 3)


class MktSummaryBackfill(unittest.TestCase):
    def test_backfill_skips_weekends_and_records_missing_files(self):
        calls, saved = [], []
        def fake_fetch(day):
            calls.append(day)
            return [] if day == "2026-09-28" else [
                {"symbol": "OGDC", "open": 1.0, "high": 2.0, "low": 0.5,
                 "close": 1.5, "volume": 10.0},
                {"symbol": "NOTTRACKED", "open": 1.0, "high": 2.0, "low": 0.5,
                 "close": 1.5, "volume": 10.0}]
        orig = ms.fetch_day
        ms.fetch_day = fake_fetch
        try:
            out = ms.backfill("2026-09-25", "2026-09-29", symbols=["OGDC"],
                              save=lambda *a, **k: saved.append(a), pause=0)
        finally:
            ms.fetch_day = orig
        # Fri 25, [Sat 26, Sun 27 skipped], Mon 28 (no file), Tue 29
        self.assertEqual(calls, ["2026-09-25", "2026-09-28", "2026-09-29"])
        self.assertEqual(out["no_file"], ["2026-09-28"])
        self.assertEqual(set(out["banked"]), {"2026-09-25", "2026-09-29"})
        self.assertTrue(all(a[0] == "OGDC" for a in saved))   # untracked never saved
        self.assertTrue(all(a[7] == ms.SOURCE for a in saved))


if __name__ == "__main__":
    unittest.main()


class SessionGapFill(unittest.TestCase):
    """main._fill_session_gap banks the sessions an outage skipped."""

    def test_gap_between_last_banked_bar_and_cutoff_is_filled(self):
        import tempfile, os, config, database, main
        from unittest import mock
        tmp = tempfile.mkdtemp()
        with mock.patch.object(config, "DB_PATH", os.path.join(tmp, "t.db")), \
             mock.patch.object(config, "STOCKS", ["OGDC"]):
            database.init_db()
            database.save_hl_bar("OGDC", "2026-09-23", 1, 2, 0.5, 1.5, 10, ms.SOURCE)
            seen = {}
            def fake_backfill(start, end, *a, **k):
                seen["range"] = (start, end)
                return {"banked": {}, "no_file": []}
            with mock.patch.object(ms, "backfill", fake_backfill):
                main._fill_session_gap("2026-09-29")
        self.assertEqual(seen["range"], ("2026-09-24", "2026-09-28"))

    def test_no_gap_means_no_request(self):
        import tempfile, os, config, database, main
        from unittest import mock
        tmp = tempfile.mkdtemp()
        with mock.patch.object(config, "DB_PATH", os.path.join(tmp, "t.db")), \
             mock.patch.object(config, "STOCKS", ["OGDC"]):
            database.init_db()
            database.save_hl_bar("OGDC", "2026-09-28", 1, 2, 0.5, 1.5, 10, ms.SOURCE)
            with mock.patch.object(ms, "backfill", side_effect=AssertionError("called")):
                self.assertIsNone(main._fill_session_gap("2026-09-29"))

    def test_an_implausibly_long_gap_is_refused_not_hammered(self):
        import tempfile, os, config, database, main
        from unittest import mock
        tmp = tempfile.mkdtemp()
        with mock.patch.object(config, "DB_PATH", os.path.join(tmp, "t.db")), \
             mock.patch.object(config, "STOCKS", ["OGDC"]):
            database.init_db()
            database.save_hl_bar("OGDC", "2026-01-05", 1, 2, 0.5, 1.5, 10, ms.SOURCE)
            with mock.patch.object(ms, "backfill", side_effect=AssertionError("called")):
                self.assertIsNone(main._fill_session_gap("2026-09-29"))


class RetryTests(unittest.TestCase):
    def _session(self, outcomes):
        calls = []
        class S:
            def get(self, url, **kw):
                calls.append(url)
                o = outcomes.pop(0)
                if isinstance(o, Exception):
                    raise o
                return o
        return S(), calls

    def test_dropped_connection_is_retried_once(self):
        import requests, psx_mkt_summary as m
        s, calls = self._session([requests.ConnectionError("closed"), "ok"])
        with mock.patch("psx_mkt_summary.time.sleep") as sl:
            self.assertEqual(m.get_with_retry(s, "u"), "ok")
        self.assertEqual(len(calls), 2)
        sl.assert_called_once()

    def test_second_failure_raises(self):
        import requests, psx_mkt_summary as m
        s, calls = self._session([requests.Timeout("t"), requests.ConnectionError("c")])
        with mock.patch("psx_mkt_summary.time.sleep"), self.assertRaises(requests.ConnectionError):
            m.get_with_retry(s, "u")
        self.assertEqual(len(calls), 2)

    def test_http_refusal_is_not_retried(self):
        import psx_mkt_summary as m
        class R:
            status_code = 403
        s, calls = self._session([R()])
        self.assertEqual(m.get_with_retry(s, "u").status_code, 403)
        self.assertEqual(len(calls), 1)
