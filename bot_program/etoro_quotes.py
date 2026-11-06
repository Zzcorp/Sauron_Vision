"""eTORO'S OWN QUOTES FOR THE OPEN REAL POSITIONS (2026-11-06).

The operator, after Sauron showed an open eToro position's P&L unlike
eToro's own: "On ne peut aussi encore augmenter to the maximum le taux de
refresh des valeurs et de eToro surtout svp?". The instruments of his open
real rows were marked from a keyless yfinance poll every 600 s, with no bid
and no ask, while eToro values a long at its bid and a short at its ask.

EVERY 30 s (config/celery.py "refresh-etoro-quotes", the fast queue) this
beat reads eToro's rates — bid, ask and last — for the instruments of the
OPEN REAL eToro rows, and writes them to LiveQuote under the source "etoro"
through market_data.quotes.write_quote: priority 70 against yfinance's 20,
so a yfinance poll cannot overwrite it for PRIORITY_HOLD_SECONDS (300 s)
while it is fresh, and the forex poll does not even ask Yahoo for a pair it
holds (market_data.tasks._held_symbols). A side eToro did not print is
written None, never 0 (a zero bid would value a long at nothing), and a
"0" answer (a shut market) writes nothing (write_quote refuses it).

WHICH ROWS: AssetBotTrade OPEN or CLOSE_PENDING, not the simulator's
(paper False), carried by eToro (metadata broker "etoro") in the LIVE
world (broker_env "live": a demo fill is stamped "paper"), not a working
entry (an order holds no position), of a user whose keyed eToro row is not
flagged Demo (the row's flag picks the world, broker_router). Morgul's
drift guard reads the same rows.

WHICH INSTRUMENTS: each once, less
  * an instrument whose platform quote is ANOTHER instrument
    (market_data.public_feed.yf_stand_in: Yahoo's front-month future for
    a metal, XAUUSD's GC=F, or a cash index, SPX500's ^GSPC): eToro's own
    rate written over it would put the basis into every paper mark of the
    symbol (bot_program.paper_exits: "a basis, not a crossing"). The row's
    P&L reads eToro's own figure from the sync's holdings (every 60 s);
  * a market the shut cadence holds shut (engine/etoro_rates.shut_max_age,
    E2: a forex or commodity weekend whose clock is known): its price does
    not move, and a quote rewritten every 30 s would read fresh;
  * an instrument the shared rates cache answered within PREFETCH_FRESH_S
    (another reader, the manage tick or the CLOSE button, has just asked).

THE eTORO REQUEST BUDGET (engine/etoro_budget, E1): every read is taken at
P3, the marks' priority, never P1 (a row eToro holds no stop for keeps its
own P1 mark in the manage tick; this beat only shows). A P3 take leaves
FLOOR_P3 of the market family to the orders, their last looks and the
closes' marks, which are never refused, and skips while the shared 429
pause holds. A refused take sends nothing and is no venue failure.

THE BATCH (engine/etoro_rates, E2): ONE batched read (twenty instruments a
request) once the shared rates cache is on and the operator's measurement
(manage.py etoro_rates_shape) proved the batch's shape; a row the batch
left out, or an unproven batch, is read alone. Until then one read an
instrument, at most SINGLE_READS_PER_PASS a pass, the instruments asked
longest ago first: at 2 or 3 open positions every instrument every pass;
at 20, each about every two minutes, inside the hold over yfinance.

A PASS STOPS, never retried in a loop, at a budget refusal (the rest of the
family is the orders' and the closes'), at the venue's failure (a 429,
which grants the shared pause, a 5xx after the read's one bounded retry, a
transport failure, a refused redirect) and when PASS_BUDGET_S has gone; it
does not start while eToro is SICK (bot_program.venue_health) or while the
shared 429 pause holds. A failed read is noted on the venue's health as
every read is.

UNDER THE SYNC'S SWITCHES (platform_master, broker_account_sync), read
inline as tasks.refresh_etoro_cells does: the component row is the sync's
verdict, and a beat every 30 s must not overwrite it. One pass at a time
(LOCK_KEY). No account figure, key or host in any line.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

#: The beat (config/celery.py "refresh-etoro-quotes").
BEAT_S = 30
#: The most single reads (one instrument a request) one pass sends: at
#: most 12 a minute, a fifth of the market family's start rate
#: (etoro_budget.RATE_MARKET_PER_MIN, 60). A batch is one request for up
#: to twenty instruments and counts as one.
SINGLE_READS_PER_PASS = 6
#: A pass starts no read past this many seconds, so it never runs into the
#: next beat (a read at P3 gives up after about 9 s with its retry).
PASS_BUDGET_S = 20.0
#: One pass at a time; a pass that died holds it this long at most.
LOCK_KEY = "etoro_quotes:pass"
LOCK_S = 60
#: When each instrument was last asked, per key hash: the rotation.
ASKED_KEY = "etoro_quotes:asked:{kh}"
ASKED_TTL_S = 3600
#: The quote's source: market_data.quotes.SOURCE_PRIORITY's "etoro" (70),
#: and the carrier key venue_mark.quote_stand_in reads as the venue's own.
SOURCE = "etoro"
#: The rows' statuses that hold a position at eToro.
OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")


def _now() -> float:
    """The rotation's clock (a seam: tests move it)."""
    return time.time()


