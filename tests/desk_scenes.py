"""The desk v2 deploy note's scenes, as measured tests read them (the polish
of 2026-11-15).

The operator's note for the desk v2 (#111, #112, #113, #115) showed the
desk on one invented book at one held instant (scratchpad bureau_v2/
shoot.py, its scenes.md), and the display defects its pictures show. The
tests of the polish read the very scenes those pictures came from: this
module seeds the part of that book the scenes read, with the pictures' own
figures, and serves a page the way the pictures were taken.

THE BOOK (build_book's tables, as the pictures have them):

    T        Thursday 12 November 2026, 19:13:56 UTC (the one-price
             fixture's instant): forex, the CME, NYSE and NASDAQ open.
    open     REAL at eToro: AUDUSD long 10,000 at 0.64500 (opened by hand),
             EURUSD long 10,000 at 1.08200, XAUUSD short 1 at 2700.00;
             DEMO GBPUSD long 5,000 at 1.28800; PAPER BTCUSD long 0.10 at
             64000.00; each REAL and DEMO row marked at eToro's own rate.
    closed   seven trades across the three worlds.
    eToro    the account's own cells, read 30 s before T: equity
             10,000.00, used margin 1,000.00, available 9,000.00; its
             holdings the three REAL rows.
    limits   the "Main" book's open-risk limit at 2.5 %.
    rail     five signals; AUDUSD's (entry 0.64900, stop 0.64650, target
             0.65400, 25 min old) is the one scene 05 pins.
    AUDUSD   120 one-hour candles of one feed (eToro's) from one seeded
             walk, their 4h buckets, 90 daily candles: the instrument
             page's chart.

Round, obviously invented sizes, levels and ages; no account id, no host,
no name, nothing real. The band's other symbols are left out: no scene
measured here reads them.

THE SERVING (the pictures' own way, B0's: tests/old_design/measure.py):
every request the page makes is answered by the test client before it can
leave the machine, no host resolves, every clock the server reads is held
at T (freeze_patches), the page's own Date, timers and idle callbacks run
on a held clock (INIT) that the scene moves as the pictures did (2.6 s
after the load, 1.6 s after an act), dark theme and Magic on the
operator's profile, the chart library from its pinned copy (tests/vendor).
Google's font sheets are answered empty: the machine's faces draw (Inter
and JetBrains Mono where they are installed, as in CI).

Display only: nothing here posts to a view, trades, or calls a broker or a
model.
"""
import collections
import json
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings

from tests.one_quote_fixture import T

SYMBOL = "AUDUSD"
PIN = "1234"
T_MS = int(T.timestamp() * 1000)
LIB = (settings.BASE_DIR / "tests/vendor/lightweight-charts-4.1.0/"
       "lightweight-charts.standalone.production.js")
CDN = "https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"

#: symbol: (name, class, exchange, starred).
INSTRUMENTS = {
    "AUDUSD": ("Australian Dollar / US Dollar", "forex", "FX", True),
    "EURUSD": ("Euro / US Dollar", "forex", "FX", True),
    "GBPUSD": ("British Pound / US Dollar", "forex", "FX", True),
    "XAUUSD": ("Gold", "commodity", "COMEX", True),
    "BTCUSD": ("Bitcoin", "crypto", "CRYPTO", True),
    "ETHUSD": ("Ethereum", "crypto", "CRYPTO", False),
    "AAPL": ("Apple", "stock", "NASDAQ", True),
    "SPX500": ("S&P 500", "index", "NYSE", True),
}

#: symbol: (source, bid, ask, day change %, age in seconds at T). The last
#: print sits at the bid.
QUOTES = {
    "AUDUSD": ("etoro", "0.65000", "0.65010", "0.20", 8),
    "EURUSD": ("etoro", "1.08000", "1.08010", "-0.10", 9),
    "GBPUSD": ("etoro", "1.29000", "1.29020", "0.10", 12),
    "XAUUSD": ("etoro", "2649.50", "2650.00", "0.40", 11),
    "BTCUSD": ("binance_ws", "65000.00", "65010.00", "1.50", 2),
    "ETHUSD": ("binance_ws", "2600.00", "2601.00", "1.00", 3),
    "AAPL": ("yfinance", "230.00", "230.05", "0.50", 60),
    "SPX500": ("yfinance", "5900.0", "5900.5", "0.30", 60),
}

