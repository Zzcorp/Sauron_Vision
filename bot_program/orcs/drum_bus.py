"""THE WAR DRUMS' BUS IN O1 (spec §4.7 "Rollout": publishing and routing as
journal facts only, no wakes, so the reach is measured before a cent is
spent). Only Orc tables are written: OrcDrum, the receivers' journal (a
`drum` fact with its DR-id) and their memory.

What publishes (code only, from facts it already writes):
  stop_hit       a leg closed by its venue stop or the care's soft stop
                 (never a weekend cut, an event cut or the no-progress
                 clock), from the death hook, once per leg (on_close)
  lock           TRANSITIONS only: break-even armed, an event or weekend
                 lock set, the mirror refused; never a trail step (the
                 care re-locks on every new high) (on_tick)
  thesis_turned  the thesis check turns to exit, a predicate is met
                 (on_tick)
  level_break    a 4h close beyond a structural menu level of a held
                 symbol, coalesced: ONE wave per (user, class, 4h bar)
                 listing the symbols; a symbol whose bar became final only
                 at a later pass joins the wave in a drum of its own
                 (hourly_market); routed by EVERY listed symbol (route)
  sweep          a swept level of a held symbol's 4h menu, read on FINAL
                 bars only (the forming bar's wick is no sweep yet), once
                 per (symbol, level) (hourly_market)
  news_shock     an N-band drum: an urgent headline matched to a held
                 symbol, published once the price has spoken or 15
                 minutes have passed, ROUTED only when a move of 1 x
                 ATR(1h) within 15 minutes of the headline corroborates
                 it (the census's LiveQuote ring), else stored with no
                 reach (census_market)
  print_surprise a printed actual beyond the median |actual - forecast| of
                 the title's past prints (8 at least) (census_market); its
                 line names the currency and the calendar row's id, never
                 the title (third-party text: fence.py)

Routing (route, in the census) stays within ONE user's book: a stop level
or a holding is private. One delivery per (wave, Orc), never to the
origin, never at hop >= 2. In O1 a delivery is a journal fact and nothing
else, whatever `orcs_drums` says (§4.7 "Rollout", §11: drums are published
and routed as journal facts only, so the reach is measured before any
wake is spent on it).

THE DRUM WAKES (O2c, 2026-11-15, the O2 spec C.14-C.17, §4 Q21). route reads
its gate once a pass (wakes_gate): `orcs_drums` first, then the drum wakes'
own switch `orcs_drum_wakes` (OFF on arrival, turned on only with the
trading PIN), then the four gates of A.2. While any reads OFF, a delivery is
O1's, byte for byte, and no wave row is written. While all are ON:
  - each drum's wave is upserted, one OrcWave row per (user, wave_id): its
    drums, symbols, first and last drum, highest hop, reach and W12 queued;
  - each delivery adds a W12 reason to the Orc it reaches (wake._queue), one
    per wave: urgent for a stop_hit on the Orc's own symbol or its own stop
    within W12_STOP_ATR1H x ATR(1h) of the mark (_urgent_for, its stop clause
    narrowed for W12), read again at the render (P15). wake.py records it no
    earlier than DRUM_SETTLE_MIN after its wave's first drum (C.15);
  - its wave's breaker open, the delivery is journaled only, as in O1;
  - an urgent W12 past the Orc's DRUM_URGENT_PER_ORC_DAY urgent drum wakes of
    the UTC day (the claim counts them) waits in the Orc's memory
    (seen["w12_carry"]) and joins its next recorded wake, routine, never a
    wake of its own; its delivery is journaled.
  The DR entry's body then says which (`w12`: queued, carried, breaker). The
  switches read again (frictionless off), the breaker's counts, the 60% rule
  and the 25% share are the scheduler's, at admission and at the claim, on a
  DRUM WAKE: a wake whose every reason is a W12 (is_drum_wake). A drum
  wake's wave, its intents' wave stamp and its cost read one rule: its
  newest W12 (drum_wave). Nothing here imports the scheduler, the mind or
  the gateway at its top: the tick imports this module (on_tick). The stop
  a drum wake would place is the O arm's alone (C.17): a real stop never
  carries a wave (on_close's seam is O3's).
"""
import logging
import re
import statistics
from datetime import timedelta
from datetime import timezone as dt_tz

from bot_program.orcs import drums
from bot_program.orcs.constants import (DRUM_FACTOR_MAP_V1, DRUM_JOIN_MIN,
                                        DRUM_LOCK_WHYS,
                                        DRUM_URGENT_PER_ORC_DAY, DRUMS_SWITCH,
                                        GAP_MIN_SAMPLES,
                                        NEWS_SHOCK_CORROBORATION_ATR1H,
                                        NEWS_SHOCK_CORROBORATION_MIN,
                                        RING_SAMPLES, RING_TTL_S, STATE_DEAD,
                                        W12_BREAKER, W12_CARRIED,
                                        W12_CARRY_KEEP, W12_CARRY_KEY,
                                        W12_QUEUED, W12_STOP_ATR1H, W12_T,
                                        W12_URGENT_KEY, WAVE_BREAKER_OPEN)

