# PSX paper trading - Turn-Confirmation Theory (forward test)

Started 20-Oct-2026. Runs in Anthropic's cloud every weekday, hourly 09:45-15:45 PKT.

* `paper_trade.py` - the whole trader (Python standard library only).
* `config.json` - capital Rs 1,000,000 (paper), 0.25% risk per trade, gate +3%, 3-ATR trail, 30-session time stop.
* `state/` - price history, breadth, open positions, pending orders (the trader's memory between runs).
* `trades.csv` - every closed trade: entry, exit, reason, R, %, rupee P&L.
* `runs/` - one report per run: what it saw, what it did, and why.

Rules: both gates open (KSE-100 >= 1.03 x its 20-day low AND breadth higher than 5 sessions ago) -> buy at the next official open
Leg B 52-week-high breakouts (live book) and Leg A washout demand closes (research book), liquid names (>= Rs 25m/day) only.
Stops never move down. Nothing is invented: if prices cannot be fetched the run says so and does nothing.
