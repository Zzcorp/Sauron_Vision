"""eTORO'S OWN QUOTES FOR THE OPEN REAL POSITIONS (2026-11-06).

The operator, after Sauron showed an open eToro position's P&L unlike
eToro's own: "On ne peut aussi encore augmenter to the maximum le taux de
refresh des valeurs et de eToro surtout svp?". The instruments of his open
real rows were marked from a keyless yfinance poll every 600 s, with no bid
and no ask, while eToro values a long at its bid and a short at its ask.

EVERY 30 s (config/celery.py "refresh-etoro-quotes", the fast queue; EVERY
15 s since 2026-11-13, BEAT_S, the operator: "aussi le refresh etoro par
minute est toujours trop long, je suggère 20-30 secondes non?") this
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
    P&L reads eToro's own figure from the sync's holdings (every 30 s);
  * a market the shut cadence holds shut (engine/etoro_rates.shut_max_age,
    E2: a forex or commodity weekend whose clock is known): its price does
    not move, and a quote rewritten every 15 s would read fresh;
  * an instrument the shared rates cache answered within OWN_FRESH_S, half
    the beat (another reader, the manage tick or the CLOSE button, has just
    asked). PREFETCH_FRESH_S (15 s) until 2026-11-13: every answer writes
    that cache, this beat's own included, so at a 15 s beat it skipped its
    own last answer and read each instrument every 30 s (measured: 1, 0, 1,
    0 reads in passes 15 s apart).

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
longest ago first: at 2 or 3 open positions every instrument every pass
(every 15 s); at 4 to 6 every 30 s, as before; at 20, each about every two
minutes, inside the hold over yfinance.

A PASS STOPS, never retried in a loop, at a budget refusal (the rest of the
family is the orders' and the closes'), at the venue's failure (a 429,
which grants the shared pause, a 5xx after the read's one bounded retry, a
transport failure, a refused redirect) and when PASS_BUDGET_S has gone; it
does not start while eToro is SICK (bot_program.venue_health) or while the
shared 429 pause holds. A failed read is noted on the venue's health as
every read is, from one pass per 30 s (NOTE_EVERY_S, 2026-11-13): the
passes the old 30 s beat ran, so a hiccup makes eToro sick no sooner and
no more often than before; the passes between read and note nothing
(EtoroTrader.health_quiet, venue_health.noting_slot).

UNDER THE SYNC'S SWITCHES (platform_master, broker_account_sync), read
inline as tasks.refresh_etoro_cells does: the component row is the sync's
verdict, and a beat every 15 s must not overwrite it. One pass at a time
(LOCK_KEY), and a run not started within 10 s is dropped (the beat's
expiry). No account figure, key or host in any line.

THE FEED SPEC'S ASKS (2026-11-06, its P-c; this beat is the interim
writer the eToro feed retires at the end of its F11, and none of these
extends what it writes):
  * A WRITE A HIGHER-RANKED FEED HOLDS IS COUNTED, NOT SILENT. Where a
    stream (OANDA's, Binance's, Finnhub's) or IBKR wrote the row within
    PRIORITY_HOLD_SECONDS, write_quote's precedence refuses eToro's
    (market_data.quotes.should_write False) and this beat did nothing
    there, silently. Each such refusal is counted ("refused"), the feed
    that held the row named ("held_by"), a pass with one says so in one
    INFO line, and the last pass and each UTC day's counts are kept
    (report) for manage.py etoro_budget, which prints them.
  * ITS TWELVE A MINUTE ARE A CAP. At most SINGLE_READS_PER_PASS requests
    a pass, a batch and the single reads after it together (a proven
    batch that left rows out was followed by six single reads: seven),
    and none past READS_PER_MINUTE in any rolling minute of a key (a run
    started late, up to its 25 s expiry, beside the next beat's run made
    three passes in a minute). Every read is still taken at P3. At the
    15 s beat (2026-11-13) a pass sends three: twelve a minute still, and
    a run late by its 10 s expiry beside the next beats' puts five passes
    in a minute, the fifth sending nothing.
  * The tick pushed to the browsers names its source
    (dashboard.consumers.push_quote_update), so a row's switch back to
    Yahoo's quote, once its position closed and the hold ended, shows.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone as dt_tz

logger = logging.getLogger(__name__)

#: The beat (config/celery.py "refresh-etoro-quotes"): 30 s from
#: 2026-11-06, 15 s since 2026-11-13 ("je suggère 20-30 secondes non?").
BEAT_S = 15
#: The most requests one pass sends (2026-11-06, the feed spec's P-c.3:
#: a batch and the single reads after it together; the single reads alone
#: before): 12 a minute at the beat, a fifth of the market family's start
#: rate (etoro_budget.RATE_MARKET_PER_MIN, 60). A batch is one request for
#: up to twenty instruments and counts as one; a retry or a cold /search
#: counts as the request it is. Six at the 30 s beat, three at 15 s
#: (2026-11-13): never slower than before for any number of instruments.
SINGLE_READS_PER_PASS = 3
#: THE BEAT'S OWN CAP (2026-11-06, P-c.3): no more requests than this in
#: any rolling minute (SENT_WINDOW_S) of one key, whatever the passes:
#: SINGLE_READS_PER_PASS at BEAT_S. The feed's request budget counts on it.
READS_PER_MINUTE = SINGLE_READS_PER_PASS * 60 // BEAT_S
#: Each key's requests of the last minute, [instant, ...] (the cap).
SENT_KEY = "etoro_quotes:sent:{kh}"
SENT_WINDOW_S = 60
#: The last pass, and each UTC day's counts (2026-11-06, P-c.1): what
#: manage.py etoro_budget prints, kept two days. Counts and the names of
#: the feeds that held a row: no price, no account figure.
LAST_KEY = "etoro_quotes:last"
DAY_KEY = "etoro_quotes:day:{day}"
RECORD_TTL_S = 2 * 86400
#: A pass starts no read past this many seconds, so it never runs into the
#: next beat (a read at P3 on a connection that never opens gives up after
#: about 9 s with its retry: 5 + 9 < 15). 20 s at the 30 s beat.
PASS_BUDGET_S = 5.0
#: THE BEAT'S OWN ANSWER (2026-11-13): an instrument the shared rates
#: cache answered within this many seconds is not asked again. Half the
#: beat, so the beat's own last answer (one beat old) is asked again and
#: another reader's that fresh is not; PREFETCH_FRESH_S (15 s) until the
#: 15 s beat, which then read every instrument every other pass.
OWN_FRESH_S = BEAT_S // 2
#: THE VENUE'S HEALTH FROM ONE PASS PER 30 s (2026-11-13,
#: venue_health.noting_slot): the passes the 30 s beat ran, per account.
#: 30 s less the beat's jitter.
NOTE_EVERY_S = 25
NOTE_KEY = "etoro_quotes:noting:{pk}"
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
    """The rotation's, the cap's and the records' clock (a seam: tests
    move it)."""
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
    OWN_FRESH_S (half the beat) by another reader. Never raises."""
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
            if etoro_rates.cached(client, symbol, max_age_s=OWN_FRESH_S):
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


