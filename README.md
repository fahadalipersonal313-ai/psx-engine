# PSX paper trading - Turn-Confirmation Theory (forward test)

Started 20-Oct-2026. Runs in Anthropic's cloud every weekday (routine `trig_01LvYyZLWtPee7SqjAzAnLAK`).
Paper only: no real money, no real orders. Research, not investment advice.

* `paper_trade.py` - the whole trader (Python standard library only). `python3 -m unittest test_paper_trade` tests it on synthetic data.
* `config.json` - capital Rs 1,000,000 (paper), 0.25% risk per trade, gate +3%, 3-ATR trail, 30-session time stop.
* `state/` - price history, breadth, open positions, pending orders, the latest gate reading and scan (`last_scan.json`),
  and `status.json`, a small summary the dashboard reads.
* `trades.csv` - every closed trade: entry, exit, reason, R, %, rupee P&L.
* `runs/` - one report per run: what it saw, what it did, and why.

## Where prices come from (since 20-Oct-2026)

Every paper decision uses PSX's **official** end-of-day bars. The psx-engine writes them to `market_eod.json` on its
`runtime-state` branch: all stocks from PSX's daily market-summary download (open, high, low, official close, volume,
previous close) and the KSE-100 close from PSX's closing-rates PDF. The trader reads that file (raw GitHub URL, or a
partial `git fetch` of just that file), and finalises each new session exactly once, oldest first:

1. Ex-dates: PSX lowers its previous close by the dividend (marker XD) or by the bonus/rights ratio (XB/XR). Only XB/XR
   rescale that stock's history, open position and pending order (as TradingView's research data does); XD is reported
   and left unadjusted (TradingView does not adjust dividends either); an unmarked change is reported, never guessed.
2. Orders placed at the previous close fill at this session's official open (cancelled if the open is more than
   0.3 ATR above the signal close, or if the stock did not trade).
3. Positions: gap below the stop at the open exits at the open; a low through the stop exits at the stop; otherwise one
   session is counted (30 = time stop at the close) and the 3-ATR chandelier trail is raised.
4. Bars are appended, both gates are evaluated, both legs are scanned, and orders are placed for the next open only if
   both gates are open.

Re-running is harmless (a stored session is never processed twice) and a missed run is caught up by the next one.
A session is refused as a probable missing session if fewer than half of PSX's previous closes match our stored closes
or more than 5% are higher (ex-dates only ever lower them), and it waits if the official KSE-100 close is not yet
published. Nothing is invented.

TradingView's public scanner, when reachable, adds an informational live line (KSE-100 now, live price vs stop, whether
a pending order would fill at today's open). It never changes state.

Rules: both gates open (KSE-100 >= 1.03 x its 20-day low AND breadth higher than 5 sessions ago) -> buy at the next official open.
Leg B 52-week-high breakouts (live book) and Leg A washout demand closes (research book), liquid names (>= Rs 25m/day) only.
Stops never move down.
