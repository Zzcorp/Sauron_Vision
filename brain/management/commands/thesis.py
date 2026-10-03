"""The thesis check (brain/thesis_check.py): is the reason for each open
trade still alive — the structure, the sweep, the bias, the odds of coming
back — and did the past verdicts pay?

Read-only: it writes nothing and touches no broker.

    python manage.py thesis                     # every open position: verdict and why
    python manage.py thesis show GBPCHF         # one symbol, the full read
    python manage.py thesis record --days 30    # how the past verdicts graded
"""
import json

from django.core.management.base import BaseCommand


def _r(x):
    return "—" if x is None else f"{x:+.2f}R"


class Command(BaseCommand):
    help = ("The thesis check on the open book: alive, adjust or dead, and "
            "why; and the record of the past verdicts.")

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="list",
                            choices=["list", "show", "record"])
        parser.add_argument("symbol", nargs="?", default="")
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **opts):
        if opts["action"] == "record":
            return self._record(opts["days"])
        return self._list(opts["symbol"].upper(), full=opts["action"] == "show")

    def _list(self, symbol, *, full):
        from brain.position_review import measure, open_positions
        rows = [p for p in open_positions()
                if not symbol or p["symbol"].upper() == symbol]
        if not rows:
            self.stdout.write("no open position"
                              + (f" on {symbol}" if symbol else ""))
            return
        cache = {}
        for pos in rows:
            facts = measure(pos, cache)
            th = facts.get("thesis") or {}
            self.stdout.write(
                f"{pos['symbol']:<10} {pos['side']:<5} #{pos['position_id']:<6}"
                f" {_r(facts.get('unrealized_r')):>8}  worst "
                f"{_r(facts.get('mae_r')):>8}  "
                f"{(th.get('verdict') or 'unread').upper():<7} "
                f"{th.get('words') or facts.get('no_verdict_reason') or ''}")
            if full:
                st = th.get("structure") or {}
                if st.get("ok"):
                    self.stdout.write(
                        f"    structure: bias {st.get('bias')} "
                        f"({st.get('confidence')}), zone {st.get('zone')}, "
                        f"sweep with {st.get('sweep_with')}, against "
                        f"{st.get('sweep_against')}, break against "
                        f"{st.get('break_against')}, structure stop "
                        f"{st.get('structure_stop')} ({st.get('structure_stop_why')})")
                else:
                    self.stdout.write(f"    structure: {st.get('why', 'unread')}")
                od = th.get("odds")
                if od:
                    self.stdout.write("    odds: " + json.dumps(
                        {k: od.get(k) for k in ("ok", "n", "thin", "won_pct",
                                                "target_pct", "avg_r",
                                                "avg_bars", "fell_back",
                                                "regime", "why")},
                        default=str))
                if th.get("adjust"):
                    self.stdout.write(f"    adjust: {th['adjust']}")

    def _record(self, days):
        from brain.thesis_check import track_record
        rec = track_record(days=days)
        if not rec:
            self.stdout.write(f"no thesis verdict in the last {days} days")
            return
        self.stdout.write(f"thesis verdicts, last {days} days "
                          f"(right = the position closed the way the "
                          f"verdict said, past the noise band)")
        for key in ("alive", "exit"):
            s = rec.get(key)
            if not s:
                continue
            judged = s["right"] + s["wrong"]
            hit = f"{s['right'] / judged * 100:.0f}%" if judged else "—"
            self.stdout.write(
                f"  {key:<6} n={s['n']:<4} right={s['right']:<3} "
                f"wrong={s['wrong']:<3} hit {hit:<5} unresolved="
                f"{s['unresolved']:<3} pending={s['pending']:<3} "
                f"R after the call {s['r_delta']:+.2f}")
