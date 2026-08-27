"""Throwaway diagnostic: what does PSX DPS actually return to a GitHub runner?

The engine's own logs only record the stringified exception, and this sandbox
cannot reach the host at all (its egress proxy rejects the CONNECT), so the
runner is the only place the real status/headers can be observed. Delete after
the cause is identified.
"""
import socket
import ssl
import time

import requests

HOST = "dps.psx.com.pk"
PATHS = ["/timeseries/int/NRL", "/timeseries/eod/NRL"]
BOT = {"User-Agent": "PSX-Research-Engine/1.0 (personal research tool)"}
BROWSER = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"https://{HOST}/",
    "X-Requested-With": "XMLHttpRequest",
}
INTERESTING = ("server", "retry-after", "cf-ray", "cf-mitigated", "x-cache",
               "content-type", "set-cookie", "x-ratelimit-remaining")


def net_layer():
    print("== DNS / TCP / TLS")
    try:
        addrs = sorted({r[4][0] for r in socket.getaddrinfo(HOST, 443)})
        print(f"  DNS  {HOST} -> {addrs}")
    except Exception as e:
        print(f"  DNS  FAILED: {e}"); return
    try:
        t = time.time()
        with socket.create_connection((HOST, 443), timeout=15) as s:
            print(f"  TCP  connected in {time.time()-t:.2f}s")
            with ssl.create_default_context().wrap_socket(s, server_hostname=HOST) as ss:
                print(f"  TLS  {ss.version()} {ss.cipher()[0]}")
                cert = ss.getpeercert()
                print(f"  CERT subject={dict(x[0] for x in cert['subject']).get('commonName')} "
                      f"notAfter={cert.get('notAfter')}")
    except Exception as e:
        print(f"  TCP/TLS FAILED: {type(e).__name__}: {e}")


def probe(path, headers, label, attempts=3):
    print(f"\n== {path}  [{label}]")
    for i in range(1, attempts + 1):
        try:
            t = time.time()
            r = requests.get(f"https://{HOST}{path}", headers=headers, timeout=20)
            hdrs = {k.lower(): v for k, v in r.headers.items()
                    if k.lower() in INTERESTING}
            body = r.text[:200].replace("\n", " ")
            print(f"  #{i} HTTP {r.status_code} in {time.time()-t:.2f}s "
                  f"len={len(r.content)}")
            print(f"      headers {hdrs}")
            print(f"      body[:200] {body!r}")
        except Exception as e:
            print(f"  #{i} EXCEPTION {type(e).__name__}: {e}")
        time.sleep(3)


def engine_path():
    """Reproduce the ENGINE's exact call path: ssl_compat.enable() first.

    The plain-requests probe got HTTP 200 for everything while the engine got
    nothing, and this is the only difference between them — truststore replaces
    Python's TLS stack process-wide before any request is made.
    """
    print("\n== ENGINE PATH: ssl_compat.enable() then fetch")
    try:
        import ssl_compat
        ok = ssl_compat.enable()
        print(f"  ssl_compat.enable() -> {ok}")
    except Exception as e:
        print(f"  ssl_compat import/enable FAILED: {type(e).__name__}: {e}")
    import config
    print(f"  REQUEST_TIMEOUT={config.REQUEST_TIMEOUT} headers={config.REQUEST_HEADERS}")
    for path in PATHS:
        for i in (1, 2):
            try:
                t = time.time()
                r = requests.get(f"https://{HOST}{path}",
                                 headers=config.REQUEST_HEADERS,
                                 timeout=config.REQUEST_TIMEOUT)
                print(f"  {path} #{i} HTTP {r.status_code} in {time.time()-t:.2f}s "
                      f"len={len(r.content)}")
            except Exception as e:
                print(f"  {path} #{i} EXCEPTION {type(e).__name__}: {e}")
    # And the real function, so nothing about the wrapper is left untested.
    try:
        import data_fetcher
        q = data_fetcher.latest_quote("NRL")
        eod, meta = data_fetcher.fetch_eod("NRL")
        print(f"  data_fetcher.latest_quote -> price={q.get('price')} live={q.get('live')}")
        print(f"  data_fetcher.fetch_eod    -> rows={None if eod is None else len(eod)} "
              f"live={meta.get('live')} warning={str(meta.get('warning'))[:160]}")
    except Exception as e:
        print(f"  data_fetcher FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    net_layer()
    for p in PATHS:
        probe(p, BOT, "engine bot UA")
        probe(p, BROWSER, "browser UA + Referer")
    # Does volume itself trip it? 20 rapid symbols, as one cycle would.
    print("\n== burst: 20 rapid EOD calls (browser UA), status only")
    syms = ["NRL","PSO","MEBL","OGDC","PPL","LUCK","FFC","MARI","ATRL","PRL",
            "DGKC","MLCF","FCCL","HUBC","SSGC","SNGP","EFERT","POL","TREET","SYS"]
    out = []
    for s in syms:
        try:
            r = requests.get(f"https://{HOST}/timeseries/eod/{s}",
                             headers=BROWSER, timeout=20)
            out.append(f"{s}:{r.status_code}")
        except Exception as e:
            out.append(f"{s}:{type(e).__name__}")
    print("  " + " ".join(out))
    engine_path()