def _cache():
    from django.core.cache import cache
    return cache


def _switched_off() -> str:
    """The words of the switch that holds the beat, or ""."""
    from core.platform_control import is_component_enabled
    for key in ("platform_master", "broker_account_sync"):
        if not is_component_enabled(key):
            return f"{key} is off"
    return ""


def _client_for(acct):
    """The live-world adapter on `acct`'s keys (a seam: tests hand a fake
    wire). None when the stored keys cannot be read."""
    k, u = acct.get_credentials()
    if not (k and u):
        return None
    from bot_program.engine.etoro_client import EtoroTrader
    return EtoroTrader(k, u, env="live")


def _accounts() -> list:
    """[(account, [(SYMBOL, asset class), ...])] for every keyed eToro row
    not flagged Demo whose user holds open real eToro rows, each symbol
    once, in the order the rows were opened."""
    from bot_program.models import AssetBotTrade, EtoroAccount
    out = []
    for acct in (EtoroAccount.objects.exclude(api_key_enc="")
                 .filter(demo=False).order_by("pk")):
        picked = {}
        for trade in (AssetBotTrade.objects
                      .filter(config__user_id=acct.user_id, paper=False,
                              status__in=OPEN_STATUSES)
                      .only("symbol", "asset_class", "metadata")
                      .order_by("pk")):
            meta = trade.metadata if isinstance(trade.metadata, dict) else {}
            if (meta.get("broker") != "etoro"
                    or meta.get("broker_env") != "live"
                    or meta.get("entry_working")):
                continue
            symbol = str(trade.symbol or "").strip().upper()
            if symbol and symbol not in picked:
                picked[symbol] = trade.asset_class
        if picked:
            out.append((acct, list(picked.items())))
    return out


def _wanted(client, rows) -> tuple:
    """(the symbols to ask, {symbol: why not}) of `rows`: not a stand-in,
    not a market the shut cadence holds shut, not answered within
    PREFETCH_FRESH_S by another reader. Never raises."""
    from bot_program.engine import etoro_rates
    from market_data.public_feed import yf_stand_in
    ask, left = [], {}
    for symbol, cls in rows:
        try:
            stand_in = yf_stand_in(symbol)
            if stand_in:
                left[symbol] = f"its platform quote is a {stand_in}"
                continue
            if etoro_rates.shut_max_age(symbol, cls):
                left[symbol] = "its market is shut"
                continue
            if etoro_rates.cached(client, symbol,
                                  max_age_s=etoro_rates.PREFETCH_FRESH_S):
                left[symbol] = "answered in the last seconds"
                continue
        except Exception as e:  # noqa: BLE001 — unread: asked
            logger.debug("eToro quotes: %s not sorted (%s)", symbol,
                         type(e).__name__)
        ask.append(symbol)
    return ask, left


def _stalest_first(kh, symbols) -> list:
    """`symbols`, the ones asked longest ago first (never asked first of
    all), by name between equals. Never raises."""
    try:
        asked = _cache().get(ASKED_KEY.format(kh=kh))
        asked = asked if isinstance(asked, dict) else {}
    except Exception:  # noqa: BLE001
        asked = {}

    def key(s):
        try:
            return (float(asked.get(s) or 0.0), s)
        except (TypeError, ValueError):
            return (0.0, s)
    return sorted(symbols, key=key)


def _note_asked(kh, symbols) -> None:
    """Stamp `symbols` asked now (the rotation). Never raises."""
    if not symbols:
        return
    try:
        c = _cache()
        key = ASKED_KEY.format(kh=kh)
        asked = c.get(key)
        asked = dict(asked) if isinstance(asked, dict) else {}
        now = _now()
        for s in symbols:
            asked[s] = now
        c.set(key, asked, ASKED_TTL_S)
    except Exception:  # noqa: BLE001 — the rotation is a courtesy
        pass


def _venue_failed(e) -> bool:
    """Does `e` end the pass? A budget refusal and the venue's failure (a
    429, a 5xx, a transport failure, a refused redirect) do; an answer
    about one instrument alone (an unknown spelling, a shape not measured,
    a row the batch left out, a 4xx about that id) does not."""
    if getattr(e, "budget_refused", False):
        return True
    if isinstance(e, LookupError):
        return False
    code = getattr(getattr(e, "response", None), "status_code", None)
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    if code is not None and 400 <= code < 500 and code != 429:
        return False
    return True


