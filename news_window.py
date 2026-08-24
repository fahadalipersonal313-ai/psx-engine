"""Is the PSX news routine allowed to run right now?

Gate for the hourly news cron. GitHub cron fires in UTC and cannot express
"weekdays, session hours only, except holidays", so the schedule is deliberately
loose and this module makes the real decision. Exits the workflow early rather
than fetching outside the session.
"""
import datetime
import sys

import config

PKT = datetime.timezone(datetime.timedelta(hours=5))


def pkt_now():
    # Pakistan is UTC+5 year-round (no DST), and runners/containers are UTC —
    # datetime.now() without this offset puts every session time before the open.
    return datetime.datetime.now(PKT)


def _hhmm(s):
    h, m = s.split(":")
    return datetime.time(int(h), int(m))


def check(now=None):
    """Return (ok: bool, reason: str). Reason is logged either way."""
    now = now or pkt_now()
    stamp = now.strftime("%Y-%m-%d %H:%M PKT")

    if now.weekday() >= 5:
        return False, f"{stamp}: weekend ({now:%A}) — PSX closed"

    if now.strftime("%Y-%m-%d") in set(config.PSX_HOLIDAYS):
        return False, f"{stamp}: PSX trading holiday"

    key = "fri" if now.weekday() == 4 else "mon_thu"
    start, end = (_hhmm(t) for t in config.NEWS_WINDOW[key])
    if not (start <= now.time() <= end):
        return False, (f"{stamp}: outside the {key} news window "
                       f"{start:%H:%M}-{end:%H:%M}")

    return True, f"{stamp}: inside the {key} window {start:%H:%M}-{end:%H:%M}"


if __name__ == "__main__":
    ok, reason = check()
    print(reason)
    sys.exit(0 if ok else 1)
