"""THE MORGUL GUARDS: the orcs that save Sauron from itself (2026-09-26).

The operator, 2026-09-26/27: "we need a 'Morgul', or orcs to save Sauron
from itself" -- "guards". The trigger: on Saturday 2026-09-26 at 13:53 UTC
two paper forex positions (EURCAD, GBPCAD) were closed while forex was
shut, at a Friday price the OANDA stream made look fresh, and nothing on
the platform noticed. From 2026-09-28 the operator is away for three
weeks and his father runs Sauron from his phone: what the book does wrong
must reach the group without anyone asking, in English, once.

WHAT A GUARD IS
  A key, a name in words, a severity (warning or critical), a check that
  READS the database -- the rows, the stamps the engine and the syncs
  already wrote, the component table, the cache -- and returns findings
  (a subject and its facts as lines), and whether its critical findings
  may pull the brake. No guard calls a broker, sends an order or closes
  anything; tests/test_morgul.py greps this file for it.

    G1  Market-shut booking    critical, brake   a booking in the last 24 h
                                                 while its market was shut
    G2  Live without a stop    critical          no stop rests at the broker
                                                 for 10 min (eToro's "no stop"
                                                 echo included); a stop the
                                                 broker moved FARTHER (warning)
    G3  Stuck close            warning at 30 min, critical at 4 h (a warning
                                                 while the market is shut)
    G4  Price sanity           warning           5% (forex, index) / 15% from
                                                 the nearest 1h/4h bar close
    G5  Proofs and ceilings    critical, brake   a live eToro row past its
                                                 proof, class ceiling or proven
                                                 multiplier
    G6  Margin                 critical, brake   pledged past the fraction + 5
                                                 points on fresh cells of the
                                                 account's own world; stale or
                                                 other-world cells (warnings)
    G7  Daily loss             critical, brake   realized LIVE P&L, 24 h, past
                                                 the configs' daily stop
    G8  Duplicates             warning           two open live rows, one
                                                 config, symbol and side
    G9  Drift                  critical          the stored eToro snapshot of
                                                 the LIVE world and the open
                                                 live rows disagree, 15 min
    G10 Heartbeat              critical          the bot tick, and the marks
                                                 of the live bots' symbols

  THE WORLDS. A row is paper (the simulator), demo (paper=False routed to
  eToro's virtual segment, metadata broker_env "paper") or live (real
  money); every label says which. G2 and G7 judge live rows only, G9 the
  live account only, and each says what it left out.

HOW IT SPEAKS (G0)
  Every guard runs in its own try: a guard that raises becomes a finding,
  "Guard <name> could not run: <type>", never silence -- and the findings
  it had before stay open (a blind guard is not a healthy one). A guard
  that runs but cannot judge a subject (no fresh snapshot, a market shut)
  says so in its notes and keeps what it said before about that subject
  (Context.blind): "back to normal" is said only of what was judged
  healthy. A finding reaches the staff Telegram group (the chat the Eye
  answers, through notifications._send_telegram) once per (guard,
  subject) per three hours, at once when a warning turns critical, and one
  "back to normal" line when it stops. A finding about a past EVENT (a
  booking, a price) is said once: it is true for 24 hours and repeating it
  adds nothing. The memory is the cache (STATE_KEY, seven days); a cache
  that is down forgets, and a finding said twice is better than one never
  said. Quiet hours do not hold a guard back, as they do not hold the
  digest. One run at a time (LOCK_KEY): a backlog never sends twice.

THE BRAKE (G11)
  A second component, BRAKE_KEY, OFF on arrival and never switched on by a
  group's "all on" button (core.platform_control.BULK_ENABLE_EXEMPT). It
  acts only while the guards themselves are on. While it is off a critical
  finding of a braking guard says which bots it WOULD stop. While it is on
  it stops them, once per finding, through the Eye's own
  telegram_eye.apply_brake: enabled = False on the configs named, never
  on, never a close, never an order. It reads every critical finding of
  the run, not only those due -- the three hours are the group's, not
  the brake's: a finding said while it was off is stopped on the first
  run after it is armed, and that run says so. G1 and G5 stop the row's
  config; G6 and G7 every enabled live config of the user. The message
  says what the stopped bots leave open: a live position without a stop
  at the broker is protected by nothing while its bot is stopped, and
  paper stops pause.
  It never acts when no staff chat could be told, and its record is kept
  before anything else can fail: a stop is always announced, at the
  latest on the next run. A bot the operator re-arms is not stopped again
  for the same finding -- while the cache remembers: a flushed cache
  forgets, and a finding still standing then stops it again, and says so.

WHAT IT REUSES
  telegram_eye's house style (Reply, fit, heading, money, price, when,
  ago, config_label, plain_detail) and its brake; core.exchange_status's
  market_clock (the clock the paper venue's gate reads: the strip the
  badges read, plus the 17:00 New York forex week in winter and the NYSE
  holidays and early closes -- no clock of its own; market_status_for
  only names the session);
  asset_engine.base's proof set, ceilings, pledged fraction and proven
  multiplier, read at call time; safety's heartbeat stamp
  (extras["last_tick_at"]); the LiveQuote marks of the live bots' own
  symbols; the eToro sync's stored cells and holdings. Where an alert already fires (notify_protection_vanished, the
  fill-time stop-rewrite alert, notify_unclaimed_position, the drawdown
  warning) the guard reads the same state and says it in its own words,
  on its own cadence: those fire once, at the moment; a guard repeats
  while the fact stands.

Doors: bot_program.tasks.run_morgul_guards (every 5 min, fast queue, gated
by COMPONENT_KEY, OFF on arrival), `manage.py morgul` (prints; sends only
with --send), the /health/ row (health_row) and the Eye's /status line
(status_line).
"""
from __future__ import annotations

import logging
from collections import Counter, OrderedDict
from datetime import timedelta

from bot_program import telegram_eye as eye

logger = logging.getLogger(__name__)

COMPONENT_KEY = "morgul_guards"
BRAKE_KEY = "morgul_brake"
#: The shield: every Morgul message leads with it.
MARK = "\U0001F6E1️"
SEVERITIES = ("warning", "critical")

#: A standing finding is said again after this long, never sooner.
REMIND_S = 3 * 3600
STATE_KEY = "morgul:state"
SUMMARY_KEY = "morgul:summary"
SINCE_KEY = "morgul:since:{scope}"
STATE_TTL_S = 7 * 86400
#: The /status line and the /health/ row call a summary older than this
#: stale (the beat runs every five minutes).
SUMMARY_STALE_S = 900

#: G1, G4, G5, G7: the bookings of the last day.
WINDOW_H = 24
#: G1: a booking this soon after the close is a tick in flight, not a
#: stale price (the clock is judged at the booking AND this long before).
CLOSE_GRACE_S = 300
#: G1: a live fill the tick NOTICED (a working entry, entry_filled_at is
#: the poll's time) may have filled at the venue up to this long before.
NOTICED_GRACE_S = 900
#: G1: the marker the close retry leaves on a live row it booked
#: (pending_closes._finalise_closed: "closed:RETRY", "..._ALREADY_FLAT",
#: "..._WORKING_CLOSE_FILLED"): its time is the drain's, not the fill's.
RETRY_MARK = "closed:RETRY"
#: G2: how long a live row may run without a stop at the broker.
NO_STOP_AFTER_S = 600
#: G2: eToro's "no stop" echo: a held stop at or under this is no stop
#: (base.stop_moved_words and the working-fill path read it the same way).
NO_STOP_SENTINEL = 0.0001
#: G3: CLOSE_PENDING this long is a warning, then critical.
STUCK_WARN_S = 1800
STUCK_CRIT_S = 4 * 3600
#: G3: retry_pending_closes runs every five minutes, so N retries mean the
#: close has been pending at least N x this.
RETRY_EVERY_S = 300
#: G4: how far a booked price may sit from the nearest bar close, per
#: instrument class; a class absent is not judged, and said so.
PRICE_LIMITS = {"forex": 0.05, "index": 0.05, "stock": 0.15, "etf": 0.15,
                "commodity": 0.15, "crypto": 0.15}
BAR_WINDOW_S = 3600
TIMEFRAME_WORDS = {"1h": "one-hour", "4h": "four-hour"}
#: G6: the alarm sits this far above MAX_PLEDGED_FRACTION.
MARGIN_SLACK = 0.05
MARGIN_STALE_S = 3600
#: G9: a row younger than this at the snapshot may not be listed yet, and
#: a position no row claims is said once it has stood this long.
DRIFT_AFTER_S = 900
SNAPSHOT_STALE_S = 3600
#: G10: the tick beats every five minutes.
TICK_STALE_S = 900
#: G10: a market judged for marks only once it has been open this long.
FEED_OPEN_FOR_S = 1800
#: G10: the freshest mark of a live class's symbols older than this is
#: stale (the slowest declared poller is dead at an hour, feeds._SLOW_POLL).
MARK_STALE_S = 3600
#: G1: the classes core.exchange_status keeps a clock for (options on the
#: venue session, the one the paper market-hours gate of the same day
#: reads). Crypto never shuts; anything else (cfd, an unknown class) is
#: not judged, and said so.
CLOCK_CLASSES = ("forex", "stock", "etf", "index", "commodity", "options")
OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")
BOOKED_STATUSES = ("OPEN", "CLOSE_PENDING", "CLOSED")
#: One run at a time: a worker back from an outage drains the queued runs
#: two at a time, and both would read the same memory before either wrote.
LOCK_KEY = "morgul:lock"
LOCK_S = 240
BACK_TO_NORMAL = "Morgul — back to normal"
GUARD_FAILED = "Morgul — a guard could not run"


