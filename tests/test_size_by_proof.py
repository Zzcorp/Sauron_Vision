"""SIZE BY PROOF (2026-10-07): real money follows the proving ground's
verdict on the rule, the class and the side.

The order of 2026-10-01 put 36 rules at live_full by hand (reason
manual_promote), most with 0 graded signals, and real money followed the
stage alone. The operator's rule now: for a LIVE bot-lane entry (the
AssetBot lane and the options lane), the newest saved live-rules verdict
for (rule, instrument class, side) decides —

  FAILED       refused (skips.PROVING_FAILED), whatever the graded record;
  PROVEN       full size;
  LIVE_PROVEN  no proving verdict for it, but the rule's own all-time
               graded record proves it on the floor's own measure: full
               size;
  UNPROVEN     anything else (PROMISING, INSUFFICIENT, no saved verdict,
               no side, a class or a rule the proving ground does not
               judge, a verdict that could not be read): the entry is cut
               to REDUCED = SIZE_FACTORS["live_small"] (0.25).

The verdict read is the newest rules- row PER KEY (live_rule, asset_class,
direction) at the live rules' own timeframe, exit policy and filter: a
one-class run does not unjudge the others, compare_exits' rows never
count, and bollinger's short reads its own row. A hand promotion without
proof reads "(by hand, unproven)" wherever its stage is shown, and the
TAKE TRADE ticket only warns. proof.GATE is off for the rest of the suite
(tests/__init__.py) and turned on here where a test needs it.

Run with:  python manage.py test tests.test_size_by_proof
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from backtester.proving import proof
from tests.test_bar_losers import _hand_promoted, _seed_record
from tests.test_promotion_pipeline import _seed_signals, _set_stage

BOLL = "bollinger_squeeze_breakout"


def _verdict(rule, cls, side, verdict, *, run="rules-a1", age_h=0,
             generated=False, policy="care", flt="none", timeframe="4h",
             family="bb_squeeze", exp=0.21, oe=0.14, lb=0.05, n=140,
             why=""):
    """One saved proving row, `age_h` hours old."""
    from backtester.models_proving import ProvingVerdict
    row = ProvingVerdict.objects.create(
        run_id=run, family=family, live_rule=rule, direction=side,
        filter=flt, policy=policy, asset_class=cls, timeframe=timeframe,
        generated=generated, verdict=verdict, expectancy=exp,
        holdout_expectancy=oe, lower_bound=lb, trades_n=n,
        holdout_n=n // 4, why=why or f"{verdict} on {cls} {side}")
    ProvingVerdict.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - timedelta(hours=age_h))
    row.refresh_from_db()
    return row


def _gate_on(test):
    p = mock.patch.object(proof, "GATE", True)
    p.start()
    test.addCleanup(p.stop)


# ── 1. the verdict read ───────────────────────────────────────────────────

class TheVerdictReaderTests(TestCase):

    def test_the_newest_live_rules_row_for_the_key_decides(self):
        _verdict(BOLL, "stock", "long", "proven", run="rules-old", age_h=48)
        _verdict(BOLL, "stock", "long", "failed", run="rules-new", age_h=24,
                 exp=-0.12, oe=-0.2)
        # newer rows that are not the live rule as it trades: none counts
        _verdict(BOLL, "stock", "long", "proven", run="gen-x", generated=True)
        _verdict(BOLL, "stock", "long", "proven", run="exits-x",
                 policy="care")
        _verdict(BOLL, "stock", "long", "proven", run="rules-1h",
                 timeframe="1h")
        _verdict(BOLL, "stock", "long", "proven", run="rules-trend",
                 flt="trend")
        _verdict(BOLL, "stock", "long", "proven", run="rules-trail",
                 policy="trail")
        p = proof.proof_for(BOLL, "stock", "BUY")
        self.assertEqual(p["tier"], proof.FAILED)
        self.assertEqual(p["run_id"], "rules-new")
        self.assertEqual(p["multiplier"], 0.0)

    def test_a_one_class_run_does_not_unjudge_the_others(self):
        _verdict(BOLL, "stock", "long", "failed", run="rules-all", age_h=48,
                 exp=-0.1, oe=-0.1)
        _verdict(BOLL, "crypto", "long", "proven", run="rules-crypto",
                 age_h=1)
        self.assertEqual(proof.proof_for(BOLL, "stock", "BUY")["tier"],
                         proof.FAILED)
        self.assertEqual(proof.proof_for(BOLL, "crypto", "BUY")["tier"],
                         proof.PROVEN)

    def test_bollinger_short_reads_its_own_row(self):
        _verdict(BOLL, "etf", "long", "proven")
        _verdict(BOLL, "etf", "short", "failed", exp=-0.08, oe=-0.11)
        self.assertEqual(proof.proof_for(BOLL, "etf", "SELL")["tier"],
                         proof.FAILED)
        self.assertEqual(proof.proof_for(BOLL, "etf", "BUY")["tier"],
                         proof.PROVEN)

    def test_a_long_only_rule_never_reads_its_short_mirror(self):
        _verdict("rsi_divergence (short mirror)", "stock", "short", "proven",
                 family="rsi_divergence")
        p = proof.proof_for("rsi_bull_divergence", "stock", "SELL")
        self.assertEqual(p["tier"], proof.UNPROVEN)
        self.assertEqual(p["verdict"], "")
        self.assertIn("replays rsi_bull_divergence long only", p["words"])

    def test_the_side_mapping(self):
        for word, side in (("BUY", "long"), ("SELL", "short"),
                           ("long", "long"), ("short", "short"),
                           ("bullish", "long"), ("bearish", "short")):
            with self.subTest(word=word):
                self.assertEqual(proof.side_of(word), side)
        for word in ("", "HOLD"):
            with self.subTest(word=word):
                self.assertEqual(proof.side_of(word), "")
                p = proof.proof_for(BOLL, "stock", word)
                self.assertEqual(p["tier"], proof.UNPROVEN)
                self.assertIn("no side", p["words"])

    def test_an_etf_reads_the_etf_pool_in_a_stock_config(self):
        from bot_program.asset_engine.base import BotDecision
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_entry_quote import _instrument, _live_cfg, _user
        _gate_on(self)
        cfg = _live_cfg(_user("sbp_etf"), name="SBP ETF")
        _instrument("SPY", "etf")
        _verdict(BOLL, "etf", "long", "promising", why="lower bound -0.02R")
        _verdict(BOLL, "stock", "long", "proven")
        p = StockBot(cfg)._proof_gate(
            "SPY", BotDecision("BUY", 0.9, ["s"], rule_name=BOLL))
        self.assertEqual(p["asset_class"], "etf")
        self.assertEqual(p["verdict"], "promising")
        self.assertEqual(p["tier"], proof.UNPROVEN)


# ── 2. the tiers and their words ─────────────────────────────────────────

class TheTiersTests(TestCase):

    def test_proven_keeps_full_size(self):
        _verdict(BOLL, "stock", "long", "proven")
        p = proof.proof_for(BOLL, "stock", "BUY")
        self.assertEqual(p["multiplier"], 1.0)
        self.assertTrue(p["words"].startswith("PROVEN stock long:"),
                        p["words"])
        self.assertIn("full size", p["words"])

    def test_failed_is_refused_with_its_numbers_first(self):
        _verdict(BOLL, "stock", "long", "failed", exp=-0.12, oe=-0.2, n=140)
        p = proof.proof_for(BOLL, "stock", "BUY")
        self.assertEqual(p["multiplier"], 0)
        head = p["words"][:88]
        for part in ("FAILED", "-0.12R", "holdout -0.20R", "140 trades"):
            self.assertIn(part, head)
        for money in ("$", "USD", "EUR"):
            self.assertNotIn(money, p["words"])

    def test_failed_stands_against_a_proving_record(self):
        _verdict(BOLL, "stock", "long", "failed", exp=-0.05, oe=-0.1)
        _seed_record(BOLL, 43, 14, 0.26, "SBPF1")
        p = proof.proof_for(BOLL, "stock", "BUY")
        self.assertEqual(p["tier"], proof.FAILED)
        self.assertEqual(p["record"], {})

    def test_promising_insufficient_and_not_judged_enter_reduced(self):
        from signals.promotion_pipeline import SIZE_FACTORS
        _verdict(BOLL, "stock", "long", "promising")
        _verdict(BOLL, "forex", "long", "insufficient", exp=None, oe=None)
        cases = ((BOLL, "stock"), (BOLL, "forex"),
                 ("smc_composite", "stock"),
                 ("golden_cross_evolved_v2", "stock"),
                 (BOLL, "cfd"))
        self.assertEqual(SIZE_FACTORS["live_small"], 0.25)
        for rule, cls in cases:
            with self.subTest(rule=rule, cls=cls):
                p = proof.proof_for(rule, cls, "BUY")
                self.assertEqual(p["tier"], proof.UNPROVEN)
                self.assertEqual(p["multiplier"], SIZE_FACTORS["live_small"])
                self.assertTrue(p["words"].endswith("entered at 0.25x"),
                                p["words"])
        self.assertIn("judges no cfd class",
                      proof.proof_for(BOLL, "cfd", "BUY")["words"])
        self.assertIn("replays no family for smc_composite",
                      proof.proof_for("smc_composite", "stock",
                                      "BUY")["words"])

    def test_the_rules_own_record_can_prove_it(self):
        _seed_record(BOLL, 43, 14, 0.26, "SBPR1")
        p = proof.proof_for(BOLL, "stock", "BUY")
        self.assertEqual(p["tier"], proof.LIVE_PROVEN)
        self.assertEqual(p["multiplier"], 1.0)
        self.assertIn("both sides, every class", p["words"])
        self.assertTrue(p["words"].startswith("NOT JUDGED stock long — but "
                                              "its own record proves it"),
                        p["words"])
        self.assertEqual(p["record"]["n"], 43)

    def test_a_short_thin_or_losing_record_does_not_prove_it(self):
        _seed_signals("sbp_few", [2.0] * 19)
        _seed_record("sbp_thin", 25, 10, 0.05, "SBPT1")
        _seed_signals("sbp_loser", [-1.0] * 22)
        for rule in ("sbp_few", "sbp_thin", "sbp_loser"):
            with self.subTest(rule=rule):
                p = proof.proof_for(rule, "stock", "BUY")
                self.assertEqual(p["tier"], proof.UNPROVEN)
                self.assertIn("its own record does not prove it",
                              p["words"])

    def test_an_unread_verdict_is_reduced_never_full_never_refused(self):
        from backtester.models_proving import ProvingVerdict
        with mock.patch.object(ProvingVerdict.objects, "filter",
                               side_effect=RuntimeError("db gone")), \
                mock.patch("signals.promotion_pipeline.proven_record"
                           ) as rec, \
                self.assertLogs("backtester.proving.proof", "WARNING"):
            p = proof.proof_for(BOLL, "stock", "BUY")
        rec.assert_not_called()
        self.assertEqual(p["tier"], proof.UNPROVEN)
        self.assertEqual(p["unread"], "RuntimeError")
        self.assertEqual(p["multiplier"], 0.25)
        self.assertIn("could not be read (RuntimeError)", p["words"])
        self.assertIn("never a refusal", p["words"])

    def test_one_read_per_key_per_tick(self):
        _seed_record("sbp_cache", 21, 10, 0.3, "SBPC1")
        cache = {}
        first = proof.proof_for("sbp_cache", "stock", "BUY", cache=cache)
        with self.assertNumQueries(0):
            again = proof.proof_for("sbp_cache", "stock", "BUY", cache=cache)
        self.assertEqual(first, again)
        again["words"] = "changed"
        self.assertNotEqual(proof.proof_for("sbp_cache", "stock", "BUY",
                                            cache=cache)["words"], "changed")


# ── 3. the provenance label ───────────────────────────────────────────────

class TheHandPromotionTests(TestCase):

    def _prov(self, rule):
        from signals.promotion_pipeline import promotion_provenance
        return promotion_provenance(rule)

    def test_by_hand_without_proof_reads_so(self):
        from signals.models import PromotionEvent
        _set_stage("sbp_hand", "live_full")
        ev = _hand_promoted("sbp_hand", 2)
        self.assertEqual(ev.n_at_transition, 0)
        self.assertIsNone(PromotionEvent.objects.get(
            pk=ev.pk).expectancy_at_transition)
        prov = self._prov("sbp_hand")
        self.assertEqual(prov["label"], "live_full (by hand, unproven)")
        self.assertTrue(prov["unproven"])
        self.assertTrue(prov["words"].startswith(
            "promoted to live_full by hand on"), prov["words"])
        self.assertIn("with 0 graded signals (proof needs 20 at +0.10R)",
                      prov["words"])
        self.assertTrue(prov["words"].endswith("; not proven since"))

    def test_by_hand_and_proven_since_reads_so(self):
        _set_stage("sbp_hand2", "live_full")
        _hand_promoted("sbp_hand2", 2)
        _seed_record("sbp_hand2", 43, 14, 0.26, "SBPH2")
        prov = self._prov("sbp_hand2")
        self.assertEqual(prov["label"], "live_full (by hand, proven since)")
        self.assertFalse(prov["unproven"])
        self.assertIn("; proven since: 43 graded signals all time, "
                      "expectancy +0.26R", prov["words"])

    def test_proven_or_automatic_promotions_read_plain_and_no_event_is_said(self):
        from signals.models import PromotionEvent
        _set_stage("sbp_auto", "live_full")
        PromotionEvent.objects.create(rule_name="sbp_auto",
                                      from_stage="live_small",
                                      to_stage="live_full",
                                      reason="auto_promote")
        self.assertEqual(self._prov("sbp_auto")["label"], "live_full")
        _set_stage("sbp_then", "live_full")
        PromotionEvent.objects.create(rule_name="sbp_then",
                                      from_stage="paper",
                                      to_stage="live_full",
                                      reason="manual_promote",
                                      n_at_transition=25,
                                      expectancy_at_transition=0.30)
        self.assertEqual(self._prov("sbp_then")["label"], "live_full")
        _set_stage("sbp_none", "live_full")
        self.assertEqual(self._prov("sbp_none")["label"],
                         "live_full (no promotion recorded, unproven)")
        _set_stage("sbp_paper", "paper")
        self.assertEqual(self._prov("sbp_paper")["label"], "paper")

    def test_a_demotion_does_not_launder_the_hand_promotion(self):
        from signals.models import PromotionEvent
        _hand_promoted("sbp_demo", 5)
        PromotionEvent.objects.create(rule_name="sbp_demo",
                                      from_stage="live_full",
                                      to_stage="live_small",
                                      reason="auto_demote")
        _set_stage("sbp_demo", "live_small")
        self.assertEqual(self._prov("sbp_demo")["label"],
                         "live_small (by hand, unproven)")

    def test_a_proving_ground_proof_reads_as_proven(self):
        _set_stage("sbp_pg", "live_full")
        _hand_promoted("sbp_pg", 2)
        _verdict("sbp_pg", "stock", "long", "proven", age_h=10)
        prov = self._prov("sbp_pg")
        self.assertEqual(prov["label"], "live_full (by hand, proven since)")
        self.assertIn("the proving ground proves it on stock long",
                      prov["words"])
        # an older PROVEN under a newer FAILED for the same key is no proof
        _verdict("sbp_pg", "stock", "long", "failed", age_h=1, exp=-0.1,
                 oe=-0.1)
        self.assertEqual(self._prov("sbp_pg")["label"],
                         "live_full (by hand, unproven)")


# ── 4. the bot lane ───────────────────────────────────────────────────────

class TheBotLaneTests(TestCase):
    """A live StockBot on AAPL at 100 whose rule sits at live_full. The
    pool's PROVEN size is a whole multiple of four shares, so a quarter of
    it survives whole-share rounding exactly."""

    RULE = "sbp_rule"

    def setUp(self):
        from tests.test_entry_quote import (_book, _instrument, _live_cfg,
                                            _signal, _user)
        _gate_on(self)
        self.user = _user("sbp_bot")
        self.cfg = _live_cfg(self.user, name="SBP")
        _signal(_instrument(), rule=self.RULE)
        _book(self.user)

    def _client(self):
        from tests.test_entry_quote import _mock_client
        client = _mock_client("100.00")
        client.ticker.return_value = {"lastPrice": "100.00", "bid": "99.98",
                                      "ask": "100.02", "symbol": "AAPL"}
        client.market_order.side_effect = lambda symbol, side, qty, **kw: {
            "orderId": "sbp-1", "status": "FILLED", "avgPrice": "100.00",
            "executedQty": str(qty)}
        return client

    def _propose(self, client=None):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_entry_quote import ROUTER
        self.bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=client or self._client()):
            return self.bot.propose_entry("AAPL")

    def _skip_note(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)["AAPL"]

    def test_failed_is_a_proving_failed_skip_before_the_size(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.stock_bot import StockBot
        _verdict(self.RULE, "stock", "long", "failed", exp=-0.12, oe=-0.2)
        with mock.patch.object(StockBot, "_size_for_entry") as size:
            cand = self._propose()
        self.assertIsNone(cand)
        size.assert_not_called()
        note = self._skip_note()
        self.assertEqual(note["code"], skips.PROVING_FAILED)
        self.assertTrue(note["detail"].startswith("FAILED"), note)

    def test_unproven_live_full_enters_at_a_quarter(self):
        row = _verdict(self.RULE, "stock", "long", "proven")
        full = self._propose()
        self.assertIsNotNone(full)
        self.assertEqual(full.stage["proof"]["tier"], proof.PROVEN)
        self.assertEqual(full.qty_default % 4, 0, full.qty_default)
        row.delete()
        cut = self._propose()
        self.assertIsNotNone(cut)
        self.assertAlmostEqual(cut.qty_default, 0.25 * full.qty_default)
        self.assertAlmostEqual(cut.risk_dollars_default,
                               0.25 * full.risk_dollars_default)
        self.assertEqual(cut.stage["live_size_factor"], 0.25)
        self.assertEqual(cut.stage["proof"]["tier"], proof.UNPROVEN)
        self.assertEqual(cut.stage["proof"]["cut"], 0.25)

    def test_live_small_is_not_cut_twice(self):
        _set_stage(self.RULE, "live_small")
        cand = self._propose()
        self.assertIsNotNone(cand)
        self.assertEqual(cand.stage["live_size_factor"], 0.25)
        self.assertEqual(cand.stage["proof"]["tier"], proof.UNPROVEN)
        self.assertEqual(cand.stage["proof"]["cut"], 1.0)

    def test_aragorn_probation_still_multiplies(self):
        pol = {"state": "probation", "force_paper": False, "size": 0.25,
               "reason": "aragorn: probation"}
        with mock.patch("bot_program.aragorn.pair_policy", return_value=pol):
            cand = self._propose()
        self.assertIsNotNone(cand)
        self.assertAlmostEqual(cand.stage["live_size_factor"], 0.0625)

    def test_a_paper_config_and_a_paper_bound_entry_never_read_it(self):
        from tests.test_entry_quote import _live_cfg
        with mock.patch.object(proof, "proof_for",
                               wraps=proof.proof_for) as pf:
            self.cfg = _live_cfg(self.user, mode="paper", name="SBP paper")
            # a candidate: the proposal went past where the gate sits, so
            # the gate was not merely never reached
            paper = self._propose()
            self.assertIsNotNone(paper)
            self.assertNotIn("proof", paper.stage)
            pf.assert_not_called()
            # a live config whose pair Aragorn benched: paper-bound, so a
            # FAILED verdict neither refuses nor cuts it
            self.cfg = _live_cfg(self.user, name="SBP bench")
            _verdict(self.RULE, "stock", "long", "failed")
            bench = {"state": "bench", "force_paper": True, "size": 1.0,
                     "reason": "aragorn: benched"}
            with mock.patch("bot_program.aragorn.pair_policy",
                            return_value=bench):
                cand = self._propose()
            pf.assert_not_called()
        self.assertIsNotNone(cand)
        self.assertEqual(cand.venue, "paper")
        self.assertNotIn("proof", cand.stage)

    def _execute(self, cand, client):
        from tests.test_entry_quote import ROUTER
        with mock.patch(ROUTER, return_value=client), \
                mock.patch("time.sleep"):
            return self.bot.execute_entry(cand)

    def test_the_row_carries_the_proof_and_the_label(self):
        from bot_program.models import AssetBotTrade
        _hand_promoted(self.RULE, 2)
        client = self._client()
        cand = self._propose(client)
        self.assertIsNotNone(cand)
        res = self._execute(cand, client)
        if res is None:
            self.fail(f"nothing booked: {self._skip_note()}")
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        meta = trade.metadata
        self.assertEqual(meta["proof"]["tier"], proof.UNPROVEN)
        self.assertEqual(meta["proof"]["words"], cand.stage["proof"]["words"])
        self.assertEqual(meta["proof"]["cut"], 0.25)
        self.assertEqual(meta["promotion_stage"],
                         "live_full (by hand, unproven)")

    def test_gate_off_changes_nothing(self):
        from bot_program.models import AssetBotTrade
        _hand_promoted(self.RULE, 2)
        client = self._client()
        with mock.patch.object(proof, "GATE", False), \
                mock.patch.object(proof, "proof_for") as pf:
            cand = self._propose(client)
            self.assertIsNotNone(cand)
            res = self._execute(cand, client)
        pf.assert_not_called()
        self.assertIsNotNone(res)
        self.assertNotIn("proof", cand.stage)
        meta = AssetBotTrade.objects.get(id=res["trade_id"]).metadata
        self.assertNotIn("proof", meta)
        self.assertEqual(meta["promotion_stage"], "live_full")

    def test_a_cut_too_small_to_trade_names_the_cut(self):
        from bot_program.asset_engine import skips
        # a pool whose full size is under four shares: a quarter of it
        # floors to none
        self.cfg.capital = Decimal("1000")
        self.cfg.save(update_fields=["capital"])
        row = _verdict(self.RULE, "stock", "long", "proven")
        full = self._propose()
        self.assertIsNotNone(full)
        self.assertLess(full.qty_default, 4)
        row.delete()
        self.assertIsNone(self._propose())
        note = self._skip_note()
        self.assertEqual(note["code"], skips.SIZED_TO_ZERO)
        self.assertTrue(note["detail"].startswith("unproven 0.25x: "), note)

    def test_a_send_refusal_the_cut_causes_names_the_cut(self):
        from alerts.models import Notification
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.stock_bot import StockBot
        client = self._client()
        cand = self._propose(client)
        self.assertEqual(cand.stage["proof"]["cut"], 0.25)
        with mock.patch.object(StockBot, "_venue_size_floor",
                               return_value=(cand.qty_default * 4, "")):
            self.assertIsNone(self._execute(cand, client))
        note = self._skip_note()
        self.assertEqual(note["code"], skips.VENUE_MIN_SIZE)
        self.assertTrue(note["detail"].startswith("unproven 0.25x: "), note)
        sent = Notification.objects.filter(user=self.user,
                                           notification_type="bot")
        self.assertEqual(sent.count(), 1)
        self.assertIn("unproven 0.25x", sent.get().body)
        self.assertIn("the proving ground's cut", sent.get().body)
        client.market_order.assert_not_called()
        with mock.patch.object(StockBot, "_venue_fee_refusal",
                               return_value=(0.0, "the venue's fee leaves "
                                                  "no edge")):
            self.assertIsNone(self._execute(cand, client))
        note = self._skip_note()
        self.assertEqual(note["code"], skips.COST_FILTER)
        self.assertTrue(note["detail"].startswith("unproven 0.25x: "), note)
        client.market_order.assert_not_called()
        # 2026-10-07: a binding Executioner scales the quarter again, and
        # the smaller ticket falls under the venue's floor the quarter
        # alone cleared — the refusal names the proof's cut first too
        with mock.patch.object(StockBot, "_venue_size_floor",
                               return_value=(cand.qty_default - 1, "")), \
                mock.patch("ai_agents.agents.trade_debate.debate_candidate",
                           return_value={"on": True, "binding": True,
                                         "scale": 0.5,
                                         "why": "a thin edge"}):
            self.assertIsNone(self._execute(cand, client))
        note = self._skip_note()
        self.assertEqual(note["code"], skips.SIZED_TO_ZERO)
        self.assertTrue(note["detail"].startswith(
            "unproven 0.25x: the Executioner cut it to 0.5x: "), note)
        client.market_order.assert_not_called()


# ── 5. the options lane ───────────────────────────────────────────────────

class TheOptionsLaneTests(TestCase):
    """The options lane never meets propose_entry: the proof is read on the
    UNDERLYING's class and the decision's side on its own path."""

    RULE = "sbp_opt_rule"

    def setUp(self):
        from tests.test_paper_market_hours import _user
        _gate_on(self)
        self.user = _user("sbp_opt")
        self.n = 0

    def _scan(self, client, stage="live_full"):
        from bot_program.asset_engine.base import BotDecision
        from bot_program.asset_engine.options_bot import OptionsBot
        from bot_program.models import AssetBotConfig
        from bot_program.options_models import OptionContract
        from portfolio.risk_gate import limits_book
        from signals.models import RuleControl
        from tests.test_paper_market_hours import ROUTER, _inst
        RuleControl.objects.update_or_create(
            rule_name=self.RULE,
            defaults={"status": "active", "promotion_stage": stage,
                      "stage_entered_at": timezone.now()})
        pf = limits_book()
        pf.current_value = Decimal("10000")
        pf.max_single_position_pct = 100.0
        pf.save()
        inst = _inst("AAPL", "stock")
        self.n += 1
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="options", name=f"sbp_opt_{self.n}",
            enabled=True, mode="live", symbols=["AAPL"],
            capital=Decimal("1000000"), stop_loss_pct=20.0,
            take_profit_pct=50.0)
        OptionContract.objects.get_or_create(
            underlying=inst, strike=Decimal("180"),
            expiry=timezone.now().date() + timedelta(days=30), right="C",
            defaults=dict(multiplier=100, bid=Decimal("1.00"),
                          ask=Decimal("1.02"), last_price=Decimal("1.01"),
                          iv=0.30, delta=0.41))
        bot = OptionsBot(cfg)
        corr = {"scale": 1.0, "max_corr": 0.0, "peer": "",
                "threshold": 0.7, "measured": True, "reason": ""}
        with mock.patch.object(bot, "decide", return_value=BotDecision(
                "BUY", 0.9, ["signal"], rule_name=self.RULE)), \
                mock.patch(ROUTER, return_value=client), \
                mock.patch("portfolio.risk_gate.correlation_state",
                           return_value=corr):
            out = bot.scan_symbol("AAPL")
        return cfg, out

    @staticmethod
    def _client():
        client = mock.MagicMock(name="fake_live_options_client")
        client.market_order_option.side_effect = RuntimeError("socket closed")
        return client

    def test_the_options_lane_reads_the_underlyings_verdict(self):
        # FAILED on the underlying's class and side: refused, nothing sent
        row = _verdict(self.RULE, "stock", "long", "failed", exp=-0.2,
                       oe=-0.3)
        client = self._client()
        cfg, out = self._scan(client)
        self.assertIsNone(out)
        client.market_order_option.assert_not_called()
        cfg.refresh_from_db()
        skip = (cfg.extras.get("skips") or {}).get("AAPL") or {}
        self.assertEqual(skip.get("code"), "proving_failed")
        self.assertTrue(skip.get("detail", "").startswith("FAILED stock long"))
        # PROVEN: the full contract count
        row.verdict = "proven"
        row.save(update_fields=["verdict"])
        client = self._client()
        self._scan(client)
        client.market_order_option.assert_called_once()
        full = client.market_order_option.call_args.kwargs["contracts"]
        # no verdict and no record: the count a 0.25 stage factor gives —
        # the same as a live_small rule's, which the proof does not cut
        row.delete()
        client = self._client()
        self._scan(client)
        cut = client.market_order_option.call_args.kwargs["contracts"]
        client = self._client()
        self._scan(client, stage="live_small")
        small = client.market_order_option.call_args.kwargs["contracts"]
        self.assertEqual(cut, small)
        self.assertLess(cut, full)
        self.assertGreater(cut, 0)


# ── 6. the wiring ─────────────────────────────────────────────────────────

class TheWiringTests(SimpleTestCase):

    def test_the_gate_sits_after_aragorn_and_before_the_size(self):
        import inspect
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.options_bot import OptionsBot
        src = inspect.getsource(AssetBot.propose_entry)
        self.assertLess(src.index("self._aragorn_and_posture("),
                        src.index("self._proof_gate("))
        self.assertLess(src.index("self._proof_gate("),
                        src.index("self._size_for_entry(symbol, price, sl, "
                                  "decision)"))
        src = inspect.getsource(AssetBot.execute_entry)
        self.assertLess(src.index('entry_meta["proof"]'),
                        src.index("debate_candidate(self, cand, qty)"))
        src = inspect.getsource(OptionsBot.scan_symbol)
        self.assertLess(src.index("proof.proof_for("),
                        src.index('raw *= float(stage["live_size_factor"])'))

    def test_the_skip_code_has_its_advice_and_its_words(self):
        import inspect
        from bot_program.asset_engine import skips
        from bot_program.telegram_eye import SKIP_WORDS
        self.assertEqual(skips.PROVING_FAILED, "proving_failed")
        self.assertIn("PROVING_FAILED:", inspect.getsource(skips.diagnose))
        self.assertIn("proving_failed", SKIP_WORDS)
        for money in ("$", "USD", "EUR"):
            self.assertNotIn(money, SKIP_WORDS["proving_failed"])

    def test_the_suite_switch_the_run_prefix_and_the_reduced_size(self):
        import inspect
        from backtester.proving import run
        base = Path(settings.BASE_DIR)
        self.assertIn("_proof.GATE = False",
                      (base / "tests" / "__init__.py").read_text(
                          encoding="utf-8"))
        self.assertIn("RULES_RUN_PREFIX",
                      inspect.getsource(run.prove_live_rules))
        self.assertEqual(run.RULES_RUN_PREFIX, "rules-")
        self.assertIn('SIZE_FACTORS["live_small"]',
                      (base / "backtester" / "proving" / "proof.py")
                      .read_text(encoding="utf-8"))
        self.assertEqual(proof.REDUCED, 0.25)


# ── 7. the manual lane only warns ─────────────────────────────────────────

class TheManualLaneTests(TestCase):

    def setUp(self):
        _gate_on(self)
        self.inst = SimpleNamespace(symbol="AAPL", asset_class="stock",
                                    exchange="NASDAQ")
        self.sig = SimpleNamespace(rule_name=BOLL)

    def test_the_ticket_warns_and_never_refuses_or_resizes(self):
        from bot_program.manual_trade import proof_advisory
        row = _verdict(BOLL, "stock", "long", "failed", exp=-0.1, oe=-0.2)
        adv = proof_advisory(self.sig, self.inst, "BUY")
        self.assertFalse(adv["ok"])
        self.assertEqual(adv["tier"], proof.FAILED)
        self.assertTrue(adv["reason"].endswith("no real money here"), adv)
        row.delete()
        adv = proof_advisory(self.sig, self.inst, "BUY")
        self.assertFalse(adv["ok"])
        self.assertTrue(adv["reason"].endswith("at 0.25x of their size"),
                        adv)
        _verdict(BOLL, "stock", "long", "proven")
        self.assertTrue(proof_advisory(self.sig, self.inst, "BUY")["ok"])
        self.assertTrue(proof_advisory(self.sig, self.inst, "SELL",
                                       live=False)["ok"])
        self.assertTrue(proof_advisory(None, self.inst, "SELL")["ok"])

    def test_the_preview_the_booking_and_the_popup_carry_it_without_blocking(self):
        base = Path(settings.BASE_DIR)
        manual = (base / "bot_program" / "manual_trade.py").read_text(
            encoding="utf-8")
        self.assertIn('"proof_advisory": proof_advisory(signal, inst, side, '
                      'live=live),', manual)
        self.assertIn('extra["proof_advisory_at_entry"]', manual)
        html = (base / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("p.proof_advisory", html)
        self.assertIn("THIS RULE IS NOT PROVEN HERE", html)
        self.assertIn("THE PROVING GROUND FAILED THIS RULE HERE", html)
        expr = html.split("okBtn.disabled = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("proofAdv", expr)
        self.assertNotIn("proof_advisory", expr)


# ── 8. every stage display says it ────────────────────────────────────────

class TheShownStageTests(TestCase):

    RULE = "sbp_shown"

    def setUp(self):
        _set_stage(self.RULE, "live_full")
        _hand_promoted(self.RULE, 2)

    def test_bar_losers_reads_a_hand_promotion_without_proof(self):
        out = StringIO()
        call_command("bar_losers", stdout=out)
        text = out.getvalue()
        lines = text.splitlines()
        i = next(k for k, l in enumerate(lines)
                 if l.startswith(f"  {self.RULE} "))
        self.assertIn("live_full (by hand, unproven)", lines[i])
        self.assertTrue(lines[i].rstrip().endswith("unmeasured (n 0 < 20)"),
                        lines[i])
        self.assertTrue(lines[i + 1].startswith(
            "    promoted to live_full by hand on"), lines[i + 1])
        self.assertIn("rule(s) at a live stage", text)
        self.assertIn("floor: 20 graded signals and expectancy <= 0R, or "
                      "hit < 35% with expectancy < 0.10R", text)

    def test_the_promotions_page_reads_it_too(self):
        staff = User.objects.create_user("sbp_staff", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        from django.urls import reverse
        resp = self.client.get(reverse("promotions_dashboard"),
                               HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "by hand, unproven")

    def test_every_other_stage_display_reads_it(self):
        from django.urls import reverse
        from bot_program import evidence
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from dashboard import views_forensics
        from signals.models import RuleMutation
        from signals.models_opportunity import OpportunitySetup
        staff = User.objects.create_user("sbp_staff2", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        OpportunitySetup.objects.create(
            name=self.RULE, direction="bullish", asset_classes=["stock"],
            is_active=True,
            conditions=[{"kind": "price_pattern",
                         "params": {"ma_period": 50}}])
        resp = self.client.get(reverse("strategies_list"),
                               HTTP_HOST="127.0.0.1")
        self.assertContains(resp, "by hand, unproven")
        with mock.patch("dashboard.views_setups._diagnostic",
                        return_value=None):
            resp = self.client.get("/setups/", HTTP_HOST="127.0.0.1")
        self.assertContains(resp, "by hand, unproven")
        out = StringIO()
        call_command("setups", "list", stdout=out, stderr=out)
        self.assertIn("live_full (by hand, unproven)", out.getvalue())
        rows = {r["rule"]: r for r in evidence.rule_rows()}
        self.assertEqual(rows[self.RULE]["stage_note"], "by hand, unproven")
        cfg = AssetBotConfig.objects.create(
            user=staff, asset_class="stock", name="SBP forensics",
            mode="live", symbols=["AAPL"], capital=Decimal("10000"))
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), status="OPEN", paper=False,
            rule_name=self.RULE)
        state = views_forensics._rule_state(trade)
        self.assertEqual(state["stage_note"], "by hand, unproven")
        RuleMutation.objects.create(
            parent_rule=self.RULE, parent_params={"fast": 50},
            mutated_params={"fast": 30}, parameters_changed=["fast"],
            parent_expectancy=0.2, proposed_score=0.3,
            score_method="walk_forward", state=RuleMutation.STATE_PROPOSED)
        resp = self.client.get("/evolution/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "by hand, unproven")
