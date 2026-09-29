"""Inspect two official PSX pages/files for KMI30 closes. Read-only."""
import io, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests, config
UA = config.REQUEST_HEADERS

r = requests.get("https://dps.psx.com.pk/indices", headers=UA, timeout=30)
t = r.text
for m in list(re.finditer(r"KMI30", t))[:3]:
    s = t[max(0, m.start() - 300): m.end() + 700]
    print("=== /indices around KMI30:\n", re.sub(r"\s+", " ", s), "\n")

r = requests.get("https://dps.psx.com.pk/indices/KMI30", headers=UA, timeout=30)
print("=== /indices/KMI30 title:", re.findall(r"<title>(.*?)</title>", r.text, re.S)[:1])
print("    numbers near 'close|value|current':",
      re.findall(r"(?:close|value|current|index)[^<]{0,40}?([0-9]{2,3},?[0-9]{3}\.[0-9]{2})", r.text, re.I)[:8])
print("    script srcs:", re.findall(r'<script[^>]+src="([^"]+)"', r.text)[:6])

from pypdf import PdfReader
for day in ("2026-09-29", "2026-09-24"):
    x = requests.get(f"https://dps.psx.com.pk/download/closing_rates/{day}.pdf", headers=UA, timeout=60)
    print(f"\n=== closing_rates {day}: {x.status_code} {len(x.content)}b")
    if x.status_code != 200:
        continue
    pdf = PdfReader(io.BytesIO(x.content))
    first = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    print(f"    pages: {len(pdf.pages)}")
    for line in first.splitlines():
        if re.search(r"KMI|KSE|ALLSHR|INDEX", line, re.I):
            print("   ", line[:160])
    print("    head:", first[:500].replace("\n", " | "))
