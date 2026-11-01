"""ONE HONEST PRICE ON THE INSTRUMENT PAGE (2026-10-31).

The operator: "sometimes the graph and the price written arent perfectly
the same and some spikes up or down happen for no reason". One screen drew
one instrument from up to five feeds: eToro's CFD candles on 1h and 4h,
Yahoo's future or cash index on the daily and the minute frames (GC=F for
gold, ^GSPC for the S&P), the platform quote in the hero (whichever feed
won the LiveQuote row last), welded onto the last candle every 15 seconds,
and eToro's bid in the positions row. A 1h or 4h series mixed eToro's bars
with Yahoo's stand-ins bar by bar, and nothing on the page said whose any
number was.

This module is the one answer to "whose is this price", for the chart's
reply (`series`), the quote's preview and the hero (`quote_facts`):

  * ONE FEED PER SERIES. The candles of the venue the instrument routes to
    (bot_program.engine.broker_router.broker_name_for_symbol, a read of the
    operator's own settings, no request, and a venue the operator holds)
    when it has them for that frame and they are not stale, else the
    public feed's (Yahoo, Binance for crypto) when they are newer, else
    whatever feed the newest row came from. Rows of the other feeds are
    not drawn; the legend says when older history was cut and when
    another feed holds newer bars.
  * WORDS. "eToro's own candles", "Yahoo GC=F, the front-month future, not
    eToro's price": printed under the chart and beside the hero.
  * THE VENUE'S LAST PRICE beside the hero for a venue-routed instrument:
    a real row's venue mark or the venue's newest stored candle, with its
    age. Never a new request: eToro's quota is unwritten and a burst of
    background reads once held real entries (market_data/bot_bars.py).
  * TODAY'S FORMING DAILY CANDLE from the same feed's intraday bars, and a
    bar that cannot have traded marked, never hidden
    (market_data.bar_shape).
  * FOLDED FRAMES (2026-11-01, the operator: "augmenter la division des
    chart ajout de 10min etc..."). A candle no feed stores or serves is
    folded from a finer one of the SAME series: 2h from the 1h rows
    choose() picks, on the fixed UTC grid; the weekly candle from the
    daily series' days, by ISO week (Monday 00:00 UTC), each day in the
    week of its session; 10 min from the keyless feed's 5 min bars
    (neither Yahoo nor Binance has 10 min). A bucket is its first open,
    highest high, lowest low, last close and summed volume; one holding a
    suspect bar inherits its marking; the partial last one is the forming
    bar. This week's candle takes the live tick only while it holds
    today's forming day, as the daily view's last candle does.

Display only: the engine reads bars through its own loaders, never this.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_tz

logger = logging.getLogger(__name__)

#: A PriceData or LiveQuote source tag -> the feed it belongs to.
FAMILY = {
    "yfinance": "yahoo", "yfinance_public": "yahoo",
    "yfinancefeed_public": "yahoo",
    "binance": "binance", "binance_public": "binance",
    "binance_ws": "binance", "binancefutures": "binance",
    "etoro": "etoro",
    "oanda": "oanda", "oanda_stream": "oanda",
    "finnhub_ws": "finnhub",
    "alpaca": "alpaca", "ibkr": "ibkr", "saxo": "saxo",
    "coingecko": "coingecko", "alpha_vantage": "alpha_vantage",
    "twelve_data": "twelve_data", "fmp": "fmp",
}
FEED_NAME = {
    "yahoo": "Yahoo", "binance": "Binance", "etoro": "eToro",
    "oanda": "OANDA", "finnhub": "Finnhub", "alpaca": "Alpaca",
    "ibkr": "IBKR", "saxo": "Saxo", "coingecko": "CoinGecko",
    "alpha_vantage": "Alpha Vantage", "twelve_data": "Twelve Data",
    "fmp": "FMP",
}
#: The router's venues whose own candles the bar refresh stores.
VENUES = frozenset({"etoro", "oanda", "alpaca", "ibkr", "saxo", "binance"})
STAND_IN_WORDS = {"future": "the front-month future",
                  "cash index": "the cash index"}
#: Intraday bars per chart reply.
INTRADAY_LIMIT = 240
#: How long a live minute frame is kept between the chart's polls.
MINUTE_CACHE_S = 60
#: The gap between the quote and the venue's last price the hero names.
GAP_WORDS_PCT = 0.05

# ── The chart's frames (2026-11-01) ─────────────────────────────────────
#: The chart's timeframe on the wire -> its interval. "1min" etc., never a
#: bare "1m": on this API "1m" has always meant one month of daily candles.
WIRE_INTERVALS = {"1min": "1m", "5min": "5m", "10min": "10m",
                  "15min": "15m", "30min": "30m", "1h": "1h", "2h": "2h",
                  "4h": "4h"}
#: The weekly candle on the wire: Yahoo's spelling, apart from "1w", the
#: range of daily candles the toolbar has always had.
WEEKLY = "1wk"
#: An intraday frame's seconds.
FRAME_SECONDS = {"1m": 60, "5m": 300, "10m": 600, "15m": 900, "30m": 1800,
                 "1h": 3600, "2h": 7200, "4h": 14400}
#: Frames drawn from STORED rows, and the stored frame each reads: nothing
#: writes 2h, so it is folded from the same feed's 1h rows.
STORED_FROM = {"1h": "1h", "2h": "1h", "4h": "4h"}
#: Live frames a keyless feed has no interval for, and the finer one they
#: are folded from (_native).
LIVE_FOLD = {"10m": "5m"}
#: Binance's kline intervals (GET /api/v3/klines). Yahoo's are
#: market_data.public_feed.YF_NATIVE, and its client resamples the
#: RESAMPLE_FROM frames from 1h itself.
BINANCE_INTERVALS = frozenset({"1s", "1m", "3m", "5m", "15m", "30m", "1h",
                               "2h", "4h", "6h", "8h", "12h", "1d", "3d",
                               "1w", "1M"})
#: How far back the weekly view reads days: five years of weeks, so SMA50
#: and SMA200 have weeks to say something on.
WEEKLY_DAYS = 1820
#: A frame in the legend's words.
FRAME_WORDS = {"5m": "5 min", "10m": "10 min"}


def family(tag) -> str:
    """The feed a source tag belongs to: "yahoo", "etoro", ... An unknown
    tag is its own feed, so a writer this table does not know still
    draws."""
    t = str(tag or "").strip().lower()
    if not t:
        return ""
    if t in FAMILY:
        return FAMILY[t]
    for suffix in ("_public", "_ws", "_stream"):
        if t.endswith(suffix):
            base = t[: -len(suffix)]
            return FAMILY.get(base, base)
    return t


def feed_name(fam) -> str:
    return FEED_NAME.get(fam, fam or "an unknown feed")


def public_family(asset_class) -> str:
    return "binance" if (asset_class or "") == "crypto" else "yahoo"


def public_tag(asset_class) -> str:
    """The tag the keyless feed writes its bars under for this class."""
    return "binance_public" if (asset_class or "") == "crypto" \
        else "yfinance_public"


def stand_in(fam, symbol) -> str:
    """"future" or "cash index" when `fam`'s price for `symbol` is another
    instrument (public_feed.yf_stand_in), else ""."""
    if fam != "yahoo":
        return ""
    try:
        from market_data.public_feed import yf_stand_in
        return yf_stand_in(symbol)
    except Exception:  # noqa: BLE001 — a dict read; kept total
        return ""


def feed_symbol(fam, instrument) -> str:
    """The symbol `fam` quotes `instrument` under ("" when it is ours)."""
    sym = getattr(instrument, "symbol", "") or ""
    try:
        if fam == "yahoo":
            from market_data.public_feed import yf_symbol
            return yf_symbol(sym, getattr(instrument, "asset_class", ""))
        if fam == "binance":
            from market_data.management.commands.backfill_bars import (
                venue_symbol)
            return venue_symbol(sym)
    except Exception:  # noqa: BLE001
        return ""
    return ""


def label(fam, instrument) -> str:
    """"eToro", "Yahoo GC=F", "Binance BTCUSDT"."""
    sym = feed_symbol(fam, instrument)
    return feed_name(fam) + (f" {sym}" if sym else "")


def what(fam, instrument) -> str:
    """The label and, for a stand-in, what it stands in as: "Yahoo GC=F,
    the front-month future"."""
    si = stand_in(fam, getattr(instrument, "symbol", ""))
    return label(fam, instrument) + (f", {STAND_IN_WORDS[si]}" if si else "")


