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


if __name__ == "__main__":
    main()
