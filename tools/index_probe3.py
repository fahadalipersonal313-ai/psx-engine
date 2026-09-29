"""Does /indices/KMI30 carry dated history? Read-only."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests, config
r = requests.get("https://dps.psx.com.pk/indices/KMI30", headers=config.REQUEST_HEADERS, timeout=30)
t = re.sub(r"\s+", " ", r.text)
print("status", r.status_code, len(t))
print("dates found:", sorted(set(re.findall(r"(?:20\d\d-\d\d-\d\d|[A-Z][a-z]{2} \d{1,2}, 20\d\d|\d{1,2}-[A-Z][a-z]{2}-20\d\d)", t)))[:20])
print("head:", t[:1500])
print("... tail:", t[-1200:])
