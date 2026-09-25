"""Ask PSX, once per endpoint, exactly what the engine asks -- and record the answer.

Read-only and deliberately NOT a workaround. It sends the engine's own
requests, with the engine's own headers, and never retries, varies headers or
disguises itself. Our rule is public permitted sources and no protection
bypass, so the point is to learn what PSX now returns, not to get past it.

What the answer means:
  every endpoint 403, a WAF/CDN header present  -> the runner is being blocked
  404s but the site home page loads             -> PSX moved or retired URLs
  timeouts / connection errors                  -> network or DNS, not PSX policy
  200s                                          -> transient; resume the engine
"""
import os
import socket
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import config
import psx_historical

INTERESTING = ("server", "cf-ray", "cf-cache-status", "x-cache", "via",
               "x-amz-cf-id", "x-akamai-transformed", "x-sucuri-id",
               "retry-after", "content-type", "location", "set-cookie")

PROBES = [
    ("GET",  "site home",       "https://dps.psx.com.pk/", config.REQUEST_HEADERS, None),
    ("GET",  "public site",     "https://www.psx.com.pk/", config.REQUEST_HEADERS, None),
    ("POST", "historical day",  psx_historical.URL, psx_historical.HEADERS,
     {"date": "2026-09-24"}),
    ("GET",  "market watch",    config.PSX_DPS_BASE + "/market-watch", config.REQUEST_HEADERS, None),
    ("GET",  "EOD index KMI30", config.PSX_DPS_BASE + "/timeseries/eod/KMI30", config.REQUEST_HEADERS, None),
    ("GET",  "EOD stock PSO",   config.PSX_DPS_BASE + "/timeseries/eod/PSO", config.REQUEST_HEADERS, None),
    ("GET",  "intraday PSO",    config.PSX_INTRADAY_URL.format(symbol="PSO"), config.REQUEST_HEADERS, None),
]


def main():
    host = urlparse(config.PSX_DPS_BASE).hostname
    try:
        print(f"DNS {host} -> {sorted({a[4][0] for a in socket.getaddrinfo(host, 443)})}")
    except OSError as exc:
        print(f"DNS {host} FAILED: {exc}")
    try:
        ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
        print(f"runner egress IP: {ip}")
    except requests.RequestException:
        print("runner egress IP: unknown")
    print()
    for method, label, url, headers, data in PROBES:
        print(f"=== {label}: {method} {url}")
        try:
            r = requests.request(method, url, headers=headers, data=data,
                                 timeout=30, allow_redirects=False)
        except requests.RequestException as exc:
            print(f"    ERROR {type(exc).__name__}: {exc}\n")
            continue
        print(f"    status {r.status_code} {r.reason} | {len(r.content)} bytes")
        for k in INTERESTING:
            if k in r.headers:
                v = r.headers[k]
                print(f"    {k}: {v[:120]}")
        body = r.text[:240].replace("\n", " ").strip()
        print(f"    body: {body}\n")


if __name__ == "__main__" and "--discover" not in sys.argv:
    main()


# ---------------------------------------------------------------------------
# Discovery: where did the data endpoints go?
#
# Reads PSX's PUBLIC pages exactly as a visitor's browser would, once each, and
# lists the data-looking paths they reference -- in page links and in the
# site's own JavaScript. These are PSX's published addresses; nothing is
# guessed, brute-forced or submitted.
#
# For the historical form it GETs the page and reports the form's field NAMES
# only, including whether a one-time token field exists. It never submits the
# form. Whether to use such a token is the operator's decision under the
# no-protection-bypass rule, not this tool's.
# ---------------------------------------------------------------------------
import re
from urllib.parse import urljoin

DATA_HINT = re.compile(
    r"""["'`](/[A-Za-z0-9_\-./{}$:]*?(?:timeseries|historical|market|eod|intraday|"""
    r"""trades?|quote|symbol|company|data|api|chart|index|indices|summary)"""
    r"""[A-Za-z0-9_\-./{}$:?=&]*)["'`]""", re.I)
MAX_SCRIPTS = 12


def _paths(text):
    return sorted({m.group(1) for m in DATA_HINT.finditer(text)
                   if not m.group(1).endswith((".css", ".png", ".jpg", ".svg", ".woff", ".woff2"))})


def discover():
    base = config.PSX_DPS_BASE + "/"
    print(f"=== DISCOVERY from {base}")
    home = requests.get(base, headers=config.REQUEST_HEADERS, timeout=30)
    print(f"home: {home.status_code}, {len(home.content)} bytes")
    found = set(_paths(home.text))
    nav = sorted({h for h in re.findall(r'href="(/[^"#?]+)"', home.text)
                  if not h.endswith((".css", ".png", ".ico", ".svg"))})
    print(f"\n-- {len(nav)} page links on the home page:")
    for h in nav[:80]:
        print(f"   {h}")
    scripts = [urljoin(base, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', home.text)]
    scripts = [s for s in scripts if "psx.com.pk" in s][:MAX_SCRIPTS]
    print(f"\n-- reading {len(scripts)} of the site's own scripts")
    for src in scripts:
        try:
            r = requests.get(src, headers=config.REQUEST_HEADERS, timeout=30)
            p = _paths(r.text)
            print(f"   {r.status_code} {src.split('psx.com.pk')[-1][:70]}  ({len(p)} data paths)")
            found.update(p)
        except requests.RequestException as exc:
            print(f"   ERROR {src}: {exc}")
    print(f"\n-- {len(found)} data-looking paths referenced by PSX's own pages/scripts:")
    for p in sorted(found)[:150]:
        print(f"   {p}")

    print("\n=== historical form (GET only, never submitted)")
    r = requests.get(psx_historical.URL, headers=config.REQUEST_HEADERS, timeout=30)
    print(f"GET {psx_historical.URL}: {r.status_code}, {len(r.content)} bytes")
    for form in re.findall(r"<form\b.*?</form>", r.text, re.S | re.I)[:3]:
        head = re.search(r"<form\b[^>]*>", form, re.I).group(0)
        names = re.findall(r'name="([^"]+)"', form)
        tokenish = [n for n in names if re.search(r"csrf|token|_token|nonce|captcha", n, re.I)]
        print(f"   form: {head[:160]}")
        print(f"   field names: {names}")
        print(f"   token-like fields: {tokenish or 'none'}")
    metas = re.findall(r'<meta[^>]+name="(csrf[^"]*)"', r.text, re.I)
    if metas:
        print(f"   page-level token meta tags: {metas}")


if __name__ == "__main__" and "--discover" in sys.argv:
    discover()