def _sent_lately(kh) -> int:
    """The requests this beat sent for key hash `kh` in the last
    SENT_WINDOW_S (the cap, P-c.3). Never raises: unread, 0 (a pass whose
    cache cannot be read takes no lock either)."""
    try:
        held = _cache().get(SENT_KEY.format(kh=kh))
        now = _now()
        return sum(1 for at in (held if isinstance(held, list) else [])
                   if now - float(at) < SENT_WINDOW_S)
    except Exception:  # noqa: BLE001
        return 0


def _note_sent(kh, n) -> None:
    """Stamp `n` requests sent now for `kh` (the cap). Never raises."""
    if n <= 0:
        return
    try:
        c = _cache()
        key = SENT_KEY.format(kh=kh)
        now = _now()
        held = c.get(key)
        kept = [float(at) for at in (held if isinstance(held, list) else [])
                if now - float(at) < SENT_WINDOW_S]
        c.set(key, kept + [now] * int(n), 2 * SENT_WINDOW_S)
    except Exception:  # noqa: BLE001 — the budget still counts every read
        pass


def _wire(client) -> int:
    """The requests `client` has sent (EtoroTrader.wire_reads: every
    attempt, a retry and a cold /search included). Never raises."""
    try:
        return int(getattr(client, "wire_reads", 0) or 0)
    except (TypeError, ValueError):
        return 0


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


