"""THE SHORTS THE PLATFORM PROVES ITSELF, ON eToro's DEMO ACCOUNT (2026-10-31).

The operator, 2026-10-31: "je veux les short possible entierement svp" (I
want shorts fully possible, please). The TAKE TRADE lane sends a short on
every class eToro allows since S1 (bot_program/short_readback.py); THE BOTS
short a class only once its short is proven. Until now a proof was a
developer's sitting, pinned by hand (asset_engine/base.py
ETORO_SHORT_PROVEN: stock and forex since 2026-10-01). This module runs the
sitting itself, on a schedule, for every class whose short is not pinned:

  ONLY THE DEMO SEGMENT  whatever the eToro row's live/demo flag says. One
                key pair opens both worlds (measured 2026-09-23) and the URL
                segment alone picks the world, so the client is
                engine/etoro_client.DemoOnlyEtoroTrader, built from the
                keys and never from the flag: it writes the demo segment by
                construction, refuses before the wire any URL that is not
                on it, and follows no redirect (a 3xx answer is refused,
                RedirectRefused: an order or a close answered so is in
                doubt) (demo_client).
  THE STEPS     for each class (CLASS_ORDER) at 1x, then 2x and 5x where
                eToro's demo row lists them (LEVERAGES), one step per run:
                eToro's short eligibility (the demo row: its short entry,
                allowOpenPosition, the floor, the margin minimum, the
                maximum units), a SELL of the venue minimum
                (venue_minimum, stop 3% above and target 3% below), the
                fill read (short_readback.judge, off the fill's own
                lookup), the close by position id, the close read (the
                open order's state "closed", then the order read once
                more). A clean round trip is a demo proof
                (short_models.EtoroShortObservation, demo_proven).
  THE MARKET    only while the instrument's own market is open on the
                platform's clock (market_words: core.exchange_status
                .market_clock, settled 15 minutes, never in the 17:00 New
                York rollover or the US index futures' break, never in a
                market's last 30 minutes). An index waits for New York's
                cash session: the demo index SELLs of 2026-10-01 were
                refused (749) inside the futures' break.
  THE BUDGET    one key's quota serves both worlds, so the live lane goes
                first (refusing): nothing is asked while eToro (either
                world) is sick, after a 429 within YIELD_AFTER_429_S, in a
                429 pause, or while a real position's close is pending.
                Within the runner, a position it holds is closed before
                anything else is opened, and that run opens nothing
                (closes first). One class at a time: while any demo
                position is held (an overnight hold included), no step of
                any class opens. MIN_GAP_S apart; a round trip costs about
                fifteen requests, counted on the row.
  IN DOUBT      an order or a close whose request did not come back, a
                5xx or a redirect on the order or the close, an acceptance
                (a 2xx) whose body nobody could read, a fill nobody could
                read, a held order whose withdrawal was not proven: NOTHING
                is sent again, the runner stops (stopped), the alarm chat
                and the staff are told, until a superuser clears it on
                /short-proofs/ with the trading PIN after checking eToro's
                demo account.
  THE GATE      a recorded demo proof opens the class to the bots at the
                multiplier measured and no other (base.missing_proofs,
                base.AssetBot._short_proof_leverage, proven_leverages); the
                operator hears it on Telegram (PROVEN_TITLE); a superuser
                revokes it with the trading PIN (revoke), with an audit row:
                every standing proof of that class at that multiplier at
                once, and a step of it still held then is revoked with it.
  OVERNIGHT     once per class, after its 1x proof: a 1x short held across
                the close (Monday to Thursday, one night), read on
                /portfolio the next session and closed: its overnight fee
                (the held row's fee, read whole: FEE_KEYS) and its nights.
                The cost model charges the measured short
                (measured_short_fees, risk_levels.short_fee_fraction),
                never less than before.
  THE SWITCH    short_proofs_demo, ON by default: it only ever touches the
                demo account. The beat (tasks.run_short_proofs_demo) and
                `manage.py short_proofs_demo` (--dry-run) are its doors.

No account figure rides any text: the words name classes, symbols, units,
multipliers and states; the amounts stay on the rows.
"""
import logging
import math
import re
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

#: The component switch: ON by default (core/platform_control.py).
SWITCH_KEY = "short_proofs_demo"
#: EtoroShortObservation.source of every row this module writes.
SOURCE = "proof_runner"
DEMO = "demo"

#: The classes proven, in this order, and the instruments tried for each,
#: in order: the BUY proofs' instruments (GLDM, SPX500, BTC) first; gold's
#: id is pinned (etoro_client.VENUE_ID_PINS), WHEAT.FUT is the commodity
#: BUY proof's. A class whose short the code pins is never run.
CLASS_ORDER = ("crypto", "etf", "index", "commodity")
PROOF_INSTRUMENTS = {"crypto": ("BTCUSD",), "etf": ("GLDM",),
                     "index": ("SPX500", "NSDQ100"),
                     "commodity": ("XAUUSD", "WHEATUSD")}
#: 1x first; 2x and 5x where eToro's demo row lists them, after 1x.
LEVERAGES = (1, 2, 5)
OVERNIGHT_LEVERAGE = 1
#: Between two steps that send (the scheduled runs; a step by hand waits
#: for nothing).
MIN_GAP_S = 25 * 60
#: The stop above and the target below the last price, as fractions.
STOP_FRACTION = 0.03
#: Above eToro's money floor, so the price's move between the rate read
#: and the fill never leaves the order under it.
FLOOR_MARGIN = 0.05
#: The size step per class; a row printed "whole" is 1.
CLASS_STEP = {"crypto": 0.0001}
#: No new round trip in a market's last minutes.
CLOSE_MARGIN_MIN = 30
#: An overnight hold opens Monday to Thursday, New York: one night.
OVERNIGHT_WEEKDAYS = (0, 1, 2, 3)
#: After a 429 on either world, the runner stays away this long.
YIELD_AFTER_429_S = 600
#: A step still "sending" after this long died between its POST and its
#: answer: in doubt.
SENDING_STALE_S = 300
#: Closes sent for one position before it is called in doubt.
MAX_CLOSE_ATTEMPTS = 3
LOCK_KEY = "short_proofs_demo:lock"
LOCK_S = 300

SENDING, OPEN, CLOSING = "sending", "open", "closing"
PROVEN, MISMATCH = "proven", "mismatch"
REFUSED, NOT_LISTED, NO_SHORT, NO_ROW = ("refused", "not_listed",
                                         "no_short", "no_row")
