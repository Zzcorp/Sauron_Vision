"""The confirm step is a control panel, not a receipt.

The operator's report: "we should be able to manage more the trade choice
taken before taking trade... especially IF WE CLOSE ANOTHER POSITION OR NOT
before opening the other."

The last clause was a live defect. When capital was short the popup built
`close_ids` itself, by copying every entry out of the server's funding
proposal, and the button liquidated all of them. The positions were LISTED
under a "Close first" label — shown, never asked about — so pressing
CLOSE + TAKE moved the operator's money on a default they had seen and not
agreed to. This file pins the fix: the closes are a selection, declining
one costs the trade rather than the position, and the shortfall comes back
with its arithmetic.

The same posture then covers the rest of the ticket — the stop and the
target are adjustable and re-judged server-side against the platform's own
bands and its own cost filter, and the size follows a hand-placed stop
because risk sizing is what a stop is FOR.

Leverage is the one control this deliberately does NOT build. Nothing in
the execution path multiplies a manual order: forex ties up broker margin
and every other class settles in full. So the preview ships it as a fact
and the tests here pin the fact, not an input — an input wired to nothing
would have the operator sizing against a number the order never sees.

What every test below is really guarding: the DEFAULTS. The risk-derived
size, the planned levels and the minimum-disturbance proposal are the right
answers, and pressing the button without touching anything must still send
byte-for-byte the request it sent before any of this was adjustable.

Run with:  python manage.py test tests.test_pretrade_controls
"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "binance_public"})
    return inst


def _signal(inst, *, direction="bullish", entry=60000, stop=59100,
            target=61800, rule="pretrade_rule"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="high", title=f"{inst.symbol} {direction}", description="d",
        rule_name=rule, score=0.8, sub_scores={},
        price_at_signal=Decimal(str(entry)),
        suggested_entry=Decimal(str(entry)),
        suggested_stop=Decimal(str(stop)),
        suggested_target=Decimal(str(target)), is_active=True)


def _manual_position(cfg, *, qty, entry="60000", symbol="BTCUSD", side="BUY"):
    """A manual position already on the book — what the funding proposal
    chooses from. Written directly rather than through execute_take_trade
    because the point is the SHAPE of the pool, not how it got there."""
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal(entry),
        stop_loss=Decimal("57000"), take_profit=Decimal("66000"),
        status="OPEN", paper=True, rule_name="manual_take",
        metadata={"manual": True, "signal_id": None, "value_per_unit": 1.0,
                  "initial_stop_loss": 57000.0})


# The paper fill BTCUSD opens a BUY at: 10bps round trip for crypto, half
# of it charged adversely. Every level bound below is measured from HERE,
# because the fill is what the server judges a hand-placed level against.
FILL = 60030.0


class FundingSelectionTests(TestCase):
    """Which positions are liquidated is the operator's decision."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("fund_u", password="x")

    def setUp(self):
        from bot_program.manual_trade import manual_config_for
        self.inst = _quote("BTCUSD", 60000)
        self.cfg = manual_config_for(self.user, "crypto")
        # $9,000 of the $10,000 crypto pool committed across two positions,
        # so a $1,666 trade is short and EITHER position covers the gap on
        # its own. That is the case the old popup could not express: the
        # proposal picks the smaller one, and the operator may disagree.
        # The two committed positions sit in OTHER symbols. The pool is what
        # funds a trade, and it is pool-wide — but the concentration ceiling
        # is per symbol and side, so parking $9,000 of BTCUSD here would mean
        # this fixture arrived already past that ceiling and the trade would
        # be refused for a reason this class is not about. The question posed
        # is which position the operator liquidates, and that question does
        # not depend on what the position is in.
        _quote("ETHUSD", 60000)
        _quote("SOLUSD", 60000)
        self.big = _manual_position(self.cfg, qty="0.10",
                                    symbol="ETHUSD")          # frees $6,000
        self.small = _manual_position(self.cfg, qty="0.05",
                                      symbol="SOLUSD")        # frees $3,000

    def _preview(self):
        from bot_program.manual_trade import preview_take_trade
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p, p)
        return p

    def test_the_preview_offers_the_whole_pool_not_just_the_proposal(self):
        """The popup used to receive close_proposal alone, so 'keep that one
        and close this other one instead' had nowhere to be expressed."""
        p = self._preview()
        self.assertFalse(p["sufficient"])
        ids = sorted(c["trade_id"] for c in p["closable"])
        self.assertEqual(ids, sorted([self.big.id, self.small.id]))
        proposed = [c["trade_id"] for c in p["closable"] if c["proposed"]]
        self.assertEqual(proposed, [self.small.id],
                         "the proposal is not the smallest single cover")
        self.assertGreater(p["deficit"], 0)

    def test_every_offered_close_carries_what_it_frees(self):
        """A tick with no number beside it is not a choice — the operator
        has to see which position covers the gap before deciding."""
        p = self._preview()
        by_id = {c["trade_id"]: c for c in p["closable"]}
        self.assertAlmostEqual(by_id[self.big.id]["freed"], 6000.0, places=2)
        self.assertAlmostEqual(by_id[self.small.id]["freed"], 3000.0, places=2)

    def test_declining_every_close_refuses_the_trade_not_the_positions(self):
        """The whole point. An empty selection must cost the TRADE — the
        positions the operator kept stay exactly where they were, and the
        refusal says how much short they are rather than blaming the
        'funding closes' the operator declined."""
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        out = execute_take_trade(self.user, _signal(self.inst), close_ids=[])
        self.assertIn("error", out)
        self.assertIn("short", out["error"])
        self.assertIn("$", out["error"])
        self.big.refresh_from_db()
        self.small.refresh_from_db()
        self.assertEqual(self.big.status, "OPEN")
        self.assertEqual(self.small.status, "OPEN")
        self.assertEqual(
            AssetBotTrade.objects.filter(config=self.cfg).count(), 2,
            "a refused ticket still opened a position")

    def test_the_operator_may_close_a_position_the_proposal_did_not_pick(self):
        """Minimum disturbance is a heuristic, not a judgement. The operator
        knows which thesis is dead; the proposal only knows which row is
        smallest."""
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(self.inst),
                                 close_ids=[self.big.id])
        self.assertTrue(out.get("ok"), out)
        self.big.refresh_from_db()
        self.small.refresh_from_db()
        self.assertEqual(self.big.status, "CLOSED")
        self.assertEqual(self.small.status, "OPEN",
                         "a position the operator kept was liquidated anyway")

    def test_a_close_id_from_another_pool_is_not_honoured(self):
        """close_ids arrives in a request body. It is filtered to THIS
        user's manual config for this class — a hand-edited id cannot reach
        a bot's position or another user's."""
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotConfig
        other = AssetBotConfig.objects.create(
            user=self.user, asset_class="crypto", name="Crypto Fleet",
            enabled=True, mode="paper", symbols=["BTCUSD"],
            capital=Decimal("10000"))
        bot_pos = _manual_position(other, qty="0.10")
        out = execute_take_trade(self.user, _signal(self.inst),
                                 close_ids=[bot_pos.id])
        # Nothing was freed, so the trade is refused — and crucially the
        # bot's position is untouched either way.
        self.assertIn("error", out)
        bot_pos.refresh_from_db()
        self.assertEqual(bot_pos.status, "OPEN")