def series_words(fam, instrument, route="") -> str:
    """The legend's words for candles of `fam` on an instrument routed to
    `route`."""
    if fam and fam == route and not feed_symbol(fam, instrument):
        return f"{feed_name(fam)}'s own candles"
    out = what(fam, instrument)
    if fam == route:
        return out + ", the venue's own candles"
    if route and route in VENUES:
        out += f", not {feed_name(route)}'s price"
    return out


def route_of(user, instrument) -> str:
    """The venue the operator's orders on `instrument` go to, as a feed
    ("etoro", ...), or "" (paper, unknown, or no operator). A read of the
    operator's own settings: no client is built, no request is sent.

    A VENUE THE OPERATOR HOLDS (2026-10-31). broker_name_for_symbol falls
    through to the class's default broker (OANDA for forex, Alpaca for
    stocks, Binance for crypto, IBKR for options and CFDs) whatever the
    credentials, so for a user with no such account the legend said
    "Binance BTCUSDT, the venue's own candles" over the public feed's
    klines and the hero printed a binance_public candle as the venue's
    last known price. The route counts only when _holds says so."""
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    try:
        from bot_program.engine.broker_router import broker_name_for_symbol
        name = family(broker_name_for_symbol(user, instrument.symbol))
        if name not in VENUES or not _holds(user, name):
            return ""
    except Exception:  # noqa: BLE001 — a word on a chart never raises
        return ""
    return name


#: The router's default brokers and the account row that holds each one's
#: stored credentials (bot_program.models).
_CREDENTIAL_ROWS = {"binance": "binance_account", "oanda": "oanda_account",
                    "alpaca": "alpaca_account"}


def _holds(user, name) -> bool:
    """True when `user` holds venue `name`, read from the database alone:
    eToro and Saxo are named only on their own account's primary flag,
    IBKR needs an account with an id (the router's own refusal), OANDA,
    Alpaca and Binance need stored credentials (and Binance not on its
    testnet, which the router sends to paper)."""
    if name in ("etoro", "saxo"):
        return True
    if name == "ibkr":
        acct = getattr(user, "ibkr_account", None)
        return bool(acct is not None and acct.get_account_id())
    attr = _CREDENTIAL_ROWS.get(name)
    acct = getattr(user, attr, None) if attr else None
    if acct is None:
        return False
    first, second = acct.get_credentials()
    if not (first and second):
        return False
    return not (name == "binance" and getattr(acct, "testnet", False))


def tick_bar(asset_class) -> float:
    """The class's jump bar (bot_program.mark_sanity.bar_for): the live
    tick is not drawn on a candle it would move further than this."""
    try:
        from bot_program.mark_sanity import bar_for
        return bar_for(asset_class)
    except Exception:  # noqa: BLE001
        return 0.0


