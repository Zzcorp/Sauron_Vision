"""Multi-timeframe SMC scan with HTF confluence boost."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Scan a symbol across multiple timeframes with HTF confluence."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--timeframes", default="1h,4h,1d",
                            help="Comma-separated list, e.g. 1h,4h,1d")
        parser.add_argument("--bars", type=int, default=500)
        parser.add_argument("--persist", action="store_true")

    def handle(self, *args, **opts):
        from signals.mtf import scan_symbol_mtf
        from signals.rules.smc_rules import persist_cards
        from signals.explain.formatter import render_terminal_card

        timeframes = [tf.strip() for tf in opts["timeframes"].split(",")]
        cards = scan_symbol_mtf(opts["symbol"], timeframes=timeframes, bars=opts["bars"])

        if not cards:
            self.stdout.write(self.style.WARNING(
                f"No setups found for {opts['symbol']} across {timeframes}"
            ))
            return

        for c in cards:
            self.stdout.write(render_terminal_card(c))
            extra = []
            if c.get("htf_agrees"):
                extra.append(self.style.SUCCESS(
                    f"  HTF {c['htf_timeframe']} ({c['htf_trend']}) agrees"
                ))
            elif c.get("htf_trend") in ("up", "down"):
                extra.append(self.style.ERROR(
                    f"  HTF {c['htf_timeframe']} ({c['htf_trend']}) conflicts"
                ))
            for line in extra:
                self.stdout.write(line)
            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS(
            f"Found {len(cards)} setup(s) for {opts['symbol']} across {timeframes}"
        ))

        if opts["persist"]:
            count = 0
            for tf in timeframes:
                tf_cards = [c for c in cards if c["timeframe"] == tf]
                if tf_cards:
                    persist_cards(tf_cards, opts["symbol"], tf)
                    count += len(tf_cards)
            self.stdout.write(self.style.SUCCESS(
                f"Persisted {count} signal cards"
            ))
