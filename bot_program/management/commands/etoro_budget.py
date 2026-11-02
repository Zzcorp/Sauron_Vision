"""The eToro request budget, per key hash and family, read-only (2026-11-01).

The budget (bot_program/engine/etoro_budget) counts every request to
eToro's public API per user key, in four families (market, account,
execution, lookups), and refuses the takes below P1 that would leave a
family less than its floor for the priorities above, judged on the rolling
minute (every request of the last 60 s, 2026-11-02). This prints, per key
hash and family, that rolling minute's count, and for this minute and the
one before:
the takes by priority, the refusals with their reasons and the last
refusal's words, the overruns (P0 and P1 past the family's rate, sent
anyway), and whether the shared 429 pause holds for each world and until
when.

Read-only: it writes nothing and asks no broker. No account figure and no
key: a key is named by its short hash only (etoro_budget.key_hash), the
same twelve characters every budget log line carries. A key appears once
a process has counted one of its requests within two days.

    python manage.py etoro_budget
"""
from datetime import datetime, timezone as dt_tz

from django.core.management.base import BaseCommand


def _at(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=dt_tz.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _minute(win, window_s) -> str:
    try:
        return datetime.fromtimestamp(int(win) * int(window_s),
                                      tz=dt_tz.utc).strftime("%H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


class Command(BaseCommand):
    help = ("Print the eToro request budget per key hash and family: this "
            "minute's and the last minute's takes by priority, refusals "
            "with their reasons, overruns, and the shared 429 pause. "
            "Read-only; no key, no account figure.")

    def handle(self, *args, **opts):
        from bot_program.engine import etoro_budget as eb

        rep = eb.report()
        out = self.stdout
        out.write(f"eToro request budget at {_at(rep['now'])} — windows of "
                  f"{eb.WINDOW_S} s, this minute and the one before")
        out.write("Rates a minute (guesses until eToro's quota headers are "
                  "measured): " + ", ".join(
                      f"{f} {rep['rates'][f]}" for f in eb.FAMILIES))
        out.write("Floors kept for the higher priorities, in tokens: " + "; "
                  .join(f"{eb.PRIORITY_NAMES[p]} " + ", ".join(
                      f"{f} {rep['floors'][p][f]}" for f in eb.FAMILIES)
                      for p in (eb.P2, eb.P3, eb.P4, eb.P5)))
        out.write("P0 and P1 are never refused: they are counted once sent, "
                  "and a family they take past its rate is an overrun.")
        if rep["unbudgeted_here"]:
            out.write("This process sent requests unbudgeted (the cache "
                      "unreachable): " + ", ".join(
                          f"{eb.PRIORITY_NAMES.get(p, p)} {n}" for p, n in
                          sorted(rep["unbudgeted_here"].items())))
        if not rep["ok"]:
            out.write(f"The budget's cache could not be read "
                      f"({rep['error']}): nothing more to show. P0 and P1 go "
                      f"through unbudgeted while it is unreachable; P2 to P5 "
                      f"are not asked.")
            return
        if not rep["keys"]:
            out.write("No eToro request has been counted in the last two "
                      "days (or the budget is off).")
            return
        for kh, entry in rep["keys"].items():
            out.write("")
            out.write(f"key {kh} · last counted {_at(entry['seen'])}")
            pause = []
            for world in ("live", "demo"):
                held = entry["pause"].get(world)
                if held and held["left"] > 0:
                    pause.append(f"{world} holds for {held['left']:.0f} s, "
                                 f"until {_at(held['end'])}")
                elif held:
                    pause.append(f"{world} none (the last ended "
                                 f"{_at(held['end'])})")
                else:
                    pause.append(f"{world} none")
            out.write("  429 pause: " + " · ".join(pause))
            # THE ROLLING MINUTE (2026-11-02): what a take is judged on;
            # the minutes below are its history
            for family in eb.FAMILIES:
                n = (entry.get("rolling") or {}).get(family) or 0
                if n:
                    out.write(f"  {family:<10} in the last {eb.WINDOW_S} s: "
                              f"{n}/{rep['rates'][family]} (what a take is "
                              f"judged on)")
            for family in eb.FAMILIES:
                rows = entry["families"].get(family) or {}
                for win in rep["windows"]:
                    row = rows.get(win)
                    if not row or not (row["taken"] or row["refused"]):
                        continue
                    by = " · ".join(
                        f"P{p} {row['by'][p]}" for p in eb.PRIORITIES
                        if row["by"].get(p))
                    refused = " · ".join(
                        f"P{p} refused {n} ({reason})" for (p, reason), n
                        in sorted(row["refused"].items()))
                    line = (f"  {family:<10} {_minute(win, eb.WINDOW_S)}  "
                            f"taken {row['taken']}/{rep['rates'][family]}")
                    if by:
                        line += f" · {by}"
                    if refused:
                        line += f" · {refused}"
                    if row["overruns"]:
                        line += f" · overruns {row['overruns']}"
                    out.write(line)
                    for p, words in sorted(row["last"].items()):
                        out.write(f"             last refusal at P{p}: "
                                  f"{words}")
