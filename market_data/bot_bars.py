"""Write OHLCV bars for every symbol an enabled bot trades, from the broker
that bot trades through.

Why this exists: every technical rule loads 4h bars (signals/rules/
technical_rules.py) and the SMC composite rule is hard-coded to 4h, but no
code path ever wrote a 4h row. `load_ohlcv` returned None, every rule
returned None, and `AssetBot.decide()` fell through to
HOLD "no active signals" — the multi-asset bots were structurally
incapable of opening a position.

Design notes:
  * Bars come from the SAME venue the order fills on (Alpaca for stocks,
    OANDA for forex, Binance for crypto), so there is no feed/execution
    basis. This is also why it is preferred over buying a vendor feed.
  * Only symbols on enabled AssetBotConfigs are fetched — the universe
    stays small enough to run beside the 5-minute bot tick.
  * Paper-mode configs still get bars: paper bots must be able to decide,
    and the router returns a real market-data client for them anyway when
    credentials exist (falling back to PaperTrader, which is skipped).
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone as dt_tz
from decimal import InvalidOperation

from django.core.cache import cache

logger = logging.getLogger(__name__)

# The timeframes the rule layer actually reads. The LARGER one first: the
# keyless feed builds 4h from a single hourly download and remembers that
# frame for a few minutes, so the 1h request that follows is served from
# it — one download per symbol per pass instead of two.
DEFAULT_INTERVALS = ("4h", "1h")
DEFAULT_LIMIT = 200

# A breath between symbols on the keyless feed. Yahoo tolerates a steady
# trickle and cuts off a burst; a research fleet of 150 symbols is a burst
# without this, and 30 seconds of a ten-minute pass with it.
PUBLIC_FEED_PACE_S = 0.2


def _pace() -> None:
    time.sleep(PUBLIC_FEED_PACE_S)

# A venue that gave no bars for a symbol is not asked again for a while.
# One IBKR historical request the Gateway never answers costs the whole
# request timeout, and seven forex CFDs times two intervals is most of a
# ten-minute refresh spent waiting on a venue that has already said no —
# which is how the 2026-09-10 bar writer spent its afternoon. The memo
# is written only when the venue was actually asked and stayed mute, so
# it expires on its own and the venue gets one fresh chance per window.
MUTE_VENUE_MEMO_S = 6 * 3600


def _mute_key(source: str, symbol: str, interval: str) -> str:
    return f"bars:mute:{source}:{symbol}:{interval}"


def _venue_is_mute(source: str, symbol: str, interval: str) -> bool:
    try:
        return bool(cache.get(_mute_key(source, symbol, interval)))
    except Exception:  # noqa: BLE001 — a dead cache costs one request
        return False


def _remember_mute(source: str, symbol: str, interval: str) -> None:
    try:
        cache.set(_mute_key(source, symbol, interval), 1, MUTE_VENUE_MEMO_S)
    except Exception:  # noqa: BLE001
        pass


# THE eTORO CANDLE QUOTA (2026-10-07). eToro's quota is written nowhere
# (deploy/ETORO_DEPARTURE.md:643). This pass asked it two candle GETs per
# enabled (config, symbol), paper configs included, back to back, and kept
# asking after the first 429: on 2026-10-06 at 23:38:31-35 UTC at least
# seventeen refused klines in four seconds, at least ten of them /candles
# 429s (the venue's memory keeps only seven /search notes there, and every
# refused /search was noted). Those seven, most likely this pass's own
# cold ids, made eToro (live) sick and held real entries until 23:48.
# Now, for eToro only:
#   * each (source, symbol, interval) once per pass (bars are per Instrument);
#   * from eToro's own newest stored bar (it may have been stored while
#     forming) instead of 200 bars every ten minutes;
#   * real rows no enabled live config covers first, then live configs,
#     then paper; CANDLE_GAP_S per wire request the previous call sent;
#     none after CANDLE_PASS_MAX_S into the pass;
#   * none for the rest of the pass after its first 429, while eToro is
#     sick, or once the trading lane noted a 429 within
#     YIELD_AFTER_LIVE_429_S: the public feed fills those series exactly as
#     for a mute venue, and no series is muted for a 429;
#   * its reads are background reads: never noted on the venue's health,
#     never granting the adapter's 429 pause (EtoroTrader.klines).
CANDLE_GAP_S = 1.0
CANDLE_PASS_MAX_S = 420.0
BARS_PASS_MAX_S = 540.0
YIELD_AFTER_LIVE_429_S = 120.0
#: The headroom ramp's 429 (epoch seconds until which every candle pass
#: yields): market_data/candle_headroom.py writes it, _etoro_refusing reads
#: it. Nothing else sets it, so with the ramp never run it is never there.
HEADROOM_429_KEY = "bars:yield_until"
INCREMENT_SPARE_BARS = 2


def _mono() -> float:
    return time.monotonic()


def _candle_sleep(seconds: float) -> None:
    time.sleep(seconds)


def _etoro_world(client) -> str:
    """"live" or "demo" for an eToro client, "" for every other client."""
    try:
        from bot_program.engine.capabilities import adapter_key
        if adapter_key(client) != "etoro":
            return ""
        from bot_program.venue_health import world_of
        return world_of(client)
    except Exception:  # noqa: BLE001
        return ""


def _wire_reads(client) -> int:
    n = getattr(client, "wire_reads", 0)
    return n if isinstance(n, int) and not isinstance(n, bool) else 0


def _http_status(exc):
    """The HTTP status a requests error carries, or None."""
    try:
        code = int(getattr(getattr(exc, "response", None), "status_code", 0)
                   or 0)
    except (TypeError, ValueError):
        return None
    return code or None


def _etoro_refusing(world: str) -> str:
    """Why the bars must not ask eToro now, or "": the venue is sick, or
    the trading lane met its 429 within YIELD_AFTER_LIVE_429_S."""
    try:
        from bot_program import venue_health as vh
        if vh.sick("etoro", world):
            return f"eToro ({world}) is sick"
        hits = vh.recent_refusals("etoro", world,
                                  within_s=YIELD_AFTER_LIVE_429_S)
        if hits:
            return (f"the trading lane met eToro's HTTP 429 "
                    f"({hits[-1].get('where') or '?'}) within the last "
                    f"{YIELD_AFTER_LIVE_429_S:.0f}s")
        # the headroom ramp (market_data/candle_headroom.py, an operator's
        # command) provoked a 429 on purpose: background 429s are never
        # noted on the venue's health, so it leaves this marker for
        # YIELD_AFTER_LIVE_429_S and the next passes yield instead of
        # meeting the same 429
        until = cache.get(HEADROOM_429_KEY)
        if until and float(until) > time.time():
            return ("the candle headroom ramp met eToro's HTTP 429 within "
                    f"the last {YIELD_AFTER_LIVE_429_S:.0f}s")
    except Exception:  # noqa: BLE001 — an unreadable memory refuses nothing
        return ""
    return ""


def _etoro_window(inst, interval, source, limit, now=None) -> int:
    """How many of the newest bars to ask eToro for: from its own newest
    stored bar to now, plus INCREMENT_SPARE_BARS; `limit` when it has
    stored none or the gap is wider."""
    from market_data.models import PriceData
    span = INTERVAL_SECONDS.get(interval)
    if not span:
        return limit
    try:
        newest = (PriceData.objects
                  .filter(instrument=inst, timeframe=interval, source=source)
                  .order_by("-timestamp")
                  .values_list("timestamp", flat=True).first())
    except Exception:  # noqa: BLE001 — unreadable: the full window
        return limit
    if newest is None:
        return limit
    now = now or datetime.now(dt_tz.utc)
    behind = max(0.0, (now - newest).total_seconds()) / span
    return max(1, min(int(limit), math.ceil(behind) + INCREMENT_SPARE_BARS))


class _CandlePass:
    """One refresh pass: what it handled, and whether it may ask eToro.
    A stop reason ends eToro candles for that world for the REST of the
    pass, never for a while (2026-10-07)."""

    def __init__(self):
        self.started = _mono()
        self.seen: set = set()
        self.last_get = None
        self.extra = 0.0
        self.asked = 0
        self.left = 0
        self.stopped: dict = {}
        self.headers_said = False
        # The config symbols the deadline let a config reach, and the ones
        # it cut (2026-10-07): a cut symbol nothing reached is the
        # watchlist's to fill (refresh_bot_bars).
        self.reached: set = set()
        self.cut: set = set()
        # A pass that must give way (the Orcs' Mercenary tape, O1c): a
        # callable read before EVERY candle read; truthy ends eToro for
        # this pass. The bar pass leaves it None (unchanged).
        self.yield_to = None

    def past_deadline(self) -> bool:
        return _mono() - self.started >= BARS_PASS_MAX_S

    def may_ask(self, world: str) -> bool:
        if self.yield_to is not None:
            try:
                why = self.yield_to()
            except Exception:  # noqa: BLE001 — unreadable: give way
                why = "the lock it yields to is unreadable"
            if why:
                self.stopped.setdefault(
                    world, why if isinstance(why, str)
                    else "a bar pass started")
                return False
        if world in self.stopped:
            return False
        if self.last_get is not None:
            wait = CANDLE_GAP_S + self.extra - (_mono() - self.last_get)
            if wait > 0:
                _candle_sleep(wait)
        if _mono() - self.started >= CANDLE_PASS_MAX_S:
            self.stopped[world] = (f"the pass reached "
                                   f"{CANDLE_PASS_MAX_S:.0f}s")
            return False
        why = _etoro_refusing(world)
        if why:
            self.stopped[world] = why
            return False
        self.last_get = _mono()
        self.extra = 0.0
        self.asked += 1
        return True

    def spent(self, reads: int) -> None:
        """The last klines call sent `reads` wire requests (a cold id's
        /search, a 5xx retry): the next waits one gap per extra request."""
        self.extra = max(0, int(reads) - 1) * CANDLE_GAP_S

    def refused(self, world: str, what: str) -> None:
        self.stopped.setdefault(world, f"eToro answered HTTP 429 at {what}")

    def heard(self, client) -> None:
        if self.headers_said:
            return
        self.headers_said = True
        said = getattr(client, "last_rate_headers", None)
        logger.info("[bars] eToro's quota headers on a candle answer: %s",
                    said if isinstance(said, dict) and said else "none")

    def words(self) -> str:
        return "; ".join(why for _w, why in sorted(self.stopped.items()))


# WHAT THE SOURCE SAID, AND WHEN (2026-10-02). A 4h bar hours old while the
# market is open reads as a dead feed — and on a thin contract it is not:
# CBOT oats can go hours overnight without a print, and Yahoo writes no
# hourly bar for an hour that traded nothing. The writer asked, the source
# answered, it simply had nothing newer. Recorded per symbol and interval
# on every answer that carried rows, so the readiness checks
# (preflight_live._bar_verdict) can tell "the feed stopped" from "the
# market printed nothing": the first is a blocker, the second a note.
ANSWER_MEMO_S = 6 * 3600


def _answer_key(symbol: str, interval: str) -> str:
    return f"bars:answered:{symbol}:{interval}"


def _note_answer(symbol: str, interval: str, rows) -> None:
    """Remember that a source answered for (symbol, interval) now, and the
    newest bar it had. An empty answer is not an answer: nothing is
    written, and an old note runs out on its own."""
    try:
        newest = max(int(r[0]) for r in (rows or []) if r and len(r) >= 6)
    except (ValueError, TypeError):
        return
    try:
        prev = cache.get(_answer_key(symbol, interval)) or {}
        if prev.get("at") and time.time() - float(prev["at"]) < 60 \
                and int(prev.get("newest_ms") or 0) > newest:
            newest = int(prev["newest_ms"])   # two sources in one pass
        cache.set(_answer_key(symbol, interval),
                  {"at": time.time(), "newest_ms": newest}, ANSWER_MEMO_S)
    except Exception:  # noqa: BLE001 — a dead cache costs the note only
        pass


def last_answer(symbol: str, interval: str) -> "dict | None":
    """{"at": epoch seconds, "newest_ms": the newest bar's open, epoch ms}
    of the last source answer for (symbol, interval), or None."""
    try:
        return cache.get(_answer_key(symbol, interval)) or None
    except Exception:  # noqa: BLE001
        return None


# THE VENUE'S OWN ANSWER (2026-10-31). The note above is any source's: the
# public feed's fallback and the watchlist pass refresh it too, so it
# cannot say when the VENUE last answered. The hero dates a venue
# candle's close by it (dashboard.chart_source.venue_last): dated by the
# shared note, eToro's forming 4h close read "0 s old" for hours after
# eToro went quiet. This one is written only from a venue's answer, keyed
# by its source tag, and names the newest bar the writer accepted.
def _venue_answer_key(source: str, symbol: str, interval: str) -> str:
    return f"bars:venue_answered:{source}:{symbol}:{interval}"


def _note_venue_answer(source: str, symbol: str, interval: str, rows,
                       at=None) -> None:
    """Remember that venue `source` answered `rows` (the bars the writer
    accepted) for (symbol, interval) at `at` (epoch seconds, now by
    default). No rows, no note."""
    try:
        newest = max(int(r[0]) for r in (rows or []) if r and len(r) >= 6)
    except (ValueError, TypeError):
        return
    try:
        cache.set(_venue_answer_key(source, symbol, interval),
                  {"at": float(at if at is not None else time.time()),
                   "newest_ms": newest}, ANSWER_MEMO_S)
    except Exception:  # noqa: BLE001 — a dead cache costs the note only
        pass


def last_venue_answer(source: str, symbol: str,
                      interval: str) -> "dict | None":
    """{"at", "newest_ms"} of venue `source`'s last answer for (symbol,
    interval), or None."""
    try:
        return cache.get(_venue_answer_key(source, symbol, interval)) or None
    except Exception:  # noqa: BLE001
        return None


def _client_for(user, symbol, cfg):
    """Market-data client for a symbol, or None when only paper is available.

    PaperTrader reads bars back out of PriceData, so using it here would be
    a no-op loop that writes nothing.
    """
    from bot_program.engine.broker_router import client_for_symbol
    from bot_program.engine.paper_trader import PaperTrader

    # purpose="data": this writer only reads bars, and on IBKR it must not
    # share the trader's clientId — see bot_program/engine/ibkr_sessions.
    client = client_for_symbol(user, symbol, cfg, purpose="data")
    if isinstance(client, PaperTrader):
        # Paper configs short-circuit the router; retry with mode ignored so
        # market data still comes from the real venue when creds exist.
        if getattr(cfg, "mode", "paper") == "paper":
            client = client_for_symbol(user, symbol, None, purpose="data")
        if isinstance(client, PaperTrader):
            return _public_market_data_client(cfg)
    return client


def _public_market_data_client(cfg):
    """A keyless client for venues whose market data is public.

    Requiring broker credentials for BARS was a structural dead end on a
    fresh install: no keys meant no bars, no bars meant no indicators and no
    rule could ever fire, so the platform could not produce the evidence it
    needed to justify connecting a broker in the first place.

    Crypto uses Binance public klines; stocks, ETFs, indices, commodity
    futures and FX majors use Yahoo. Options are absent deliberately —
    there is no free chain source worth trusting.

    Deliberately the LIVE endpoint even for paper configs: testnet klines
    are synthetic, and a strategy validated against invented candles has
    been validated against nothing.
    """
    try:
        from market_data.public_feed import public_feed_for
        return public_feed_for(getattr(cfg, "asset_class", "") or "")
    except Exception as e:
        logger.warning("[bars] public market-data client unavailable: %s", e)
        return None


def _venue_symbol(client, symbol: str) -> str:
    """Platform spelling -> the spelling THIS client's venue lists.

    Binance is the only wired venue whose client maps nothing of its own:
    OANDA translates inside `klines` (`_to_oanda_symbol`), Alpaca and Yahoo
    take the platform symbol as-is. Asking Binance for BTCUSD is not an
    error — /api/v3/klines answers an empty list or a 400 — so an
    untranslated crypto config quietly received no bars at all, every rule
    on it returned None, and the bot could only ever HOLD. That is exactly
    the failure this module exists to prevent, reintroduced one symbol
    spelling at a time.
    """
    try:
        from bot_program.engine.binance_client import BinanceClient
        from bot_program.engine.binance_futures_client import (
            BinanceFuturesClient,
        )
    except Exception:      # pragma: no cover - import-time breakage only
        return symbol
    if not isinstance(client, (BinanceClient, BinanceFuturesClient)):
        return symbol
    from market_data.management.commands.backfill_bars import venue_symbol
    return venue_symbol(symbol)


def _source_tag(client) -> str:
    """The provenance a client's bars are written under.

    One feed, one spelling. The scheduled path stripped "Trader" and
    "Client" from the class name but not "Feed", so the same Yahoo feed
    wrote `yfinancefeed_public` for a config with no broker and
    `yfinance_public` from the fallback and from backfill_bars — and an
    audit of the keyless rows by either spelling missed the other half.
    """
    name = type(client).__name__
    for word in ("Trader", "Client", "Feed"):
        name = name.replace(word, "")
    tag = name.lower() or "broker"
    if getattr(client, "_sv_public_feed", False):
        tag += "_public"
    return tag


#: PriceData.volume is a BigIntegerField.
_BIGINT_MAX = 2 ** 63 - 1


def _volume(raw) -> int:
    """A bar's volume as the column stores it; 0 when the venue gave none.

    The volume is never the reason a bar is lost (2026-09-29). A venue
    candle can carry `"volume": null`; eToro's adapter turned it into the
    text "None", `int(float("None"))` raised, and the whole bar was
    counted as skipped, its price with it. A bar without a volume still
    has a price.
    """
    if raw is None:
        return 0
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(value) or value <= 0:
        return 0
    return min(int(value), _BIGINT_MAX)


def _upsert_rows(inst, interval, rows, source) -> tuple[int, int]:
    """Persist Binance-style kline rows. Returns (written, skipped).

    A row the database refuses is skipped and said, never raised: one
    unwritable bar used to abort the refresh of the whole config.

    A bar that cannot have traded is skipped too (2026-10-31,
    market_data.bar_shape.parse): a price that is not a finite number, or
    one outside 0 < low <= min(open, close) <= max(open, close) <= high.
    Only `ts <= 0` and `close <= 0` were refused, so a bar with a low of 0
    or a high under its open was stored, drawn as a wick to zero and read
    by every ATR stop on the symbol. A real bar always passes."""
    from django.db import DatabaseError

    from market_data.bar_shape import parse
    from market_data.models import PriceData

    written = skipped = 0
    refused = None
    for row in rows or []:
        try:
            bar = parse(row)
            if bar is None:
                skipped += 1
                continue
            ts_ms, open_, high, low, close = bar
            PriceData.objects.update_or_create(
                instrument=inst, timeframe=interval,
                timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=dt_tz.utc),
                defaults={
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": _volume(row[5]),
                    "source": source,
                },
            )
            written += 1
        except (ValueError, TypeError, InvalidOperation, IndexError):
            skipped += 1
        except (DatabaseError, OverflowError) as e:
            skipped += 1
            refused = refused or e
    if refused is not None:
        logger.warning("[bars] %s %s: the database refused %d %s bar(s): %s",
                       getattr(inst, "symbol", inst), interval, skipped,
                       source, refused)
    return written, skipped


def _every_bar_impossible(rows) -> bool:
    """True when `rows` is a non-empty answer none of whose bars could have
    traded (market_data.bar_shape.parse refuses every one)."""
    from market_data.bar_shape import parse
    return bool(rows) and all(parse(r) is None for r in rows)


def _possible_rows(rows) -> list:
    """The rows of an answer the writer accepts (market_data.bar_shape
    .parse), in order (2026-10-31). The venue's window, its staleness and
    its mark are read from these alone: a refused newest bar (eToro's
    forming candle with no low) still widened the eviction over the
    public stand-in in its slot, and its stamp made the window look
    fresh, so the slot was emptied and nothing filled it."""
    from market_data.bar_shape import parse
    return [r for r in (rows or []) if parse(r) is not None]


def _write_venue_window(inst, interval, rows, source) -> tuple[int, int, int]:
    """Write a venue's answer, THEN give its window back to it.

    Returns (written, skipped, evicted). The public feed's stand-in rows
    inside the venue's window go only once the venue's own bars are in the
    table, in the same transaction. 2026-09-29: the eviction ran first,
    none of eToro's 200 fresh BTCUSD bars reached the table, and every ten
    minutes the refresh deleted the stand-ins and wrote nothing in their
    place. The table kept the bars from before the venue's window and
    nothing after, so an armed bot read a 4h candle 33 days old. A venue
    answer that writes nothing now evicts nothing, and the caller falls
    back to the public feed as for a mute venue.

    The window is the WRITTEN bars' (2026-10-31, _possible_rows): a bar
    the writer refused leaves its slot to the stand-in already there.
    """
    from django.db import DatabaseError, transaction

    try:
        with transaction.atomic():
            written, skipped = _upsert_rows(inst, interval, rows, source)
            evicted = (_evict_stand_in_rows(inst, interval,
                                            _possible_rows(rows))
                       if written else 0)
    except DatabaseError as e:
        logger.warning("[bars] %s %s: writing %s's window failed, nothing "
                       "changed: %s", getattr(inst, "symbol", inst), interval,
                       source, e)
        return 0, len(rows or []), 0
    return written, skipped, evicted


def _stamp_venue_rows(client, symbol, interval, rows) -> int:
    """THE VENUE'S CANDLE IS THE VENUE'S PRICE (2026-10-08).

    The venue just answered its own candles for `symbol` — for every
    symbol a live config trades, and for every real row no enabled live
    config covers (_held_real_rows: the manual lane, a config switched off
    by hand or by the kill switch). The newest candle's close is stamped
    as the venue mark (bot_program.venue_mark.stamp_rows) on the open real
    rows of that symbol this venue carries, at the candle's end (now, for
    the candle still forming): no request is added, and a row no manage
    tick reaches is still valued at its own venue's rate, at most one pass
    (600 s) old, never at the platform's quote of another instrument.
    Whether eToro's close is a bid, a mid or a last print is unmeasured;
    the tick's own read replaces it whenever the tick runs. A stamp newer
    than the candle is kept. Returns how many rows were stamped. Never
    raises, and only a venue's answer reaches it (never the public feed's,
    never the fallback's)."""
    try:
        if getattr(client, "_sv_public_feed", False):
            return 0
        from bot_program.engine.capabilities import adapter_key
        carrier = adapter_key(client)
        if not carrier:
            return 0
        best = None
        for row in rows or []:
            try:
                ts, close = int(row[0]), float(row[4])
            except (TypeError, ValueError, IndexError):
                continue
            if close > 0 and math.isfinite(close) and \
                    (best is None or ts > best[0]):
                best = (ts, close)
        if best is None:
            return 0
        span = INTERVAL_SECONDS.get(interval, 3600)
        at = datetime.fromtimestamp(best[0] / 1000 + span, tz=dt_tz.utc)
        from bot_program import venue_mark
        return venue_mark.stamp_rows(symbol, best[1], carrier=carrier,
                                     at=at, via="candle")
    except Exception as e:  # noqa: BLE001 — a stamp never costs a bar
        logger.info("[bars] %s %s: the venue mark was not stamped: %s",
                    symbol, interval, e)
        return 0


