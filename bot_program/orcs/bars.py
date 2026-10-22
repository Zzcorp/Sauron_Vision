"""THE VENUE'S BARS, READ ONE WAY (spec §5.2, §1.4): the frames the menu, the
predicates, the playbook and the arms read, from one reader.

  venue first   load_ohlcv(symbol, tf, source="etoro") (PR O0b): the bar
                refresh writes eToro's candles under its adapter's label
                (market_data/bot_bars._source_tag), so a venue frame is the
                venue's own grid;
  one source    when the venue's frame is thin, the single source with the
                newest bar stands in, labelled "platform", NEVER mixed with
                the venue's in one frame (a stand-in's 4h grid is anchored
                elsewhere and two grids in one frame double its density);
  fresh         a frame is fresh while its newest bar ended within
                FRESH_BAR_LENGTHS bar lengths of OPEN market time (a
                weekend or a session shut is not staleness): read from
                core.exchange_status.market_clock and next_close_utc; a
                class that never shuts, or has no modelled hours, counts
                wall time.
  1d            THE VENUE'S DAILY FRAME IS ITS 4h BARS BY UTC DAY
                (2026-10-22). No 1d candle is ever asked or written: the
                nightly EOD job writes Yahoo's 1d bars at Yahoo's own
                anchor, every unfiltered 1d reader (the regime, the
                posture, the charts' daily candles) reads all 1d rows,
                and eToro's OneDay candle (00:00 UTC) stored beside them
                would have given those readers two bars a day. The frame
                is built in memory: the day's first open, its high, its
                low, its last close. When the venue's 4h bars give fewer
                than THIN_BARS days, the newest other source's stored 1d
                bars stand in, labelled "platform", as for any frame.
  until         a frame CUT at a past moment (the tail's menu, no
                look-ahead): only the bars complete at `until`, its
                freshness read at `until`.
  final         a bar that ended is a SNAPSHOT until the refresh's next
                pass rewrites it (it stores the forming candle): final once
                its successor is stored or BAR_REFRESH_S and a margin have
                gone by (final_bar). The predicates and the playbook's bar
                triggers read final bars only (2026-10-22).

A PriceData timestamp is the bar's OPEN (bot_bars), so a bar ends one span
later. Frames are memoised in the caller's per-pass dict (the tick's
`_tick_broker_cache`, the task's own), so one tick reads a (symbol, tf)
once whatever the number of arms. Reads only.
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from bot_program.orcs.constants import (BAR_FINAL_MARGIN_S, BAR_REFRESH_S,
                                        FRESH_BAR_LENGTHS)

logger = logging.getLogger(__name__)

VENUE_SOURCE = "etoro"
SPANS = {"5m": timedelta(minutes=5), "15m": timedelta(minutes=15),
         "1h": timedelta(hours=1), "4h": timedelta(hours=4),
         "1d": timedelta(days=1)}
#: Fewer venue bars than this and the frame is thin (the structure read's
#: own floor, brain/thesis_check.MIN_BARS).
THIN_BARS = 30
#: The open-time walk's step where the clock names no edge.
STEP = timedelta(minutes=15)
#: The open-time walk stops after this many clock reads.
MAX_STEPS = 400
CACHE_PREFIX = "orcs:frame"
DAILY_TF = "1d"
#: The 4h bars a daily frame reads per day it asks for (six a UTC day).
FOUR_H_PER_DAY = 6
#: A bar with no stored successor is final this long after its end.
BAR_FINAL_AFTER = timedelta(seconds=BAR_REFRESH_S + BAR_FINAL_MARGIN_S)


@dataclass
class Frame:
    symbol: str
    tf: str
    df: object
    swings: list = field(default_factory=list)
    source: str = ""
    newest_end: object = None
    fresh: bool = False
    n: int = 0

    @property
    def label(self) -> str:
        return source_label(self.source)

    @property
    def venue(self) -> bool:
        return self.source == VENUE_SOURCE

    @property
    def atr(self) -> Optional[float]:
        try:
            from signals.smc.pivots import atr as _atr
            v = float(_atr(self.df)[-1] or 0)
        except Exception:  # noqa: BLE001 — no ATR is None, never 0
            return None
        return v if v > 0 else None

    @property
    def last_close(self) -> Optional[float]:
        try:
            return float(self.df["close"].values[-1])
        except Exception:  # noqa: BLE001
            return None


def source_label(source) -> str:
    """"etoro" for the venue's own bars, "platform" for anything else."""
    return "etoro" if str(source or "") == VENUE_SOURCE else "platform"


