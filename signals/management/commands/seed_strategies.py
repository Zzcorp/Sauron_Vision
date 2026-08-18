"""Phase-31 — seed a starter pack of OpportunitySetup + RuleControl rows.

Six pre-built strategies covering common patterns: trend-following,
mean-reversion, breakout, news-driven, volatility regime, and a
multi-modal cross-asset macro setup.

Each is created in `RuleControl` at stage="research" with weight=1.0 so
they go through the Phase-8 promotion pipeline before any live sizing.

Run with:
    python manage.py seed_strategies              # idempotent — safe to re-run
    python manage.py seed_strategies --activate   # also activate them in scanner
    python manage.py seed_strategies --reset      # remove the seeded rules

Designed to be safe: only touches setups whose `name` starts with the
`SEED_PREFIX` so user-created setups are never modified.
"""
from django.core.management.base import BaseCommand


SEED_PREFIX = "starter_"


def _setup_definitions() -> list[dict]:
    """The six starter strategies. Edit here to add more."""
    return [
        # ── 1. Momentum / trend-following on stocks ─────────────────────
        {
            "name": "starter_stock_momentum",
            "description": (
                "Trend-following on equities: price above 20-period MA "
                "AND breakout above 60-bar high. Confirmation via positive "
                "macro_trend on US economic indicators."
            ),
            "direction": "bullish",
            "asset_classes": ["stock", "etf"],
            "conditions": [
                {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 20},
                 "weight": 1.0},
                {"kind": "price_pattern",
                 "params": {"pattern": "breakout_high", "lookback": 60},
                 "weight": 1.5},
                {"kind": "macro_trend",
                 "params": {"indicator": "GDP", "direction": "rising",
                              "lookback_quarters": 2},
                 "weight": 0.5},
            ],
            "min_match_score": 0.65,
            "suggested_horizon_days": 10,
            "sizing": {"stop_pct": 3.0, "target_pct": 6.0},
        },

        # ── 2. Mean-reversion on stocks ─────────────────────────────────
        {
            "name": "starter_stock_mean_reversion",
            "description": (
                "Counter-trend: price below 20-period MA + bearish "
                "volatility_regime (oversold). Bias bullish on the bounce."
            ),
            "direction": "bullish",
            "asset_classes": ["stock", "etf"],
            "conditions": [
                {"kind": "price_pattern",
                 "params": {"pattern": "below_ma", "ma_period": 20},
                 "weight": 1.0},
                {"kind": "volatility_regime",
                 "params": {"regime": "elevated"},
                 "weight": 0.8},
            ],
            "min_match_score": 0.60,
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 2.5, "target_pct": 5.0},
        },

        # ── 3. Forex breakout on session overlap ────────────────────────
        {
            "name": "starter_forex_breakout",
            "description": (
                "FX breakout: price breaks above 30-bar high. Pairs with the "
                "ForexBot's London/NY session filter (Phase 13.4) so entries "
                "fire only during liquid hours."
            ),
            "direction": "bullish",
            "asset_classes": ["forex"],
            "conditions": [
                {"kind": "price_pattern",
                 "params": {"pattern": "breakout_high", "lookback": 30},
                 "weight": 1.5},
                {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 50},
                 "weight": 1.0},
            ],
            "min_match_score": 0.70,
            "suggested_horizon_days": 3,
            "sizing": {"stop_pct": 1.0, "target_pct": 2.5},
        },

        # ── 4. News-driven event play ───────────────────────────────────
        {
            "name": "starter_news_event_bullish",
            "description": (
                "High-volume bullish news + sentiment confirmation. Best for "
                "stocks with single-name catalysts (earnings beat, upgrades)."
            ),
            "direction": "bullish",
            "asset_classes": ["stock"],
            "conditions": [
                {"kind": "news_volume",
                 "params": {"hours": 24, "min_articles": 3},
                 "weight": 1.0},
                {"kind": "news_sentiment",
                 "params": {"hours": 24, "min_score": 0.4},
                 "weight": 1.5},
                {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 10},
                 "weight": 0.5},
            ],
            "min_match_score": 0.70,
            "suggested_horizon_days": 3,
            "sizing": {"stop_pct": 4.0, "target_pct": 8.0},
        },

        # ── 5. Volatility-regime contraction (commodity) ────────────────
        {
            "name": "starter_commodity_vol_compression",
            "description": (
                "Commodities exiting a low-vol regime tend to trend. "
                "Look for normal regime + price above MA as the breakout sets up."
            ),
            "direction": "bullish",
            "asset_classes": ["commodity"],
            "conditions": [
                {"kind": "volatility_regime",
                 "params": {"regime": "low"},
                 "weight": 1.5},
                {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 30},
                 "weight": 1.0},
            ],
            "min_match_score": 0.65,
            "suggested_horizon_days": 14,
            "sizing": {"stop_pct": 5.0, "target_pct": 12.0},
        },

        # ── 6. Macro-driven cross-asset (USD-weakness composite) ────────
        {
            "name": "starter_usd_weakness_macro",
            "description": (
                "Composite USD-weakness setup: dovish macro_regime on US + "
                "rising COT non-commercial euro longs. Bias bullish on EUR/USD, "
                "gold, and other USD-shorts."
            ),
            "direction": "bullish",
            "asset_classes": ["forex", "commodity"],
            "conditions": [
                {"kind": "macro_regime",
                 "params": {"region": "US", "regime": "dovish"},
                 "weight": 1.5},
                {"kind": "cot_report",
                 "params": {"category": "non_commercial",
                              "position": "long_increasing"},
                 "weight": 1.0},
            ],
            "min_match_score": 0.70,
            "suggested_horizon_days": 21,
            "sizing": {"stop_pct": 2.0, "target_pct": 6.0},
        },
    ]


