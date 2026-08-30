"""Answer, in one pass, why the bots are not opening positions.

The question "why is Sauron not trading" has about nine possible answers
and they are spread across four apps: a master switch, a component row, a
beat that never registered, a config with no symbols, an instrument with
no bars, a gate that refuses every tick. Each one is individually easy to
check and collectively easy to miss, and several of them are SILENT — a
component with no row no-ops forever and reports nothing, and an enabled
config with an empty symbol list is reported GREEN by the health page.

Everything here is READ-ONLY. It writes nothing, places no order, and
touches no broker.

    python manage.py why_no_trade
    python manage.py why_no_trade --symbols 8
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Diagnose why the asset bots are not opening positions."

    def add_arguments(self, parser):
        parser.add_argument("--symbols", type=int, default=4,
                            help="How many symbols per config to detail.")

    def handle(self, *args, **opts):
        from datetime import timedelta

        from django.utils import timezone

        from bot_program.models import AssetBotConfig, AssetBotTrade
        from core.models import PlatformComponent
        from core.platform_control import is_component_enabled
        from market_data.models import PriceData
        from signals.models import Signal

        w = self.stdout.write
        per = max(1, int(opts["symbols"]))
        blockers = []

        w("=" * 66)
        w("WHY IS SAURON NOT TRADING")
        w("=" * 66)

        # ── 1. the switches, in the order they gate each other ──────────
        w("\n1. MASTER SWITCHES — any False stops everything below it")
        for key in ("platform_master", "pipeline_asset_bots",
                    "pipeline_signals", "scraper_prices"):
            row = PlatformComponent.objects.filter(key=key).first()
            try:
                on = is_component_enabled(key)
            except Exception as exc:            # noqa: BLE001
                on = f"ERR {exc}"
            if row is None:
                w(f"   {key:<22} NO ROW  — the gated task no-ops forever "
                  f"and leaves no trace")
                blockers.append(f"{key} has no PlatformComponent row "
                                f"(run: manage.py seed_components)")
                continue
            w(f"   {key:<22} {str(on):<6} last_run={row.last_run_at}")
            if on is False:
                blockers.append(f"{key} is OFF")

        # ── 2. the tick itself ──────────────────────────────────────────
        w("\n2. THE TICK — bots can only open from tick_all_asset_bots")
        row = PlatformComponent.objects.filter(
            key="pipeline_asset_bots").first()
        if row is not None:
            w(f"   enabled={row.is_enabled}  last_run={row.last_run_at}")
            msg = (getattr(row, "last_message", "") or "")[:220]
            if msg:
                w(f"   last message: {msg}")
            if row.last_run_at is None:
                blockers.append("tick_all_asset_bots has NEVER run — check "
                                "that beat and a worker are up")

        # ── 3. the configs ──────────────────────────────────────────────
        w("\n3. CONFIGS")
        cfgs = list(AssetBotConfig.objects.all().order_by("asset_class",
                                                          "name"))
        if not cfgs:
            w("   NONE — nothing can trade without one.")
            blockers.append("no AssetBotConfig rows exist")
        # TAKE TRADE's per-class config is enabled with an EMPTY symbol
        # list ON PURPOSE — `manual_config_for` creates it that way so it
        # manages hand-taken positions and never scans for its own. Flagging
        # it would send the operator to "fix" the one config that is
        # correct, which is how a diagnostic starts costing more than it
        # saves. `_config_error` treats symbols ON that config as the fault.
        from bot_program.manual_trade import MANUAL_CONFIG_NAME

        for c in cfgs:
            syms = list(c.symbols or [])
            manual = c.name == MANUAL_CONFIG_NAME
            note = "  (manual: manages, never scans)" if manual else ""
            w(f"   [{c.id}] {c.name[:18]:<18} {c.asset_class:<9} "
              f"mode={c.mode:<5} enabled={str(c.enabled):<5} "
              f"symbols={len(syms):<3} capital={c.capital}{note}")
            if c.enabled and not syms and not manual:
                w("        ^ ENABLED WITH NO SYMBOLS — opens nothing, and "
                  "the health page still calls it green")
                blockers.append(f"config {c.id} ({c.name}) is enabled with "
                                f"an empty symbol list")

        enabled = [c for c in cfgs if c.enabled]

        # ── 4. the refusals, which is usually the real answer ───────────
        w("\n4. WHY EACH ENABLED CONFIG DID NOT OPEN")
        w("   (cumulative skip counts — the bots record every refusal)")
        for c in enabled:
            ex = c.extras or {}
            counts = ex.get("skip_counts") or {}
            w(f"   [{c.id}] {c.name}")
            if not counts and c.name == MANUAL_CONFIG_NAME:
                w("        nothing to record — it scans no symbols by "
                  "design; its trades come from TAKE TRADE")
            elif not counts:
                w("        nothing recorded — the tick may never have "
                  "reached this config at all")
            for code, n in sorted(counts.items(), key=lambda kv: -int(kv[1])):
                w(f"        {code:<20} {n}")
            for sym, d in list((ex.get("skips") or {}).items())[:per]:
                if isinstance(d, dict):
                    w(f"        last {sym:<10} {d.get('code')}: "
                      f"{str(d.get('detail'))[:88]}")

        # ── 5. fuel ─────────────────────────────────────────────────────
        w("\n5. FUEL — a bot with no bars can never form a decision")
        starved = []
        for c in enabled:
            for sym in list(c.symbols or [])[:per]:
                n4 = PriceData.objects.filter(
                    instrument__symbol=sym, timeframe="4h").count()
                n1 = PriceData.objects.filter(
                    instrument__symbol=sym, timeframe="1d").count()
                w(f"   {sym:<12} 4h={n4:<6} 1d={n1}")
                if n4 == 0 and n1 == 0:
                    starved.append(sym)
        if starved:
            blockers.append("no bars at all for: " + ", ".join(starved[:8]))

        # ── 6. activity ─────────────────────────────────────────────────
        w("\n6. RECENT ACTIVITY")
        now = timezone.now()
        day, week = now - timedelta(days=1), now - timedelta(days=7)
        n_open = AssetBotTrade.objects.filter(
            status__in=("OPEN", "CLOSE_PENDING")).count()
        w(f"   active signals now  : "
          f"{Signal.objects.filter(is_active=True).count()}")
        w(f"   signals created 24h : "
          f"{Signal.objects.filter(created_at__gte=day).count()}")
        w(f"   trades opened 24h   : "
          f"{AssetBotTrade.objects.filter(opened_at__gte=day).count()}")
        w(f"   trades opened 7d    : "
          f"{AssetBotTrade.objects.filter(opened_at__gte=week).count()}")
        w(f"   open positions      : {n_open}")

        # ── the verdict ─────────────────────────────────────────────────
        w("\n" + "=" * 66)
        if blockers:
            w("BLOCKERS — fix in this order:")
            for i, b in enumerate(blockers, 1):
                w(f"  {i}. {b}")
        else:
            w("No structural blocker found. If nothing is opening, the")
            w("answer is in section 4: the bots are running and REFUSING.")
            w("A skip code is a decision, not a fault.")
        w("=" * 66)
