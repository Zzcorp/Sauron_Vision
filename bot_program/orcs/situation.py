"""The measured situation an Orc is born into (spec §1.6), read from the
database only: no broker, no network, no model. bot_program/orcs/army.py
assigns the type from it, purely.

  persona and hold   the config's persona (personas.persona_of) and its
                     hold, else 72 h
  stop distance      |entry - the initial stop| (the stop the row opened
                     with, never a trailed one)
  ATR 1h / 4h / 1d   on the venue's own bars (source "etoro") first, else
                     on any stored bars, labelled "platform"
  spread             the entry's last-look quote, else the live quote
  shuts              every session shut inside the hold
                     (bot_program/orcs/sessions.py)
  prints             high-impact calendar events inside the hold on the
                     row's currencies (either leg of a pair; USD otherwise;
                     the care's sources, position_care.py:168-175)
  exotic legs        a forex leg outside risk_gate.THEME_CURRENCIES
  gap p90            the next shut's measured gap in R (orcs/gaps.py),
                     None while unmeasured
"""
import logging
from datetime import timedelta

from django.utils import timezone

from bot_program.orcs.constants import ATR_BARS, ATR_PERIOD, DEFAULT_HOLD_H

logger = logging.getLogger(__name__)

TIMEFRAMES = ("1h", "4h", "1d")
#: The bar refresh writes eToro's candles under its adapter's label
#: (market_data/bot_bars.py _source_tag).
VENUE_SOURCE = "etoro"


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def atr_of(symbol, tf):
    """(ATR, "etoro" | "platform") on the newest ATR_BARS bars, or
    (None, None) when too few are stored."""
    from signals.smc.dataframe import load_ohlcv
    from signals.smc.pivots import atr
    for source, label in ((VENUE_SOURCE, "etoro"), (None, "platform")):
        try:
            df = load_ohlcv(symbol, tf, ATR_BARS, source=source)
        except Exception as e:  # noqa: BLE001 — unread bars are no bars
            logger.info("[orcs] %s %s bars unread: %s", symbol, tf, e)
            df = None
        if df is None or len(df) <= ATR_PERIOD:
            continue
        try:
            value = float(atr(df, ATR_PERIOD)[-1])
        except Exception:  # noqa: BLE001
            continue
        if value > 0:
            return value, label
    return None, None


def _spread(trade):
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    quote = meta.get("entry_quote")
    if isinstance(quote, dict):
        bid, ask = _f(quote.get("bid")), _f(quote.get("ask"))
        if bid and ask and ask >= bid:
            return ask - bid, "entry_quote"
    try:
        from market_data.models import LiveQuote
        q = LiveQuote.objects.filter(instrument__symbol=trade.symbol).first()
        spread = _f(q.spread) if q is not None else None
        if spread is not None and spread >= 0:
            return spread, "live_quote"
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _instrument(symbol):
    try:
        from instruments.models import Instrument
        return (Instrument.objects.filter(symbol=symbol)
                .values("asset_class", "exchange").first()) or {}
    except Exception:  # noqa: BLE001
        return {}


def currencies(trade) -> list:
    """The currencies whose prints reach this row: either leg of a forex
    pair, the home currency (USD) for every other class."""
    sym = str(trade.symbol or "").upper()
    if str(trade.asset_class) == "forex" and len(sym) == 6:
        return [sym[:3], sym[3:]]
    return ["USD"]


def exotic_legs(trade) -> list:
    if str(trade.asset_class) != "forex":
        return []
    try:
        from portfolio.risk_gate import THEME_CURRENCIES
    except Exception:  # noqa: BLE001
        return []
    return [c for c in currencies(trade) if c not in THEME_CURRENCIES]


def _prints(trade, now, hold_h) -> int:
    try:
        from market_data.models import EconomicEvent

        from bot_program.position_care import EVENT_IMPACT, EVENT_SOURCES
        return (EconomicEvent.objects
                .filter(datetime__gte=now,
                        datetime__lte=now + timedelta(hours=hold_h),
                        source__in=EVENT_SOURCES,
                        impact__iexact=EVENT_IMPACT,
                        currency_affected__in=currencies(trade))
                .count())
    except Exception as e:  # noqa: BLE001 — an unread calendar is no print
        logger.info("[orcs] calendar unread: %s", e)
        return 0


def _crypto_weekend(now, hold_h) -> bool:
    """A Saturday or a Sunday (UTC) inside [now, now + hold]."""
    end = now + timedelta(hours=hold_h)
    day = now.date()
    while day <= end.date():
        if day.weekday() >= 5:
            return True
        day += timedelta(days=1)
    return False


def gap_p90_r(trade, now, stop_distance):
    """The next shut's measured gap p90 in R (bot_program/orcs/gaps.py:
    the weekend's, the overnight's, a never-shut class's 1h range), or None
    while it is unmeasured or the row has no R. Never raises."""
    if not stop_distance:
        return None
    try:
        from bot_program.orcs import gaps
        gap = gaps.next_shut_gap(trade.symbol, str(trade.asset_class or ""),
                                 now=now)
        return gaps.in_r(gap, stop_distance) if gaps.measured(gap) else None
    except Exception as e:  # noqa: BLE001 — an unread gap adds nothing
        logger.info("[orcs] %s: the gap was not read: %s", trade.symbol, e)
        return None


def situation_for(trade, cfg, *, manual=False, now=None) -> dict:
    from bot_program.orcs import sessions
    from bot_program.orcs.facts import initial_stop
    now = now or timezone.now()
    persona, hold = "", None
    try:
        from bot_program.personas import persona_for, persona_of
        persona = persona_of(cfg)
        p = persona_for(cfg)
        hold = _f((p.fields or {}).get("max_hold_hours")) if p else None
    except Exception:  # noqa: BLE001
        pass
    hold_h = hold or DEFAULT_HOLD_H
    entry, stop = _f(trade.entry_price), initial_stop(trade)
    stop_distance = abs(entry - stop) if entry and stop else None
    atrs, sources = {}, {}
    for tf in TIMEFRAMES:
        atrs[tf], sources[tf] = atr_of(trade.symbol, tf)
    spread, spread_source = _spread(trade)
    inst = _instrument(trade.symbol)
    cls = str(trade.asset_class or "")
    shuts = []
    try:
        for s in sessions.shuts_within(cls, trade.symbol, now, hours=hold_h,
                                       exchange=inst.get("exchange") or ""):
            shuts.append({"at": s["at"].isoformat() if s.get("at") else "",
                          "words": s.get("words") or "",
                          "kind": s.get("kind") or "",
                          "hours": s.get("hours")})
    except Exception as e:  # noqa: BLE001 — an unread clock is no shut
        logger.info("[orcs] %s: the session calendar was not read: %s",
                    trade.symbol, e)
    return {
        "asset_class": cls,
        "instrument_class": str(inst.get("asset_class") or cls),
        "exchange": str(inst.get("exchange") or ""),
        "symbol": str(trade.symbol or ""),
        "side": str(trade.side or ""),
        "manual": bool(manual),
        "persona": persona,
        "hold_h": float(hold_h),
        "stop_distance": stop_distance,
        "atr": atrs,
        "atr_source": sources,
        "spread": spread,
        "spread_source": spread_source,
        "shuts": shuts[:12],
        "crypto_weekend": (cls in sessions.NEVER_SHUTS
                           and _crypto_weekend(now, hold_h)),
        "prints": _prints(trade, now, hold_h),
        "exotic_legs": exotic_legs(trade),
        "gap_p90_r": gap_p90_r(trade, now, stop_distance),
        "operator_horizon_h": None,
        "at": now.isoformat(),
    }
