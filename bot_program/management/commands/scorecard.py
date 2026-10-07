"""The book's scorecard: win rate, average win, average loss, expectancy —
and which of them is losing the money (bot_program/scorecard.py).

Read-only: it writes nothing and touches no broker.

    python manage.py scorecard                  # last 30 days, every lane
    python manage.py scorecard --days 90
    python manage.py scorecard --venue live     # real money only
    python manage.py scorecard --by rule        # one block per rule
    python manage.py scorecard --by class
    python manage.py scorecard --by signal      # with a Sauron signal or without
    python manage.py scorecard --venue live --by exit   # which exit closed each trade

`--by exit` (2026-10-07, PR51a) adds two lines: how many exit prices are
inferred, and how many live stock and ETF closes the venue made outside
09:30-16:00 New York ("unmeasured" when the venue's close time is not
recorded). `--by policy` waits for PR51b: no exit policy exists yet.
"""
from django.core.management.base import BaseCommand


def _pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def _r(x):
    return "—" if x is None else f"{x:+.2f}R"


class Command(BaseCommand):
    help = "Win rate, payoff and expectancy of the closed book, and the diagnosis."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--venue", choices=["live", "paper"], default=None)
        parser.add_argument("--by", choices=["lane", "rule", "class", "venue",
                                     "signal", "exit"],
                            default="lane",
                            help="How to split the book (default: lane — "
                                 "your hand-taken trades against the bots).")

    def handle(self, *args, **opts):
        from bot_program import scorecard as sc

        rows = sc.rows(days=max(1, opts["days"]), venue=opts["venue"])
        w = self.stdout.write
        scope = opts["venue"] or "live + paper"
        w(f"SCORECARD · last {opts['days']} days · {scope} · "
          f"{len(rows)} closed trade(s)")
        self._block("ALL", sc.summarize(rows))
        if opts["by"] == "exit":
            # WHICH EXIT (2026-10-07, PR51a): how far these R are estimates,
            # and how many venue closes fell outside the regular session
            w("")
            w(f"  {sc.inferred_line(rows)}")
            w(f"  {sc.outside_hours_line(rows)}")
        keys = {"lane": lambda r: r["lane"], "rule": lambda r: r["rule"] or "—",
                "class": lambda r: r["asset_class"],
                "venue": lambda r: r["venue"],
                "signal": lambda r: ("on a signal" if r["backed"]
                                     else "without a signal"),
                "exit": lambda r: r["exit"]}
        groups = sc.group(rows, keys[opts["by"]])
        for name, members in sorted(groups.items(),
                                    key=lambda kv: -len(kv[1])):
            self._block(f"{opts['by']} {name}", sc.summarize(members))

    def _block(self, title, s):
        from bot_program import scorecard as sc
        w = self.stdout.write
        w("")
        w(f"── {title} " + "─" * max(4, 56 - len(title)))
        if not s["n"]:
            w("  no measured closed trade" +
              (f" ({s['unmeasured']} unmeasured)" if s["unmeasured"] else ""))
            return
        w(f"  trades {s['n']}  ·  won {s['wins']}  lost {s['losses']}  ·  "
          f"win rate {_pct(s['win_rate'])}"
          + ("  ·  THIN SAMPLE" if s["thin"] else "")
          + (f"  ·  {s['unmeasured']} unmeasured" if s["unmeasured"] else ""))
        payoff = "—" if s["payoff"] is None else f"{s['payoff']:.2f}"
        w(f"  avg win {_r(s['avg_win'])}  ·  avg loss {_r(s['avg_loss'])}  ·  "
          f"payoff {payoff}")
        w(f"  expectancy {_r(s['expectancy'])} a trade  ·  total {_r(s['sum_r'])}")
        if s["needed_avg_win"] is not None:
            w(f"  at this win rate a winner must average "
              f"{_r(s['needed_avg_win'])} to break even; this payoff needs "
              f"a {_pct(s['breakeven_win_rate'])} win rate")
        w(f"  targets hit {s['targets_hit']}  ·  closed by hand {s['by_hand']}"
          + (f" ({s['by_hand_wins']} winners at {_r(s['by_hand_win_avg'])}"
             + (f", best seen {_r(s['by_hand_win_mfe'])}"
                if s["by_hand_win_mfe"] is not None else "") + ")"
             if s["by_hand_wins"] else ""))
        if s["gave_back"]:
            w(f"  gave back: {s['gave_back']} loser(s) had been "
              f"+{sc.REACHED_R:.0f}R first")
        for tid, sym, r in s["overshoot"]:
            w(f"  OVERSHOOT #{tid} {sym} {r:+.2f}R — past -{sc.OVERSHOOT_R}R, "
              f"a stop that did not hold")
        w(f"  → {sc.diagnosis(s)}")
