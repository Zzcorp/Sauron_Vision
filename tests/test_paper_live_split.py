"""Plan 1.2 — LIVE entries must not be weighted with PAPER evidence.

`bot_performance_summary` filtered closed AssetBotTrade rows by status,
outcome, rule, asset class, user and date, and never by `paper`.
`bot_trade_track_record` read it, `aggregation.rule_weight` multiplied each
rule's vote by that number, and weighted consensus is on by default — so
simulated fills chose the direction and the score of real orders.

The two venues cannot produce the same R by construction: a paper fill is
charged a modelled half-spread on both sides (risk_levels.paper_fill_price)
and rests no stop at a broker, while a live fill books the raw mark against
a real bracket. The pooled average estimates neither, which is what the
first test here pins down numerically.

Run with:  python manage.py test tests.test_paper_live_split
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name):
    return User.objects.create_user(username=name, password="x")


def _abc(user, asset_class, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=defaults.pop("name", "T"),
        **defaults,
    )


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class,
                  "is_watchlist": False})
    return inst


def _signal(inst, direction="bullish", score=0.85, rule="r1"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction=direction,
        urgency="medium", title=f"{rule} fired", description="d",
        rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        is_active=True)


def _closed(cfg, *, symbol, rule_name, paper, win, qty=10):
    """One graded close. Win: entry 100 → exit 110 against a 95 stop = +2R.
    Loss: exit 95 = the stop = -1R. Identical shape on both venues, so any
    difference the tests below observe comes from the venue split alone.
    """
    from bot_program.bot_grading import grade_bot_trade
    from bot_program.models import AssetBotTrade
    exit_price = 110 if win else 95
    pnl = Decimal(str((exit_price - 100) * qty))
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal(str(qty)), entry_price=Decimal("100"),
        exit_price=Decimal(str(exit_price)), stop_loss=Decimal("95"),
        take_profit=Decimal("110"), status="CLOSED", pnl=pnl,
        rule_name=rule_name, paper=paper,
    )
    AssetBotTrade.objects.filter(pk=t.pk).update(
        opened_at=timezone.now() - timedelta(hours=2),
        closed_at=timezone.now())
    t.refresh_from_db()
    grade_bot_trade(t)
    return t


def _seed(cfg, rule, *, paper, wins, losses, tag=""):
    for i in range(wins):
        _closed(cfg, symbol=f"{tag}W{i}", rule_name=rule, paper=paper, win=True)
    for i in range(losses):
        _closed(cfg, symbol=f"{tag}L{i}", rule_name=rule, paper=paper, win=False)


# ── the venue filter itself ──────────────────────────────────────────────

class VenueFilterTests(TestCase):
    def setUp(self):
        self.cfg = _abc(_user("venue_u"), "stock", name="V")
        # A rule that works in the simulator and loses real money: the exact
        # shape the pooled number was hiding.
        _seed(self.cfg, "split", paper=True, wins=8, losses=2, tag="p")
        _seed(self.cfg, "split", paper=False, wins=2, losses=8, tag="l")

    def test_live_rows_exclude_paper_fills(self):
        from bot_program.bot_grading import VENUE_LIVE, bot_performance_summary
        rows = bot_performance_summary(rule_name="split", days=30,
                                       venue=VENUE_LIVE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["n"], 10)
        self.assertEqual(rows[0]["n_wins"], 2)
        self.assertAlmostEqual(rows[0]["expectancy"], -0.4, places=4)

    def test_paper_rows_exclude_live_fills(self):
        from bot_program.bot_grading import VENUE_PAPER, bot_performance_summary
        rows = bot_performance_summary(rule_name="split", days=30,
                                       venue=VENUE_PAPER)
        self.assertEqual(rows[0]["n"], 10)
        self.assertEqual(rows[0]["n_wins"], 8)
        self.assertAlmostEqual(rows[0]["expectancy"], 1.4, places=4)

    def test_pooled_row_is_still_the_default(self):
        """Dashboards, the decay detector and the promotion ladder all read
        the pooled row and must keep seeing every trade."""
        from bot_program.bot_grading import VENUE_ALL, bot_performance_summary
        rows = bot_performance_summary(rule_name="split", days=30)
        self.assertEqual(rows[0]["n"], 20)
        self.assertEqual(rows[0]["venue"], VENUE_ALL)

    def test_pooled_expectancy_describes_neither_venue(self):
        """Not a style complaint — the pooled +0.5R sits between a +1.4R
        simulator and a -0.4R book, so it overstates live and understates
        paper simultaneously. No amount of sample size fixes that."""
        from bot_program.bot_grading import (
            VENUE_LIVE, VENUE_PAPER, bot_performance_summary,
        )
        pooled = bot_performance_summary(rule_name="split", days=30)[0]
        live = bot_performance_summary(rule_name="split", days=30,
                                       venue=VENUE_LIVE)[0]
        paper = bot_performance_summary(rule_name="split", days=30,
                                        venue=VENUE_PAPER)[0]
        self.assertGreater(pooled["expectancy"], live["expectancy"])
        self.assertLess(pooled["expectancy"], paper["expectancy"])

    def test_every_row_names_its_venue(self):
        from bot_program.bot_grading import VENUE_LIVE, bot_performance_summary
        rows = bot_performance_summary(days=30, venue=VENUE_LIVE)
        self.assertTrue(all(r["venue"] == VENUE_LIVE for r in rows))

    def test_unknown_venue_raises_rather_than_pooling(self):
        """A typo that quietly pooled would reinstate the bug invisibly at
        the one call site where it costs money."""
        from bot_program.bot_grading import bot_performance_summary
        with self.assertRaises(ValueError):
            bot_performance_summary(rule_name="split", venue="Live")


# ── the multiplier ───────────────────────────────────────────────────────

class TrackRecordVenueTests(TestCase):
    def setUp(self):
        self.cfg = _abc(_user("trk_u"), "stock", name="T")

    def test_paper_evidence_no_longer_reaches_a_live_multiplier(self):
        from bot_program.bot_grading import (
            VENUE_ALL, VENUE_LIVE, bot_trade_track_record,
        )
        _seed(self.cfg, "split", paper=True, wins=8, losses=2, tag="p")
        _seed(self.cfg, "split", paper=False, wins=2, losses=8, tag="l")
        live = bot_trade_track_record("split", "stock", min_n=5,
                                      venue=VENUE_LIVE)
        pooled = bot_trade_track_record("split", "stock", min_n=5,
                                        venue=VENUE_ALL)
        self.assertLess(live, 1.0)     # the book says shrink this rule
        self.assertGreater(pooled, 1.0)  # the pool said grow it

    def test_cold_start_live_rule_is_neutral_not_paper_and_not_zero(self):
        """A rule fresh off promotion has a full paper record and no live
        one. The honest weight is 1.0 with a reason: the paper number would
        let simulated fills size the first real order, and 0.0 would veto
        every rule on its first live day."""
        from bot_program.bot_grading import VENUE_LIVE, bot_track_record_detail
        _seed(self.cfg, "fresh", paper=True, wins=9, losses=1, tag="p")
        d = bot_track_record_detail("fresh", "stock", min_n=5,
                                    venue=VENUE_LIVE)
        self.assertEqual(d["multiplier"], 1.0)
        self.assertEqual(d["n"], 0)
        self.assertFalse(d["measured"])
        # Not measured is not zero — the house rule.
        self.assertIsNone(d["expectancy"])
        self.assertIsNone(d["win_rate"])
        self.assertIn("no closed live trades", d["reason"])

    def test_thin_live_record_states_its_own_count(self):
        """Distinct from the cold start: four closes is evidence, just not
        enough of it, and the reason must not read as 'never traded'."""
        from bot_program.bot_grading import VENUE_LIVE, bot_track_record_detail
        _seed(self.cfg, "thin", paper=False, wins=3, losses=1, tag="l")
        d = bot_track_record_detail("thin", "stock", min_n=10,
                                    venue=VENUE_LIVE)
        self.assertEqual(d["multiplier"], 1.0)
        self.assertEqual(d["n"], 4)
        self.assertFalse(d["measured"])
        self.assertIsNotNone(d["expectancy"])
        self.assertIn("below min_n=10", d["reason"])

    def test_clamping_is_unchanged(self):
        """8 wins at +2R and 2 losses at -1R computes to 1.58; the ceiling
        of 1.5 still holds, and the floor still holds on the mirror image."""
        from bot_program.bot_grading import VENUE_PAPER, bot_trade_track_record
        _seed(self.cfg, "hot", paper=True, wins=8, losses=2, tag="h")
        self.assertEqual(
            bot_trade_track_record("hot", "stock", min_n=5, venue=VENUE_PAPER),
            1.5)
        _seed(self.cfg, "cold", paper=True, wins=0, losses=10, tag="c")
        m = bot_trade_track_record("cold", "stock", min_n=5, venue=VENUE_PAPER)
        self.assertGreaterEqual(m, 0.5)
        self.assertLess(m, 1.0)

    def test_default_venue_still_pools(self):
        """Callers that were not part of this change keep their number."""
        from bot_program.bot_grading import (
            VENUE_ALL, bot_trade_track_record,
        )
        _seed(self.cfg, "split", paper=True, wins=8, losses=2, tag="p")
        _seed(self.cfg, "split", paper=False, wins=2, losses=8, tag="l")
        self.assertEqual(
            bot_trade_track_record("split", "stock", min_n=5),
            bot_trade_track_record("split", "stock", min_n=5, venue=VENUE_ALL))


# ── the decision path ────────────────────────────────────────────────────

class RuleWeightVenueTests(TestCase):
    def setUp(self):
        self.cfg = _abc(_user("rw_u"), "stock", name="R")
        # Proven in the simulator only — nothing has ever filled live.
        _seed(self.cfg, "sim_star", paper=True, wins=9, losses=1, tag="p")

    def test_live_entry_ignores_a_paper_only_record(self):
        from bot_program.asset_engine.aggregation import rule_weight
        self.assertEqual(
            rule_weight("sim_star", "stock", signal_stats={}, venue="live"),
            1.0)

    def test_paper_entry_still_uses_its_own_record(self):
        from bot_program.asset_engine.aggregation import rule_weight
        self.assertGreater(
            rule_weight("sim_star", "stock", signal_stats={}, venue="paper"),
            1.0)

    def test_unstated_venue_skips_the_bot_lane(self):
        """Pooled is the wrong number for both venues, so a caller that has
        not said which venue it is trading gets no bot-trade evidence at
        all rather than a number that is wrong either way."""
        from bot_program.asset_engine.aggregation import rule_weight
        self.assertEqual(
            rule_weight("sim_star", "stock", signal_stats={}), 1.0)

    def test_weighted_consensus_forwards_the_venue(self):
        from bot_program.asset_engine import aggregation
        seen = {}

        def spy(rule, asset_class="", **kw):
            seen[rule] = kw.get("venue")
            return 1.0

        with patch.object(aggregation, "rule_weight", side_effect=spy):
            aggregation.weighted_consensus(
                [SimpleNamespace(score=0.8, rule_name="a")], [],
                asset_class="stock", venue="live")
        self.assertEqual(seen, {"a": "live"})

    def test_the_venue_can_change_the_verdict(self):
        """The end-to-end statement of the defect: identical signals, and
        the only difference is which venue's fills were allowed to vouch
        for the rule."""
        from bot_program.asset_engine.aggregation import weighted_consensus
        bull = [SimpleNamespace(score=0.7, rule_name="sim_star")]
        bear = [SimpleNamespace(score=0.7, rule_name="unproven")]
        on_paper = weighted_consensus(bull, bear, asset_class="stock",
                                      min_net_weight=0.3, venue="paper")
        on_live = weighted_consensus(bull, bear, asset_class="stock",
                                     min_net_weight=0.3, venue="live")
        self.assertEqual(on_paper["direction"], "BUY")
        self.assertEqual(on_live["direction"], "HOLD")


# ── the diagnostic that falls out of the split ───────────────────────────

class ExecutionGapTests(TestCase):
    def setUp(self):
        self.cfg = _abc(_user("gap_u"), "stock", name="G")

    def test_gap_is_live_minus_paper(self):
        from bot_program.bot_grading import paper_live_expectancy_gap
        _seed(self.cfg, "split", paper=True, wins=8, losses=2, tag="p")
        _seed(self.cfg, "split", paper=False, wins=2, losses=8, tag="l")
        row = paper_live_expectancy_gap(rule_name="split", days=30)[0]
        self.assertEqual(row["n_paper"], 10)
        self.assertEqual(row["n_live"], 10)
        self.assertAlmostEqual(row["paper_expectancy"], 1.4, places=4)
        self.assertAlmostEqual(row["live_expectancy"], -0.4, places=4)
        self.assertAlmostEqual(row["gap"], -1.8, places=4)

    def test_gap_against_an_unmeasured_venue_is_none_not_zero(self):
        """A rule that has never traded live has no execution gap to report.
        Zero would read as 'the edge survived intact'."""
        from bot_program.bot_grading import paper_live_expectancy_gap
        _seed(self.cfg, "sim_only", paper=True, wins=6, losses=4, tag="p")
        row = paper_live_expectancy_gap(rule_name="sim_only", days=30)[0]
        self.assertEqual(row["n_live"], 0)
        self.assertIsNone(row["live_expectancy"])
        self.assertIsNone(row["gap"])

    def test_a_censored_venue_still_states_its_count(self):
        """The dishonest zero: three live closes under min_n=10 came back as
        `n_live: 0`, which is the same reading a rule that has never gone
        live produces. The count is an observation and survives the
        threshold; the EXPECTANCY is what gets censored, to None."""
        from bot_program.bot_grading import paper_live_expectancy_gap
        _seed(self.cfg, "thin_live", paper=True, wins=6, losses=4, tag="p")
        _seed(self.cfg, "thin_live", paper=False, wins=2, losses=1, tag="l")
        row = paper_live_expectancy_gap(rule_name="thin_live", days=30,
                                        min_n=10)[0]
        self.assertEqual(row["n_live"], 3)
        self.assertIsNone(row["live_expectancy"])
        self.assertEqual(row["n_paper"], 10)
        self.assertIsNotNone(row["paper_expectancy"])
        self.assertIsNone(row["gap"])

    def test_a_censored_count_reads_differently_from_an_empty_venue(self):
        """The point of the previous test stated as the comparison it exists
        to make possible."""
        from bot_program.bot_grading import paper_live_expectancy_gap
        _seed(self.cfg, "thin_live", paper=True, wins=6, losses=4, tag="tp")
        _seed(self.cfg, "thin_live", paper=False, wins=2, losses=1, tag="tl")
        _seed(self.cfg, "never_live", paper=True, wins=6, losses=4, tag="np")
        by_rule = {r["rule_name"]: r
                   for r in paper_live_expectancy_gap(days=30, min_n=10)}
        self.assertNotEqual(by_rule["thin_live"]["n_live"],
                            by_rule["never_live"]["n_live"])

    def test_a_pair_thin_on_both_venues_is_dropped(self):
        """min_n still filters — a rule with nothing to say on either venue
        is not worth a row of Nones."""
        from bot_program.bot_grading import paper_live_expectancy_gap
        _seed(self.cfg, "tiny", paper=True, wins=1, losses=1, tag="p")
        self.assertEqual(
            paper_live_expectancy_gap(rule_name="tiny", days=30, min_n=10), [])


# ── the venue actually reaching the decision ─────────────────────────────

class DecidePathVenueTests(TestCase):
    """`decide()` must NAME the venue, or the bot-trade lane never runs.

    `rule_weight` skips that lane whenever the venue is unstated — a
    deliberate refusal to weigh an order with a pooled number. So a
    `weighted_consensus` call with no venue does not fall back to pooled, it
    drops the bot-trade evidence entirely, on paper and live alike. The lane
    is only reachable from production if `decide()` plumbs the config's mode
    through.
    """

    def setUp(self):
        self.user = _user("decide_u")
        self.inst = _instrument("DSYM")
        # Proven in the simulator, never filled live: 9 wins at +2R and one
        # loss at -1R clamps to the 1.5 ceiling on paper and leaves live with
        # nothing to say.
        cfg = _abc(self.user, "stock", name="Dseed", symbols=["DSYM"])
        _seed(cfg, "sim_star", paper=True, wins=9, losses=1, tag="p")
        _signal(self.inst, "bullish", 0.85, "sim_star")

    def _decide(self, mode):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _abc(self.user, "stock", name=f"D{mode}", mode=mode,
                   symbols=["DSYM"])
        return StockBot(cfg).decide("DSYM")

    def test_a_paper_config_gets_its_paper_evidence_back(self):
        """0.85 × the 1.5 paper multiplier, capped at 1.0. Without the venue
        the lane is skipped and the score is the bare 0.85 — the evidence
        this whole module exists to route was reaching neither venue."""
        d = self._decide("paper")
        self.assertEqual(d.direction, "BUY")
        self.assertEqual(d.score, 1.0)

    def test_a_live_config_is_not_lent_the_paper_record(self):
        """Same signal, same rule, no live fills — so a neutral 1.0 weight
        and the raw consensus score."""
        d = self._decide("live")
        self.assertEqual(d.direction, "BUY")
        self.assertAlmostEqual(d.score, 0.85, places=4)

    def test_the_two_modes_do_not_produce_the_same_score(self):
        """The defect in one line: before the venue was plumbed through,
        these were equal — both at the unweighted 0.85."""
        self.assertNotEqual(self._decide("paper").score,
                            self._decide("live").score)

    def test_the_venue_passed_is_the_one_the_fill_lands_on(self):
        from bot_program.asset_engine import aggregation
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.bot_grading import VENUE_LIVE, VENUE_PAPER
        real = aggregation.weighted_consensus
        for mode, expected in (("paper", VENUE_PAPER), ("live", VENUE_LIVE)):
            seen = {}

            def spy(*a, _seen=seen, **kw):
                _seen["venue"] = kw.get("venue")
                return real(*a, **kw)

            cfg = _abc(self.user, "stock", name=f"S{mode}", mode=mode,
                       symbols=["DSYM"])
            with patch.object(aggregation, "weighted_consensus",
                              side_effect=spy):
                StockBot(cfg).decide("DSYM")
            self.assertEqual(seen["venue"], expected, mode)


class TrackRecordFeedbackVenueTests(TestCase):
    """The OTHER feedback path — `_apply_track_record`, reached when a config
    sets use_weighted_consensus False and use_bot_track_record True. It read
    the pooled record, so paper fills went on scaling a live config's entry
    score there after the weighted path had stopped letting them."""

    def setUp(self):
        self.user = _user("atr_u")
        self.inst = _instrument("ASYM")
        cfg = _abc(self.user, "stock", name="Aseed", symbols=["ASYM"])
        # Works in the simulator, loses money in the book.
        _seed(cfg, "split", paper=True, wins=8, losses=2, tag="p")
        _seed(cfg, "split", paper=False, wins=2, losses=8, tag="l")
        _signal(self.inst, "bullish", 0.85, "split")

    def _decide(self, mode):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _abc(self.user, "stock", name=f"A{mode}", mode=mode,
                   symbols=["ASYM"],
                   extras={"use_weighted_consensus": False,
                           "use_bot_track_record": True})
        return StockBot(cfg).decide("ASYM")

    def test_a_live_config_is_scored_by_its_live_record(self):
        """win_rate 0.20, avg_r -0.4 → ×0.66, so 0.85 shrinks to 0.561. The
        pooled multiplier is above 1.0 and would have capped the score at
        1.0 instead — the book saying 'shrink this' read as 'grow it'."""
        from bot_program.bot_grading import VENUE_ALL, bot_trade_track_record
        d = self._decide("live")
        self.assertEqual(d.direction, "BUY")
        self.assertAlmostEqual(d.score, 0.561, places=3)
        self.assertGreater(
            bot_trade_track_record("split", "stock", venue=VENUE_ALL), 1.0)

    def test_a_paper_config_is_scored_by_its_paper_record(self):
        """The mirror: the paper record is strong, so the paper config's
        score is raised (and capped at 1.0), not lowered by live losses."""
        d = self._decide("paper")
        self.assertEqual(d.score, 1.0)

    def test_the_venue_reaches_the_ledger_call(self):
        from bot_program import bot_grading
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.bot_grading import VENUE_LIVE
        seen = {}
        real = bot_grading.bot_trade_track_record

        def spy(*a, **kw):
            seen["venue"] = kw.get("venue")
            return real(*a, **kw)

        cfg = _abc(self.user, "stock", name="Aspy", mode="live",
                   symbols=["ASYM"],
                   extras={"use_weighted_consensus": False,
                           "use_bot_track_record": True})
        with patch.object(bot_grading, "bot_trade_track_record",
                          side_effect=spy):
            StockBot(cfg).decide("ASYM")
        self.assertEqual(seen["venue"], VENUE_LIVE)


# ── the loud failure has to be reachable to be worth claiming ────────────

class VenueTypoIsLoudTests(TestCase):
    """`_venue_filter` raises on an unknown venue and the docstring claimed
    that protected the call site where it costs money. It could not: the
    membership guard in `rule_weight` skipped the query before it ran, and
    the broad `except` around that query would have logged the rest away. The
    check now lives where the venue is chosen."""

    def test_rule_weight_raises_on_a_typo(self):
        from bot_program.asset_engine.aggregation import rule_weight
        with self.assertRaises(ValueError):
            rule_weight("any", "stock", signal_stats={}, venue="Live")

    def test_rule_weight_refuses_the_pooled_venue_by_name(self):
        """Not a typo — a caller asking the decision path for paper+live
        pooled is asking for the original bug, spelled correctly."""
        from bot_program.asset_engine.aggregation import rule_weight
        from bot_program.bot_grading import VENUE_ALL
        with self.assertRaises(ValueError):
            rule_weight("any", "stock", signal_stats={}, venue=VENUE_ALL)

    def test_unstated_is_a_statement_not_a_typo(self):
        """None still means 'I did not say', and still skips the lane."""
        from bot_program.asset_engine.aggregation import rule_weight
        self.assertEqual(rule_weight("any", "stock", signal_stats={}), 1.0)

    def test_a_quiet_tick_raises_too(self):
        """Validated on entry to weighted_consensus, not lazily inside the
        per-rule weighting: otherwise a typo hides until the first tick that
        has something to weigh, which is the first tick that trades."""
        from bot_program.asset_engine.aggregation import weighted_consensus
        with self.assertRaises(ValueError):
            weighted_consensus([], [], asset_class="stock", venue="paper ")

    def test_a_ledger_venue_error_is_not_logged_away(self):
        """The second suppression: even had the guard let it through, the
        except turned the ledger's ValueError into a neutral 1.0."""
        from bot_program import bot_grading
        from bot_program.asset_engine.aggregation import rule_weight
        with patch.object(bot_grading, "bot_track_record_detail",
                          side_effect=ValueError("venue must be one of ...")):
            with self.assertRaises(ValueError):
                rule_weight("any", "stock", signal_stats={}, venue="live")

    def test_a_ledger_outage_is_still_neutral_rather_than_fatal(self):
        """The mirror image, guarded against: a database that cannot answer
        is missing evidence, not a programming error, and must not take the
        bot down mid-tick."""
        from bot_program import bot_grading
        from bot_program.asset_engine.aggregation import rule_weight
        with patch.object(bot_grading, "bot_track_record_detail",
                          side_effect=RuntimeError("db unreachable")):
            self.assertEqual(
                rule_weight("any", "stock", signal_stats={}, venue="live"),
                1.0)
