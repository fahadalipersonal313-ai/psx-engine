# Order-book captures

Drop L1 snapshot CSVs here. Every engine run re-scans this folder and ingests
anything new; re-ingesting the same file is a no-op.

Capture them with `tools/investify_l1.js` — paste it into Chrome's DevTools
console on the broker's quote page (nothing to install), then:

    book.peek()          check it parses what is on screen
    book.start("NRL")    capture, auto-stops
    book.dump()          CSV to clipboard

Name files so the DATE is recoverable — `NRL_2026-09-04.csv`, or leave the
epoch-ms the download helper adds. The CSV's `t` column carries only a clock
time, so without a date the snapshots would scatter across sessions.

**This is a measurement dataset.** Nothing here reaches a signal. It accumulates
so `imbalance` can be graded with `measure.py` first — every unmeasured input
this repo has trusted on appearance alone went on to measure flat or negative.
