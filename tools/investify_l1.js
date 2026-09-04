/* Investify L1 order-book capture — paste into Chrome DevTools console.
   Nothing to install. Reads only what is already on screen; sends nothing.
   Works on div layouts because it reads LABEL -> next number from innerText,
   so it does not depend on Investify's CSS classes or DOM nesting.

   book.peek()            one read, to check it parses
   book.start("NRL")      capture every 5s, auto-stops after 20 min
   book.dump()            CSV to clipboard, paste back
   book.stop()                                                            */
(function () {
  var FIELDS = ['BID PRICE','ASK PRICE','BID VOLUME','ASK VOLUME','SPREAD',
                'LAST PRICE','CURRENT','OPEN','PREV CLOSE','VOLUME',
                'DAY LOW','DAY HIGH'];
  var KEY = FIELDS.map(function (f) { return f.replace(/ /g, '_').toLowerCase(); });

  function read() {
    var t = document.body.innerText;
    var o = {};
    FIELDS.forEach(function (f, i) {
      // label, then whitespace/newlines, then the first number that follows
      var m = new RegExp(f.replace(/ /g, '\\s+') + '\\s*[\\r\\n]+\\s*([\\d,]+(?:\\.\\d+)?)', 'i').exec(t);
      o[KEY[i]] = m ? parseFloat(m[1].replace(/,/g, '')) : null;
    });
    return o;
  }

  var rows = [], timer = null, sym = '?';

  window.book = {
    peek: function () { var r = read(); console.table(r); return r; },
    start: function (symbol, secs, mins) {
      sym = symbol || (location.pathname.split('/')[2] || '?');
      rows = [];
      var every = (secs || 5) * 1000, until = Date.now() + (mins || 20) * 60000;
      timer = setInterval(function () {
        var r = read();
        if (r.bid_price != null || r.ask_price != null) {
          r.t = new Date().toTimeString().slice(0, 8);
          rows.push(r);
        }
        if (Date.now() > until) { clearInterval(timer); console.log('done — ' + rows.length + ' rows. book.dump()'); }
      }, every);
      console.log('capturing ' + sym + ' every ' + (every / 1000) + 's for ' + (mins || 20) + ' min');
    },
    stop: function () { clearInterval(timer); console.log('stopped — ' + rows.length + ' rows'); },
    dump: function () {
      var cols = ['t'].concat(KEY);
      var out = ['symbol,' + cols.join(',')].concat(rows.map(function (r) {
        return sym + ',' + cols.map(function (c) { return r[c] == null ? '' : r[c]; }).join(',');
      })).join('\n');
      console.log(out);
      try { copy(out); console.log('(copied to clipboard)'); } catch (e) {}
      return out;
    }
  };
  console.log('book ready → run  book.peek()');
})();