def span_of(tf) -> timedelta:
    return SPANS.get(str(tf), timedelta(hours=1))


def _utc(ts):
    t = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    if getattr(t, "tzinfo", None) is None:
        from datetime import timezone as dt_tz
        t = t.replace(tzinfo=dt_tz.utc)
    return t


def final_bar(frame, now) -> Optional[tuple]:
    """(end, close) of the frame's newest FINAL bar, or None. A bar that
    ended is a snapshot until the refresh's next pass rewrites it: final
    once the frame holds its successor (the pass that stored the successor
    rewrote it too) or BAR_FINAL_AFTER has gone by since its end. The bar
    still forming is never final."""
    df = getattr(frame, "df", None)
    if df is None or not len(df):
        return None
    span = span_of(frame.tf)
    idx, last = df.index, len(df.index) - 1
    for i in range(last, -1, -1):
        end = _utc(idx[i]) + span
        if end > now:
            continue
        if i < last or now >= end + BAR_FINAL_AFTER:
            return end, float(df["close"].values[i])
    return None


def final_end(frame, now):
    """The end of the frame's newest FINAL bar (final_bar), or None."""
    got = final_bar(frame, now)
    return got[0] if got else None


def final_df(frame, now):
    """The frame's bars up to its newest FINAL one (final_bar): the forming
    bar and a snapshot not yet rewritten are cut. None without one."""
    end = final_end(frame, now)
    if end is None:
        return None
    span = span_of(frame.tf)
    keep = [_utc(t) + span <= end for t in frame.df.index]
    return frame.df[keep]


def _instrument(symbol):
    from instruments.models import Instrument
    return Instrument.objects.filter(symbol=symbol).first()


def _newest_other_source(symbol, tf, until=None):
    """The source (not the venue's) with the newest bar in this frame: one
    query, through the instrument's symbol."""
    from market_data.models import PriceData
    qs = PriceData.objects.filter(instrument__symbol=symbol, timeframe=tf)
    if until is not None:
        qs = qs.filter(timestamp__lte=until - span_of(tf))
    return (qs.exclude(source=VENUE_SOURCE).order_by("-timestamp")
            .values_list("source", flat=True).first())


def _load(symbol, tf, n, source, until=None):
    """The newest `n` bars of (symbol, tf, source) as load_ohlcv frames
    them; with `until`, only the bars complete at that moment."""
    from signals.smc.dataframe import load_ohlcv
    if until is None:
        return load_ohlcv(symbol, tf, bars=n, source=source)
    import pandas as pd

    from market_data.models import PriceData
    rows = list(PriceData.objects
                .filter(instrument__symbol=symbol, timeframe=tf,
                        source=source,
                        timestamp__lte=until - span_of(tf))
                .order_by("-timestamp")
                .values("timestamp", "open", "high", "low", "close",
                        "volume")[:n])
    if not rows:
        return None
    rows.reverse()
    df = pd.DataFrame([{
        "timestamp": r["timestamp"], "open": float(r["open"] or 0),
        "high": float(r["high"] or 0), "low": float(r["low"] or 0),
        "close": float(r["close"] or 0), "volume": float(r["volume"] or 0),
    } for r in rows])
    df.set_index("timestamp", inplace=True)
    return df


