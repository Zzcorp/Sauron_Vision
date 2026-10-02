"""The smart money, from the shell (2026-10-02).

    python manage.py smart_money                     # switch, VIX curve, what it did
    python manage.py smart_money read EURUSD BUY     # what it says about an entry now
    python manage.py smart_money cot                 # the COT index of every mapped symbol
    python manage.py smart_money cot-backfill        # 3 years of COT history (plan)
    python manage.py smart_money cot-backfill --yes  # ... download and store it

`read` prices the entry at the last 4h close and takes the stop and the
target from a bot config that trades the symbol (its own levels), or
from the default ATR levels when none does. Nothing is sent, nothing is
stored. `cot-backfill --years N` takes N years before this one (3 by
default). The switch is `smart_money` (manage.py component on
smart_money): OFF, the bots ignore everything this prints.
"""
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "The smart money: crowd stops, sweeps, COT positioning."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status",
                            choices=["status", "read", "cot", "cot-backfill"])
        parser.add_argument("params", nargs="*")
        parser.add_argument("--yes", action="store_true")
        parser.add_argument("--years", type=int, default=3)
        parser.add_argument("--days", type=int, default=1)

    def handle(self, *args, **o):
        getattr(self, "_" + o["action"].replace("-", "_"))(o)

    def _status(self, o):
        from bot_program.smart_money import summary_lines
        for line in summary_lines(days=max(1, o["days"])):
            self.stdout.write(line)

    def _config_for(self, symbol, cls):
        from bot_program.asset_models import AssetBotConfig
        rows = list(AssetBotConfig.objects.all())
        for cfg in sorted(rows, key=lambda c: c.mode != "live"):
            if symbol in (cfg.symbols or []):
                return cfg
        for cfg in sorted(rows, key=lambda c: c.mode != "live"):
            if cfg.asset_class == cls:
                return cfg
        return SimpleNamespace(asset_class=cls, extras={},
                               stop_loss_pct=1.5, take_profit_pct=3.0)

    def _read(self, o):
        if len(o["params"]) != 2 or o["params"][1].upper() not in ("BUY", "SELL"):
            raise CommandError("usage: smart_money read SYMBOL BUY|SELL")
        symbol, side = o["params"][0].upper(), o["params"][1].upper()
        from bot_program import smart_money as sm
        from bot_program.asset_engine.risk_levels import (
            _extras, max_stop_distance, stop_and_target,
        )
        from instruments.models import Instrument
        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            raise CommandError(f"no instrument {symbol}")
        df, swings = sm._bars(symbol, sm.TIMEFRAME)
        if df is None or not len(df):
            raise CommandError(f"no {sm.TIMEFRAME} bars for {symbol}")
        price = float(df["close"].iloc[-1])
        cfg = self._config_for(symbol, inst.asset_class)
        stop, target, meta = stop_and_target(cfg, symbol, price, side)
        room = max_stop_distance(cfg, symbol, price, target)
        read = sm.entry_read(
            symbol, side, price, stop, atr=meta.get("atr"),
            asset_class=getattr(cfg, "asset_class", inst.asset_class),
            timeframe=_extras(cfg).get("atr_timeframe") or sm.TIMEFRAME,
            bars=(df, swings), max_distance=room)
        self.stdout.write(
            f"{symbol} {side} at {price:g} (last {sm.TIMEFRAME} close) · "
            f"levels from {getattr(cfg, 'name', None) or 'the defaults'}")
        self.stdout.write(f"  stop {stop:g} -> {read['stop']:g}"
                          + (" (moved)" if read["moved"] else "")
                          + f" · target {target:g}")
        self.stdout.write(f"  real-money size x{read['scale']:g}")
        for why in read["why"]:
            self.stdout.write(f"  · {why}")
        if not sm.is_on():
            self.stdout.write("  (switch OFF: the bots do none of this; "
                              "manage.py component on smart_money)")

    def _cot(self, o):
        from bot_program.smart_money import COT_MIN_WEEKS, cot_read
        from scraping.scrapers.cot_reports import MARKET_NAME_MAP
        for symbol in sorted(set(MARKET_NAME_MAP.values())):
            r = cot_read(symbol, "BUY")
            if r["spec_index"] is None and r["comm_index"] is None:
                self.stdout.write(f"  {symbol:<12} {r['why']}")
                continue
            self.stdout.write(
                f"  {symbol:<12} speculators {r['spec_index']} · commercials "
                f"{r['comm_index']} · {r['weeks']} weeks to "
                f"{r.get('report_date', '?')} · a BUY: x{r['scale']:g}")
        self.stdout.write(f"(COT index 0-100 against 3 years; "
                          f"{COT_MIN_WEEKS} weeks needed)")

    def _cot_backfill(self, o):
        years = max(1, min(int(o["years"]), 10))
        if not o["yes"]:
            self.stdout.write(
                f"PLAN: download the CFTC legacy archives for the last "
                f"{years} years and this one, and store every mapped "
                f"market's weeks (a re-run changes nothing). --yes runs it.")
            return
        from scraping.scrapers.cot_reports import backfill_cot_history
        out = backfill_cot_history(years)
        self.stdout.write(
            f"years {out['years'] or '-'} · parsed {out['parsed']} · stored "
            f"{out['stored']} ({out['created']} new)"
            + (f" · FAILED {out['failed']}" if out["failed"] else "")
            + (f" · no instrument row for {', '.join(out['missing_instruments'])}"
               if out["missing_instruments"] else ""))