def seed_setups(*, activate: bool = False) -> dict:
    """Idempotent upsert of starter setups + corresponding RuleControl rows.

    Returns counts: {created, updated, rules_created, rules_updated}.
    """
    from signals.models_opportunity import OpportunitySetup
    from signals.models_control import RuleControl

    created = updated = rules_created = rules_updated = 0
    for spec in _setup_definitions():
        defaults = {
            "description": spec["description"],
            "direction": spec["direction"],
            "asset_classes": spec["asset_classes"],
            "conditions": spec["conditions"],
            "min_match_score": spec["min_match_score"],
            "suggested_horizon_days": spec["suggested_horizon_days"],
            "sizing": spec.get("sizing", {}),
        }
        # is_active is the OPERATOR's field once the row exists: a re-run
        # without --activate used to silently disarm setups someone had
        # switched on by hand. Only --activate asserts it on updates; a
        # fresh row starts at the flag's value (default: off, on purpose).
        if activate:
            defaults["is_active"] = activate
        obj, was_created = OpportunitySetup.objects.update_or_create(
            name=spec["name"], defaults=defaults,
        )
        if was_created:
            if not activate:
                OpportunitySetup.objects.filter(pk=obj.pk).update(
                    is_active=False)
            created += 1
        else:
            updated += 1

        # Companion RuleControl entry — research stage, no live sizing yet.
        rule, rule_was_created = RuleControl.objects.update_or_create(
            rule_name=spec["name"],
            defaults={
                "status": "active",
                "weight_multiplier": 1.0,
                "allocator_weight": 1.0,
                "promotion_stage": "research",
                "notes": (f"Seeded by Phase-31 starter pack. "
                            f"{spec['description'][:80]}..."),
                "parameters": {
                    "asset_classes": spec["asset_classes"],
                    "min_match_score": spec["min_match_score"],
                    "horizon_days": spec["suggested_horizon_days"],
                },
            },
        )
        if rule_was_created:
            rules_created += 1
        else:
            rules_updated += 1
    return {
        "created": created, "updated": updated,
        "rules_created": rules_created, "rules_updated": rules_updated,
        "total": len(_setup_definitions()),
    }


def reset_setups() -> dict:
    """Remove all seeded starter setups + their RuleControl entries."""
    from signals.models_opportunity import OpportunitySetup
    from signals.models_control import RuleControl

    s_count, _ = OpportunitySetup.objects.filter(
        name__startswith=SEED_PREFIX).delete()
    r_count, _ = RuleControl.objects.filter(
        rule_name__startswith=SEED_PREFIX).delete()
    return {"setups_deleted": s_count, "rules_deleted": r_count}


class Command(BaseCommand):
    help = "Seed a starter pack of 6 OpportunitySetup + RuleControl rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--activate", action="store_true",
            help="Mark setups is_active=True so the scanner picks them up.",
        )
        parser.add_argument(
            "--reset", action="store_true",
            help="Remove all seeded setups + rules instead of creating them.",
        )

    def handle(self, *args, **opts):
        if opts["reset"]:
            r = reset_setups()
            self.stdout.write(self.style.SUCCESS(
                f"Reset done — removed {r['setups_deleted']} setups, "
                f"{r['rules_deleted']} rules."))
            return

        r = seed_setups(activate=opts["activate"])
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {r['total']} starter strategies — "
            f"{r['created']} created / {r['updated']} updated · "
            f"RuleControl: {r['rules_created']} created / {r['rules_updated']} updated · "
            f"is_active={opts['activate']}"))
        if not opts["activate"]:
            self.stdout.write(
                "  Setups are INACTIVE until you arm them: re-run with "
                "--activate, or toggle each on /opportunities/ "
                "(Intelligence → Opportunities).")