class StopControlTests(TestCase):
    """The stop is adjustable, and the size follows it."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("stop_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def test_a_hand_placed_stop_is_the_stop_the_position_opens_with(self):
        """R is denominated by the stop the trade OPENED with for its whole
        life. If metadata kept the engine's stop while the broker held the
        operator's, every realized_r on the row would be measured against a
        level that was never live."""
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        out = execute_take_trade(self.user,
                                 _signal(self.inst, target=63000),
                                 stop=58500.0, target=63000.0)
        self.assertTrue(out.get("ok"), out)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertAlmostEqual(float(trade.stop_loss), 58500.0, places=6)
        self.assertAlmostEqual(float(trade.take_profit), 63000.0, places=6)
        self.assertAlmostEqual(trade.metadata["initial_stop_loss"], 58500.0,
                               places=6)
        self.assertEqual(trade.metadata["operator_overrides"],
                         ["stop", "target"])
        self.assertEqual(trade.metadata["level_source"], "operator")
        # The engine's answer is kept beside it: grading later wants to know
        # whether a level was a person's or the machinery's.
        self.assertAlmostEqual(trade.metadata["engine_stop"], 59100.0, places=6)

    def test_a_wider_stop_shrinks_the_size_and_holds_the_risk_budget(self):
        """Risk sizing is what a stop is FOR. Moving the stop and leaving
        the size alone must re-derive the size, or the operator silently
        doubles their risk by widening a level.

        Two clips on one symbol and side is exactly what the concentration
        ceiling allows and no more — CONCENTRATION_CLIP_ALLOWANCE is 2 — so
        this test sits deliberately at the boundary. A third would be
        refused, which is the point of the ceiling rather than a problem
        with this test.
        """
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        auto = execute_take_trade(self.user, _signal(self.inst, target=64000))
        self.assertTrue(auto.get("ok"), auto)
        wide = execute_take_trade(self.user, _signal(self.inst, target=64000),
                                  stop=58000.0)
        self.assertTrue(wide.get("ok"), wide)
        self.assertLess(wide["qty"], auto["qty"],
                        "a wider stop did not shrink the position")
        trade = AssetBotTrade.objects.get(pk=wide["trade_id"])
        realised = (float(trade.qty)
                    * abs(float(trade.entry_price) - float(trade.stop_loss))
                    * trade.metadata["value_per_unit"])
        self.assertAlmostEqual(realised, 25.0, places=1)
        # The size is still the platform's arithmetic — only the level was
        # the operator's, and the ledger has to keep the two apart.
        self.assertEqual(trade.metadata["size_source"], "risk_budget")

    def test_a_stop_on_the_wrong_side_of_the_fill_is_refused(self):
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(self.inst), stop=60100.0)
        self.assertIn("error", out)
        self.assertIn("BELOW", out["error"])

    def test_a_stop_inside_the_platforms_floor_is_refused(self):
        """0.2% is where risk_levels stops believing an ATR stop. Inside it
        the distance is spread and noise, and the position is one tick of
        jitter from a stop-out."""
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(self.inst), stop=59990.0)
        self.assertIn("error", out)
        self.assertIn("floor", out["error"])

    def test_a_stop_past_the_platforms_ceiling_is_refused(self):
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(self.inst), stop=40000.0)
        self.assertIn("error", out)
        self.assertIn("ceiling", out["error"])

    def test_a_tightened_stop_that_breaches_the_notional_cap_is_refused(self):
        """The one that is easy to miss. A tighter stop buys MORE units per
        dollar of risk, so an automatic size at a hand-placed stop can walk
        straight through the notional cap the preview was judged against.
        The caps bite on the size that is actually sent."""
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        out = execute_take_trade(self.user, _signal(self.inst), stop=59500.0)
        self.assertIn("error", out)
        self.assertIn("notional", out["error"])
        self.assertIn("2,000.00", out["error"])
        self.assertFalse(
            AssetBotTrade.objects.filter(config__user=self.user).exists(),
            "a refused stop still opened a position")


class TargetControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tgt_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def test_a_target_on_the_wrong_side_of_the_fill_is_refused(self):
        """A BUY take-profit below the entry is not an aggressive target —
        it is an instruction to book a loss the moment the tick reaches it."""
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(self.inst), target=59000.0)
        self.assertIn("error", out)
        self.assertIn("ABOVE", out["error"])

    def test_levels_that_no_longer_clear_their_costs_are_refused(self):
        """passes_cost_filter is the gate every bot entry goes through. A
        target dragged in until the planned move no longer covers the round
        trip leaves a ticket that pays the spread and nothing else."""
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(self.inst), target=60050.0)
        self.assertIn("error", out)
        self.assertIn("clear their own costs", out["error"])

    def test_the_cost_filter_is_asked_only_of_levels_that_moved(self):
        """It must not be applied to the untouched defaults: the ATR
        machinery that produced them already respects this band, and
        re-judging them here could refuse a trade the plain button takes —
        which would change the default."""
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(self.inst))
        self.assertTrue(out.get("ok"), out)


class DefaultsAreUnchangedTests(TestCase):
    """Everything above is an override. This is what happens when nobody
    overrides anything, and it must not have moved a hair."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("def_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def test_an_untouched_ticket_carries_no_override_bookkeeping(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        out = execute_take_trade(self.user, _signal(self.inst))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["overrides"], [])
        self.assertEqual(out["sized_by"], "risk_budget")
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(trade.metadata["size_source"], "risk_budget")
        self.assertNotIn("operator_overrides", trade.metadata)
        self.assertNotIn("level_source", trade.metadata)
        # The engine's levels, verbatim, and the budget it sized to.
        self.assertAlmostEqual(float(trade.stop_loss), 59100.0, places=6)
        self.assertAlmostEqual(float(trade.take_profit), 61800.0, places=6)
        self.assertAlmostEqual(trade.metadata["risk_dollars"], 25.0, places=6)


