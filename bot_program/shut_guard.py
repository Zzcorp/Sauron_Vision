"""THE GUARD: no management order to eToro while a market is shut for a day
or more (2026-11-19; the operator: "oui pour le garde-fou").

A LIVE row had no market clock in the manage tick (asset_engine/base.py
manage_positions: only paper rows wait while their market is shut). Over a
weekend eToro shuts its currency pairs and its weekday-only commodities
(copper, platinum, palladium), yet the tick could send it the time stop's
close, the care's soft-stop close and its mirrored stop PATCH, the config
knobs' stop PATCH and the bot-side SL/TP close; and the pending-close drain
(bot_program/pending_closes.py) resent a refused close every five minutes
until the twelfth refusal put the row in ERROR, out of every reader.

THE SWITCH care_holds_while_shut, "Hold management while the market is
shut" (core.platform_control): a live-money switch, OFF on arrival, its ON
behind the trading PIN at /ops/. OFF, or a switch that cannot be read:
nothing here holds anything, and the tick and the drain are as they were.

ON, a row is HELD (held()) while all of this is true:
  * it is LIVE, in eToro's real or demo world: never a paper row;
  * eToro carries it: its carrier stamp (metadata["broker"], written at
    the fill by both lanes) says so, or, for a row with no stamp, the
    client the router hands it is eToro's;
  * its instrument, read as the router reads it (the Instrument row's
    class and exchange; the trade's class when there is no row), is inside
    a shut of a day or more (market_data.shut_bars.shut_for_a_day_now), on
    eToro's own published edges: a currency pair from Friday 16:30 to
    Sunday 17:05 New York (21:30 to 22:05 UTC in winter); a commodity on
    Globex's clock (metals and energy, an unknown exchange) from 30 minutes
    before Globex's Friday close to its Sunday reopen (21:30 to 23:00 UTC
    in winter), any other commodity on its own market clock; Christmas Day
    and New Year's Day stretch the weekend (Fri 2026-12-25: held from
    Thursday's close). eToro's all-week instruments (GOLD, OIL, SILVER,
    NATGAS, SPX500, NSDQ100: shut_bars.ALL_WEEK_ETORO_IDS) are never held,
    nor EURUSD, whose weekend hours at eToro are unsettled (shut_bars
    .UNSETTLED_WEEKEND_ETORO_IDS: if eToro trades it at weekends, a hold
    would leave only eToro's resting stop), nor a commodity filed under an
    exchange the venue does not keep (LME), nor any class outside
    shut_bars.HELD_CLASSES. Early closes are not modelled.

Held in the manage tick (hold_tick, asked before the row's mark is read):
the row's tick ends there. No mark is read, nothing is sent (no time stop,
no care close, no mirror or knob stop move, no bot-side SL/TP) and nothing
a send follows moves (the care's peak and soft stop, the trailing stop, the
mark sanity's memory). Only the time stop's warning runs, as for a paper
row. The first tick after the reopen manages the row as before, at the
reopen's price, through the mark sanity.

Held in the drain (hold_close, asked by retry_all_pending_closes before
retry_trade_close): the close is not resent and no attempt is counted, so
no "stranded" alert and no ERROR comes of a weekend; the drain takes the
row up again at the reopen. The CLOSE button's retry (manual_close
._retry_pending) calls retry_trade_close itself: it is the operator's own
act, and it goes through.

Untouched, whatever the switch: the kill switch, the CLOSE button, TAKE
TRADE, reconcile and its orphan booking, Morgul, and a working entry's poll
and withdrawal. The Orcs send nothing: their reading of a held row's tick
(observe.after_care, after the care) waits with it, and their bar wakes are
unchanged.

THE LINE. A held row says so in one plain line, in this module's log at
every held tick or pass, and on the row (metadata["shut_hold"]: the words,
the reopen, since when), written once a shut and read by nothing that
sends: "held: market shut until Sun 22 Nov 22:05 UTC (the guard): ...".
"""
from __future__ import annotations

import logging
from datetime import timezone as dt_tz
from types import SimpleNamespace

from django.utils import timezone

logger = logging.getLogger(__name__)

#: The switch (core.platform_control.LIVE_MONEY_SWITCHES).
SWITCH_KEY = "care_holds_while_shut"
#: The row's line (metadata[NOTE_KEY]).
NOTE_KEY = "shut_hold"
HELD_WORDS = "held: market shut until {until} (the guard)"
TICK_WORDS = (HELD_WORDS + ": nothing is sent to eToro; the row is managed "
                           "again at the reopen")
DRAIN_WORDS = (HELD_WORDS + ": the close is not resent and no attempt is "
                            "spent; the drain resumes at the reopen")

#: The weekday and month from fixed tables: no locale changes the words.
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
           "Oct", "Nov", "Dec")


def switch_on(cache=None) -> bool:
    """The guard's switch, read at call time; once a pass when `cache` (a
    dict that lives for one pass) is given. A missing row is OFF
    (core.platform_control.is_component_enabled); so is a row that cannot
    be read: the guard is never on by a failure."""
    key = ("shut_guard", SWITCH_KEY)
    if isinstance(cache, dict) and key in cache:
        return cache[key]
    try:
        from core.platform_control import is_component_enabled
        on = bool(is_component_enabled(SWITCH_KEY))
    except Exception as e:  # noqa: BLE001 (unread is OFF; said)
        logger.warning("[guard] %s unreadable (%s) — read as OFF",
                       SWITCH_KEY, type(e).__name__)
        on = False
    if isinstance(cache, dict):
        cache[key] = on
    return on