#: The open book: symbol, side, qty, entry, stop, target, world, rule, hours
#: open, leverage, eToro's own net profit (REAL rows).
OPEN = (
    ("AUDUSD", "BUY", "10000", "0.64500", "0.64000", "0.66000", "live", "manual_take", 6, 20, 50.00),
    ("EURUSD", "BUY", "10000", "1.08200", "1.07700", "1.09200", "live", "range_break_1h", 9, 30, -20.00),
    ("XAUUSD", "SELL", "1", "2700.00", "2750.00", "2600.00", "live", "trend_break_4h", 26, 20, 50.00),
    ("GBPUSD", "BUY", "5000", "1.28800", "1.28300", "1.30000", "demo", "range_break_1h", 4, 30, None),
    ("BTCUSD", "BUY", "0.10", "64000.00", "62000.00", "68000.00", "paper", "trend_follow_1h", 12, 1, None),
)

#: The closed book: symbol, side, qty, entry, exit, stop, P&L, R, outcome,
#: world, hours since the close, hours it was open.
CLOSED = (
    ("EURUSD", "BUY", "10000", "1.07000", "1.07800", "1.06500", "80.00", 1.6, "hit_target", "live", 3, 5),
    ("AUDUSD", "SELL", "10000", "0.65200", "0.65400", "0.65700", "-20.00", -0.4, "manual_close", "live", 27, 4),
    ("XAUUSD", "BUY", "1", "2680.00", "2630.00", "2630.00", "-50.00", -1.0, "stopped_out", "live", 50, 9),
    ("AAPL", "BUY", "10", "220.00", "225.00", "215.00", "50.00", 1.0, "hit_target", "live", 75, 6),
    ("GBPUSD", "SELL", "5000", "1.29500", "1.29300", "1.29900", "10.00", 0.5, "hit_target", "demo", 30, 3),
    ("BTCUSD", "SELL", "0.10", "66000.00", "65000.00", "68000.00", "100.00", 0.5, "hit_target", "paper", 6, 7),
    ("ETHUSD", "BUY", "1", "2600.00", "2550.00", "2550.00", "-50.00", -1.0, "stopped_out", "paper", 10, 5),
)

#: The rail: symbol, direction, score, rule, title, entry, stop, target,
#: price at the signal, minutes old, urgency.
SIGNALS = (
    ("AUDUSD", "bullish", 0.80, "range_break_1h", "Higher low above the Asian range",
     "0.64900", "0.64650", "0.65400", "0.64900", 25, "high"),
    ("EURUSD", "bearish", 0.66, "pivot_reject_1h", "Rejected at the weekly pivot",
     "1.08000", "1.08400", "1.07200", "1.08010", 50, "medium"),
    ("XAUUSD", "bearish", 0.70, "trend_break_4h", "Lower high under the 4h range",
     "2650.00", "2675.00", "2600.00", "2650.50", 120, "medium"),
    ("BTCUSD", "bullish", 0.72, "trend_follow_1h", "Higher low on the 1h",
     "65000.00", "63500.00", "68000.00", "64990.00", 180, "medium"),
    ("AAPL", "bullish", 0.61, "opening_range_long", "Back above the opening range high",
     "230.00", "226.00", "238.00", "229.90", 40, "low"),
)


def _forex_hours(end, n):
    """The last n forex hours up to `end` (the week shuts Friday 22:00 to
    Sunday 22:00 UTC), oldest first."""
    out, t = [], end
    while len(out) < n:
        wd, h = t.weekday(), t.hour
        if not ((wd == 4 and h >= 22) or wd == 5 or (wd == 6 and h < 22)):
            out.append(t)
        t -= timedelta(hours=1)
    return list(reversed(out))