WITHDRAWN, NOT_SENT, IN_DOUBT = "withdrawn", "not_sent", "in_doubt"
#: The states that hold a position (or may) at eToro's demo account.
HELD = (SENDING, OPEN, CLOSING)
#: How long a step waits after each answer before it is asked again.
BACKOFF = {REFUSED: timedelta(hours=24), MISMATCH: timedelta(hours=24),
           WITHDRAWN: timedelta(hours=2), NOT_LISTED: timedelta(days=7),
           NO_SHORT: timedelta(days=7), NO_ROW: timedelta(hours=24),
           NOT_SENT: timedelta(0)}
#: A refusal of the instrument itself, at every multiplier.
WHOLE_INSTRUMENT = (NO_SHORT, NO_ROW)

#: The operator's words (2026-10-31), on Telegram when a proof opens a
#: class to the bots.
PROVEN_TITLE = ("Short on {cls} proven on the demo account: the bots may "
                "now short it at {lev}x")
IN_DOUBT_TITLE = "A demo short proof is in doubt: the runner stopped"
CLASS_NAMES = {"etf": "ETF", "index": "index", "commodity": "commodity",
               "crypto": "crypto", "stock": "stock", "forex": "forex"}
#: Where an overnight fee may ride on eToro's /portfolio row: the first key
#: present is read and named on the row (close_lookup "fee_key"); the
#: whole row is kept. EVERY KEY IS READ WHOLE (2026-10-31): the only
#: /portfolio row eToro has printed (tests/test_etoro_client.py
#: PORTFOLIO_ROW, measured 2026-09-23) shows totalFees 0.0 beside the open
#: fee in totalExternalFees (0.13, the same order's openingData fees), so
#: totalFees holds the nights' fees and no open fee. The others are
#: unmeasured, and whole is the stricter reading: a fee is never read
#: below what the row prints.
FEE_KEYS = ("totalFees", "fees", "totalOvernightFees", "overnightFees")


def class_name(icls) -> str:
    cls = str(icls or "").strip().lower()
    return CLASS_NAMES.get(cls, cls or "this class")


def a_class(icls) -> str:
    """The class with its article: "an ETF", "an index", "a crypto"."""
    name = class_name(icls)
    return f"{'an' if name[:1].lower() in 'aeiou' else 'a'} {name}"


def _model():
    from bot_program.short_models import EtoroShortObservation
    return EtoroShortObservation


def _rows():
    return _model().objects.filter(source=SOURCE)


# ── what the gate and the cost model read ───────────────────────────────

def proven_leverages(icls) -> frozenset:
    """The multipliers a SELL of `icls` has a demo round trip recorded at:
    demo_proven, never revoked, eToro's side "short", the demo world."""
    rows = _rows().filter(world=DEMO, demo_proven=True,
                          revoked_at__isnull=True, asset_class=str(icls),
                          side="short")
    return frozenset(int(v) for v in rows.values_list("leverage", flat=True)
                     if v)


def measured_short_fees(icls):
    """{"open_fee", "notional", "symbol"[, "overnight_fee",
    "overnight_notional", "nights"]} off the newest demo proofs of `icls`
    (the open fee of a round trip and, once measured, the overnight fee of
    its hold), or None: nothing measured, or nothing readable."""
    try:
        rows = _rows().filter(world=DEMO, demo_proven=True,
                              revoked_at__isnull=True,
                              asset_class=str(icls), side="short",
                              notional__isnull=False)
        trip = (rows.filter(fees__isnull=False)
                .order_by("-read_at", "-pk").first())
        night = (rows.filter(overnight=True, overnight_fee__isnull=False)
                 .order_by("-read_at", "-pk").first())
        if trip is None and night is None:
            return None
        src = trip or night
        out = {"open_fee": float(src.fees or 0),
               "notional": float(src.notional), "symbol": src.symbol}
        if night is not None:
            out.update(overnight_fee=float(night.overnight_fee),
                       overnight_notional=float(night.notional),
                       nights=max(1, int(night.nights or 1)))
        return out
    except Exception as e:  # noqa: BLE001 — unread: the table stands
        logger.warning("[short-proofs] the measured fees of %s are unread: "
                       "%s", icls, type(e).__name__)
        return None


def nights_of(horizon_hours) -> int:
    """The nights a hold of `horizon_hours` pays: one at least (an unknown
    horizon is read the stricter way), a night a day beyond."""
    try:
        hours = float(horizon_hours)
    except (TypeError, ValueError):
        return 1
    if not math.isfinite(hours) or hours <= 0:
        return 1
    return max(1, int(math.ceil(hours / 24.0)))


def nights_between(start, end) -> int:
    """The New York 17:00 rollovers (the daily swap, entry_timing's
    ROLLOVER_NY) inside (start, end]: the nights a hold paid."""
    from bot_program.entry_timing import NY
    if start is None or end is None or end <= start:
        return 0
    n = 0
    day = start.astimezone(NY).date()
    last = end.astimezone(NY).date()
    while day <= last:
        cut = datetime(day.year, day.month, day.day, 17, 0, tzinfo=NY)
        if start < cut <= end:
            n += 1
        day += timedelta(days=1)
    return n


# ── the switch, the stop, the account, the client ───────────────────────

def switch_on() -> bool:
    from core.platform_control import is_component_enabled
    return is_component_enabled(SWITCH_KEY)


def stopped():
    """The in-doubt step that stops the runner, or None."""
    return (_rows().filter(proof_state=IN_DOUBT, revoked_at__isnull=True)
            .order_by("read_at", "pk").first())


def stop_words(row) -> str:
    from core.exchange_status import utc_words
    when = utc_words(row.read_at) if row.read_at else "?"
    return (f"the demo short proofs are stopped: {a_class(row.asset_class)}"
            f" short ({row.symbol}) is in doubt since {when} — check eToro's "
            f"demo account, then clear it on /short-proofs/ with your trading "
            f"PIN")


def keyed_account(user=None):
    """The eToro row whose keys the runner uses: the first one with both
    keys (the operator's), or `user`'s. Its demo flag is never read."""
    from bot_program.models import EtoroAccount
    qs = EtoroAccount.objects.select_related("user").order_by("pk")
    if user is not None:
        qs = qs.filter(user=user)
    for acct in qs:
        try:
            key, user_key = acct.get_credentials()
        except Exception:  # noqa: BLE001 — unreadable keys are no keys
            continue
        if key and user_key:
            return acct
    return None


def demo_client(account):
    """The runner's client: eToro's DEMO segment and nothing else, built
    from the row's keys and never from its demo flag."""
    from bot_program.engine.etoro_client import DemoOnlyEtoroTrader
    key, user_key = account.get_credentials()
    if not key or not user_key:
        raise ValueError("this eToro row has no keys")
    return DemoOnlyEtoroTrader(key, user_key)


# ── the clock and the venue ─────────────────────────────────────────────

