"""THE TICKET'S WORDS AND ITS RECORD (review 2026-10-07, PR49 findings #2
and #14).

#2: the TAKE TRADE proof warning (manual_trade.proof_advisory) said "the
bots take it at 0.25x of their size" for every verdict short of proven,
whatever the rule's promotion stage. The bots never ask the proof of a
rule they trade on paper (base.py: live mode and not force_paper), a
research rule gets no orders at all, and the proof does not cut a
live_small rule twice (proof.stage_with_proof). The tail is now read off
signals.rule_actuator.stage_policy, and the reason no longer carries
proof.py's "— entered at 0.25x", which sat in the same box as "this
ticket is yours to send, at the size you chose".

#14: what a live TAKE TRADE booking records of the warnings it was taken
past (extra["proof_advisory_at_entry"], extra["timing_advisory_at_entry"])
was pinned only by source substrings. Here the live booking path runs end
to end (manual_trade._execute through execute_take_trade, a mocked live
client) with proof.GATE and entry_timing.GATE ON, which tests/__init__.py
turns off for the rest of the suite: a FAILED rule on a shut exchange
books a row that records both, a PROVEN rule in session records neither.

Run with:  python manage.py test tests.test_ticket_records
"""
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from backtester.proving import proof
from bot_program import entry_timing as et

UTC = dt_timezone.utc
BOLL = "bollinger_squeeze_breakout"
ROUTER = "bot_program.engine.broker_router.client_for_symbol"
#: Wednesday 03:00 UTC: the NYSE has been shut since Tuesday's close, and
#: was shut CLOSE_GRACE_S before too (a booking Morgul G1 would flag).
NYSE_SHUT = datetime(2026, 10, 7, 3, 0, tzinfo=UTC)
#: Wednesday 15:00 UTC (11:00 New York): in session, past the first
#: quarter hour and clear of the last ten minutes.
NYSE_OPEN = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)


def _verdict(rule, cls, side, verdict, *, exp=0.21, oe=0.14, lb=0.05,
             n=140):
    """One saved live-rules row (prove_live_rules' shape: rules- prefix,
    4h, care, none, generated False) — the row proof.newest_verdict
    reads."""
    from backtester.models_proving import ProvingVerdict
    return ProvingVerdict.objects.create(
        run_id="rules-tr1", family="bb_squeeze", live_rule=rule,
        direction=side, filter=proof.FILTER, policy=proof.POLICY,
        asset_class=cls, timeframe=proof.TIMEFRAME, generated=False,
        verdict=verdict, expectancy=exp, holdout_expectancy=oe,
        lower_bound=lb, trades_n=n, holdout_n=n // 4,
        why=f"{verdict} on {cls} {side}")


def _stage(rule, stage):
    from signals.models import RuleControl
    RuleControl.objects.update_or_create(
        rule_name=rule, defaults={"status": "active",
                                  "promotion_stage": stage,
                                  "stage_entered_at": timezone.now()})


def _on(test, module, attr="GATE"):
    p = mock.patch.object(module, attr, True)
    p.start()
    test.addCleanup(p.stop)


# ── #2: the ticket says what the bots do with the rule ───────────────────