logger = logging.getLogger(__name__)

LOCK_WORDS = {"breakeven": "break-even armed", "event lock": "an event lock",
              "weekend lock": "a weekend lock"}
STOP_HIT_KINDS = ("venue_stop", "engine_sl", "care", "paper_resting")
NOT_A_STOP = ("weekend cut", "event cut")
OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")
NEWS_LOOKBACK_MIN = 45
PRINT_LOOKBACK_MIN = 90
RING_KEY = "orcs:ring:{}"


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _now():
    from django.utils import timezone
    return timezone.now()


def drums_on() -> bool:
    """The `orcs_drums` switch. Inert through O1. From O2c (2026-11-15, C.14)
    its one reader is route's gate (wakes_gate), read first, once a pass:
    OFF, nothing else of the gate is read and a delivery is O1's. ON alone
    it wakes nobody: the drums are journaled with `orcs` ON whatever it
    says."""
    try:
        from core.platform_control import is_component_enabled
        return bool(is_component_enabled(DRUMS_SWITCH))
    except Exception:  # noqa: BLE001 — an unreadable switch is OFF
        return False


# ── publishing ───────────────────────────────────────────────────────────

def publish(kind, *, user, symbol, asset_class, payload, origin, orc=None,
            hop=0, at=None, wave_id=None, direction=0, legs=()):
    """Record one drum (OrcDrum): its wave is the open one of the same kind
    and symbol within DRUM_JOIN_MIN, else a new one."""
    from bot_program.orcs.models import OrcDrum
    at = at or _now()
    if wave_id is None:
        recent = list(OrcDrum.objects.filter(
            user=user, kind=kind, symbol=symbol,
            at__gte=at - timedelta(minutes=DRUM_JOIN_MIN), at__lte=at)
            .values("wave_id", "kind", "symbol", "at"))
        wave_id = drums.wave_of(kind, symbol, at, recent)
    return OrcDrum.objects.create(
        wave_id=str(wave_id)[:40], origin=str(origin)[:40], orc=orc,
        hop=int(hop), kind=str(kind)[:16], symbol=str(symbol)[:40],
        asset_class=str(asset_class or "")[:12], legs=list(legs or []),
        direction=int(direction or 0), at=at, payload=dict(payload or {}),
        user=user)


def _why_of(key):
    if not isinstance(key, (list, tuple)) or len(key) < 2:
        return ""
    return str(key[1] or "").replace(" (beyond the crowd)", "")


def _px(trade, value):
    from bot_program.orcs.facts import px
    return px(trade, value) if _f(value) is not None else "—"


def on_tick(orc, trade, seen_before, seen) -> int:
    """Lock and thesis drums from what this tick's facts just remembered:
    TRANSITIONS only. Returns how many were published."""
    before = seen_before if isinstance(seen_before, dict) else {}
    after = seen if isinstance(seen, dict) else {}
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    out = []
    why_b, why_a = _why_of(before.get("care_stop")), _why_of(
        after.get("care_stop"))
    if why_a != why_b and why_a in DRUM_LOCK_WHYS:
        out.append(("lock", drums.payload_lock(
            what=LOCK_WORDS[why_a], price=_px(trade, care.get("soft_stop")))))
    if before.get("venue_refused") is None and \
            after.get("venue_refused") is not None:
        out.append(("lock", drums.payload_lock(
            what="the venue refused the stop",
            price=_px(trade, care.get("venue_asked_for")))))
    tb = (before.get("thesis") or [None])[0]
    ta = (after.get("thesis") or [None])[0]
    if ta == "exit" and tb != "exit":
        out.append(("thesis_turned", drums.payload_thesis(
            why="the thesis check reads exit")))
    pb = before.get("predicates") or {}
    for key, state in sorted((after.get("predicates") or {}).items()):
        if (state or {}).get("state") == "met" and \
                ((pb.get(key) or {}).get("state") != "met"):
            out.append(("thesis_turned", drums.payload_thesis(
                why=f"a predicate met ({key.split(':')[0]})")))
    for kind, payload in out:
        publish(kind, user=orc.user, symbol=trade.symbol,
                asset_class=trade.asset_class, payload=payload,
                origin=f"orc:{orc.pk}", orc=orc)
    return len(out)


def _atr1h(symbol, asset_class, now):
    try:
        from bot_program.orcs import bars
        f = bars.frame(symbol, "1h", asset_class=asset_class, now=now)
        return f.atr if f is not None else None
    except Exception:  # noqa: BLE001
        return None


def _last(symbol):
    try:
        from market_data.models import LiveQuote
        q = LiveQuote.objects.filter(instrument__symbol=symbol).only(
            "last").first()
        return _f(q.last) if q is not None else None
    except Exception:  # noqa: BLE001
        return None


