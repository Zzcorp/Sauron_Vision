"""Nightly self-grading digest — Phase 1.0.

Prints a performance digest for both Signal and SmcSignal models, sliced by
multiple groupings. Intended to run nightly via Celery beat or `python manage.py
grade_signals --window=30`.

Usage:
    python manage.py grade_signals
    python manage.py grade_signals --window=30
    python manage.py grade_signals --window=14 --decay-baseline=90
    python manage.py grade_signals --json
"""
import json
from django.core.management.base import BaseCommand


GROUPINGS = ("signal_type", "asset_class", "urgency", "rule_name")


class Command(BaseCommand):
    help = "Print a performance digest grading every closed signal in the lookback window."

    def add_arguments(self, parser):
        parser.add_argument("--window", type=int, default=30,
                            help="Lookback in days for the headline digest (default: 30).")
        parser.add_argument("--decay-baseline", type=int, default=90,
                            help="Baseline window for decay comparison (default: 90 days).")
        parser.add_argument("--decay-recent", type=int, default=14,
                            help="Recent window for decay comparison (default: 14 days).")
        parser.add_argument("--json", action="store_true",
                            help="Emit JSON instead of human output.")

    def handle(self, *args, **opts):
        from signals.models import Signal
        from signals.performance import (
            calculate_signal_stats,
            setup_performance_summary,
            decay_flag,
        )

        window = opts["window"]
        recent_days = opts["decay_recent"]
        baseline_days = opts["decay_baseline"]

        report = {
            "window_days": window,
            "overall_signal": calculate_signal_stats(days=window),
            "setup_summary": setup_performance_summary(days=window),
            "groupings": {
                g: calculate_signal_stats(days=window, group_by=g) for g in GROUPINGS
            },
            "decay": [],
        }

        # Decay scan: every rule_name with at least one closed signal in baseline window.
        rules = (
            Signal.objects
            .filter(is_active=False).exclude(outcome="")
            .values_list("rule_name", flat=True)
            .distinct()
        )
        for rn in rules:
            if not rn:
                continue
            report["decay"].append(decay_flag(rn, recent_days=recent_days, baseline_days=baseline_days))

        if opts["json"]:
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return

        self._render_human(report, window)

    # ── human renderer ─────────────────────────────────────────────────────

    def _render_human(self, report, window):
        s = self.stdout
        s.write(self.style.SUCCESS(f"\n=== SAURON · self-grading digest ({window}d) ===\n"))

        ov = report["overall_signal"]
        s.write(self.style.WARNING("Overall (Signal model)"))
        s.write(self._fmt_row(ov))
        s.write("")

        for group, data in report["groupings"].items():
            s.write(self.style.WARNING(f"By {group}"))
            if not data:
                s.write("  (no closed signals)")
            else:
                for k, stats in sorted(data.items(), key=lambda kv: -(kv[1]["n_closed"] or 0)):
                    s.write(f"  {str(k)[:24]:24s} {self._fmt_row(stats, indent=False)}")
            s.write("")

        s.write(self.style.WARNING("SmcSignal setup performance"))
        if not report["setup_summary"]:
            s.write("  (no closed SMC signals)")
        else:
            for setup, p in sorted(
                report["setup_summary"].items(), key=lambda kv: -(kv[1]["n_closed"] or 0)
            ):
                hr = f"{p['hit_rate']:.0%}" if p["hit_rate"] is not None else "  n/a"
                ex = f"{p['expectancy_r']:+.2f}R" if p["expectancy_r"] is not None else "   n/a"
                tag = "empirical" if p["is_empirical"] else "fallback"
                s.write(f"  {setup:18s} hit={hr:>5} exp={ex:>7} n={p['n_closed']:3d} ({tag})")
        s.write("")

        decaying = [d for d in report["decay"] if d["is_decaying"]]
        s.write(self.style.WARNING(f"Decay watch ({len(report['decay'])} rules scanned)"))
        if not decaying:
            s.write("  no decaying rules detected.")
        else:
            s.write(self.style.ERROR(f"  ▲  {len(decaying)} rule(s) below half of baseline expectancy:"))
            for d in decaying:
                s.write(self.style.ERROR(
                    f"    {d['rule_name'][:40]:40s} recent={d['recent_expectancy']:+.2f}R "
                    f"(n={d['recent_n']})  vs baseline={d['baseline_expectancy']:+.2f}R "
                    f"(n={d['baseline_n']})"
                ))
        s.write("")

    def _fmt_row(self, stats, indent=True):
        lead = "  " if indent else ""
        if stats["n_closed"] == 0:
            return f"{lead}(no closed signals)"
        hr = f"{stats['hit_rate']:.0%}" if stats["hit_rate"] is not None else "n/a"
        ex = f"{stats['expectancy_r']:+.2f}R" if stats["expectancy_r"] is not None else "n/a"
        dur = f"{stats['avg_duration_h']:.1f}h" if stats["avg_duration_h"] is not None else "n/a"
        tag = "empirical" if stats["is_empirical"] else "fallback"
        return f"{lead}n={stats['n_closed']:3d}  hit={hr:>5}  exp={ex:>7}  dur={dur:>7}  ({tag})"
