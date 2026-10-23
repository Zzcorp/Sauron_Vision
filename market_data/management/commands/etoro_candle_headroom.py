"""Measure eToro's candle headroom before the Orcs' 15m and 5m candles run
(spec §5.2a item 3, O1c; market_data/candle_headroom.py).

    python manage.py etoro_candle_headroom                     # a dry run: the plan, nothing sent
    python manage.py etoro_candle_headroom --yes               # run the ramp (demo, or quiet hours)
    python manage.py etoro_candle_headroom --yes --live        # ... on a live account
    python manage.py etoro_candle_headroom --yes --max-requests 40 --symbol EURUSD --symbol XAUUSD

The ramp asks 15m and 5m candles of 2 bars each with a gap that starts at
2 s and halves every 10 reads down to 0.25 s, and stops at eToro's first
429 or at the ceiling (60 by default). It records the clean rate, the rate
at the 429, eToro's quota headers and the tape's budget per bar pass. The
tape stays off until this record exists AND `orcs_tape` is ON. Refused on a
live account without --live, while eToro is sick, after a trading-lane 429
in the last two minutes, and while a bar pass or a Mercenary tape pass is
running. While it runs it holds the tape's lock; a bar pass that starts
ends it and nothing is recorded. Its reads are background reads: never
noted on the venue's health, so after its 429 it leaves a two-minute
marker every candle pass yields to.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Measure eToro's candle rate before its first 429 (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true",
                            help="run the ramp and record it")
        parser.add_argument("--live", action="store_true",
                            help="allow a live eToro account")
        parser.add_argument("--max-requests", type=int, default=None)
        parser.add_argument("--symbol", action="append", default=[],
                            help="a symbol to read (repeatable)")
        parser.add_argument("--user", default="",
                            help="whose eToro client (default: the owner "
                                 "of the oldest enabled config)")

    def _carrier(self, opts):
        from django.contrib.auth import get_user_model

        from bot_program.models import AssetBotConfig
        qs = AssetBotConfig.objects.select_related("user").order_by("id")
        if opts["user"]:
            user = get_user_model().objects.filter(
                username=opts["user"]).first()
            if user is None:
                raise CommandError(f"No user {opts['user']!r}.")
            qs = qs.filter(user=user)
        return qs.filter(enabled=True).first() or qs.first()

    def _symbols(self, opts):
        if opts["symbol"]:
            return [s.strip().upper() for s in opts["symbol"] if s.strip()]
        from market_data.bot_bars import _orc_board, _orc_tape_held
        syms = []
        for held in _orc_tape_held():
            syms.extend(s for s in held.symbols if s not in syms)
        for s in _orc_board():
            if s not in syms:
                syms.append(s)
        return syms

    def handle(self, *args, **opts):
        from market_data import candle_headroom as ch
        w = self.stdout.write
        max_req = int(opts["max_requests"] or ch.DEFAULT_MAX_REQUESTS)
        if max_req < 2:
            raise CommandError("--max-requests needs at least 2 reads.")
        symbols = self._symbols(opts)
        if not symbols:
            raise CommandError("No symbol to read: pass --symbol.")
        cfg = self._carrier(opts)
        try:
            client = ch.client_for(getattr(cfg, "user", None), symbols[0],
                                   cfg)
        except Exception as e:  # noqa: BLE001 — no client, nothing sent
            raise CommandError(f"No eToro client: {e}")
        world = ch.world_of(client) if client is not None else ""
        for line in ch.plan_words(world, symbols, max_req):
            w(line)
        if not world:
            raise CommandError("The client for these symbols is not "
                               "eToro's: nothing to measure.")
        if not opts["yes"]:
            w(f"A dry run: nothing was sent. With --yes the ramp asks at "
              f"most {max_req} candle reads.")
            return
        if world == "live" and not opts["live"]:
            raise CommandError("A live eToro account: run it on demo or in "
                               "quiet hours, and pass --live to measure on "
                               "the live account.")
        why = ch.refusing(world)
        if why:
            raise CommandError(f"Refused: {why}.")
        try:
            result = ch.run(client, symbols, max_requests=max_req)
        except Exception as e:  # noqa: BLE001 — a failed read is no measure
            raise CommandError(f"The ramp stopped on an error that is not a "
                               f"429 ({type(e).__name__}: {e}); nothing was "
                               f"recorded.")
        if result.get("aborted"):
            raise CommandError(f"The ramp stopped: {result['aborted']}; "
                               f"nothing was recorded. Run it again in a "
                               f"quiet minute.")
        rec = ch.record(result, world=world, symbols=symbols)
        if result["hit_429"]:
            w(f"eToro answered HTTP 429 after {result['requests']} clean "
              f"reads (about {result['at_429_per_min']} a minute at the "
              f"last gap).")
        else:
            w(f"No 429 in {result['requests']} reads (the ceiling).")
        w(f"Clean rate: {result['clean_per_min']} reads a minute; quota "
          f"headers: {result['headers'] or 'none'}.")
        w(f"Recorded: the tape may ask {rec['tape_per_pass']} candle reads "
          f"a bar pass. It runs once `manage.py component on orcs_tape`.")