class LeverageHonestyTests(TestCase):
    """Leverage is reported, never offered — because no execution path
    applies one."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lev_u", password="x")

    def test_forex_states_the_brokers_leverage_and_the_notional_it_allows(self):
        from bot_program.manual_trade import preview_take_trade
        fx = _quote("EURUSD", 1.10, asset_class="forex")
        p = preview_take_trade(self.user, _signal(
            fx, entry=1.10, stop=1.0967, target=1.1066))
        self.assertNotIn("error", p, p)
        lev = p["leverage"]
        self.assertAlmostEqual(lev["effective"], 30.0, places=4)
        self.assertFalse(lev["adjustable"],
                         "the dialog would render an input nothing applies")
        self.assertAlmostEqual(lev["max_notional"], 40000.0, places=2)
        self.assertIn("broker", lev["note"])

    def test_a_cash_settled_class_says_it_has_no_leverage_knob(self):
        """Rather than showing a dead input set to 1x."""
        from bot_program.manual_trade import preview_take_trade
        inst = _quote("BTCUSD", 60000)
        p = preview_take_trade(self.user, _signal(inst))
        lev = p["leverage"]
        self.assertAlmostEqual(lev["effective"], 1.0, places=4)
        self.assertFalse(lev["adjustable"])
        self.assertIn("No leverage", lev["note"])


class LevelBoundsPayloadTests(TestCase):
    """The browser is given the rules so it can show a consequence per
    keystroke. It is never given the verdict."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("bounds2_u",
                                                        password="x")

    def test_the_preview_ships_the_bands_the_server_will_judge_against(self):
        from bot_program.asset_engine.risk_levels import (MAX_STOP_FRACTION,
                                                          MIN_STOP_FRACTION)
        from bot_program.manual_trade import preview_take_trade
        inst = _quote("BTCUSD", 60000)
        p = preview_take_trade(self.user, _signal(inst))
        lv = p["levels"]
        self.assertAlmostEqual(lv["min_stop_fraction"], MIN_STOP_FRACTION)
        self.assertAlmostEqual(lv["max_stop_fraction"], MAX_STOP_FRACTION)
        self.assertGreater(lv["cost_fraction"], 0)
        self.assertGreater(lv["min_net_rr"], 0)
        # The fill, not the mark: a reward:risk quoted off the free mark is
        # a reward:risk nobody actually gets.
        self.assertAlmostEqual(lv["fill"], FILL, places=4)
        self.assertGreater(lv["fill"], p["entry"])