# ── Which feed draws a series ─────────────────────────────────────────

def _families(instrument, timeframe) -> dict:
    """{feed: {"tags": [...], "oldest": dt, "newest": dt}} of the stored
    rows of `instrument` at `timeframe`."""
    from django.db.models import Max, Min

    from market_data.models import PriceData

    out = {}
    rows = (PriceData.objects.filter(instrument=instrument,
                                     timeframe=timeframe)
            .values("source")
            .annotate(oldest=Min("timestamp"), newest=Max("timestamp")))
    for r in rows:
        fam = family(r["source"])
        f = out.setdefault(fam, {"tags": [], "oldest": r["oldest"],
                                 "newest": r["newest"]})
        f["tags"].append(r["source"])
        f["oldest"] = min(f["oldest"], r["oldest"])
        f["newest"] = max(f["newest"], r["newest"])
    return out


def _stale(instrument, timeframe, newest, now) -> bool:
    """A venue's series whose newest bar the market has long left
    (market_data.bot_bars' own bound for a stale venue window)."""
    from market_data.bot_bars import (INTERVAL_SECONDS,
                                      STALE_VENUE_AFTER_S,
                                      STALE_VENUE_BARS_CRYPTO)
    if newest is None:
        return True
    age = (now - newest).total_seconds()
    if (getattr(instrument, "asset_class", "") or "") == "crypto":
        return age > STALE_VENUE_BARS_CRYPTO * INTERVAL_SECONDS.get(
            timeframe, 3600)
    return age > STALE_VENUE_AFTER_S


def choose(instrument, timeframe, fams, route, now, notes=None):
    """The feed that draws `timeframe`: the routed venue's when it has rows
    that are not stale, else the public feed's, else the newest row's.

    A stale venue gives way only to NEWER bars (2026-10-31). The public
    feed's rows of a routed instrument are history from before the
    venue's window and whatever it wrote after the venue's newest bar
    (bot_bars evicts the rest), so after a long weekend, or with nothing
    written since, the chart dropped the venue's recent bars for Yahoo's
    weeks older. The venue keeps the series unless the public feed's
    newest row is newer than its own."""
    pub = public_family(getattr(instrument, "asset_class", ""))
    if route and route in fams:
        newest = fams[route]["newest"]
        if not _stale(instrument, timeframe, newest, now) \
                or pub not in fams or fams[pub]["newest"] <= newest:
            return route
        if notes is not None:
            notes.append(f"{feed_name(route)}'s candles stopped on "
                         f"{fams[route]['newest']:%Y-%m-%d %H:%M} UTC; these "
                         f"are {label(pub, instrument)}'s")
        return pub
    if pub in fams:
        return pub
    if fams:
        return max(fams, key=lambda f: fams[f]["newest"])
    return None


def _venue_hole(fams, fam, route):
    """The venue's newest bar when the public feed draws a routed
    instrument the venue has rows of, else None (2026-10-31).

    bot_bars evicts the public feed's rows inside each venue window and
    writes its stand-ins only after the venue's newest bar, so the public
    rows of a routed instrument are old history, a hole where the venue's
    bars sit, and the stand-ins since. Drawn as they are, the last candle
    of the history and the first stand-in sat side by side: one price
    step that never traded. Only the rows after this are drawn."""
    if fam and route and fam != route and route in fams:
        return fams[route]["newest"]
    return None


def _newer_note(instrument, timeframe, fams, fam, last):
    """The legend's words when other feeds hold rows newer than `last`,
    the series' newest drawn bar, else "" (2026-10-31). bot_bars writes
    the public feed after the venue's newest bar whenever the venue is
    muted, paced, refused with a 429 or answers only impossible bars, and
    the bots read those rows; the chart ended at the venue's last candle,
    hours ago, with nothing saying newer bars exist."""
    from market_data.models import PriceData

    parts, total = [], 0
    for f in sorted(fams):
        v = fams[f]
        if f == fam or v["newest"] <= last:
            continue
        n = (PriceData.objects
             .filter(instrument=instrument, timeframe=timeframe,
                     source__in=v["tags"], timestamp__gt=last).count())
        if n:
            total += n
            parts.append(f"{n} newer bar{'s' if n > 1 else ''} from "
                         f"{label(f, instrument)}")
    if not parts:
        return ""
    return (f"{feed_name(fam)}'s newest {timeframe} candle is "
            f"{last:%Y-%m-%d %H:%M} UTC; " + " and ".join(parts)
            + (" are" if total > 1 else " is") + " not drawn")


def _source(instrument, fam, route, notes):
    """The reply's `source`. `same_feed_only` (2026-10-31): crypto candles
    take the live tick of their own feed alone. A Binance BTCUSDT quote is
    another exchange's, quoted in USDT, not the instrument of eToro's BTC
    candles, and its gap sits well inside crypto's 3% jump bar, so the
    widget's "neither side is a stand-in" welded it onto eToro's forming
    candle every 15 s and the refresh took it away again."""
    si = stand_in(fam, instrument.symbol)
    return {"family": fam, "label": label(fam, instrument),
            "what": what(fam, instrument),
            "words": series_words(fam, instrument, route),
            "stand_in": si, "route": route,
            "same_feed_only": (instrument.asset_class or "") == "crypto",
            "tick_bar": tick_bar(instrument.asset_class),
            "notes": notes, "positions": ""}


def _bar(p, time_value):
    return {"time": time_value,
            "open": float(p.open), "high": float(p.high),
            "low": float(p.low), "close": float(p.close),
            "volume": float(p.volume) if p.volume else 0}


