import unittest

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
