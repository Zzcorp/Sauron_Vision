"""The invented AUDUSD book of the bureau v2 note's pictures (2026-11-15).

The operator's deploy note for the desk v2 (#111, #112, #113, #115) showed
the instrument page on one invented book, held at one instant, and named
the defects its pictures show (scenes 04 and 05: /instruments/AUDUSD/ at
1440 x 900, the signal rail open, a REAL long on the chart; 05 with the
rail's AUDUSD card pinned). This module seeds the part of that book the
instrument page reads, with the pictures' own figures, so a measured test
reads the page the pictures show:

    T        Thursday 12 November 2026, 19:13:56 UTC (the one-price
             fixture's instant): forex, the CME, NYSE and NASDAQ open.
    AUDUSD   eToro's quote 0.65000 / 0.65010, 8 s old; 120 one-hour
             candles of one feed (eToro's) from one seeded walk, ending in
             the forming 19:00 bar at the bid; their 4h buckets; 90 daily
             candles up to yesterday's close of 0.64870.
    REAL     a long of 10,000 AUDUSD at eToro, opened by hand six hours
             before T: entry 0.64500, stop 0.64000, target 0.66000
             (+50.00, +1.00R at the bid).
    the rest of the open book: REAL EURUSD and XAUUSD, a DEMO GBPUSD and
             a PAPER BTCUSD, the eToro account's cells, the "Main" book's
             2.5 % open-risk limit, the manual lanes and four bots.
    rail     five signals; AUDUSD's (entry 0.64900, stop 0.64650, target
             0.65400, 25 min old) is the one scene 05 pins.

Round, obviously invented sizes, levels and ages; no account id, no host,
no name, nothing real. Display only: nothing here reaches a broker, an
order or a model.
"""
import collections
import random
from datetime import timedelta
from decimal import Decimal

from tests.one_quote_fixture import T

SYMBOL = "AUDUSD"
PAGE_URL = "/instruments/AUDUSD/"
CHART_ID = "instrument-main-chart"

#: symbol: (name, class, exchange, starred): the page's instrument, the
#: rail's and the watchlist's.
INSTRUMENTS = {
    "AUDUSD": ("Australian Dollar / US Dollar", "forex", "FX", True),
    "EURUSD": ("Euro / US Dollar", "forex", "FX", True),
    "GBPUSD": ("British Pound / US Dollar", "forex", "FX", True),
    "XAUUSD": ("Gold", "commodity", "COMEX", True),
    "BTCUSD": ("Bitcoin", "crypto", "CRYPTO", True),
    "AAPL": ("Apple", "stock", "NASDAQ", True),
    "SPX500": ("S&P 500", "index", "NYSE", True),
}

#: symbol: (source, bid, ask, day change %, age in seconds at T).
QUOTES = {
    "AUDUSD": ("etoro", "0.65000", "0.65010", "0.20", 8),
    "EURUSD": ("etoro", "1.08000", "1.08010", "-0.10", 9),
    "GBPUSD": ("etoro", "1.29000", "1.29020", "0.10", 12),
    "XAUUSD": ("etoro", "2649.50", "2650.00", "0.40", 11),
    "BTCUSD": ("binance_ws", "65000.00", "65010.00", "1.50", 2),
    "AAPL": ("yfinance", "230.00", "230.05", "0.50", 60),
    "SPX500": ("yfinance", "5900.0", "5900.5", "0.30", 60),
}

#: The open book: symbol, side, qty, entry, stop, target, world, rule,
#: hours open, leverage, eToro's own net profit (REAL rows).
OPEN = (
    ("AUDUSD", "BUY", "10000", "0.64500", "0.64000", "0.66000", "live", "manual_take", 6, 20, 50.00),
    ("EURUSD", "BUY", "10000", "1.08200", "1.07700", "1.09200", "live", "range_break_1h", 9, 30, -20.00),
    ("XAUUSD", "SELL", "1", "2700.00", "2750.00", "2600.00", "live", "trend_break_4h", 26, 20, 50.00),
    ("GBPUSD", "BUY", "5000", "1.28800", "1.28300", "1.30000", "demo", "range_break_1h", 4, 30, None),
    ("BTCUSD", "BUY", "0.10", "64000.00", "62000.00", "68000.00", "paper", "trend_follow_1h", 12, 1, None),
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


def forex_hours(end, n):
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
    """120 one-hour AUDUSD candles of one feed (eToro's), ending with the
    forming 19:00 one, from one seeded walk through round anchors: 0.6487
    at yesterday's close, the day's low 0.6440, the REAL long's entry bar
    at 0.6450 six hours ago, the bid 0.65000 now."""
    rnd = random.Random(20261112)
    n = 120
    hours = forex_hours(T.replace(minute=0, second=0, microsecond=0), n)
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


def daily_walk(end_close, days, seed):
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


def seed_scene(user):
    """The pictures' book (the module docstring) for `user`. Returns
    {"user", "ids"}."""
    from bot_program.models import AssetBotConfig, AssetBotTrade, EtoroAccount
    from instruments.models import Instrument
    from market_data.models import LiveQuote, PriceData
    from portfolio.trader_profile import TraderProfile
    from signals.models import Signal

    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.theme_mode = "dark"
    prof.ambience = "magic"
    prof.tour_completed_at = T - timedelta(days=30)
    prof.save()

    insts = {}
    for sym, (name, cls, exch, starred) in INSTRUMENTS.items():
        insts[sym], _ = Instrument.objects.update_or_create(
            symbol=sym, defaults={"name": name, "asset_class": cls, "exchange": exch, "currency": "USD",
                                  "is_active": True, "is_watchlist": starred})
    for sym, (src, bid, ask, chg, age) in QUOTES.items():
        # the last print at the bid: a long's mark and the bands read one figure
        LiveQuote.objects.update_or_create(
            instrument=insts[sym],
            defaults={"last": Decimal(bid), "bid": Decimal(bid), "ask": Decimal(ask),
                      "change_pct": Decimal(chg), "volume": 1000, "source": src, "change_source": src})
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
        for ts, o, h, lo, c, v in daily_walk(0.64870, 90, 1112)])

    def lane(cls, name, mode, symbols=()):
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=user, asset_class=cls, name=name,
            defaults={"enabled": True, "mode": mode, "symbols": list(symbols), "capital": Decimal("10000"),
                      "base_currency": "USD"})
        return cfg

    # the manual lanes (the ticket's venue): forex, gold and stocks REAL
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
    from core.platform_control import PlatformComponent
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

    # the eToro account's own cells as the sync stored them 30 s before T
    # (no eToro call: the credentials are two invented words)
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
    from portfolio.models import Portfolio
    from portfolio.services import get_or_create_default_portfolio
    get_or_create_default_portfolio()        # the book the pages read ("Main")
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