def _daily_from_4h(symbol, n, until=None):
    """The venue's daily frame from its own 4h bars, grouped by UTC date
    (eToro's OneDay anchor): the day's first open, its high, its low, its
    last close, its volume. The newest `n` days; None without bars. Built
    in memory: nothing is written."""
    df = _load(symbol, "4h", int(n) * FOUR_H_PER_DAY, VENUE_SOURCE, until)
    if df is None or not len(df):
        return None
    import pandas as pd
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df = df.set_axis(idx)
    days = df.groupby(idx.normalize())
    out = pd.DataFrame({"open": days["open"].first(),
                        "high": days["high"].max(),
                        "low": days["low"].min(),
                        "close": days["close"].last(),
                        "volume": days["volume"].sum()})
    return out.iloc[-int(n):]


def _swings(df):
    from bot_program.smart_money import SWING_LEFT, SWING_RIGHT
    from signals.smc.pivots import classify_swings, get_swings
    if df is None or len(df) < SWING_LEFT + SWING_RIGHT + 2:
        return []
    return classify_swings(get_swings(df, SWING_LEFT, SWING_RIGHT))


def frame(symbol, tf, *, asset_class="", now=None, n=200, prefer="etoro",
          cache=None, exchange="", until=None) -> Optional[Frame]:
    """The (symbol, tf) frame: the venue's bars when it holds THIN_BARS or
    more, else the newest single other source; None without bars. The
    venue's 1d is its 4h bars by UTC day (_daily_from_4h). `until` cuts
    the frame at a past moment (only the bars complete then). Never
    raises."""
    from django.utils import timezone
    now = now or timezone.now()
    key = (CACHE_PREFIX, str(symbol), str(tf), int(n),
           until.isoformat() if until is not None else None)
    if isinstance(cache, dict) and key in cache:
        return cache[key]
    out = None
    try:
        df, source = None, ""
        if prefer == VENUE_SOURCE:
            df = (_daily_from_4h(symbol, n, until) if str(tf) == DAILY_TF
                  else _load(symbol, tf, n, VENUE_SOURCE, until))
            source = VENUE_SOURCE
        if df is None or len(df) < THIN_BARS:
            other = _newest_other_source(symbol, tf, until)
            if other:
                alt = _load(symbol, tf, n, other, until)
                if alt is not None and len(alt) >= (len(df) if df is not None
                                                    else 0):
                    df, source = alt, other
        if df is not None and len(df):
            newest = df.index[-1]
            if getattr(newest, "tzinfo", None) is None:
                from datetime import timezone as dt_tz
                newest = newest.replace(tzinfo=dt_tz.utc)
            end = newest.to_pydatetime() + span_of(tf) \
                if hasattr(newest, "to_pydatetime") else newest + span_of(tf)
            out = Frame(symbol=str(symbol), tf=str(tf), df=df,
                        swings=_swings(df), source=str(source or ""),
                        newest_end=end, n=len(df),
                        fresh=fresh(end, tf, asset_class, symbol, now,
                                    exchange=exchange))
    except Exception as e:  # noqa: BLE001 — unread bars are no frame
        logger.info("[orcs] %s %s: bars unread: %s", symbol, tf, e)
        out = None
    if isinstance(cache, dict):
        cache[key] = out
    return out


