"""Every open legacy portfolio.Position row, by symbol, with where it came
from and how old it is (2026-10-31).

These rows predate the bots' AssetBotTrade table. They are written by the
/setup/ eToro sync button (the shared "Main" book), the /setup/ 'add
position' form and the chat trader (the user's own `<username>_main`
book), and no bot or reconcile closes one (the chat trader's 'close' and
the kill switch close `<username>_main` rows). The duplicate rule counts
every open one as a REAL-MONEY holder of its symbol and side, so a
forgotten row blocks the bots on that symbol and side and puts a warning
on the TAKE TRADE ticket for as long as it stays open. open_trades does
not list them; this does.

Read-only: it writes nothing and touches no broker. A row eToro no longer
holds is closed by hand on its admin page (set "Closed at", or delete the
row there), printed on each line; the page closes a row with no stop or
target too (portfolio.admin, 2026-10-31).

    python manage.py legacy_positions
    python manage.py legacy_positions --symbol AAPL
    python manage.py legacy_positions --user <username>
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("List open legacy portfolio.Position rows by symbol, with their "
            "book, the writer that can have made them, their age and the "
            "page that closes them. Read-only.")

    def add_arguments(self, parser):
        parser.add_argument("--symbol", default="",
                            help="only this symbol")
        parser.add_argument("--user", default="",
                            help="only the books this user's gates read "
                                 "(the shared Main book and <user>_main)")

    def handle(self, *args, **opts):
        from portfolio.models import Position
        from portfolio.risk_gate import legacy_position_words

        rows = (Position.objects.filter(closed_at__isnull=True)
                .select_related("portfolio", "instrument", "strategy")
                .order_by("instrument__symbol", "opened_at", "pk"))
        if opts["symbol"]:
            rows = rows.filter(instrument__symbol__iexact=opts["symbol"])
        if opts["user"]:
            from django.contrib.auth import get_user_model
            user = get_user_model().objects.filter(
                username=opts["user"]).first()
            if user is None:
                raise CommandError(f"no user {opts['user']!r}")
            rows = rows.filter(portfolio__name__in=(
                "Main", f"{user.username}_main"))
        rows = list(rows)
        out = self.stdout
        if not rows:
            out.write("No open legacy portfolio position: nothing here "
                      "counts as a holder in the duplicate rule.")
            return
        out.write(f"{len(rows)} open legacy portfolio position(s). Each "
                  f"counts as a real-money holder of its symbol and side in "
                  f"the duplicate rule (bots refused, the ticket warned).")
        symbol = None
        for pos in rows:
            sym = str(pos.instrument.symbol or "").upper()
            if sym != symbol:
                symbol = sym
                out.write("")
                out.write(sym)
            w = legacy_position_words(pos)
            age = ("?" if w["age_days"] is None else f"{w['age_days']}d")
            strategy = getattr(pos.strategy, "name", "") or "-"
            out.write(f"  #{pos.pk:<6} {str(pos.direction or '').lower():<5} "
                      f"qty {pos.quantity} @ {pos.entry_price}  "
                      f"book {w['book']}  age {age}  strategy {strategy}")
            out.write(f"          written by {w['origin']}; close it at "
                      f"{w['remove_at']} (set Closed at, or delete the row "
                      f"there)")
