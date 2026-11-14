"""The synthetic fixture of the desk v2's instrument page (B10, 2026-11-13).

The board the operator approved ("amazing work, bravo, I need it fast!!",
scratchpad canvas_v2/project/Instrument2.dc.html) prints one invented gold
book; this module seeds the same one, so the page the tests measure and the
pictures beside the board print the same figures:

    XAUUSD   Gold, commodity, eToro's quote: bid 2,647.72 / ask 2,648.12
             (spread 0.40), 12 s old; the day -0.32 %.
    REAL     a short of 1.5 at eToro, entry 2,658.40, stop 2,682.00,
             target 2,610.00, opened a day ago: +15.42 at the ask, +0.44R.
    bars     76 one-hour candles of one feed (eToro's), ending on the hour
             now, drawn from one seeded walk (the board's own anchors).
    signals  XAUUSD short 0.72 (trend_break_4h: entry 2,651.40, stop
             2,675.40, target 2,603.40, four hours old) and four others:
             EURUSD long 0.66, AAPL long 0.61, BTCUSD short 0.60, USDJPY
             long 0.64.

Round, invented instruments, levels, sizes and ages, written relative to
the moment the test runs (the chart's clock is the browser's). Nothing here
is anybody's data, no network, no broker, no model.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

BID, ASK = Decimal("2647.72"), Decimal("2648.12")
ENTRY, STOP, TARGET, QTY = Decimal("2658.40"), Decimal("2682.00"), Decimal("2610.00"), Decimal("1.5")
SIG = {"entry": Decimal("2651.40"), "stop": Decimal("2675.40"), "target": Decimal("2603.40"),
       "score": 0.72, "rule": "trend_break_4h", "title": "Breakdown under the 4h range"}
N_BARS = 76
ENTRY_BAR = N_BARS - 1 - 24          # the short opened a day ago
SIG_BAR = N_BARS - 1 - 4             # the pinned signal, four hours ago

INSTRUMENTS = {
    "XAUUSD": ("Gold", "commodity", "COMEX"),
    "EURUSD": ("Euro / US Dollar", "forex", "FX"),
    "AAPL": ("Apple", "stock", "NASDAQ"),
    "BTCUSD": ("Bitcoin", "crypto", "CRYPTO"),
    "USDJPY": ("US Dollar / Japanese Yen", "forex", "FX"),
}


def instrument(symbol):
    from instruments.models import Instrument
    name, cls, exch = INSTRUMENTS[symbol]
    inst, _ = Instrument.objects.update_or_create(
        symbol=symbol, defaults={"name": name, "asset_class": cls, "exchange": exch,
                                 "currency": "USD", "is_active": True, "is_watchlist": True})
    return inst


def series(seed=20261113):
    """[(open, high, low, close, volume)] * N_BARS: the board's walk
    (canvas_v2/tools/series.py), its last close the bid."""
    rnd = random.Random(seed)
    anchors = [(0, 2661.0), (8, 2669.5), (15, 2675.0), (21, 2667.0), (28, 2673.5), (35, 2664.0),
               (42, 2668.5), (47, 2663.0), (ENTRY_BAR, 2659.5), (56, 2650.5), (61, 2657.0),
               (66, 2646.8), (SIG_BAR - 1, 2655.0), (N_BARS - 2, 2652.4)]
    path = []
    for i in range(N_BARS):
        for (a, pa), (b, pb) in zip(anchors, anchors[1:]):
            if a <= i <= b:
                path.append(pa + (pb - pa) * ((i - a) / (b - a) if b > a else 0))
                break
        else:
            path.append(anchors[-1][1])
    out, prev = [], path[0] - 0.8
    for i in range(N_BARS - 1):
        o, c = prev, path[i] + rnd.uniform(-2.6, 2.6)
        if i == ENTRY_BAR:
            o, c = 2660.2, 2657.1
        if i == SIG_BAR:
            c = float(SIG["entry"])
        h = max(o, c) + abs(rnd.gauss(0, 1.9)) + 0.4
        lo = min(o, c) - abs(rnd.gauss(0, 1.9)) - 0.4
        if i == ENTRY_BAR:
            h, lo = max(h, 2661.0), min(lo, 2656.4)
        out.append([o, h, lo, c])
        prev = c
    out.append([2652.40, 2655.10, 2646.80, float(BID)])
    out[-2][3] = 2652.40
    out[-2][1] = max(out[-2][1], out[-2][0] + .3, 2652.8)
    out[-2][2] = min(out[-2][2], out[-2][0] - .2, 2652.2)
    rows = []
    for i, (o, h, lo, c) in enumerate(out):
        v = 520 + rnd.uniform(0, 520) + abs(c - o) * 95
        if i in (45, 46, 66, 74):
            v *= 1.55
        rows.append((o, h, lo, c, round(v)))
    rows[-1] = rows[-1][:4] + (1284,)
    return rows


def _bars(inst, now):
    """One feed's stored 1h candles, the newest the forming one."""
    from market_data.models import PriceData
    top = now.replace(minute=0, second=0, microsecond=0)
    q = lambda v: Decimal(str(round(v, 2)))  # noqa: E731
    rows = series()
    PriceData.objects.bulk_create([
        PriceData(instrument=inst, timeframe="1h", source="etoro",
                  timestamp=top - timedelta(hours=N_BARS - 1 - i),
                  open=q(o), high=q(h), low=q(lo), close=q(c), volume=v)
        for i, (o, h, lo, c, v) in enumerate(rows)])
    # the same walk as 4h candles on the UTC grid: the living levels read them
    buckets = {}
    for i, (o, h, lo, c, v) in enumerate(rows):
        at = top - timedelta(hours=N_BARS - 1 - i)
        key = at.replace(hour=at.hour - at.hour % 4)
        b = buckets.get(key)
        buckets[key] = [o, h, lo, c, v] if b is None else [b[0], max(b[1], h), min(b[2], lo), c, b[4] + v]
    PriceData.objects.bulk_create([
        PriceData(instrument=inst, timeframe="4h", source="etoro", timestamp=k,
                  open=q(b[0]), high=q(b[1]), low=q(b[2]), close=q(b[3]), volume=b[4])
        for k, b in sorted(buckets.items())])