def refresh_bars_for_config(cfg, *, intervals=DEFAULT_INTERVALS,
                            limit=DEFAULT_LIMIT, pass_state=None,
                            cut=True, stamp_marks=True,
                            venue_only=False) -> dict:
    """Fetch and persist bars for every symbol on one bot config.

    `pass_state` (2026-10-07) is the refresh pass this config belongs to
    (_CandlePass: the dedup, the eToro pacing and stop); a call without
    one is a pass of its own. `cut=False` keeps every symbol past the
    pass's deadline: the held real rows (_held_real_rows) are never cut.
    Each symbol lands in the pass's `reached` or `cut` set. `stamp_marks`
    False (the Orcs' parts, 2026-10-16) writes the bars and stamps no
    venue mark on any row: the Orcs' bars are evidence, never a price for
    a row. `venue_only` (the Orcs' tape, O1c) asks eToro alone: a symbol
    whose client is not eToro's is skipped (counted under
    "venue_only_skipped"), and no public-feed fallback runs in either
    branch: a 15m or 5m frame is the venue's or nothing."""
    from instruments.models import Instrument

    state = pass_state if pass_state is not None else _CandlePass()
    out = {"symbols": 0, "bars": 0, "skipped": 0, "errors": 0, "no_client": 0,
           "fallback": 0, "deduped": 0, "not_reached": 0}
    if venue_only:
        out["venue_only_skipped"] = 0
    for symbol in (cfg.symbols or []):
        if cut and state.past_deadline():
            out["not_reached"] += 1
            state.cut.add(symbol)
            continue
        state.reached.add(symbol)
        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            logger.warning("[bars] no Instrument row for %s — skipping", symbol)
            out["errors"] += 1
            continue

        client = _client_for(cfg.user, symbol, cfg)
        if client is None:
            # Distinct from `errors`, which means "no Instrument row".
            # Operators scan errors for real breakage; a missing broker is a
            # configuration state with a different remedy, and at WARNING
            # because it means this symbol can never produce a decision.
            logger.warning(
                "[bars] no market-data client for %s (%s) — this symbol will "
                "produce no bars, no indicators and no signals until broker "
                "credentials exist for that asset class", symbol, cfg.asset_class)
            out["no_client"] += 1
            continue

        source = _source_tag(client)
        world = _etoro_world(client)
        if venue_only and not world:
            out["venue_only_skipped"] += 1
            continue
        out["symbols"] += 1
        fetch_symbol = _venue_symbol(client, symbol)
        fetched = False
        for interval in intervals:
            # ONCE PER PASS (2026-10-07): bars are written per Instrument,
            # so the first config to reach a series handles it, whatever
            # the outcome, and every later one skips it.
            key = (source, symbol, interval)
            if key in state.seen:
                out["deduped"] += 1
                continue
            state.seen.add(key)
            fetched = True
            rows = []
            asked = False
            refused = False
            if _venue_is_mute(source, symbol, interval):
                logger.info("[bars] %s %s: %s gave no bars within the last "
                            "%dh — public feed directly", symbol, interval,
                            source, MUTE_VENUE_MEMO_S // 3600)
            elif world and not state.may_ask(world):
                # eToro is not asked for the rest of this pass: the public
                # feed fills it below exactly as for a mute venue.
                state.left += 1
            else:
                asked = True
                want = (_etoro_window(inst, interval, source, limit)
                        if world else limit)
                before = _wire_reads(client)
                try:
                    rows = client.klines(fetch_symbol, interval=interval,
                                         limit=want)
                except Exception as e:
                    logger.warning("[bars] klines(%s, %s) failed: %s",
                                   symbol, interval, e)
                    out["errors"] += 1
                    rows = []
                    if world and _http_status(e) == 429:
                        refused = True
                        at = getattr(client, "last_read", "") or "candles"
                        state.refused(world, f"/{at} in klines({symbol}, "
                                             f"{interval})")
                        logger.warning(
                            "[bars] eToro answered HTTP 429 to /%s in "
                            "klines(%s, %s) — no more eToro candles this "
                            "pass; quota headers: %s", at, symbol, interval,
                            getattr(client, "last_rate_headers", None)
                            or "none")
                else:
                    if world:
                        state.heard(client)
                finally:
                    if world:
                        state.spent(max(1, _wire_reads(client) - before))
                _note_answer(symbol, interval, rows)
            if getattr(client, "_sv_public_feed", False):
                # The keyless feed IS the fallback: what it gave is written
                # as it is, and nothing backs it up.
                written, skipped = _upsert_rows(inst, interval, rows, source)
                out["bars"] += written
                out["skipped"] += skipped
                continue

            written = 0
            good = _possible_rows(rows)
            if rows:
                # THE VENUE ANSWERED: ITS WINDOW IS ITS OWN. Its bars are
                # written, then the stand-in rows inside the window it
                # returned go, so that window holds one grid, the venue's.
                # History behind the window (a backfilled year) stays, and
                # so does anything newer than it (see _evict_stand_in_rows).
                # The window, the mark and the staleness below are the
                # accepted bars' (`good`, 2026-10-31).
                written, skipped, evicted = _write_venue_window(
                    inst, interval, rows, source)
                out["bars"] += written
                out["skipped"] += skipped
                if written:
                    _note_venue_answer(source, symbol, interval, good)
                if written and stamp_marks:
                    _stamp_venue_rows(client, symbol, interval, good)
                if evicted:
                    logger.info("[bars] %s %s: %s answered — %d public-feed "
                                "stand-in bars in its window gave way to "
                                "the venue's", symbol, interval, source,
                                evicted)
                if not written:
                    logger.warning("[bars] %s %s: %s answered %d bars and "
                                   "none could be written — the public feed "
                                   "instead", symbol, interval, source,
                                   len(rows))
                    # AN ANSWER OF BARS THAT CANNOT HAVE TRADED IS "NOT
                    # NOW", NEVER "NO BARS HERE" (2026-10-31). The writer
                    # refuses such a bar (market_data.bar_shape); an answer
                    # of nothing else used to mute the venue for this
                    # series for MUTE_VENUE_MEMO_S, and for six hours the
                    # bots read the stand-in (for gold, the future). Like
                    # a 429 it mutes nothing: the public feed fills this
                    # pass and the venue is asked again the next.
                    if _every_bar_impossible(rows):
                        refused = True

            if not written and venue_only:
                continue                  # the venue's frame or nothing
            if not written:
                # THE VENUE IS MUTE, NOT THE MARKET. An execution venue
                # that answers a bar request with nothing — a historical
                # farm that never replies (the IBKR forex case that aged
                # every pair's bars 36 hours), a pacing refusal, a symbol
                # it will not serve history for — or with bars that cannot
                # be written must not leave the bot blind when the same
                # candles are one keyless request away. The rows are tagged
                # as the public feed's, so a bar's provenance still says
                # where it came from.
                pub, pub_source = _fallback_rows(cfg, symbol, interval, limit)
                _note_answer(symbol, interval, pub)
                if pub:
                    out["fallback"] += 1
                    # A quota's 429 is "not now", never "no bars here": it
                    # mutes nothing (2026-10-07).
                    if asked and not refused:
                        _remember_mute(source, symbol, interval)
                        logger.warning("[bars] %s %s: %s gave no usable bars "
                                       "— written from the public feed "
                                       "instead, and not asked again for "
                                       "%dh", symbol, interval, source,
                                       MUTE_VENUE_MEMO_S // 3600)
                    # THE STAND-IN FILLS THE GAP, NOT THE HISTORY. Yahoo's
                    # 4h grid is anchored at exchange midnight and a
                    # venue's at its own session close (OANDA: 17:00 New
                    # York), so the two never share a timestamp, and a
                    # stand-in written across the venue's window sat
                    # BESIDE its bars: one series at twice the density,
                    # read by every ATR stop and IPDA range on the pair.
                    # Only the bars after the venue's newest are written.
                    pub = _after_the_venues_last_bar(inst, interval, pub)
                    w2, s2 = _upsert_rows(inst, interval, pub, pub_source)
                    out["bars"] += w2
                    out["skipped"] += s2
                continue

            stale_age = (None if venue_only else
                         _venue_window_is_stale(inst, interval, good))
            if stale_age is not None:
                # A VENUE THAT ANSWERS WITH THE PAST. A window whose newest
                # bar the market has long left behind (a history farm that
                # lags, a symbol the venue stopped quoting) is written, and
                # the public feed fills AFTER its newest bar, exactly as it
                # does for a venue that said nothing. When the feed has
                # nothing newer either, the market is shut and nothing is
                # said.
                pub, pub_source = _fallback_rows(cfg, symbol, interval, limit)
                _note_answer(symbol, interval, pub)
                pub = _after_the_venues_last_bar(inst, interval, pub)
                if pub:
                    w2, s2 = _upsert_rows(inst, interval, pub, pub_source)
                    out["bars"] += w2
                    out["skipped"] += s2
                    out["fallback"] += 1
                    if not _venue_is_mute(source + ":stale", symbol, interval):
                        _remember_mute(source + ":stale", symbol, interval)
                        logger.warning(
                            "[bars] %s %s: %s answered with a window whose "
                            "newest bar is %.1f h old — the public feed fills "
                            "after it (%d bars)", symbol, interval, source,
                            stale_age / 3600, len(pub))
        if fetched and getattr(client, "_sv_public_feed", False) is True:
            _pace()
    return out


def _fallback_rows(cfg, symbol, interval, limit) -> "tuple[list, str]":
    """Bars from the keyless feed when the venue gave none, or ([], '')."""
    feed = _public_market_data_client(cfg)
    if feed is None:
        return [], ""
    try:
        # In the FEED's spelling (2026-10-03): the fallback asked Binance
        # for AAVEUSD, which answers nothing for a symbol it does not list,
        # so every crypto pair the venue (eToro) would not serve candles
        # for — AAVE, ADA, ATOM, AVAX, DOGE, DOT, MATIC, NEAR, UNI — sat on
        # a 4h bar four days old while the primary path, one branch up,
        # translated correctly. paper_readiness: "an armed bot is deciding
        # on a stale candle".
        rows = feed.klines(_venue_symbol(feed, symbol), interval=interval,
                           limit=limit) or []
    except Exception as e:  # noqa: BLE001 — the fallback must not raise
        logger.warning("[bars] public feed klines(%s, %s) failed: %s",
                       symbol, interval, e)
        return [], ""
    return rows, _source_tag(feed)


def _after_the_venues_last_bar(inst, interval, rows) -> list:
    """The stand-in's rows newer than the venue's newest bar — all of them
    when no venue has ever written this frame."""
    from market_data.models import PriceData

    last = (PriceData.objects
            .filter(instrument=inst, timeframe=interval)
            .exclude(source__endswith="_public")
            .order_by("-timestamp")
            .values_list("timestamp", flat=True).first())
    if last is None:
        return rows
    last_ms = int(last.timestamp() * 1000)
    kept = []
    for row in rows:
        try:
            if int(row[0]) > last_ms:
                kept.append(row)
        except (TypeError, ValueError, IndexError):
            kept.append(row)        # _upsert_rows counts it as skipped
    return kept


def _evict_stand_in_rows(inst, interval, rows) -> int:
    """Delete the public feed's rows INSIDE the venue's returned window —
    from its oldest bar to one interval past its newest. Returns how many
    went.

    The window, not "from the oldest bar onward" (2026-09-29). Stand-ins
    beyond the venue's newest bar are a stretch the venue does not cover,
    and "onward" deleted them too: with a venue whose bars never reached
    the table (see _write_venue_window), every public bar from the window's
    start to the present went, every ten minutes. The interval of slack
    past the venue's newest bar keeps the tail on one grid (a Yahoo bar two
    hours after the venue's last would otherwise sit beside it). Called
    only after the venue's own bars are written."""
    from market_data.models import PriceData

    stamps = []
    for row in rows:
        try:
            stamps.append(int(row[0]))
        except (TypeError, ValueError, IndexError):
            continue
    if not stamps:
        return 0
    since = datetime.fromtimestamp(min(stamps) / 1000, tz=dt_tz.utc)
    until = datetime.fromtimestamp(
        (max(stamps) + INTERVAL_SECONDS.get(interval, 3600) * 1000) / 1000,
        tz=dt_tz.utc)
    deleted, _ = (PriceData.objects
                  .filter(instrument=inst, timeframe=interval,
                          timestamp__gte=since, timestamp__lt=until,
                          source__endswith="_public")
                  .delete())
    return deleted


#: Seconds per bar, for the eviction window and the staleness judgement.
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}

#: A venue whose newest bar is older than this answered with a STALE
#: window. Crypto trades round the clock, so three bars behind is stale;
#: every other class closes for weekends and holidays, so a Monday-morning
#: window three days old is only the market being shut.
STALE_VENUE_BARS_CRYPTO = 3
STALE_VENUE_AFTER_S = 72 * 3600


def _venue_window_is_stale(inst, interval, rows, now=None) -> "float | None":
    """Age in seconds of the venue's newest returned bar when that is
    stale for this instrument's class, else None."""
    stamps = []
    for row in rows or []:
        try:
            stamps.append(int(row[0]))
        except (TypeError, ValueError, IndexError):
            continue
    if not stamps:
        return None
    now = now or datetime.now(dt_tz.utc)
    age = now.timestamp() - max(stamps) / 1000
    if (getattr(inst, "asset_class", "") or "") == "crypto":
        limit = STALE_VENUE_BARS_CRYPTO * INTERVAL_SECONDS.get(interval, 3600)
    else:
        limit = STALE_VENUE_AFTER_S
    return age if age > limit else None


# Starred instruments beyond the fleet get bars too, capped per pass —
# keyless requests are cheap, not free. Held symbols are never capped.
WATCHLIST_BAR_CAP = 30


def refresh_watchlist_bars(*, intervals=DEFAULT_INTERVALS,
                           limit=DEFAULT_LIMIT, covered=None,
                           starred=True, stop=None, unreached=None,
                           also=()) -> dict:
    """Bars for HELD and STARRED instruments no enabled bot already covers.

    The star used to bring quotes and signal scans but not bars — so a
    starred instrument's chart stayed blank and its rules could never
    fire, which quietly contradicted what the star promises. The keyless
    public feeds close the gap; symbols with no free source are skipped
    by name.

    HELD symbols come first and outside the cap. The manual TAKE TRADE
    config carries `symbols=[]` by design, so a pair held only through the
    manual lane is covered by no config — and the cap used to be taken
    BEFORE covered symbols were skipped, so fleet symbols spent the thirty
    slots and a held pair starred past them got no 4h/1h bars at all. The
    held set is the one the brain's regime probe reads
    (`brain.synthesizer._held_symbols`), so every probe on the book has a
    frame to read. The cap now counts only symbols this pass will fetch.

    `starred=False` (2026-10-07) skips the starred part only: a bar pass
    past its deadline (BARS_PASS_MAX_S) still refreshes the held part.
    `stop` (2026-10-07), when it says True, ends the starred part before
    the next starred symbol; the held part is never cut. `unreached` are
    config symbols the pass's deadline cut: their venue owns the series,
    so the keyless rows go only after the venue's newest bar, as for a
    mute venue (_after_the_venues_last_bar). Since 2026-10-31 every symbol
    gets that guard (skeptic M1), so `unreached` changes nothing here; it
    is kept for its callers. `also` (O1c, the Orcs' board
    of market symbols, only while `orcs` is ON and the pass is not late)
    runs after the starred part, cut by `stop` like it; the held part is
    exactly what it is without it.
    """
    from brain.synthesizer import _held_symbols
    from instruments.models import Instrument
    from market_data.public_feed import (SUPPORTED_ASSET_CLASSES,
                                         YF_UNAVAILABLE, public_feed_for)

    out = {"symbols": 0, "bars": 0, "skipped": 0, "errors": 0, "no_client": 0,
           "not_reached": 0}
    covered = covered or set()
    classes = sorted(SUPPORTED_ASSET_CLASSES | {"crypto"})
    skip = set(covered) | set(YF_UNAVAILABLE)
    held = [i for i in (Instrument.objects
                        .filter(symbol__in=_held_symbols(),
                                asset_class__in=classes)
                        .order_by("symbol"))
            if i.symbol not in skip]
    skip.update(i.symbol for i in held)
    stars = [i for i in (Instrument.objects
                         .filter(is_watchlist=True, is_active=True,
                                 asset_class__in=classes)
                         .order_by("symbol"))
             if i.symbol not in skip][:WATCHLIST_BAR_CAP] if starred else []
    # THE ORCS' BOARD (O1c) runs LAST, after the starred part and cut by
    # the same deadline: never in the held part, whose order and whose
    # never-cut promise (the fallback bars of the config symbols a late
    # pass cut) stay exactly what they are with `orcs` OFF.
    board = []
    if also:
        skip.update(i.symbol for i in stars)
        order = {sym: n for n, sym in enumerate(also)}
        board = sorted((i for i in Instrument.objects.filter(
            symbol__in=list(also), asset_class__in=classes)
            if i.symbol not in skip),
            key=lambda i: order.get(i.symbol, len(order)))
    for n, inst in enumerate(held + stars + board):
        # THE STARRED PART STOPS SYMBOL BY SYMBOL (2026-10-07): read once
        # before it, the deadline let thirty starred symbols run past the
        # task's hard limit, which kills the pass before its last line.
        if n >= len(held) and stop is not None and stop():
            out["not_reached"] = len(held) + len(stars) + len(board) - n
            logger.warning("[bars] the starred watchlist stopped at the "
                           "pass's deadline: %d starred symbol(s) not "
                           "reached", out["not_reached"])
            break
        client = public_feed_for(inst.asset_class)
        if client is None:
            out["no_client"] += 1
            continue
        fetch_symbol = _venue_symbol(client, inst.symbol)
        source = _source_tag(client)
        out["symbols"] += 1
        for interval in intervals:
            try:
                rows = client.klines(fetch_symbol, interval=interval,
                                     limit=limit)
            except Exception as e:
                logger.warning("[bars] watchlist klines(%s, %s) failed: %s",
                               inst.symbol, interval, e)
                out["errors"] += 1
                continue
            _note_answer(inst.symbol, interval, rows)
            # THE VENUE'S BARS ARE NEVER WRITTEN OVER (2026-10-31, skeptic
            # M1). Only a symbol the deadline cut was guarded, so a symbol
            # a venue wrote bars for earlier and no config covers now (a
            # closed TAKE TRADE, a disabled config, a starred symbol) had
            # the feed's whole window written over the venue's bars where
            # the timestamps met and beside them where they did not: the
            # recent 1h/4h flipped to the future or the cash index. Every
            # symbol gets the guard; one no venue ever wrote is unchanged
            # (_after_the_venues_last_bar keeps every row then).
            rows = _after_the_venues_last_bar(inst, interval, rows)
            written, skipped = _upsert_rows(inst, interval, rows, source)
            out["bars"] += written
            out["skipped"] += skipped
        # The same breath as the config pass: this pass runs straight
        # after it, on the same keyless feed, for up to thirty more.
        if getattr(client, "_sv_public_feed", False) is True:
            _pace()
    return out


class _HeldRows:
    """One REAL row's symbol that no enabled LIVE config covers (the manual
    lane, a braked or disabled config, a paper-only config): fetched from
    that config's own venue, first in the pass, never cut by the
    deadline."""

    def __init__(self, cfg, symbol, asset_class):
        self._cfg = cfg
        self.id = cfg.id
        self.user = cfg.user
        self.mode = "live"
        self.asset_class = asset_class or cfg.asset_class
        self.symbols = [symbol]

    def __getattr__(self, name):          # market_type, extras, capital...
        return getattr(self._cfg, name)


def _held_real_rows(live_covered) -> list:
    """_HeldRows for every OPEN or CLOSE_PENDING real row whose symbol no
    enabled LIVE config covers, one per (config, symbol). Never raises.

    REAL ROWS FROM THEIR OWN VENUE (2026-10-07). The manual lane
    (`symbols=[]`), a braked or disabled config and a paper-only config
    left a real row with the watchlist's keyless bars only, regular
    session: the stop eToro filled in the extended session on three real
    stock rows left no bar the reconcile's pricing could read."""
    try:
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        out, seen = [], set()
        rows = (AssetBotTrade.objects
                .filter(status__in=("OPEN", "CLOSE_PENDING"), paper=False)
                .exclude(symbol__in=list(live_covered))
                .select_related("config__user").order_by("symbol", "id"))
        for t in rows:
            key = (t.config_id, t.symbol)
            if not t.symbol or key in seen:
                continue
            seen.add(key)
            inst = Instrument.objects.filter(symbol=t.symbol).first()
            out.append(_HeldRows(t.config, t.symbol,
                                 getattr(inst, "asset_class", "")))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[bars] the held real rows could not be listed: %s", e)
        return []


class _OrcHeld(_HeldRows):
    """An Orc's symbol (bot_program/orcs, O1b): a row's config, the
    intervals the Orc reads, the config's own mode (a real row's is
    "live"); it stamps no venue mark."""

    def __init__(self, cfg, symbol, asset_class, *, mode, intervals):
        super().__init__(cfg, symbol, asset_class)
        self.mode = mode
        self.intervals = tuple(intervals)


def _orcs_on() -> bool:
    """The `orcs` switch, read once a pass; unreadable reads OFF."""
    try:
        from bot_program.orcs.switches import orcs_on
        return bool(orcs_on())
    except Exception:  # noqa: BLE001 — the Orcs never cost a bar
        return False


def _orc_held(part) -> list:
    """The Orcs' symbols the bar refresh fetches, by part (2026-10-16, O1b;
    spec §5.2, §6.1), 4h and 1h only:

      "real"   a real idea whose row has CLOSED while an arm still walks
               its bars (no other part refreshes it then); an open real
               row is the configs' and the held rows' to refresh
      "paper"  the LIVING paper ideas, at most the Orcs' paper cap of
               (config, symbol) pairs, oldest first (2026-10-22: the cap
               bounds the living ideas, §5.2), then the dead paper ideas
               whose arms still walk their tail, on top

    An idea whose arms should all be out (a bar of the multi-ghost's
    timeframe past its tail cap: ghost.step_bars closes them there) asks
    nothing more, so an idea that could not end never holds a request
    for ever. No 1d candle (2026-10-22): the Orcs' daily frame is the
    venue's 4h bars by UTC day (bot_program/orcs/bars.py), so no second
    daily grid sits beside the nightly EOD bars. The caller reads the
    switch. Never raises."""
    try:
        from django.utils import timezone

        from bot_program.orcs.bars import BAR_FINAL_AFTER, span_of
        from bot_program.orcs.birth import paper_cap
        from bot_program.orcs.constants import (LEG_DONE_STATUSES,
                                                MULTI_GHOST_TF, STATE_DEAD)
        from bot_program.orcs.ghost import tail_cap
        from bot_program.orcs.models import Orc
        now = timezone.now()
        paper = part == "paper"
        base = (Orc.objects.filter(paper=paper)
                .select_related("root_trade", "config__user")
                .order_by("born_at", "pk"))
        tailing = base.filter(state=STATE_DEAD, tracks__open=True).distinct()
        if paper:
            living = list(base.exclude(state=STATE_DEAD))
            orcs = living + list(tailing)
            cap_left = max(0, int(paper_cap()))
        else:
            orcs = list(base.exclude(state=STATE_DEAD)) + list(tailing)
            cap_left = None

        def done(orc):
            try:
                cap = tail_cap(orc, orc.root_trade, now)
            except Exception:  # noqa: BLE001 — an unread cap holds the bars
                return False
            return cap is not None and now >= (cap + span_of(MULTI_GHOST_TF)
                                               + BAR_FINAL_AFTER)

        out, seen = [], set()
        for orc in orcs:
            row = orc.root_trade
            dead = orc.state == STATE_DEAD
            if not paper and row.status not in LEG_DONE_STATUSES:
                continue
            if (dead or not paper) and done(orc):
                continue
            key = (orc.config_id, orc.symbol)
            if key in seen:
                continue
            if paper and not dead:
                if cap_left <= 0:
                    continue
                cap_left -= 1
            seen.add(key)
            cfg = orc.config
            out.append(_OrcHeld(cfg, orc.symbol, orc.asset_class,
                                mode="live" if not paper
                                else getattr(cfg, "mode", "paper"),
                                intervals=DEFAULT_INTERVALS))
        return out
    except Exception as e:  # noqa: BLE001 — the Orcs never cost a bar
        logger.warning("[bars] the Orcs' symbols could not be listed: %s", e)
        return []


def _orc_board() -> list:
    """The board's symbols (spec §5.2a MK2, BOARD_SYMBOLS) that have an
    Instrument row, in the board's order: US10Y has none and drops
    silently. One query. The caller reads the switch."""
    try:
        from bot_program.orcs.constants import BOARD_SYMBOLS
        from instruments.models import Instrument
        have = set(Instrument.objects.filter(symbol__in=BOARD_SYMBOLS)
                   .values_list("symbol", flat=True))
        return [s for s in BOARD_SYMBOLS if s in have]
    except Exception as e:  # noqa: BLE001 — the Orcs never cost a bar
        logger.warning("[bars] the Orcs' board could not be listed: %s", e)
        return []


def tape_ready() -> tuple:
    """(ready, why, per_pass): the Orcs' 15m and 5m eToro candles run only
    with `orcs` ON, `orcs_tape` ON AND a recorded headroom measurement
    (manage.py etoro_candle_headroom --yes), within its budget per pass.
    Never raises."""
    try:
        if not _orcs_on():
            return False, "the orcs switch is OFF", 0
        from core.platform_control import is_component_enabled

        from bot_program.orcs.constants import HEADROOM_KEY, TAPE_SWITCH
        from bot_program.orcs.models import OrcSetting
        if not is_component_enabled(TAPE_SWITCH):
            return False, "the orcs_tape switch is OFF", 0
        rec = OrcSetting.get(HEADROOM_KEY) or {}
        per_pass = int((rec or {}).get("tape_per_pass") or 0)
        if per_pass <= 0:
            return False, ("eToro's candle headroom is not measured "
                           "(manage.py etoro_candle_headroom)"), 0
        return True, "", per_pass
    except Exception as e:  # noqa: BLE001
        return False, f"unread: {type(e).__name__}", 0


def _orc_tape_held(*, mercenaries_only=False) -> list:
    """The tape's symbols, 15m and 5m: the LIVING Orcs' symbols first
    (oldest first, one per config and symbol), then the board's, carried
    by the oldest living Orc's config; the Mercenaries' own beat reads
    theirs only. Never raises."""
    try:
        from bot_program.orcs.constants import (STATE_DEAD,
                                                TAPE_INTERVALS)
        from bot_program.orcs.models import Orc
        orcs = list(Orc.objects.exclude(state=STATE_DEAD)
                    .filter(root_trade__status__in=("OPEN",
                                                    "CLOSE_PENDING"))
                    .select_related("config__user")
                    .order_by("born_at", "pk"))
        if mercenaries_only:
            orcs = [o for o in orcs if o.army_type == "mercenaries"]
        out, seen = [], set()
        for orc in orcs:
            if orc.symbol in seen:
                continue
            seen.add(orc.symbol)
            out.append(_OrcHeld(orc.config, orc.symbol, orc.asset_class,
                                mode="live" if not orc.paper else getattr(
                                    orc.config, "mode", "paper"),
                                intervals=TAPE_INTERVALS))
        if mercenaries_only or not orcs:
            return out
        from instruments.models import Instrument
        classes = dict(Instrument.objects.filter(symbol__in=_orc_board())
                       .values_list("symbol", "asset_class"))
        carrier = orcs[0].config
        for sym in _orc_board():
            if sym in seen:
                continue
            seen.add(sym)
            out.append(_OrcHeld(carrier, sym, classes.get(sym, ""),
                                mode=getattr(carrier, "mode", "paper"),
                                intervals=TAPE_INTERVALS))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[bars] the Orcs' tape could not be listed: %s", e)
        return []


def _tape_pass(state, held_list, per_pass, *, limit=DEFAULT_LIMIT) -> dict:
    """Ask eToro the tape of `held_list` in this pass: cut by the deadline,
    within `per_pass` candle reads, stopping at the first 429 (the pass's
    own stop), never a fallback, never a venue mark."""
    from bot_program.orcs.constants import TAPE_INTERVALS
    out = {"symbols": 0, "bars": 0, "asked": 0, "errors": 0,
           "venue_only_skipped": 0, "not_reached": 0, "budget": per_pass}
    start, left = state.asked, state.left
    for held in held_list:
        if state.asked - start + len(TAPE_INTERVALS) > per_pass:
            out["not_reached"] += 1
            continue
        try:
            res = refresh_bars_for_config(
                held, intervals=held.intervals, limit=limit,
                pass_state=state, stamp_marks=False, venue_only=True)
        except Exception as e:  # noqa: BLE001
            logger.exception("[bars] the Orcs' tape %s failed: %s",
                             held.symbols, e)
            out["errors"] += 1
            continue
        for k in ("symbols", "bars", "errors", "venue_only_skipped",
                  "not_reached"):
            out[k] += res.get(k, 0)
    out["asked"] = state.asked - start
    # a tape read eToro was not asked goes nowhere (no fallback): it is
    # counted here, never in the pass's "sent to the public feed"
    out["not_asked"] = state.left - left
    state.left = left
    return out


def _bar_pass_running():
    """Why the Mercenaries' tape must give way now ("" when it need not):
    a bar pass holds its lock (market_data.tasks.BARS_LOCK_KEY)."""
    from market_data.tasks import BARS_LOCK_KEY
    return "a bar pass started" if cache.get(BARS_LOCK_KEY) else ""


def refresh_orc_tape(now=None) -> dict:
    """The Mercenaries' tape on its own 5-minute beat (spec §1.6): a pass
    of its own, their symbols only, within the measured budget. It gives
    way to a bar pass at EVERY read (yield_to), not only at its start: two
    candle loops on one account key would ask eToro twice the measured
    pace, outside TAPE_SHARE.

    The task is the only writer of the `orcs_tape` row, so every outcome
    but the lock stand-aside (the task's own) is a counted pass
    (core/task_gate.py): a pass with no Mercenary holding a position is a
    success that read nothing, an unmeasured headroom a warning in words."""
    ready, why, per_pass = tape_ready()
    if not ready:
        if why.startswith("the orcs switch"):
            return {"status": "skipped", "reason": "orcs_disabled"}
        return {"status": "warning", "reason": f"the tape asks nothing: "
                                               f"{why}"}
    held = _orc_tape_held(mercenaries_only=True)
    if not held:
        return {"status": "success", "symbols": 0,
                "why": "no Mercenary holds a position"}
    state = _CandlePass()
    state.yield_to = _bar_pass_running
    out = _tape_pass(state, held, per_pass)
    out["status"] = "success"
    out["etoro_stopped"] = state.words()
    return out


def refresh_bot_bars(*, intervals=DEFAULT_INTERVALS, limit=DEFAULT_LIMIT) -> dict:
    """Refresh bars for every enabled AssetBotConfig, then for held and
    starred instruments the fleet does not already cover.

    One pass (2026-10-07): real rows no enabled live config covers first
    (never cut), then live configs, then paper ones, then the watchlist's
    held part, then its starred part. Configs and the starred part stop at
    BARS_PASS_MAX_S, symbol by symbol; the held part is never cut, and a
    held symbol on a config the deadline cut is the watchlist's. eToro's
    candles follow _CandlePass, and their summary is said before the
    watchlist.

    THE ORCS (2026-10-16, O1b; only while the `orcs` switch is ON, else
    the pass is exactly as before): their parts come LAST (2026-10-22),
    after every config and after the cut symbols are settled, so
    every config asks exactly what it asks OFF. An Orc's 429 or eToro
    budget can then never send a config's decision bars to the public
    feed, and an Orc fetch never takes a config's dedup slot (its
    venue-mark stamp with it). The parts are cut by the deadline like a
    config, stamp no venue mark, and are counted apart under "orcs"
    (_orc_held). The watchlist gets the very `unreached` it gets OFF, and
    a `covered` that also holds every symbol an Orc part reached
    (2026-10-22): the venue owns that series, as a config's."""
    from bot_program.models import AssetBotConfig

    totals = {"configs": 0, "symbols": 0, "bars": 0, "skipped": 0, "errors": 0,
              "no_client": 0, "fallback": 0, "deduped": 0, "not_reached": 0}
    state = _CandlePass()
    # Live configs first: the eToro budget of the pass goes to the bars
    # real money decides on before the paper fleet's.
    configs = sorted(AssetBotConfig.objects.filter(enabled=True)
                     .select_related("user"),
                     key=lambda c: getattr(c, "mode", "") != "live")
    live_covered = {s for c in configs if getattr(c, "mode", "") == "live"
                    for s in (c.symbols or []) if s}
    covered = {s for c in configs for s in (c.symbols or []) if s}
    keys = ("symbols", "bars", "skipped", "errors", "no_client",
            "fallback", "deduped", "not_reached")
    # REAL ROWS NO ENABLED LIVE CONFIG COVERS, FIRST, AND NEVER CUT.
    for held in _held_real_rows(live_covered):
        try:
            res = refresh_bars_for_config(held, intervals=intervals,
                                          limit=limit, pass_state=state,
                                          cut=False)
        except Exception as e:  # noqa: BLE001
            logger.exception("[bars] held %s failed: %s", held.symbols, e)
            totals["errors"] += 1
            continue
        covered.update(held.symbols)
        for k in keys:
            totals[k] += res.get(k, 0)
    for cfg in configs:
        totals["configs"] += 1
        if state.past_deadline():
            totals["not_reached"] += len(cfg.symbols or [])
            state.cut.update(s for s in (cfg.symbols or []) if s)
            continue
        try:
            res = refresh_bars_for_config(cfg, intervals=intervals,
                                          limit=limit, pass_state=state)
        except Exception as e:
            logger.exception("[bars] config %s failed: %s", cfg.id, e)
            totals["errors"] += 1
            continue
        for k in keys:
            totals[k] += res.get(k, 0)

    # WHAT THE DEADLINE CUT IS NOT COVERED (review, 2026-10-07). `covered`
    # held every enabled config's symbols, reached or not, so an OPEN row
    # on a config the deadline cut (paper, or real on a live config: no D8
    # row) got no bar from any path in that pass, while the WARNING below
    # said held symbols are still refreshed. A cut symbol no config or
    # held row reached goes back to the watchlist's held part, which writes
    # it after the venue's newest bar.
    unreached = state.cut - state.reached
    covered -= unreached
    late = state.past_deadline()
    if late:
        logger.warning("[bars] the pass reached %.0fs: %d config symbol(s) "
                       "not reached and the starred watchlist skipped; held "
                       "symbols are still refreshed", BARS_PASS_MAX_S,
                       totals["not_reached"])
    # THE ORCS' PARTS, LAST (O1b, 2026-10-22): every config has
    # asked what it asks OFF and the cut symbols are settled above, so
    # nothing here changes a config's bars, its venue-mark stamp or the
    # watchlist's `unreached`; `covered` gains what an Orc part reached.
    # Cut by the deadline like a config; counted apart.
    orcs_on_now = _orcs_on()
    if orcs_on_now:
        orcs = dict.fromkeys(keys, 0)
        for part in ("real", "paper"):
            for held in _orc_held(part):
                try:
                    res = refresh_bars_for_config(
                        held, intervals=held.intervals, limit=limit,
                        pass_state=state, stamp_marks=False)
                except Exception as e:  # noqa: BLE001
                    logger.exception("[bars] the Orcs' %s failed: %s",
                                     held.symbols, e)
                    orcs["errors"] += 1
                    continue
                for k in keys:
                    orcs[k] += res.get(k, 0)
                # THE VENUE OWNS WHAT AN ORC PART REACHED (2026-10-22), as
                # a config's symbol: else the watchlist's held part wrote
                # the public feed's bars over it in this same pass (a
                # symbol held by a row no config lists), and the next pass
                # asked eToro the whole window again. A 429 already falls
                # back to the public feed in the part itself; a symbol the
                # deadline cut stays the watchlist's.
                covered.update(s for s in held.symbols
                               if s in state.reached)
        totals["orcs"] = orcs
        # THE ORCS' TAPE (O1c, spec §5.2a item 3): eToro's 15m and 5m
        # candles of the living Orcs' symbols, then the board's, only with
        # `orcs_tape` ON and a recorded headroom measurement; after
        # everything else of the pass, cut by its deadline, within the
        # measured budget, stopping at the first 429, the venue's or
        # nothing (no fallback), no venue mark. Never in `covered`.
        ready, why, per_pass = tape_ready()
        if ready:
            totals["orcs_tape"] = _tape_pass(state, _orc_tape_held(),
                                             per_pass, limit=limit)
        else:
            logger.info("[bars] the Orcs' tape is not asked: %s", why)
    # eToro's part of the pass is over: its summary is said BEFORE the
    # watchlist (review, 2026-10-07), whose held part is never cut, so a
    # hard kill there cannot drop the lines operator checks #3 and #4 read.
    totals["etoro_asked"] = state.asked
    totals["etoro_left"] = state.left
    totals["etoro_stopped"] = state.words()
    if state.stopped:
        logger.warning("[bars] eToro was asked no more candles this pass "
                       "(%s): %d candle read(s) not asked, sent to the public "
                       "feed instead; %d asked", state.words(), state.left,
                       state.asked)
    try:
        # THE ORCS' BOARD (O1c): the market's symbols the dossier's MK2
        # reads, after the watchlist's starred part (the keyless feed, 4h
        # and 1h), cut by the deadline, skipped in a late pass, only while
        # `orcs` is ON; OFF the call is as before.
        board = _orc_board() if orcs_on_now and not late else []
        extra = {"also": board} if board else {}
        wl = refresh_watchlist_bars(intervals=intervals, limit=limit,
                                    covered=covered, starred=not late,
                                    stop=state.past_deadline,
                                    unreached=unreached, **extra)
        for k in ("symbols", "bars", "skipped", "errors", "no_client",
                  "fallback"):
            totals[k] += wl.get(k, 0)
    except Exception as e:
        logger.exception("[bars] watchlist pass failed: %s", e)
        totals["errors"] += 1

    logger.info("[bars] refresh complete: %s", totals)
    return totals
