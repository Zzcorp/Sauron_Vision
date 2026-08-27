"""TradingView alerts arrive as signals, never as orders.

The boundary is the whole point. TradingView is good at the screener and
the Pine script; Sauron owns the risk gates, the broker-side brackets,
the tax lots and the grading. So an alert joins the same queue every
internal rule writes into and is refused by the same book — a webhook
that placed trades would be a second execution path with none of that,
which is the exact shape of the bugs this platform keeps finding in
itself.

This endpoint is reachable by anyone who finds the URL, so most of what
follows is about refusing things.

Run with:  python manage.py test tests.test_tradingview_webhook
"""
import json
import os
from decimal import Decimal

from django.test import TestCase

SECRET = "test-secret-value-1234"


class _Base(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        os.environ["TRADINGVIEW_WEBHOOK_SECRET"] = SECRET
        self.inst = Instrument.objects.create(
            symbol="BRNUSD", name="Brent", asset_class="commodity",
            is_active=True)
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("82.45"),
                                 source="ibkr")

    def tearDown(self):
        os.environ.pop("TRADINGVIEW_WEBHOOK_SECRET", None)

    def post(self, body):
        return self.client.post("/api/webhook/tradingview/",
                                data=json.dumps(body),
                                content_type="application/json")


class ItRefusesWhatItShouldTests(_Base):
    def test_a_wrong_secret_is_refused(self):
        r = self.post({"secret": "nope", "symbol": "BRNUSD", "action": "buy"})
        self.assertEqual(r.status_code, 403)

    def test_a_missing_secret_is_refused(self):
        self.assertEqual(
            self.post({"symbol": "BRNUSD", "action": "buy"}).status_code, 403)

    def test_an_unconfigured_webhook_is_closed_not_open(self):
        """The opposite default would leave every deployment that never
        heard of this feature running an open signal injector."""
        os.environ.pop("TRADINGVIEW_WEBHOOK_SECRET", None)
        r = self.post({"secret": SECRET, "symbol": "BRNUSD", "action": "buy"})
        self.assertEqual(r.status_code, 503)

    def test_an_unknown_symbol_is_named_not_created(self):
        """An unauthenticated POST that could add instruments is one that
        can fill the catalogue with anything."""
        from instruments.models import Instrument
        r = self.post({"secret": SECRET, "symbol": "NOTREAL", "action": "buy"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Instrument.objects.filter(symbol="NOTREAL").exists())

    def test_an_unknown_action_is_refused(self):
        r = self.post({"secret": SECRET, "symbol": "BRNUSD", "action": "hodl"})
        self.assertEqual(r.status_code, 400)

    def test_a_non_json_body_is_refused(self):
        r = self.client.post("/api/webhook/tradingview/", data="not json",
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_an_oversized_body_is_refused_before_parsing(self):
        r = self.post({"secret": SECRET, "symbol": "BRNUSD",
                       "action": "buy", "pad": "x" * 9000})
        self.assertEqual(r.status_code, 413)

    def test_get_is_not_allowed(self):
        self.assertEqual(
            self.client.get("/api/webhook/tradingview/").status_code, 405)


class ItCreatesASignalNotAnOrderTests(_Base):
    def test_a_buy_becomes_a_bullish_signal(self):
        from signals.models import Signal
        r = self.post({"secret": SECRET, "symbol": "BRNUSD", "action": "buy",
                       "price": 82.5, "strategy": "squeeze"})
        self.assertEqual(r.status_code, 200)
        s = Signal.objects.get(pk=r.json()["signal_id"])
        self.assertEqual(s.direction, "bullish")
        self.assertEqual(s.instrument, self.inst)
        self.assertEqual(s.rule_name, "tradingview:squeeze")

    def test_a_sell_becomes_bearish(self):
        from signals.models import Signal
        r = self.post({"secret": SECRET, "symbol": "BRNUSD", "action": "sell",
                       "price": 82.5})
        self.assertEqual(
            Signal.objects.get(pk=r.json()["signal_id"]).direction, "bearish")

    def test_no_trade_is_ever_placed(self):
        """The boundary: this writes a Signal and nothing else."""
        from bot_program.models import AssetBotTrade
        self.post({"secret": SECRET, "symbol": "BRNUSD", "action": "buy",
                   "price": 82.5})
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_a_full_plan_carries_its_levels_and_rr(self):
        from signals.models import Signal
        r = self.post({"secret": SECRET, "symbol": "BRNUSD", "action": "buy",
                       "price": 80, "stop": 78, "target": 86})
        s = Signal.objects.get(pk=r.json()["signal_id"])
        self.assertEqual(Decimal(str(s.suggested_stop)), Decimal("78"))
        self.assertEqual(Decimal(str(s.suggested_target)), Decimal("86"))
        self.assertAlmostEqual(s.risk_reward_ratio, 3.0, places=3)

    def test_a_bare_arrow_scores_lower_than_a_full_plan(self):
        """An external source does not get to claim conviction it has not
        earned here."""
        from signals.models import Signal
        bare_id = self.post({"secret": SECRET, "symbol": "BRNUSD",
                             "action": "buy", "price": 80,
                             "strategy": "bare"}).json()["signal_id"]
        full_id = self.post({"secret": SECRET, "symbol": "BRNUSD",
                             "action": "buy", "price": 80, "stop": 78,
                             "target": 86,
                             "strategy": "full"}).json()["signal_id"]
        self.assertLess(Signal.objects.get(pk=bare_id).score,
                        Signal.objects.get(pk=full_id).score)

    def test_a_missing_price_falls_back_to_the_platform_mark(self):
        """An alert whose template did not interpolate the close is still
        a real alert."""
        from signals.models import Signal
        r = self.post({"secret": SECRET, "symbol": "BRNUSD", "action": "buy"})
        self.assertEqual(r.status_code, 200)
        s = Signal.objects.get(pk=r.json()["signal_id"])
        self.assertEqual(Decimal(str(s.price_at_signal)), Decimal("82.45"))

    def test_the_source_is_recorded_for_grading(self):
        """Everything here is graded like any other rule, so it has to be
        attributable."""
        from signals.models import Signal
        r = self.post({"secret": SECRET, "symbol": "BRNUSD", "action": "buy",
                       "price": 80, "strategy": "squeeze"})
        s = Signal.objects.get(pk=r.json()["signal_id"])
        self.assertEqual(s.sub_scores.get("source"), "tradingview")
        self.assertEqual(s.sub_scores.get("strategy"), "squeeze")


class ARetryIsNotASecondBetTests(_Base):
    def test_a_duplicate_inside_the_window_is_ignored(self):
        """TradingView retries, and once-per-bar-close fires again on
        every reconnection — without this a flaky link doubles the vote."""
        from signals.models import Signal
        body = {"secret": SECRET, "symbol": "BRNUSD", "action": "buy",
                "price": 82.5, "strategy": "squeeze"}
        self.assertEqual(self.post(body).status_code, 200)
        second = self.post(body)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json().get("duplicate"))
        self.assertEqual(
            Signal.objects.filter(rule_name="tradingview:squeeze").count(), 1)

    def test_the_opposite_direction_is_not_a_duplicate(self):
        from signals.models import Signal
        base = {"secret": SECRET, "symbol": "BRNUSD", "price": 82.5,
                "strategy": "squeeze"}
        buy = dict(base)
        buy["action"] = "buy"
        sell = dict(base)
        sell["action"] = "sell"
        self.post(buy)
        self.post(sell)
        self.assertEqual(
            Signal.objects.filter(rule_name="tradingview:squeeze").count(), 2)