def audusd_bars():
    """120 one-hour AUDUSD candles of eToro's feed, ending with the forming
    19:00 one, from one seeded walk through round anchors: 0.6487 at
    yesterday's close, the day's low 0.6440, the REAL long's entry bar at
    0.6450 six hours ago, the bid 0.65000 now."""
    rnd = random.Random(20261112)
    n = 120
    hours = _forex_hours(T.replace(minute=0, second=0, microsecond=0), n)
    anchors = [(119, 0.6455), (100, 0.6470), (80, 0.6452), (60, 0.6476), (45, 0.6460), (30, 0.6481),
               (21, 0.6487), (14, 0.6440), (6, 0.6450), (2, 0.6482), (1, 0.6494), (0, 0.6500)]
    path = []
    for i in range(n):
        k = n - 1 - i
        for (ka, pa), (kb, pb) in zip(anchors, anchors[1:]):
            if kb <= k <= ka:
                path.append(pa + (pb - pa) * ((ka - k) / (ka - kb) if ka != kb else 0))
                break
    rows, prev = [], path[0] - 0.0003
    for i, ts in enumerate(hours):
        k = n - 1 - i
        o = prev
        c = path[i] + (rnd.uniform(-0.0004, 0.0004) if k > 2 else 0)
        if k == 0:
            c = 0.65000
        hi = max(o, c) + abs(rnd.gauss(0, 0.00025)) + 0.00008
        lo = min(o, c) - abs(rnd.gauss(0, 0.00025)) - 0.00008
        if k == 6:
            lo, hi = min(lo, 0.64480), max(hi, 0.64530)
        if k == 1:
            hi = max(hi, 0.64990)
        if k == 0:
            hi, lo = max(hi, 0.65030), min(lo, 0.64940)
        v = int(400 + rnd.uniform(0, 800) + abs(c - o) * 400000)
        rows.append((ts, round(o, 5), round(hi, 5), round(lo, 5), round(c, 5), v))
        prev = c
    return rows


def _daily_walk(end_close, days, seed):
    """`days` daily candles on the weekdays before T, a seeded bridge that
    ends at `end_close` (yesterday's close)."""
    rnd = random.Random(seed)
    stamps, d = [], (T - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while len(stamps) < days:
        if d.weekday() < 5:
            stamps.append(d)
        d -= timedelta(days=1)
    stamps.reverse()
    walk = [0.0]
    for _ in range(days - 1):
        walk.append(walk[-1] + rnd.gauss(0, 0.0028))
    start = end_close * 0.984
    closes = [start + (end_close - start) * i / (days - 1) + (walk[i] - walk[-1] * i / (days - 1)) * end_close
              for i in range(days)]
    out, prev = [], closes[0] * 0.999
    for ts, c in zip(stamps, closes):
        o = prev
        hi = max(o, c) * (1 + abs(rnd.gauss(0, 0.0015)))
        lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.0015)))
        out.append((ts, round(o, 5), round(hi, 5), round(lo, 5), round(c, 5), int(rnd.uniform(40000, 90000))))
        prev = c
    return out


