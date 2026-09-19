"""Where the money is, what each broker holds, and where the platform and
the broker disagree — in one screen.

The shell twin of /treasury/. Both render bot_program/broker_vision.vision(),
so the page and the terminal cannot tell different stories. Reads cached
columns only: it makes NO broker call and writes nothing.

Run with:

    python manage.py treasury
    python manage.py treasury --user mathe
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()
DASH = "—"          # unmeasured. Never a 0.


def _age(seconds) -> str:
    if seconds is None:
        return DASH
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds / 3600:.1f}h"


class Command(BaseCommand):
    help = ("Every broker, its capital, its positions, and the divergence "
            "between what the broker reports and what the platform believes. "
            "Read-only, no broker call.")

    def add_arguments(self, parser):
        parser.add_argument("--user", default="",
                            help="username (default: every user with a "
                                 "broker row)")

    def handle(self, *args, **opts):
        from bot_program.broker_vision import vision

        if opts["user"]:
            users = list(User.objects.filter(username=opts["user"]))
            if not users:
                raise CommandError(f"no user {opts['user']!r}")
        else:
            users = [u for u in User.objects.all()
                     if any(getattr(u, a, None) is not None for a in
                            ("saxo_account", "etoro_account", "ibkr_account"))]
            if not users:
                raise CommandError("no user has a broker row — add keys on "
                                   "/brokers/ first")
        w = self.stdout.write
        for user in users:
            self._one(w, user, vision(user))

    def _one(self, w, user, v):
        w("=" * 78)
        w(f"TREASURY {DASH} {user.username} {DASH} "
          f"{v['at'].strftime('%Y-%m-%d %H:%M')} UTC")
        w("=" * 78)

        w("\n1. THE BOOK")
        book = v["book"]
        if book is None:
            w(f"   {DASH} no row is the book: capital_truth has nothing to "
              f"read, and the preflight refuses to arm money")
        else:
            eq = book["equity"]
            money = (f"{eq['value_text']} {eq['currency']}" if eq else DASH)
            w(f"   {book['name']:<22} {book['env']:<6} {money:>20}   "
              f"read {_age(eq['age_seconds'] if eq else None)} ago")
            hw, dd = v["high_water"], v["drawdown"]
            hw_text = f"{hw['hwm']:,.2f} {hw['currency']}" if hw else DASH
            # drawdown_pct is a FRACTION of the high-water mark, never
            # negative — capital_truth.equity_drawdown's own contract.
            dd_text = f"{dd['drawdown_pct'] * 100:.2f}%" if dd else DASH
            w(f"   high water {hw_text:<24} drawdown from it {dd_text}")

        w("\n2. EVERY BROKER")
        w(f"   {'broker':<22} {'env':<6} {'capital':>18}  {'age':>6} "
          f"{'held':>5}  claims")
        for r in v["brokers"]:
            eq = r["equity"]
            money = f"{eq['value_text']} {eq['currency']}" if eq else DASH
            held = DASH if r["held_n"] is None else str(r["held_n"])
            flag = " *book" if r["is_book"] else ""
            w(f"   {r['name'] + flag:<22} {r['env']:<6} {money:>18}  "
              f"{_age(eq['age_seconds'] if eq else None):>6} {held:>5}  "
              f"{', '.join(r['claims']) or DASH}")
            w(f"   {'':<22} {r['session']}")

        w("\n3. WHERE A NEW TRADE WOULD GO")
        for r in v["routing"]:
            how = ("contested: " + ", ".join(r["claimants"])
                   if r["contested"] else
                   "by default" if r["by_default"] else "claimed")
            w(f"   {r['asset_class']:<12} {r['winner']:<10} {how}")

        w("\n4. POSITIONS THE PLATFORM BELIEVES ARE OPEN")
        plat = v["platform"]
        if not plat["live"]:
            w(f"   no live row open   ({plat['paper_n']} paper row(s), "
              f"counted apart {DASH} venue discipline)")
        else:
            w(f"   {'symbol':<12} {'side':<5} {'qty':>14} {'entry':>14} "
              f"{'broker':<8} {'how':<9} state")
            for p in plat["live"]:
                state = ("working" if p["working"] else
                         "protected" if p["protected"] else "unprotected")
                w(f"   {p['symbol']:<12} {p['side']:<5} {p['qty']:>14.4f} "
                  f"{p['entry']:>14.4f} {p['broker']:<8} "
                  f"{p['attribution']:<9} {state}")
            w(f"   and {plat['paper_n']} paper row(s), counted apart")

        w("\n5. WHAT EACH BROKER SAYS IT HOLDS")
        for r in v["brokers"]:
            if r["held"] is None:
                w(f"   {r['name']}: {DASH} never read")
                continue
            w(f"   {r['name']} ({_age(r['held']['age_seconds'])} ago):")
            if not r["held"]["rows"]:
                w("      flat — measured, and zero")
            for h in r["held"]["rows"]:
                mark = h.get("market_price") or 0
                w(f"      {str(h.get('symbol')):<12} "
                  f"{str(h.get('side', '')):<5} "
                  f"{float(h.get('qty') or 0):>14.4f} @ "
                  f"{float(h.get('avg_cost') or 0):>12.4f}  "
                  f"mark {float(mark):>12.4f}  "
                  f"{h.get('currency') or ''}")

        w("\n6. DIVERGENCE — THE BROKER AGAINST THE PLATFORM")
        for d in v["divergence"]:
            if not d["known"]:
                w(f"   {d['name']}: {DASH} cannot be compared ({d['reason']}); "
                  f"{d['platform_n']} platform row(s) attributed to it")
                continue
            w(f"   {d['name']}: {len(d['agree'])} agree, "
              f"{len(d['only_broker'])} only at the broker, "
              f"{len(d['only_platform'])} only in the platform")
            for p in d["only_platform"]:
                w(f"      PLATFORM ONLY  {p['symbol']:<12} {p['side']:<5} "
                  f"{p['qty']:.4f}  ({p['config']})")
            for h in d["only_broker"]:
                w(f"      BROKER ONLY    {str(h.get('symbol')):<12} "
                  f"{str(h.get('side', '')):<5} "
                  f"{float(h.get('qty') or 0):.4f}")

        w("\n" + "=" * 78)
        if v["blockers"]:
            w("BLOCKERS — the platform and the money do not agree:")
            for i, m in enumerate(v["blockers"], 1):
                w(f"  {i}. {m}")
        else:
            w("NO BLOCKERS — every broker read agrees with the platform's own "
              "rows.")
        if v["notes"]:
            w("\nWORTH READING:")
            for i, m in enumerate(v["notes"], 1):
                w(f"  {i}. {m}")
        w("=" * 78)
        w("Cached columns only: this command makes no broker call and writes "
          "nothing. An em dash is never a zero.")
