"""manage.py side_scorecard [--rule X] [--class Y]

THE SCORECARD BY SIDE (2026-10-31): long against short per rule and
class — graded signals, paper and live fills, the proving ground's newest
verdict and the stage — the table /evidence/ shows
(bot_program.evidence.side_rows). Read-only: it writes nothing and no
gate reads it.

    python manage.py side_scorecard                     # every rule, every class
    python manage.py side_scorecard --rule death_cross
    python manage.py side_scorecard --class stock
"""
from django.core.management.base import BaseCommand


def _r(x) -> str:
    return "—" if x is None else f"{float(x):+.2f}R"


def _pct(x) -> str:
    return "—" if x is None else f"{float(x) * 100:.0f}%"


class Command(BaseCommand):
    help = "Long against short, per rule and class (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--rule", default=None)
        parser.add_argument("--class", dest="asset_class", default=None)

    def handle(self, *args, **opts):
        from bot_program.evidence import SIDES, side_rows
        rows = side_rows(rule=opts["rule"], asset_class=opts["asset_class"])
        w = self.stdout.write
        w("SCORECARD BY SIDE · long against short, per rule and class")
        if not rows:
            w("  nothing graded or filled yet")
            return
        for r in rows:
            w(f"  {r['rule']} · {r['asset_class']} · stage {r['stage']}")
            for side in SIDES:
                c = r[side]
                v = c["verdict"]
                verdict = (f"{v['verdict'].upper()} {_r(v['expectancy'])} over "
                           f"{v['trades_n']} trades" if v
                           else f"unjudged ({c['unjudged']})")
                w(f"    {side:5}  graded {c['sig_n']} · hit "
                  f"{_pct(c['sig_hit'])} · avg {_r(c['sig_avg'])} · paper "
                  f"{c['paper_n']} at {_r(c['paper_avg'])} · live "
                  f"{c['live_n']} at {_r(c['live_avg'])} · {verdict}")
            if r["gap"] is not None:
                w(f"    gap    short less long {_r(r['gap'])}")