def _holder(inst, last) -> str:
    """The source that held `inst`'s LiveQuote row when write_quote refused
    eToro's priced answer FOR PRECEDENCE (market_data.quotes.should_write
    False: a higher-ranked feed wrote it within PRIORITY_HOLD_SECONDS),
    read right after the refusal by the rule write_quote applied; "" for
    any other refusal (no price, no instrument). Never raises."""
    try:
        if inst is None or not float(last or 0) > 0:
            return ""
        from market_data.models import LiveQuote
        from market_data.quotes import should_write
        existing = LiveQuote.objects.filter(instrument=inst).first()
        if existing is not None and not should_write(existing, SOURCE):
            return str(existing.source or "?")[:40]
    except Exception:  # noqa: BLE001 — unread: not counted
        pass
    return ""


def _write(symbol, tick, out) -> None:
    """Write one answer of eToro's to LiveQuote, counted in `out`:
    "written", or "refused" with the feed that held the row ("held_by")
    when write_quote's precedence refused it (P-c.1)."""
    from instruments.models import Instrument
    from market_data.quotes import write_quote
    if not isinstance(tick, dict):
        return
    inst = Instrument.objects.filter(symbol=symbol).first()
    if write_quote(symbol, last=tick.get("lastPrice"), source=SOURCE,
                   bid=_side(tick.get("bid")), ask=_side(tick.get("ask")),
                   instrument=inst):
        out["written"] += 1
        return
    held = _holder(inst, tick.get("lastPrice"))
    if held:
        out["refused"] += 1
        out.setdefault("held_by", {})[symbol] = held