def _quote(inst, now, last, bid=None, ask=None, chg="0", source="etoro", age_s=12):
    from market_data.models import LiveQuote
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)), "source": source,
                                   "bid": None if bid is None else Decimal(str(bid)),
                                   "ask": None if ask is None else Decimal(str(ask)),
                                   "change_pct": Decimal(str(chg)), "volume": 0,
                                   "change_source": source})
    LiveQuote.objects.filter(instrument=inst).update(updated_at=now - timedelta(seconds=age_s))


def _lane(user, asset_class):
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=asset_class, name="desk %s" % asset_class,
        defaults={"enabled": True, "mode": "live", "symbols": [],
                  "capital": Decimal("10000"), "base_currency": "USD"})
    return cfg


def _held(user, inst, now, *, side, qty, entry, stop, target, bid, ask, age_s=12,
          opened=timedelta(days=1), world="live"):
    """An open row at eToro, its venue stamp eToro's bid and ask."""
    from bot_program.models import AssetBotTrade
    vm = {"price": float((bid + ask) / 2), "bid": float(bid), "ask": float(ask),
          "source": "etoro", "via": "tick",
          "at": (now - timedelta(seconds=age_s)).isoformat()}
    meta = {"broker": "etoro", "broker_env": "paper" if world == "demo" else "live",
            "initial_stop_loss": float(stop), "venue_mark": vm}
    t = AssetBotTrade.objects.create(
        config=_lane(user, inst.asset_class), asset_class=inst.asset_class, symbol=inst.symbol,
        side=side, qty=qty, entry_price=entry, stop_loss=stop, take_profit=target,
        status="OPEN", paper=False, rule_name="trend_break_4h", metadata=meta)
    AssetBotTrade.objects.filter(pk=t.pk).update(opened_at=now - opened)
    return t


def _signal(inst, now, *, direction, score, rule, title, entry, stop, target, age):
    from signals.models import Signal
    s = Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction, urgency="medium",
        title=title, description="The 4h range broke on rising volume; the daily trend points down.",
        rule_name=rule, score=score, sub_scores={}, price_at_signal=Decimal(str(entry)),
        suggested_entry=Decimal(str(entry)), suggested_stop=Decimal(str(stop)),
        suggested_target=Decimal(str(target)), risk_reward_ratio=2.0, is_active=True)
    Signal.objects.filter(pk=s.pk).update(created_at=now - age)
    return s