def _care_stop_hit(trade, rx) -> bool:
    """Did the care close the row at one of its STOPS (a trail, a lock, a
    structure stop), rather than by a cut or a clock? Read on the care's
    own word, metadata["care_exit"] (position_care._save_care), which
    real_exit_of wraps as "the care's <word>"."""
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    word = str(meta.get("care_exit") or "").strip()
    if not word:
        word = str(rx.why or "").replace("the care's ", "", 1).strip()
    return not (word in NOT_A_STOP or word.startswith("no progress"))


def on_close(orc, trade):
    """A stop_hit drum when the leg's stop closed it (the venue's stop, the
    engine's, the care's soft stop; never a cut or a clock): once per
    leg."""
    from bot_program.orcs import ghost
    from bot_program.orcs.models import OrcDrum
    rx = ghost.real_exit_of(orc, trade)
    if rx is None or rx.kind not in STOP_HIT_KINDS:
        return None
    if rx.kind == "care" and not _care_stop_hit(trade, rx):
        return None
    if OrcDrum.objects.filter(kind="stop_hit", orc=orc,
                              payload__leg=trade.pk).exists():
        return None
    level = _f(rx.level) if rx.level is not None else _f(trade.exit_price)
    at = rx.at or trade.closed_at or _now()
    mark, atr = _last(trade.symbol), _atr1h(trade.symbol, trade.asset_class,
                                            at)
    beyond = None
    if level is not None and mark is not None and atr:
        sign = 1 if str(trade.side).upper() == "BUY" else -1
        beyond = round(max(0.0, sign * (level - mark)) / atr, 2)
    payload = drums.payload_stop_hit(stop=_px(trade, level), at=at,
                                     beyond_atr=beyond)
    payload["leg"] = trade.pk
    # O3: a stop placed from a drum wake carries its wave; its hit
    # inherits the wave and hop + 1 (§4.7). Through O2 every real stop
    # is hop 0: no Orc places one (the wave stamp is the O arm's, C.17).
    return publish("stop_hit", user=orc.user, symbol=trade.symbol,
                   asset_class=trade.asset_class, payload=payload,
                   origin=f"orc:{orc.pk}", orc=orc, at=at)


def on_close_quietly(orc_id, trade_id):
    """The death hook's call, after the close commits. Never raises."""
    try:
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc
        from bot_program.orcs.switches import orcs_on
        if not orcs_on():
            return None
        orc = Orc.objects.filter(pk=orc_id).first()
        trade = AssetBotTrade.objects.filter(pk=trade_id).first()
        if orc is None or trade is None:
            return None
        return on_close(orc, trade)
    except Exception as e:  # noqa: BLE001 — a drum never costs a close
        logger.warning("[orcs] stop drum of #%s not published: %s",
                       trade_id, e)
        return None


# ── the market's drums (the hourly beat, the census) ─────────────────────

def _living():
    from bot_program.orcs.models import Orc
    return list(Orc.objects.exclude(state=STATE_DEAD)
                .filter(root_trade__status__in=OPEN_STATUSES)
                .select_related("user", "root_trade"))


def _level_breaks(now) -> dict:
    """{(user_id, class, 4h bar end): [symbols]}: the held symbols whose
    newest FINAL 4h close crossed a structural level of the menu as it
    stood before that bar."""
    from bot_program.orcs import bars, menu
    out = {}
    seen = set()
    for orc in _living():
        key = (orc.user_id, orc.symbol)
        if key in seen:
            continue
        seen.add(key)
        try:
            f = bars.frame(orc.symbol, "4h", asset_class=orc.asset_class,
                           now=now)
            if f is None or not f.venue or not f.fresh:
                continue
            got = bars.final_bar(f, now)
            if got is None:
                continue
            end, close = got
            df = bars.final_df(f, now)
            if df is None or len(df) < 2:
                continue
            prev = float(df["close"].values[-2])
            mn = menu.symbol_levels(orc.symbol, orc.asset_class, now=now,
                                    until=end - bars.span_of("4h"))
            for lv in mn.levels:
                if lv.kind not in ("swing", "pool"):
                    continue
                if (prev <= lv.price < close) or (prev >= lv.price > close):
                    out.setdefault((orc.user_id, orc.asset_class, end),
                                   []).append(orc.symbol)
                    break
        except Exception as e:  # noqa: BLE001 — one symbol never stops it
            logger.info("[orcs] level break of %s unread: %s", orc.symbol, e)
    return {k: sorted(set(v)) for k, v in out.items()}


