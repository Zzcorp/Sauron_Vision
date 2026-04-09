"""Run one SmcSignal lifecycle pass from the CLI."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run one SmcSignal lifecycle pass."

    def handle(self, *args, **opts):
        from signals.lifecycle import run_lifecycle_pass
        from signals.performance import setup_performance_summary

        result = run_lifecycle_pass()
        self.stdout.write(self.style.SUCCESS("Lifecycle pass complete:"))
        for status, count in result.items():
            self.stdout.write(f"  {status:14s} {count}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Setup performance (last 30d):"))
        perf = setup_performance_summary(days=30)
        if not perf:
            self.stdout.write("  (no closed signals yet)")
        for setup, p in perf.items():
            tag = "empirical" if p["is_empirical"] else "fallback"
            hr = f"{p['hit_rate']:.0%}" if p["hit_rate"] is not None else "n/a"
            ex = f"{p['expectancy_r']:+.2f}R" if p["expectancy_r"] is not None else "n/a"
            self.stdout.write(
                f"  {setup:18s}  hit={hr:>5}  exp={ex:>7}  n={p['n_closed']:3d}  ({tag})"
            )
