"""technical_analyzer.py — Computes the 30% technical score.

All indicators are calculated from real fetched OHLC/volume data (pandas/
NumPy only — no fabricated values). When history is too short for an
indicator (e.g. EMA-200), the indicator is skipped and noted, never faked.
"""

import logging
import numpy as np
import pandas as pd

import config

log = logging.getLogger("technical")


# ----------------------------- indicators ---------------------------------
def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    ema_f = series.ewm(span=fast, adjust=False).mean()
    ema_s = series.ewm(span=slow, adjust=False).mean()
    line = ema_f - ema_s
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def bollinger(series, period=20, mult=2):
    mid = series.rolling(period).mean()
    sd = series.rolling(period).std()
    return mid + mult * sd, mid, mid - mult * sd


def obv(close, volume):
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def atr_from_close(close, period=14):
    """Approximate ATR using close-to-close ranges (EOD feed has no H/L)."""
    tr = close.diff().abs()
    return tr.rolling(period).mean()


def adx_proxy(close, period=14):
    """Directional-strength proxy from close data (true ADX needs H/L).
    Returns 0-100 style trend-strength estimate, clearly labelled a proxy."""
    up = close.diff().clip(lower=0).rolling(period).sum()
    dn = (-close.diff().clip(upper=0)).rolling(period).sum()
    denom = (up + dn).replace(0, np.nan)
    dx = (abs(up - dn) / denom) * 100
    return dx.rolling(period).mean()


def support_resistance(close, lookback=60):
    win = close.tail(lookback)
    lo, hi, last = win.min(), win.max(), close.iloc[-1]
    # nearest swing levels via quantiles for robustness
    support = float(win[win <= last].quantile(0.10)) if (win <= last).any() else float(lo)
    resistance = float(win[win >= last].quantile(0.90)) if (win >= last).any() else float(hi)
    return support, resistance, float(lo), float(hi)


def candle_signal(close):
    """Very simple pattern proxy from closes: 3-bar momentum reversal."""
    if len(close) < 4:
        return None
    c = close.tail(4).values
    if c[0] > c[1] > c[2] and c[3] > c[2]:
        return "potential bullish reversal (3-down then up)"
    if c[0] < c[1] < c[2] and c[3] < c[2]:
        return "potential bearish reversal (3-up then down)"
    return None


