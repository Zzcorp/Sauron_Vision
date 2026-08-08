"""Phase 34-36 — seed advanced multi-modal strategies.

Six composite OpportunitySetups that demonstrate the new tradecraft, behavioral
and quantitative evaluators working together:

  1. advanced_smc_long           — liquidity sweep + FVG + RVOL (bullish)
  2. advanced_smc_short          — liquidity sweep + FVG + RVOL (bearish)
  3. advanced_capitulation_buy   — capitulation candle + crowd panic + Hurst mean-reverting
  4. advanced_blowoff_short      — parabolic exhaustion + crowd euphoric + RVOL
  5. advanced_news_fade          — bullish news + bearish price + narrative consensus
  6. advanced_smart_money_pivot  — COT divergence + bullish FVG + Hurst trending

Each composite combines one tradecraft pattern, one psychology pattern, and a
regime/quant filter — the way professional discretionary desks actually
structure trade theses.

All setups are seeded into RuleControl at stage='research' with weight=1.0 so
they go through the Phase-8 promotion pipeline before any live sizing.

Run:
    python manage.py seed_advanced_strategies              # idempotent
    python manage.py seed_advanced_strategies --activate   # also is_active=True
    python manage.py seed_advanced_strategies --reset      # delete the seeded rows
"""
from django.core.management.base import BaseCommand


SEED_PREFIX = "advanced_"


def _setup_definitions() -> list[dict]:
    return [
        # ── 1. Smart-money long: stop-hunt → imbalance → impulse ────────
        {
            "name": "advanced_smc_long",
            "description": (
                "Smart-Money long: a swing-low liquidity sweep PRINTS, a "
                "bullish FVG remains unfilled below current price, and "
                "the breakout candle prints with above-average volume. "
                "Classic 'sweep-and-reclaim' setup."
            ),
            "direction": "bullish",
            "asset_classes": ["stock", "etf", "forex", "crypto"],
            "conditions": [
                {"kind": "liquidity_sweep",
                 "params": {"direction": "bullish_sweep", "lookback": 20, "wick_pct": 0.3},
                 "weight": 1.5},
                {"kind": "fair_value_gap",
                 "params": {"direction": "bullish", "max_age": 5},
                 "weight": 1.0},
                {"kind": "relative_volume",
                 "params": {"period": 20, "threshold": 1.5},
                 "weight": 0.8},
            ],
            "min_match_score": 0.65,
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 1.5, "target_rr": 3.0},
        },

        # ── 2. Smart-money short: mirror-image of #1 ─────────────────────
        {
            "name": "advanced_smc_short",
            "description": (
                "Smart-Money short: swing-high liquidity sweep + bearish "
                "FVG above price + above-average volume on the rejection."
            ),
            "direction": "bearish",
            "asset_classes": ["stock", "etf", "forex", "crypto"],
            "conditions": [
                {"kind": "liquidity_sweep",
                 "params": {"direction": "bearish_sweep", "lookback": 20, "wick_pct": 0.3},
                 "weight": 1.5},
                {"kind": "fair_value_gap",
                 "params": {"direction": "bearish", "max_age": 5},
                 "weight": 1.0},
                {"kind": "relative_volume",
                 "params": {"period": 20, "threshold": 1.5},
                 "weight": 0.8},
            ],
            "min_match_score": 0.65,
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 1.5, "target_rr": 3.0},
        },

        # ── 3. Capitulation reversal long ────────────────────────────────
        {
            "name": "advanced_capitulation_buy",
            "description": (
                "Outsized red candle on outsized volume after a 5%+ multi-day "
                "decline (capitulation), confirmed by retail social sentiment "
                "at a panic extreme. Best when the asset's regime is "
                "mean-reverting (Hurst < 0.45)."
            ),
            "direction": "bullish",
            "asset_classes": ["stock", "etf", "crypto"],
            "conditions": [
                {"kind": "capitulation_detector",
                 "params": {"decline_bars": 5, "decline_min_pct": 5.0,
                            "body_z": 2.0, "vol_multiplier": 1.8, "window": 20},
                 "weight": 1.5},
                {"kind": "crowd_extreme",
                 "params": {"direction": "panic", "z_threshold": 1.5,
                            "window": 30, "lookback_days": 60},
                 "weight": 1.0},
                {"kind": "hurst_regime",
                 "params": {"regime": "mean_reverting", "lookback": 120},
                 "weight": 0.7},
            ],
            "min_match_score": 0.60,
            "suggested_horizon_days": 7,
            "sizing": {"stop_pct": 4.0, "target_rr": 2.5},
        },

        # ── 4. Parabolic blow-off short ──────────────────────────────────
        {
            "name": "advanced_blowoff_short",
            "description": (
                "Three or more accelerating up-candles + euphoric retail "
                "sentiment z-score + volume spike. Mean-reversion short "
                "into the exhaustion."
            ),
            "direction": "bearish",
            "asset_classes": ["stock", "etf", "crypto"],
            "conditions": [
                {"kind": "parabolic_exhaustion",
                 "params": {"direction": "exhaustion_up", "min_consecutive": 3},
                 "weight": 1.5},
                {"kind": "crowd_extreme",
                 "params": {"direction": "euphoric", "z_threshold": 1.5,
                            "window": 30, "lookback_days": 60},
                 "weight": 1.2},
                {"kind": "relative_volume",
                 "params": {"period": 20, "threshold": 2.0},
                 "weight": 0.8},
            ],
            "min_match_score": 0.65,
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 3.0, "target_rr": 2.0},
        },

        # ── 5. News-price fade (sell the rumor) ──────────────────────────
        {
            "name": "advanced_news_fade",
            "description": (
                "Bullish news flow + flat-to-down price (divergence) + "
                "narrative consensus already baked in (high article count, "
                "small price reaction). Smart money sold the news — fade."
            ),
            "direction": "bearish",
            "asset_classes": ["stock"],
            "conditions": [
                {"kind": "news_price_divergence",
                 "params": {"sentiment_dir": "bullish_news_bearish_price",
                            "lookback_days": 2, "min_articles": 3,
                            "min_sentiment": 0.3, "max_price_move_pct": 0.5},
                 "weight": 1.5},
                {"kind": "narrative_consensus",
                 "params": {"lookback_days": 5, "min_articles": 8,
                            "max_price_move_pct": 1.5},
                 "weight": 1.0},
                {"kind": "anchored_vwap_break",
                 "params": {"anchor_days_ago": 5, "direction": "below"},
                 "weight": 0.8},
            ],
            "min_match_score": 0.65,
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 2.5, "target_rr": 2.5},
        },

        # ── 6. Smart-money positioning pivot (futures/FX/commodities) ─────
        {
            "name": "advanced_smart_money_pivot",
            "description": (
                "COT non-commercials positioned OPPOSITE recent price slope "
                "(divergence) + bullish FVG remaining + price in a trending "
                "regime by Hurst. Trade with the smart money against retail "
                "momentum."
            ),
            "direction": "bullish",
            "asset_classes": ["forex", "commodity"],
            "conditions": [
                {"kind": "smart_money_divergence",
                 "params": {"slope_lookback": 20, "slope_threshold": 0.0005,
                            "min_ratio": 0.3},
                 "weight": 1.5},
                {"kind": "fair_value_gap",
                 "params": {"direction": "bullish", "max_age": 8},
                 "weight": 0.8},
                {"kind": "hurst_regime",
                 "params": {"regime": "trending", "lookback": 120},
                 "weight": 0.7},
            ],
            "min_match_score": 0.60,
            "suggested_horizon_days": 14,
            "sizing": {"stop_pct": 2.0, "target_rr": 3.0},
        },
    ]


