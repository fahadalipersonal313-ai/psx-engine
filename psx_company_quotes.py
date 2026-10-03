"""Dated, delayed REG snapshots from public PSX company pages.

The displayed quote timestamp is preserved separately from retrieval time.
Volume and OHLC describe the running session, never a 15-minute candle. This
adapter neither reconstructs ticks nor writes the engine's daily history.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import math
import re
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from research_contract import UNIVERSE

PKT = ZoneInfo('Asia/Karachi')
BASE = 'https://dps.psx.com.pk/company/'
MAX_BYTES = 2_000_000
USER_AGENT = 'PSXResearch/1.0 (public company quote availability check)'
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}


class _Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.parts = tag, dict(attrs), []

    def descendants(self):
        for part in self.parts:
            if isinstance(part, _Node):
                yield part
                yield from part.descendants()

    def text(self):
        return ' '.join(''.join(p.text() if isinstance(p, _Node) else p
                               for p in self.parts).split())


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].parts.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].parts.append(_Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].parts.append(data)


def _one(node, *, cls=None, attr=None, value=None):
    matches = [n for n in node.descendants()
               if (cls is None or cls in n.attrs.get('class', '').split())
               and (attr is None or n.attrs.get(attr) == value)]
    if len(matches) != 1:
        raise ValueError(f'Expected one {cls or attr}={value or ""}; found {len(matches)}')
    return matches[0]


def _stamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Retrieval timestamp needs timezone')
    return value.astimezone(timezone.utc)


def _number(text, positive=True):
    if not re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', text):
        raise ValueError('Invalid quote number: ' + text)
    value = float(text.replace(',', ''))
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError('Invalid quote value')
    return value


def parse(html, symbol, fetched_at=None):
    """Return one validated snapshot; missing identity/date/REG data raises.

    Old source dates are retained with their age, not made current by a fetch.
    The caller applies session, freshness and monotonic-observation policies.
    """
    if symbol not in UNIVERSE:
        raise ValueError('Symbol outside the approved 15-stock universe')
    if not isinstance(html, str) or len(html.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Invalid or oversized company page')
    fetched = _stamp(fetched_at or datetime.now(timezone.utc))
    page = _Page()
    page.feed(html)
    root = page.root
    identity = _one(root, attr='property', value='og:url')
    source_url = BASE + symbol
    if identity.attrs.get('content', '').rstrip('/') != source_url:
        raise ValueError('Company page identity does not match requested symbol')
    raw_price = _one(root, cls='quote__close').text()
    if not raw_price.startswith('Rs.'):
        raise ValueError('Missing PKR quote currency')
    price = _number(raw_price[3:].strip())
    raw_date = _one(root, cls='quote__date').text()
    date_match = re.fullmatch(r'\^?\s*As of\s+(.+)', raw_date)
    if not date_match:
        raise ValueError('Missing source quote timestamp')
    source_time = datetime.strptime(date_match[1], '%a, %b %d, %Y %I:%M %p').replace(tzinfo=PKT)
    if source_time.strftime('%a') != date_match[1].split(',')[0]:
        raise ValueError('Source quote weekday does not match date')
    if source_time > fetched:
        raise ValueError('Future source quote timestamp')
    stats = _one(root, attr='id', value='statsTab')
    reg = _one(stats, cls='tabs__panel', attr='data-name', value='REG')
    fields = {}
    required = {'Open', 'High', 'Low', 'Volume', 'LDCP'}
    for item in reg.descendants():
        if 'stats_item' not in item.attrs.get('class', '').split():
            continue
        labels = [n for n in item.descendants()
                  if 'stats_label' in n.attrs.get('class', '').split()]
        if len(labels) != 1 or labels[0].text() not in required:
            continue
        label = labels[0].text()
        if label in fields:
            raise ValueError('Duplicate REG statistic: ' + label)
        fields[label] = _number(_one(item, cls='stats_value').text(), positive=label != 'Volume')
    if set(fields) != required:
        raise ValueError('Missing REG statistics: ' + ', '.join(sorted(required - set(fields))))
    o, h, l = (fields[k] for k in ('Open', 'High', 'Low'))
    if not l <= min(o, price) <= max(o, price) <= h:
        raise ValueError('Inconsistent running-session OHLC')
    if not fields['Volume'].is_integer():
        raise ValueError('Share volume must be a whole number')
    return {
        'symbol': symbol, 'market': 'REG', 'price': price,
        'open': o, 'high': h, 'low': l, 'ldcp': fields['LDCP'],
        'prior_close': fields['LDCP'], 'day_volume': int(fields['Volume']),
        'change_pct': (price / fields['LDCP'] - 1) * 100,
        'volume_kind': 'cumulative_session', 'ohlc_kind': 'running_session',
        'source': 'PSX public company page', 'source_url': source_url,
        'source_as_of': source_time.isoformat(), 'timestamp_kind': 'displayed_quote_as_of',
        'fetched_at': fetched.isoformat(), 'session': source_time.date().isoformat(),
        'source_age_seconds': (fetched - source_time).total_seconds(),
        'declared_delay_minutes': 5, 'data_status': 'delayed_snapshot',
        'delay_source_url': 'https://dps.psx.com.pk/',
        'limitations': 'Running-session snapshot, not ticks or intraday candles; source timestamp is displayed quote time. No verified execution price or fill.',
    }


def fetch(symbol, *, timeout=30, opener=urlopen):
    """One ordinary public GET. No retries of refusals, authentication or bypass."""
    if symbol not in UNIVERSE:
        raise ValueError('Symbol outside the approved 15-stock universe')
    request = Request(BASE + symbol, headers={'User-Agent': USER_AGENT,
                                             'Accept': 'text/html'})
    with opener(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f'Company page HTTP {response.status}')
        if response.geturl().rstrip('/') != BASE + symbol:
            raise ValueError('Unexpected company page redirect')
        if 'text/html' not in response.headers.get('Content-Type', '').lower():
            raise ValueError('Company response is not HTML')
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Oversized company response')
    return parse(raw.decode('utf-8'), symbol, datetime.now(timezone.utc))


def collect(symbols=None, now=None, *, workers=2, fetcher=fetch):
    """Coverage/error envelope, preserving source time per stock. No file writes."""
    symbols = list(UNIVERSE if symbols is None else symbols)
    if not symbols or len(set(symbols)) != len(symbols) or any(s not in UNIVERSE for s in symbols):
        raise ValueError('Invalid or duplicate requested universe')
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('Workers must be 1..4')
    started = _stamp(now or datetime.now(timezone.utc)).isoformat()

    def one(symbol):
        try:
            row = fetcher(symbol)
            if row.get('symbol') != symbol:
                raise ValueError('Returned quote identity mismatch')
            return row, None
        except Exception as exc:
            return None, {'symbol': symbol, 'source_url': BASE + symbol,
                          'error': type(exc).__name__ + ': ' + str(exc)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, symbols))
    quotes = [r for r, _ in results if r is not None]
    errors = [e for _, e in results if e is not None]
    checked = _stamp(now or datetime.now(timezone.utc)).isoformat()
    return {'source': 'PSX public company pages', 'started_at': started,
            'fetched_at': checked, 'checked_at': checked, 'universe': symbols,
            'requested': len(symbols), 'available': len(quotes), 'prices': quotes,
            'failed': [e['symbol'] for e in errors], 'errors': errors,
            'status': 'snapshot_available' if not errors else ('partial' if quotes else 'unavailable'),
            'declared_delay_minutes': 5, 'note': 'Availability is not freshness. Use each source_as_of and session; no synthesized intraday candles.'}


if __name__ == '__main__':
    print(json.dumps(collect(), indent=2, allow_nan=False))