class ValidatorUnitTests(TestCase):
    """The level validators on their own, so the refusal reasons are pinned
    without an execution around them."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lvlval_u",
                                                        password="x")

    def _cfg(self):
        from bot_program.manual_trade import manual_config_for
        return manual_config_for(self.user, "crypto")

    def _stop(self, raw, side="BUY", entry=60000.0):
        from bot_program.manual_trade import validate_stop_override
        return validate_stop_override(self._cfg(), asset_class="crypto",
                                      raw=raw, entry=entry, side=side)

    def test_a_legal_stop_comes_back_as_a_float(self):
        stop, why = self._stop("59000")
        self.assertIsNone(why)
        self.assertAlmostEqual(stop, 59000.0)

    def test_a_boolean_is_not_a_stop(self):
        """bool is an int in Python: a JSON `true` would otherwise place the
        stop at $1 and size the position to the whole pool."""
        self.assertIn("number", self._stop(True)[1])

    def test_nan_and_infinity_are_refused(self):
        self.assertIn("positive", self._stop(float("nan"))[1])
        self.assertIn("positive", self._stop(float("inf"))[1])

    def test_a_sell_stop_must_sit_above_the_entry(self):
        self.assertIn("ABOVE", self._stop(59000.0, side="SELL")[1])
        self.assertIsNone(self._stop(61000.0, side="SELL")[1])

    def test_targets_are_judged_on_side_only(self):
        """How FAR is a judgement — an operator scalping half the ATR is
        making a real choice. Whether the distance pays for itself is the
        cost filter's question, not this one's."""
        from bot_program.manual_trade import validate_target_override
        self.assertIsNone(
            validate_target_override(raw=60001.0, entry=60000.0,
                                     side="BUY")[1])
        self.assertIn("ABOVE", validate_target_override(
            raw=59999.0, entry=60000.0, side="BUY")[1])
        self.assertIn("BELOW", validate_target_override(
            raw=60001.0, entry=60000.0, side="SELL")[1])


class PreTradeWireTests(TestCase):
    """Every control arrives as a number in a request body, which makes it
    a claim. The preview the browser saw is a payload it can edit."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("wire2_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        self.sig = _signal(self.inst)
        self.client.force_login(self.user)

    def _post(self, body, url=None):
        return self.client.post(url or f"/signals/{self.sig.id}/take-trade/",
                                data=body, content_type="application/json",
                                HTTP_HOST="127.0.0.1")

    def _open_count(self):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.filter(config__user=self.user).count()

    def test_a_body_without_levels_takes_the_platforms_own(self):
        from bot_program.models import AssetBotTrade
        data = self._post("{}").json()
        self.assertTrue(data.get("ok"), data)
        trade = AssetBotTrade.objects.get(pk=data["trade_id"])
        self.assertNotIn("operator_overrides", trade.metadata)

    def test_hand_placed_levels_ride_the_wire_and_are_honoured(self):
        from bot_program.models import AssetBotTrade
        data = self._post('{"stop": 58500, "target": 63000}').json()
        self.assertTrue(data.get("ok"), data)
        trade = AssetBotTrade.objects.get(pk=data["trade_id"])
        self.assertAlmostEqual(float(trade.stop_loss), 58500.0, places=6)
        self.assertEqual(data["overrides"], ["stop", "target"])

    def test_the_browser_cannot_smuggle_a_stop_past_validation(self):
        why = self._post('{"stop": 60100}').json().get("error", "")
        self.assertIn("BELOW", why)
        self.assertEqual(self._open_count(), 0)

    def test_a_non_numeric_level_is_a_400_not_a_500(self):
        resp = self._post('{"stop": "under the last low"}')
        self.assertEqual(resp.status_code, 400)
        self.assertIn("stop must be a number", resp.json()["error"])
        self.assertEqual(self._open_count(), 0)

    def test_a_json_true_level_is_refused_at_the_wire(self):
        self.assertEqual(self._post('{"target": true}').status_code, 400)
        self.assertEqual(self._open_count(), 0)

    def test_infinity_is_refused_before_it_reaches_the_money_math(self):
        # JSON has no Infinity literal, but Python's decoder accepts 1e999
        # and overflows it to inf on the way in.
        resp = self._post('{"stop": 1e999}')
        self.assertEqual(resp.status_code, 400)
        self.assertIn("finite", resp.json()["error"])
        self.assertEqual(self._open_count(), 0)

    def test_a_null_level_means_the_platforms_own(self):
        data = self._post('{"stop": null, "target": null}').json()
        self.assertTrue(data.get("ok"), data)
        self.assertEqual(data["overrides"], [])

    def test_the_signal_less_path_takes_levels_too(self):
        data = self._post('{"side": "BUY", "stop": 58500, "target": 63000}',
                          url="/instruments/BTCUSD/take-trade/").json()
        if data.get("error"):
            self.skipTest(f"no engine levels without bars: {data}")
        self.assertEqual(data["overrides"], ["stop", "target"])