class TheProofWarningReadsTheStageTests(TestCase):

    def setUp(self):
        _on(self, proof)
        self.inst = SimpleNamespace(symbol="PG", asset_class="stock",
                                    exchange="NYSE")
        self.sig = SimpleNamespace(rule_name=BOLL)

    def _adv(self):
        from bot_program.manual_trade import proof_advisory
        adv = proof_advisory(self.sig, self.inst, "BUY")
        self.assertFalse(adv["ok"], adv)
        # never the bots' entry size on a ticket the operator sizes
        self.assertNotIn("entered at", adv["reason"])
        return adv

    def test_a_paper_stage_rule_is_traded_on_paper_only(self):
        _stage(BOLL, "paper")
        adv = self._adv()
        self.assertEqual(adv["tier"], proof.UNPROVEN)
        self.assertTrue(adv["reason"].endswith(
            " — the bots trade this rule on paper only"), adv)
        self.assertNotIn("0.25x", adv["reason"])

    def test_a_rule_with_no_promotion_record_is_paper_only_too(self):
        adv = self._adv()
        self.assertTrue(adv["reason"].endswith(
            " — the bots trade this rule on paper only"), adv)

    def test_a_research_rule_gets_no_orders(self):
        _stage(BOLL, "research")
        adv = self._adv()
        self.assertTrue(adv["reason"].endswith(
            " — the bots send this rule no orders"), adv)
        self.assertNotIn("0.25x", adv["reason"])

    def test_a_live_small_rule_is_not_cut_twice(self):
        _stage(BOLL, "live_small")
        adv = self._adv()
        self.assertTrue(adv["reason"].endswith(
            " — the bots already take it at their live_small size"), adv)
        self.assertNotIn("0.25x", adv["reason"])

    def test_an_unproven_live_full_rule_is_cut(self):
        _stage(BOLL, "live_full")
        adv = self._adv()
        self.assertEqual(adv["tier"], proof.UNPROVEN)
        self.assertTrue(adv["reason"].startswith("NOT JUDGED stock long: "),
                        adv)
        self.assertTrue(adv["reason"].endswith(
            " — the bots take it at 0.25x of their size"), adv)
        self.assertEqual(adv["reason"].count("0.25x"), 1)

    def test_failed_keeps_its_refusal_words_on_every_stage(self):
        _verdict(BOLL, "stock", "long", "failed", exp=-0.1, oe=-0.2)
        for stage in ("paper", "live_small", "live_full"):
            with self.subTest(stage=stage):
                _stage(BOLL, stage)
                adv = self._adv()
                self.assertEqual(adv["tier"], proof.FAILED)
                self.assertTrue(adv["reason"].endswith(
                    " — the bots send this rule no real money here"), adv)

    def test_a_stage_that_cannot_be_read_keeps_the_cuts_words(self):
        _stage(BOLL, "paper")
        with mock.patch("signals.rule_actuator.stage_policy",
                        side_effect=RuntimeError("no stage")), \
                self.assertLogs("bot_program.manual_trade", level="WARNING"):
            adv = self._adv()
        self.assertTrue(adv["reason"].endswith(
            " — the bots take it at 0.25x of their size"), adv)

    def test_an_unread_verdict_never_says_entered_at(self):
        _stage(BOLL, "live_full")
        unread = proof.unread_proof(BOLL, "stock", "BUY", RuntimeError("x"))
        self.assertIn("entered at 0.25x", unread["words"])
        with mock.patch.object(proof, "proof_for", return_value=unread):
            adv = self._adv()
        self.assertEqual(adv["reason"],
                         "the proving ground's verdict could not be read "
                         "(RuntimeError) — the bots take it at 0.25x of "
                         "their size")

    def test_the_ticket_footer_names_no_bot_action_of_its_own(self):
        import re
        from pathlib import Path
        from django.conf import settings
        html = (Path(settings.BASE_DIR) / "templates" / "base.html"
                ).read_text(encoding="utf-8")
        joined = re.sub(r"'\s*\+\s*'", "", html)    # the JS literals, joined
        block = joined.split("var proofAdv = p.proof_advisory", 1)[1]
        block = block.split("var quoteAdv", 1)[0]
        self.assertIn("A warning, not a block: this ticket is yours to "
                      "send, at the size you chose.", block)
        self.assertNotIn("refuse or cut", block)


# ── #14: the booked row records the warnings it was taken past ──────────

