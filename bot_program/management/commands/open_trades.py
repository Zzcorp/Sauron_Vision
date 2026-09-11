"""Every position the bots hold, with the platform's own mark on it.

One line per open trade: which config opened it, paper or LIVE, side,
size, entry, stop, target, the last price Sauron knows, the unrealised
P&L and R against the stop, how long it has been open, and which rule
fired. A trade without a stop is flagged — that is exposure with no
exit. Read-only: it writes nothing and touches no broker.

    python manage.py open_trades
    python manage.py open_trades --symbol SOL
    python manage.py open_trades --all      # closed rows of the last 7 days too
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")


def num(d) -> str:
    """A Decimal as people write it: 200, 190.5, 0.00012 — never 2E+2."""
    if d is None:
        return "-"
    s = format(Decimal(str(d)), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def unrealised(side, entry, stop, mark, qty):
    """(pnl, r) — pnl in quote currency, r against the stop, None when
    there is no mark or no stop distance."""
    if mark is None:
        return None, None
    sign = 1 if side == "BUY" else -1
    move = (Decimal(str(mark)) - entry) * sign
    pnl = move * qty
    if stop is None or stop == entry:
        return pnl, None
    risk = abs(entry - stop)
    return pnl, float(move / risk)


class Command(BaseCommand):
    help = "List the bots' open positions with mark, unrealised P&L and R."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", default="",
                            help="Only symbols containing this text.")
        parser.add_argument("--all", action="store_true",
                            help="Also show rows closed in the last 7 days.")

    def handle(self, *args, **opts):
        from ai_agents.calibration import mark_for_symbol
        from bot_program.asset_models import AssetBotTrade

        rows = AssetBotTrade.objects.select_related("config")
        if opts["all"]:
            since = timezone.now() - timedelta(days=7)
            rows = rows.filter(status__in=OPEN_STATUSES) | rows.filter(
                closed_at__gte=since)
        else:
            rows = rows.filter(status__in=OPEN_STATUSES)
        if opts["symbol"]:
            rows = rows.filter(symbol__icontains=opts["symbol"])
        rows = list(rows.order_by("paper", "-opened_at"))
        if not rows:
            self.stdout.write("no open positions")
            return

        now = timezone.now()
        n_live = n_paper = 0
        for t in rows:
            is_open = t.status in OPEN_STATUSES
            mark = mark_for_symbol(t.symbol) if is_open else (
                float(t.exit_price) if t.exit_price is not None else None)
            pnl, r = unrealised(t.side, t.entry_price, t.stop_loss, mark,
                                t.qty)
            if is_open:
                n_live += 0 if t.paper else 1
                n_paper += 1 if t.paper else 0
            cfg = t.config
            age_h = (now - t.opened_at).total_seconds() / 3600
            lane = "paper" if t.paper else "LIVE "
            self.stdout.write(
                f"#{t.pk:<5} {lane} {t.status:<13} [{cfg.pk}] {cfg.name} "
                f"({cfg.asset_class}/{cfg.mode})")
            self.stdout.write(
                f"       {t.side} {num(t.qty)} {t.symbol} @ {num(t.entry_price)}"
                f"  stop {num(t.stop_loss) if t.stop_loss is not None else 'NO STOP'}"
                f"  target {num(t.take_profit)}")
            mark_s = f"{mark:g}" if mark is not None else "no mark"
            pnl_s = f"{float(pnl):+.2f}" if pnl is not None else "-"
            r_s = f"{r:+.2f}R" if r is not None else "-"
            when = (f"open {age_h:.1f}h" if is_open
                    else f"closed {t.closed_at:%m-%d %H:%M}" if t.closed_at
                    else t.status.lower())
            self.stdout.write(
                f"       mark {mark_s}  unrealised {pnl_s}  {r_s}  {when}"
                f"  rule {t.rule_name or '-'}")
            if t.stop_loss is None and is_open:
                self.stdout.write(self.style.WARNING(
                    "       NO STOP on this position — exposure with no exit"))
            if t.reason:
                self.stdout.write(f"       why: {t.reason.strip()[:160]}")
        self.stdout.write(f"\n{n_live} live, {n_paper} paper open")