def _side(value):
    """A printed side as written: a positive number, else None."""
    try:
        return value if value is not None and float(value) > 0 else None
    except (TypeError, ValueError):
        return None


def _write(symbol, tick) -> bool:
    """Write one answer of eToro's to LiveQuote. True when written."""
    from instruments.models import Instrument
    from market_data.quotes import write_quote
    if not isinstance(tick, dict):
        return False
    return write_quote(symbol, last=tick.get("lastPrice"), source=SOURCE,
                       bid=_side(tick.get("bid")), ask=_side(tick.get("ask")),
                       instrument=Instrument.objects.filter(
                           symbol=symbol).first())


def _read_account(client, symbols, out, started) -> str:
    """Ask eToro for `symbols` (already sorted) and write each answer: the
    batch when proven, else one read each, at most SINGLE_READS_PER_PASS.
    Returns why the pass must stop ("" to go on). Inside the caller's P3
    scope."""
    from bot_program.engine import etoro_rates
    kh = client._bkey()
    singles = list(symbols)
    if etoro_rates.CACHE and not etoro_rates.batch_waits() \
            and not etoro_rates.unproven():
        carried = symbols[:SINGLE_READS_PER_PASS * etoro_rates.BATCH_MAX_IDS]
        _note_asked(kh, carried)
        answers = client.tickers(carried)
        out["asked"] += -(-len(carried) // etoro_rates.BATCH_MAX_IDS)
        singles = []
        for symbol in carried:
            answer = answers.get(symbol)
            if isinstance(answer, dict):
                out["written"] += int(_write(symbol, answer))
            elif answer is not None and etoro_rates.final(answer):
                return str(getattr(answer, "why", "") or answer)
            else:
                singles.append(symbol)
    for symbol in singles[:SINGLE_READS_PER_PASS]:
        if time.monotonic() - started > PASS_BUDGET_S:
            return f"the pass reached its {PASS_BUDGET_S:.0f} s"
        _note_asked(kh, [symbol])
        out["asked"] += 1
        try:
            tick = client.ticker(symbol)
        except Exception as e:  # noqa: BLE001 — sorted below
            if _venue_failed(e):
                return str(getattr(e, "why", "") or e)[:160]
            logger.debug("eToro quotes: %s not read (%s)", symbol,
                         str(e)[:120])
            continue
        out["written"] += int(_write(symbol, tick))
    return ""


def refresh() -> dict:
    """ONE PASS (the module docstring): {"accounts", "symbols", "asked"
    (requests sent), "written"}, with "skipped" (why nothing was asked) or
    "stopped" (why the pass ended early) in words. Never raises."""
    out = {"accounts": 0, "symbols": 0, "asked": 0, "written": 0}
    try:
        off = _switched_off()
    except Exception as e:  # noqa: BLE001 — an unread switch is off
        off = f"the switches could not be read ({type(e).__name__})"
    if off:
        out["skipped"] = off
        return out
    c = _cache()
    try:
        if not c.add(LOCK_KEY, 1, LOCK_S):
            out["skipped"] = "a pass is running"
            return out
    except Exception as e:  # noqa: BLE001 — no lock, no pass
        out["skipped"] = f"the lock could not be read ({type(e).__name__})"
        return out
    started = time.monotonic()
    try:
        return _pass(out, started)
    except Exception as e:  # noqa: BLE001 — a display beat never raises
        logger.warning("eToro quotes: the pass failed (%s)",
                       type(e).__name__)
        out["stopped"] = f"the pass failed ({type(e).__name__})"
        return out
    finally:
        try:
            c.delete(LOCK_KEY)
        except Exception:  # noqa: BLE001 — it expires on its own
            pass


def _pass(out, started) -> dict:
    from bot_program import venue_health
    from bot_program.engine import etoro_budget
    accounts = _accounts()
    if not accounts:
        out["skipped"] = "no open real eToro row"
        return out
    sick = venue_health.sick("etoro", "live")
    if sick:
        out["skipped"] = f"eToro is sick: {sick.get('words', '')}"[:200]
        return out
    for acct, rows in accounts:
        client = _client_for(acct)
        if client is None:
            continue
        out["accounts"] += 1
        pause = venue_health.pause_s(client)
        if pause > 0:
            out["skipped"] = (f"the shared 429 pause holds ({pause:.0f} s "
                              f"left)")
            continue
        ask, left = _wanted(client, rows)
        out["symbols"] += len(ask)
        if left:
            out.setdefault("left", {}).update(left)
        if not ask:
            continue
        with etoro_budget.at_priority(etoro_budget.P3, "live quotes"):
            stop = _read_account(client, _stalest_first(client._bkey(), ask),
                                 out, started)
        if stop:
            out["stopped"] = stop[:200]
            logger.debug("eToro quotes: the pass stopped — %s", out["stopped"])
            return out
    return out