def scene_book():
    """The scenes' book (the tables above), written at T: call it with the
    server's clock held (hold_the_clock). Returns {"user", "ids"}: the
    operator, signed in as the pictures were, and each row's id by
    "<world>_<symbol>" ("signal" for the AUDUSD signal)."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.hashers import make_password

    from bot_program.models import AssetBotConfig, AssetBotTrade, EtoroAccount
    from core.platform_control import PlatformComponent
    from instruments.models import Instrument
    from market_data.models import LiveQuote, PriceData
    from portfolio.models import Portfolio
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.trader_profile import TraderProfile
    from signals.models import Signal

    user = get_user_model().objects.create_user("desk", password="x", is_staff=True, is_superuser=True)
    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.theme_mode, prof.ambience = "dark", "magic"
    prof.tour_completed_at = T - timedelta(days=30)
    prof.access_pin_hash = make_password(PIN)
    prof.save()

    insts = {}
    for sym, (name, cls, exch, starred) in INSTRUMENTS.items():
        insts[sym], _ = Instrument.objects.update_or_create(
            symbol=sym, defaults={"name": name, "asset_class": cls, "exchange": exch, "currency": "USD",
                                  "is_active": True, "is_watchlist": starred})
    for sym, (src, bid, ask, chg, age) in QUOTES.items():
        LiveQuote.objects.update_or_create(
            instrument=insts[sym],
            defaults={"last": Decimal(bid), "bid": Decimal(bid), "ask": Decimal(ask), "change_pct": Decimal(chg),
                      "volume": 1000, "source": src, "change_source": src})
        LiveQuote.objects.filter(instrument=insts[sym]).update(updated_at=T - timedelta(seconds=age))

    hourly = audusd_bars()
    q5 = lambda v: Decimal(str(round(v, 5)))  # noqa: E731
    PriceData.objects.bulk_create([
        PriceData(instrument=insts[SYMBOL], timeframe="1h", source="etoro", timestamp=ts,
                  open=q5(o), high=q5(h), low=q5(lo), close=q5(c), volume=v)
        for ts, o, h, lo, c, v in hourly])
    buckets = collections.OrderedDict()
    for ts, o, h, lo, c, v in hourly:
        key = ts.replace(hour=ts.hour - ts.hour % 4)
        b = buckets.get(key)
        buckets[key] = [o, h, lo, c, v] if b is None else [b[0], max(b[1], h), min(b[2], lo), c, b[4] + v]
    PriceData.objects.bulk_create([
        PriceData(instrument=insts[SYMBOL], timeframe="4h", source="etoro", timestamp=k,
                  open=q5(b[0]), high=q5(b[1]), low=q5(b[2]), close=q5(b[3]), volume=b[4])
        for k, b in buckets.items()])
    PriceData.objects.bulk_create([
        PriceData(instrument=insts[SYMBOL], timeframe="1d", source="etoro", timestamp=ts,
                  open=q5(o), high=q5(h), low=q5(lo), close=q5(c), volume=v)
        for ts, o, h, lo, c, v in _daily_walk(0.64870, 90, 1112)])

    def lane(cls, name, mode, symbols=()):
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=user, asset_class=cls, name=name,
            defaults={"enabled": True, "mode": mode, "symbols": list(symbols), "capital": Decimal("10000"),
                      "base_currency": "USD"})
        return cfg

    # The manual lanes (the ticket's venue) and the four bots, each ticked
    # 90 s before T; the platform's switch and the bots' component ON.
    manual = {"forex": lane("forex", "manual", "live"), "commodity": lane("commodity", "manual", "live"),
              "stock": lane("stock", "manual", "live"), "crypto": lane("crypto", "manual", "paper")}
    bots = {("forex", "live"): lane("forex", "fx_breakout", "live", ("EURUSD", "GBPUSD", "AUDUSD")),
            ("commodity", "live"): lane("commodity", "gold_trend", "live", ("XAUUSD",)),
            ("stock", "live"): lane("stock", "us_open", "live", ("AAPL",)),
            ("crypto", "paper"): lane("crypto", "crypto_paper", "paper", ("BTCUSD", "ETHUSD"))}
    for cfg in bots.values():
        cfg.extras = dict(cfg.extras or {}, last_tick_at=(T - timedelta(seconds=90)).isoformat(),
                          last_tick_status="ok", last_tick_note="ticked: nothing to do")
        cfg.save(update_fields=["extras"])
    for key in ("platform_master", "pipeline_asset_bots"):
        PlatformComponent.objects.update_or_create(
            key=key, defaults={"name": key.replace("_", " ").title(), "category": "system", "is_enabled": True})

    def meta_for(world, stop, leverage):
        meta = {"value_per_unit": 1.0, "initial_stop_loss": float(stop), "leverage": leverage}
        if world == "live":
            meta.update({"broker": "etoro", "broker_env": "live"})
        elif world == "demo":
            meta.update({"broker": "etoro", "broker_env": "paper"})
        return meta

    ids = {}
    for sym, side, qty, entry, stop, target, world, rule, hours, lev, _net in OPEN:
        cls = INSTRUMENTS[sym][1]
        meta = meta_for(world, stop, lev)
        _src, bid, ask, _chg, age = QUOTES[sym]
        if world in ("live", "demo"):
            meta["venue_mark"] = {"price": float(bid if side == "BUY" else ask), "bid": float(bid),
                                  "ask": float(ask), "source": "etoro", "via": "tick",
                                  "at": (T - timedelta(seconds=age)).isoformat()}
        if rule == "manual_take":
            cfg, meta["manual"] = manual[cls], True
        else:
            cfg = bots[(cls, "paper" if world == "paper" else "live")]
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class=cls, symbol=sym, side=side, qty=Decimal(qty), entry_price=Decimal(entry),
            stop_loss=Decimal(stop), take_profit=Decimal(target), status="OPEN", paper=(world == "paper"),
            rule_name=rule, composite_score=0.7, reason="An invented entry for the pictures.", metadata=meta)
        AssetBotTrade.objects.filter(pk=t.pk).update(opened_at=T - timedelta(hours=hours))
        ids["%s_%s" % (world, sym)] = t.pk
    for sym, side, qty, entry, exit_, stop, pnl, r, outcome, world, ago, held in CLOSED:
        cls = INSTRUMENTS[sym][1]
        cfg = bots.get((cls, "paper" if world == "paper" else "live")) or manual[cls]
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class=cls, symbol=sym, side=side, qty=Decimal(qty), entry_price=Decimal(entry),
            exit_price=Decimal(exit_), stop_loss=Decimal(stop), status="CLOSED", paper=(world == "paper"),
            rule_name="range_break_1h", reason="An invented trade for the pictures.",
            metadata=meta_for(world, stop, 1), pnl=Decimal(pnl), realized_r=r, outcome=outcome,
            duration_minutes=held * 60)
        AssetBotTrade.objects.filter(pk=t.pk).update(opened_at=T - timedelta(hours=ago + held),
                                                     closed_at=T - timedelta(hours=ago))

    # The eToro account's own cells, as the sync would have stored them 30 s
    # before T (the credentials are two invented words; eToro is never
    # called), and its holdings: the three REAL rows.
    acct = EtoroAccount.objects.create(user=user, demo=False, label="Main", connected=True,
                                       is_primary_for_stocks=True, is_primary_for_forex=True,
                                       is_primary_for_commodity=True, is_primary_for_crypto=True)
    acct.set_credentials("invented-key", "invented-user")
    at = T - timedelta(seconds=30)
    acct.last_sync = at
    acct.last_equity, acct.last_equity_currency, acct.last_equity_at = Decimal("10000.00"), "USD", at
    acct.last_used_margin, acct.last_available_cash = Decimal("1000.00"), Decimal("9000.00")
    acct.last_pnl, acct.last_frozen_cash, acct.last_balance = Decimal("80.00"), Decimal("0"), Decimal("9920.00")
    acct.last_margin_at, acct.last_margin_world = at, "live"
    acct.broker_positions = [
        {"symbol": sym, "sec_type": "CFD", "side": side, "qty": float(qty), "avg_cost": float(entry),
         "market_price": 0.0, "market_value": 0.0, "unrealized_pnl": 0.0, "currency": "USD",
         "leverage": lev, "amount": {"AUDUSD": 300.0, "EURUSD": 400.0, "XAUUSD": 300.0}[sym], "net_profit": net}
        for sym, side, qty, entry, _s, _t, world, _r, _h, lev, net in OPEN if world == "live"]
    acct.broker_positions_at = T - timedelta(seconds=20)
    acct.save()
    get_or_create_default_portfolio()
    Portfolio.objects.filter(name="Main").update(max_open_risk_pct=Decimal("2.5"))

    for sym, direction, score, rule, title, entry, stop, target, px, mins, urgency in SIGNALS:
        s = Signal.objects.create(
            instrument=insts[sym], signal_type="technical", direction=direction, urgency=urgency, title=title,
            description=title + ". An invented signal for the pictures.", rule_name=rule, score=score,
            sub_scores={"structure": round(score - 0.04, 2), "momentum": round(score - 0.08, 2)},
            price_at_signal=Decimal(px), suggested_entry=Decimal(entry), suggested_stop=Decimal(stop),
            suggested_target=Decimal(target), risk_reward_ratio=2.0, is_active=True)
        Signal.objects.filter(pk=s.pk).update(created_at=T - timedelta(minutes=mins))
        if sym == SYMBOL:
            ids["signal"] = s.pk
    return {"user": user, "ids": ids}


def hold_the_clock(cls):
    """Every clock the server reads held at T for the test class (B0's
    freeze_patches, stopped at the class's cleanup even when its setup
    raises)."""
    from tests.old_design.measure import freeze_patches
    for p in freeze_patches():
        p.start()
        cls.addClassCleanup(p.stop)


def chart_pref(symbol=SYMBOL):
    """The chart on its one-hour candles (its own saved choice)."""
    return {"sv-chart:instrument-main-chart:" + symbol: json.dumps({"tf": "1h"})}


class SceneBrowser:
    """The pictures' browser: B0's driver (every request answered by the
    test client, no host that resolves), the chart library from its pinned
    copy on the page's own origin, one tab per scene."""

    def __init__(self, client):
        from tests.old_design.measure import ORIGIN, _Driver, _Server
        from tests.test_close_advice import CHROME
        self.origin = ORIGIN
        server = _Server(client)
        lib = LIB.read_bytes()

        def answer(request, rtype):
            url = request["url"]
            if url.startswith(ORIGIN + "/__lwc__/") or url.startswith(CDN.rsplit("/", 2)[0]):
                return 200, {"Content-Type": "application/javascript; charset=utf-8",
                             "Access-Control-Allow-Origin": "*"}, lib
            got = server(request, rtype)
            if got and rtype == "Document" and got[0] == 200:
                body = got[2].replace(CDN.encode(), (ORIGIN + "/__lwc__/lightweight-charts.js").encode())
                return got[0], got[1], body
            return got
        self.driver = _Driver(CHROME, answer)

    def open(self, path, width=1440, height=900, rail="closed", sidebar="full", prefs=None):
        """A tab on the page as the pictures opened it: the page's clock at
        T, the operator's saved choices (the rail, the menu, the rail's two
        sections open), dark, no reduced motion, UTC; then the page let
        live 2.6 s on its held clock, its fetches landed, its last short
        timers run and its finite animations ended."""
        from tests.old_design.measure import INIT, LOAD_MS
        saved = {"sauron_signals_rail": rail, "sauron_sidebar": sidebar,
                 "sauron_rail_sig": "0", "sauron_rail_watch": "0"}
        saved.update(prefs or {})
        init = INIT % {"t": T_MS, "prefs": json.dumps(saved), "ws": json.dumps("quiet")}
        for attempt in range(4):
            tid, sid = self.driver.tab(width, height, init=init)
            self.driver.call("Emulation.setEmulatedMedia", {"features": [
                {"name": "prefers-color-scheme", "value": "dark"},
                {"name": "prefers-reduced-motion", "value": "no-preference"}]}, session=sid)
            self.driver.call("Emulation.setTimezoneOverride", {"timezoneId": "UTC"}, session=sid)
            try:
                self.driver.go(sid, self.origin + path, timeout=45)
                break
            except TimeoutError:
                # A loaded machine can stall a tab's first parse: a fresh
                # tab, at most four.
                self.driver.close_tab(tid)
                if attempt == 3:
                    raise
        self.settle(sid, LOAD_MS)
        return tid, sid

    def settle(self, sid, ms):
        """The held clock moved on `ms`, the page's fetches landed, its last
        short timers run (htmx's settle), its finite animations ended."""
        from tests.old_design.measure import ADVANCE, SETTLE
        self.driver.js(sid, ADVANCE % ms)
        self.driver.quiet(sid)
        for _ in range(6):
            before = self.driver.served
            self.driver.js(sid, ADVANCE % 250)
            self.driver.quiet(sid, still=0.3)
            if self.driver.served == before:
                break
        self.driver.js(sid, SETTLE % 120)

    def chart(self, sid):
        """The instrument page's chart has drawn: a canvas of size in the
        page and no loading veil (the pictures waited the same way)."""
        from tests.old_design.measure import ADVANCE, SETTLE
        probe = ("(function () { var v = Array.prototype.filter.call(document.querySelectorAll("
                 "'.page-content [id$=\"-loading\"]'), function (e) { return e.offsetParent !== null; });"
                 " var c = Array.prototype.filter.call(document.querySelectorAll('.page-content canvas'),"
                 " function (e) { var r = e.getBoundingClientRect(); return r.width > 300 && r.height > 150; });"
                 " return c.length > 0 && v.length === 0; })()")
        for _ in range(25):
            if self.driver.js(sid, probe):
                break
            self.driver.js(sid, ADVANCE % 200)
            self.driver.quiet(sid, still=0.3)
        self.driver.js(sid, SETTLE % 300)
        return bool(self.driver.js(sid, probe))

    def js(self, sid, expression):
        return self.driver.js(sid, expression)

    def close_tab(self, tid):
        self.driver.close_tab(tid)

    def close(self):
        self.driver.close()