def seed_desk(user, now=None):
    """The board's book (the module docstring). Returns its parts."""
    now = now or timezone.now()
    gold = instrument("XAUUSD")
    _bars(gold, now)
    _quote(gold, now, BID, BID, ASK, chg="-0.32")
    # The venue's stamp a little older than the poll of the same feed, so the
    # one price is the poll's and its day change prints (the board's state:
    # "Day -0.32 % ▼"; the review of B10, F14). Both eToro's.
    trade = _held(user, gold, now, side="SELL", qty=QTY, entry=ENTRY, stop=STOP, target=TARGET,
                  bid=BID, ask=ASK, age_s=30)
    pinned = _signal(gold, now, direction="bearish", score=SIG["score"], rule=SIG["rule"],
                     title=SIG["title"], entry=SIG["entry"], stop=SIG["stop"],
                     target=SIG["target"], age=timedelta(hours=4))
    others = []
    for sym, direction, score, rule, title, px, age in (
            ("EURUSD", "bullish", 0.66, "mean_revert_1h", "Pullback to the 1h mean", 1.08745,
             timedelta(minutes=12)),
            ("AAPL", "bullish", 0.61, "gap_fill_1d", "Gap fill toward 230", 228.31,
             timedelta(minutes=41)),
            ("BTCUSD", "bearish", 0.60, "trend_break_1h", "Lower high under 92k", 91230.5,
             timedelta(hours=1)),
            ("USDJPY", "bullish", 0.64, "trend_follow_1h", "Higher low on the 1h", 153.412,
             timedelta(hours=2))):
        inst = instrument(sym)
        _quote(inst, now, px, chg="0.12", source="yfinance", age_s=40)
        up = direction == "bullish"
        others.append(_signal(inst, now, direction=direction, score=score, rule=rule, title=title,
                              entry=px, stop=px * (0.99 if up else 1.01),
                              target=px * (1.02 if up else 0.98), age=age))
    return {"gold": gold, "trade": trade, "pinned": pinned, "others": others}


def market_open():
    """The instrument's market open, whatever the clock says: the file page
    keeps no script that would repaint the market's chip, and its checks
    read the trading day's header (a shut market's own check rides the live
    page, tests/test_instrument_desk_v2.py, TheLiveDeskTests). A patch of
    core.exchange_status.market_status_for, which the view reads per
    request; display only."""
    from unittest import mock

    import core.exchange_status as ex
    real = ex.market_status_for

    def opened(*args, **kwargs):
        out = dict(real(*args, **kwargs))
        out.update(is_open=True)
        return out
    return mock.patch.object(ex, "market_status_for", opened)


# ── the page as Chromium opens it, offline ────────────────────────────────

CHART_ID = "instrument-main-chart"
PAGE_URL = "/instruments/XAUUSD/"


def chart_payload(client, tf="1h"):
    """The chart's own reply for `tf`, as the page's widget asks for it."""
    resp = client.get("/api/chart-data/?symbol=XAUUSD&timeframe=%s&overlays=1" % tf,
                      HTTP_HOST="127.0.0.1")
    return resp.json()


def _keep(m):
    """The scripts the chart and the one price run on, where the page has
    them; the shell's own (htmx, the sockets, the pollers) dropped."""
    s = m.group(0)
    head = s[:s.index(">") + 1]
    if 'type="application/json"' in head or "data-sv-quotes" in head:
        return s
    if "src=" in head:
        return s if "js/sv-venue.js" in head else ""
    body = s[len(head):]
    for words in ("__svLwChartsLoaded", "window.svSignalDots = {", "var CHART_ID", "data-ih=\"range\""):
        if words in body:
            return s
    return ""


def file_page(markup, payloads, *, base_dir, lib, prefs=None, before=""):
    """The rendered page as a file Chromium opens on its own: the chart's
    and the one price's scripts kept, every other script dropped, external
    stylesheets dropped (no network), /static/ read from the tree, the
    chart library from `lib`, and fetch answering /api/chart-data/ from
    `payloads` ({timeframe: reply}); `prefs` seeds the chart's own saved
    view (its timeframe), as a visit before this one left it."""
    import json
    import re
    page = re.sub(r"<script\b.*?</script>", _keep, markup, flags=re.S)
    page = re.sub(r'<link\b[^>]*href="https?://[^>]*>', "", page)
    page = page.replace('"/static/', '"file://%s/static/' % base_dir)
    page = page.replace("'/static/", "'file://%s/static/" % base_dir)
    stub = """<script>
(function () {
  var P = %s;
  window.__svFetches = [];
  window.fetch = function (url) {
    url = String(url);
    window.__svFetches.push(url);
    var m = /[?&]timeframe=([^&]+)/.exec(url);
    var body = (url.indexOf('/api/chart-data/') >= 0 && m) ? P[decodeURIComponent(m[1])] : null;
    if (!body) return Promise.resolve({ status: 404, ok: false, json: function () { return Promise.resolve({}); } });
    var copy = JSON.parse(JSON.stringify(body));
    /* answered as a server would: later, once the page has parsed */
    return new Promise(function (r) { setTimeout(r, 60); }).then(function () {
      return { status: 200, ok: true, json: function () { return Promise.resolve(copy); } };
    });
  };
  try {
    localStorage.clear();
    var prefs = %s;
    if (prefs) localStorage.setItem('sv-chart:%s:XAUUSD', JSON.stringify(prefs));
  } catch (e) {}
})();
</script>%s<script src="%s"></script>""" % (json.dumps(payloads), json.dumps(prefs), CHART_ID, before,
                                             lib.as_uri())
    return re.sub(r"(<head\b[^>]*>)", lambda m: m.group(1) + stub, page, count=1)
