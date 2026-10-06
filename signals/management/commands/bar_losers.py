"""Bar the measured losers from real money — read the table, or apply it.

The operator (2026-10-05): the account has paid in and nothing has come
back. The rules that lose, measured, must not keep the live venue. The
nightly sweep (signals.tasks.auto_evaluate_promotions, component
`pipeline_promotion`) compares a live rule's recent window with the
baseline it was promoted on — and returns nothing when that baseline is
None or at or under zero, which is what a bulk promotion leaves behind.
So a measured loser could keep real money until a human acted.

This command reads every rule at a live stage with its ALL-TIME graded
record (signals.promotion_pipeline.measured_loser: LOSER_MIN_N graded
signals, a hit rate under LOSER_HIT_MAX or an expectancy at or under
zero) and the verdict the floor gives it; `--apply` demotes every LOSER
to PAPER (one PromotionEvent each, reason auto_demote, the numbers in
the note). A rule the operator promoted by hand within MANUAL_DWELL_DAYS
is listed and left alone: their last word stands. The nightly sweep
applies the same floor once pipeline_promotion is ON.

    python manage.py bar_losers           # the table, nothing written
    python manage.py bar_losers --apply   # bar every LOSER to paper

Demotion to paper gates the orders the consensus NAMES after the rule;
its signals still vote (base.py's vote filter drops research only) — the
next cut, not this one. Nothing here touches a position or a venue.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Read every live rule's measured record and the floor's verdict; "
            "--apply bars the measured losers to paper.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Demote every LOSER to paper (one "
                                 "PromotionEvent each). Without it: the table "
                                 "only, nothing written.")

    def handle(self, *args, **opts):
        from signals.models import RuleControl
        from signals.promotion_pipeline import (
            LOSER_HIT_MAX, LOSER_MIN_N, MANUAL_DWELL_DAYS, _stats_since,
            demote_rule, hand_promoted_recently, measured_loser)
        w = self.stdout.write
        apply = bool(opts.get("apply"))
        rows = list(RuleControl.objects.filter(
            promotion_stage__in=("live_small", "live_full"))
            .order_by("rule_name"))
        w(f"BAR THE LOSERS · {len(rows)} rule(s) at a live stage · floor: "
          f"{LOSER_MIN_N} graded signals and hit < {LOSER_HIT_MAX:.0%} or "
          f"expectancy <= 0R · a hand promotion stands {MANUAL_DWELL_DAYS} "
          f"days")
        if not rows:
            w("  no rule is at a live stage — nothing to bar")
            return
        barred = 0
        for ctrl in rows:
            s = _stats_since(ctrl.rule_name)
            n = int(s.get("n") or 0)
            hit = s.get("hit_rate")
            exp = s.get("expectancy")
            why = measured_loser(ctrl.rule_name)
            dwell = why and hand_promoted_recently(ctrl.rule_name)
            if why and not dwell:
                verdict = "LOSER"
            elif why and dwell:
                verdict = (f"loser, but promoted by hand within "
                           f"{MANUAL_DWELL_DAYS} days — left alone")
            elif n < LOSER_MIN_N:
                verdict = f"unmeasured (n {n} < {LOSER_MIN_N})"
            else:
                verdict = "ok"
            w(f"  {ctrl.rule_name:28} {ctrl.promotion_stage:10} n {n:4}  hit "
              f"{(f'{float(hit):.0%}' if hit is not None else '—'):>4}  exp "
              f"{(f'{float(exp):+.2f}R' if exp is not None else '—'):>7}  "
              f"{verdict}")
            if apply and verdict == "LOSER":
                demote_rule(ctrl.rule_name, "paper", user=None,
                            reason="auto_demote",
                            notes=f"bar_losers: measured loser: {why}")
                barred += 1
                w(f"    -> barred to paper ({why})")
        if apply:
            w(self.style.SUCCESS(f"Barred {barred} rule(s) to paper."))
        else:
            w("Dry run — nothing written. --apply demotes every LOSER to "
              "paper; the nightly sweep does the same once "
              "pipeline_promotion is ON.")
