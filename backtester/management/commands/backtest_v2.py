"""CLI runner for backtester v2 — drives the bot strategy code path."""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Run a backtest using the v2 engine that drives the bot's actual decide() function."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", required=True,
                            help="Comma-separated symbol list, e.g. BTCUSDT,ETHUSDT")
        parser.add_argument("--timeframe", default="4h")
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--capital", type=float, default=10_000.0)
        parser.add_argument("--position-pct", type=float, default=5.0)
        parser.add_argument("--max-positions", type=int, default=4)
        parser.add_argument("--leverage", type=float, default=1.0)
        parser.add_argument("--futures", action="store_true")
        parser.add_argument("--trail-pct", type=float, default=0.0)
        parser.add_argument("--persist", action="store_true")
        parser.add_argument("--name", default="")

    def handle(self, *args, **opts):
        from signals.smc.dataframe import load_ohlcv
        from backtester.engine_v2 import BacktestEngineV2

        symbols = [s.strip() for s in opts["symbol"].split(",")]
        bars = max(300, opts["days"] * 24 // 4 if opts["timeframe"] == "4h" else opts["days"] * 24)

        dataframes = {}
        for sym in symbols:
            df = load_ohlcv(sym, opts["timeframe"], bars=bars)
            if df is None or len(df) < 50:
                self.stdout.write(self.style.WARNING(f"  no data for {sym}"))
                continue
            dataframes[sym] = df
            self.stdout.write(f"  loaded {sym}: {len(df)} bars")

        if not dataframes:
            self.stdout.write(self.style.ERROR("No data loaded; aborting."))
            return

        engine = BacktestEngineV2(
            initial_capital=opts["capital"],
            position_size_pct=opts["position_pct"],
            max_concurrent=opts["max_positions"],
            leverage=opts["leverage"],
            is_futures=opts["futures"],
        )
        self.stdout.write(self.style.SUCCESS(f"Running backtest on {len(dataframes)} symbols..."))
        result = engine.run(dataframes, trail_pct=opts["trail_pct"])

        m = result["metrics"]
        self.stdout.write("")
        self.stdout.write("=" * 64)
        self.stdout.write(f"  Backtest results — {','.join(symbols)} ({opts['timeframe']})")
        self.stdout.write("=" * 64)
        for k, v in m.items():
            self.stdout.write(f"  {k:24s} {v}")
        self.stdout.write(f"  final_capital            {result['final_capital']}")
        self.stdout.write("=" * 64)

        if opts["persist"]:
            from backtester.models_v2 import BacktestRunV2, hash_config
            cfg = {
                "symbols": symbols, "timeframe": opts["timeframe"],
                "days": opts["days"], "capital": opts["capital"],
                "position_pct": opts["position_pct"],
                "max_positions": opts["max_positions"],
                "leverage": opts["leverage"], "futures": opts["futures"],
                "trail_pct": opts["trail_pct"],
            }
            run = BacktestRunV2.objects.create(
                name=opts["name"] or f"{','.join(symbols)} {opts['timeframe']}",
                config_hash=hash_config(cfg),
                config=cfg,
                symbols=symbols,
                initial_capital=opts["capital"],
                final_capital=result["final_capital"],
                total_return_pct=m.get("total_return_pct", 0),
                max_drawdown_pct=m.get("max_drawdown_pct", 0),
                sharpe=m.get("sharpe"),
                sortino=m.get("sortino"),
                calmar=m.get("calmar"),
                profit_factor=m.get("profit_factor"),
                win_rate=m.get("win_rate", 0),
                n_trades=m.get("n_trades", 0),
                expectancy_r=m.get("expectancy_R", 0),
                metrics=m,
                trades=[t.__dict__ for t in result["trades"]],
                equity_curve=result["equity_curve"][-500:],
            )
            self.stdout.write(self.style.SUCCESS(f"Persisted as BacktestRunV2 #{run.id} (hash {run.config_hash})"))