def market_words(symbol, icls, now, *, closing=False) -> str:
    """"" when `symbol`'s own market is open for a demo proof at `now`,
    else why not: shut, not settled, the rollover, the US index break, its
    last CLOSE_MARGIN_MIN minutes (not asked of a close), or no hours
    modelled for the class. Crypto never shuts."""
    from bot_program import entry_timing
    from core.exchange_status import market_clock, next_close_utc
    cls, exchange = entry_timing.instrument_key(symbol, icls)
    cls = str(cls or icls)
    if cls in entry_timing.NEVER_SHUTS:
        return ""
    words = class_name(cls)
    try:
        clock = market_clock(cls, exchange or "", symbol=symbol, now_utc=now)
    except Exception as e:  # noqa: BLE001 — an unread clock opens nothing
        return f"the {words} market clock is unreadable ({type(e).__name__})"
    if not clock.get("modelled", False):
        return f"no market hours are modelled for {words}"
    if not clock.get("is_open", False):
        return (f"the {words} market is shut"
                + (f" until {clock['reopens_words']}"
                   if clock.get("reopens_words") else ""))
    opened = clock.get("opened")
    settle = timedelta(minutes=entry_timing.OPEN_SETTLE_MINUTES)
    if opened is not None and now < opened + settle:
        return (f"the {words} market opened less than "
                f"{entry_timing.OPEN_SETTLE_MINUTES} minutes ago")
    for check in (entry_timing.rollover, entry_timing.index_break):
        got = check(now, cls, exchange=exchange or "", symbol=symbol)
        if got:
            return got["why"]
    if not closing:
        try:
            close = next_close_utc(cls, exchange or "", symbol, now_utc=now)
        except Exception:  # noqa: BLE001 — no close read, no margin judged
            close = None
        if close is not None and close - now < timedelta(
                minutes=CLOSE_MARGIN_MIN):
            return (f"the {words} market closes within {CLOSE_MARGIN_MIN} "
                    f"minutes")
    return ""


def refusing() -> str:
    """Why the runner must not ask eToro anything now, or "": the live
    lane goes first. One key's quota serves both worlds, so either
    world's sickness, a 429 within YIELD_AFTER_429_S, a 429 pause, or a
    real position's close still pending holds every step. Read on the wall
    clock: these are the wire's state, not the run's."""
    from bot_program import venue_health as vh
    from bot_program.engine import etoro_client as ec
    for world in ("live", "demo"):
        if vh.sick("etoro", world):
            return (f"eToro ({world}) is sick: the live lane's closes and "
                    f"stops go first, nothing is asked")
        if vh.recent_refusals("etoro", world, within_s=YIELD_AFTER_429_S):
            return (f"eToro ({world}) answered HTTP 429 within the last "
                    f"{YIELD_AFTER_429_S // 60} minutes")
        try:
            end = ec._RATE_PAUSE.get(world)
            if ec.RATE_PAUSE and end is not None and end > ec._mono():
                return f"eToro ({world}) is in its 429 pause"
        except Exception:  # noqa: BLE001 — an unread pause holds nothing
            pass
    try:
        from bot_program.asset_models import AssetBotTrade
        if AssetBotTrade.objects.filter(status="CLOSE_PENDING",
                                        paper=False).exists():
            return "a real position's close is pending: closes go first"
    except Exception as e:  # noqa: BLE001
        return f"the pending closes are unread ({type(e).__name__})"
    return ""


def hold_until_for(symbol, icls, now):
    """When an overnight hold opened at `now` is due to close: its market's
    next session, after the close that follows `now`, settled; a day for
    crypto (one New York rollover)."""
    from bot_program import entry_timing
    from core.exchange_status import market_clock, next_close_utc
    cls, exchange = entry_timing.instrument_key(symbol, icls)
    cls = str(cls or icls)
    settle = timedelta(minutes=entry_timing.OPEN_SETTLE_MINUTES + 15)
    if cls in entry_timing.NEVER_SHUTS:
        return now + timedelta(hours=24) + settle
    try:
        close = next_close_utc(cls, exchange or "", symbol, now_utc=now)
        if close is None:
            return now + timedelta(hours=24)
        later = market_clock(cls, exchange or "", symbol=symbol,
                             now_utc=close + timedelta(minutes=1))
        reopens = later.get("reopens") or close + timedelta(hours=16)
        return reopens + settle
    except Exception:  # noqa: BLE001 — a day, the crypto reading
        return now + timedelta(hours=24)


def _overnight_day(now) -> str:
    from bot_program.entry_timing import NY
    if now.astimezone(NY).weekday() in OVERNIGHT_WEEKDAYS:
        return ""
    return ("an overnight hold opens Monday to Thursday only (one night, "
            "never a weekend)")


# ── the plan ────────────────────────────────────────────────────────────

def _instrument_for(icls, lev, mine, now, *, overnight):
    """(symbol, None, None) for the first instrument of `icls` no refusal
    holds back at `lev`, else (None, until, the refusal row)."""
    held_back = None
    for sym in PROOF_INSTRUMENTS[icls]:
        blocks = [r for r in mine if r.symbol == sym
                  and r.proof_state in BACKOFF
                  and (r.proof_state in WHOLE_INSTRUMENT
                       or (r.leverage == lev
                           and bool(r.overnight) == bool(overnight)))]
        latest = max(blocks, key=lambda r: (r.read_at, r.pk)) \
            if blocks else None
        if latest is None:
            return sym, None, None
        until = latest.read_at + BACKOFF[latest.proof_state]
        if until <= now:
            return sym, None, None
        if held_back is None or until < held_back[0]:
            held_back = (until, latest)
    return None, held_back[0], held_back[1]


def _step(icls, lev, overnight):
    return {"asset_class": icls, "leverage": int(lev),
            "overnight": bool(overnight),
            "symbol": PROOF_INSTRUMENTS[icls][0], "state": "", "why": ""}


