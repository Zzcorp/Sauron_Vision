"""Seed the wider paper fleet — forex, commodity and stock bots.

The platform's first trade was crypto because crypto was the only asset
class whose market data was free. That is no longer true: bars and marks
now come keylessly for forex, commodities, stocks and indices, so the only
remaining reason the fleet was one bot wide was that nobody had created
the configs. This command creates them.

    python manage.py seed_bots                  # create, DISABLED, paper
    python manage.py seed_bots --activate       # ...and switch them on
    python manage.py seed_bots --user zz        # attach to a named user
    python manage.py seed_bots --reset          # remove seeded configs

Everything lands in PAPER mode. A re-run re-asserts only `symbols` — never
`enabled` (the operator's decision), never `extras` (the safety engine
persists circuit-breaker state in there), and never `mode` (an operator may
have promoted a starter config to live through the PIN-gated HQ flow, and a
seed command silently demoting it would strand its open live trades behind
the paper-client refusal guard). Seeded configs are namespaced by the
"starter_" name prefix, so --reset never touches a config a human named.

`max_hold_hours` is left BLANK on purpose, which is not the same as leaving
it unset: blank inherits `AssetBotConfig.DEFAULT_MAX_HOLD_HOURS` for the
class, so every seeded bot has a real time stop from its first tick and
picks up any later correction to that table. Writing a number here instead
would freeze today's belief into the fleet and, on a re-run, would overwrite
whatever the operator had since tuned. The command prints the ceiling each
config ends up enforcing, because "the fleet has a time stop" is a claim
that should be checkable from the console rather than inferred.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

SEED_PREFIX = "starter_"

# (asset_class, name, symbols). Symbols use the catalogue's spelling —
# an unknown spelling gets zero bars forever AND routes to Binance as
# crypto, so every entry here must match seed_instruments exactly.
#
# JPY-quoted pairs are back: ForexBot._value_per_unit now converts the
# quote-currency stop distance into account currency, so USDJPY sizes to
# ~1,700 units instead of computing ~10 and rounding to zero.
FLEET = [
    ("forex", "starter_fx_majors",
     ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]),
    ("forex", "starter_fx_crosses",
     ["EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF", "GBPCHF"]),
    ("commodity", "starter_metals",
     ["XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "HGUSD"]),
    ("commodity", "starter_energy",
     ["WTIUSD", "BRNUSD", "NGUSD"]),
    ("commodity", "starter_softs",
     ["WHEATUSD", "CORNUSD", "SOYUSD", "COFFEEUSD", "SUGARUSD",
      "COCOAUSD", "COTTONUSD"]),
    ("stock", "starter_megacaps",
     ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]),
]


def default_owner():
    """The first superuser, or None. Nothing in the platform designates a
    bot owner, and the tick loop runs every enabled config regardless of
    owner — so the superuser is only a sensible default, not a rule."""
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(
        is_superuser=True).order_by("pk").first()


def seed_bots(user, *, activate: bool = False) -> dict:
    """Create or refresh the starter fleet for `user`. Importable on purpose."""
    from bot_program.models import AssetBotConfig
    from instruments.models import Instrument

    known = set(Instrument.objects.filter(
        symbol__in={s for _, _, syms in FLEET for s in syms},
    ).values_list("symbol", flat=True))

    created = updated = 0
    missing: set[str] = set()
    time_stops: list[str] = []
    for asset_class, name, symbols in FLEET:
        present = [s for s in symbols if s in known]
        missing.update(s for s in symbols if s not in known)
        if not present:
            continue
        cfg, was_created = AssetBotConfig.objects.get_or_create(
            user=user, asset_class=asset_class, name=name,
            defaults={"mode": "paper", "symbols": present, "enabled": False},
        )
        if was_created:
            created += 1
        else:
            # Re-assert only what the seed owns: the symbol list. `enabled`
            # belongs to the operator; `extras` belongs to the safety
            # engine; `mode` may have been promoted to live through the
            # PIN-gated HQ flow; `capital` and the sizing knobs may have
            # been tuned by hand.
            cfg.symbols = present
            cfg.save(update_fields=["symbols", "updated_at"])
            updated += 1
        if activate and not cfg.enabled:
            cfg.enabled = True
            cfg.save(update_fields=["enabled", "updated_at"])

        # Reported, never written. A seeded config with no time stop is the
        # one state this command must not create silently, so the number it
        # will actually enforce is surfaced rather than assumed.
        ts = cfg.time_stop_setting()
        time_stops.append(
            f"{cfg.name}: {ts['hours']:.0f}h ({ts['source']})"
            if ts["enabled"] else
            f"{cfg.name}: NO time stop ({ts['source']}) — unbounded in time")
    return {"created": created, "updated": updated,
            "missing_symbols": sorted(missing),
            "time_stops": time_stops}


def reset_bots(user) -> dict:
    """Remove seeded configs — except any that have traded. AssetBotTrade
    cascades from its config, so deleting a config that traded would erase
    the trade history the grading layer reads.

    A kept config is DISABLED. The keep-guard fires precisely when the bot
    has been trading — i.e. when it is enabled and on the 5-minute tick —
    and an operator running --reset is decommissioning the fleet, not
    asking for its history to keep opening positions."""
    from bot_program.models import AssetBotConfig

    deleted = 0
    kept: list[str] = []
    for cfg in AssetBotConfig.objects.filter(
            user=user, name__startswith=SEED_PREFIX):
        if cfg.trades.exists():
            if cfg.enabled:
                cfg.enabled = False
                cfg.save(update_fields=["enabled", "updated_at"])
            kept.append(cfg.name)
            continue
        cfg.delete()
        deleted += 1
    return {"deleted": deleted, "kept": kept}


class Command(BaseCommand):
    help = ("Seed the starter paper fleet (forex, commodity, stock bots). "
            "Idempotent; seeded configs are namespaced 'starter_'.")

    def add_arguments(self, parser):
        parser.add_argument("--user", type=str, default="",
                            help="Username to own the fleet "
                                 "(default: the first superuser)")
        parser.add_argument("--activate", action="store_true",
                            help="Enable the seeded bots so the 5-min tick "
                                 "picks them up")
        parser.add_argument("--reset", action="store_true",
                            help="Delete seeded configs that have never traded")

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        if options["user"]:
            user = get_user_model().objects.filter(
                username=options["user"]).first()
            if user is None:
                raise CommandError(f"No user named {options['user']!r}")
        else:
            user = default_owner()
            if user is None:
                raise CommandError(
                    "No superuser exists — run create_users first, or pass "
                    "--user <username>")

        if options["reset"]:
            out = reset_bots(user)
            for name in out["kept"]:
                self.stderr.write(self.style.WARNING(
                    f"  kept {name} (now disabled) — it has trades, and "
                    f"deleting the config would cascade into the trade "
                    f"history"))
            self.stdout.write(self.style.SUCCESS(
                f"Removed {out['deleted']} seeded bot config(s) for "
                f"{user.username}"))
            return

        out = seed_bots(user, activate=options["activate"])
        for sym in out["missing_symbols"]:
            self.stderr.write(self.style.WARNING(
                f"  {sym}: no Instrument row — run seed_instruments first; "
                f"the symbol was left out of its config"))
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {out['created'] + out['updated']} paper bot config(s) "
            f"for {user.username} — {out['created']} created / "
            f"{out['updated']} updated · enabled={options['activate']}"))
        if out["time_stops"]:
            self.stdout.write(
                "  Time stops (max hold before a stale position is closed "
                "with reason TIME — blank on the config means the "
                "asset-class default):")
            for line in out["time_stops"]:
                self.stdout.write(f"    {line}")
        if not options["activate"]:
            self.stdout.write(
                "  Nothing trades yet: enable the bots with --activate or "
                "from the HQ panel, and make sure the platform_master and "
                "pipeline_asset_bots components are on.")
        self.stdout.write(
            "  Bars arrive automatically within ~10 min of enabling: the "
            "bot-bar refresh reads each asset class's keyless public feed. "
            "Do NOT use backfill_bars for these — it is Binance-only, and "
            "asking it for EURUSD would write EUR/Tether candles into the "
            "forex instrument.")
