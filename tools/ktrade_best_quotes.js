/* Run locally on your logged-in KTrade web terminal. Reads visible quote cells
   only; no requests, credentials, positions, balances, or order actions.
   Click Start, Stop, then Download in the small panel. Best quotes, not depth. */
(() => {
  if (document.getElementById('psx-quote-recorder')) return;
  const columns = ['symbol','captured_at','bid_price','bid_volume','ask_price','ask_volume','source'];
  let timer = null, rows = [], rejected = 0, fileHandle = null, writing = false;
  const csv = () => [columns.join(','), ...rows.map(r => r.join(','))].join('\n');
  const save = async () => {
    if (!fileHandle || writing) return;
    writing = true;
    try {
      const file = await fileHandle.createWritable();
      await file.write(csv()); await file.close();
    } catch (_) {
      fileHandle = null; status.textContent = 'Live save stopped. Download CSV or choose a file again.';
    } finally { writing = false; }
  };
  const panel = document.createElement('div');
  panel.id = 'psx-quote-recorder';
  panel.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2147483647;background:#fff;color:#111;border:2px solid #167;padding:12px;font:14px sans-serif';
  const title = document.createElement('div'); title.textContent = 'Local best-quote recorder (no orders)'; panel.append(title);
  const status = document.createElement('div'); panel.append(status);
  const read = () => {
    const seen = new Set();
    for (const table of document.querySelectorAll('table')) {
      if (!table.getClientRects().length) continue;
      const trs = [...table.querySelectorAll('tr')];
      if (!trs.length) continue;
      const headers = [...trs[0].querySelectorAll('th,td')].map(c => c.innerText.toLowerCase().replace(/\s+/g,''));
      const mapping = ['symbol','bidprice','bidsize','askprice','asksize'].map(h => headers.indexOf(h));
      const market = headers.indexOf('market');
      if (mapping.some(i => i < 0)) continue;
      for (const tr of trs.slice(1)) {
        if (!tr.getClientRects().length) continue;
        const cells = [...tr.querySelectorAll('td')];
        if (market >= 0 && cells[market]?.innerText.trim() !== 'REG') continue;
        const selected = mapping.map(i => cells[i]?.innerText.trim());
        const symbol = selected[0];
        if (!symbol || !/^[A-Z0-9][A-Z0-9.-]{0,19}$/.test(symbol) || seen.has(symbol)) continue;
        const values = selected.slice(1).map(x => Number((x || '').replace(/,/g,'')));
        if (values.some(x => !Number.isFinite(x) || x <= 0) || values[0] >= values[2]) { rejected++; continue; }
        seen.add(symbol);
        rows.push([symbol,new Date().toISOString(),...values,'KTrade visible best quotes']);
      }
    }
    status.textContent = `${rows.length} captured; ${rejected} empty/invalid reads skipped`;
    save();
  };
  const stop = () => { clearInterval(timer); timer = null; };
  const button = (label, handler) => {
    const b = document.createElement('button'); b.textContent = label;
    b.type = 'button'; b.style.margin = '6px'; b.onclick = handler; panel.append(b);
  };
  button('Start (20 minutes)', () => {
    stop(); rows = []; rejected = 0; const until = Date.now() + 20 * 60000;
    read(); timer = setInterval(() => { if (Date.now() >= until) stop(); else read(); }, 5000);
  });
  button('Stop', stop);
  button('Choose local live CSV', async () => {
    if (!window.showSaveFilePicker) { status.textContent = 'Live file saving is unavailable. Use Download CSV.'; return; }
    try {
      fileHandle = await window.showSaveFilePicker({suggestedName:'ktrade_live.csv',types:[{description:'Quote CSV',accept:{'text/csv':['.csv']}}]});
      status.textContent = 'Local file selected. Start records into this file every five seconds.';
    } catch (_) { status.textContent = 'No file selected. Download CSV is still available.'; }
  });
  button('Download CSV', () => {
    const text = csv();
    const url = URL.createObjectURL(new Blob([text], {type:'text/csv'}));
    const a = document.createElement('a'); a.href = url;
    a.download = 'ktrade_quotes_' + new Date().toISOString().slice(0,10) + '.csv'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  button('Close', () => { stop(); panel.remove(); });
  status.textContent = 'Open a watchlist with Bid size/price and Ask price/size, then Start.';
  document.body.append(panel);
})();
