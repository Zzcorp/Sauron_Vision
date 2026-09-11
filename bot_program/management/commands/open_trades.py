"""Every position the bots hold, with the platform's own mark on it.

One line per open trade: which config opened it, paper or LIVE, side,
size, entry, stop, target, the last price Sauron knows, the unrealised
P&L and R against the stop, how long it has been open, and which rule
fired. A trade without a stop is flagged — that is exposure with no
exit. Two sources: the asset bots (AssetBotTrade) and the legacy crypto
bot (BotTrade, Binance) — the Solana position lived in the second and
the first cut of this command did not look there. Read-only: it writes
nothing and touches no broker.

    python manage.py open_trades
    python manage.py open_trades --symbol SOL
    python manage.py open_trades --all      # closed rows of the last 7 days too
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")
FX_QUOTES = ("USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "ZAR",
             "USDT", "USDC", "BUSD")


def num(d) -> str:
    """A Decimal as people write it: 200, 190.5, 0.00012 — never 2E+2."""
    if d is None:
        return "-"
    s = format(Decimal(str(d)), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def quote_of(symbol: str) -> str:
    """The currency a P&L on `symbol` is counted in, when the symbol says
    so: EURJPY -> JPY, SOLUSDT -> USDT, GBPUSD -> USD. '' otherwise — a
    stock's P&L is in the stock's currency, which the row does not carry."""
    s = (symbol or "").upper()
    for q in sorted(FX_QUOTES, key=len, reverse=True):
        if s.endswith(q) and len(s) > len(q):
            return q
    return ""


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
        from bot_program.models import BotTrade

        since = timezone.now() - timedelta(days=7)

        def _select(qs):
            if opts["all"]:
                qs = qs.filter(status__in=OPEN_STATUSES) | qs.filter(
                    closed_at__gte=since)
            else:
                qs = qs.filter(status__in=OPEN_STATUSES)
            if opts["symbol"]:
                qs = qs.filter(symbol__icontains=opts["symbol"])
            return list(qs.order_by("paper", "-opened_at"))

        rows = [(t, False) for t in _select(
            AssetBotTrade.objects.select_related("config"))]
        rows += [(t, True) for t in _select(
            BotTrade.objects.select_related("config"))]
        if not rows:
            self.stdout.write("no open positions")
            return

        now = timezone.now()
        n_live = n_paper = 0
        for t, legacy in rows:
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
            where = (f"[legacy] {cfg.name} (crypto/{cfg.mode})" if legacy
                     else f"[{cfg.pk}] {cfg.name} ({cfg.asset_class}/{cfg.mode})")
            self.stdout.write(f"#{t.pk:<5} {lane} {t.status:<13} {where}")
            self.stdout.write(
                f"       {t.side} {num(t.qty)} {t.symbol} @ {num(t.entry_price)}"
                f"  stop {num(t.stop_loss) if t.stop_loss is not None else 'NO STOP'}"
                f"  target {num(t.take_profit)}")
            q = quote_of(t.symbol)
            mark_s = f"{mark:g}" if mark is not None else "no mark"
            pnl_s = (f"{float(pnl):+.2f}" + (f" {q}" if q else "")
                     if pnl is not None else "-")
            r_s = f"{r:+.2f}R" if r is not None else "-"
            when = (f"open {age_h:.1f}h" if is_open
                    else f"closed {t.closed_at:%m-%d %H:%M}" if t.closed_at
                    else t.status.lower())
            rule = "-" if legacy else (t.rule_name or "-")
            self.stdout.write(
                f"       mark {mark_s}  unrealised {pnl_s}  {r_s}  {when}"
                f"  rule {rule}")
            if t.stop_loss is None and is_open:
                self.stdout.write(self.style.WARNING(
                    "       NO STOP on this position — exposure with no exit"))
            if t.reason:
                self.stdout.write(f"       why: {t.reason.strip()[:160]}")
        self.stdout.write(f"\n{n_live} live, {n_paper} paper open")
