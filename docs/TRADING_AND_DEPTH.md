# Buying checks, intraday quotes and trading evidence

## Changes in v7
The wider-market veto is OFF. A falling index adds a warning and cannot by itself turn a Buy into Watch. A stock must still pass its own price, liquidity, support, buying-flow and relative-strength checks. The score is still based on completed sessions; intraday quotes do not rewrite historical decisions.

Keep the data, eligibility, PKR liquidity, valid stop/target and broken-support guards. Keep stock strength/buying flow and the one-session pause after a sharp jump. Strong Buy still needs two completed sessions, and the score buffer still prevents repeated changes near a boundary. Chase, near-resistance and single-stock concentration SIGNAL vetoes were already off; account-level cash/position/sector limits remain.

Buying more reduces the average purchase price but increases exposure. It should require a fresh reason for that stock and an affordable loss, not just an existing loss. Strong company news is shown as context; it does not excuse invalid prices, illiquidity or broken support. News and intraday quote signals remain uncalibrated, with zero daily-score weight.

The latest 60 saved decisions inspected on September 11 were 51 Avoid, 7 Watch and 2 Hold. Reasons mentioned market weakness in 4 records and broken support in 32. Reasons overlap; four market warnings do NOT mean four guaranteed new Buys. Evidence: read-only query `select payload from decisions where session=(select max(session) from decisions)`, decoded with `database.unpack_payload`, counted `signal.signal` and reason substrings.

## What is available at no extra subscription cost
- User confirmed that KTrade and Investify show best buying/selling orders. That is **best bid/offer**, not a full multi-level book.
- The logged-in KTrade web watchlist was inspected on September 11 after market hours. It has Bid size, Bid price, Ask price and Ask size columns; the observed entries were zero. No usable live depth or export was verified. No personal account details were copied into this repository.
- KTrade's official [terminal manual](https://kasb.com/wp-content/uploads/2023/06/Ktrade-User-Manual.pdf), pages 27–28, describes a market-depth display. It does not establish a free export/API or equal iOS feature support.
- PSX [Data Services](https://www.psx.com.pk/psx/product-and-services/data-services-vending) describes Level 1+ top-ten order-book feeds and licensing requirements. A documented free public multi-level API was not verified. Use your existing account's permitted viewing/capture access; do not republish licensed raw captures.

Recommended first step: record the best quotes already visible in your logged-in page for the stock you are considering. No broker credentials, private endpoints, network interception, order placement, paid feed or subscription is added.

## KTrade recording
1. Open the logged-in web terminal during market hours and show the regular-market watchlist with the five columns named above plus Symbol.
2. In Chrome's developer console, run the contents of `tools/ktrade_best_quotes.js`. It adds a small recorder panel. Review the source first; it reads only visible market-quote cells and never sends a request.
3. Click **Start (20 minutes)**. It reads every five seconds. Zero/invalid quotes are skipped. The table-header adapter was based on the observed web watchlist; live repaint behavior cannot be verified while the market is closed.
4. Click **Download CSV**, then use **Intraday best bid / offer** in Streamlit to load the file. Uploads are analyzed in that session; raw captures are not committed to GitHub.
5. For continuous LOCAL monitoring, first choose **Choose local live CSV** and save as `private_depth/ktrade_live.csv` inside your local checkout. Start the recorder, then run `python depth_analysis.py PSO --watch`, or your local Streamlit dashboard. The local file updates every five seconds while the page is open and capture is running. Browser permission/file access is granted by you through the save dialog.

The recorder stops after 20 minutes; restart deliberately to continue. Closing/suspending the browser or losing the session stops updates. A file on your PC does not automatically reach Streamlit Cloud. The hosted dashboard supports manual upload; unattended cloud streaming still requires an approved accessible feed or a private bridge. None is claimed to be connected.

## Investify recording
Use the existing `tools/investify_l1.js` on the visible quote page: `book.peek()` checks its label parser, `book.start("PSO")` records five-second samples for 20 minutes, and `book.dump()` returns CSV. Save/load the CSV into the new Streamlit panel. Captures now contain full UTC timestamps. Page changes can break the label parser; check its values against the screen before recording. No undocumented Investify API was verified or added.

## What the analysis does
- Rejects missing, non-positive, crossed or locked quotes and unknown clock dates. Future samples cannot influence a current read.
- Requires open-session time, a latest quote within 30 seconds, at least 12 different quote states across at least one minute, and no capture gaps over 30 seconds.
- Keeps vendors and supplied level counts separate. Repeated reads of an unchanged screen do not create confirmation.
- Measures spread, persistence of displayed buying/selling interest, price range, and fading buying interest. A best-quote file is always labelled one level. Multi-level CSVs are supported only if actual levels are supplied; no levels are inferred.
- Flags broad spreads. A holding price with persistent bids is described as displayed buying interest, not proven accumulation. We cannot distinguish cancellations from trades, identify hidden orders or establish absorption from these fields.
- All thresholds are transparent research heuristics in `depth_analysis.py`. They are not fitted success probabilities and do not change daily scores. Before considering a score weight, collect timestamped forward quotes/trades and compare non-overlapping outcomes after spreads/costs on held-out sessions. No such evidence exists yet.

CSV format: `symbol,captured_at,level,bid_price,bid_size,ask_price,ask_size,source`. Use timezone-bearing timestamps such as `2026-09-11T10:20:00+05:00`. `level` defaults to 1. Existing Investify `bid_volume` and `ask_volume` names work. Old clock-only files require a date in the filename. Optional cumulative volume can distinguish a changing screen but is not classified as buy/sell trades.

## Is the new history best for trading?
No such conclusion is established. Better software and a clearer history screen do not prove profitability. The read-only stored-cohort query grouped by strategy version found v5 with 3 stops and 22 pending candidates; no v6 outcomes were present in that snapshot. These are candidates (including rejected ideas), not an executed portfolio. They cannot prove v7, whose market gate has just changed.

The earlier supplied five-year/grid measurements were not rerun. Their conclusions remain historical evidence for earlier contracts. Current-rule results are separated by version AND contract in the dashboard, and displayed stocks still using earlier rules are labelled until regenerated. Missing pre-September-9 universe membership is still explicitly withheld.

Validation covers behavior and safeguards, not returns. Raw captures remain under ignored `private_depth/`. No account holdings, balances or credentials are part of this update.

Checks before publication: 105 unit tests passed; all 62 root Python modules compiled; both capture scripts passed JavaScript syntax checks; the workflow YAML parsed; the two new Streamlit panels passed an isolated AppTest with no exceptions. Actual broker quote updates remain untested until the market opens.
