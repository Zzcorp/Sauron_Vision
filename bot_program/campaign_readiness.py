"""CAN THE EVIDENCE CHAIN PRODUCE A GRADED TRACK RECORD? (2026-09-15)

The read side, shared by `manage.py paper_readiness` (which renders it) and
`watch_evidence_chain` (which watches it). One implementation, because a
command and a watchdog that disagreed about whether the chain was cold would
be the worst possible pair: the page would say fine and the alert would never
come, or the reverse, and neither could be trusted again.

    bars -> indicators -> signals -> fills -> outcomes -> the ladder

Every link but one is gated by a `PlatformComponent`, and
`is_component_enabled` returns False for a MISSING ROW. So a link can be cold
in two different ways — switched off, or never seeded — and neither raises,
neither logs, and `guarded_task` simply no-ops. Ninety days later the ladder
reads n=0 and there is nothing to show.

WHY A ONE-OFF CHECK WAS NOT ENOUGH

`paper_readiness` answers the question the moment it is asked. A campaign
that starts green and goes cold on day twelve spends seventy-eight days
producing nothing, and the only thing that would notice is somebody choosing
to run the command again. Nothing on this platform chose to.

That is the same shape as every defect found this week — the funding feed
that wrote nothing, the broker sync that missed eight times, the backtester
that priced an absent bar at zero. A failure with no mouth. So the chain is
now watched on a schedule, and the alert is what a campaign's silence sounds
like.

A LIVE OPERATION IS NOT A BROKEN PAPER CAMPAIGN (2026-11-12)

Two of the checks below ask whether the campaign is PAPER: the five
live-action switches off, one paper bot on. The operator trades real money
by decision and can never meet them, so the watchdog alarmed on his decision
every one to two days, under a title ("The evidence chain is broken") that
was false: every link was ON. The report now says what KIND of campaign the
enabled configs make (`campaign`), keeps the chain's own faults apart from
the two paper checks (`chain_faults`, `campaign_gaps`), and for a live
operation `blockers` holds only what is a fault for it.

Each finding also carries a KEY (Finding.key) that names what is wrong.
Three of the sentences carry a number that moves every morning (a stale
bar's age, the days of bars missing, the count of closed signals with no
result), and a watchdog that remembered sentences would take an unchanged
fault for a new one every day.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

#: The links that turn a signal into gradeable evidence, in order, with the
#: task each component gates. A cold link here does not degrade the campaign
#: — it ends it, quietly.
EVIDENCE_CHAIN = (
    ("pipeline_indicators", "indicators the rules read"),
    ("pipeline_signals", "the engine that writes Signal rows"),
    ("pipeline_asset_bots", "the bots that turn a signal into a fill"),
    ("pipeline_promotion", "the ladder that grades the fills"),
)

#: The live-action switches: what a PAPER campaign wants off, because with
#: one of them on something may change what real money does. They are five
#: different things, and LIVE_ACTION_WORDS says each in its own words: for
#: three of them a person applies, with one the bots obey a plan on every
#: pass, and one applies a de-risking plan by itself. In a live operation
#: (readiness()["campaign"]) they are the operator's decision: listed, said
#: once, never a blocker. Named individually rather than matched on
#: "_mode_live", so a new actuator has to be added here deliberately instead
#: of inheriting an exemption from a naming convention. The name stays: the
#: command and the tests read it.
MUST_BE_OFF = (
    "actuator_mode_live",
    "meta_allocator_mode_live",
    "share_allocator_mode_live",
    "capital_desk_mode_live",
    "share_allocator_auto_derisk",
)

#: What each of them really allows: (its name in words, what it allows).
#: One sentence used to serve all five and was true of one of them. No
#: underscore in any of these words: they are read on a phone, and the key
#: itself goes in the folded record only.
LIVE_ACTION_WORDS = {
    "actuator_mode_live": (
        "the rule actuator's live mode",
        "a superuser may apply a pause or a size cut to a rule; nothing "
        "applies by itself"),
    "meta_allocator_mode_live": (
        "the meta-allocator's live mode",
        "a superuser may apply rule weights, 0.1x to 3x, to future entries"),
    "share_allocator_mode_live": (
        "the share allocator's live mode",
        "a share plan may be applied with the PIN, which re-sizes the pools"),
    "capital_desk_mode_live": (
        "the capital desk's live mode",
        "the bots obey the desk's plan: displaced entries are skipped and "
        "sizes cut"),
    "share_allocator_auto_derisk": (
        "the share allocator's automatic de-risk",
        "a shock plan that only lowers shares applies itself"),
}


def live_action_words(key: str) -> str:
    """A live-action switch in its own words: "the rule actuator's live
    mode (a superuser may apply a pause or a size cut to a rule; nothing
    applies by itself)". The key itself for one with no entry (the tests
    refuse that for a key of MUST_BE_OFF)."""
    name, allows = LIVE_ACTION_WORDS.get(key) or (str(key), "")
    return f"{name} ({allows})" if allows else name


class Finding(str):
    """One finding: the sentence a person reads, and the key that names it.

    A plain str subclass (as notifications.TelegramHeading is), so whatever
    prints, joins, searches or counts the blockers keeps working and only
    the watchdog reads the difference.

    THE KEY SAYS WHAT IS WRONG, NEVER HOW BAD IT IS TODAY. It is built
    where the finding is written, and no age, count or day goes into it:

        ("master",)                       ("beat", task)
        ("link", key, state)              ("no_result",)
        ("no_bars", symbols)              ("bars_stopped", venue, symbols)
        ("no_symbol",)                    ("stuck", rules)
        ("armed", key)                    ("no_paper",)

    `symbols` and `rules` are sorted tuples of names. A stale bar and
    missing days of bars share ONE word, "bars_stopped": the same dead feed
    reads "OPEN and N hours behind" while its market is open and "N days
    missing" once it is shut, and at the watchdog's hour that flips with
    every weekend.
    """

    key: tuple = ()

    def __new__(cls, key, text):
        self = super().__new__(cls, text)
        self.key = tuple(key)
        return self

    def __getnewargs__(self):
        return (self.key, str(self))


#: Ungated by design, and load-bearing. Reported so that nobody looks for a
#: switch that does not exist.
UNGATED = (
    ("signals.tasks_lifecycle.run_signal_lifecycle", 300,
     "stamps MFE/MAE and closes outcomes — the sole writer of realized_r"),
    ("market_data.tasks.refresh_bot_bars_task", 600,
     "writes the 1h/4h bars every other link reads"),
    ("bot_program.tasks.refresh_saxo_sessions", 600,
     "rotates the Saxo OAuth session — its refresh token lives 40 minutes"),
)

#: How many symbols of a config to inspect. The point is to find a cold feed,
#: not to enumerate a universe — one dead symbol in a config is the signal.
SYMBOLS_PER_CONFIG = 8


#: Past this many symbols a list stops being read and starts being skipped.
NAMES_SHOWN = 12


def _names(symbols: list) -> str:
    """A readable symbol list: all of them, or the first few and a count.

    Naming them matters — "8 symbols are stale" sends an operator to a page,
    "LEANHOGS, LIVECATTLE, LUMBER" sends them to a feed. Naming SIXTY-ONE of
    them is how the two findings that mattered got buried.
    """
    shown = sorted(symbols)[:NAMES_SHOWN]
    rest = len(symbols) - len(shown)
    return ", ".join(shown) + (f" and {rest} more" if rest > 0 else "")


def component_state(key: str) -> str:
    """"ON", "off", or "NO ROW" — three states, not two.

    `is_component_enabled` collapses the last two into False, which is the
    right call for a task gate and the wrong one for a report: "off" is a
    decision and "NO ROW" is an omission, and they are fixed differently.
    """
    from core.platform_control import get_component
    row = get_component(key)
    if row is None:
        return "NO ROW"
    return "ON" if row.is_enabled else "off"


def _is_hand_lane(cfg) -> bool:
    """The TAKE TRADE lane of its class: the config NAMED manual
    (manual_trade.manual_config_for), in live mode once it is armed."""
    from bot_program.manual_trade import MANUAL_CONFIG_NAME
    return cfg.name == MANUAL_CONFIG_NAME


def _scans(cfg) -> bool:
    """A bot: it lists symbols, and it is not the hand lane. The lane is an
    enabled config with no symbols; nothing scans it, a person trades it."""
    return bool(cfg.symbols) and not _is_hand_lane(cfg)


def _on_demo_world(cfg, seen: dict) -> bool:
    """True only when EVERY class this live-mode config carries routes to a
    broker row that answers its demo world (eToro's Demo box, Saxo's SIM:
    the row decides the world, not the config — engine/broker_router).
    Such a bot is in live mode and moves no real money.

    Anything else counts as real money, a row that cannot be read
    included: the notice may call a demo bot real, never a real one demo.
    `seen` caches each user's rows for the length of one report.
    """
    try:
        from bot_program.capital_truth import broker_env
        from bot_program.management.commands.preflight_live import (
            _instrument_classes, _venue_for)
        if cfg.user_id not in seen:
            seen[cfg.user_id] = (cfg.user, {})
        owner, venues = seen[cfg.user_id]
        classes = _instrument_classes(cfg)
        for cls in classes:
            if cls not in venues:
                venues[cls] = _venue_for(owner, cls)[0]
            row = venues[cls]
            if row is None or broker_env(row) != "paper":
                return False
        return bool(classes)
    except Exception:  # noqa: BLE001 — unread counts as real money
        return False


def fleet_words(fleet: dict) -> str:
    """"2 bots are armed for real money; 1 hand lane is in live mode": what
    makes this a live operation, the hand lanes named apart from the bots
    and a bot on the demo world never called real money. One wording for
    the command's verdict and the watchdog's notice."""
    def said(n, one, many):
        return f"{n} {one if n == 1 else many}"

    live, demo, lanes = (int(fleet.get(k) or 0)
                         for k in ("live_bots", "demo_bots", "hand_lanes"))
    parts = []
    if live:
        parts.append(said(live, "bot is", "bots are")
                     + " armed for real money")
    if demo:
        parts.append(said(demo, "bot is", "bots are")
                     + " in live mode on the demo world")
    if lanes:
        parts.append(said(lanes, "hand lane is", "hand lanes are")
                     + " in live mode")
    return "; ".join(parts)


def no_paper_bot_words(paper_lanes: int = 0) -> str:
    """What "no paper bot is on" means for a live operation: the simulator
    still books the entries a live bot sends there (its rule is at the
    paper stage or has no stage row, the pair is benched, the posture sends
    a long to paper: asset_engine/base), and a paper hand lane's tickets
    when there is one."""
    return ("nothing trades on the simulator except entries a live bot's "
            "rule sends there"
            + (" and trades taken by hand on a paper lane"
               if paper_lanes else ""))


def _markets(configs) -> set:
    """{(symbol, class)} the configs list: the INSTRUMENT's class, the key a
    rule's eligibility reads, the config's own for a symbol with no row."""
    from instruments.models import Instrument
    listed = [(str(sym), str(cfg.asset_class))
              for cfg in configs for sym in (cfg.symbols or [])]
    known = dict(Instrument.objects
                 .filter(symbol__in={sym for sym, _cls in listed})
                 .values_list("symbol", "asset_class"))
    return {(sym, str(known.get(sym) or cls)) for sym, cls in listed}


def _fires_on(rule: str, symbol: str, asset_class: str) -> bool:
    """Can `rule` fire on this market? Its own eligibility test, the one
    its live rule asks before it evaluates (bearish_rules._BearishRule
    .eligible): the family that IS the rule, a fork reading its root's.

    A rule whose family has no test fires wherever it is scanned, and so
    does a rule no family replays (positioning_crowd_reversal_short, which
    takes every market no COT report maps): True. Unread is True as well.
    This feeds an alarm that names a rule, and it must not name one it
    could not read.
    """
    try:
        from backtester.proving.families import family_of
        hit = family_of(rule)
    except Exception:  # noqa: BLE001
        return True
    if hit is None:
        return True
    return hit[0].is_eligible(symbol, asset_class)


def _stuck_at_paper(paper_bots) -> list:
    """The rules born at research that reached the PAPER stage and that no
    enabled paper bot can give a fill: no paper bot lists a market the rule
    fires on. Sorted names.

    At the paper stage such a rule votes on a paper config and on no live
    one (signals/rule_birth.voteless), and the ladder asks for paper FILLS
    before real money (promotion_pipeline, paper to live_small). So with no
    paper bot for it, its ladder ends at paper. A paper stock bot does not
    help a rule that never fires on a share, and a paper hand lane scans
    nothing. A read that fails names no rule and is logged.
    """
    try:
        from signals.rule_birth import at_paper_stage
        rules = at_paper_stage()
        if not rules:
            return []
        markets = sorted(_markets(paper_bots))
        return [rule for rule in rules
                if not any(_fires_on(rule, sym, cls) for sym, cls in markets)]
    except Exception as e:  # noqa: BLE001 — unread names no rule
        logger.warning("[campaign readiness] rules at the paper stage "
                       "unread (%s): none is named", e)
        return []


def readiness(window_days: int = 30) -> dict:
    """Everything both callers need, measured once.

    Returns {"sections": [...], "blockers": [...], "notes": [...],
             "cold_links": [...], "window_days": int} and, since
    2026-11-12:

      "campaign"           "live": at least one enabled live-mode config
                           that SCANS (symbols, not the hand lane);
                           "paper": none, and at least one enabled paper
                           config; "none": neither. A live hand lane alone
                           does not change the kind: it is not a bot.
      "chain_faults"       what stops evidence being produced, whatever the
                           kind: the master switch, a beat entry, a link,
                           signals closed with no result, bars, no symbol
      "campaign_gaps"      the two paper checks: a live-action switch ON,
                           no paper bot
      "armed"              the live-action keys that are ON
      "paper_stage_stuck"  rules born at research, at the paper stage, with
                           no paper bot to trade on (_stuck_at_paper)
      "fleet"              the counts behind the kind (fleet_words)
      "bar_state"          {symbol: {"verdict", "newest"}} for every listed
                           symbol that has a 4h bar: the bar verdict and
                           the newest bar's time. The watchdog reads it to
                           tell a feed that was repaired from one whose
                           market is merely shut (tasks._waits_for_the_open)

    "blockers" is what the watchdog alarms on. For a paper campaign, or
    none, it holds what it always held, in the order the checks run. For a
    live operation it holds the chain's faults and the stuck-rule finding
    only: the two paper checks are the operator's decision.

    Every finding is a Finding: its sentence, and the key that names it.
    Never raises: a readiness check that can fail is one more thing that
    can go quiet.
    """
    now = timezone.now()
    window = max(1, int(window_days or 30))
    sections: list = []
    notes: list = []
    cold: list = []
    #: Every finding in the order the checks run: (group, Finding).
    found: list = []

    def fault(key, text):
        """A fault of the chain: a blocker for every kind of campaign."""
        found.append(("chain", Finding(key, text)))

    def gap(key, text):
        """One of the two paper checks: a blocker unless a bot is live."""
        found.append(("campaign", Finding(key, text)))

    def stuck(key, text):
        """The one paper check a live operation keeps."""
        found.append(("stuck", Finding(key, text)))

    # ── 1. the master switch ────────────────────────────────────────────
    master = component_state("platform_master")
    sections.append(("MASTER SWITCH", [("platform_master", master, "")]))
    if master != "ON":
        fault(("master",),
              "platform_master is not ON — every guarded task no-ops, so "
              "nothing in the chain below runs whatever its own switch says")
        cold.append("platform_master")

    # ── 2. the chain ────────────────────────────────────────────────────
    # ── 1b. the switch that "ungated" tasks DO have ────────────────────
    # Under django_celery_beat's DatabaseScheduler every beat entry is a
    # PeriodicTask row with an `enabled` box in /admin/, and a box unticked
    # there stays unticked across every beat restart. "No switch to look
    # for" is true of PlatformComponent, not of that box — so look at it.
    for task, _every, _what in UNGATED:
        try:
            from django_celery_beat.models import PeriodicTask
            off = PeriodicTask.objects.filter(task=task, enabled=False).exists()
        except Exception:  # noqa: BLE001 — no scheduler table is not a blocker
            off = False
        if off:
            fault(("beat", task),
                  f"{task.split('.')[-1]} is DISABLED in the beat schedule "
                  f"(Django admin → Periodic tasks). It has no "
                  f"PlatformComponent switch, but that box is one, and it "
                  f"stays unticked across restarts")

    rows = []
    for key, what in EVIDENCE_CHAIN:
        state = component_state(key)
        rows.append((key, state, what))
        if state == "ON":
            continue
        cold.append(key)
        fix = ("run: manage.py seed_components" if state == "NO ROW"
               else "turn it on at /ops/")
        fault(("link", key, state),
              f"{key} is {state} — {what} never runs, so the ladder will "
              f"read n=0 after 90 days and there will be nothing to show "
              f"({fix})")
    sections.append(("THE EVIDENCE CHAIN", rows))

    # ── 3. what a paper campaign wants off ──────────────────────────────
    # The section keeps its title for a paper campaign; the command heads
    # it "LIVE-ACTION SWITCHES" for a live operation, where "must not" is
    # no longer true. Each switch in its own words (LIVE_ACTION_WORDS).
    rows = []
    armed: list = []
    for key in MUST_BE_OFF:
        state = component_state(key)
        rows.append((key, state, ""))
        if state == "ON":
            armed.append(key)
            gap(("armed", key),
                f"{key} is ON — {live_action_words(key)}, which is not a "
                f"paper campaign")
    sections.append(("MONEY MUST NOT MOVE", rows))

    # ── 4. configs ──────────────────────────────────────────────────────
    from bot_program.models import AssetBotConfig
    enabled = list(AssetBotConfig.objects.filter(enabled=True))
    paper = [c for c in enabled if c.mode == "paper"]
    live = [c for c in enabled if c.mode != "paper"]
    sections.append((f"ENABLED CONFIGS — {len(paper)} paper, {len(live)} live", [
        (f"[{c.id}] {c.name}", c.mode,
         f"{c.asset_class} · {len(c.symbols or [])} symbols")
        for c in enabled]))

    # THE KIND OF CAMPAIGN (2026-11-12), decided by the configs that SCAN.
    # A live hand lane is not a bot: paper bots beside one are still a
    # paper campaign, and a lane alone is no campaign at all, as before.
    # The count that makes a campaign "paper" is the old one (any enabled
    # paper config, a paper lane included), so nothing moves for it.
    live_bots = [c for c in live if _scans(c)]
    paper_bots = [c for c in paper if _scans(c)]
    campaign = "live" if live_bots else ("paper" if paper else "none")
    worlds: dict = {}
    demo_bots = [c for c in live_bots if _on_demo_world(c, worlds)]
    fleet = {"live_bots": len(live_bots) - len(demo_bots),
             "demo_bots": len(demo_bots),
             "hand_lanes": sum(1 for c in live if _is_hand_lane(c)),
             "paper_bots": len(paper_bots),
             "paper_lanes": sum(1 for c in paper if _is_hand_lane(c))}
    if campaign == "live":
        if not paper_bots:
            gap(("no_paper",),
                "no paper bot is on — "
                + no_paper_bot_words(fleet["paper_lanes"]))
    elif not paper:
        gap(("no_paper",),
            "no enabled config is in paper mode — a paper campaign needs at "
            "least one bot allowed to produce paper fills")
    if live:
        notes.append(
            f"{len(live)} config(s) are in LIVE mode. That is a choice, not a "
            f"fault — but their fills enter the same track record, and venue "
            f"discipline means live and paper are never pooled. Decide which "
            f"one the 90 days are measuring")

    # ── 5. what the ladder can see ──────────────────────────────────────
    from signals.models import Signal
    since = now - timedelta(days=window)
    closed = Signal.objects.filter(is_active=False, created_at__gte=since)
    n_closed = closed.count()
    n_graded = closed.exclude(realized_r__isnull=True).count()
    n_active = Signal.objects.filter(is_active=True).count()
    # The gates are quoted, never typed: retuning the ladder must not leave
    # this report describing the old one.
    from signals.promotion_pipeline import (
        PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS, PROMO_PAPER_TO_LIVE_SMALL_MIN_N,
        PROMO_RESEARCH_TO_PAPER_MIN_N)
    sections.append(("WHAT THE LADDER CAN SEE", [
        ("signals still active", str(n_active), ""),
        ("signals closed", str(n_closed), f"last {window} days"),
        ("... carrying a realized_r", str(n_graded),
         "the ladder counts ONLY these"),
        ("gates", "",
         f"research->paper needs n>={PROMO_RESEARCH_TO_PAPER_MIN_N}, "
         f"paper->live needs n>={PROMO_PAPER_TO_LIVE_SMALL_MIN_N} over "
         f">={PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS} days"),
    ]))
    if n_closed and not n_graded:
        fault(("no_result",),
              f"{n_closed} signals closed in the last {window} days and NOT "
              f"ONE carries a realized_r — the lifecycle pass is closing "
              f"rows without a price it can measure against, which is what "
              f"a bar feed past its age limit looks like from the ladder's "
              f"side")

    # ── 6. the fuel ─────────────────────────────────────────────────────
    # GROUPED BY CAUSE, NOT ONE PARAGRAPH PER SYMBOL (2026-09-15).
    # The first version of this walked the live fleet and produced 65
    # near-identical notes saying a US market was shut, which buried the two
    # findings that mattered — two live actuators armed during a paper
    # campaign. A report that repeats itself is not thorough, it is
    # unreadable, and an operator who scrolls past it once scrolls past it
    # every time.
    from bot_program.management.commands.preflight_live import (
        BAR_DEAD_HOURS, _bar_verdict, _market_note)
    from market_data.models import PriceData
    rows, seen = [], set()
    grouped: dict = {}
    no_bars: list = []
    bar_state: dict = {}
    for cfg in enabled:
        for sym in list(cfg.symbols or [])[:SYMBOLS_PER_CONFIG]:
            if sym in seen:
                continue
            seen.add(sym)
            row = (PriceData.objects
                   .filter(instrument__symbol=sym, timeframe="4h")
                   .order_by("-timestamp")
                   .values("timestamp", "close", "instrument__asset_class",
                           "instrument__exchange", "instrument__symbol")
                   .first())
            newest = row["timestamp"] if row else None
            if newest is None:
                rows.append((sym, "no 4h bar at all", ""))
                no_bars.append(sym)
                continue
            age = (now - newest).total_seconds() / 3600.0
            rows.append((sym, f"{age:.1f}h", _market_note(row, newest, now)))
            kind, name, _age = _bar_verdict(row, newest, now)
            bar_state[sym] = {"verdict": kind, "newest": newest.isoformat()}
            if kind not in ("ok", "unknown"):
                grouped.setdefault((kind, name), []).append((sym, age))
    sections.append(("BARS FOR ENABLED CONFIGS", rows))

    if no_bars:
        fault(("no_bars", tuple(sorted(no_bars))),
              f"{len(no_bars)} symbol(s) have no 4h bars at all — no rule "
              f"can form a decision on them, so they contribute nothing to "
              f"the 90 days: {_names(no_bars)}")

    # The two bar faults share one key word and carry the venue and the
    # symbols, never the age: see Finding.
    for (kind, name), hits in sorted(grouped.items()):
        syms = [s for s, _a in hits]
        worst = max(a for _s, a in hits)
        if kind == "late_open":
            fault(("bars_stopped", name, tuple(sorted(syms))),
                  f"{name} is OPEN and {len(syms)} symbol(s) have a 4h bar "
                  f"up to {worst:.1f}h old — refresh-bot-bars runs every 10 "
                  f"minutes, so the feed has stopped for them and an armed "
                  f"bot is deciding on a stale candle: {_names(syms)}")
        elif kind == "thin_open":
            notes.append(
                f"{name} is open and {len(syms)} symbol(s) have a 4h bar up "
                f"to {worst:.1f}h old, but the bar writer asked the source "
                f"minutes ago and it had nothing newer: a thin market that "
                f"printed nothing, not a dead feed — the bot decides on the "
                f"last trade there is: {_names(syms)}")
        elif kind == "shut_dead":
            fault(("bars_stopped", name, tuple(sorted(syms))),
                  f"{len(syms)} symbol(s) are missing up to "
                  f"{worst / 24:.1f} days of 4h bars. {name} being shut "
                  f"explains a weekend, not this — the bar writer has "
                  f"stopped for them: {_names(syms)}")
        else:  # shut_stale
            notes.append(
                f"{name} is shut and {len(syms)} symbol(s) have bars up to "
                f"{worst:.1f}h old, past the {BAR_DEAD_HOURS:.0f}h limit the "
                f"paper venue and the signal lifecycle both enforce. Correct "
                f"for a shut market — and it means no signal on them reaches "
                f"an outcome, and no paper position is marked, until {name} "
                f"reopens: {_names(syms)}")

    if not seen:
        fault(("no_symbol",),
              "no enabled config lists a symbol — nothing will be measured")

    # ── 7. the rules with nowhere to trade ──────────────────────────────
    # The true form of "no enabled config is in paper mode" for a live
    # operation: silent while it changes nothing, and a finding the day a
    # rule born at research reaches the paper stage and no paper bot can
    # give it a fill. A paper campaign, or none, keeps its blockers as
    # they were.
    stuck_rules = _stuck_at_paper(paper_bots)
    if stuck_rules and campaign == "live":
        one = len(stuck_rules) == 1
        stuck(("stuck", tuple(stuck_rules)),
              f"{_names(stuck_rules)} {'is' if one else 'are'} at the paper "
              f"stage with no paper bot to trade on — "
              f"{'it' if one else 'they'} can earn no paper fill, and the "
              f"ladder asks for paper fills before real money. "
              f"{'It needs' if one else 'They need'} a paper bot that lists "
              f"a market {'it fires' if one else 'they fire'} on")

    chain_faults = [f for group, f in found if group == "chain"]
    campaign_gaps = [f for group, f in found if group == "campaign"]
    if campaign == "live":
        blockers = [f for group, f in found if group != "campaign"]
    else:
        blockers = [f for _group, f in found]

    return {"sections": sections, "blockers": blockers, "notes": notes,
            "cold_links": cold, "window_days": window,
            "campaign": campaign, "chain_faults": chain_faults,
            "campaign_gaps": campaign_gaps, "armed": armed,
            "paper_stage_stuck": stuck_rules, "fleet": fleet,
            "bar_state": bar_state}
