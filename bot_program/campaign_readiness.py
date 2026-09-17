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

#: A paper campaign must move no money. These are the keys that let a
#: proposer ACT rather than propose, plus the one that de-risks on its own.
#: Named individually rather than matched on "_mode_live", so a new actuator
#: has to be added here deliberately instead of inheriting an exemption from
#: a naming convention.
MUST_BE_OFF = (
    "actuator_mode_live",
    "meta_allocator_mode_live",
    "share_allocator_mode_live",
    "capital_desk_mode_live",
    "share_allocator_auto_derisk",
)

#: Ungated by design, and load-bearing. Reported so that nobody looks for a
#: switch that does not exist.
UNGATED = (
    ("signals.tasks_lifecycle.run_signal_lifecycle", 300,
     "stamps MFE/MAE and closes outcomes — the sole writer of realized_r"),
    ("market_data.tasks.refresh_bot_bars_task", 600,
     "writes the 1h/4h bars every other link reads"),
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


def readiness(window_days: int = 30) -> dict:
    """Everything both callers need, measured once.

    Returns {"sections": [...], "blockers": [...], "notes": [...],
             "cold_links": [...], "window_days": int}. Never raises: a
    readiness check that can fail is one more thing that can go quiet.
    """
    now = timezone.now()
    window = max(1, int(window_days or 30))
    sections: list = []
    blockers: list = []
    notes: list = []
    cold: list = []

    # ── 1. the master switch ────────────────────────────────────────────
    master = component_state("platform_master")
    sections.append(("MASTER SWITCH", [("platform_master", master, "")]))
    if master != "ON":
        blockers.append(
            "platform_master is not ON — every guarded task no-ops, so "
            "nothing in the chain below runs whatever its own switch says")
        cold.append("platform_master")

    # ── 2. the chain ────────────────────────────────────────────────────
    rows = []
    for key, what in EVIDENCE_CHAIN:
        state = component_state(key)
        rows.append((key, state, what))
        if state == "ON":
            continue
        cold.append(key)
        fix = ("run: manage.py seed_components" if state == "NO ROW"
               else "turn it on at /ops/")
        blockers.append(
            f"{key} is {state} — {what} never runs, so the ladder will read "
            f"n=0 after 90 days and there will be nothing to show ({fix})")
    sections.append(("THE EVIDENCE CHAIN", rows))

    # ── 3. what must stay off ───────────────────────────────────────────
    rows = []
    for key in MUST_BE_OFF:
        state = component_state(key)
        rows.append((key, state, ""))
        if state == "ON":
            blockers.append(
                f"{key} is ON — a proposer is allowed to ACT on live "
                f"capital, which is not a paper campaign")
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
    if not paper:
        blockers.append(
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
        blockers.append(
            f"{n_closed} signals closed in the last {window} days and NOT ONE "
            f"carries a realized_r — the lifecycle pass is closing rows "
            f"without a price it can measure against, which is what a bar "
            f"feed past its age limit looks like from the ladder's side")

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
            if kind not in ("ok", "unknown"):
                grouped.setdefault((kind, name), []).append((sym, age))
    sections.append(("BARS FOR ENABLED CONFIGS", rows))

    if no_bars:
        blockers.append(
            f"{len(no_bars)} symbol(s) have no 4h bars at all — no rule can "
            f"form a decision on them, so they contribute nothing to the 90 "
            f"days: {_names(no_bars)}")

    for (kind, name), hits in sorted(grouped.items()):
        syms = [s for s, _a in hits]
        worst = max(a for _s, a in hits)
        if kind == "late_open":
            blockers.append(
                f"{name} is OPEN and {len(syms)} symbol(s) have a 4h bar up "
                f"to {worst:.1f}h old — refresh-bot-bars runs every 10 "
                f"minutes, so the feed has stopped for them and an armed bot "
                f"is deciding on a stale candle: {_names(syms)}")
        elif kind == "shut_dead":
            blockers.append(
                f"{len(syms)} symbol(s) are missing up to {worst / 24:.1f} "
                f"days of 4h bars. {name} being shut explains a weekend, not "
                f"this — the bar writer has stopped for them: {_names(syms)}")
        else:  # shut_stale
            notes.append(
                f"{name} is shut and {len(syms)} symbol(s) have bars up to "
                f"{worst:.1f}h old, past the {BAR_DEAD_HOURS:.0f}h limit the "
                f"paper venue and the signal lifecycle both enforce. Correct "
                f"for a shut market — and it means no signal on them reaches "
                f"an outcome, and no paper position is marked, until {name} "
                f"reopens: {_names(syms)}")

    if not seen:
        blockers.append(
            "no enabled config lists a symbol — nothing will be measured")

    return {"sections": sections, "blockers": blockers, "notes": notes,
            "cold_links": cold, "window_days": window}