def _finish(bars, src, fold_with=None):
    """Drop the bars that cannot be drawn, mark the suspect ones, and say
    both in the legend's notes.

    With `fold_with` (2026-11-01) the bars are marked FIRST, then folded:
    a bucket holding a suspect bar inherits the marking (`fold`), so a bad
    hour whose 2h bucket's prices happen to look possible is still drawn
    hollow and named. The note counts the bars drawn."""
    from market_data.bar_shape import finite, mark_suspects
    bars, dropped = finite(bars)
    mark_suspects(bars, src["label"])
    if fold_with is not None:
        bars = fold_with(bars)
    marked = sum(1 for b in bars if b.get("suspect"))
    if marked:
        # "on candle charts": a line or area chart draws the close alone
        # (2026-10-31).
        src["notes"].append(f"{marked} suspect bar{'s' if marked > 1 else ''}"
                            f", drawn hollow on candle charts")
    if dropped:
        src["notes"].append(f"{dropped} unreadable bar"
                            f"{'s' if dropped > 1 else ''} left out")
    return bars


# ── Folded frames (2026-11-01) ────────────────────────────────────────

def _stamp(t) -> str:
    """A bar's time in the legend's words: a date as it is, epoch seconds
    as 'YYYY-MM-DD HH:MM UTC'."""
    if isinstance(t, (int, float)):
        return f"{datetime.fromtimestamp(t, tz=dt_tz.utc):%Y-%m-%d %H:%M} UTC"
    return str(t)


def fold(bars, key, part) -> list:
    """Chart bars (oldest first) folded into buckets: `key(time)` names
    each bar's bucket, and the bucket is drawn at that time. Its open is
    the first bar's, its high the highest, its low the lowest, its close
    the last bar's and its volume the sum (2026-11-01).

    One feed in, one feed out: the caller hands the bars of ONE series. A
    bucket holding a bar already marked suspect (mark_suspects) inherits
    its words and says which `part` it was ("1h bar"): folded with a sound
    neighbour, a bar whose high sits under its open makes a bucket whose
    prices look possible. A partial bucket is drawn as it stands: the last
    one is the forming bar, and a cut first one is the caller's to drop."""
    groups = []
    for b in bars:
        k = key(b["time"])
        if not groups or groups[-1][0] != k:
            groups.append((k, []))
        groups[-1][1].append(b)
    out = []
    for k, members in groups:
        bar = {"time": k, "open": members[0]["open"],
               "high": max(m["high"] for m in members),
               "low": min(m["low"] for m in members),
               "close": members[-1]["close"],
               "volume": sum(float(m.get("volume") or 0) for m in members)}
        odd = [m for m in members if m.get("suspect")]
        if odd:
            more = f" and {len(odd) - 1} more" if len(odd) > 1 else ""
            bar["suspect"] = (f"{odd[0]['suspect']} (the {part} of "
                              f"{_stamp(odd[0]['time'])}{more})")
        out.append(bar)
    return out


def _on_grid(span, part, limit=None):
    """A fold onto the fixed UTC grid of `span` seconds (00:00, 02:00 ...
    for 2h, from the epoch whatever the season), keeping the newest `limit`
    buckets. Read `limit` buckets' worth of rows, a first bucket the read
    cut short always makes one bucket too many, so the newest `limit` never
    hold it."""
    def run(bars):
        out = fold(bars, lambda t: int(t) - int(t) % span, part)
        return out[-limit:] if limit else out
    return run


def _native(fam, interval) -> bool:
    """Whether keyless feed `fam` serves `interval` itself (2026-11-01).
    Yahoo serves market_data.public_feed.YF_NATIVE and resamples
    RESAMPLE_FROM from 1h itself; Binance serves its kline intervals.
    Neither serves 10 minutes: asked, Yahoo answers nothing and Binance
    refuses the request."""
    if fam == "binance":
        return interval in BINANCE_INTERVALS
    from market_data.public_feed import RESAMPLE_FROM, YF_NATIVE
    return interval in YF_NATIVE or interval in RESAMPLE_FROM


def _monday(when):
    """00:00 UTC of the Monday of `when`'s ISO week."""
    day = when.astimezone(dt_tz.utc).replace(hour=0, minute=0, second=0,
                                            microsecond=0)
    return day - timedelta(days=day.weekday())