def _judge_step(step, mine, now, forced, held=()):
    """Fill in the step's state: done, revoked, held, blocked, backoff,
    waiting (its market) or due. `mine` is the class's rows; `held` the
    runner's rows that hold (or may hold) a position at eToro's demo
    account, WHATEVER their class: one class at a time, so any of them
    holds every step (2026-10-31). `forced` (a step named by hand: its
    multiplier, or the overnight hold) runs whatever its record says."""
    from bot_program.asset_engine import base
    from core.exchange_status import utc_words
    icls, lev, night = step["asset_class"], step["leverage"], \
        step["overnight"]
    words = class_name(icls)
    if icls not in base.ETORO_PROVEN:
        return dict(step, state="blocked",
                    why=f"no fill-and-close proof is pinned for {words} "
                        f"itself")
    if night:
        # standing rows only: a measurement revoked with its pair is
        # measured again once the 1x stands anew (its fee is read from
        # standing rows only, measured_short_fees)
        measured = [r for r in mine if r.overnight and r.demo_proven
                    and r.revoked_at is None]
        if measured and not forced:
            last = measured[-1]
            fee = ("its fee unread" if last.overnight_fee is None else
                   f"{last.nights} night{'s' if last.nights != 1 else ''}")
            return dict(step, state="done", symbol=last.symbol,
                        why=f"measured on {last.symbol} ({fee})")
    else:
        proven = [r for r in mine if r.demo_proven and r.leverage == lev]
        live = [r for r in proven if r.revoked_at is None]
        if live and not forced:
            return dict(step, state="done", symbol=live[-1].symbol,
                        why=f"proven on {live[-1].symbol}")
        if proven and not forced:
            return dict(step, state="revoked", symbol=proven[-1].symbol,
                        why="revoked on /short-proofs/: run it again by "
                            "hand to prove it anew")
    if held:
        last = held[-1]
        return dict(step, state="held",
                    why=f"{a_class(last.asset_class)} short is held "
                        f"({last.symbol}) on eToro's demo account: one class "
                        f"at a time, nothing opens until it is closed")
    at_one = {r.leverage for r in mine if r.demo_proven
              and r.revoked_at is None}
    if (night or lev > 1) and 1 not in at_one and not forced:
        return dict(step, state="blocked", why="after its 1x proof")
    sym, until, latest = _instrument_for(icls, lev, mine, now,
                                         overnight=night)
    if sym is None and not forced:
        return dict(step, state="backoff", symbol=latest.symbol,
                    why=f"{latest.refusal or latest.proof_state} — asked "
                        f"again {utc_words(until)}")
    sym = sym or step["symbol"]
    why = market_words(sym, icls, now) or (_overnight_day(now)
                                           if night else "")
    return dict(step, symbol=sym, state="waiting" if why else "due",
                why=why)


def plan(*, now=None, asset_class=None, leverage=None, overnight=False,
         forced=False) -> list:
    """Every step still to run, in the order it runs, each with its state
    and why: every class at 1x first, then 2x, then 5x, then each class's
    overnight hold. A class whose short the code pins is not in it.
    `asset_class`, `leverage` and `overnight` narrow it (a step by hand);
    `forced` runs a step whatever its record says, never while a demo
    position is held (whatever its class: one class at a time) or its
    market is shut."""
    from django.utils import timezone

    from bot_program.asset_engine import base
    now = now or timezone.now()
    rows = list(_rows().order_by("read_at", "pk"))
    held = [r for r in rows if r.proof_state in HELD
            and r.revoked_at is None]
    classes = [c for c in CLASS_ORDER if not base.short_pinned(c)
               and (asset_class is None or c == asset_class)]
    levels = [] if overnight else [
        lv for lv in LEVERAGES if leverage is None or lv == int(leverage)]
    steps = []
    for lev in levels:
        for icls in classes:
            mine = [r for r in rows if r.asset_class == icls]
            steps.append(_judge_step(_step(icls, lev, False), mine, now,
                                     forced, held))
    if overnight or leverage is None:
        for icls in classes:
            mine = [r for r in rows if r.asset_class == icls]
            steps.append(_judge_step(_step(icls, OVERNIGHT_LEVERAGE, True),
                                     mine, now, forced, held))
    return steps


def step_words(step) -> str:
    kind = ("overnight hold at 1x" if step["overnight"]
            else f"round trip at {step['leverage']}x")
    return (f"{class_name(step['asset_class'])} ({step['symbol']}) {kind}: "
            f"{step['state']}" + (f" — {step['why']}" if step["why"] else ""))


# ── one run ─────────────────────────────────────────────────────────────

def _lock() -> bool:
    from django.core.cache import cache
    try:
        return bool(cache.add(LOCK_KEY, 1, LOCK_S))
    except Exception as e:  # noqa: BLE001 — an unread lock runs nothing
        logger.warning("[short-proofs] the lock is unreadable (%s)",
                       type(e).__name__)
        return False


def _unlock() -> None:
    from django.core.cache import cache
    try:
        cache.delete(LOCK_KEY)
    except Exception:  # noqa: BLE001 — it expires on its own
        pass


def run_once(*, now=None, dry_run=False, asset_class=None, leverage=None,
             overnight=False, user=None, client=None) -> dict:
    """ONE step of the demo proofs: {"status" (success, skipped, error),
    "did" or "reason" (or "error"), "row", "requests"}, and "plan" on a dry
    run, which sends nothing and builds no client. `asset_class`,
    `leverage` and `overnight` ask for one step by hand (spacing waived);
    a multiplier or the overnight hold named by hand runs whatever its
    record says (forced), never while a demo position is held (whatever
    its class) or its market is shut. `client` is the eToro client to use
    (a test's); else demo_client of the keyed account."""
    from django.utils import timezone
    now = now or timezone.now()
    explicit = bool(asset_class or leverage or overnight)
    forced = bool(leverage or overnight)
    out = {"status": "skipped", "reason": "", "did": "", "row": None,
           "requests": 0}
    if dry_run:
        stop = stopped()
        out.update(reason="a dry run: nothing was sent",
                   plan=plan(now=now, asset_class=asset_class,
                             leverage=leverage, overnight=overnight,
                             forced=forced),
                   stopped=stop_words(stop) if stop is not None else "",
                   refusing=refusing(), switch=switch_on(),
                   keyed=keyed_account(user) is not None)
        return out
    if not switch_on():
        out["reason"] = f"the switch {SWITCH_KEY} is OFF: nothing was sent"
        return out
    stop = stopped()
    if stop is not None:
        return {"status": "error", "error": stop_words(stop), "row": stop.pk,
                "requests": 0}
    if not _lock():
        out["reason"] = "another pass of the demo proofs holds its lock"
        return out
    try:
        return _run(now, out, explicit=explicit, forced=forced,
                    asset_class=asset_class, leverage=leverage,
                    overnight=overnight, user=user, client=client)
    finally:
        _unlock()