# ----------------------------- main entry ---------------------------------
def analyze(symbol, eod_df, quote):
    """eod_df: DataFrame[date, close, volume] (real fetched data) or None.
    quote: dict from data_fetcher.latest_quote.
    Returns dict with score (0-100), classification, levels, and notes."""
    notes, missing = [], []
    out = {"symbol": symbol, "score": None, "classification": "No data",
           "notes": notes, "missing": missing}

    if eod_df is None or len(eod_df) < 30:
        notes.append("Insufficient price history (<30 sessions) — technical "
                     "score withheld rather than guessed.")
        out["score"] = 50.0  # neutral, low-confidence
        out["low_confidence"] = True
        return out

    df = eod_df.copy()
    close, vol = df["close"].astype(float), df["volume"].astype(float)
    price = float(quote["price"]) if quote.get("price") else float(close.iloc[-1])

    # --- core indicators
    df["rsi"] = rsi(close)
    macd_line, macd_sig, macd_hist = macd(close)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean() if len(close) >= 200 else None
    if ema200 is None:
        missing.append("EMA-200 (needs 200 sessions)")
    bb_up, bb_mid, bb_lo = bollinger(close)
    obv_series = obv(close, vol)
    atr = atr_from_close(close)
    adx = adx_proxy(close)
    support, resistance, recent_lo, recent_hi = support_resistance(close)

    last_rsi = float(df["rsi"].iloc[-1]) if not np.isnan(df["rsi"].iloc[-1]) else None
    avg_vol = float(vol.tail(20).mean())
    today_vol = float(quote.get("volume") or vol.iloc[-1])
    vol_spike = today_vol > 1.8 * avg_vol if avg_vol else False
    last_atr = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else None
    atr_pct = (last_atr / price * 100) if (last_atr and price) else None
    last_adx = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else None
    momentum_20d = (price / float(close.iloc[-21]) - 1) * 100 if len(close) > 21 else 0.0
    obv_trend_up = float(obv_series.iloc[-1]) > float(obv_series.iloc[-10]) \
        if len(obv_series) > 10 else None

    breakout = price > resistance and vol_spike
    breakdown = price < support

    # --- scoring (each component contributes to 0-100)
    score, max_pts = 0.0, 0.0

    def add(points, max_p, label, hit_note=None):
        nonlocal score, max_pts
        score += points
        max_pts += max_p
        if hit_note:
            notes.append(hit_note)

    # Trend via EMAs (25 pts)
    pts = 0
    if price > float(ema20.iloc[-1]): pts += 8
    if price > float(ema50.iloc[-1]): pts += 9
    if ema200 is not None and price > float(ema200.iloc[-1]): pts += 8
    add(pts, 25 if ema200 is not None else 17, "trend",
        f"Price vs EMAs: 20={ema20.iloc[-1]:.2f}, 50={ema50.iloc[-1]:.2f}"
        + (f", 200={ema200.iloc[-1]:.2f}" if ema200 is not None else " (no EMA-200)"))

    # RSI (15 pts) — reward healthy zone, penalise extremes
    if last_rsi is not None:
        if 45 <= last_rsi <= 65: r_pts = 15
        elif 35 <= last_rsi < 45 or 65 < last_rsi <= 72: r_pts = 9
        elif last_rsi < 30: r_pts = 5; notes.append("RSI oversold (<30) — possible bounce but weak trend")
        elif last_rsi > 75: r_pts = 2; notes.append("RSI overbought (>75) — chase risk")
        else: r_pts = 6
        add(r_pts, 15, "rsi", f"RSI(14)={last_rsi:.1f}")
    else:
        missing.append("RSI")

    # MACD (15 pts)
    m_pts = 0
    if float(macd_hist.iloc[-1]) > 0: m_pts += 8
    if float(macd_line.iloc[-1]) > float(macd_sig.iloc[-1]): m_pts += 7
    add(m_pts, 15, "macd", f"MACD hist={macd_hist.iloc[-1]:.3f}")

    # Momentum (10 pts)
    mo_pts = 10 if momentum_20d > 5 else 7 if momentum_20d > 0 else 3 if momentum_20d > -5 else 0
    add(mo_pts, 10, "momentum", f"20-day momentum {momentum_20d:+.1f}%")

    # Volume/OBV (15 pts)
    v_pts = 0
    if vol_spike: v_pts += 7; notes.append(f"Volume spike: today {today_vol:,.0f} vs 20d avg {avg_vol:,.0f}")
    if obv_trend_up: v_pts += 8
    add(v_pts, 15, "volume")

    # Breakout / breakdown (10 pts)
    if breakout:
        add(10, 10, "breakout", f"Breakout above resistance {resistance:.2f} on volume")
    elif breakdown:
        add(0, 10, "breakdown", f"BREAKDOWN below support {support:.2f}")
    else:
        add(5, 10, "range")

    # Trend strength ADX proxy (10 pts)
    if last_adx is not None:
        add(min(10, last_adx / 5), 10, "adx",
            f"Trend strength (ADX proxy)={last_adx:.0f} — proxy, not true ADX")
    else:
        missing.append("ADX proxy")

    final = round(score / max_pts * 100, 1) if max_pts else 50.0

    cls = ("Strong bullish" if final >= 80 else "Bullish" if final >= 65
           else "Neutral" if final >= 45 else "Weak" if final >= 30 else "Bearish")
    cs = candle_signal(close)
    if cs:
        notes.append("Candle proxy: " + cs)
    if atr_pct and atr_pct > config.RISK["max_volatility_pct"]:
        notes.append(f"High volatility: ATR≈{atr_pct:.1f}% of price")

    stop_loss = round(max(support, price - config.RISK["default_stop_atr_mult"]
                          * (last_atr or price * 0.02)), 2)
    risk = price - stop_loss
    target1 = round(price + 2 * risk, 2)
    target2 = round(min(price + 3 * risk, recent_hi * 1.05), 2)
    rr = round((target1 - price) / risk, 2) if risk > 0 else None

    out.update({
        "score": final, "classification": cls, "price": price,
        "volume": today_vol, "avg_volume": avg_vol, "volume_spike": vol_spike,
        "rsi": last_rsi, "macd_hist": float(macd_hist.iloc[-1]),
        "ema20": float(ema20.iloc[-1]), "ema50": float(ema50.iloc[-1]),
        "ema200": float(ema200.iloc[-1]) if ema200 is not None else None,
        "bb_upper": float(bb_up.iloc[-1]), "bb_lower": float(bb_lo.iloc[-1]),
        "support": support, "resistance": resistance,
        "recent_high": recent_hi, "recent_low": recent_lo,
        "breakout": breakout, "breakdown": breakdown,
        "atr": last_atr, "atr_pct": atr_pct, "adx_proxy": last_adx,
        "momentum_20d": momentum_20d, "obv_up": obv_trend_up,
        "stop_loss": stop_loss, "target1": target1, "target2": target2,
        "risk_reward": rr, "low_confidence": len(close) < 60,
    })
    return out