def seed_setups(*, activate: bool = False) -> dict:
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
            "is_active": activate,
        }
        obj, was_created = OpportunitySetup.objects.update_or_create(
            name=spec["name"], defaults=defaults,
        )
        if was_created:
            created += 1
        else:
            updated += 1

        rule, rule_was_created = RuleControl.objects.update_or_create(
            rule_name=spec["name"],
            defaults={
                "status": "active",
                "weight_multiplier": 1.0,
                "allocator_weight": 1.0,
                "promotion_stage": "research",
                "notes": (f"Seeded by Phase 34-36 advanced pack. "
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
    from signals.models_opportunity import OpportunitySetup
    from signals.models_control import RuleControl

    s_count, _ = OpportunitySetup.objects.filter(
        name__startswith=SEED_PREFIX).delete()
    r_count, _ = RuleControl.objects.filter(
        rule_name__startswith=SEED_PREFIX).delete()
    return {"setups_deleted": s_count, "rules_deleted": r_count}


class Command(BaseCommand):
    help = "Seed Phase 34-36 advanced multi-modal OpportunitySetups + RuleControls."

    def add_arguments(self, parser):
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args, **opts):
        if opts["reset"]:
            r = reset_setups()
            self.stdout.write(self.style.SUCCESS(
                f"Reset done — removed {r['setups_deleted']} setups, "
                f"{r['rules_deleted']} rules."))
            return

        r = seed_setups(activate=opts["activate"])
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {r['total']} advanced strategies — "
            f"{r['created']} created / {r['updated']} updated · "
            f"RuleControl: {r['rules_created']} created / {r['rules_updated']} updated · "
            f"is_active={opts['activate']}"))
