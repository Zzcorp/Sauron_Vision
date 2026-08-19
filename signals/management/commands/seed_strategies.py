"""Phase-31 — seed a starter pack of OpportunitySetup + RuleControl rows.

Six pre-built strategies covering common patterns: trend-following,
mean-reversion, breakout, news-driven, volatility regime, and a
multi-modal cross-asset macro setup.

Each is created in `RuleControl` at stage="research" with weight=1.0 so
they go through the Phase-8 promotion pipeline before any live sizing.

Run with:
    python manage.py seed_strategies              # refresh definitions
    python manage.py seed_strategies --activate   # also activate them in scanner
    python manage.py seed_strategies --reset      # remove the seeded rules

Designed to be safe in two ways:

  - only touches setups whose `name` starts with `SEED_PREFIX`, so
    user-created setups are never modified;
  - a re-run refreshes DEFINITIONS ONLY. Everything the operator or the engine
    has since decided about a seeded rule — its promotion stage, whether it is
    paused or reduced, its allocator budget, its notes, whether the setup is
    armed — survives untouched. See `upsert_rule_control`.
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
                "AND breakout above 60-bar high. Confirmation via rising "
                "US GDP (FRED series GDP), oldest versus newest print "
                "released inside a 400-day window — two to three quarters "
                "of growth."
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
                # FRED dates a quarterly observation at the QUARTER START, and
                # BEA publishes the advance estimate ~30 days after the quarter
                # ENDS. So the newest print an install can hold is dated
                # d-121 at best and ages to d-212 before the next one lands,
                # and macro_trend needs TWO rows inside its window or it scores
                # 0. Floor = longest three consecutive quarters (91+92+92=275)
                # + the 30-day release lag - 1 = 304 days; 240 satisfied that
                # on only ~31% of days, so the confirmation leg was inert two
                # thirds of the year while still sitting in the denominator.
                # 400 holds three or four released prints every day of the
                # cycle and tolerates a release running ~95 days late — a
                # shutdown-scale delay — before the leg can blank again.
                {"kind": "macro_trend",
                 "params": {"series_id": "GDP", "direction": "rising",
                              "lookback_days": 400, "min_change_pct": 0.5},
                 "weight": 0.5},
            ],
            "min_match_score": 0.65,
            "suggested_horizon_days": 10,
            # target_rr, not target_pct: _suggested_levels reads stop_pct and
            # target_rr and nothing else, so every target_pct seeded here was
            # discarded and the target silently fell back to 2R. Each ratio
            # below is the one the old target_pct actually asked for.
            "sizing": {"stop_pct": 3.0, "target_rr": 2.0},
        },

        # ── 2. Mean-reversion on stocks ─────────────────────────────────
        {
            "name": "starter_stock_mean_reversion",
            "description": (
                "Counter-trend: price below its 20-period MA while 20-day "
                "realized volatility is elevated (≥2%/day) — a washout, not a "
                "drift. Bias bullish on the bounce."
            ),
            "direction": "bullish",
            "asset_classes": ["stock", "etf"],
            "conditions": [
                {"kind": "price_pattern",
                 "params": {"pattern": "below_ma", "ma_period": 20},
                 "weight": 1.0},
                # "Oversold" here means the selling was violent, so the vol leg
                # reads ABOVE the threshold. `period` tracks the MA leg so both
                # conditions describe the same 20 bars.
                {"kind": "volatility_regime",
                 "params": {"period": 20, "direction": "above",
                              "threshold_pct": 2.0},
                 "weight": 0.8},
            ],
            "min_match_score": 0.60,
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 2.5, "target_rr": 2.0},
        },

        # ── 3. Forex breakout on session overlap ────────────────────────
        {
            "name": "starter_forex_breakout",
            "description": (
                "FX breakout: price breaks above 30-bar high while holding "
                "above the 50-period MA. Pairs with the ForexBot's London/NY "
                "session filter (Phase 13.4) so entries fire only during "
                "liquid hours."
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
            # above_ma scores (last-ma)/ma×5, so 0.70 across these weights
            # demanded spot 5% above its 50-day MA — a level FX majors do not
            # reach. The breakout is still mandatory (above_ma alone tops out
            # at 0.40); 0.62 only stops the MA leg from vetoing every breakout.
            "min_match_score": 0.62,
            "suggested_horizon_days": 3,
            "sizing": {"stop_pct": 1.0, "target_rr": 2.5},
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
                 "params": {"lookback_days": 1, "min_count": 3},
                 "weight": 1.0},
                # min_count mirrors the volume leg's 3 so the two conditions
                # can't disagree about how much coverage counts as a catalyst.
                {"kind": "news_sentiment",
                 "params": {"lookback_days": 1, "direction": "above",
                              "threshold": 0.4, "min_count": 3},
                 "weight": 1.5},
                {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 10},
                 "weight": 0.5},
            ],
            "min_match_score": 0.70,
            "suggested_horizon_days": 3,
            "sizing": {"stop_pct": 4.0, "target_rr": 2.0},
        },

        # ── 5. Volatility-regime contraction (commodity) ────────────────
        {
            "name": "starter_commodity_vol_compression",
            "description": (
                "Commodities exiting a low-vol regime tend to trend: 20-day "
                "realized volatility compressed below 2%/day AND a break of "
                "the 20-bar high — the expansion actually firing, not merely "
                "setting up."
            ),
            "direction": "bullish",
            "asset_classes": ["commodity"],
            "conditions": [
                # Compression is the thesis, so this leg reads BELOW. The
                # seeded {"regime": "low"} was read by nobody and the evaluator
                # defaulted to direction="above" — the setup was scoring
                # exactly the volatility expansion it exists to front-run.
                {"kind": "volatility_regime",
                 "params": {"period": 20, "direction": "below",
                              "threshold_pct": 2.0},
                 "weight": 1.5},
                # A breakout, not above_ma: in a compressed tape price sits ON
                # its MA by definition, so above_ma's (last-ma)/ma×5 score can
                # never clear this setup's bar — the two conditions would have
                # contradicted each other arithmetically.
                {"kind": "price_pattern",
                 "params": {"pattern": "breakout_high", "lookback": 20},
                 "weight": 1.0},
            ],
            "min_match_score": 0.65,
            "suggested_horizon_days": 14,
            "sizing": {"stop_pct": 5.0, "target_rr": 2.4},
        },

        # ── 6. Macro-driven cross-asset (USD-weakness composite) ────────
        {
            "name": "starter_usd_weakness_macro",
            "description": (
                "Composite USD-weakness setup: the 2-year Treasury yield "
                "falling (the market pricing cuts — dovish) + COT "
                "non-commercials net long with conviction. Restricted to "
                "USD-QUOTED symbols (EURUSD, GBPUSD, XAUUSD, WTIUSD …), where "
                "a weaker dollar means the symbol rises. USD-base pairs "
                "(USDJPY, USDCHF, USDCAD, USDMXN) express the same thesis "
                "upside-down and are gated out rather than traded backwards."
            ),
            "direction": "bullish",
            "asset_classes": ["forex", "commodity"],
            "conditions": [
                # The thesis is about the DOLLAR; `direction` is about the
                # SYMBOL. On USDJPY et al. those point opposite ways, and the
                # scanner writes setup.direction verbatim into the Signal, the
                # flag and the suggested levels — so the setup was emitting
                # BULLISH USDJPY on evidence that the dollar was falling, and
                # grading those inversions into the hit-rate the promotion
                # ladder reads. A gate, not a weighted leg: "does this setup
                # apply to this symbol" must not be outvotable by evidence.
                {"kind": "quote_currency",
                 "params": {"currency": "USD"},
                 "gate": True},
                # "Dovish" is a direction, not a level. macro_regime can only
                # compare a FRED level to a fixed threshold, and no threshold on
                # any series here means dovish across rate regimes — one written
                # for a 5% funds rate is dead the moment the cycle turns. DGS2
                # falling says the same thing and can fire in any decade.
                {"kind": "macro_trend",
                 "params": {"series_id": "DGS2", "direction": "falling",
                              "lookback_days": 60, "min_change_pct": 5.0},
                 "weight": 1.5},
                # The evaluator holds one report at a time, so it cannot see
                # longs "increasing"; net-long past a 0.25 skew is the closest
                # honest reading, and it sits inside the 0.1–0.4 band real COT
                # ratios occupy rather than above it.
                {"kind": "cot_report",
                 "params": {"direction": "long_extreme", "min_ratio": 0.25},
                 "weight": 1.0},
            ],
            "min_match_score": 0.70,
            "suggested_horizon_days": 21,
            "sizing": {"stop_pct": 2.0, "target_rr": 3.0},
        },
    ]


def rule_parameters(spec: dict) -> dict:
    """The slice of RuleControl.parameters this pack owns — the setup's shape,
    echoed for the rules lane. Never the whole dict: see `upsert_rule_control`."""
    return {
        "asset_classes": spec["asset_classes"],
        "min_match_score": spec["min_match_score"],
        "horizon_days": spec["suggested_horizon_days"],
    }


def upsert_rule_control(*, rule_name: str, seed_notes: str,
                        parameters: dict) -> tuple:
    """Create the companion RuleControl, or refresh ONLY its definition.

    Returns (rule, was_created).

    `update_or_create(defaults=...)` writes its defaults on UPDATE too, so the
    previous form force-wrote status, weight_multiplier, allocator_weight and
    promotion_stage onto rows the operator and the engine had been moving for
    months. Re-seeding to pick up a repaired condition — which is the only way
    those repairs reach the DB, and which the admin panel offers as one button
    — therefore demoted every promoted rule back to research (SIZE_FACTORS
    ["research"] = 0.0, so a live rule stops trading) with no PromotionEvent
    written, cleared admin pauses and reduces back to full size, and reset the
    meta-allocator's risk budget to 1.0. None of that is a definition.

    What a re-run may touch:
      - `parameters`, and only the keys this pack owns. The column is shared
        with the evolution engine's tuned values, so the seed merges into it
        instead of replacing it.

    What it must never touch on an existing row:
      - promotion_stage / stage_entered_at / stage_baseline_expectancy — the
        promotion ladder's state, and its audit log has no record of a seeder
        moving anything;
      - status / paused_until / weight_multiplier — the actuator's, set by an
        admin-confirmed pause or reduce;
      - allocator_weight — the meta-allocator's applied risk budget;
      - notes — the actuator writes its own record there ("Paused by RuleAction
        #N …"), which the seed blurb used to overwrite.
    """
    from signals.models_control import RuleControl

    rule, was_created = RuleControl.objects.get_or_create(
        rule_name=rule_name,
        defaults={
            "status": "active",
            "weight_multiplier": 1.0,
            "allocator_weight": 1.0,
            "promotion_stage": "research",
            "notes": seed_notes,
            "parameters": dict(parameters),
        },
    )
    if was_created:
        return rule, True

    merged = dict(rule.parameters or {})
    merged.update(parameters)
    if merged != (rule.parameters or {}):
        rule.parameters = merged
        rule.save(update_fields=["parameters", "updated_at"])
    return rule, False


def seed_setups(*, activate: bool = False) -> dict:
    """Upsert starter setups + companion RuleControl rows.

    Re-running refreshes definitions only — operator and engine state on both
    models is preserved. Returns counts:
    {created, updated, rules_created, rules_updated}.
    """
    from signals.models_opportunity import OpportunitySetup

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
        rule, rule_was_created = upsert_rule_control(
            rule_name=spec["name"],
            seed_notes=(f"Seeded by Phase-31 starter pack. "
                        f"{spec['description'][:80]}..."),
            parameters=rule_parameters(spec),
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
            # "->" not "→": U+2192 has no cp1252 mapping, so the arrow raised
            # UnicodeEncodeError and killed the command on a Windows console —
            # after the seeding had already committed. Every other glyph this
            # command prints (— ·) does map.
            self.stdout.write(
                "  Setups are INACTIVE until you arm them: re-run with "
                "--activate, or toggle each on /opportunities/ "
                "(Intelligence -> Opportunities).")