# ── the frame ────────────────────────────────────────────────────────────

class Guard:
    """One guard: its key, its name in words, its severity, the title its
    findings carry, its check, and whether its critical findings brake."""

    def __init__(self, key, name, severity, title, check, *, brake=False):
        assert severity in SEVERITIES, severity
        self.key = key
        self.name = name
        self.severity = severity
        self.title = title
        self.check = check
        self.brake = bool(brake)

    def finding(self, subject, **kw):
        kw.setdefault("title", self.title)
        return Finding(self, subject, **kw)

    def __repr__(self):
        return f"Guard({self.key})"


class Finding:
    """What a guard found about one subject: its facts as lines, and the
    configs the brake may stop for it (with the user they belong to)."""

    def __init__(self, guard, subject, *, title, label, facts,
                 severity=None, event=False, user=None, configs=()):
        self.guard = guard
        self.subject = str(subject)
        self.title = title
        self.label = str(label)
        self.facts = [str(f) for f in facts if str(f or "").strip()]
        self.severity = severity or guard.severity
        self.event = bool(event)
        self.user = user
        self.configs = list(dict.fromkeys(int(c) for c in configs))

    @property
    def key(self) -> str:
        return f"{self.guard.key}|{self.subject}"

    @property
    def brakes(self) -> bool:
        return (self.guard.brake and self.severity == "critical"
                and self.user is not None and bool(self.configs))


class Context:
    """One run: its clock, whether it may write its memory, the notes it
    prints (what was not judged, and why), the subjects a guard could not
    judge, and a per-run instrument cache."""

    def __init__(self, now, persist=False):
        self.now = now
        self.persist = bool(persist)
        self.notes = []
        #: {guard key: subjects it could not judge this run}
        self.unjudged = {}
        self._instruments = {}

    def note(self, guard, text) -> None:
        self.notes.append(f"{guard.name}: {text}")

    def blind(self, guard, subjects) -> None:
        """Subjects this guard could not judge this run (no fresh
        snapshot, a market shut): what it said about them before stays
        open, never "back to normal" -- a guard that cannot see is not a
        healthy one."""
        self.unjudged.setdefault(guard.key, set()).update(
            str(s) for s in subjects)

    def instrument(self, symbol, fallback) -> tuple:
        """(class, exchange, pk) of the instrument row, the router's own
        key; the row's class when no instrument row exists."""
        key = str(symbol or "").upper()
        if key not in self._instruments:
            from instruments.models import Instrument
            self._instruments[key] = (
                Instrument.objects.filter(symbol=symbol)
                .values_list("asset_class", "exchange", "pk").first())
        row = self._instruments[key]
        if row is None:
            return str(fallback or ""), "", None
        return str(row[0] or fallback or ""), str(row[1] or ""), row[2]

    def since(self, scope, subjects, keep=()) -> dict:
        """{subject: when this guard first saw it}, from the cache; now for
        a subject not seen before. Only the subjects given are kept, with
        those in `keep` (subjects it could not judge this run) carried
        over as they were, and only when the run may write (a `manage.py
        morgul` without --send reads, never writes)."""
        from django.core.cache import cache
        key = SINCE_KEY.format(scope=scope)
        try:
            old = cache.get(key) or {}
        except Exception:  # noqa: BLE001 (a cache down forgets, never raises)
            old = {}
        if not isinstance(old, dict):
            old = {}
        out = {}
        for subject in subjects:
            seen = eye._parse_iso(old[subject]) if old.get(subject) else None
            out[subject] = seen if seen is not None and seen <= self.now \
                else self.now
        if self.persist:
            carried = {s: old[s] for s in keep
                       if s not in out and old.get(s)}
            try:
                cache.set(key, dict(carried, **{
                    s: at.isoformat() for s, at in out.items()}),
                    STATE_TTL_S)
            except Exception:  # noqa: BLE001
                logger.warning("[morgul] could not remember %s", scope)
        return out


