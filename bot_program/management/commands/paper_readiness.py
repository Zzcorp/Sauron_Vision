"""WILL 90 DAYS OF PAPER PRODUCE A GRADED TRACK RECORD? (2026-09-15)

`preflight_live` answers "is it safe to arm real money". This is its mirror,
and it exists because the operator asked to spend two to three months on a
full paper campaign and then arrive with evidence — which is exactly what a
real firm would ask for, and exactly what this platform can silently fail to
produce.

THE CHAIN, AND WHY A SINGLE COLD LINK COSTS THE WHOLE CAMPAIGN

    bars -> indicators -> signals -> bot fills -> outcomes -> the ladder

Every link but one is gated by a `PlatformComponent`, and
`is_component_enabled` returns False for a MISSING ROW. So a link can be
cold in two different ways — switched off, or never seeded — and neither
raises, neither logs, and `guarded_task` simply no-ops. Ninety days later
the ladder reads `n=0` and there is nothing to show. That is not a
hypothetical: `broker_account_sync` was found with NO ROW on a development
box by this command's sibling.

The one ungated link is `signals.tasks_lifecycle.run_signal_lifecycle`,
every 300 s, and it is the link that writes `realized_r`. The ladder's gates
(`PROMO_PAPER_TO_LIVE_SMALL_MIN_N = 20`, `..._MIN_DAYS = 30`) count exactly
those rows. It needs a price, and past `MAX_BAR_AGE_SECONDS` it has none —
which is why bar age is reported here beside the market that explains it,
the same way `preflight_live` now does.

WHAT IT REFUSES TO DO

    python manage.py paper_readiness
    python manage.py paper_readiness --window-days 90

It writes nothing and it makes no broker call. It also never reports a
component as ON because a default says so: the answer comes from the row, and
a missing row is printed as its own state, because "off" and "never seeded"
lead an operator to two different actions.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

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


def _component_state(key: str) -> str:
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


class Command(BaseCommand):
    help = ("Is the evidence chain complete? Read-only readiness check for a "
            "paper-trading campaign.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-days", type=int, default=30,
            help="Window for counting graded rows (default 30).")

    def handle(self, *args, **opts):
        lines, blockers, notes = [], [], []

        def w(text=""):
            lines.append(text)

        now = timezone.now()
        window = max(1, int(opts.get("window_days") or 30))

        w("=" * 70)
        w("PAPER READINESS — WILL 90 DAYS PRODUCE A GRADED TRACK RECORD")
        w("=" * 70)

        # ── 1. the master switch ────────────────────────────────────────
        master = _component_state("platform_master")
        w(f"\n1. MASTER SWITCH\n   platform_master        {master}")
        if master != "ON":
            blockers.append(
                "platform_master is not ON — every guarded task no-ops, so "
                "nothing in the chain below runs whatever its own switch says")

        # ── 2. the chain ────────────────────────────────────────────────
        w("\n2. THE EVIDENCE CHAIN  (bars -> indicators -> signals -> fills "
          "-> outcomes -> ladder)")
        for key, what in EVIDENCE_CHAIN:
            state = _component_state(key)
            w(f"   {key:<24} {state:<7} {what}")
            if state == "ON":
                continue
            fix = ("run: manage.py seed_components" if state == "NO ROW"
                   else "turn it on at /ops/")
            blockers.append(
                f"{key} is {state} — {what} never runs, so the ladder will "
                f"read n=0 after 90 days and there will be nothing to show "
                f"({fix})")

        w("\n   Ungated by design — no switch to look for:")
        for task, every, what in UNGATED:
            w(f"   {task.split('.')[-1]:<24} every {every}s  {what}")

        # ── 3. what must stay off ───────────────────────────────────────
        w("\n3. MONEY MUST NOT MOVE DURING A PAPER CAMPAIGN")
        for key in MUST_BE_OFF:
            state = _component_state(key)
            w(f"   {key:<30} {state}")
            if state == "ON":
                blockers.append(
                    f"{key} is ON — a proposer is allowed to ACT on live "
                    f"capital, which is not a paper campaign")

        # ── 4. are any configs actually in paper mode? ──────────────────
        from bot_program.models import AssetBotConfig
        enabled = list(AssetBotConfig.objects.filter(enabled=True))
        paper = [c for c in enabled if c.mode == "paper"]
        live = [c for c in enabled if c.mode != "paper"]
        w(f"\n4. ENABLED CONFIGS — {len(paper)} paper, {len(live)} live")
        for cfg in enabled:
            w(f"   [{cfg.id}] {cfg.name:<20} {cfg.asset_class:<10} "
              f"{cfg.mode:<6} {len(cfg.symbols or [])} symbols")
        if not paper:
            blockers.append(
                "no enabled config is in paper mode — a paper campaign needs "
                "at least one bot allowed to produce paper fills")
        if live:
            notes.append(
                f"{len(live)} config(s) are in LIVE mode. That is a choice, "
                f"not a fault — but their fills enter the same track record, "
                f"and venue discipline means live and paper are never pooled. "
                f"Decide which one the 90 days are measuring")

        # ── 5. what the ladder can actually see ─────────────────────────
        from signals.models import Signal
        since = now - timezone.timedelta(days=window) \
            if hasattr(timezone, "timedelta") else None
        if since is None:
            from datetime import timedelta as _td
            since = now - _td(days=window)
        closed = Signal.objects.filter(is_active=False, created_at__gte=since)
        graded = closed.exclude(realized_r__isnull=True)
        active = Signal.objects.filter(is_active=True).count()
        w(f"\n5. WHAT THE LADDER CAN SEE  (last {window} days)")
        w(f"   signals still active        {active}")
        w(f"   signals closed              {closed.count()}")
        w(f"   ... carrying a realized_r   {graded.count()}   "
          f"(the ladder counts ONLY these)")

        from signals.promotion_pipeline import (
            PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS,
            PROMO_PAPER_TO_LIVE_SMALL_MIN_N,
            PROMO_RESEARCH_TO_PAPER_MIN_N)
        w(f"   gates: research->paper needs n>={PROMO_RESEARCH_TO_PAPER_MIN_N}"
          f", paper->live needs n>={PROMO_PAPER_TO_LIVE_SMALL_MIN_N} over "
          f">={PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS} days")
        if closed.count() and not graded.count():
            blockers.append(
                f"{closed.count()} signals closed in the last {window} days "
                f"and NOT ONE carries a realized_r — the lifecycle pass is "
                f"closing rows without a price it can measure against "
                f"(see section 6: a bar past the age limit yields no price)")

        # ── 6. the fuel, with the market that explains its age ──────────
        from bot_program.management.commands.preflight_live import (
            BAR_DEAD_HOURS, _bar_findings, _market_note)
        from market_data.models import PriceData
        w(f"\n6. BARS FOR ENABLED CONFIGS  (dead past {BAR_DEAD_HOURS:.0f}h "
          f"— no price, no outcome, no evidence)")
        seen = set()
        for cfg in enabled:
            for sym in list(cfg.symbols or [])[:8]:
                if sym in seen:
                    continue
                seen.add(sym)
                row = (PriceData.objects
                       .filter(instrument__symbol=sym, timeframe="4h")
                       .order_by("-timestamp")
                       .values("timestamp", "close",
                               "instrument__asset_class",
                               "instrument__exchange")
                       .first())
                newest = row["timestamp"] if row else None
                if newest is None:
                    w(f"   {sym:<12} no 4h bar at all")
                    blockers.append(
                        f"{sym} has no 4h bars — no rule can form a decision "
                        f"on it, so it contributes nothing to the 90 days")
                    continue
                age = (now - newest).total_seconds() / 3600.0
                w(f"   {sym:<12} {age:.1f}h"
                  f"{_market_note(row, newest, now)}")
                _bar_findings(sym, row, newest, now, blockers, notes)
        if not seen:
            blockers.append(
                "no enabled config lists a symbol — nothing will be measured")

        # ── verdict ─────────────────────────────────────────────────────
        w("\n" + "=" * 70)
        if blockers:
            w("BLOCKERS — 90 days would produce nothing gradeable:")
            for i, m in enumerate(blockers, 1):
                w(f"  {i}. {m}")
        else:
            w("NO BLOCKERS — the chain is complete end to end.")
        if notes:
            w("\nWORTH READING:")
            for i, m in enumerate(notes, 1):
                w(f"  {i}. {m}")
        w("=" * 70)
        w("This command writes nothing and makes no broker call. It says")
        w("whether the chain CAN produce evidence, never whether the")
        w("evidence is good.")

        self.stdout.write("\n".join(lines) + "\n")