def week_of(day_label) -> str:
    """The ISO week of a 'YYYY-MM-DD' day, as its Monday's 'YYYY-MM-DD'."""
    d = datetime.strptime(str(day_label)[:10], "%Y-%m-%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def utc_day(stamp) -> str:
    """A daily row's label on the daily view: the UTC date of its stamp
    (C1's label, unchanged)."""
    return stamp.strftime("%Y-%m-%d")


def session_day(stamp) -> str:
    """The trading day a daily row is the bar of, 'YYYY-MM-DD'
    (2026-11-01): its stamp rounded to the nearest UTC midnight.

    Yahoo stamps a daily bar at midnight in the exchange's own zone, and
    the EOD writer stores that instant as it is (yfinance_adapter
    .save_history_to_db): DAX40's Monday sits at Sunday 22:00 or 23:00
    UTC, the Nikkei's at Sunday 15:00, the ASX's at Sunday 13:00 or 14:00,
    EURUSD=X's in British Summer Time at Sunday 23:00. By the UTC date of
    the stamp, Monday's session was folded into the week before. Rounded,
    a midnight from UTC-11 to UTC+12 lands on its own date: every index
    in public_feed.YF_SYMBOL_MAP (the ASX's UTC+11 summer is the furthest
    east) and every forex day; a market at UTC+13 (New Zealand's summer)
    would not, and none is charted. A feed that stamps 00:00 UTC (Binance,
    Alpha Vantage) or New York's midnight (04:00 or 05:00 UTC) keeps its
    date."""
    return (stamp.astimezone(dt_tz.utc) + timedelta(hours=12)) \
        .strftime("%Y-%m-%d")


def intraday_series(instrument, interval, *, route="",
                    limit=INTRADAY_LIMIT, now=None):
    """(bars, source) for an intraday frame. 1h and 4h are the stored
    rows of one feed; finer frames are fetched live from the keyless feed
    (never stored: a minute table for a chart click is not worth its
    rows) and kept a minute. `time` is epoch seconds.

    2h and 10 min (2026-11-01). Nothing stores 2h: it is folded from the
    1h rows of the feed choose() picks for 1h, with the same hole cut,
    notes and suspect marks, on the fixed UTC grid; the newest `limit`
    buckets are read as twice as many hours. Neither keyless feed serves
    10 min: it is folded from the feed's 5 min bars, kept a minute under
    its own key. 30 min is both feeds' own interval."""
    from market_data.models import PriceData

    now = now or datetime.now(dt_tz.utc)
    notes = []
    base = STORED_FROM.get(interval)
    if base:
        ratio = FRAME_SECONDS[interval] // FRAME_SECONDS[base]
        fams = _families(instrument, base)
        fam = choose(instrument, base, fams, route, now, notes)
        if fam:
            qs = PriceData.objects.filter(instrument=instrument,
                                          timeframe=base,
                                          source__in=fams[fam]["tags"])
            cut = _venue_hole(fams, fam, route)
            if cut is not None:
                qs = qs.filter(timestamp__gt=cut)
            rows = list(qs.order_by("-timestamp")[:limit * ratio])
            rows.reverse()
            bars = [_bar(p, int(p.timestamp.timestamp())) for p in rows]
            if rows and cut is not None and fams[fam]["oldest"] <= cut:
                notes.append(f"older bars from {label(fam, instrument)}, "
                             f"from before {feed_name(route)}'s last "
                             f"candle, are not drawn")
            elif fam == route and rows:
                first = rows[0].timestamp
                older = sorted(f for f, v in fams.items()
                               if f != fam and v["oldest"] < first)
                if older:
                    notes.append("older bars from " + " and ".join(
                        label(f, instrument) for f in older)
                        + " are not drawn")
            if rows:
                newer = _newer_note(instrument, base, fams, fam,
                                    rows[-1].timestamp)
                if newer:
                    notes.append(newer)
            fold_with = None
            if ratio > 1:
                fold_with = _on_grid(FRAME_SECONDS[interval], f"{base} bar",
                                     limit)
                if rows:
                    notes.insert(0, f"{interval} candles folded from "
                                    f"{label(fam, instrument)}'s {base} "
                                    f"candles, on the UTC grid")
            src = _source(instrument, fam, route, notes)
            return _finish(bars, src, fold_with), src
        # No stored rows (an instrument outside the fleet and the
        # watchlist): the live fetch below.

    fam = public_family(instrument.asset_class)
    src = _source(instrument, fam, route, notes)
    fetch, ratio = interval, 1
    if interval in LIVE_FOLD and not _native(fam, interval):
        fetch = LIVE_FOLD[interval]
        ratio = FRAME_SECONDS[interval] // FRAME_SECONDS[fetch]
    raw = _live_frame(instrument, fetch, limit * ratio, key=interval)
    if raw is None:
        return [], src
    bars, dropped = raw
    if dropped:
        notes.append(f"{dropped} unreadable bar{'s' if dropped > 1 else ''}"
                     f" left out")
    fold_with = None
    if ratio > 1:
        part = FRAME_WORDS.get(fetch, fetch)
        fold_with = _on_grid(FRAME_SECONDS[interval], f"{part} bar", limit)
        if bars:
            notes.insert(0, f"{FRAME_WORDS.get(interval, interval)} candles "
                            f"folded from {label(fam, instrument)}'s {part} "
                            f"bars, on the UTC grid")
    return _finish([dict(b) for b in bars], src, fold_with), src


def _live_frame(instrument, interval, limit, key=None):
    """(bars, dropped) of the keyless feed, kept a minute; None when the
    class has no keyless feed. `key` (2026-11-01): the chart frame the
    bars are kept for, when it is not `interval` (10 min keeps the 5 min
    bars it folds apart from the 5 min view's)."""
    from django.core.cache import cache

    from market_data.bar_shape import finite

    key = f"chart:v2:{instrument.symbol}:{key or interval}"
    try:
        hit = cache.get(key)
    except Exception:  # noqa: BLE001
        hit = None
    if hit is not None:
        return hit.get("bars", []), hit.get("dropped", 0)

    from market_data.public_feed import public_feed_for
    client = public_feed_for(instrument.asset_class)
    if client is None:
        return None
    fetch_symbol = instrument.symbol
    if instrument.asset_class == "crypto":
        from market_data.management.commands.backfill_bars import venue_symbol
        fetch_symbol = venue_symbol(instrument.symbol)
    bars = []
    try:
        for row in client.klines(fetch_symbol, interval=interval,
                                 limit=limit) or []:
            if not row or len(row) < 6:
                continue
            try:
                bars.append({
                    "time": int(int(row[0]) / 1000),
                    "open": float(row[1]), "high": float(row[2]),
                    "low": float(row[3]), "close": float(row[4]),
                    "volume": float(row[5] or 0),
                })
            except (TypeError, ValueError):
                bars.append({"time": 0, "open": None, "high": None,
                             "low": None, "close": None, "volume": 0})
    except Exception:  # noqa: BLE001 — a dead feed is an empty chart, not a 500
        bars = []
    bars, dropped = finite(bars)
    try:
        cache.set(key, {"bars": bars, "dropped": dropped}, MINUTE_CACHE_S)
    except Exception:  # noqa: BLE001
        pass
    return bars, dropped


def daily_series(instrument, *, since=None, limit=None, route="", now=None):
    """(bars, source) of daily candles, `time` a 'YYYY-MM-DD' string.

    One feed's 1d rows. With none at all, the day is built from one feed's
    4h, else 1h rows: a daily candle IS the aggregate of its day's
    intraday bars (a fresh deployment has 1h/4h days before its first 1d
    row). With 1d rows whose newest is older than today, today's FORMING
    candle is built from the same feed's intraday rows of today, labelled
    forming: the default daily view ended on yesterday all day while the
    hero moved (Yahoo's EOD pass runs at 22:30 UTC)."""
    now = now or datetime.now(dt_tz.utc)
    notes = []
    bars, fam = _daily_bars(instrument, since=since, route=route, now=now,
                            notes=notes, words=_DAY_WORDS)
    src = _source(instrument, fam or public_family(instrument.asset_class),
                  route, notes)
    if limit:
        bars = bars[-int(limit):]
    return _finish(bars, src), src


#: What the legend says of today when the day is built from intraday rows,
#: or cannot be (2026-11-01: the weekly view says it of this week).
_DAY_WORDS = {
    "forming": "today's candle is forming from {}'s intraday bars",
    "elsewhere": ("today's candle is not drawn: today's intraday bars are "
                  "{}'s, not {}'s"),
}
_WEEK_WORDS = {
    "forming": "this week's candle is forming, today from {}'s intraday bars",
    "elsewhere": ("this week's candle leaves today out: today's intraday "
                  "bars are {}'s, not {}'s"),
}
#: Why this week's candle takes no live tick (2026-11-01): the bar's
#: `no_tick`, which the widget's caption prints after "live quote not
#: drawn: ".
WEEK_NO_TICK = {
    "out": "this week's candle leaves today out",
    "closed": "today's daily candle has closed",
}


def weekly_series(instrument, *, since=None, route="", now=None):
    """(bars, source) of weekly candles (2026-11-01), `time` the ISO week's
    Monday as 'YYYY-MM-DD'.

    Folded from the daily series' days (_daily_bars: ONE feed's 1d rows,
    else its days folded from intraday rows, and today's forming day from
    the same feed's intraday rows alone), by ISO week from Monday 00:00
    UTC, each daily row in the week of its session (session_day). `since`
    is taken back to its Monday, so the first week is whole, and the rows
    are read from 12 hours before it: a Monday session stamped at Sunday
    22:00 UTC is that week's first day. The week that holds `now` is this
    week's FORMING candle, drawn as it stands; a week holding a suspect day
    is marked. No row is written and no feed is asked.

    THE TICK ONLY WHERE TODAY IS (2026-11-01). The widget welds the live
    quote onto a forming daily-family bar. This week's candle holds today
    only when its last day is today's forming candle, built from the same
    feed's intraday rows: exactly when the daily view's last candle takes
    the tick. When today's hours are another feed's (an eToro-routed
    instrument on Yahoo's days, its normal state), or nothing of today is
    stored yet, or today's day is the feed's stored daily bar, the candle
    stays `forming` (the week runs) and says in `no_tick` why it takes no
    tick (WEEK_NO_TICK): welded anyway, its close and high took the live
    price every 15 s and the 60 s refresh took them away again."""
    now = now or datetime.now(dt_tz.utc)
    notes = []
    first = None
    if since is not None:
        first = _monday(since)
        since = first - timedelta(hours=12)
    days, fam = _daily_bars(instrument, since=since, route=route, now=now,
                            notes=notes, words=_WEEK_WORDS,
                            day_of=session_day)
    if first is not None:
        # The half day read before the first Monday: a session of that
        # Monday stays, an hour or a stamp of the Sunday before goes.
        cut = first.strftime("%Y-%m-%d")
        days = [d for d in days if d["time"] >= cut]
    fam = fam or public_family(instrument.asset_class)
    this_week = _monday(now).strftime("%Y-%m-%d")
    today = now.astimezone(dt_tz.utc).strftime("%Y-%m-%d")

    def weeks(bars):
        out = fold(bars, week_of, "daily bar")
        if out and out[-1]["time"] == this_week:
            out[-1]["forming"] = True
            last = bars[-1]
            if not last.get("forming"):
                out[-1]["no_tick"] = WEEK_NO_TICK[
                    "out" if last["time"] < today else "closed"]
        return out

    if days:
        notes.insert(0, f"weekly candles folded from {label(fam, instrument)}"
                        f"'s days, ISO weeks from Monday 00:00 UTC")
    src = _source(instrument, fam, route, notes)
    bars = _finish(days, src, weeks)
    if bars and bars[-1].get("forming") and not any(
            n.startswith("this week's candle") for n in notes):
        notes.append("this week's candle is forming")
    return bars, src


def _daily_bars(instrument, *, since, route, now, notes, words,
                day_of=utc_day):
    """(bars, feed) of ONE feed's daily candles, and the legend's notes on
    `notes` in `words` (the daily_series body, 2026-11-01: the weekly view
    folds the same days). `day_of` labels a daily row from its stamp: the
    daily view keeps the UTC date (utc_day); the weekly view takes the
    session's (session_day), and so does the check of whether today's
    candle is in. Days folded from intraday rows are their UTC dates."""
    from market_data.models import PriceData

    def _rows(tf, tags):
        qs = PriceData.objects.filter(instrument=instrument, timeframe=tf,
                                      source__in=tags)
        if since is not None:
            qs = qs.filter(timestamp__gte=since)
        return qs.order_by("timestamp")

    fams = _families(instrument, "1d")
    fam = choose(instrument, "1d", fams, route, now, notes)
    bars = []
    newest = None
    if fam:
        rows = list(_rows("1d", fams[fam]["tags"]))
        bars = [_bar(p, day_of(p.timestamp)) for p in rows]
        newest = rows[-1].timestamp if rows else None
    if not bars:
        for tf in ("4h", "1h"):
            tf_fams = _families(instrument, tf)
            f = choose(instrument, tf, tf_fams, route, now)
            if not f:
                continue
            days = {}
            qs = _rows(tf, tf_fams[f]["tags"])
            cut = _venue_hole(tf_fams, f, route)
            if cut is not None:
                qs = qs.filter(timestamp__gt=cut)
            for p in qs:
                _fold(days, p.timestamp.strftime("%Y-%m-%d"), p)
            if days:
                bars = [days[k] for k in sorted(days)]
                fam = f
                # TODAY'S FOLDED DAY IS FORMING (2026-10-31): served as a
                # closed candle, the caption said "the last candle has
                # closed" while it traded (USDCNH has no Yahoo daily bar;
                # a fresh deployment has none for anything).
                if bars[-1]["time"] == now.strftime("%Y-%m-%d"):
                    bars[-1]["forming"] = True
                    notes.append(words["forming"].format(
                        label(f, instrument)))
                break
    elif newest is not None:
        forming = _forming(instrument, fam, newest, bars[-1]["time"], now)
        if forming is not None:
            bars.append(forming)
            notes.append(words["forming"].format(label(fam, instrument)))
        else:
            elsewhere = _today_elsewhere(instrument, fam, route,
                                         bars[-1]["time"], now)
            if elsewhere:
                notes.append(words["elsewhere"].format(
                    label(elsewhere, instrument), label(fam, instrument)))
    return bars, fam


def _fold(days, key, p):
    d = days.get(key)
    vol = float(p.volume) if p.volume else 0
    if d is None:
        days[key] = {"time": key, "open": float(p.open),
                     "high": float(p.high), "low": float(p.low),
                     "close": float(p.close), "volume": vol}
        return
    d["high"] = max(d["high"], float(p.high))
    d["low"] = min(d["low"], float(p.low))
    d["close"] = float(p.close)
    d["volume"] += vol


def _forming(instrument, fam, newest, last_label, now):
    """Today's candle from `fam`'s 1h (else 4h) rows of the UTC day, after
    the day the newest daily bar covers; None when there are none."""
    from market_data.models import PriceData

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    key = today.strftime("%Y-%m-%d")
    if key <= last_label:
        return None
    start = max(today, newest + timedelta(days=1))
    for tf in ("1h", "4h"):
        tags = [t for t in _families(instrument, tf).get(fam, {})
                .get("tags", [])]
        if not tags:
            continue
        days = {}
        for p in (PriceData.objects
                  .filter(instrument=instrument, timeframe=tf,
                          source__in=tags, timestamp__gte=start,
                          timestamp__lt=today + timedelta(days=1))
                  .order_by("timestamp")):
            _fold(days, key, p)
        if key in days:
            return dict(days[key], forming=True)
    return None


def _today_elsewhere(instrument, fam, route, last_label, now) -> str:
    """The feed whose intraday rows of today exist when `fam`'s do not
    (the routed venue's first), else "" (2026-10-31). Crypto routed to
    eToro: the daily series is Binance's, eToro's 1h rows replaced
    Binance's for today, and the EOD writes only closed klines, so the
    daily view ended on yesterday all day with nothing said. Today's
    candle is not built from another feed's bars (one feed per series);
    the legend says why it is not drawn."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if today.strftime("%Y-%m-%d") <= last_label:
        return ""
    found = set()
    for tf in ("1h", "4h"):
        for f, v in _families(instrument, tf).items():
            if f != fam and v["newest"] >= today:
                found.add(f)
    if not found:
        return ""
    return route if route in found else sorted(found)[0]


def positions_words(positions, src) -> str:
    """The legend's words when real position lines (the venue's prices)
    sit over candles of another feed (skeptic M4): a stop can look crossed,
    or far, by the basis alone."""
    venues = {family(p.get("venue")) for p in positions or []
              if not p.get("paper") and p.get("venue")}
    venues.discard(src.get("family"))
    venues.discard("")
    if not venues:
        return ""
    names = " and ".join(feed_name(v) for v in sorted(venues))
    return (f"Your position lines are {names} prices; the candles are "
            f"{src.get('what') or src.get('label')}.")


# ── Whose quote the hero prints ───────────────────────────────────────

def quote_label(tag, instrument) -> str:
    """"Yahoo GC=F", "OANDA stream", "eToro"."""
    fam = family(tag)
    t = str(tag or "").lower()
    if t.endswith("_ws") or t.endswith("_stream"):
        return f"{feed_name(fam)} stream"
    return label(fam, instrument)


def quote_facts(instrument, quote, *, route="", now=None) -> dict:
    """What the hero says beside the price: whose it is, how old, the
    stand-in words, whose bid/ask the ticket carries, whether the day
    change is the same feed's, and (venue-routed) the venue's last known
    price with its gap to the quote. Reads only."""
    from bot_program.venue_mark import age_words

    now = now or datetime.now(dt_tz.utc)
    out = {"source": None, "source_family": "", "source_label": "",
           "source_words": "", "stand_in": "", "quote_age_seconds": None,
           "age_words": "", "quote_at": None, "sides_source": None,
           "sides_words": "", "change_same_feed": None,
           "tick_bar": tick_bar(getattr(instrument, "asset_class", "")),
           "venue": None, "gap_pct": None}
    last = None
    if quote is not None:
        tag = str(getattr(quote, "source", "") or "")
        fam = family(tag)
        si = stand_in(fam, instrument.symbol)
        lab = quote_label(tag, instrument)
        out.update({"source": tag, "source_family": fam, "source_label": lab,
                    "source_words": lab + (f", {STAND_IN_WORDS[si]}"
                                           if si else ""),
                    "stand_in": si})
        at = getattr(quote, "updated_at", None)
        if at is not None:
            age = max(0, int((now - at).total_seconds()))
            out.update({"quote_age_seconds": age,
                        "age_words": age_words(age),
                        "quote_at": at.isoformat()})
        if getattr(quote, "bid", None) is not None or \
                getattr(quote, "ask", None) is not None:
            out["sides_source"] = tag
            out["sides_words"] = lab
        cs = str(getattr(quote, "change_source", "") or "")
        out["change_same_feed"] = bool(cs) and cs.lower() == tag.lower()
        out["change_source"] = cs
        if not out["change_same_feed"]:
            out["change_words"] = (
                f"The price is {lab}'s; the day change on this row was "
                + (f"measured by {quote_label(cs, instrument)}" if cs
                   else "measured by a feed not recorded")
                + ", so it is not printed beside it")
        try:
            last = float(quote.last) if quote.last is not None else None
        except (TypeError, ValueError):
            last = None
    venue = venue_last(instrument, route, now=now)
    out["venue"] = venue
    out["gap_words"] = ""
    if venue and last:
        gap = (last / venue["price"] - 1.0) * 100.0
        out["gap_pct"] = gap
        if abs(gap) >= GAP_WORDS_PCT:
            out["gap_words"] = f"quote vs {venue['label']} {gap:+.2f}%"
    return out


def venue_last(instrument, route, *, now=None):
    """The routed venue's last known price for `instrument`, from what the
    platform already holds: a real row's venue mark (bot_program
    .venue_mark) or the venue's newest stored 1h/4h candle. {price,
    price_text, at, age_s, age_words, via, label}, or None. Never a
    request.

    A CANDLE'S CLOSE IS AS OLD AS THE VENUE'S LAST ANSWER (2026-10-31).
    It was dated at min(now, the candle's end): for the forming 4h candle
    that is "now" for four hours, whenever the close was read, so when
    eToro went quiet (the six-hour mute, a 429, the pacing) the hero
    printed its last price as "0 s old", and that dated candle beat a
    newer position mark. The answer note it was checked against is keyed
    by symbol and interval only, and the public feed's fallback refreshes
    it. Now the close is dated by the venue's OWN answer note
    (market_data.bot_bars.last_venue_answer): at that answer, never past
    the candle's end; with no such note, at the candle's open, the one
    time the platform knows it had."""
    if not route:
        return None
    now = now or datetime.now(dt_tz.utc)
    best = None
    try:
        from bot_program import venue_mark
        from bot_program.models import AssetBotTrade
        for t in AssetBotTrade.objects.filter(
                symbol=instrument.symbol, paper=False,
                status__in=("OPEN", "CLOSE_PENDING"),
                metadata__broker=route):
            vm = venue_mark.last(t, now=now)
            if vm and (best is None or vm["at"] > best[0]):
                best = (vm["at"], vm["price"],
                        f"position {vm['via'] or 'mark'}")
    except Exception as e:  # noqa: BLE001 — a word beside the hero
        logger.info("[chart source] %s: venue marks unread: %s",
                    instrument.symbol, e)
    try:
        from market_data.bot_bars import INTERVAL_SECONDS, last_venue_answer
        from market_data.models import PriceData
        for tf in ("1h", "4h"):
            tags = _families(instrument, tf).get(route, {}).get("tags", [])
            if not tags:
                continue
            row = (PriceData.objects
                   .filter(instrument=instrument, timeframe=tf,
                           source__in=tags)
                   .order_by("-timestamp").first())
            if row is None:
                continue
            at = row.timestamp
            end = row.timestamp + timedelta(
                seconds=INTERVAL_SECONDS.get(tf, 3600))
            ans = last_venue_answer(row.source, instrument.symbol, tf) or {}
            if ans.get("at") and int(ans.get("newest_ms") or 0) >= \
                    int(row.timestamp.timestamp() * 1000):
                heard = datetime.fromtimestamp(float(ans["at"]), tz=dt_tz.utc)
                at = max(at, min(end, now, heard))
            if best is None or at > best[0]:
                best = (at, float(row.close), f"{tf} candle")
    except Exception as e:  # noqa: BLE001
        logger.info("[chart source] %s: venue candles unread: %s",
                    instrument.symbol, e)
    if best is None:
        return None
    at, price, via = best
    try:
        from core.price_format import price_decimals
        lq = getattr(instrument, "live_quote", None)
        dec = price_decimals(getattr(lq, "last", None) or price,
                             instrument.asset_class, instrument.symbol)
    except Exception:  # noqa: BLE001
        dec = 2
    from bot_program.venue_mark import age_words
    age = max(0, int((now - at).total_seconds()))
    return {"price": price, "price_text": f"{price:.{dec}f}",
            "at": at.isoformat(), "age_s": age, "age_words": age_words(age),
            "via": via, "label": feed_name(route)}