class TheBookedRowRecordsTheWarningsTests(TestCase):
    """A LIVE TAKE TRADE through manual_trade._execute, a mocked live
    client, the proof and the clock ON: the row's metadata is the record a
    review reads to ask whether tickets taken past a warning paid."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tr_book",
                                                        password="x")

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from tests.test_take_trade_live import _arm_live, _components_on
        cache.clear()
        _on(self, proof)
        _on(self, et)
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="PG", defaults={"name": "Procter & Gamble",
                                   "asset_class": "stock",
                                   "exchange": "NYSE", "is_active": True})
        LiveQuote.objects.update_or_create(
            instrument=self.inst, defaults={"last": Decimal("150"),
                                            "source": "etoro"})
        _components_on()
        self.cfg = _arm_live(self.user, "stock")
        _stage(BOLL, "live_full")

    def _signal(self):
        from signals.models import Signal
        return Signal.objects.create(
            instrument=self.inst, signal_type="technical",
            direction="bullish", urgency="high", title="PG bullish",
            description="d", rule_name=BOLL, score=0.8, sub_scores={},
            price_at_signal=Decimal("150"), suggested_entry=Decimal("150"),
            suggested_stop=Decimal("147"), suggested_target=Decimal("156"),
            is_active=True)

    def _book(self, at):
        """Execute a live TAKE TRADE with entry_timing's clock at `at`
        (only the gate's clock: the booking path keeps the wall clock) and
        return the booked row."""
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        client = MagicMock(name="fake_live_client")
        client.ticker.return_value = {"lastPrice": "150"}
        # market_order(symbol, side, qty, ...): filled in full at the mark
        client.market_order.side_effect = lambda *a, **k: {
            "orderId": "71", "symbol": "PG", "side": "BUY",
            "executedQty": str(a[2]), "avgPrice": "150.02",
            "status": "FILLED", "raw": {},
            "protectedOnFill": True, "protectiveOrders": ["72", "73"],
            "protectiveStopId": "73", "protectiveTargetId": "72"}
        with mock.patch(ROUTER, return_value=client), \
                mock.patch.object(et, "timezone",
                                  SimpleNamespace(now=lambda: at)):
            out = execute_take_trade(self.user, self._signal(), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["venue"], "live")
        client.market_order.assert_called_once()
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertFalse(trade.paper)
        return trade

    def test_a_failed_rule_on_a_shut_exchange_books_both_warnings(self):
        """The ticket warns and books (never refused): the FAILED verdict
        and the shut exchange are both on the row, with their tier and
        code."""
        _verdict(BOLL, "stock", "long", "failed", exp=-0.12, oe=-0.2)
        trade = self._book(NYSE_SHUT)
        extra = trade.metadata or {}
        pa = extra.get("proof_advisory_at_entry")
        self.assertIsInstance(pa, dict, extra)
        self.assertEqual(pa["tier"], proof.FAILED)
        self.assertFalse(pa["ok"])
        self.assertTrue(pa["reason"].startswith("FAILED stock long: "), pa)
        self.assertNotIn("entered at", pa["reason"])
        ta = extra.get("timing_advisory_at_entry")
        self.assertIsInstance(ta, dict, extra)
        self.assertEqual(ta["code"], et.SHUT)
        self.assertFalse(ta["ok"])
        self.assertIn("the stock market is shut until Wednesday 13:30 UTC",
                      ta["reason"])

    def test_a_proven_rule_in_session_books_neither(self):
        _verdict(BOLL, "stock", "long", "proven")
        trade = self._book(NYSE_OPEN)
        extra = trade.metadata or {}
        self.assertNotIn("proof_advisory_at_entry", extra)
        self.assertNotIn("timing_advisory_at_entry", extra)

    def test_the_clock_the_gate_reads_is_the_one_patched(self):
        """The seam this file uses: entry_timing's own clock, at the two
        instants above, reads shut and then open on the NYSE."""
        with mock.patch.object(et, "timezone",
                               SimpleNamespace(now=lambda: NYSE_SHUT)):
            self.assertEqual(et.advisory("PG", "stock",
                                         exchange="NYSE")["code"], et.SHUT)
        with mock.patch.object(et, "timezone",
                               SimpleNamespace(now=lambda: NYSE_OPEN)):
            self.assertEqual(et.advisory("PG", "stock", exchange="NYSE"),
                             {"ok": True, "reason": "", "attack": "",
                              "code": ""})