def _carrier(trade) -> str:
    meta = getattr(trade, "metadata", None)
    return str((meta if isinstance(meta, dict) else {}).get("broker")
               or "").strip().lower()


def carried_by_etoro(trade, client=None) -> bool:
    """eToro carries `trade`: its carrier stamp says so; a row with no
    stamp is eToro's when `client`, the one the router hands it, is eToro's
    adapter (capabilities.adapter_key). Another venue's stamp never is."""
    stamp = _carrier(trade)
    if stamp:
        return stamp == "etoro"
    if client is None:
        return False
    from bot_program.engine.capabilities import adapter_key
    return adapter_key(client) == "etoro"


def until_words(moment) -> str:
    """"Sun 22 Nov 22:05 UTC" for an aware datetime."""
    m = moment.astimezone(dt_tz.utc)
    return (f"{_DAYS[m.weekday()]} {m.day:02d} {_MONTHS[m.month - 1]} "
            f"{m:%H:%M} UTC")


def held(trade, client=None, *, now=None, cache=None):
    """{"closed", "reopens", "until"} while THE GUARD holds `trade` at
    `now` (the wall clock when None), the shut's start and its reopen as
    aware UTC datetimes and the reopen in words; None for every row it
    does not hold (the module docstring), with the switch OFF, and when
    anything cannot be read: such a row is managed as without the guard.
    `cache`: the pass's dict, so the switch is read once a pass. Never
    raises."""
    try:
        if getattr(trade, "paper", True):
            return None
        if not carried_by_etoro(trade, client):
            return None
        if not switch_on(cache):
            return None
        from bot_program.engine.paper_trader import _instrument_key
        from market_data.shut_bars import shut_for_a_day_now
        cls, exchange = _instrument_key(trade.symbol, trade.asset_class)
        shut = shut_for_a_day_now(
            SimpleNamespace(symbol=trade.symbol, asset_class=cls,
                            exchange=exchange),
            now or timezone.now())
        if shut is None:
            return None
        closed, reopens = shut
        return {"closed": closed, "reopens": reopens,
                "until": until_words(reopens)}
    except Exception as e:  # noqa: BLE001 — unread holds nothing; said
        logger.warning("[guard] %s #%s: not judged (%s: %s) — managed as "
                       "without the guard", getattr(trade, "symbol", "?"),
                       getattr(trade, "id", "?"), type(e).__name__, e)
        return None


def note(trade, hold, template) -> str:
    """Say the hold in one plain line: in the log, every time, and on the
    row (metadata[NOTE_KEY]) when the line or its reopen changed, so once a
    shut, merged under a row lock (no other writer's keys are lost).
    Returns the line. Never raises."""
    words = template.format(until=hold["until"])
    logger.info("[guard] %s #%s: %s", trade.symbol, trade.id, words)
    try:
        until = hold["reopens"].isoformat()
        current = (trade.metadata or {}).get(NOTE_KEY) or {}
        if current.get("words") == words and current.get("until") == until:
            return words
        from django.db import transaction

        from bot_program.models import AssetBotTrade
        with transaction.atomic():
            row = AssetBotTrade.objects.select_for_update().get(pk=trade.pk)
            meta = dict(row.metadata or {})
            before = meta.get(NOTE_KEY) or {}
            since = (before.get("since") if before.get("until") == until
                     else None)
            meta[NOTE_KEY] = {"words": words, "until": until,
                              "since": since or timezone.now().isoformat()}
            row.metadata = meta
            row.save(update_fields=["metadata"])
        trade.metadata = meta
    except Exception as e:  # noqa: BLE001 — the log line was said
        logger.warning("[guard] %s #%s: the line was not written on the "
                       "row: %s", getattr(trade, "symbol", "?"),
                       getattr(trade, "id", "?"), e)
    return words


def hold_tick(bot, trade, client) -> bool:
    """The manage tick's question, asked before the row's mark is read:
    True when the guard holds `trade` this tick. Its line is said, and it
    leaves the walk's batched mark snapshot (no later row's batch reads its
    rate). Never raises: what cannot be read holds nothing."""
    try:
        hold = held(trade, client,
                    cache=getattr(bot, "_tick_broker_cache", None))
        if hold is None:
            return False
        snap = getattr(bot, "_marks_snapshot", None)
        if isinstance(snap, dict):
            snap.pop(getattr(trade, "pk", None), None)
        note(trade, hold, TICK_WORDS)
        return True
    except Exception as e:  # noqa: BLE001 — managed as before; said
        logger.warning("[guard] %s: the tick's hold was not judged: %s",
                       getattr(trade, "symbol", "?"), e)
        return False


def hold_close(trade, *, cache=None) -> bool:
    """The drain's question for one claimed CLOSE_PENDING row: True when
    the guard holds it this pass. Its line is said; nothing is resent and
    no attempt is counted (the caller moves on). A row with no carrier
    stamp asks the router for its client, as retry_trade_close would.
    Never raises: what cannot be read holds nothing."""
    try:
        if getattr(trade, "paper", True) or not switch_on(cache):
            return False
        client = None
        if not _carrier(trade):
            from bot_program.engine.broker_router import client_for_symbol
            client = client_for_symbol(trade.config.user, trade.symbol,
                                       trade.config)
        hold = held(trade, client, cache=cache)
        if hold is None:
            return False
        note(trade, hold, DRAIN_WORDS)
        return True
    except Exception as e:  # noqa: BLE001 — drained as before; said
        logger.warning("[guard] %s: the drain's hold was not judged: %s",
                       getattr(trade, "symbol", "?"), e)
        return False
