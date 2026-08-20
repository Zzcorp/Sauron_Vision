"""Phase 34-38 — seed advanced multi-modal strategies.

Nine composite OpportunitySetups that demonstrate the tradecraft, behavioral,
quantitative and structural evaluators working together:

  1. advanced_smc_long           — sweep→BOS sequence + CHoCH + FVG + RVOL
  2. advanced_smc_short          — the mirror image
  3. advanced_capitulation_buy   — capitulation candle + crowd panic + Hurst mean-reverting
  4. advanced_blowoff_short      — parabolic exhaustion + crowd euphoric + RVOL
  5. advanced_news_fade          — bullish news + bearish price + narrative consensus
  6. advanced_smart_money_pivot  — COT divergence + bullish FVG + Hurst trending
  7. advanced_seasonal_turn_long — turn-of-month edge on the symbol's own history
  8. advanced_funding_carry_short— persistent positive funding, contained vol
  9. advanced_pead_drift_long    — earnings beat, entered after the print, HELD

Each composite combines one tradecraft pattern, one psychology pattern, and a
regime/quant filter — the way professional discretionary desks actually
structure trade theses.

Setup 9 is the exception and is the point of Phase 38. Every other setup in
both packs is a reaction: a pattern is true now, so trade now. `pead` is the
first whose thesis is the HOLDING PERIOD — the drift after an earnings print
accrues over weeks — so it is also the first whose `suggested_horizon_days` has
to be checked against the asset class's own time stop before the setup means
anything. The comment on that field carries the arithmetic.

Setups 1 and 2 changed shape in Phase 37. They used to be unordered bags of
three simultaneous conditions; `rule_adapter.is_smc_card` names them as the
tradeable substitute for the SmcSignal cards it drops, so an ICT setup that
could not express ORDER meant the platform's only armed SMC lane was scoring
sweep-then-break and break-then-sweep identically. `event_sequence` is the leg
that fixes it. One consequence is deliberate and worth stating: a whipsaw bar
that sweeps BOTH sides of a coil and closes back inside breaks no structure, so
it no longer fires either setup — the degeneracy the contradiction guard in
`scan_all_setups` exists to catch is now largely removed at the source rather
than caught downstream.

All setups are seeded into RuleControl at stage='research' with weight=1.0 so
they go through the Phase-8 promotion pipeline before any live sizing.

Run:
    python manage.py seed_advanced_strategies              # refresh definitions
    python manage.py seed_advanced_strategies --activate   # also is_active=True
    python manage.py seed_advanced_strategies --reset      # delete the seeded rows

A re-run refreshes DEFINITIONS ONLY: promotion stage, pause/reduce state,
allocator budget, notes, and whether the operator armed the setup all survive.
The RuleControl half of that guarantee lives in `seed_strategies`, shared
verbatim so the two packs cannot drift apart on it.
"""
from django.core.management.base import BaseCommand


SEED_PREFIX = "advanced_"


