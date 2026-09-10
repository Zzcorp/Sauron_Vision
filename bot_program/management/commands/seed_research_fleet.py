"""Seed the RESEARCH fleet — paper bots across the whole catalogue.

The learning engine grades what the fleet does: every closed paper trade
carries a realized R, every Signal on a scanned instrument resolves to an
outcome, and the promotion ladder counts both. By 2026-09-11 that engine
was fed by six starter configs on 35 symbols and three live pools on a
500 EUR account — fourteen trades in a week, four signals a day — while
the catalogue held 179 instruments with keyless bars and marks for most
of them. The ladder was starving on a full pantry.

    python manage.py seed_research_fleet                 # every keyless class
    python manage.py seed_research_fleet --budget 80     # fewer symbols
    python manage.py seed_research_fleet --dry-run       # print, write nothing
    python manage.py seed_research_fleet --reset         # remove the fleet

WHAT IT MAKES. One paper config per chunk of symbols per bot class —
research_stock_1, research_stock_2, research_forex_1 … — enabled, in
paper, with a paper pool large enough that sizing never rounds to zero
(100,000 by default; a research pool measures rules, not an account).
ETFs trade under the stock bot; indices, options and bonds have no bot
class or no keyless feed and are left out; the symbols the keyless feed
cannot serve (public_feed.YF_UNAVAILABLE) are skipped by name, and so is
any symbol already on another enabled config of the same user — two bots
voting on one symbol double-count its evidence.

WHY CHUNKS. A config holds at most `max_concurrent_positions` open trades
(5 by default), so one config over 60 symbols would produce five fills a
week however good the signals. Ten symbols a config keeps the paper fill
rate — the evidence the paper→live_small gate counts — proportional to
the universe, and keeps each config's skip counters readable.

THE BUDGET. Every enabled bot symbol costs one keyless download per bar
pass (ten minutes) and a place in the signal scan. The default budget of
150 symbols is filled round-robin across classes so no class is starved
when it binds, and the command prints what the fleet will cost per pass.

A re-run re-asserts only `symbols`, and only on configs it seeded that are
still in paper: a research config an operator promoted to live is theirs
now, and a config that merely wears the research_ name without the
research_fleet mark is never touched. `--reset` deletes seeded configs
that never traded and disables the ones that did — AssetBotTrade cascades
from its config, and the grading layer reads that history.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

RESEARCH_PREFIX = "research_"
DEFAULT_BUDGET = 150
DEFAULT_CHUNK = 10
DEFAULT_CAPITAL = Decimal("100000")

# Catalogue class -> the bot class that trades it. Absent here = no bot.
BOT_CLASS_FOR = {
    "stock": "stock", "etf": "stock", "forex": "forex",
    "commodity": "commodity", "crypto": "crypto",
}


def default_owner():
    """The first superuser, or None — the same default seed_bots uses."""
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(
        is_superuser=True).order_by("pk").first()


def research_universe(user, *, budget: int = DEFAULT_BUDGET) -> dict:
    """{bot_class: [symbols]} the fleet should cover, within `budget`.

    Active instruments with a bot class and a keyless feed, minus the
    symbols the feed cannot serve and the ones another enabled config of
    this user already trades, filled round-robin across classes.
    """
    from bot_program.models import AssetBotConfig
    from instruments.models import Instrument
    from market_data.public_feed import YF_UNAVAILABLE, public_feed_for

    covered = {
        s for cfg in (AssetBotConfig.objects
                      .filter(user=user, enabled=True)
                      .exclude(name__startswith=RESEARCH_PREFIX))
        for s in (cfg.symbols or []) if s
    }
    per_class: dict = {}
    for inst in (Instrument.objects.filter(is_active=True)
                 .order_by("asset_class", "symbol")):
        bot_class = BOT_CLASS_FOR.get(inst.asset_class)
        if bot_class is None:
            continue
        if inst.symbol in YF_UNAVAILABLE or inst.symbol in covered:
            continue
        if public_feed_for(inst.asset_class) is None:
            continue
        per_class.setdefault(bot_class, []).append(inst.symbol)
    # By symbol within a bot class, whatever catalogue class it came from:
    # an ETF and a stock share one bot, and a re-run must produce the same
    # chunks as the first.
    for symbols in per_class.values():
        symbols.sort()

    queues = {c: list(v) for c, v in per_class.items()}
    picked = {c: [] for c in per_class}
    total = 0
    while total < budget and any(queues.values()):
        for c in sorted(queues):
            if queues[c] and total < budget:
                picked[c].append(queues[c].pop(0))
                total += 1
    return {c: v for c, v in picked.items() if v}


def plan_configs(universe: dict, *, chunk: int = DEFAULT_CHUNK) -> list:
    """[(bot_class, name, symbols)] — the fleet as it will be written."""
    out = []
    for bot_class in sorted(universe):
        symbols = universe[bot_class]
        for i in range(0, len(symbols), chunk):
            out.append((bot_class,
                        f"{RESEARCH_PREFIX}{bot_class}_{i // chunk + 1}",
                        symbols[i:i + chunk]))
    return out


def seed_research_fleet(user, *, budget: int = DEFAULT_BUDGET,
                        chunk: int = DEFAULT_CHUNK,
                        capital: Decimal = DEFAULT_CAPITAL,
                        enabled: bool = True, dry_run: bool = False) -> dict:
    """Create or refresh the research fleet for `user`. Importable."""
    from bot_program.models import AssetBotConfig

    plan = plan_configs(research_universe(user, budget=budget), chunk=chunk)
    created = updated = 0
    left_alone: list = []
    if not dry_run:
        for bot_class, name, symbols in plan:
            cfg, was_created = AssetBotConfig.objects.get_or_create(
                user=user, asset_class=bot_class, name=name,
                defaults={"mode": "paper", "symbols": symbols,
                          "enabled": enabled, "capital": capital,
                          "base_currency": "USD",
                          "extras": {"research_fleet": True}})
            if was_created:
                created += 1
                continue
            if not (cfg.extras or {}).get("research_fleet"):
                left_alone.append(f"{name} (not seeded by this command)")
                continue
            if cfg.mode != "paper":
                left_alone.append(f"{name} (promoted to {cfg.mode})")
                continue
            if cfg.symbols != symbols:
                cfg.symbols = symbols
                cfg.save(update_fields=["symbols", "updated_at"])
                updated += 1
        # A research config the plan no longer names covers symbols that
        # moved elsewhere or fell out of the budget; it stands down rather
        # than keep voting on a universe the fleet no longer owns.
        planned = {name for _, name, _ in plan}
        stale = (AssetBotConfig.objects
                 .filter(user=user, name__startswith=RESEARCH_PREFIX,
                         mode="paper")
                 .exclude(name__in=planned))
        for cfg in stale:
            if not (cfg.extras or {}).get("research_fleet"):
                continue
            if cfg.trades.exists():
                cfg.enabled = False
                cfg.symbols = []
                cfg.save(update_fields=["enabled", "symbols", "updated_at"])
                left_alone.append(f"{cfg.name} (stood down, keeps its trades)")
            else:
                cfg.delete()
    symbols = sum(len(s) for _, _, s in plan)
    return {"plan": plan, "created": created, "updated": updated,
            "left_alone": left_alone, "symbols": symbols,
            "configs": len(plan)}


def reset_research_fleet(user) -> dict:
    """Remove the fleet — except configs that traded, which are disabled."""
    from bot_program.models import AssetBotConfig

    deleted = 0
    kept: list = []
    for cfg in AssetBotConfig.objects.filter(
            user=user, name__startswith=RESEARCH_PREFIX):
        if not (cfg.extras or {}).get("research_fleet"):
            continue
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
    help = ("Seed paper research bots across the whole keyless catalogue, "
            "so the promotion ladder has evidence to count.")

    def add_arguments(self, parser):
        parser.add_argument("--user", default="",
                            help="Owner username (default: first superuser).")
        parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                            help=f"Max symbols across the fleet "
                                 f"(default {DEFAULT_BUDGET}).")
        parser.add_argument("--chunk", type=int, default=DEFAULT_CHUNK,
                            help=f"Symbols per config (default "
                                 f"{DEFAULT_CHUNK}).")
        parser.add_argument("--capital", type=str,
                            default=str(DEFAULT_CAPITAL),
                            help="Paper pool per config.")
        parser.add_argument("--disabled", action="store_true",
                            help="Create the configs switched OFF.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Print the plan, write nothing.")
        parser.add_argument("--reset", action="store_true",
                            help="Remove the fleet (traded configs are "
                                 "disabled, not deleted).")

    def handle(self, *args, **opts):
        from django.contrib.auth import get_user_model

        user = None
        if opts["user"]:
            user = get_user_model().objects.filter(
                username=opts["user"]).first()
            if user is None:
                raise CommandError(f"no user named {opts['user']!r}")
        else:
            user = default_owner()
            if user is None:
                raise CommandError("no superuser exists — pass --user")

        if opts["reset"]:
            res = reset_research_fleet(user)
            self.stdout.write(f"Deleted {res['deleted']} research config(s)"
                              + (f"; kept (disabled, they traded): "
                                 f"{', '.join(res['kept'])}"
                                 if res["kept"] else ""))
            return

        budget, chunk = int(opts["budget"]), int(opts["chunk"])
        if budget <= 0 or chunk <= 0:
            raise CommandError("--budget and --chunk must be positive")
        try:
            capital = Decimal(str(opts["capital"]))
        except Exception:  # noqa: BLE001
            raise CommandError("--capital must be a number")
        if capital <= 0:
            raise CommandError("--capital must be positive")

        res = seed_research_fleet(user, budget=budget, chunk=chunk,
                                  capital=capital,
                                  enabled=not opts["disabled"],
                                  dry_run=opts["dry_run"])
        for bot_class, name, symbols in res["plan"]:
            self.stdout.write(f"  {name:<22} {bot_class:<10} "
                              f"{len(symbols):>3} symbols: "
                              f"{', '.join(symbols)}")
        verb = "would seed" if opts["dry_run"] else "seeded"
        self.stdout.write(self.style.SUCCESS(
            f"\nResearch fleet {verb}: {res['configs']} config(s), "
            f"{res['symbols']} symbols for {user.username} — "
            f"{res['created']} created, {res['updated']} refreshed."))
        if res["left_alone"]:
            self.stdout.write("Left alone: " + "; ".join(res["left_alone"]))
        self.stdout.write(
            f"Cost per bar pass (every 10 min): ~{res['symbols']} keyless "
            f"downloads, one per symbol (the 4h frame serves 1h). "
            f"Every symbol also joins the signal scan.")
        if not opts["dry_run"]:
            self.stdout.write(
                "Next: python manage.py backfill_bars --from-configs "
                "--intervals 1d,4h --bars 300   (a year of history at once, "
                "so every evaluator can compute from the first pass)")