def _meta(trade) -> dict:
    meta = getattr(trade, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _parse(value):
    return eye._parse_iso(value) if value else None


def _float(value):
    d = eye._dec(value)
    return None if d is None else float(d)


def _class_word(cls) -> str:
    return eye.CLASS_WORDS.get(cls, str(cls or "unknown").replace("_", " "))


def _plural(n, word) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _world(trade) -> str:
    """paper (the simulator), demo (paper=False routed to eToro's virtual
    segment: the venue's world stamp broker_env "paper", base.VENUE_WORLDS)
    or live (real money)."""
    if trade.paper:
        return "paper"
    return "demo" if _meta(trade).get("broker_env") == "paper" else "live"


def _trade_label(trade) -> str:
    side = eye.SIDE_WORDS.get(trade.side, str(trade.side or "").lower())
    return (f"{trade.symbol} {side} #{trade.pk} · {_world(trade)} · "
            f"{eye.config_label(trade.config)}")


def _held_stop(meta) -> tuple:
    """(sent, held) off the venue's echo at the fill (the
    stop_rewritten_by_venue stamp), floats or None."""
    moved = meta.get("stop_rewritten_by_venue")
    if not isinstance(moved, dict):
        return None, None
    return _float(moved.get("sent")), _float(moved.get("held"))


def _no_venue_stop(meta) -> bool:
    """eToro echoed NO stop at the fill: a held stop at or under the
    0.0001 sentinel, or a zero. On an immediate fill `protected` records
    what was SENT (etoro_client sets protectedOnFill from the legs it
    posted), so this stamp is the only trace of it."""
    _sent, held = _held_stop(meta)
    return held is not None and held <= NO_STOP_SENTINEL


def _bare(meta) -> bool:
    """No stop rests at the broker: the engine's own `protected` fact is
    False, eToro reported no stop on a held order's fill
    (venue_stop_unread), or eToro echoed no stop on an immediate one."""
    return (not meta.get("protected") or bool(meta.get("venue_stop_unread"))
            or _no_venue_stop(meta))


def _entry_at(trade):
    """When the entry was BOOKED: the fill of a working entry, else the
    row's own opened_at; None while the order still works (no booking)."""
    meta = _meta(trade)
    if meta.get("entry_working"):
        return None
    return _parse(meta.get("entry_filled_at")) or trade.opened_at


def _noticed_close(trade) -> bool:
    """A close booked when the platform NOTICED it, not at a fill it sent
    that moment: a reconciliation (the broker had closed it), or a live
    row the close retry drained (RETRY_MARK: the retry finds the broker
    flat and books the mark, or books a close it re-sent). Its time is the
    noticing, not the fill. A paper row is always judged at its booking:
    the simulator's time is the fill."""
    meta = _meta(trade)
    reason = str(trade.reason or "")
    return ("reconciled" in reason
            or "exit_price_inferred" in meta
            or "close_filled_reconciled_at" in meta
            or (not trade.paper and RETRY_MARK in reason))


def _leverage(meta) -> int:
    """The multiplier the row records (base.execute_entry's stamp, or the
    attack mode's); 1 when absent -- absent is 1x on the wire."""
    for raw in (meta.get("leverage"),
                (meta.get("attack") or {}).get("leverage")
                if isinstance(meta.get("attack"), dict) else None):
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val >= 1:
            return val
    return 1


def _recent_rows(ctx):
    """The rows that may carry a booking of the last 24 h: opened or
    closed in it, and every open row -- a working entry is booked at its
    FILL (entry_filled_at), which may be days after its opened_at."""
    from django.db.models import Q
    from bot_program.asset_models import AssetBotTrade
    since = ctx.now - timedelta(hours=WINDOW_H)
    return since, (AssetBotTrade.objects.filter(status__in=BOOKED_STATUSES)
                   .filter(Q(opened_at__gte=since) | Q(closed_at__gte=since)
                           | Q(status__in=OPEN_STATUSES))
                   .select_related("config", "config__user").order_by("pk"))


def _bookings(trade, since) -> list:
    """(what, when, price) for each booking of this row inside the window."""
    out = []
    entry = _entry_at(trade)
    if entry is not None and entry >= since:
        out.append(("Opened", entry, trade.entry_price))
    if (trade.status == "CLOSED" and trade.closed_at is not None
            and trade.closed_at >= since):
        out.append(("Closed", trade.closed_at, trade.exit_price))
    return out


def _live_configs(user):
    from bot_program.asset_models import AssetBotConfig
    return list(AssetBotConfig.objects.filter(user=user, enabled=True,
                                              mode="live").order_by("pk"))


def _shut(cls, exchange, symbol, at) -> bool:
    """Shut at `at` on the clock the paper venue's gate reads
    (core.exchange_status.market_clock): the strip's hours, plus the
    17:00 New York forex week -- Sunday 22:00 UTC from November to
    March, the hour a poller can re-stamp Friday's close -- and the NYSE
    holidays and early closes. The strip alone (market_status_for) reads
    open in all of those; here it only names the session."""
    from core.exchange_status import market_clock
    return not market_clock(cls, exchange, symbol=symbol,
                            now_utc=at).get("is_open", True)


# ── G1: a booking while the market was shut ──────────────────────────────

def check_market_shut(ctx, g) -> list:
    """Every booking (open or close, paper, demo or live) of the last
    24 h, judged on the paper venue's own clock (_shut) at the booking
    and a grace before it (CLOSE_GRACE_S; NOTICED_GRACE_S for a live fill
    the tick noticed). Not judged, and said so: crypto (it never shuts), a
    class the clock does not model, a close booked when the platform
    noticed it (_noticed_close), and an index booked at a broker -- the
    clock keeps the cash session (SPX500 on New York) while a broker's
    index CFD trades nearly round the clock; paper index rows are judged,
    as the paper venue's own gate judges them."""
    from core.exchange_status import market_status_for
    since, rows = _recent_rows(ctx)
    out, unmodelled, noticed, cfd = [], Counter(), 0, 0
    for trade in rows:
        cls, exchange, _pk = ctx.instrument(trade.symbol, trade.asset_class)
        if cls == "crypto":
            continue
        bookings = _bookings(trade, since)
        if not bookings:
            continue
        if cls not in CLOCK_CLASSES:
            unmodelled[cls or "unknown"] += 1
            continue
        if cls == "index" and not trade.paper:
            cfd += len(bookings)
            continue
        facts = []
        for what, at, px in bookings:
            if what == "Closed" and _noticed_close(trade):
                noticed += 1
                continue
            grace = (NOTICED_GRACE_S if what == "Opened" and not trade.paper
                     and _meta(trade).get("entry_filled_at")
                     else CLOSE_GRACE_S)
            if not (_shut(cls, exchange, trade.symbol, at)
                    and _shut(cls, exchange, trade.symbol,
                              at - timedelta(seconds=grace))):
                continue
            status = market_status_for(cls, exchange, now_utc=at,
                                       symbol=trade.symbol)
            facts.append(f"{what} {eye.when(at)} at {eye.price(px)}")
            facts.append("Market shut then: "
                         f"{status.get('name') or status.get('session')}")
        if facts:
            facts.append("A price booked while its market is shut is a "
                         "stale price")
            out.append(g.finding(
                f"trade:{trade.pk}", label=_trade_label(trade), facts=facts,
                event=True, user=trade.config.user,
                configs=[trade.config_id]))
    if unmodelled:
        ctx.note(g, "not judged, the market clock does not model "
                 + ", ".join(f"{_class_word(c)} ({n})"
                             for c, n in sorted(unmodelled.items())))
    if noticed:
        ctx.note(g, f"{_plural(noticed, 'close')} booked by reconciliation "
                 "or by the close retry not judged: the time is when the "
                 "platform noticed, not the fill")
    if cfd:
        ctx.note(g, f"{_plural(cfd, 'index booking')} at a broker not "
                 "judged: the clock keeps the cash session, and a broker's "
                 "index CFD trades nearly round the clock")
    return out


# ── G2: a live position without a stop at the broker ─────────────────────

def check_no_stop(ctx, g) -> list:
    """An open live row whose stop does not rest at the broker (_bare: the
    engine's own `protected` fact, eToro's venue_stop_unread, or eToro's
    "no stop" echo on an immediate fill) for more than NO_STOP_AFTER_S
    since it was booked or since the stop vanished. And a stop the broker
    holds FARTHER from the entry than the one sent (the
    stop_rewritten_by_venue stamp, a real held price), as a warning. Demo
    rows are virtual money: counted in the notes, not judged."""
    from bot_program.asset_models import AssetBotTrade
    rows = (AssetBotTrade.objects.filter(paper=False,
                                         status__in=OPEN_STATUSES)
            .select_related("config", "config__user").order_by("pk"))
    out, demo = [], 0
    for trade in rows:
        meta = _meta(trade)
        if meta.get("entry_working"):
            continue
        if _world(trade) == "demo":
            demo += 1
            continue
        since = _entry_at(trade) or trade.opened_at
        vanished_since = False
        vanished = _parse(meta.get("protection_vanished_at"))
        if vanished is not None and (since is None or vanished > since):
            since, vanished_since = vanished, True
        sent, held = _held_stop(meta)
        if (_bare(meta) and since is not None
                and (ctx.now - since).total_seconds() > NO_STOP_AFTER_S):
            age = eye.ago(since, ctx.now)
            facts = [(f"Without a stop since {eye.when(since)} ({age})"
                      if vanished_since else
                      f"Live since {eye.when(since)} ({age})"),
                     f"Stop the bot keeps: {eye.price(trade.stop_loss)}"]
            if _no_venue_stop(meta):
                facts.append(f"eToro holds no stop: sent {eye.price(sent)}")
            facts.append("No stop rests at the broker: the bot manages the "
                         "exit, and a stopped bot protects nothing")
            why = eye.plain_detail(meta.get("protection_vanished_reason")
                                   or meta.get("protection_note") or "")
            if why:
                facts.append(f"Broker note: {why}")
            out.append(g.finding(f"trade:{trade.pk}",
                                 label=_trade_label(trade), facts=facts,
                                 user=trade.config.user))
        if held is not None and held > NO_STOP_SENTINEL:
            entry = _float(trade.entry_price)
            if sent and entry:
                farther = held < sent if trade.side == "BUY" else held > sent
                if farther:
                    facts = [f"Stop sent: {eye.price(sent)}",
                             f"Stop the broker holds: {eye.price(held)}"]
                    budget, actual = abs(entry - sent), abs(entry - held)
                    if budget > 0:
                        facts.append(f"The loss at the stop is "
                                     f"{actual / budget:.1f} times the risk "
                                     f"budgeted")
                    out.append(g.finding(
                        f"trade:{trade.pk}:stop", severity="warning",
                        title="Morgul — the broker moved a stop farther away",
                        label=_trade_label(trade), facts=facts,
                        user=trade.config.user))
    if demo:
        ctx.note(g, f"{_plural(demo, 'demo position')} not judged: the "
                 "demo world is virtual money")
    return out


# ── G3: a close stuck at the broker ──────────────────────────────────────

def check_stuck_close(ctx, g) -> list:
    """A CLOSE_PENDING row. The row carries no "pending since", so the
    age is the oldest of: the close_sent_at stamp (measured), the last
    retry and the retries counted at five minutes each, and when this
    guard first saw it (its memory) -- all but the first only bound it,
    and the words say "at least". Critical from STUCK_CRIT_S, except while
    the instrument's market is shut (_shut, the paper venue's clock): a
    close can only fill at the open (an eToro close off hours is queued,
    status PENDING), so it stays a warning and says so. Whether the broker
    still holds the position is not read here, and not said (a row the
    retry found flat but could not price waits CLOSE_PENDING too)."""
    from bot_program.asset_models import AssetBotTrade
    from core.exchange_status import market_status_for
    rows = list(AssetBotTrade.objects.filter(status="CLOSE_PENDING")
                .select_related("config", "config__user").order_by("pk"))
    seen = ctx.since(g.key, [f"trade:{t.pk}" for t in rows])
    out = []
    for trade in rows:
        meta = _meta(trade)
        try:
            attempts = int(meta.get("close_retry_attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        sent = _parse(meta.get("close_sent_at"))
        marks = [seen[f"trade:{trade.pk}"]]
        for at in (sent, _parse(meta.get("close_retry_last_at"))):
            if at is not None:
                marks.append(at)
        if attempts > 0:
            marks.append(ctx.now - timedelta(seconds=attempts * RETRY_EVERY_S))
        since = min(marks)
        age = (ctx.now - since).total_seconds()
        if age < STUCK_WARN_S:
            continue
        ago = eye.ago(since, ctx.now)
        facts = [(f"Close sent {eye.when(since)} ({ago})"
                  if sent is not None and since == sent else
                  f"Close pending at least since {eye.when(since)} ({ago})"),
                 f"Retries: {attempts}"]
        err = eye.plain_detail(meta.get("close_retry_last_error") or "")
        if err:
            facts.append(f"Last error: {err}")
        severity = "critical" if age >= STUCK_CRIT_S else "warning"
        cls, exchange, _pk = ctx.instrument(trade.symbol, trade.asset_class)
        if (severity == "critical" and cls in CLOCK_CLASSES
                and _shut(cls, exchange, trade.symbol, ctx.now)):
            status = market_status_for(cls, exchange, now_utc=ctx.now,
                                       symbol=trade.symbol)
            severity = "warning"
            facts.append("Market shut now: "
                         f"{status.get('name') or status.get('session')}"
                         "; a close can only fill when it opens")
        out.append(g.finding(
            f"trade:{trade.pk}", label=_trade_label(trade), facts=facts,
            severity=severity, user=trade.config.user))
    return out


# ── G4: a price far from the market ──────────────────────────────────────

def check_price_sanity(ctx, g) -> list:
    """Every booked entry and exit of the last 24 h against the nearest
    1h or 4h bar close (market_data.PriceData) within an hour of it. No
    bar, no judgement -- counted in the notes."""
    from market_data.models import PriceData
    since, rows = _recent_rows(ctx)
    out, unjudged, no_bar = [], Counter(), 0
    window = timedelta(seconds=BAR_WINDOW_S)
    for trade in rows:
        cls, _exchange, inst = ctx.instrument(trade.symbol, trade.asset_class)
        limit = PRICE_LIMITS.get(cls)
        if limit is None:
            unjudged[cls or "unknown"] += 1
            continue
        facts = []
        for what, at, px in _bookings(trade, since):
            booked = _float(px)
            bars = [] if inst is None else list(
                PriceData.objects.filter(
                    instrument_id=inst, timeframe__in=("1h", "4h"),
                    timestamp__gte=at - window, timestamp__lte=at + window)
                .values_list("timeframe", "timestamp", "close"))
            if booked is None or not bars:
                no_bar += 1
                continue
            tf, stamp, close = min(bars, key=lambda b: (
                abs((b[1] - at).total_seconds()), b[0] != "1h"))
            close = _float(close)
            if not close:
                no_bar += 1
                continue
            gap = abs(booked - close) / close
            if gap > limit:
                facts.append(f"{what} {eye.when(at)} at {eye.price(booked)}")
                facts.append(f"The {TIMEFRAME_WORDS.get(tf, tf)} bar of "
                             f"{eye.when(stamp)} closed at "
                             f"{eye.price(close)}: "
                             f"{eye.percent(gap * 100)} away")
                facts.append(f"The limit for {_class_word(cls)} is "
                             f"{eye.percent(limit * 100)}")
        if facts:
            out.append(g.finding(f"trade:{trade.pk}",
                                 label=_trade_label(trade), facts=facts,
                                 event=True, user=trade.config.user))
    if no_bar:
        ctx.note(g, f"{_plural(no_bar, 'booking')} with no one-hour or "
                 "four-hour bar within an hour: not judged")
    if unjudged:
        ctx.note(g, "no price limit for " + ", ".join(
            f"{_class_word(c)} ({n})" for c, n in sorted(unjudged.items())))
    return out


# ── G5: a live eToro position past its proof or ceiling ──────────────────

def check_proofs(ctx, g) -> list:
    """A live row eToro carried (metadata broker "etoro"), open or opened
    in the last 24 h, whose instrument class -- or, for a SELL, its short
    -- is not proven (base.missing_proofs), whose recorded multiplier is above
    base.ORDER_LEVERAGE_CEILING for its class, or, for a multiplier the
    attack mode picked, above base.proven_leverage (the proven multiplier
    binds the attack mode only; a typed one answers to the ceiling)."""
    from django.db.models import Q
    from bot_program.asset_engine import base
    from bot_program.asset_models import AssetBotTrade
    ceilings = dict(getattr(base, "ORDER_LEVERAGE_CEILING", {}) or {})
    proven_at = getattr(base, "proven_leverage", None)
    since = ctx.now - timedelta(hours=WINDOW_H)
    rows = (AssetBotTrade.objects.filter(paper=False,
                                         status__in=BOOKED_STATUSES)
            .filter(Q(status__in=OPEN_STATUSES) | Q(opened_at__gte=since))
            .select_related("config", "config__user").order_by("pk"))
    out = []
    for trade in rows:
        meta = _meta(trade)
        if meta.get("broker") != "etoro":
            continue
        cls, _exchange, _pk = ctx.instrument(trade.symbol, trade.asset_class)
        missing = base.missing_proofs(cls, trade.side)
        facts = []
        if missing:
            facts.append("No fill-and-close proof pinned for: " + ", ".join(
                eye.proof_word(m) for m in missing))
        lev = _leverage(meta)
        try:
            ceiling = int(ceilings.get(cls, 1))
        except (TypeError, ValueError):
            ceiling = 1
        if lev > ceiling:
            facts.append(f"Multiplier {lev}x is above the "
                         f"{_class_word(cls)} ceiling of {ceiling}x")
        if isinstance(meta.get("attack"), dict) and callable(proven_at):
            best = proven_at(cls)
            if lev > best:
                facts.append(f"The attack mode picked {lev}x, above the "
                             f"{best}x proven for {_class_word(cls)}")
        if facts:
            out.append(g.finding(
                f"trade:{trade.pk}", label=_trade_label(trade), facts=facts,
                event=trade.status not in OPEN_STATUSES,
                user=trade.config.user, configs=[trade.config_id]))
    return out


# ── G6: the margin ───────────────────────────────────────────────────────

def check_margin(ctx, g) -> list:
    """The eToro sync's cells (last_used_margin, last_equity, their age
    last_margin_at and world last_margin_world): pledged past
    MAX_PLEDGED_FRACTION + MARGIN_SLACK is critical -- and may brake every
    enabled live config of the user -- only on cells the gate itself would
    trust: at most MARGIN_STALE_S old, read in the account's own world, of
    an account a running live bot routes to. Otherwise the same numbers
    are a warning that says why it does not brake. Cells older than an
    hour while a live eToro bot runs, or read in the other world, are
    warnings of their own."""
    from bot_program.asset_engine import base
    from bot_program.models import EtoroAccount
    fraction = float(base.pledged_ceiling())
    alarm = fraction + MARGIN_SLACK
    out = []
    for acct in (EtoroAccount.objects.exclude(api_key_enc="")
                 .select_related("user").order_by("pk")):
        world = "demo" if acct.demo else "live"
        label = f"eToro {world} account ({acct.label})"
        running = _live_configs(acct.user)
        routed = [c for c in running if acct.is_primary_for(c.asset_class)]
        at, code = acct.last_margin_at, acct.last_equity_currency
        stamped = str(acct.last_margin_world or "")
        used, equity = _float(acct.last_used_margin), _float(acct.last_equity)
        if used is not None and equity is not None:
            ratio = used / equity if equity > 0 else None
            if ratio is None or ratio > alarm:
                facts = [f"Used margin: {eye.money(used, code)}",
                         f"Equity: {eye.money(equity, code)}",
                         ("Pledged: all of it, the equity is not above zero"
                          if ratio is None else
                          f"Pledged: {eye.percent(ratio * 100)} of equity; "
                          f"the limit is {eye.percent(fraction * 100)}, the "
                          f"alarm {eye.percent(alarm * 100)}"),
                         f"Read: {eye.ago(at, ctx.now)}"]
                doubts = []
                if at is None or (ctx.now - at).total_seconds() > MARGIN_STALE_S:
                    doubts.append(f"read {eye.ago(at, ctx.now)}" if at
                                  else "no reading time recorded")
                if stamped != world:
                    doubts.append(f"read in the {stamped} world while the "
                                  f"account is now {world}" if stamped
                                  else "no world recorded")
                if not routed:
                    doubts.append("no running live bot routes here")
                if doubts:
                    facts.append("A warning only, and no brake: "
                                 + "; ".join(doubts))
                out.append(g.finding(
                    f"account:{acct.pk}:pledged", label=label, facts=facts,
                    severity="warning" if doubts else None, user=acct.user,
                    configs=[] if doubts else [c.pk for c in running]))
        elif routed:
            ctx.note(g, f"{label}: no margin cells stored yet")
        if routed and (at is None
                       or (ctx.now - at).total_seconds() > MARGIN_STALE_S):
            out.append(g.finding(
                f"account:{acct.pk}:stale", severity="warning",
                title="Morgul — the margin reading is stale", label=label,
                facts=[f"Margin read: {eye.ago(at, ctx.now)}"
                       if at else "Margin read: never",
                       f"Live bots routed here: {len(routed)}",
                       "The broker sync writes it every 15 minutes; check "
                       "that the sync runs"],
                user=acct.user))
        if at is not None and stamped != world:
            out.append(g.finding(
                f"account:{acct.pk}:world", severity="warning",
                title="Morgul — the margin was read in the other world",
                label=label,
                facts=[f"Read in: {stamped or 'no world recorded'}",
                       f"The account is now set to: {world}",
                       "Cells from one world must not judge orders in the "
                       "other; the next sync rewrites them"],
                user=acct.user))
    return out


# ── G7: the daily loss ───────────────────────────────────────────────────

def _book_daily_pct():
    """MAX DAILY LOSS off the /setup/ limits book, or None when it carries
    none (or cannot be read: then the bots' own percentages, as before)."""
    try:
        from portfolio.risk_gate import _limit_pct, limits_book
        return _limit_pct(limits_book(), "max_daily_loss_pct")
    except Exception as e:  # noqa: BLE001 — a guard must not raise
        logger.warning("[morgul] the book's daily-loss limit is unreadable "
                       "(%s) — the bots' own percentages apply", e)
        return None


def check_daily_loss(ctx, g) -> list:
    """Realized LIVE P&L of the last 24 h, per user and currency, against
    the daily stop the configs carry: the SMALLEST max_daily_loss_pct of
    the live configs concerned (every config with a live close in the
    window, and every enabled live config) that carry one -- a config set
    never to halt on drawdown (halt_on_drawdown False, which the engine's
    own gate honours) or at 0% is left out of the number, and said -- on
    their combined capital, and the number is said. At or past it, as the
    engine's gate (base.py: realized <= limit). Paper and demo are never
    counted, never netted; an unpriced close is counted apart, never as
    zero. The unit is the bots' base currency, the one the engine's gate
    and the row's pnl use (asset_models: "in the config's base_currency");
    when the user's eToro account reads another, nothing converts, and the
    message says so."""
    from bot_program.asset_models import AssetBotTrade
    from bot_program.models import EtoroAccount
    since = ctx.now - timedelta(hours=WINDOW_H)
    closes = (AssetBotTrade.objects.filter(paper=False, status="CLOSED",
                                           closed_at__gte=since)
              .select_related("config", "config__user").order_by("pk"))
    by_user, demo = OrderedDict(), 0
    for trade in closes:
        if _world(trade) == "demo":
            demo += 1
            continue
        by_user.setdefault(trade.config.user_id, []).append(trade)
    if demo:
        ctx.note(g, f"{_plural(demo, 'demo close')} not counted: the demo "
                 "world is virtual money")
    out = []
    for rows in by_user.values():
        user = rows[0].config.user
        running = _live_configs(user)
        configs = {c.pk: c for c in running}
        for trade in rows:
            configs.setdefault(trade.config_id, trade.config)
        acct = (EtoroAccount.objects.filter(user=user)
                .exclude(api_key_enc="").first())
        by_ccy = OrderedDict()
        for cfg in sorted(configs.values(), key=lambda c: c.pk):
            by_ccy.setdefault((cfg.base_currency or "").upper(), []).append(cfg)
        for ccy, cfgs in by_ccy.items():
            pks = {c.pk for c in cfgs}
            mine = [t for t in rows if t.config_id in pks]
            if not mine:
                continue
            label = (f"Live bots of account #{user.pk} · "
                     f"{ccy or 'no currency'}")
            # ONE DAILY STOP (2026-10-01): the book's MAX DAILY LOSS when
            # it carries one, for every live bot — the number the engine's
            # gate now stops on. The bots' own percentages only without it.
            book_pct = _book_daily_pct()
            carriers = ([c for c in cfgs] if book_pct is not None else
                        [c for c in cfgs if c.halt_on_drawdown
                         and float(c.max_daily_loss_pct or 0) > 0])
            if not carriers:
                ctx.note(g, f"{label}: no bot carries a daily stop (each is "
                         "set never to halt on drawdown, or at 0%); not "
                         "judged")
                continue
            priced = [t.pnl for t in mine if t.pnl is not None]
            realized = sum((float(p) for p in priced), 0.0)
            unpriced = len(mine) - len(priced)
            pct = (book_pct if book_pct is not None else
                   min(float(c.max_daily_loss_pct) for c in carriers))
            # The followers of one shared account are ONE pool: summed,
            # the stop would be a multiple of the account it guards.
            from bot_program.capital_truth import combined_capital
            capital = combined_capital(cfgs)
            stop = capital * pct / 100.0
            if stop <= 0:
                ctx.note(g, f"{label}: no capital to measure a daily stop "
                         "against; not judged")
                continue
            if realized > -stop:
                continue
            facts = [f"Realized live P&L, last 24 h: "
                     f"{eye.money(realized, ccy)} over "
                     f"{_plural(len(mine), 'close')} (paper and demo excluded)",
                     f"Daily stop used: {eye.percent(pct)} of "
                     f"{eye.money(capital, ccy)} = {eye.money(stop, ccy)}"]
            if book_pct is not None:
                from portfolio.risk_gate import (ABSOLUTE_STOP_MULTIPLE,
                                                 ELITE_MAX_PER_WINDOW,
                                                 ELITE_SIZE_SCALE)
                hard = stop * ABSOLUTE_STOP_MULTIPLE
                facts.append("That is MAX DAILY LOSS on /setup/, the one "
                             "daily stop of every live bot")
                if realized > -hard:
                    facts.append(
                        f"Elite entries only until the absolute stop at "
                        f"{eye.percent(pct * ABSOLUTE_STOP_MULTIPLE)} = "
                        f"{eye.money(hard, ccy)}: a measured edge, at "
                        f"{ELITE_SIZE_SCALE:g}x size, at most "
                        f"{ELITE_MAX_PER_WINDOW} in 24 h")
                else:
                    facts.append(
                        f"Past the absolute stop at "
                        f"{eye.percent(pct * ABSOLUTE_STOP_MULTIPLE)} = "
                        f"{eye.money(hard, ccy)}: nothing opens, elite "
                        f"entries included")
                facts.append("No bot is switched off: exits and stops keep "
                             "running")
            left = [f"{eye.config_label(c)} ("
                    + ("never halts on drawdown" if not c.halt_on_drawdown
                       else "a daily stop of 0%") + ")"
                    for c in cfgs if c not in carriers]
            if book_pct is None and left:
                facts.append(f"That is the smallest daily stop of the "
                             f"{_plural(len(carriers), 'live bot')} that "
                             f"carry one, on the combined capital of all "
                             f"{len(cfgs)}")
                facts.append("Left out of that number: " + ", ".join(left))
            elif book_pct is None:
                facts.append(f"That is the smallest daily stop of the "
                             f"{_plural(len(cfgs), 'live bot')}, on their "
                             f"combined capital")
            if unpriced:
                facts.append(f"Closes without a price: {unpriced} (not "
                             f"counted as zero)")
            read = str(getattr(acct, "last_equity_currency", "") or "").upper()
            if (acct is not None and read and ccy and read != ccy
                    and any(acct.is_primary_for(c.asset_class)
                            for c in cfgs)):
                facts.append(f"Counted in {ccy}, the bots' base currency, "
                             f"as the engine's daily gate counts it; the "
                             f"eToro account reads {read} and nothing "
                             f"converts")
            # The label names the account by number: a username is typed
            # by a person and may read like code on the group's screen.
            out.append(g.finding(
                f"user:{user.pk}:{ccy or 'none'}", label=label,
                facts=facts, user=user, configs=[c.pk for c in running]))
    return out


# ── G8: duplicates ───────────────────────────────────────────────────────

def check_duplicates(ctx, g) -> list:
    """More than one OPEN row at a broker (live or demo, said) on one
    config, symbol and side."""
    from bot_program.asset_models import AssetBotTrade
    groups = OrderedDict()
    for trade in (AssetBotTrade.objects.filter(paper=False, status="OPEN")
                  .select_related("config", "config__user").order_by("pk")):
        key = (trade.config_id, str(trade.symbol).upper(), trade.side,
               _world(trade))
        groups.setdefault(key, []).append(trade)
    out = []
    for (cfg_pk, symbol, side, world), rows in groups.items():
        if len(rows) < 2:
            continue
        first = rows[0]
        side_words = eye.SIDE_WORDS.get(side, str(side).lower())
        subject = f"config:{cfg_pk}:{symbol}:{side}" + (
            f":{world}" if world != "live" else "")
        out.append(g.finding(
            subject,
            label=(f"{symbol} {side_words} · {world} · "
                   f"{eye.config_label(first.config)}"),
            facts=[f"Open {world} rows: {len(rows)} ("
                   + ", ".join(f"#{t.pk}" for t in rows) + ")",
                   "One config should hold one position per symbol and "
                   "side; check the broker for a second order"],
            user=first.config.user))
    return out


# ── G9: drift between the book and the broker ────────────────────────────

def check_drift(ctx, g) -> list:
    """The holdings the eToro sync STORED (EtoroAccount.broker_positions,
    broker_positions_at) against the open live rows eToro carried in the
    LIVE world. No broker is asked. Not judged, and said so: a demo
    account (virtual money: its proof positions belong to no row), no
    snapshot, one older than an hour, or one the sync read in the other
    world (its margin cells, stamped at the same moment, say which) -- and
    what the guard said before about that account stays open
    (Context.blind). The sync's fresh client cannot name a position
    ("ETORO:<id>"), so a book with an unnamed position is compared by
    COUNT; a fully named one by symbol. A row younger than DRIFT_AFTER_S
    at the snapshot may not be listed yet, a row closed that recently may
    still be. Either way round -- a row the broker does not hold, or a
    position no row claims -- a disagreement is said only once it has
    stood DRIFT_AFTER_S (the guard's memory): a stop filled at the broker
    is booked by the reconcile, which may run after the sync reads."""
    from bot_program.asset_models import AssetBotTrade
    from bot_program.models import EtoroAccount
    lag = timedelta(seconds=DRIFT_AFTER_S)
    candidates, keep = [], set()
    for acct in (EtoroAccount.objects.exclude(api_key_enc="")
                 .select_related("user").order_by("pk")):
        label = f"eToro {'demo' if acct.demo else 'live'} account ({acct.label})"
        held, at = acct.broker_positions, acct.broker_positions_at
        if acct.demo:
            if isinstance(held, list) and held:
                ctx.note(g, f"{label}: the demo world is virtual money; its "
                         f"{_plural(len(held), 'position')} not judged")
            continue
        rows = []
        for trade in (AssetBotTrade.objects
                      .filter(config__user=acct.user, paper=False,
                              status__in=OPEN_STATUSES)
                      .select_related("config", "config__user")
                      .order_by("pk")):
            meta = _meta(trade)
            if (meta.get("broker") == "etoro" and not meta.get("entry_working")
                    and meta.get("broker_env") == "live"):
                rows.append(trade)
        subjects = ({f"trade:{t.pk}" for t in rows}
                    | {f"account:{acct.pk}:missing",
                       f"account:{acct.pk}:unclaimed"})
        why = ""
        if at is None or not isinstance(held, list):
            why = "no holdings snapshot stored"
        elif (ctx.now - at).total_seconds() > SNAPSHOT_STALE_S:
            why = f"the holdings snapshot was taken {eye.ago(at, ctx.now)}"
        elif (acct.last_margin_at == at and acct.last_margin_world
              and acct.last_margin_world != "live"):
            why = ("the holdings snapshot was read in the "
                   f"{acct.last_margin_world} world")
        if why:
            if rows or held:
                ctx.note(g, f"{label}: {why}; not judged")
            ctx.blind(g, subjects)
            keep |= subjects
            continue
        names = [str((p or {}).get("symbol") or "").upper()
                 for p in held if isinstance(p, dict)]
        unnamed = [n for n in names if not n or n.startswith("ETORO:")]
        claim = [t for t in rows if (_entry_at(t) or t.opened_at) <= at]
        settled = [t for t in claim if (_entry_at(t) or t.opened_at) <= at - lag]
        recent = 0
        for trade in (AssetBotTrade.objects
                      .filter(config__user=acct.user, paper=False,
                              status="CLOSED", closed_at__gt=at - lag,
                              closed_at__lte=at)):
            meta = _meta(trade)
            if meta.get("broker") == "etoro" and meta.get("broker_env") == "live":
                recent += 1
        synced = f"Synced: {eye.ago(at, ctx.now)}"
        if not unnamed:
            left = Counter(names)
            for trade in settled:
                sym = str(trade.symbol).upper()
                if left[sym] > 0:
                    left[sym] -= 1
                    continue
                candidates.append((
                    f"trade:{trade.pk}", _trade_label(trade),
                    [f"Not in the holdings eToro reported ({synced})",
                     "The platform counts it open; the broker may have "
                     "closed it"], acct.user))
        elif len(settled) > len(names):
            candidates.append((
                f"account:{acct.pk}:missing", label,
                [f"Held at eToro: {len(names)} ({synced})",
                 f"Open live rows booked before that: {len(settled)} ("
                 + ", ".join(f"{t.symbol} #{t.pk}" for t in settled) + ")",
                 "The platform counts more positions than the broker "
                 "holds"], acct.user))
        extra = len(names) - len(claim) - recent
        if extra > 0:
            claimed = Counter(str(t.symbol).upper() for t in claim)
            shown = []
            for name in names:
                if claimed[name] > 0:
                    claimed[name] -= 1
                else:
                    shown.append(name or "unnamed")
            candidates.append((
                f"account:{acct.pk}:unclaimed", label,
                [f"Held at eToro: {len(names)} ({synced})",
                 f"Open live rows that claim them: {len(claim)}",
                 "Not claimed: " + ", ".join(shown[:6])
                 + (f", +{len(shown) - 6} more" if len(shown) > 6 else ""),
                 "No gate counts them and no bot protects them; check the "
                 "broker"], acct.user))
    seen = ctx.since(g.key, [c[0] for c in candidates], keep=keep)
    out = []
    for subject, label, facts, user in candidates:
        first = seen[subject]
        if (ctx.now - first).total_seconds() < DRIFT_AFTER_S:
            ctx.note(g, f"{label}: the book and the broker disagree, seen "
                     f"{eye.ago(first, ctx.now)}; said after "
                     f"{DRIFT_AFTER_S // 60} min")
            continue
        out.append(g.finding(subject, label=label,
                             facts=facts + [f"Seen since: {eye.when(first)}"],
                             user=user))
    return out


# ── G10: the heartbeat ───────────────────────────────────────────────────

def _last_sign(cfg):
    """The latest sign of life of a config: its tick stamp (safety
    .write_heartbeat, extras["last_tick_at"]) or its row's updated_at,
    which the engine's own writes move and which an operator's edit (a
    config just enabled) moves too."""
    tick = _parse((cfg.extras or {}).get("last_tick_at")
                  if isinstance(cfg.extras, dict) else None)
    marks = [m for m in (tick, cfg.updated_at) if m is not None]
    return max(marks) if marks else None, tick


def _feed_word(source) -> str:
    """A LiveQuote source in words: its declared label
    (market_data/feeds.py), else the key with spaces."""
    try:
        from market_data.feeds import FEEDS
        labels = {f["key"]: f["label"] for f in FEEDS}
    except Exception:  # noqa: BLE001 (a label is never worth a failure)
        labels = {}
    key = str(source or "")
    return labels.get(key) or key.replace("_", " ") or "no source recorded"


def check_heartbeat(ctx, g) -> list:
    """While any live config is enabled: the bot tick (the
    pipeline_asset_bots row, and each live config's own tick stamp) has
    moved in the last TICK_STALE_S; and for each live config class whose
    market has been open FEED_OPEN_FOR_S, the freshest LiveQuote mark of
    the live bots' own symbols in that class is at most MARK_STALE_S old
    -- per class, on the bots' symbols, so a feed fresh for one class
    never hides a dead one for another. Those are the bars and marks the
    bots decide on; an eToro order is priced by eToro's own rates. A
    market shut (or open less than FEED_OPEN_FOR_S) is not judged, and
    what was said before stays open; a class with no symbols or no mark
    stored is not judged, and said so."""
    from bot_program.asset_models import AssetBotConfig
    from core.exchange_status import market_status_for
    from core.platform_control import get_component, is_component_enabled
    from market_data.models import LiveQuote
    live = list(AssetBotConfig.objects.filter(enabled=True, mode="live")
                .select_related("user").order_by("pk"))
    if not live:
        return []
    out = []
    facts = []
    if not is_component_enabled("platform_master"):
        facts.append("The platform master switch is off: no bot ticks")
    comp = get_component("pipeline_asset_bots")
    if comp is None or not comp.is_enabled:
        facts.append("The bot tick is switched off")
    elif (comp.last_run_at is None or (ctx.now - comp.last_run_at)
            .total_seconds() > TICK_STALE_S):
        facts.append("The bot tick last ran "
                     + (eye.ago(comp.last_run_at, ctx.now)
                        if comp.last_run_at else "never"))
    for cfg in live:
        sign, tick = _last_sign(cfg)
        if sign is None or (ctx.now - sign).total_seconds() > TICK_STALE_S:
            facts.append(f"{eye.config_label(cfg)}: last tick "
                         + (eye.ago(tick, ctx.now) if tick else "never"))
    if facts:
        facts.append("While the tick is down, no bot manages its "
                     "positions; broker stops still hold")
        out.append(g.finding("tick", label=f"Live bots running: {len(live)}",
                             facts=facts))
    by_cls = OrderedDict()
    for cfg in live:
        by_cls.setdefault(str(cfg.asset_class or ""), []).append(cfg)
    for cls in sorted(by_cls):
        subject = f"feeds:{cls}"
        if cls != "crypto" and cls not in CLOCK_CLASSES:
            ctx.note(g, f"{_class_word(cls)}: the market clock does not "
                     "model it; its marks are not judged")
            continue
        opened = market_status_for(cls, "", now_utc=ctx.now)
        earlier = market_status_for(
            cls, "", now_utc=ctx.now - timedelta(seconds=FEED_OPEN_FOR_S))
        if not (opened.get("is_open") and earlier.get("is_open")):
            ctx.blind(g, [subject])
            continue
        symbols = sorted({str(s).strip().upper() for c in by_cls[cls]
                          for s in (c.symbols or [])
                          if isinstance(s, str) and s.strip()})
        if not symbols:
            ctx.note(g, f"{_class_word(cls)}: the live bots list no symbol; "
                     "their marks are not judged")
            continue
        marks = list(LiveQuote.objects
                     .filter(instrument__symbol__in=symbols)
                     .values_list("instrument__symbol", "updated_at",
                                  "source"))
        if not marks:
            ctx.note(g, f"{_class_word(cls)}: no mark stored for the live "
                     f"bots' {_plural(len(symbols), 'symbol')}; not judged")
            continue
        sym, at, source = max(marks, key=lambda m: m[1])
        if (ctx.now - at).total_seconds() <= MARK_STALE_S:
            continue
        out.append(g.finding(
            subject, title="Morgul — no fresh quotes for a live market",
            label=f"{_class_word(cls)} · market open",
            facts=[f"Freshest mark of the live bots' "
                   f"{_plural(len(symbols), 'symbol')}: {sym}, "
                   f"{eye.ago(at, ctx.now)} ({_feed_word(source)})",
                   f"Market: {opened.get('name') or opened.get('session')}, "
                   f"open",
                   "The bars and marks the bots decide on are stale while "
                   "the market trades; an eToro order is priced by eToro"]))
    return out


GUARDS = [
    Guard("market_shut", "Market-shut booking", "critical",
          "Morgul — a booking while the market was shut", check_market_shut,
          brake=True),
    Guard("no_stop", "Live without a stop", "critical",
          "Morgul — a live position without a stop at the broker",
          check_no_stop),
    Guard("stuck_close", "Stuck close", "warning",
          "Morgul — a close stuck at the broker", check_stuck_close),
    Guard("price_sanity", "Price sanity", "warning",
          "Morgul — a price far from the market", check_price_sanity),
    Guard("proofs", "Proofs and ceilings", "critical",
          "Morgul — a live position past its proof or ceiling",
          check_proofs, brake=True),
    Guard("margin", "Margin", "critical",
          "Morgul — the margin pledged is past the limit", check_margin,
          brake=True),
    # Never a brake (2026-10-01): past the daily stop the engine's gate
    # lets only elite entries through and stops at the absolute stop by
    # itself; switching the bots off would stop their exits too.
    Guard("daily_loss", "Daily loss", "critical",
          "Morgul — the daily loss is past the stop", check_daily_loss),
    Guard("duplicates", "Duplicates", "warning",
          "Morgul — duplicate live positions", check_duplicates),
    Guard("drift", "Drift", "critical",
          "Morgul — the platform and the broker disagree", check_drift),
    Guard("heartbeat", "Heartbeat", "critical",
          "Morgul — the bot tick has stopped", check_heartbeat),
]
GUARD = {g.key: g for g in GUARDS}


# ── one run ──────────────────────────────────────────────────────────────

class Report:
    """What one run found, what it noted, and (sent) what it did."""

    def __init__(self, ctx, guards, findings, failed, result, messages,
                 outcomes):
        self.ctx = ctx
        self.guards = guards
        self.findings = findings
        self.failed = failed
        self.result = result
        self.messages = messages
        self.outcomes = outcomes


def collect(*, now=None, persist=False, guards=None) -> tuple:
    """(context, findings, failed guard keys): every guard once, each in
    its own savepoint and its own try. A guard that raises is a finding."""
    from django.db import transaction
    from django.utils import timezone
    ctx = Context(now or timezone.now(), persist)
    findings, failed = [], []
    for guard in (GUARDS if guards is None else guards):
        try:
            with transaction.atomic():
                got = list(guard.check(ctx, guard) or [])
        except Exception as e:  # noqa: BLE001 (a guard that fails is said)
            name = type(e).__name__
            logger.warning("[morgul] guard %s could not run (%s)", guard.key,
                           name, exc_info=True)
            failed.append(guard.key)
            got = [Finding(guard, "error", title=GUARD_FAILED,
                           label=guard.name, severity="warning",
                           facts=[f"Guard {guard.name.lower()} could not "
                                  f"run: {name}",
                                  "Until it runs, nothing watches what it "
                                  "watches"])]
        findings.extend(got)
    return ctx, findings, failed


def _load(key) -> dict:
    from django.core.cache import cache
    try:
        value = cache.get(key)
    except Exception:  # noqa: BLE001 (a cache down forgets: said twice)
        logger.warning("[morgul] the cache could not be read")
        return {}
    return value if isinstance(value, dict) else {}


def _store(key, value) -> None:
    from django.core.cache import cache
    try:
        cache.set(key, value, STATE_TTL_S)
    except Exception:  # noqa: BLE001
        logger.warning("[morgul] the cache could not be written")


def _configs(pks) -> list:
    from bot_program.asset_models import AssetBotConfig
    by_pk = {c.pk: c for c in AssetBotConfig.objects.filter(pk__in=list(pks))}
    return [by_pk[pk] for pk in pks if pk in by_pk]


def would_stop(finding) -> list:
    """The labels of the configs the brake would turn off: those running."""
    return [eye.config_label(c) for c in _configs(finding.configs)
            if c.enabled]


def _brake_armed() -> bool:
    """The brake acts only while its own switch AND the guards' are on:
    `manage.py morgul --send` with the guards off says what it would
    stop, as the registry row promises."""
    from core.platform_control import is_component_enabled
    return (is_component_enabled(BRAKE_KEY)
            and is_component_enabled(COMPONENT_KEY))


def _brake(finding) -> tuple:
    """THE BRAKE: telegram_eye.apply_brake, the Eye's own write
    (enabled = False on the user's own configs, nothing else). Returns
    (stopped labels, already-off labels, stopped pks). Nothing running,
    nothing to call."""
    before = _configs(finding.configs)
    if not any(c.enabled for c in before):
        return [], [eye.config_label(c) for c in before], []
    reply = eye.apply_brake(finding.user, [c.pk for c in before])
    stopped = set(reply.meta.get("stopped") or [])
    logger.warning("[morgul] BRAKE on %s: configs %s turned off",
                   finding.key, sorted(stopped))
    return ([eye.config_label(c) for c in before if c.pk in stopped],
            [eye.config_label(c) for c in before if c.pk not in stopped],
            sorted(stopped))


def _left_open(pks) -> dict:
    """What the stopped bots leave open, read now: positions at a broker
    (and those with no stop resting there, _bare), and paper positions.
    A working entry is an order, not a position: not counted."""
    from bot_program.asset_models import AssetBotTrade
    left = {"broker": 0, "bare": 0, "paper": 0}
    if not pks:
        return left
    for trade in AssetBotTrade.objects.filter(config_id__in=list(pks),
                                              status__in=OPEN_STATUSES):
        meta = _meta(trade)
        if trade.paper:
            left["paper"] += 1
        elif not meta.get("entry_working"):
            left["broker"] += 1
            left["bare"] += int(_bare(meta))
    return left


def _join(labels) -> str:
    return ", ".join(dict.fromkeys(labels))


def brake_lines(outcomes) -> list:
    """The brake's words for one message, from each finding's outcome:
    ("stopped", stopped, already, left), ("earlier", stopped, [], left),
    ("would", labels), ("held", labels) or ("failed", labels, error
    name); `left` is _left_open's count, optional. "The stops stay at the
    broker" is said only when it is true: a position at the broker with no
    stop there is protected by nothing while its bot is stopped, and a
    paper stop is the bot's own and pauses with it."""
    stopped, already, would, earlier, held, failed = [], [], [], [], [], []
    left = {"broker": 0, "bare": 0, "paper": 0}
    for outcome in outcomes:
        kind = outcome[0]
        if kind in ("stopped", "earlier"):
            (stopped if kind == "stopped" else earlier).extend(outcome[1])
            already += outcome[2] if kind == "stopped" else []
            counts = outcome[3] if len(outcome) > 3 else None
            for k in left:
                left[k] += int((counts or {}).get(k) or 0)
        elif kind == "would":
            would += outcome[1]
        elif kind == "held":
            held += outcome[1]
        elif kind == "failed":
            failed.append((outcome[1], outcome[2]))
    exposed = bool(left["bare"] or left["paper"])
    lines = []
    if stopped:
        lines.append(f"Stopped: {_join(stopped)} — no position was "
                     f"closed; "
                     + ("" if exposed else "the stops stay at the broker; ")
                     + "to re-arm: the server")
    elif already and not would:
        lines.append(f"Nothing to stop: {_join(already)} already off — no "
                     f"position was closed")
    if would:
        lines.append(f"Would stop: {_join(would)} — the brake is off; "
                     f"nothing was stopped")
    elif any(o[0] == "would" for o in outcomes):
        lines.append("Would stop: nothing, those bots are already off")
    if held:
        lines.append(f"Would stop: {_join(held)} — the brake held back: "
                     f"no staff Telegram chat could be told")
    if earlier:
        lines.append(f"Stopped earlier by the brake: {_join(earlier)} — to "
                     f"re-arm: the server")
    if left["bare"]:
        lines.append(f"At the broker without a stop: {left['bare']} — "
                     f"while the bot is stopped, nothing protects them")
    if left["bare"] and left["broker"] > left["bare"]:
        lines.append(f"At the broker with a stop: "
                     f"{left['broker'] - left['bare']} — those stops stay")
    if left["paper"]:
        lines.append(f"Paper positions: {left['paper']} — their stops "
                     f"are simulated by the bot and pause while it is "
                     f"stopped")
    for labels, name in failed:
        lines.append(f"The brake could not stop {_join(labels)} ({name}): "
                     f"stop them on the server")
    return lines


def build_messages(findings, outcomes, now) -> list:
    """One Reply per title, in the guards' order: the severity, each
    subject in bold with its facts, then the brake's words and the time,
    both kept whole by fit (meta keep_tail)."""
    groups = OrderedDict()
    for f in findings:
        groups.setdefault(f.title, []).append(f)
    out = []
    for title, group in groups.items():
        worst = ("critical" if any(f.severity == "critical" for f in group)
                 else "warning")
        lines = [f"Severity: {worst}"]
        for f in group:
            lines.append(eye.heading(f.label))
            lines.extend(f"{eye.BULLET}{fact}" for fact in f.facts)
        tail = brake_lines([outcomes[f.key] for f in group
                            if f.key in outcomes])
        tail.append(f"Checked: {eye.when(now)}")
        out.append(eye.Reply(MARK, title,
                             eye._cap(lines, eye.MAX_LINES - len(tail)) + tail,
                             meta={"keep_tail": len(tail),
                                   "keys": [f.key for f in group]}))
    return out


def back_to_normal(entries, now):
    """One line per finding that stopped; a bot the brake turned off for
    it stays off (the brake never re-arms), and the line says so."""
    lines = [(f"{e.get('name')}: the guard runs again — back to normal"
              if e.get("subject") == "error" else
              f"{e.get('name')}: {e.get('label')} — back to normal")
             + (" (the bots the brake stopped stay off until re-armed on "
                "the server)" if e.get("braked") else "")
             for e in entries]
    return eye.Reply(MARK, BACK_TO_NORMAL,
                     eye._cap(lines, eye.MAX_LINES - 1)
                     + [f"Checked: {eye.when(now)}"], meta={"keep_tail": 1})


def recipients() -> list:
    """One staff user per configured Telegram chat: the chats the Eye
    answers and the fills reach (active staff, notify_channel telegram)."""
    from alerts.models import UserNotificationPrefs
    from bot_program.notifications import _user_channel
    seen, out = set(), []
    for prefs in (UserNotificationPrefs.objects.exclude(telegram_chat_id="")
                  .select_related("user").order_by("user_id")):
        user = prefs.user
        if not (user.is_staff and user.is_active):
            continue
        if _user_channel(user) != "telegram":
            continue
        chat = str(prefs.telegram_chat_id or "").strip()
        if chat and chat not in seen:
            seen.add(chat)
            out.append(user)
    return out


#: What a finding keeps of the brake when its message is taken back.
BRAKE_RECORD = ("braked", "stopped", "stopped_pks")


def _unsaid(cur, prev, keys) -> dict:
    """The memory as if these findings had not been said: each back to
    what the last run stored (a new one due again), the brake's own
    record kept -- so the next run says them, and says the brake."""
    out = dict(cur)
    for key in keys:
        if key not in cur:
            continue
        kept = {k: cur[key][k] for k in BRAKE_RECORD if k in cur[key]}
        out[key] = (dict(prev[key], **kept) if key in prev
                    else dict(cur[key], sent=None))
    return out


def _settle(ctx, findings, failed, result) -> tuple:
    """The sending half: which findings are due (new, escalated, three
    hours since said, or a brake not yet announced), which are back to
    normal (never one a guard could not judge), the brake, the messages,
    the memory. The brake acts on every critical finding of a braking
    guard it has not braked yet, due or not (the three hours are the
    group's, not the brake's), only while armed (_brake_armed) and only
    when a staff chat can be told; its record is stored before anything
    else can fail, and a stop is announced by the first message that
    reaches the group ("Stopped: ..."; a finding not due joins it), then
    reminded ("Stopped earlier by the brake: ...") -- whatever the
    finding's configs read by then."""
    now, stamp = ctx.now, ctx.now.isoformat()
    prev = _load(STATE_KEY)
    cur, due, cleared = {}, [], []
    for f in findings:
        entry = dict(prev.get(f.key) or {})
        last = _parse(entry.get("sent"))
        worse = entry.get("severity") == "warning" and f.severity == "critical"
        unannounced = bool(entry.get("braked")) and not entry.get("announced")
        if (last is None or worse or unannounced
                or (not f.event
                    and (now - last).total_seconds() >= REMIND_S)):
            due.append(f)
            entry["sent"] = stamp
        entry.setdefault("first", stamp)
        entry.update(guard=f.guard.key, name=f.guard.name, label=f.label,
                     subject=f.subject, severity=f.severity, event=f.event)
        cur[f.key] = entry
    blind = set(failed)
    for key, entry in prev.items():
        if key in cur:
            continue
        guard = entry.get("guard")
        if (guard in blind
                or entry.get("subject") in ctx.unjudged.get(guard, ())):
            cur[key] = entry           # a guard that could not look keeps
            continue                   # what it last saw
        if entry.get("sent") and not entry.get("event"):
            cleared.append(entry)
    people = recipients()
    armed = _brake_armed()
    outcomes, braked = {}, False
    said = {f.key for f in due}
    # Every finding of the run, not only those due: a critical finding
    # said while the brake was off is not due again for three hours --
    # never, an event -- and the brake armed since must not wait for it.
    # Its words (would, held, earlier) belong to a message, so they are
    # kept for the findings one carries.
    for f in findings:
        entry, heard = cur[f.key], f.key in said
        if entry.get("braked"):
            if heard:
                outcomes[f.key] = (
                    "earlier" if entry.get("announced") else "stopped",
                    entry.get("stopped") or [], [],
                    _left_open(entry.get("stopped_pks") or []))
            continue
        if not f.brakes:
            continue
        if not armed:
            if heard:
                outcomes[f.key] = ("would", would_stop(f))
            continue
        if not people:
            if heard:
                outcomes[f.key] = ("held", would_stop(f))
                result["held"] = True
            continue
        try:
            stopped, already, pks = _brake(f)
        except Exception as e:  # noqa: BLE001
            logger.warning("[morgul] the brake failed on %s (%s)", f.key,
                           type(e).__name__, exc_info=True)
            outcomes[f.key] = ("failed", would_stop(f), type(e).__name__)
            continue
        entry.update(braked=True, stopped=stopped, stopped_pks=pks)
        braked = True
        result["stopped"].extend(stopped)
        outcomes[f.key] = ("stopped", stopped, already, _left_open(pks))
        if not heard:
            # The brake's record is always announced: the finding joins
            # this run's message ("Stopped: ...", or "Nothing to stop").
            due.append(f)
            entry["sent"] = stamp
    if braked:
        # The brake's record first, as if nothing had been said yet: a run
        # that dies after this line still leaves the next one announcing it
        # (and saying "back to normal" for what stopped).
        early = _unsaid(cur, prev, [f.key for f in due])
        early.update((k, v) for k, v in prev.items() if k not in early)
        _store(STATE_KEY, early)
    messages = build_messages(due, outcomes, now)
    if cleared:
        messages.append(back_to_normal(cleared, now))
    for reply in messages:
        delivered = 0
        for user in people:
            try:
                if eye._send(user, reply):
                    delivered += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("[morgul] a message could not be sent (%s)",
                               type(e).__name__)
        result["sent"] += delivered
        logger.warning("[morgul] %s: %s", reply.title,
                       "no staff Telegram chat" if not people
                       else f"delivered {delivered} of {len(people)}")
        keys = reply.meta.get("keys") or []
        if people and not delivered:
            # Telegram refused or was unreachable: the findings stay DUE
            # and go out on the next run, five minutes on, rather than in
            # three hours. The brake's own record is kept.
            cur = _unsaid(cur, prev, keys)
        elif delivered:
            for key in keys:
                if cur.get(key, {}).get("braked"):
                    cur[key]["announced"] = True
    result["due"] = len(due)
    result["cleared"] = len(cleared)
    if messages and not people:
        result["skipped"] = ("no staff Telegram chat is configured"
                             + ("; the brake held back" if result.get("held")
                                else ""))
    _store(STATE_KEY, cur)
    _store(SUMMARY_KEY, {
        "at": stamp, "guards": result["guards"], "failed": list(failed),
        "findings": [{"guard": f.guard.key, "name": f.guard.name,
                      "severity": f.severity, "label": f.label}
                     for f in findings]})
    return messages, outcomes


def _lock() -> bool:
    """One run at a time (LOCK_KEY, LOCK_S): False when another holds it.
    A cache that cannot answer lets the run go on: a finding said twice is
    better than one never said."""
    from django.core.cache import cache
    try:
        return bool(cache.add(LOCK_KEY, "held", LOCK_S))
    except Exception:  # noqa: BLE001
        logger.warning("[morgul] the lock could not be read; running")
        return True


def _unlock() -> None:
    from django.core.cache import cache
    try:
        cache.delete(LOCK_KEY)
    except Exception:  # noqa: BLE001 (it expires in LOCK_S anyway)
        logger.warning("[morgul] the lock could not be released")


def cycle(*, now=None, send=False, guards=None) -> Report:
    """Every guard once. With send: one run at a time, the dedupe, the
    brake (while armed), the messages and the memory; without: nothing is
    written or sent (the command's read)."""
    from django.utils import timezone
    chosen = GUARDS if guards is None else list(guards)
    if send and not _lock():
        logger.warning("[morgul] another run holds the lock; this one did "
                       "nothing")
        return Report(Context(now or timezone.now()), chosen, [], [],
                      {"status": "success", "guards": len(chosen),
                       "findings": 0, "sent": 0, "stopped": [],
                       "idle": "another Morgul run is in progress"}, [], {})
    try:
        ctx, findings, failed = collect(now=now, persist=send, guards=chosen)
        result = {"status": "success", "guards": len(chosen),
                  "findings": len(findings), "sent": 0, "stopped": []}
        if failed:
            result["failed"] = list(failed)
        messages, outcomes = [], {}
        if send:
            messages, outcomes = _settle(ctx, findings, failed, result)
        return Report(ctx, chosen, findings, failed, result, messages,
                      outcomes)
    finally:
        if send:
            _unlock()


def run_guards(*, now=None) -> dict:
    """The beat's door (tasks.run_morgul_guards). A run that found the
    lock held answers "idle": the component keeps its last verdict."""
    return cycle(now=now, send=True).result


# ── what the platform shows ──────────────────────────────────────────────

def _summary(now):
    summary = _load(SUMMARY_KEY)
    at = _parse(summary.get("at")) if summary else None
    return summary, at


def _finding_names(summary) -> list:
    return list(dict.fromkeys(str(f.get("name") or "")
                              for f in summary.get("findings") or []
                              if isinstance(f, dict)))


def status_line(now=None) -> str:
    """The Eye's /status line: "Guards: all quiet", or the guards with
    findings, from the last run's summary."""
    from django.utils import timezone
    from core.platform_control import is_component_enabled
    now = now or timezone.now()
    if not is_component_enabled(COMPONENT_KEY):
        return "Guards: off"
    summary, at = _summary(now)
    if at is None:
        return "Guards: no run recorded yet"
    stale = ((now - at).total_seconds() > SUMMARY_STALE_S)
    names = _finding_names(summary)
    tail = f" (last ran {eye.ago(at, now)})" if stale else ""
    if not names:
        return f"Guards: all quiet{tail}"
    n = len(summary.get("findings") or [])
    shown = ", ".join(names[:3]) + (f", +{len(names) - 3} more"
                                    if len(names) > 3 else "")
    return f"Guards: {_plural(n, 'finding')} — {shown}{tail}"


def health_row(make) -> dict:
    """The /health/ row, through the page's own _check (`make`)."""
    from django.utils import timezone
    from core.platform_control import is_component_enabled
    now = timezone.now()
    label = "Morgul guards"
    if not is_component_enabled(COMPONENT_KEY):
        # Not a fault: nothing set up yet, as every row with nothing to look
        # at reads (configured=False: the page says NOT SET UP, not
        # DEGRADED, until `component on morgul_guards`).
        return make("morgul", label, "ok",
                    "off — nothing watches the book",
                    "manage.py component on morgul_guards", configured=False)
    summary, at = _summary(now)
    if at is None:
        return make("morgul", label, "warn", "no run recorded yet",
                    "the beat runs them every 5 min; manage.py morgul reads "
                    "them now")
    age = eye.ago(at, now)
    if (now - at).total_seconds() > SUMMARY_STALE_S:
        return make("morgul", label, "warn", f"last ran {age}",
                    "check the worker and the beat")
    found = [f for f in summary.get("findings") or [] if isinstance(f, dict)]
    if not found:
        return make("morgul", label, "ok",
                    f"quiet — {summary.get('guards')} guards, last run {age}")
    state = ("fail" if any(f.get("severity") == "critical" for f in found)
             else "warn")
    names = ", ".join(_finding_names(summary)[:4])
    return make("morgul", label, state,
                f"{_plural(len(found), 'finding')}: {names} (last run {age})",
                "manage.py morgul prints them")


def render_report(report) -> list:
    """The command's lines: every finding with its facts, what the brake
    would do, and the notes (what was not judged)."""
    ctx = report.ctx
    brake_on = _brake_armed()
    lines = [f"Morgul guards · {eye.when(ctx.now)} · "
             f"{_plural(len(report.guards), 'guard')} · "
             f"{_plural(len(report.findings), 'finding')}"]
    for f in report.findings:
        lines.append(f"[{f.severity}] {f.guard.name} · {f.label}")
        lines.extend(f"    {fact}" for fact in f.facts)
        if f.key in report.outcomes:
            lines.extend(f"    {ln}" for ln in
                         brake_lines([report.outcomes[f.key]]))
        elif f.brakes:
            labels = _join(would_stop(f)) or "nothing running"
            lines.append(f"    Brake: {'on' if brake_on else 'off'} — it "
                         f"would stop {labels}")
    if not report.findings:
        lines.append("All quiet.")
    if ctx.notes:
        lines.append("Notes")
        lines.extend(f"    {note}" for note in ctx.notes)
    return lines