def _setup_definitions() -> list[dict]:
    return [
        # ── 1. Smart-money long: stop-hunt → BREAK → imbalance → impulse ──
        {
            "name": "advanced_smc_long",
            "description": (
                "Smart-Money long, in ORDER: a swing-low liquidity sweep "
                "prints, and THEN the market breaks structure to the upside "
                "within eight bars. Confirmed by a change of character, an "
                "unfilled bullish FVG, and above-average volume. This is the "
                "setup `rule_adapter` names as the tradeable substitute for "
                "SmcSignal cards, so the sequence has to live here."
            ),
            "direction": "bullish",
            "asset_classes": ["stock", "etf", "forex", "crypto"],
            "conditions": [
                # The thesis leg, and the one the setup did not have. Every
                # other condition in this pack asks "is X true now", so three
                # of them compose to a BAG: the old form scored "a sweep
                # happened AND a gap exists somewhere in the last five days AND
                # volume is 1.5x", in any order, on any leg. Sweep-then-break is
                # a reversal; break-then-sweep is a trend that got tested and
                # held — the opposite trade, which the bag scored identically.
                {"kind": "event_sequence",
                 "params": {"first": "sweep", "then": "structure_break",
                            "direction": "bullish", "lookback": 90,
                            "max_gap_bars": 8, "max_age": 5, "timeframe": "1d"},
                 "weight": 1.5},
                # CHoCH, not BOS: a break that CONTRADICTS the prior break is
                # the only event in this vocabulary that says the direction
                # CHANGED rather than continued, and that is the claim a
                # reversal setup is making. Weighted heavily but not made a
                # gate — a genuine sweep-and-reclaim sometimes prints before the
                # character change is confirmable, and the arithmetic below
                # leaves that case reachable.
                {"kind": "market_structure_break",
                 "params": {"direction": "bullish", "event": "choch",
                            "lookback": 90, "max_age": 5, "timeframe": "1d"},
                 "weight": 1.2},
                # `liquidity_sweep` is GONE from this setup, and its removal is
                # the same repair `starter_commodity_vol_compression` needed.
                # It reads the CURRENT bar only — "is this bar a sweep" — while
                # the sequence leg requires a sweep STRICTLY BEFORE the break.
                # Both can only fire at once if one bar is simultaneously the
                # sweep and a bar before the break, which no bar can be. The
                # two conditions were arithmetically incompatible, so keeping
                # the leg would have parked 1.0 of dead weight in the
                # denominator on every bar the setup could ever match. The
                # sequence leg applies the same 0.3 wick floor, so nothing about
                # the rigour of the sweep test is lost.

                {"kind": "fair_value_gap",
                 "params": {"direction": "bullish", "max_age": 5},
                 "weight": 0.6},
                {"kind": "relative_volume",
                 "params": {"period": 20, "threshold": 1.5},
                 "weight": 0.8},
            ],
            # The arithmetic, since the legs changed shape. Weights total 4.1,
            # so 0.65 needs 2.665 of weighted score. `fair_value_gap` is
            # deliberately the lightest: it scores gap ÷ middle-bar range, and
            # the middle bar of an impulsive three-bar sequence normally spans
            # the gap it leaves, so on real tape the leg lands well under 1.0
            # whatever the imbalance is worth — weighting it heavily would just
            # be a constant drag. Worked through on the sweep→CHoCH tape in
            # tests/test_armed_lane.py: a fresh, tight sweep→break with a
            # character change, an imbalance and 4x volume scores 0.95; the same
            # sequence with NO confirmed character change still reaches 0.66,
            # which is what keeps the CHoCH leg a strong preference rather than
            # a hidden gate.
            "min_match_score": 0.65,
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 1.5, "target_rr": 3.0},
        },

        # ── 2. Smart-money short: mirror-image of #1 ─────────────────────
        {
            "name": "advanced_smc_short",
            "description": (
                "Smart-Money short, in ORDER: a swing-high liquidity sweep "
                "prints and THEN structure breaks to the downside, confirmed "
                "by a bearish change of character, a bearish FVG above price "
                "and above-average volume on the rejection."
            ),
            "direction": "bearish",
            "asset_classes": ["stock", "etf", "forex", "crypto"],
            "conditions": [
                {"kind": "event_sequence",
                 "params": {"first": "sweep", "then": "structure_break",
                            "direction": "bearish", "lookback": 90,
                            "max_gap_bars": 8, "max_age": 5, "timeframe": "1d"},
                 "weight": 1.5},
                {"kind": "market_structure_break",
                 "params": {"direction": "bearish", "event": "choch",
                            "lookback": 90, "max_age": 5, "timeframe": "1d"},
                 "weight": 1.2},
                # No `liquidity_sweep` leg here either, and for the same reason
                # — see the long side. The mirror image has to stay a mirror.
                {"kind": "fair_value_gap",
                 "params": {"direction": "bearish", "max_age": 5},
                 "weight": 0.6},
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
                "COT non-commercials net LONG into a falling price "
                "(divergence) + bullish FVG remaining + price in a trending "
                "regime by Hurst. Trade with the smart money against retail "
                "momentum. Positioning is read in the SYMBOL's frame, so the "
                "pairs the dollar is the base of (USDJPY, USDCHF, USDCAD, "
                "USDMXN) are scored right-way-up rather than gated out."
            ),
            "direction": "bullish",
            "asset_classes": ["forex", "commodity"],
            "conditions": [
                # `direction`, because the setup's own direction is fixed at
                # "bullish" and the scanner writes it verbatim into the Signal
                # and the flag. Left unqualified this leg also matched the
                # mirror-image divergence — price RISING into a net-short book,
                # which is a short thesis — and the setup published those as
                # bullish flags. The gate mechanism is not the tool here: the
                # branch is what is wrong, not the universe.
                {"kind": "smart_money_divergence",
                 "params": {"slope_lookback": 20, "slope_threshold": 0.0005,
                            "min_ratio": 0.3, "direction": "bullish"},
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

        # ── 7. Turn-of-month seasonality (Phase 37) ──────────────────────
        {
            "name": "advanced_seasonal_turn_long",
            "description": (
                "Turn-of-month long: the instrument's OWN history shows a "
                "positive mean return in the three calendar days either side "
                "of a month boundary, over at least 30 observations, taken "
                "only while price holds above its 50-day MA and the asset's "
                "own 5% tail is no worse than -6%/day. The seasonal leg "
                "reports its sample size, refuses to score a bucket it has "
                "not measured enough of, and only fires while the calendar "
                "is actually AT the turn — on any other day it declines."
            ),
            "direction": "bullish",
            "asset_classes": ["stock", "etf", "crypto"],
            "conditions": [
                # Three years, because the bucket needs observations and the
                # window has to be long enough to contain them: 1095 days holds
                # ~72 turn-of-month sessions on a five-day instrument and ~108
                # on crypto, comfortably past the 30 asked for below. A
                # month_of_year leg on the same window would hold THREE
                # observations and the evaluator would — correctly — refuse it.
                #
                # This leg is also what pins the setup to the CALENDAR, and it
                # is the only thing that can. `turn_of_month` buckets every day
                # into "turn" or "rest", and nothing else in this setup asks
                # what day it is — so on the 15th the leg used to measure the
                # "rest" bucket, whose mean on anything in a multi-year uptrend
                # is simply the drift, and the setup took an ordinary trend
                # trade wearing a seasonality label. `seasonal_bias` now
                # declines the remainder bucket outright (see
                # SEASONAL_BASELINE_BUCKETS), which leaves this setup dark on
                # roughly four days in five — as a calendar setup should be.
                {"kind": "seasonal_bias",
                 "params": {"mode": "turn_of_month", "direction": "bullish",
                            "lookback_days": 1095, "min_observations": 30,
                            "min_edge_pct": 0.05, "timeframe": "1d"},
                 "weight": 1.5},
                # A calendar edge measured on the instrument's own history is an
                # UNCONDITIONAL average — it includes every turn-of-month spent
                # inside a bear market, where the drift dominates the effect. So
                # "not in a downtrend" is a PRECONDITION of the thesis, not a
                # piece of evidence: no seasonal reading, however strong, makes
                # buying the calendar into a falling market the same trade.
                #
                # A gate for a second, arithmetic reason. `above_ma` scores
                # (last-ma)/ma × 5, so full marks need spot 20% above its 50-day
                # MA — a level a stock in a normal uptrend never reaches. As a
                # weighted leg it would contribute ~0.15 while occupying 0.8 of
                # the denominator, i.e. act as a fixed penalty on every match
                # rather than as a filter. That is the same trap
                # `starter_forex_breakout` had to lower its bar for.
                {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 50},
                 "gate": True},
                # The seasonal edge is measured in tenths of a percent per day.
                # An instrument whose worst-5% day averages below -6% can undo a
                # month of it in one session, so the tail has to be smaller than
                # the edge is worth. -6.0 rather than the evaluator's -3.0
                # default because this universe includes crypto, where -3% is an
                # ordinary tail and the leg would gate out the whole class.
                {"kind": "cvar_tail_risk",
                 "params": {"direction": "better_than", "alpha": 0.05,
                            "threshold_pct": -6.0, "lookback": 120},
                 "weight": 0.6},
            ],
            # The gate contributes no weight, so the scoring legs total 2.1 and
            # 0.60 needs 1.26. A seasonal bucket at |t| ≥ 2 scores 1.0 and
            # carries the setup on its own (1.5); one at |t| = 1.2 scores 0.6
            # and needs the tail leg's help to clear. That is the shape wanted:
            # the calendar is the thesis and the tail is a veto with a vote,
            # not the other way round.
            "min_match_score": 0.60,
            # Five days: the turn-of-month window is three days either side of
            # the boundary, so a horizon much longer than that grades the setup
            # on a period its own thesis says nothing about.
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 2.0, "target_rr": 2.0},
        },

        # ── 8. Perpetual funding carry (Phase 37) ────────────────────────
        {
            "name": "advanced_funding_carry_short",
            "description": (
                "Funding carry short: perpetual funding has been persistently "
                "POSITIVE for a fortnight, so longs are paying shorts three "
                "times a day. Taken only in a contained-volatility, "
                "mean-reverting regime, because the carry is small next to the "
                "spot risk of holding the leg. This reads FundingRate as a "
                "payment stream (level + persistence); `funding_rate_extreme` "
                "reads the same table as a z-score deviation and fires "
                "contrarian — the two can and do point opposite ways."
            ),
            "direction": "bearish",
            "asset_classes": ["crypto"],
            "conditions": [
                # 20% annualised, above the evaluator's own 15% floor: Binance's
                # base rate of 0.01%/8h annualises to ~11%, so 15% is merely
                # "above no skew at all" and 20% is the first level that pays
                # for the position's existence. 0.85 persistence over a
                # fortnight means funding paid the short on at least 12 of the
                # 14 days rather than spiking once.
                {"kind": "funding_carry",
                 "params": {"direction": "collect_short", "lookback_days": 14,
                            "min_annualized_pct": 20.0, "min_persistence": 0.85,
                            "min_days_covered": 10},
                 "weight": 1.5},
                # The honest arithmetic behind the two filters below: 20%/yr is
                # ~0.77% over a fortnight. At 3%/day realised vol — BTC's
                # long-run average — a fortnight's price sigma is ~11%. The
                # carry is a fourteenth of one sigma, so the ONLY version of
                # this trade that survives is one taken when vol is contained
                # and the tape is not trending against the short.
                {"kind": "garch_vol_forecast",
                 "params": {"direction": "below", "threshold_pct": 3.0,
                            "lookback": 120},
                 "weight": 0.8},
                {"kind": "hurst_regime",
                 "params": {"regime": "mean_reverting", "lookback": 120},
                 "weight": 0.6},
            ],
            # Weights total 2.9, so 0.60 needs 1.74. Worked through: 25%/yr at
            # 0.90 persistence in 2.5%/day vol scores 0.40 and is REFUSED —
            # correctly, since that carry is a twelfth of one fortnightly sigma.
            # 60%/yr at full persistence in 1.5%/day vol with H=0.35 scores
            # 0.78 and fires. The bar is deliberately hard to clear: carry is a
            # small edge and the only version of it worth holding is the large,
            # persistent one in a quiet tape.
            "min_match_score": 0.60,
            # Seven days, not the fourteen the carry is MEASURED over, and the
            # two numbers are different things: `lookback_days` is how much
            # history has to agree that funding pays, while the horizon is how
            # long the position is graded over. Carry accrues per settlement, so
            # a week of it is half a fortnight of it at the same rate — nothing
            # in the thesis needs the holding period to equal the measurement
            # window.
            #
            # Seven is also the longest horizon this setup is allowed to have.
            # `DEFAULT_MAX_HOLD_HOURS["crypto"]` is 192h and the crypto book is
            # 24/7, so a 14-day horizon would be time-stopped on day 8 — six
            # days before the window it claims to trade closes — and every
            # winner would resolve as a TIME exit, poisoning the rule's own
            # track record with exits its thesis never asked for. The ceiling is
            # deliberately one day past the longest crypto thesis (7d, shared
            # with advanced_capitulation_buy) so the trade is not cut while
            # still inside its own horizon; moving the ceiling to fit a
            # fortnight would loosen the time stop for every crypto setup to
            # accommodate the weakest edge in the pack.
            "suggested_horizon_days": 7,
            # target_rr=1.0 is a deliberate placeholder, not a forecast. The
            # exit is the horizon; `_suggested_levels` reads only stop_pct and
            # target_rr, so leaving target_rr out would let it fall silently to
            # 2.0 and grade a carry trade against a 10% move it never predicted.
            "sizing": {"stop_pct": 5.0, "target_rr": 1.0},
        },

        # ── 9. Post-earnings drift, HELD (Phase 38) ──────────────────────
        {
            "name": "advanced_pead_drift_long",
            "description": (
                "Post-earnings-announcement drift, long: an issuer beat its "
                "EPS estimate by 10% or more, the print is a full day old so "
                "its reaction bar has already traded, price has moved WITH "
                "the surprise since, and volume says the accumulation is "
                "still going on. The announcement gap is conceded on purpose "
                "— this is the only setup in either pack whose thesis is the "
                "HOLD rather than the entry, so its horizon is the argument."
            ),
            "direction": "bullish",
            # Stocks only. `_persist_earnings` writes one row per issuer per
            # print and nothing else in the universe reports EPS, so listing
            # any other class would seed conditions that can never be true.
            "asset_classes": ["stock"],
            "conditions": [
                # min_move_pct at 1.0 is a SIGN test with a noise floor, not a
                # strength requirement: the leg exists to reject a beat the
                # market ignored or faded, and a floor anywhere near the size
                # of a typical earnings reaction would demand the drift trade
                # also catch the gap it deliberately gives away.
                {"kind": "pead",
                 "params": {"direction": "bullish", "min_surprise_pct": 10.0,
                            "min_age_hours": 24, "max_age_days": 5,
                            "min_move_pct": 1.0},
                 "weight": 1.5},
                # 1.3x rather than the evaluator's 2.0 default: post-print
                # volume decays over exactly the days this setup enters in, so
                # a 2x bar is a day-one reading and asking for it on day four
                # would gate out the half of the window where the drift is
                # least crowded. `baseline_offset` is what makes 1.3 actually
                # BE 1.3. The average otherwise ends at the previous bar, so
                # it holds the print's own volume spike from day one and the
                # fat sessions after it by day three; dividing by that inflated
                # figure turns a stated 1.3x into roughly 1.8x of the quiet
                # pre-print tape across days three to five — the day-one-only
                # gate the lower threshold was picked to avoid, rebuilt by
                # arithmetic. Six bars is `max_age_days` plus the print bar
                # itself, so the average sits entirely before the announcement
                # wherever in the entry window a scan lands. The
                # leg is not decoration — PEAD's mechanism is slow
                # institutional accumulation, and a print nobody is trading is
                # a print nobody is accumulating into.
                {"kind": "relative_volume",
                 "params": {"period": 20, "threshold": 1.3,
                            "baseline_offset": 6},
                 "weight": 0.8},
                # A gate, not a leg, for both reasons the seasonal setup gives:
                # buying a beat into a downtrend is a different trade — the
                # drift is measured in a few percent and the trend it fights is
                # not — and `above_ma` scores (last−ma)/ma × 5, so a weighted
                # version would contribute ~0.1 while occupying 0.8 of the
                # denominator. 50 days rather than 20 because the gap itself
                # lifts price over a short MA, which would make the check free.
                {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 50},
                 "gate": True},
            ],
            # The gate carries no weight, so the scoring legs total 2.3 and
            # 0.70 needs 1.61. Worked through, every volume multiple read
            # against the pre-print baseline the offset above buys: a +25% beat
            # two days after the print (size 1.0, freshness 0.75 → 0.875) on 2x
            # volume scores 0.92 and fires; the SAME beat with volume back at
            # that baseline scores 0.57 and is refused, which is the point —
            # the thesis leg cannot carry this setup alone. At the other end a
            # +10% beat, the minimum this leg accepts, needs to be both fresh
            # and loud: on day one with 2x volume it reaches 0.84, and on day
            # four it tops out at 0.59 however loud the tape is.
            "min_match_score": 0.70,
            # Ten days, and the number is bounded from both ends. Below: the
            # drift is a multi-week effect, so a 3-day horizon grades the trade
            # on the noise around it. Above: `DEFAULT_MAX_HOLD_HOURS["stock"]`
            # is 336h and `suggested_horizon_days` is CALENDAR days, so
            # anything past 14 days is flattened with reason TIME before the
            # horizon it declares can resolve — the bug
            # `advanced_funding_carry_short` documents on the crypto side. Ten
            # also equals the longest equity thesis already seeded
            # (starter_stock_momentum), so this setup fits under the ceiling
            # that exists rather than asking every equity config to loosen its
            # time stop for one new rule.
            "suggested_horizon_days": 10,
            # 4.0% because realised vol roughly doubles in the days after a
            # print: a 2% stop is inside one ordinary post-earnings session and
            # would exit on noise before the drift had a chance to appear.
            # target_rr 1.5 (i.e. +6%) is named rather than left to default for
            # the same reason as the carry setup — the exit here is the
            # HORIZON, and the 2.0 default would silently grade ten days of
            # drift against an 8% move nothing in the thesis predicts.
            "sizing": {"stop_pct": 4.0, "target_rr": 1.5},
        },
    ]


def seed_setups(*, activate: bool = False) -> dict:
    from signals.models_opportunity import OpportunitySetup

    from .seed_strategies import rule_parameters, upsert_rule_control

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
        # is_active is the OPERATOR's field once the row exists. Hard-coding it
        # to `activate` meant the admin panel's one-click re-seed — which
        # passes no flags — disarmed every advanced setup someone had switched
        # on by hand. Only --activate asserts it on an existing row.
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

        rule, rule_was_created = upsert_rule_control(
            rule_name=spec["name"],
            seed_notes=(f"Seeded by Phase 34-38 advanced pack. "
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
    from signals.models_opportunity import OpportunitySetup
    from signals.models_control import RuleControl

    s_count, _ = OpportunitySetup.objects.filter(
        name__startswith=SEED_PREFIX).delete()
    r_count, _ = RuleControl.objects.filter(
        rule_name__startswith=SEED_PREFIX).delete()
    return {"setups_deleted": s_count, "rules_deleted": r_count}


class Command(BaseCommand):
    help = "Seed Phase 34-38 advanced multi-modal OpportunitySetups + RuleControls."

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
