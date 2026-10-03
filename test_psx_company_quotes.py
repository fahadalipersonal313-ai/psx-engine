"""Minimal REG fixture derived from the public PRL page checked 2026-10-03."""
import unittest
from unittest.mock import Mock
from datetime import datetime, timezone

import psx_company_quotes as q

FETCHED = datetime(2026, 10, 3, 18, 30, tzinfo=timezone.utc)


def stat(label, value):
    return f'<div class="stats_item"><div class="stats_label">{label}</div><div class="stats_value">{value}</div></div>'


def fixture():
    fields = ''.join(stat(k, v) for k, v in [('Open', '91.30'), ('High', '92.70'),
        ('Low', '88.00'), ('Volume', '17,786,560'), ('LDCP', '91.22')])
    return ('<html><head><meta property="og:url" content="https://dps.psx.com.pk/company/PRL"></head><body>'
            '<div>Oct 3, 2026 11:30 PM</div><div class="quote__close">Rs.90.35</div>'
            '<div class="quote__date">^ As of Fri, Oct 2, 2026 4:49 PM</div>'
            '<div id="statsTab"><div class="tabs__panels"><div class="tabs__panel" data-name="REG">'
            + fields + '</div><div class="tabs__panel" data-name="FUT">'
            + stat('Open', '91.49') + stat('Close', '90.99') + stat('Volume', '13,389,000')
            + '<div>Last update: Fri, Oct 2, 2026 4:47 PM</div></div></div></div></body></html>')


class CompanyQuoteTests(unittest.TestCase):
    def test_dated_reg_snapshot(self):
        row = q.parse(fixture(), 'PRL', FETCHED)
        self.assertEqual(row['price'], 90.35)
        self.assertEqual(row['open'], 91.3)
        self.assertEqual(row['day_volume'], 17786560)
        self.assertEqual(row['prior_close'], 91.22)
        self.assertEqual(row['source_as_of'], '2026-10-02T16:49:00+05:00')
        self.assertEqual(row['session'], '2026-10-02')
        self.assertEqual(row['volume_kind'], 'cumulative_session')
        self.assertEqual(row['declared_delay_minutes'], 5)
        self.assertNotIn('last_trade', row)
        self.assertNotIn('ticks', row)
        self.assertGreater(row['source_age_seconds'], 86400)

    def test_futures_and_page_clock_cannot_change_reg(self):
        changed = fixture().replace('91.49', '1000').replace('13,389,000', '1').replace('Oct 3, 2026 11:30 PM', 'Jan 1, 2099 1:00 AM')
        self.assertEqual(q.parse(fixture(), 'PRL', FETCHED), q.parse(changed, 'PRL', FETCHED))

    def test_missing_or_malformed_source_date_rejected(self):
        for changed in [fixture().replace('quote__date', 'removed'),
                        fixture().replace('Fri, Oct 2, 2026 4:49 PM', 'yesterday'),
                        fixture().replace('Fri, Oct 2, 2026', 'Thu, Oct 2, 2026')]:
            with self.assertRaises(ValueError):
                q.parse(changed, 'PRL', FETCHED)

    def test_future_and_naive_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            q.parse(fixture(), 'PRL', '2026-10-02T10:00:00Z')
        with self.assertRaises(ValueError):
            q.parse(fixture(), 'PRL', '2026-10-03T18:00:00')

    def test_identity_missing_field_duplicate_and_invalid_numbers(self):
        variants = [fixture().replace('/company/PRL', '/company/PSO'),
                    fixture().replace('data-name="REG"', 'data-name="ODL"'),
                    fixture().replace('>LDCP<', '>MISSING<'),
                    fixture().replace('>LDCP<', '>Open<'),
                    fixture().replace('Rs.90.35', 'Rs.NaN'),
                    fixture().replace('Rs.90.35', 'Rs.100.00'),
                    fixture().replace('>91.22<', '>0.00<'),
                    fixture().replace('>17,786,560<', '>-1<')]
        for changed in variants:
            with self.subTest(changed=changed[-80:]):
                with self.assertRaises(ValueError):
                    q.parse(changed, 'PRL', FETCHED)

    def test_old_date_and_repeated_observation_not_relabelled(self):
        first = q.parse(fixture(), 'PRL', FETCHED)
        second = q.parse(fixture(), 'PRL', '2026-10-04T18:30:00Z')
        self.assertEqual(first['source_as_of'], second['source_as_of'])
        self.assertEqual(first['day_volume'], second['day_volume'])
        self.assertGreater(second['source_age_seconds'], first['source_age_seconds'])

    def test_collection_records_partial_failure(self):
        def fetcher(symbol):
            if symbol == 'PSO':
                raise ValueError('source unavailable')
            return q.parse(fixture(), symbol, FETCHED)
        result = q.collect(['PRL', 'PSO'], now=FETCHED, workers=1, fetcher=fetcher)
        self.assertEqual((result['available'], result['status']), (1, 'partial'))
        self.assertEqual(result['errors'][0]['symbol'], 'PSO')
        self.assertEqual(result['failed'], ['PSO'])
        self.assertEqual(result['prices'][0]['symbol'], 'PRL')
        self.assertEqual(result['checked_at'], FETCHED.isoformat())

    def test_http_refusal_not_retried(self):
        opener = Mock(side_effect=ValueError('HTTP 403'))
        with self.assertRaises(ValueError):
            q.fetch('PRL', opener=opener)
        self.assertEqual(opener.call_count, 1)

    def test_unapproved_symbol_rejected_before_network(self):
        opener = Mock()
        with self.assertRaises(ValueError):
            q.fetch('OTHER', opener=opener)
        opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
