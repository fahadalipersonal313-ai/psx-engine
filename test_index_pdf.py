import unittest
from unittest.mock import patch

import main
import psx_index_pdf as ip

PAGE = ("Pakistan Stock Exchange Limited\nCLOSING RATE SUMMARY\nFrom :09:30_AM_To_04:15_PM\n"
        "Tuesday September 29,2026\nPageNo: 1\nFlu No: 925/2026\n"
        "P. Vol.: 421015660 P.KSE100 Ind: 170425.62 P.KSE30 Ind: 50717.83 Plus: 154\n"
        "C. Vol.: 568040396 C.KSE100 Ind: 169600.41 C.KSE30 Ind: 50456.98 Minus: 305\n")


def row(day, close, prev):
    return {"date": day, "close": close, "prev_close": prev, "volume": 1.0}


class ParseTests(unittest.TestCase):
    def test_reads_current_and_previous_close(self):
        r = ip.parse(PAGE, "2026-09-29")
        self.assertEqual((r["close"], r["prev_close"], r["volume"]),
                         (169600.41, 170425.62, 568040396.0))

    def test_single_digit_day_matches(self):
        page = PAGE.replace("September 29,2026", "October 1,2026")
        self.assertEqual(ip.parse(page, "2026-10-01")["close"], 169600.41)

    def test_wrong_date_is_refused(self):
        with self.assertRaisesRegex(ValueError, "September 29,2026"):
            ip.parse(PAGE, "2026-09-28")

    def test_missing_index_line_is_refused(self):
        with self.assertRaisesRegex(ValueError, "layout changed"):
            ip.parse(PAGE.replace("C.KSE100", "C.XXX"), "2026-09-29")


class BackfillTests(unittest.TestCase):
    def test_chains_and_skips_weekend_and_holiday(self):
        data = {"2026-09-24": row("2026-09-24", 170498.95, 172232.51),
                "2026-09-28": row("2026-09-28", 170425.62, 170498.95),
                "2026-09-29": row("2026-09-29", 169600.41, 170425.62)}
        saved, asked = [], []
        fetch = lambda d: (asked.append(d), data.get(d))[1]
        out = ip.backfill("2026-09-24", "2026-09-29", fetch=fetch, save=saved.append,
                          last={"date": "2026-09-23", "close": 172232.51}, pause=0)
        self.assertEqual([r["date"] for r in saved], ["2026-09-24", "2026-09-28", "2026-09-29"])
        self.assertEqual(out["no_file"], ["2026-09-25"])
        self.assertNotIn("2026-09-26", asked)

    def test_chain_break_refuses_and_stops(self):
        data = {"2026-09-28": row("2026-09-28", 170425.62, 170000.00),
                "2026-09-29": row("2026-09-29", 169600.41, 170425.62)}
        saved = []
        with self.assertRaisesRegex(ValueError, "refusing"):
            ip.backfill("2026-09-28", "2026-09-29", fetch=data.get, save=saved.append,
                        last={"date": "2026-09-25", "close": 170498.95}, pause=0)
        self.assertEqual(saved, [])


class BankBenchmarkTests(unittest.TestCase):
    def test_up_to_date_does_nothing(self):
        with patch("database.get_eod_history", return_value=[{"date": "2026-09-29", "close": 1}]), \
             patch("psx_index_pdf.backfill") as bf:
            self.assertIsNone(main._bank_benchmark("2026-09-29"))
        bf.assert_not_called()

    def test_first_run_fetches_history(self):
        with patch("database.get_eod_history", return_value=[]), \
             patch("psx_index_pdf.backfill", return_value={"banked": [], "no_file": []}) as bf:
            main._bank_benchmark("2026-09-29")
        self.assertEqual(bf.call_args[0][:2], ("2026-05-02", "2026-09-29"))

    def test_failure_is_logged_not_raised(self):
        with patch("database.get_eod_history", return_value=[{"date": "2026-09-24", "close": 1}]), \
             patch("psx_index_pdf.backfill", side_effect=ValueError("x")):
            self.assertIsNone(main._bank_benchmark("2026-09-29"))


if __name__ == "__main__":
    unittest.main()