def _sweeps(now) -> list:
    """[(user, symbol, class, tf, side, price, bar_end)] of the held
    symbols' 4h sweeps (smart_money.sweep_read, the menu's own reader: a
    wick through a confirmed swing and a close back inside on the same
    bar), read on FINAL bars only (the frame cut at the newest final 4h
    bar's end, as _level_breaks reads): a forming bar's wick through a
    level, with the price back inside it, is no sweep until that bar has
    closed back inside. `bar_end` is the sweeping bar's own end."""
    from bot_program import smart_money as sm
    from bot_program.orcs import bars
    out, seen = [], set()
    span = bars.span_of("4h")
    for orc in _living():
        if (orc.user_id, orc.symbol) in seen:
            continue
        seen.add((orc.user_id, orc.symbol))
        try:
            f = bars.frame(orc.symbol, "4h", asset_class=orc.asset_class,
                           now=now)
            end = bars.final_end(f, now) if f is not None else None
            if end is None:
                continue
            cut = bars.frame(orc.symbol, "4h", asset_class=orc.asset_class,
                             now=now, until=end)
            if cut is None or not cut.atr:
                continue
            sw = sm.sweep_read(cut.df, cut.swings, "BUY", cut.atr)
            n = len(cut.df)
            for key, side in (("against", "high"), ("with", "low")):
                hit = sw.get(key)
                level = _f((hit or {}).get("level"))
                if level is None:
                    continue
                bar_end = bars._utc(cut.df.index[n + int(hit["bar"])]) + span
                out.append((orc.user, orc.symbol, orc.asset_class, "4h",
                            side, level, bar_end))
        except Exception as e:  # noqa: BLE001
            logger.info("[orcs] sweeps of %s unread: %s", orc.symbol, e)
    return out


def hourly_market(now) -> int:
    """level_break (one wave per user, class and 4h bar) and sweep drums.
    A wave already published gains a drum for the symbols it does not
    list yet (their bar became final at a later pass), so no break is
    dropped and none is published twice."""
    from django.contrib.auth import get_user_model

    from bot_program.orcs.models import OrcDrum
    n = 0
    users = {}
    for (uid, cls, end), symbols in _level_breaks(now).items():
        wave = f"lb:{uid}:{cls}:{end:%Y%m%d%H}"
        listed = set()
        for payload in OrcDrum.objects.filter(wave_id=wave).values_list(
                "payload", flat=True):
            listed.update((payload or {}).get("symbols") or [])
        fresh = [s for s in symbols if s not in listed]
        if not fresh:
            continue
        user = users.get(uid) or get_user_model().objects.filter(
            pk=uid).first()
        users[uid] = user
        if user is None:
            continue
        publish("level_break", user=user, symbol=fresh[0],
                asset_class=cls, origin="code", wave_id=wave, at=now,
                payload=drums.payload_level_break(symbols=fresh,
                                                  bar_end=end))
        n += 1
    from core.price_format import format_price
    for user, sym, cls, tf, side, price, bar_end in _sweeps(now):
        shown = format_price(price, cls, sym)
        # one drum per sweeping bar and side: the same sweep read again on
        # the next bars (sweep_read looks back a few) is the same wave; a
        # later sweep of the level by another bar is a new one
        wave = f"sw:{user.pk}:{sym}:{tf}:{bar_end:%Y%m%d%H}:{side[0]}"[:40]
        if OrcDrum.objects.filter(wave_id=wave).exists():
            continue
        # sweep_read's sweep is a wick through the level and a close back
        # inside it on the same bar, read on final bars only, so reclaimed
        publish("sweep", user=user, symbol=sym, asset_class=cls,
                origin="code", wave_id=wave, at=now,
                payload=drums.payload_sweep(tf=tf, side=side, price=shown,
                                            reclaimed=True))
        n += 1
    return n


def sample_ring(now) -> int:
    """One LiveQuote sample per held symbol into a short ring (the census's
    5-minute beat): the news-shock corroboration's evidence."""
    from django.core.cache import cache
    n = 0
    for sym in sorted({o.symbol for o in _living()}):
        last = _last(sym)
        if last is None:
            continue
        key = RING_KEY.format(sym)
        try:
            ring = list(cache.get(key) or [])
            ring.append((now.isoformat(), last))
            cache.set(key, ring[-RING_SAMPLES:], RING_TTL_S)
            n += 1
        except Exception:  # noqa: BLE001 — a lost sample, never the census
            continue
    return n


def _ring(symbol) -> list:
    from django.core.cache import cache
    from django.utils.dateparse import parse_datetime
    out = []
    for at, price in cache.get(RING_KEY.format(symbol)) or []:
        t = parse_datetime(at) if isinstance(at, str) else at
        if t is not None:
            out.append((t, float(price)))
    return out


def corroborated(ring, at, *, atr1h) -> tuple:
    """(ok, move in ATR(1h), minutes): did the price move at least
    NEWS_SHOCK_CORROBORATION_ATR1H x ATR(1h) within
    NEWS_SHOCK_CORROBORATION_MIN of the headline? Measured from the last
    sample at or before it."""
    if not atr1h or not ring:
        return False, None, None
    before = [p for t, p in ring if t <= at]
    if not before:
        return False, None, None
    base = before[-1]
    best, when = 0.0, None
    for t, p in ring:
        mins = (t - at).total_seconds() / 60.0
        if 0 < mins <= NEWS_SHOCK_CORROBORATION_MIN:
            move = abs(p - base) / atr1h
            if move > best:
                best, when = move, int(round(mins))
    ok = best >= NEWS_SHOCK_CORROBORATION_ATR1H
    return ok, (round(best, 2) if when is not None else None), when


