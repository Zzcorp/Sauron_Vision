"""Manual scanner: print SMC setup cards for a symbol/timeframe."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Scan a symbol for SMC/ICT setups and print signal cards. Optionally persist."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", required=True,
                            help="Instrument symbol, e.g. BTCUSDT")
        parser.add_argument("--timeframe", default="4h",
                            help="Timeframe (default: 4h)")
        parser.add_argument("--bars", type=int, default=500,
                            help="Bars of history to scan (default: 500)")
        parser.add_argument("--persist", action="store_true",
                            help="Save detected cards to SmcSignal table")
        parser.add_argument("--synthetic", action="store_true",
                            help="Use synthetic OHLCV (skip DB) for smoke testing")

    def handle(self, *args, **opts):
        from signals.rules.smc_rules import scan_symbol, persist_cards
        from signals.explain.formatter import render_terminal_card

        df = None
        if opts["synthetic"]:
            from signals.smc.dataframe import synthetic_ohlcv
            df = synthetic_ohlcv(bars=opts["bars"])
            self.stdout.write(self.style.WARNING(
                "Using synthetic OHLCV (no DB). Detectors run end-to-end "
                "but setups depend on the random walk."
            ))

        cards = scan_symbol(
            opts["symbol"], opts["timeframe"], opts["bars"], df=df,
        )

        if not cards:
            self.stdout.write(self.style.WARNING(
                f"No setups found for {opts['symbol']} {opts['timeframe']}"
            ))
            return

        for c in cards:
            self.stdout.write(render_terminal_card(c))
            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS(
            f"Found {len(cards)} setup(s) for {opts['symbol']} {opts['timeframe']}"
        ))

        if opts["persist"] and not opts["synthetic"]:
            created = persist_cards(cards, opts["symbol"], opts["timeframe"])
            self.stdout.write(self.style.SUCCESS(
                f"Persisted {len(created)} signal cards to SmcSignal table"
            ))
        elif opts["persist"] and opts["synthetic"]:
            self.stdout.write(self.style.WARNING(
                "--persist ignored under --synthetic mode"
            ))