def _run(now, out, *, explicit, forced, asset_class, leverage, overnight,
         user, client) -> dict:
    account = keyed_account(user) if client is None else None
    if client is None and account is None:
        out["reason"] = "no eToro keys on file: nothing to prove with"
        return out
    stale = (_rows().filter(proof_state=SENDING,
                            read_at__lte=now - timedelta(
                                seconds=SENDING_STALE_S))
             .order_by("read_at").first())
    if stale is not None:
        return _in_doubt(stale, "stopped between its order and eToro's "
                                "answer: whether eToro holds a position is "
                                "unknown", now)
    # THE LIVE LANE FIRST: a sick venue, a 429, a real close pending hold
    # every step, the runner's own demo close too (demo money waits)
    why = refusing()
    if why:
        out["reason"] = why
        return out
    if client is None:
        client = demo_client(account)
    # CLOSES FIRST: a position the runner holds is closed before anything
    # is opened, and the run ends there
    for row in (_rows().filter(proof_state__in=(OPEN, CLOSING),
                               revoked_at__isnull=True)
                .order_by("read_at", "pk")):
        if _due(row, now):
            return _close_step(client, row, now)
    last = (_rows().order_by("-read_at").values_list("read_at", flat=True)
            .first())
    if last is not None and not explicit and \
            now - last < timedelta(seconds=MIN_GAP_S):
        minutes = int((now - last).total_seconds() // 60)
        out["reason"] = (f"spaced out: the last step was {minutes} minutes "
                         f"ago and the next waits {MIN_GAP_S // 60}")
        return out
    steps = plan(now=now, asset_class=asset_class, leverage=leverage,
                 overnight=overnight, forced=forced)
    step = next((s for s in steps if s["state"] == "due"), None)
    if step is None:
        waiting = [s for s in steps if s["state"] not in ("done",
                                                          "revoked")]
        out["reason"] = ("nothing to prove now: " + "; ".join(
            step_words(s) for s in waiting[:3]) if waiting
            else "every demo short proof is recorded")
        return out
    return _open_step(client, step, now)


def _due(row, now) -> bool:
    """A held position is closed now: a round trip at once, an overnight
    hold once its next session has opened and settled."""
    if row.proof_state == CLOSING or not row.overnight:
        return True
    if row.hold_until is not None and now < row.hold_until:
        return False
    return market_words(row.symbol, row.asset_class, now, closing=True) == ""


def _spent(client, start) -> int:
    return max(0, int(getattr(client, "wire_requests", 0) or 0) - start)


def _count(row, client, start, prior) -> None:
    """The requests the row's steps cost: what it counted before this run
    (`prior`), and what this run sent since `start`."""
    if client is not None:
        row.requests = int(prior or 0) + _spent(client, start)


def _record(step, state, words, now, *, requests=0) -> dict:
    """A step eToro's row answered without an order: recorded, so it is
    not asked again inside its BACKOFF."""
    row = _model().objects.create(
        source=SOURCE, world=DEMO, asset_class=step["asset_class"],
        symbol=step["symbol"], side="short", leverage=step["leverage"],
        units=Decimal("0"), order_id="", position_id="", proof_state=state,
        refusal=str(words)[:300], overnight=step["overnight"], read_at=now,
        requests=requests)
    logger.info("[short-proofs] %s %sx: %s", step["symbol"],
                step["leverage"], words)
    return {"status": "success", "did": words, "row": row.pk,
            "requests": requests}


def venue_minimum(floor, margin_min, lev, price, *, step=1.0) -> float:
    """The smallest size of `step` whose notional clears eToro's money
    floor and whose margin at `lev` clears its margin minimum, with
    FLOOR_MARGIN to spare."""
    need = max(float(floor or 0), float(margin_min or 0) * int(lev))
    raw = need * (1 + FLOOR_MARGIN) / float(price)
    step = float(step) if step and step > 0 else 1.0
    return round(math.ceil(raw / step - 1e-9) * step, 10)


def _levels(price) -> tuple:
    """(stop above, target below) a SELL at `price`."""
    def _r(x):
        return round(x, 2 if x >= 10 else 4 if x >= 0.1 else 6)
    return _r(price * (1 + STOP_FRACTION)), _r(price * (1 - STOP_FRACTION))


def _open_step(client, step, now) -> dict:
    """eToro's demo row, then the SELL of the venue minimum, then (unless
    held overnight) its close, in this one run."""
    from bot_program.engine.etoro_client import RealSegmentRefused
    sym, icls, lev = step["symbol"], step["asset_class"], step["leverage"]
    start = int(getattr(client, "wire_requests", 0) or 0)
    skipped = {"status": "skipped", "row": None}
    try:
        state = client.eligibility_state(sym)
    except RealSegmentRefused:
        raise
    except LookupError as e:
        # eToro's own "no such instrument", or a body of a shape nobody
        # measured: not asked again for a day either way
        return _record(step, NO_ROW, f"eToro answered no row for {sym}: "
                                     f"{str(e)[:200]}", now,
                       requests=_spent(client, start))
    except Exception as e:  # noqa: BLE001 — unread: asked again later
        return dict(skipped, reason=f"eToro's demo row for {sym} is unread "
                                    f"({type(e).__name__})",
                    requests=_spent(client, start))
    if state == "absent":
        return _record(step, NO_ROW, f"eToro lists no eligibility row for "
                                     f"{sym} on the demo account", now,
                       requests=_spent(client, start))
    if state != "read":
        return dict(skipped, reason=f"eToro's demo row for {sym} is unread",
                    requests=_spent(client, start))
    try:
        allow = client.allow_open_position(sym)
        shorts = client.leverage_values(sym, "SELL", "cfd", world=DEMO) or []
        floor = client.min_notional(sym)
        margin_min = client.min_amount(sym, "SELL", "cfd", lev, world=DEMO)
        cap = client.max_units_per_order(sym)
        unit_type = client.unit_type(sym)
    except RealSegmentRefused:
        raise
    except Exception as e:  # noqa: BLE001
        return dict(skipped, reason=f"eToro's demo row for {sym} is "
                                    f"unreadable ({type(e).__name__})",
                    requests=_spent(client, start))
    if allow is False:
        return dict(skipped, reason=f"eToro does not allow opening {sym} "
                                    f"today", requests=_spent(client, start))
    if not shorts:
        return _record(step, NO_SHORT, f"eToro lists no short entry for "
                                       f"{sym} on the demo account", now,
                       requests=_spent(client, start))
    if lev not in shorts:
        return _record(step, NOT_LISTED,
                       f"eToro's demo row for {sym} offers a short at "
                       f"{', '.join(f'{v}x' for v in shorts)} only, not at "
                       f"{lev}x", now, requests=_spent(client, start))
    if floor is None or floor <= 0:
        return dict(skipped, reason=f"eToro's minimum for {sym} is unread",
                    requests=_spent(client, start))
    try:
        last = float((client.ticker(sym) or {}).get("lastPrice") or 0)
    except RealSegmentRefused:
        raise
    except Exception as e:  # noqa: BLE001 — no rate, nothing sent
        return dict(skipped, reason=f"no rate for {sym} "
                                    f"({type(e).__name__})",
                    requests=_spent(client, start))
    if not (last > 0) or not math.isfinite(last):
        return dict(skipped, reason=f"eToro quotes no rate for {sym} now",
                    requests=_spent(client, start))
    unit_step = 1.0 if unit_type == "whole" else CLASS_STEP.get(icls, 1.0)
    units = venue_minimum(floor, margin_min, lev, last, step=unit_step)
    if cap is not None and units > float(cap) + 1e-9:
        return _record(step, REFUSED, f"the venue minimum, {units:g} units, "
                                      f"is past eToro's maxUnitsPerOrder "
                                      f"{float(cap):g} for {sym}", now,
                       requests=_spent(client, start))
    stop, target = _levels(last)
    row = _model().objects.create(
        source=SOURCE, world=DEMO, asset_class=icls, symbol=sym,
        side="short", leverage=lev, units=Decimal(str(units)), order_id="",
        position_id="", proof_state=SENDING, overnight=step["overnight"],
        read_at=now)
    try:
        res = client.market_order(sym, "SELL", units, stop_loss=stop,
                                  take_profit=target,
                                  **({"leverage": lev} if lev > 1 else {}))
    except Exception as e:  # noqa: BLE001 — every outcome is named below
        return _order_failed(client, row, e, now, start)
    try:
        return _after_fill(client, row, res, units, now, start)
    except Exception as e:  # noqa: BLE001 — unknown after an order: in doubt
        logger.exception("[short-proofs] %s: the step failed after the "
                         "order", sym)
        return _in_doubt(row, f"failed after its order "
                              f"({type(e).__name__})", now, client=client,
                         start=start)


def _order_failed(client, row, e, now, start) -> dict:
    """The SELL raised. Nothing left the box, eToro refused it, or nobody
    knows: the last is in doubt, and nothing is sent again. "Nothing left
    the box" is read off the adapter's own words only (2026-10-31): a
    ValueError is NOT_SENT when it says "eToro NOT SENT" (raised before
    the POST); any other, like requests' JSONDecodeError after a 2xx, may
    follow an accepted order."""
    from bot_program.engine.etoro_client import (RealSegmentRefused,
                                                 RedirectRefused)
    text = str(e)
    if isinstance(e, RedirectRefused):
        return _in_doubt(row, f"sent a sell answered with a redirect (HTTP "
                              f"{e.status}), which was not followed: "
                              f"whether eToro holds a position is unknown",
                         now, client=client, start=start)
    if getattr(e, "in_doubt", False):
        answered = getattr(e, "answered", None)
        return _in_doubt(row, (f"sent a sell eToro answered HTTP {answered} "
                               f"with a body nobody could read"
                               if answered is not None else
                               "sent a sell whose request did not come back"),
                         now, client=client, start=start)
    code = None
    m = re.match(r"eToro refused \((\d+)\)", text)
    if m:
        code = int(m.group(1))
    if code is not None and code >= 500:
        return _in_doubt(row, f"sent a sell eToro answered with HTTP {code}: "
                              f"it may have landed", now, client=client,
                         start=start)
    if isinstance(e, RealSegmentRefused) or code == 429 \
            or (isinstance(e, ValueError)
                and text.startswith("eToro NOT SENT")) \
            or text.startswith("eToro unreachable"):
        state = NOT_SENT
    elif code is not None:
        state = REFUSED
    else:
        return _in_doubt(row, f"sent a sell that raised {type(e).__name__}",
                         now, client=client, start=start)
    row.proof_state = state
    row.refusal = text[:300]
    row.requests = _spent(client, start)
    row.save(update_fields=["proof_state", "refusal", "requests"])
    return {"status": "success", "did": f"{row.symbol}: {text[:160]}",
            "row": row.pk, "requests": row.requests}


def _after_fill(client, row, res, units, now, start) -> dict:
    from bot_program.short_readback import (fill_reading, judge,
                                            observation_facts)
    status = str(res.get("status") or "")
    row.order_id = str(res.get("orderId") or "")
    if status in ("FILLED", "PARTIALLY_FILLED"):
        reading = fill_reading(res)
        if reading is None and row.order_id:
            try:
                reading = client.order_status(row.order_id)
            except Exception:  # noqa: BLE001 — could-not-ask
                reading = None
        verdict = judge(reading, sent_units=units,
                        sent_leverage=row.leverage,
                        position_id=str(res.get("positionId") or ""))
        if isinstance(reading, dict) and isinstance(reading.get("raw"),
                                                    dict):
            for key, value in observation_facts(
                    reading, units=units, order_id=row.order_id).items():
                setattr(row, key, value)
        if not row.position_id:
            row.position_id = str(res.get("positionId") or "")
        if row.open_rate:
            row.notional = (row.units * row.open_rate).quantize(
                Decimal("0.000001"))
        row.close_lookup = {"verdict": verdict["state"],
                            "facts": verdict["facts"],
                            "held_at_fill": verdict["held"]}
        if not row.position_id:
            return _in_doubt(row, "was filled with no position named to "
                                  "close", now, client=client, start=start)
        row.proof_state = OPEN
        if row.overnight and verdict["ok"]:
            row.hold_until = hold_until_for(row.symbol, row.asset_class, now)
            row.requests = _spent(client, start)
            row.save()
            from core.exchange_status import utc_words
            return {"status": "success",
                    "did": (f"{row.symbol} short held across the close, due "
                            f"to close {utc_words(row.hold_until)}"),
                    "row": row.pk, "requests": row.requests}
        row.requests = _spent(client, start)
        row.save()
        return _close_step(client, row, now, start=start)
    if status in ("REJECTED", "CANCELLED", "EXPIRED"):
        row.proof_state = REFUSED
        row.refusal = str(res.get("refusal") or f"eToro answered "
                                                f"{status}")[:300]
        row.lookup = _scrub((res.get("raw") or {}).get("lookup") or {})
        row.requests = _spent(client, start)
        row.save()
        return {"status": "success",
                "did": f"{row.symbol} {row.leverage}x: {row.refusal}",
                "row": row.pk, "requests": row.requests}
    if res.get("pollFailed"):
        return _in_doubt(row, "sent a sell no orders:lookup could read "
                              "afterwards: eToro may hold a position", now,
                         client=client, start=start)
    try:
        withdrawn = client.cancel_order(row.order_id)
    except Exception:  # noqa: BLE001 — a DELETE that raised proves nothing
        withdrawn = None
    if withdrawn is True:
        held = ((res.get("raw") or {}).get("statusName")) or "working"
        row.proof_state = WITHDRAWN
        row.refusal = (f"eToro held the order ({held}) and it was "
                       f"withdrawn")
        row.requests = _spent(client, start)
        row.save()
        return {"status": "success", "did": f"{row.symbol}: {row.refusal}",
                "row": row.pk, "requests": row.requests}
    return _in_doubt(row, "sent a sell eToro held, whose withdrawal was not "
                          "proven", now, client=client, start=start)


def _scrub(value):
    from bot_program.short_readback import scrub
    return scrub(value)


def _close_step(client, row, now, *, start=None) -> dict:
    """Close the position by its id and prove it by the open order's
    state; an overnight hold's /portfolio row is read first (its fee).
    A close whose request did not come back is in doubt. `start` is the
    wire count the open of this same run began at; a later run's close
    starts its own count on top of the row's."""
    from bot_program.engine.etoro_client import RedirectRefused, TRANSPORT
    prior = 0
    if start is None:
        start = int(getattr(client, "wire_requests", 0) or 0)
        prior = row.requests
    record = dict(row.close_lookup or {})
    if row.overnight and "held" not in record:
        try:
            held = client.position_row(row.position_id)
            record["held"] = _scrub(held) if held else None
        except Exception as e:  # noqa: BLE001 — the fee is then unread
            record["held_unread"] = type(e).__name__
    if row.proof_state == CLOSING:
        state = client.position_state(row.order_id, attempts=1, delay=0.0)
        if state == "closed":
            row.close_lookup = record
            return _finish(client, row, now, start, prior)
        if state is None:
            row.close_lookup = record
            row.save(update_fields=["close_lookup"])
            return {"status": "skipped", "reason": f"{row.symbol}: the "
                    f"close's proof is unread; the next pass reads it again",
                    "row": row.pk, "requests": _spent(client, start)}
    attempts = int(record.get("close_attempts") or 0) + 1
    if attempts > MAX_CLOSE_ATTEMPTS:
        row.close_lookup = record
        return _in_doubt(row, f"was sent {MAX_CLOSE_ATTEMPTS} closes and none "
                              f"was proven", now, client=client, start=start,
                         prior=prior)
    record["close_attempts"] = attempts
    row.close_lookup = record
    row.save(update_fields=["close_lookup"])
    try:
        res = client.close_position(row.position_id, row.symbol,
                                    units=float(row.units),
                                    open_order_id=row.order_id)
    except TRANSPORT as e:
        return _in_doubt(row, f"was sent a close whose request did not come "
                              f"back ({type(e).__name__})", now,
                         client=client, start=start, prior=prior)
    except RedirectRefused as e:
        return _in_doubt(row, f"was sent a close answered with a redirect "
                              f"(HTTP {e.status}), which was not followed: "
                              f"whether it closed is unknown", now,
                         client=client, start=start, prior=prior)
    except Exception as e:  # noqa: BLE001 — refused: the next pass again
        row.refusal = f"eToro refused the close: {str(e)[:200]}"
        row.proof_state = OPEN
        _count(row, client, start, prior)
        row.save(update_fields=["refusal", "proof_state", "requests"])
        return {"status": "error",
                "error": f"{row.symbol}: {row.refusal}; the next pass "
                         f"closes it again", "row": row.pk,
                "requests": _spent(client, start)}
    row.close_order_id = str(res.get("orderId") or "")
    record["close"] = _scrub(res.get("raw") or {})
    row.close_lookup = record
    if res.get("positionState") == "closed":
        return _finish(client, row, now, start, prior)
    row.proof_state = CLOSING
    _count(row, client, start, prior)
    row.save()
    return {"status": "success",
            "did": f"{row.symbol}: the close was sent and eToro has not "
                   f"shown it closed yet; the next pass reads it again",
            "row": row.pk, "requests": _spent(client, start)}


def _fee_of(held) -> tuple:
    if not isinstance(held, dict):
        return None, ""
    for key in FEE_KEYS:
        raw = held.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            return float(raw), key
        except (TypeError, ValueError):
            continue
    return None, ""


def _finish(client, row, now, start, prior=0) -> dict:
    """The close is proven: read the order once more (the close), record
    the round trip, and a clean one is a demo proof."""
    record = dict(row.close_lookup or {})
    try:
        after = client.order_status(row.order_id)
    except Exception:  # noqa: BLE001 — the close stands proven
        after = None
    if isinstance(after, dict):
        record["after_close"] = _scrub(after.get("raw") or {})
    row.closed_at = now
    clean = record.get("verdict") == "clean"
    if row.overnight:
        row.nights = nights_between(row.read_at, now)
        fee, key = _fee_of(record.get("held"))
        record["fee_key"] = key
        if fee is not None:
            row.overnight_fee = Decimal(str(round(fee, 6)))
        elif clean:
            row.refusal = ("the held position printed no fee this platform "
                           "knows: the overnight fee is unread")
    if not clean and not row.refusal:
        row.refusal = ("; ".join(str(f) for f in record.get("facts") or [])
                       or "the fill was not read clean before the close")[:300]
    row.proof_state = PROVEN if clean else MISMATCH
    row.demo_proven = clean
    # A STEP HELD WHILE ITS PAIR WAS REVOKED (2026-10-31): the superuser
    # revoked every standing proof of this (class, multiplier) after this
    # step opened. Its clean close is recorded, revoked with the pair, by
    # that act (its time, its author): it proves nothing anew by itself,
    # and nobody is told the class opened.
    revoked = _revoked_since(row) if clean else None
    if revoked is not None:
        row.revoked_at = revoked.revoked_at
        row.revoked_by_id = revoked.revoked_by_id
        row.revoke_reason = (
            f"the proofs of {a_class(row.asset_class)} short at "
            f"{row.leverage}x were revoked while it was held: not proven "
            f"anew by itself")[:200]
    row.close_lookup = record
    _count(row, client, start, prior)
    row.save()
    if revoked is not None:
        did = (f"{row.symbol} short at {row.leverage}x closed clean on the "
               f"demo account, revoked with its pair while it was held: not "
               f"proven anew by itself")
    elif clean:
        _announce(row, now)
        did = f"{row.symbol} short at {row.leverage}x proven on the demo " \
              f"account"
    else:
        _tell_mismatch(row)
        did = (f"{row.symbol} short at {row.leverage}x closed, not proven: "
               f"{row.refusal}")
    return {"status": "success", "did": did, "row": row.pk,
            "requests": _spent(client, start)}


def _revoked_since(row):
    """The newest proof of `row`'s (class, multiplier) a superuser revoked
    after `row` opened (read_at), or None: the pair was revoked while the
    step was held at eToro's demo account."""
    return (_rows().filter(world=DEMO, side="short", demo_proven=True,
                           asset_class=row.asset_class,
                           leverage=row.leverage,
                           revoked_at__gte=row.read_at)
            .exclude(pk=row.pk).order_by("-revoked_at").first())


# ── who is told ─────────────────────────────────────────────────────────

def _announce(row, now) -> None:
    """The operator hears the first proof of a (class, multiplier)."""
    others = (_rows().filter(asset_class=row.asset_class,
                             leverage=row.leverage, demo_proven=True,
                             revoked_at__isnull=True)
              .exclude(pk=row.pk).exists())
    if others:
        return
    title = PROVEN_TITLE.format(cls=class_name(row.asset_class),
                                lev=row.leverage)
    levels = sorted(proven_leverages(row.asset_class) | {int(row.leverage)})
    body = (f"Measured on {row.symbol}, on eToro's demo account: "
            f"{row.units.normalize():f} units sold short, filled as sent "
            f"and closed by position id. The bots' gate now lets "
            f"{a_class(row.asset_class)} short through at "
            f"{', '.join(f'{v}x' for v in levels)} only, still behind every "
            f"other gate. Revoke it on /short-proofs/ with your trading PIN.")
    try:
        from bot_program.notifications import notify_staff
        notify_staff(title=title, body=body, url="/short-proofs/")
        row.notified_at = now
        row.save(update_fields=["notified_at"])
    except Exception as e:  # noqa: BLE001 — the page says it in any case
        logger.warning("[short-proofs] the operator was not told of %s "
                       "(%s)", title, type(e).__name__)


def _tell_mismatch(row) -> None:
    try:
        from bot_program.notifications import notify_staff
        notify_staff(
            title=(f"A demo short of {class_name(row.asset_class)} "
                   f"({row.symbol}) was closed without a proof"),
            body=(f"On eToro's demo account: {row.refusal}. Nothing opens "
                  f"to the bots; the step is asked again in a day."),
            url="/short-proofs/")
    except Exception as e:  # noqa: BLE001
        logger.warning("[short-proofs] the staff were not told of a "
                       "mismatch (%s)", type(e).__name__)


def _in_doubt(row, words, now, *, client=None, start=0, prior=0) -> dict:
    """Stop: nothing is sent again until a superuser clears this row, and
    the alarm chat and the staff are told. No amount, no id."""
    row.proof_state = IN_DOUBT
    row.demo_proven = False
    row.refusal = f"eToro's demo account {words}"[:300]
    _count(row, client, start, prior)
    row.save()
    lines = [
        f"Demo account only: the platform's own short proof on "
        f"{class_name(row.asset_class)} ({row.symbol}) {words}.",
        "Nothing is sent again: the demo proofs have stopped.",
        f"Check eToro's demo account for {row.symbol} and close what it "
        f"holds there, then clear the stop on /short-proofs/ with your "
        f"trading PIN."]
    logger.error("[short-proofs] IN DOUBT: %s %s — %s", row.symbol,
                 row.leverage, words)
    try:
        from bot_program import alarm
        alarm.send_alarm(IN_DOUBT_TITLE, lines)
    except Exception as e:  # noqa: BLE001 — the staff are told below
        logger.warning("[short-proofs] the alarm chat was not told (%s)",
                       type(e).__name__)
    try:
        from bot_program.notifications import notify_staff
        notify_staff(title=f"{IN_DOUBT_TITLE} ({row.symbol})",
                     body=" ".join(lines), url="/short-proofs/",
                     cooldown_hours=1)
    except Exception as e:  # noqa: BLE001
        logger.warning("[short-proofs] the staff were not told (%s)",
                       type(e).__name__)
    return {"status": "error", "error": f"{IN_DOUBT_TITLE}: {row.symbol} "
                                        f"{words}",
            "row": row.pk, "requests": row.requests}


# ── the page's door ─────────────────────────────────────────────────────

def standing_pair(row):
    """Every standing demo proof of `row`'s (class, multiplier), oldest
    first: what the bots' gate reads for that pair (proven_leverages)."""
    return list(_rows().filter(world=DEMO, side="short", demo_proven=True,
                               revoked_at__isnull=True,
                               asset_class=row.asset_class,
                               leverage=row.leverage)
                .order_by("read_at", "pk"))


def revoke(row, *, user=None, reason="") -> list:
    """A superuser's revoke of a proof (the gate reads it no more), or
    clear of an in-doubt stop (the runner goes on), with ONE audit row;
    the rows it marked, oldest first. The view asks the trading PIN first
    (an ACT door).

    A PROOF IS REVOKED BY ITS (class, multiplier) (2026-10-31): the gate
    opens a multiplier on ANY standing demo proof of it, and a class's 1x
    is proven twice in the normal sequence (the round trip, then the
    overnight hold, itself a clean 1x fill-and-close), more when a step is
    run again by hand. Revoking one of them left the gate open. So every
    standing proof of the pair is revoked at once, and the audit row names
    them all; a step of the pair still held at eToro's demo account is
    revoked with it when it closes (_finish, _revoked_since)."""
    from django.utils import timezone

    from bot_program import audit
    clearing = row.proof_state == IN_DOUBT
    rows = [row] if clearing else (
        [row if r.pk == row.pk else r for r in standing_pair(row)] or [row])
    when = timezone.now()
    who = user if getattr(user, "pk", None) else None
    for r in rows:
        r.revoked_at = when
        r.revoked_by = who
        r.revoke_reason = str(reason or "")[:200]
        r.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
    audit.record_short_proof(
        audit.SHORT_PROOF_CLEARED if clearing else audit.SHORT_PROOF_REVOKED,
        row=row, rows=rows, who=getattr(user, "username", "") or "",
        reason=reason, user=user)
    return rows


def gate_words() -> list:
    """[(class, words)]: what the bots' gate lets a short through at now,
    per class."""
    from bot_program.asset_engine import base
    out = []
    for icls in ("stock", "etf", "index", "forex", "commodity", "crypto"):
        if icls not in base.ETORO_PROVEN:
            words = "no class proof pinned: no bot entry at all"
        elif base.short_pinned(icls):
            words = ("pinned in the code: at any multiplier eToro's LIVE "
                     "list, the ceiling and the band allow")
        else:
            levels = sorted(base.demo_short_leverages(icls))
            words = (f"proven on the demo account at "
                     f"{', '.join(f'{v}x' for v in levels)}: the bots short "
                     f"it at {'that multiplier' if len(levels) == 1 else 'those multipliers'} only"
                     if levels else
                     "not proven: the bots do not short it (a short taken "
                     "by hand goes, warned and read back)")
        out.append((class_name(icls), words))
    return out


def page_rows(limit=200) -> list:
    rows = list(_rows().select_related("revoked_by")
                .order_by("-read_at", "-pk")[:limit])
    out = []
    for r in rows:
        out.append({
            "row": r,
            "class_name": class_name(r.asset_class),
            "can_revoke": r.revoked_at is None and r.demo_proven,
            "can_clear": r.revoked_at is None and r.proof_state == IN_DOUBT,
        })
    return out
