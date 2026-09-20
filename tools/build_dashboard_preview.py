"""Illustrative layout using exactly the production card renderer; no real calls."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opportunity_cards import CSS, card_html

ROOT = Path(__file__).resolve().parents[1]
cards = [card_html('DEMO A', 'SWING · Illustrative company', 'Buy',
    [('Signal close', '100.00'), ('Entry area', '99.50–100.50'), ('Loss reference', '97.00'), ('Target reference', '106.00')],
    'Rising daily trend, improving participation and a pullback near the planned entry area.',
    'Consider only if the entry area holds and the live price remains suitable.',
    'Recent price swings; exit may differ from the loss reference.',
    ['Claude: Positive', 'Codex: Neutral'], 'Completed-session analysis', 'Illustrative data · not a trade'),
    card_html('DEMO B', 'SWING · Illustrative company', 'Strong Buy',
    [('Signal close', '52.40'), ('Entry area', '51.80–52.50'), ('Loss reference', '50.10'), ('Target reference', '56.60')],
    'Upward structure remains intact across completed sessions; price is near the entry area.',
    'Wait if the opening price jumps above the entry area.',
    'A positive story does not remove price or liquidity risk.',
    ['Claude: Positive', 'Codex: Positive'], 'Completed-session analysis', 'Illustrative data · not a trade')]
live = card_html('DEMO C', 'INTRADAY · 15-minute observations', 'Momentum confirmed · watch',
    [('Last price', '102.00'), ('Opening gap %', '+0.30'), ('Since open %', '+1.69'), ('Last 15 min %', '+0.55')],
    'Above previous close and today’s open; rising over 15 minutes with sufficient traded value.',
    'Watch above 102.20; reassess below 101.10. References only; verify live spread.',
    'Spread, fill and exit availability are unverified. No measured profit rate.',
    ['Claude: Neutral', 'Codex: No fresh review'], 'Example trade time 10:45 PKT', '15-min traded value PKR 2,035,000')
page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PSX dashboard · layout preview</title>'''+CSS+'''
<style>body{margin:0;background:#08111e;color:#eef5ff;font-family:Inter,Segoe UI,sans-serif}main{max-width:1160px;margin:auto;padding:28px}h1{font-size:27px;margin-bottom:6px}h2{font-size:18px;margin:26px 0 5px}.muted{color:#9db1ca;font-size:13px}.banner{padding:12px 16px;border:1px solid #75613a;background:#322c20;color:#ffe0a5;border-radius:10px;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.nav{display:flex;gap:10px;margin:20px 0}.nav span{padding:8px 12px;background:#17263c;border-radius:6px;font-size:12px}.desk{padding:16px;background:#111e30;border:1px solid #2b4058;border-radius:12px}.desk strong{color:#8aefd0}details{padding:10px;color:#b9cbe0;border:1px solid #2b4058;border-radius:7px;font-size:12px}summary{cursor:pointer}@media(max-width:750px){.grid{grid-template-columns:1fr}main{padding:16px}.nav{flex-wrap:wrap}}</style>
<main><div class="banner">LAYOUT PREVIEW · All company names, prices and calls below are fictional examples. These are not current trading signals.</div>
<h1>PSX trading desk</h1><div class="muted">Two time horizons. One clear view of the opportunity, the evidence and the risk.</div>
<div class="nav"><span>Intraday momentum</span><span>Swing opportunities</span><span>News desk</span><span>History &amp; stock detail</span></div>
<div class="desk"><strong>News desk remains independent</strong><div class="muted">Claude and Codex keep their existing review schedules. Both assessments and source times stay visible; a positive story does not automatically produce a Buy.</div></div>
<h2>Intraday momentum <span class="muted">· refreshes each successful run</span></h2><div class="muted">Opening gap · movement since open · recent acceleration · traded value</div>
<div class="grid">'''+live+'''<div class="desk" style="margin:8px 0"><h2 style="margin-top:0">What this status means</h2><p class="muted">Two suitably spaced observations met the price and traded-value checks. This is a research watch, not a validated buy instruction.</p><p class="muted">Missing prices, an unverified open or stale data remain unavailable. A continuing setup keeps its original identity while each run is preserved.</p><details><summary>All intraday observations</summary>Live dashboard expands to show every tracked stock, including weakening and unavailable names.</details></div></div>
<h2>Swing opportunities <span class="muted">· completed-session signals</span></h2><div class="muted">Check the current price before entry. Intraday movement does not rewrite the daily setup.</div><div class="grid">'''+''.join('<div>'+c+'<details><summary>Full reason, levels &amp; news</summary>Full rationale, main risk, support, resistance, second target and dated Claude/Codex evidence remain available here.</details></div>' for c in cards)+'''</div>
<p class="muted">Existing portfolio, history, stock detail, news evidence and completed-session momentum remain available. Cards use the same renderer as the implemented dashboard.</p></main></html>'''
target = ROOT / 'docs/dashboard-preview.html'
target.write_text(page, encoding='utf-8')
print(target)