def _read_account(client, symbols, out, started) -> str:
    """Ask eToro for `symbols` (already sorted) and write each answer: the
    batch when proven, else one read each. At most SINGLE_READS_PER_PASS
    requests in all, a batch and the single reads after it together, and
    none past READS_PER_MINUTE in the key's rolling minute (2026-11-06,
    P-c.3): what each call put on the wire is counted (EtoroTrader
    .wire_reads). Returns why the pass must stop ("" to go on). Inside the
    caller's P3 scope."""
    from bot_program.engine import etoro_rates
    kh = client._bkey()
    left = min(SINGLE_READS_PER_PASS, READS_PER_MINUTE - _sent_lately(kh))
    if left <= 0:
        return (f"the beat's {READS_PER_MINUTE} reads a minute are spent "
                f"(its own cap)")
    singles = list(symbols)
    if etoro_rates.CACHE and not etoro_rates.batch_waits() \
            and not etoro_rates.unproven():
        carried = symbols[:left * etoro_rates.BATCH_MAX_IDS]
        _note_asked(kh, carried)
        before = _wire(client)
        answers = client.tickers(carried)
        sent = max(0, _wire(client) - before)
        _note_sent(kh, sent)
        left -= sent
        out["asked"] += -(-len(carried) // etoro_rates.BATCH_MAX_IDS)
        singles = []
        for symbol in carried:
            answer = answers.get(symbol)
            if isinstance(answer, dict):
                _write(symbol, answer, out)
            elif answer is not None and etoro_rates.final(answer):
                return str(getattr(answer, "why", "") or answer)
            else:
                singles.append(symbol)
    for symbol in singles:
        if left <= 0:
            break
        if time.monotonic() - started > PASS_BUDGET_S:
            return f"the pass reached its {PASS_BUDGET_S:.0f} s"
        _note_asked(kh, [symbol])
        out["asked"] += 1
        before = _wire(client)
        try:
            tick = client.ticker(symbol)
        except Exception as e:  # noqa: BLE001 — sorted below
            sent = max(0, _wire(client) - before)
            _note_sent(kh, sent)
            left -= sent
            if _venue_failed(e):
                return str(getattr(e, "why", "") or e)[:160]
            logger.debug("eToro quotes: %s not read (%s)", symbol,
                         str(e)[:120])
            continue
        sent = max(0, _wire(client) - before)
        _note_sent(kh, sent)
        left -= sent
        _write(symbol, tick, out)
    return ""


def refresh() -> dict:
    """ONE PASS (the module docstring): {"accounts", "symbols", "asked"
    (requests sent), "written", "refused" (writes a higher-ranked feed's
    hold refused, P-c.1)}, with "held_by" ({symbol: that feed}) when one
    was, and "skipped" (why nothing was asked) or "stopped" (why the pass
    ended early) in words. The pass is kept for manage.py etoro_budget
    (_record). Never raises."""
    out = {"accounts": 0, "symbols": 0, "asked": 0, "written": 0,
           "refused": 0}
    try:
        off = _switched_off()
    except Exception as e:  # noqa: BLE001 — an unread switch is off
        off = f"the switches could not be read ({type(e).__name__})"
    if off:
        out["skipped"] = off
        _record(out, counted=False)
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
        _record(out, counted=True)
        try:
            c.delete(LOCK_KEY)
        except Exception:  # noqa: BLE001 — it expires on its own
            pass


def _day(at) -> str:
    return datetime.fromtimestamp(float(at), tz=dt_tz.utc).strftime(
        "%Y-%m-%d")


def _record(out, *, counted) -> None:
    """Keep this pass for manage.py etoro_budget (P-c.1): the last pass as
    it ended, with its instant, and, for a pass that ran under the lock
    (`counted`), its counts added to the UTC day's. One INFO line when a
    write was refused. Never raises."""
    refused = int(out.get("refused") or 0)
    if refused:
        held = ", ".join(f"{s}: {src}" for s, src
                         in sorted((out.get("held_by") or {}).items()))
        logger.info("eToro quotes: %d write%s refused, a higher-ranked feed "
                    "holds the row (%s)", refused, "" if refused == 1 else "s",
                    held)
    try:
        c = _cache()
        now = _now()
        c.set(LAST_KEY, dict(out, at=now), RECORD_TTL_S)
        if not counted:
            return
        key = DAY_KEY.format(day=_day(now))
        day = c.get(key)
        day = dict(day) if isinstance(day, dict) else {}
        for name in ("asked", "written", "refused"):
            day[name] = int(day.get(name) or 0) + int(out.get(name) or 0)
        day["held_by"] = dict(day.get("held_by") or {},
                              **(out.get("held_by") or {}))
        c.set(key, day, RECORD_TTL_S)
    except Exception as e:  # noqa: BLE001 — a record is a courtesy
        logger.debug("eToro quotes: the pass was not kept (%s)",
                     type(e).__name__)


def report(now=None) -> dict:
    """What manage.py etoro_budget prints of this beat (P-c.1): {"last":
    the last pass's counts and words with its "at", or None, "today": the
    UTC day's {"asked", "written", "refused", "held_by"}, or None, "day"}.
    Counts, words and feed names only. Never raises."""
    now = _now() if now is None else float(now)
    out = {"last": None, "today": None, "day": _day(now)}
    try:
        c = _cache()
        last = c.get(LAST_KEY)
        out["last"] = dict(last) if isinstance(last, dict) else None
        today = c.get(DAY_KEY.format(day=out["day"]))
        out["today"] = dict(today) if isinstance(today, dict) else None
    except Exception:  # noqa: BLE001 — unread: nothing to say
        pass
    return out


def _quiet_between_noting_passes(client, account_pk) -> None:
    """THE VENUE'S HEALTH FROM ONE PASS PER 30 s (2026-11-13): a pass that
    does not hold the account's noting slot (NOTE_EVERY_S) reads and
    writes as every pass does, and its client notes no READ failure
    (EtoroTrader.health_quiet); it still stops at its first failure. Set
    on every pass, the noting one included: the client may outlive one.
    Never raises: a slot that cannot be claimed notes."""
    try:
        from bot_program import venue_health
        noting = venue_health.noting_slot(NOTE_KEY.format(pk=account_pk),
                                          NOTE_EVERY_S, now=_now())
        client.health_quiet = (
            "" if noting else
            f"the held quotes note the venue's health from one pass per "
            f"30 s; this {BEAT_S} s pass reads only")
    except Exception as e:  # noqa: BLE001 — unread: noted, as before
        logger.debug("eToro quotes: the noting slot was not read (%s)",
                     type(e).__name__)


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
        _quiet_between_noting_passes(client, acct.pk)
        with etoro_budget.at_priority(etoro_budget.P3, "live quotes"):
            stop = _read_account(client, _stalest_first(client._bkey(), ask),
                                 out, started)
        if stop:
            out["stopped"] = stop[:200]
            logger.debug("eToro quotes: the pass stopped — %s", out["stopped"])
            return out
    return out
