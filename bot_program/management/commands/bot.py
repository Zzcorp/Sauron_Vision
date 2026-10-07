"""Enable or disable an asset bot from the shell — the toggle on the
admin page, with the page's own rule.

The page asks the trading PIN to ARM a live bot and nothing to stop
one: stopping must stay frictionless. Here `--yes` plays the PIN's
role for arming a live config; `bot off` never asks. Read-only until
told otherwise; never touches the broker. A PAPER pool larger than the
book its owner set at /setup/ is not armed (2026-10-04,
risk_gate.pool_vs_book — research pools and live pools are exempt).

`bot off` is not a pause of entries alone: the runner skips a config
stopped by hand whole, so its open positions lose their time stop,
trailing and every platform-checked stop. It still never asks — it says
how many positions it left unmanaged (runner.unmanaged_on_disable,
2026-09-26).

WHO STOPPED IT (2026-10-07, asset_engine/disarm.py). Every stop is
recorded on the config, and `bot list` prints the record under each OFF
config. `bot off` records "`bot off` on the server"; `bot on` clears the
record and says whose stop it lifted. `bot brake` is the other stop: a
BRAKE, which opens nothing new and keeps managing what is open (the
runner runs its exits every tick while it holds an open row). It is the
way to put a config that was stopped before 2026-10-07, with no record,
back under management without re-arming its entries: it records such a
config as braked. Like `bot off`, it never asks.

    python manage.py bot list
    python manage.py bot off 1
    python manage.py bot brake 26 --why "the G1 brake of 2026-10-06"
    python manage.py bot on 6            # paper: writes; live: plan only
    python manage.py bot on 6 --yes      # live: writes
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("List, enable, disable or brake asset-bot configs (the page's "
            "toggle, as a command).")

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "on", "off", "brake"])
        parser.add_argument("ids", nargs="*", type=int)
        parser.add_argument("--yes", action="store_true",
                            help="Arm a LIVE config (the page asks the PIN for this).")
        parser.add_argument("--why", default="",
                            help="brake: the reason recorded on the config.")

    def handle(self, *args, **opts):
        from bot_program.asset_engine import disarm
        from bot_program.asset_engine.runner import unmanaged_on_disable
        from bot_program.asset_models import AssetBotConfig
        if opts["action"] == "list":
            rows = AssetBotConfig.objects.select_related("user").order_by("user_id", "pk")
            ticking = []
            for c in rows:
                state = "ON " if c.enabled else "OFF"
                self.stdout.write(
                    f"  {state}  [{c.pk:<3}] {c.name:<24} {c.asset_class:<9} {c.mode:<5} "
                    f"pool {c.capital} {c.base_currency}  symbols {len(c.symbols or [])}  "
                    f"({c.user.username})")
                if not c.enabled:
                    # Who stopped it, and whether what it holds is still
                    # managed (2026-10-07): a brake's stop is, while the
                    # bot tick runs (read once per listing).
                    managing = ""
                    if disarm.keeps_managing(c):
                        if not ticking:
                            ticking.append(self._tick_manages())
                        managing = ("; still managing" if ticking[0] else
                                    "; braked — the bot tick is off, "
                                    "nothing manages it now")
                    self.stdout.write(f"        {disarm.record_words(c)}"
                                      + managing)
            if not rows:
                self.stdout.write("no configs")
            return
        if not opts["ids"]:
            raise CommandError(f"bot {opts['action']}: give at least one config id "
                               f"(see `bot list`).")
        if opts["action"] == "brake":
            self._brake(opts)
            return
        enable = opts["action"] == "on"
        for pk in opts["ids"]:
            cfg = AssetBotConfig.objects.filter(pk=pk).first()
            if cfg is None:
                self.stdout.write(self.style.ERROR(f"[{pk}]: not found"))
                continue
            if cfg.enabled == enable:
                if enable:
                    self.stdout.write(f"[{pk}] {cfg.name}: already ON "
                                      f"(unchanged)")
                else:
                    # Who stopped it, so a `bot off` on a braked config
                    # reads why its positions are still managed: a hand
                    # stop never relabels a brake's (2026-10-07).
                    self.stdout.write(f"[{pk}] {cfg.name}: already OFF "
                                      f"(unchanged) — "
                                      f"{disarm.record_words(cfg)}")
                    self._warn_unmanaged(pk, unmanaged_on_disable(cfg))
                continue
            if enable and cfg.mode == "live" and not opts["yes"]:
                self.stdout.write(self.style.WARNING(
                    f"[{pk}] {cfg.name} is LIVE ({cfg.asset_class}, pool {cfg.capital} "
                    f"{cfg.base_currency}, {len(cfg.symbols or [])} symbols): arming it "
                    f"puts real money in play — the page asks the PIN here. Add --yes."))
                continue
            if enable:
                # A PAPER pool larger than its owner's book is not armed
                # (2026-10-04, risk_gate.pool_vs_book) — the page's toggles
                # refuse it the same way; stopping never asks.
                from portfolio.risk_gate import pool_vs_book
                pool = pool_vs_book(cfg)
                if not pool["ok"]:
                    self.stdout.write(self.style.ERROR(
                        f"[{pk}] {cfg.name}: not armed — {pool['reason']}"))
                    continue
            # THE WRITE (2026-10-07): through asset_engine.disarm, which
            # records this stop (or clears the record on the way back on).
            cleared = {}
            if enable:
                cleared = disarm.enable_config(cfg)
            else:
                disarm.disable_config(cfg, by=disarm.BY_BOT_OFF,
                                      why="bot off", who="shell")
            self.stdout.write(self.style.SUCCESS(
                f"[{pk}] {cfg.name} ({cfg.asset_class}/{cfg.mode}): "
                f"{'ENABLED' if enable else 'DISABLED'}"))
            if cleared:
                self.stdout.write(f"(the stop by "
                                  f"{disarm.BY_WORDS[cleared['by']]} is "
                                  f"cleared)")
            if not enable:
                self._warn_unmanaged(pk, unmanaged_on_disable(cfg))

    def _brake(self, opts):
        """`bot brake`: the server's own brake (2026-10-07). An enabled
        config is stopped and recorded as braked; one already off with no
        record (stopped before the record existed) is adopted as braked;
        one off with a record is left as found — a brake never relabels a
        stop it did not make. Never asks: stopping never does.

        THE RACE (2026-10-07): the config is read without a lock, so
        another stop (the kill switch, `bot off`, a toggle) can land
        between that read and disable_config's locked re-read. Then
        disable_config writes nothing, returns False and mirrors the
        winner's record onto cfg: that record is printed, never a STOPPED
        this command did not make. A brake's management rides the bot
        tick: with it off, the words say so."""
        from bot_program.asset_engine import disarm
        from bot_program.asset_models import AssetBotConfig
        why = opts.get("why") or "bot brake"
        promised = False
        for pk in opts["ids"]:
            cfg = AssetBotConfig.objects.filter(pk=pk).first()
            if cfg is None:
                self.stdout.write(self.style.ERROR(f"[{pk}]: not found"))
                continue
            if cfg.enabled:
                if disarm.disable_config(cfg, by=disarm.BY_BOT_BRAKE,
                                         why=why, who="shell"):
                    promised = True
                    self.stdout.write(self.style.SUCCESS(
                        f"[{pk}] {cfg.name}: STOPPED by `bot brake` on the "
                        f"server — its open positions stay managed; it "
                        f"opens nothing"))
                elif cfg.enabled:
                    # The row is gone: disable_config re-read nothing.
                    self.stdout.write(self.style.ERROR(f"[{pk}]: not found"))
                else:
                    # Lost the race: another stop landed first, and cfg
                    # now holds its record (disarm._mirror).
                    self.stdout.write(f"[{pk}] {cfg.name}: "
                                      f"{disarm.record_words(cfg)}; "
                                      f"unchanged")
            elif disarm.adopt_unrecorded(cfg, why=why, who="shell"):
                promised = True
                self.stdout.write(self.style.SUCCESS(
                    f"[{pk}] {cfg.name}: already OFF with no record — now "
                    f"recorded as a brake: its open positions are managed "
                    f"from the next tick"))
            else:
                self.stdout.write(f"[{pk}] {cfg.name}: "
                                  f"{disarm.record_words(cfg)}; unchanged")
        if promised and not self._tick_manages():
            from bot_program.telegram_eye import TICK_OFF_WORDS
            self.stdout.write(self.style.WARNING(TICK_OFF_WORDS))

    @staticmethod
    def _tick_manages() -> bool:
        """Whether the bot tick that runs a braked config's exits is on
        (manual_trade._tick_manages; it never raises)."""
        from bot_program.manual_trade import _tick_manages
        return _tick_manages()

    def _warn_unmanaged(self, pk, sentence):
        if sentence:
            self.stdout.write(self.style.WARNING(f"[{pk}] {sentence}"))
