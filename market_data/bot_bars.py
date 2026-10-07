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
from decimal import Decimal, InvalidOperation

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

    def past_deadline(self) -> bool:
        return _mono() - self.started >= BARS_PASS_MAX_S

    def may_ask(self, world: str) -> bool:
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
    unwritable bar used to abort the refresh of the whole config."""
    from django.db import DatabaseError

    from market_data.models import PriceData

    written = skipped = 0
    refused = None
    for row in rows or []:
        try:
            if not row or len(row) < 6:
                skipped += 1
                continue
            ts_ms = int(row[0])
            close = Decimal(str(row[4]))
            if ts_ms <= 0 or close <= 0:
                skipped += 1
                continue
            PriceData.objects.update_or_create(
                instrument=inst, timeframe=interval,
                timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=dt_tz.utc),
                defaults={
                    "open": Decimal(str(row[1])),
                    "high": Decimal(str(row[2])),
                    "low": Decimal(str(row[3])),
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
    """
    from django.db import DatabaseError, transaction

    try:
        with transaction.atomic():
            written, skipped = _upsert_rows(inst, interval, rows, source)
            evicted = (_evict_stand_in_rows(inst, interval, rows)
                       if written else 0)
    except DatabaseError as e:
        logger.warning("[bars] %s %s: writing %s's window failed, nothing "
                       "changed: %s", getattr(inst, "symbol", inst), interval,
                       source, e)
        return 0, len(rows or []), 0
    return written, skipped, evicted


def refresh_bars_for_config(cfg, *, intervals=DEFAULT_INTERVALS,
                            limit=DEFAULT_LIMIT, pass_state=None,
                            cut=True) -> dict:
    """Fetch and persist bars for every symbol on one bot config.

    `pass_state` (2026-10-07) is the refresh pass this config belongs to
    (_CandlePass: the dedup, the eToro pacing and stop); a call without
    one is a pass of its own. `cut=False` keeps every symbol past the
    pass's deadline: the held real rows (_held_real_rows) are never cut.
    Each symbol lands in the pass's `reached` or `cut` set."""
    from instruments.models import Instrument

    state = pass_state if pass_state is not None else _CandlePass()
    out = {"symbols": 0, "bars": 0, "skipped": 0, "errors": 0, "no_client": 0,
           "fallback": 0, "deduped": 0, "not_reached": 0}
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
            if rows:
                # THE VENUE ANSWERED: ITS WINDOW IS ITS OWN. Its bars are
                # written, then the stand-in rows inside the window it
                # returned go, so that window holds one grid, the venue's.
                # History behind the window (a backfilled year) stays, and
                # so does anything newer than it (see _evict_stand_in_rows).
                written, skipped, evicted = _write_venue_window(
                    inst, interval, rows, source)
                out["bars"] += written
                out["skipped"] += skipped
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

            stale_age = _venue_window_is_stale(inst, interval, rows)
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
                           starred=True, stop=None, unreached=None) -> dict:
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
    mute venue (_after_the_venues_last_bar).
    """
    from brain.synthesizer import _held_symbols
    from instruments.models import Instrument
    from market_data.public_feed import (SUPPORTED_ASSET_CLASSES,
                                         YF_UNAVAILABLE, public_feed_for)

    out = {"symbols": 0, "bars": 0, "skipped": 0, "errors": 0, "no_client": 0,
           "not_reached": 0}
    covered = covered or set()
    unreached = set(unreached or ())
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
    for n, inst in enumerate(held + stars):
        # THE STARRED PART STOPS SYMBOL BY SYMBOL (2026-10-07): read once
        # before it, the deadline let thirty starred symbols run past the
        # task's hard limit, which kills the pass before its last line.
        if n >= len(held) and stop is not None and stop():
            out["not_reached"] = len(held) + len(stars) - n
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
            if inst.symbol in unreached:
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
    session: the stop eToro filled in the extended session (NVDA #131,
    PG #138, AMZN #140) left no bar the reconcile's pricing could read."""
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


def refresh_bot_bars(*, intervals=DEFAULT_INTERVALS, limit=DEFAULT_LIMIT) -> dict:
    """Refresh bars for every enabled AssetBotConfig, then for held and
    starred instruments the fleet does not already cover.

    One pass (2026-10-07): real rows no enabled live config covers first
    (never cut), then live configs, then paper ones, then the watchlist's
    held part, then its starred part. Configs and the starred part stop at
    BARS_PASS_MAX_S, symbol by symbol; the held part is never cut, and a
    held symbol on a config the deadline cut is the watchlist's. eToro's
    candles follow _CandlePass, and their summary is said before the
    watchlist."""
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
        wl = refresh_watchlist_bars(intervals=intervals, limit=limit,
                                    covered=covered, starred=not late,
                                    stop=state.past_deadline,
                                    unreached=unreached)
        for k in ("symbols", "bars", "skipped", "errors", "no_client",
                  "fallback"):
            totals[k] += wl.get(k, 0)
    except Exception as e:
        logger.exception("[bars] watchlist pass failed: %s", e)
        totals["errors"] += 1

    logger.info("[bars] refresh complete: %s", totals)
    return totals