class DialogContractTests(TestCase):
    """The defect lived in the browser: the popup filled close_ids in for
    the operator. These read the shipped asset, because a control that
    exists only in the payload is not a control."""

    @staticmethod
    def _base():
        return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")

    def test_the_dialog_no_longer_auto_accepts_the_funding_closes(self):
        js = self._base()
        self.assertNotIn("closeIds.push", js,
                         "the popup still builds the close list itself")
        self.assertIn('data-role="close"', js,
                      "the funding closes have no per-position control")
        self.assertIn("choice.close_ids", js,
                      "the request no longer carries the operator's selection")

    def test_the_dialog_sends_nothing_for_an_untouched_field(self):
        """`if (choice.x !== null)` is what keeps an untouched ticket
        byte-for-byte the request it always was — a field sent with the
        platform's own number in it would route through a validator instead
        of the automatic path and land differently in the ledger."""
        js = self._base()
        for field in ("qty", "stop", "target"):
            self.assertIn("if (choice.%s !== null) body.%s = choice.%s;"
                          % (field, field, field), js)

    def test_the_dialog_offers_no_leverage_input(self):
        """An input nothing in the execution path applies would have the
        operator sizing against a number the order never sees."""
        js = self._base()
        self.assertNotIn('data-role="leverage"', js)
        self.assertIn("lever.note", js,
                      "the dialog does not say where the leverage lives")


class DialogStyleTests(TestCase):
    """The house CSS rules, on the block this slice added."""

    @staticmethod
    def _block():
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"
               ).read_text(encoding="utf-8")
        start = css.index("TAKE TRADE — the pre-trade control panel")
        return css[start:css.index("CHART SURFACES", start)]

    def test_no_raw_hex_colours(self):
        block = self._block()
        self.assertIsNone(
            re.search(r"#[0-9a-fA-F]{3,8}\b", block),
            "the pre-trade panel hardcodes a colour instead of a token")

    def test_no_raw_z_index(self):
        self.assertNotIn("z-index", self._block())