def _news_shocks(now) -> int:
    from bot_program.news_risk import URGENT_LEVELS
    from bot_program.orcs.models import OrcDrum
    from scraping.models import NewsArticle
    held = {}
    for orc in _living():
        held.setdefault(orc.symbol, {})[orc.user_id] = orc
    if not held:
        return 0
    through = NewsArticle.ai_affected_instruments.through
    rows = list(through.objects.filter(
        instrument__symbol__in=list(held),
        newsarticle__ai_urgency__in=list(URGENT_LEVELS),
        newsarticle__published_at__gte=now - timedelta(
            minutes=NEWS_LOOKBACK_MIN),
        newsarticle__published_at__lte=now)
        .values_list("newsarticle_id", "newsarticle__published_at",
                     "instrument__symbol"))
    n = 0
    for aid, published, sym in rows:
        for uid, orc in held.get(sym, {}).items():
            wave = f"ns:{aid}:{sym}:{uid}"[:40]
            if OrcDrum.objects.filter(wave_id=wave).exists():
                continue
            ok, move, mins = corroborated(_ring(sym), published,
                                          atr1h=_atr1h(sym, orc.asset_class,
                                                       now))
            waited = (now - published).total_seconds() / 60.0 >= \
                NEWS_SHOCK_CORROBORATION_MIN
            if not ok and not waited:
                continue                 # the price may still speak
            publish("news_shock", user=orc.user, symbol=sym,
                    asset_class=orc.asset_class, origin="code",
                    wave_id=wave, at=now,
                    payload=drums.payload_news_shock(
                        move_atr=move, minutes=mins, article=aid,
                        corroborated=ok))
            n += 1
    return n


_NUM = re.compile(r"^\s*([<>]?)\s*([-+]?\d+(?:\.\d+)?)\s*([%KMBT]?)\s*$",
                  re.I)