def open_seconds(start, end, asset_class, symbol="", *, exchange="",
                 limit=None) -> float:
    """Seconds of OPEN market between start and end (stopping once past
    `limit`). A class that never shuts, or has no modelled hours, counts
    wall time."""
    if start is None or end is None or end <= start:
        return 0.0
    cls = str(asset_class or "").lower()
    from bot_program.orcs.sessions import NEVER_SHUTS
    wall = (end - start).total_seconds()
    if cls in NEVER_SHUTS:
        return wall
    from core.exchange_status import market_clock, next_close_utc
    total, t = 0.0, start
    for _ in range(MAX_STEPS):
        if t >= end or (limit is not None and total > limit):
            break
        try:
            clock = market_clock(cls, exchange or "", symbol or "", now_utc=t)
        except Exception:  # noqa: BLE001 — an unread clock reads open
            return wall
        if not clock.get("modelled"):
            return wall
        if clock.get("is_open"):
            try:
                close = next_close_utc(cls, exchange or "", symbol or "", t)
            except Exception:  # noqa: BLE001
                close = None
            nxt = close if close is not None and close > t else t + STEP
            nxt = min(nxt, end)
            total += (nxt - t).total_seconds()
            t = nxt
        else:
            reopens = clock.get("reopens")
            t = reopens if reopens is not None and reopens > t else t + STEP
    return total


def fresh(newest_end, tf, asset_class, symbol, now, *, exchange="") -> bool:
    """True while the open-market time since the newest bar's end is within
    FRESH_BAR_LENGTHS bar lengths."""
    if newest_end is None:
        return False
    limit = FRESH_BAR_LENGTHS * span_of(tf).total_seconds()
    if now <= newest_end:
        return True
    return open_seconds(newest_end, now, asset_class, symbol,
                        exchange=exchange, limit=limit) <= limit


def complete_bars_after(symbol, tf, after, now, *, prefer="etoro",
                        limit=2200, newest=False, final=False) -> tuple:
    """([bar], source): the COMPLETE bars of (symbol, tf) that start at or
    after `after` (None: every stored bar), oldest first, from the venue
    when it holds any there, else from the single newest other source.
    At most `limit` bars: the OLDEST of the window by default (the tail's
    catch-up walks forward from its last bar), the NEWEST with `newest`
    (a window measured back from now, the gap model's), returned oldest
    first either way. With `final` (the tail's walk, 2026-10-22), the
    newest bar counts only once it is FINAL (final_bar: its successor
    stored, or BAR_FINAL_AFTER gone by). Each bar: {ts, end, open, high,
    low, close, source}."""
    try:
        from market_data.models import PriceData
        inst = _instrument(symbol)
        if inst is None:
            return [], ""
        span = span_of(tf)
        # with `final`, the bar still forming is read too: it is the
        # successor that makes the one before it final
        qs = PriceData.objects.filter(instrument=inst, timeframe=tf,
                                      timestamp__lte=(now if final
                                                      else now - span))
        if after is not None:
            qs = qs.filter(timestamp__gte=after)
        source = ""
        if prefer == VENUE_SOURCE and qs.filter(
                source=VENUE_SOURCE).exists():
            source = VENUE_SOURCE
        else:
            source = (qs.exclude(source=VENUE_SOURCE).order_by("-timestamp")
                      .values_list("source", flat=True).first()) or ""
        if not source:
            return [], ""
        picked = qs.filter(source=source).values(
            "timestamp", "open", "high", "low", "close")
        if newest:
            rows = list(picked.order_by("-timestamp")[:limit])
            rows.reverse()
        else:
            rows = picked.order_by("timestamp")[:limit]
        out, successor = [], False
        for r in rows:
            if r["timestamp"] + span > now:
                successor = True          # the forming bar (`final` only)
                continue
            o, h, lo, c = (float(r["open"] or 0), float(r["high"] or 0),
                           float(r["low"] or 0), float(r["close"] or 0))
            if min(o, h, lo, c) <= 0 or h < lo:
                continue
            out.append({"ts": r["timestamp"], "end": r["timestamp"] + span,
                        "open": o, "high": max(h, o, c), "low": min(lo, o, c),
                        "close": c, "source": source})
        if final and out and not successor \
                and now < out[-1]["end"] + BAR_FINAL_AFTER:
            out.pop()                     # a snapshot the refresh rewrites
        return out, source
    except Exception as e:  # noqa: BLE001 — unread bars are no bars
        logger.info("[orcs] %s %s: bars after %s unread: %s", symbol, tf,
                    after, e)
        return [], ""
