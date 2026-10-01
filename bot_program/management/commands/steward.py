"""The steward and the crisis mode, from the shell (2026-10-02).

    python manage.py steward                       # posture, pairs, last 24 h
    python manage.py steward run                   # what it would move now (plan)
    python manage.py steward run --yes             # ... and move it
    python manage.py steward stress                # the market's stress, every input
    python manage.py steward posture crisis --hours 12   # force a posture
    python manage.py steward posture auto          # back to the measured posture
    python manage.py steward bench RULE CLASS --pin --why 'text'
    python manage.py steward live RULE CLASS --pin
    python manage.py steward unpin RULE CLASS
    python manage.py steward journal --days 3

Postures: calm, stressed, crisis, recovery (an override lasts --hours, 24
by default). `steward probation RULE CLASS` puts a pair on probation by
hand. `steward stress --yes` saves the reading it prints.
A pinned pair is the operator's: the steward never changes it. CLASS is the
config's class (stock, forex, crypto, commodity, ...), or * for every class
of the rule without a row of its own.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "The steward (pair lifecycle, position care) and the crisis mode."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status",
                            choices=["status", "run", "stress", "posture",
                                     "bench", "live", "probation", "unpin",
                                     "journal"])
        parser.add_argument("params", nargs="*")
        parser.add_argument("--yes", action="store_true")
        parser.add_argument("--pin", action="store_true")
        parser.add_argument("--why", default="")
        parser.add_argument("--hours", type=float, default=24.0)
        parser.add_argument("--days", type=int, default=3)
        parser.add_argument("--by", default="operator")

    def handle(self, *args, **o):
        action = o["action"]
        getattr(self, f"_{action}")(o)

    def _status(self, o):
        from bot_program.steward import report_lines
        for line in report_lines():
            self.stdout.write(line)

    def _run(self, o):
        from bot_program.steward import evaluate
        moves = evaluate(apply=o["yes"])
        if not moves:
            self.stdout.write("Nothing to move.")
            return
        self.stdout.write(("APPLIED" if o["yes"] else
                           "PLAN (nothing changed; --yes applies)") + ":")
        for m in moves:
            s = m.get("stats") or {}
            self.stdout.write(
                f"  {m['kind']:<10} {m['rule']}/{m['asset_class'] or '-'}"
                f" · n {s.get('n', '-')} · {m['reason']}"
                + (f" · ERROR {m['error']}" if m.get("error") else ""))

    def _stress(self, o):
        from bot_program.market_stress import evaluate
        r = evaluate(save=bool(o["yes"]))
        self.stdout.write(f"score {r.score} raw {r.raw_level or '-'} -> "
                          f"level {r.level}"
                          + ("" if o["yes"] else " (not saved; --yes saves)"))
        for k, v in (r.components.get("raw") or {}).items():
            sub = (r.components.get("sub") or {}).get(k)
            self.stdout.write(f"  {k}: {v}" + (f" -> {sub}" if sub is not None else ""))
        for why in r.reasons:
            self.stdout.write(f"  · {why}")

    def _posture(self, o):
        from bot_program.market_stress import set_override
        if not o["params"]:
            raise CommandError("posture calm|stressed|crisis|recovery|auto")
        value = set_override(o["params"][0], hours=o["hours"], by=o["by"])
        self.stdout.write(f"posture override: {value or 'cleared (auto)'}")

    def _pair(self, o):
        if len(o["params"]) != 2:
            raise CommandError("RULE CLASS expected")
        return o["params"][0], o["params"][1]

    def _set(self, o, state):
        from bot_program.steward import set_by_operator
        rule, cls = self._pair(o)
        set_by_operator(rule, cls, state, by=o["by"],
                        pin=True if o["pin"] else None, reason=o["why"])
        self.stdout.write(f"{rule}/{cls}: {state}"
                          + (" (pinned)" if o["pin"] else ""))

    def _bench(self, o):
        self._set(o, "bench")

    def _live(self, o):
        self._set(o, "live")

    def _probation(self, o):
        self._set(o, "probation")

    def _unpin(self, o):
        from bot_program.steward_models import PairVerdict, StewardAction
        rule, cls = self._pair(o)
        n = PairVerdict.objects.filter(rule_name=rule, asset_class=cls) \
            .update(pinned=False)
        StewardAction.objects.create(kind="operator_unpin", rule_name=rule,
                                     asset_class=cls, by=o["by"],
                                     detail="unpinned: the steward decides again")
        self.stdout.write(f"{rule}/{cls}: unpinned ({n} row)")

    def _journal(self, o):
        from bot_program.steward_models import StewardAction
        since = timezone.now() - timedelta(days=o["days"])
        for a in StewardAction.objects.filter(at__gte=since)[:200]:
            self.stdout.write(
                f"{a.at:%Y-%m-%d %H:%M} {a.kind:<18} "
                f"{a.rule_name}{'/' + a.asset_class if a.asset_class else ''}"
                f"{' ' + a.symbol if a.symbol else ''} [{a.by}] {a.detail[:140]}")