_MULT = {"": 1.0, "%": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def number(text):
    """A calendar figure as a number ("0.3%", "221K", "-1.2B"), or None."""
    m = _NUM.match(str(text or ""))
    if not m:
        return None
    return float(m.group(2)) * _MULT[m.group(3).upper()]


def median_surprise(title, ccy, before, *, min_n=GAP_MIN_SAMPLES):
    """The median |actual - forecast| of the title's past prints, or None
    under `min_n` samples."""
    from market_data.models import EconomicEvent
    xs = []
    for a, f in (EconomicEvent.objects
                 .filter(title__iexact=title, currency_affected=ccy,
                         datetime__lt=before)
                 .exclude(actual="").exclude(forecast="")
                 .values_list("actual", "forecast")[:400]):
        av, fv = number(a), number(f)
        if av is not None and fv is not None:
            xs.append(abs(av - fv))
    xs = [x for x in xs if x > 0] if any(xs) else xs
    if len(xs) < int(min_n):
        return None
    med = statistics.median(xs)
    return med if med > 0 else None


def _print_surprises(now) -> int:
    from market_data.models import EconomicEvent

    from bot_program.orcs.models import OrcDrum
    from bot_program.orcs.situation import currencies
    from bot_program.position_care import EVENT_IMPACT, EVENT_SOURCES
    by_ccy = {}
    for orc in _living():
        for ccy in currencies(orc.root_trade):
            by_ccy.setdefault(ccy, {})[orc.user_id] = orc
    if not by_ccy:
        return 0
    n = 0
    events = (EconomicEvent.objects
              .filter(datetime__lte=now,
                      datetime__gte=now - timedelta(
                          minutes=PRINT_LOOKBACK_MIN),
                      source__in=EVENT_SOURCES, impact__iexact=EVENT_IMPACT,
                      currency_affected__in=list(by_ccy))
              .exclude(actual="").exclude(forecast=""))
    for ev in events:
        a, f = number(ev.actual), number(ev.forecast)
        if a is None or f is None:
            continue
        med = median_surprise(ev.title, ev.currency_affected, ev.datetime)
        if med is None:
            continue
        x = abs(a - f) / med
        if x <= 1.0:
            continue
        for uid, orc in by_ccy.get(ev.currency_affected, {}).items():
            wave = f"ps:{ev.pk}:{uid}"[:40]
            if OrcDrum.objects.filter(wave_id=wave).exists():
                continue
            # the calendar title is third-party text: the drum carries the
            # row's id, never the title (its line is a T0 fact)
            publish("print_surprise", user=orc.user,
                    symbol=ev.currency_affected, asset_class="currency",
                    origin="code", wave_id=wave, at=now,
                    payload=drums.payload_print(
                        event=ev.pk, ccy=ev.currency_affected,
                        x=round(x, 2)))
            n += 1
    return n


def census_market(now) -> int:
    """The census's market drums: the LiveQuote ring, news shocks and print
    surprises. Each part fenced. Returns the drums published."""
    n = 0
    for step in (sample_ring, _news_shocks, _print_surprises):
        try:
            got = step(now)
            if step is not sample_ring:
                n += int(got or 0)
        except Exception as e:  # noqa: BLE001 — one part never stops one
            logger.warning("[orcs] drums %s failed: %s", step.__name__, e)
    return n


# ── routing ──────────────────────────────────────────────────────────────

def _factor_map():
    try:
        from bot_program.orcs.models import OrcSetting
        fm = OrcSetting.get("drum_factor_map")
        if isinstance(fm, dict) and fm.get("map"):
            return fm
    except Exception:  # noqa: BLE001
        pass
    return DRUM_FACTOR_MAP_V1


def _urgent_for(orc, drum, now, *, atr_share=1.0) -> bool:
    """§4.7: urgent only when the receiver's own stakes are: a stop_hit on
    its own symbol, or its own stop within `atr_share` x ATR(1h) of the mark
    (1 by §4.7's rule). Called by nothing in O1; from O2c (2026-11-15, C.14)
    by a delivery's W12, its stop clause narrowed to W12_STOP_ATR1H: in a
    correlated shock ATR widens and nearly every stop would sit within one
    ATR, so nearly every drum wake would be urgent."""
    if drum.kind == "stop_hit" and drum.symbol == orc.symbol:
        return True
    try:
        row = orc.root_trade
        meta = row.metadata if isinstance(row.metadata, dict) else {}
        care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
        stop = _f(care.get("soft_stop")) or _f(row.stop_loss)
        mark, atr = _last(orc.symbol), _atr1h(orc.symbol, orc.asset_class,
                                              now)
        return bool(stop and mark and atr
                    and abs(mark - stop) <= float(atr_share) * atr)
    except Exception:  # noqa: BLE001
        return False


def _reach(d, ideas, matrix, factor_map) -> list:
    """[(orc_id, relation)] of one drum. A level_break is reached by EVERY
    symbol it lists: the union of their reaches, one relation per Orc, the
    same symbol first, else the first listed symbol's relation."""
    base = {"asset_class": d.asset_class, "orc_id": d.orc_id, "hop": d.hop,
            "kind": d.kind}
    syms = [d.symbol]
    if d.kind == "level_break":
        syms = [str(s) for s in (d.payload or {}).get("symbols") or []] \
            or [d.symbol]
    chosen, order = {}, []
    for sym in syms:
        for oid, relation in drums.reach({**base, "symbol": sym}, ideas,
                                         matrix, factor_map):
            if oid not in chosen:
                order.append(oid)
                chosen[oid] = relation
            elif relation == "same symbol":
                chosen[oid] = relation
    return [(oid, chosen[oid]) for oid in order]


def route(now) -> int:
    """Route every unrouted drum within its user's book; journal one DR
    fact per (wave, Orc). Returns the deliveries. In O1 a delivery wakes
    nobody (the module's docstring). From O2c (2026-11-15, C.14-C.16), while
    the drum wakes' gate is ON (wakes_gate, read once a pass), each drum's
    wave is upserted (OrcWave) and each delivery adds its W12, carries it,
    or (its wave's breaker open) journals the drum only, its DR entry's body
    saying which (`w12`). OFF, a delivery is O1's, byte for byte, and no
    wave row is written."""
    from bot_program.orcs import journal, sources
    from bot_program.orcs.models import Orc, OrcDrum
    pending = list(OrcDrum.objects.filter(routed_at__isnull=True,
                                          at__lte=now, user__isnull=False)
                   .order_by("at", "id"))
    if not pending:
        return 0
    wakes = wakes_gate()
    factor_map = _factor_map()
    by_user = {}
    for d in pending:
        by_user.setdefault(d.user_id, []).append(d)
    delivered = 0
    for uid, user_drums in by_user.items():
        living = list(Orc.objects.filter(user_id=uid)
                      .exclude(state=STATE_DEAD)
                      .filter(root_trade__status__in=OPEN_STATUSES)
                      .select_related("root_trade"))
        ideas = [{"orc_id": o.pk, "symbol": o.symbol,
                  "asset_class": o.asset_class, "side": o.side}
                 for o in living]
        by_id = {o.pk: o for o in living}
        corr = sources.correlation(user_drums[0].user,
                                   [o.symbol for o in living])
        matrix = (corr["value"]["matrix"] if not corr.get("dash") else {})
        for d in user_drums:
            reached = []
            corroborated_ok = (d.kind != "news_shock"
                               or bool((d.payload or {}).get("corroborated")))
            targets = _reach(d, ideas, matrix, factor_map) \
                if corroborated_ok else []
            wave = None
            if wakes:
                try:
                    wave = _wave_upsert(d)
                except Exception as e:  # noqa: BLE001 — O1's delivery then
                    logger.warning("[orcs] drum %s: its wave not written: "
                                   "%s", d.pk, e)
            queued = 0
            for oid, relation in targets:
                orc = by_id.get(oid)
                if orc is None:
                    continue
                waves = list((orc.seen or {}).get("drum_waves") or [])
                if d.wave_id in waves:
                    continue
                # merged under the Orc's lock: a list another writer grew
                # since this pass loaded the Orc is kept
                remember = {"drum_waves": journal.add_keys(50, [d.wave_id])}
                payload_d = {"kind": d.kind, "symbol": d.symbol,
                             "hop": d.hop, "payload": d.payload}
                body = {"fk": "drum", "drum": d.pk, "drum_kind": d.kind,
                        "symbol": d.symbol, "relation": relation,
                        "hop": d.hop, "wave": d.wave_id}
                reason, w12 = None, ""
                if wave is not None:
                    try:
                        reason, w12 = _w12_delivery(orc, d, relation, wave,
                                                    now)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[orcs] drum %s to Orc %s: no W12: "
                                       "%s", d.pk, oid, e)
                if w12:
                    body["w12"] = w12
                if w12 == W12_CARRIED:
                    remember[W12_CARRY_KEY] = add_carry([reason])
                try:
                    journal.append(
                        orc, "drum",
                        lambda fid, pd=payload_d, rel=relation:
                        drums.line(pd, rel, fid),
                        body=body,
                        fact=True, id_prefix="DR", remember=remember, at=now)
                    reached.append({"orc": oid, "relation": relation})
                    delivered += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("[orcs] drum %s to Orc %s not "
                                   "journaled: %s", d.pk, oid, e)
                    continue
                if w12 == W12_CARRIED:
                    queued += 1
                elif w12 == W12_QUEUED:
                    try:
                        from bot_program.orcs import wake
                        wake._queue(orc, [reason], now)
                        queued += 1
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[orcs] drum %s to Orc %s: its W12 "
                                       "not queued: %s", d.pk, oid, e)
            if wave is not None:
                try:
                    _wave_reach(wave, reached, queued)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[orcs] drum %s: its wave's reach not "
                                   "written: %s", d.pk, e)
            d.reach = list(d.reach or []) + reached
            d.routed_at = now
            d.save(update_fields=["reach", "routed_at"])
    return delivered


# ── the drum wakes (O2c, 2026-11-15, the O2 spec C.14-C.16) ──────────────

def wakes_gate() -> bool:
    """C.14: may this pass's deliveries add a W12? `orcs_drums` first (its
    one reader, drums_on), then the drum wakes' own switch, then the four
    gates of A.2 (switches.gate_code: the Orcs line is read through the
    gateway inside that function, so this module still imports no
    scheduler, mind or gateway at its top). Read once a pass; unreadable
    reads OFF."""
    try:
        if not drums_on():
            return False
        from bot_program.orcs import switches
        return bool(switches.drum_wakes_on()) and switches.gate_code() == ""
    except Exception as e:  # noqa: BLE001 — an unreadable gate is OFF
        logger.info("[orcs] the drum wakes' gate could not be read: %s", e)
        return False


def _symbols_of(d) -> list:
    syms = ([str(x) for x in (d.payload or {}).get("symbols") or []]
            if d.kind == "level_break" else [])
    return syms or [str(d.symbol)]


def w12_reason(d, relation, *, urgent, own, first_at) -> dict:
    """C.14: one delivery's W12 reason, keyed per wave (one per wave and
    Orc): {code W12, key "W12:<wave_id>", t (W12_T's code words), urgent,
    wave, hop, first_at (its wave's first drum: the settle counts from it),
    drum (its kind), own (a stop_hit on the receiver's own symbol: urgent
    whatever its stop, the render reading it again)}."""
    from bot_program.orcs.notes import DRUM_WORDS
    hop = int(d.hop or 0)
    t = W12_T.format(kind_t=DRUM_WORDS.get(str(d.kind), "a drum"),
                     symbols=", ".join(_symbols_of(d)), relation=relation,
                     hop=hop)
    return {"code": "W12", "key": f"W12:{d.wave_id}"[:120], "t": t,
            "urgent": bool(urgent), "wave": str(d.wave_id), "hop": hop,
            "first_at": (first_at.isoformat() if hasattr(first_at,
                                                         "isoformat")
                         else str(first_at or "")),
            "drum": str(d.kind), "own": bool(own)}


def is_drum_wake(reasons) -> bool:
    """A DRUM WAKE (C.16; defined here, once): a wake whose every reason is
    a W12. Only a drum wake meets the breaker, the 60% rule and the 25%
    share, and only a drum wake counts for its wave, for the user's hour and
    for its Orc's urgent drum wakes of the day: a W12 that rides a wake with
    another reason is read with it, on that reason's own account."""
    rs = [r for r in reasons or () if isinstance(r, dict)]
    return bool(rs) and all(r.get("code") == "W12" for r in rs)


def drum_wave(reasons):
    """The wave a wake answers to (C.16, C.17; one rule, documented): its
    NEWEST W12 reason, the latest first_at (its wave's first drum; ties, the
    greater key). (wave_id, hop), or None when no reason is a W12. A drum
    wake's counts and cost, and the wave stamp on an intent, read it."""
    from django.utils.dateparse import parse_datetime
    best = None
    for r in reasons or ():
        if not isinstance(r, dict) or r.get("code") != "W12" or \
                not r.get("wave"):
            continue
        try:
            at = parse_datetime(str(r.get("first_at") or ""))
        except (TypeError, ValueError):
            at = None
        rank = (at.timestamp() if at is not None else float("-inf"),
                str(r.get("key") or ""))
        if best is None or rank > best[0]:
            best = (rank, (str(r["wave"]), int(r.get("hop") or 0)))
    return best[1] if best is not None else None


def urgent_today(orc, now) -> int:
    """The Orc's urgent drum wakes of `now`'s UTC day, as the claim counts
    them (seen[W12_URGENT_KEY] = {day, n}); 0 for another day."""
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    got = seen.get(W12_URGENT_KEY)
    if not isinstance(got, dict) or \
            got.get("day") != now.astimezone(dt_tz.utc).date().isoformat():
        return 0
    try:
        return max(0, int(got.get("n") or 0))
    except (TypeError, ValueError):
        return 0


def add_carry(reasons):
    """A `remember` value for seen[W12_CARRY_KEY]: the locked carry with
    `reasons` added once per key, each routine (urgent False) and marked
    `carried`, the newest W12_CARRY_KEEP kept. A carried W12 joins the Orc's
    next recorded wake (wake.record), never one of its own, and the render
    never reads it urgent again."""
    add = [{**r, "urgent": False, "carried": True} for r in reasons or ()
           if isinstance(r, dict) and r.get("key")]

    def merge(cur):
        out = [r for r in (cur if isinstance(cur, list) else [])
               if isinstance(r, dict) and r.get("key")]
        have = {r["key"] for r in out}
        for r in add:
            if r["key"] not in have:
                out.append(r)
                have.add(r["key"])
        return out[-W12_CARRY_KEEP:]
    return merge


def _wave_upsert(d):
    """C.16: the drum's wave, one OrcWave row per (user, wave_id), upserted
    from it: its drums counted, its symbols joined, its first and last drum
    and its highest hop. A new row's first drum is its wave's first OrcDrum
    (a drum routed before the gate was ON counts). Route alone writes these
    columns; the claim writes w12_answered and the breaker, the settle the
    cost, each by its own UPDATE of its own columns."""
    from django.db.models import F, Min

    from bot_program.orcs.models import OrcDrum, OrcWave
    syms = _symbols_of(d)
    wave = OrcWave.objects.filter(user_id=d.user_id,
                                  wave_id=d.wave_id).first()
    if wave is None:
        first = OrcDrum.objects.filter(
            user_id=d.user_id, wave_id=d.wave_id).aggregate(
            m=Min("at"))["m"] or d.at
        wave, created = OrcWave.objects.get_or_create(
            user_id=d.user_id, wave_id=d.wave_id, defaults={
                "kind": str(d.kind)[:16], "symbols": sorted(set(syms)),
                "origin": str(d.origin or "")[:40],
                "first_at": min(first, d.at), "last_at": d.at,
                "max_hop": int(d.hop or 0), "drums": 1})
        if created:
            return wave
    OrcWave.objects.filter(pk=wave.pk).update(
        drums=F("drums") + 1,
        symbols=sorted(set(wave.symbols or []) | set(syms)),
        first_at=min(wave.first_at, d.at), last_at=max(wave.last_at, d.at),
        max_hop=max(int(wave.max_hop or 0), int(d.hop or 0)))
    wave.refresh_from_db()
    return wave


def _wave_reach(wave, reached, queued) -> None:
    """After one drum's deliveries: the wave's reach (one entry per Orc it
    reached) and its W12 queued (each W12 queued or carried)."""
    from django.db.models import F

    from bot_program.orcs.models import OrcWave
    if not reached and not queued:
        return
    have = {r.get("orc") for r in wave.reach or [] if isinstance(r, dict)}
    reach = list(wave.reach or []) + [r for r in reached
                                      if r.get("orc") not in have]
    OrcWave.objects.filter(pk=wave.pk).update(
        reach=reach, w12_queued=F("w12_queued") + int(queued))
    wave.reach = reach


def _w12_delivery(orc, d, relation, wave, now) -> tuple:
    """C.14, C.16: one delivery's W12, as (the reason or None, what became
    of it): none while its wave's breaker is open (W12_BREAKER: the drum
    journaled only, as in O1); urgent for a stop_hit on the Orc's own
    symbol, or for its own stop within W12_STOP_ATR1H x ATR(1h) of the mark
    (_urgent_for, its stop clause narrowed); an urgent one past the Orc's
    DRUM_URGENT_PER_ORC_DAY urgent drum wakes of the day carried
    (W12_CARRIED), any other queued (W12_QUEUED)."""
    if (wave.breaker or {}).get("state") == WAVE_BREAKER_OPEN:
        return None, W12_BREAKER
    own = d.kind == "stop_hit" and d.symbol == orc.symbol
    urgent = own or _urgent_for(orc, d, now, atr_share=W12_STOP_ATR1H)
    reason = w12_reason(d, relation, urgent=urgent, own=own,
                        first_at=wave.first_at)
    if urgent and urgent_today(orc, now) >= DRUM_URGENT_PER_ORC_DAY:
        return reason, W12_CARRIED
    return reason, W12_QUEUED
