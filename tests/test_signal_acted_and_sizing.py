"""A signal that has been acted on says so — and the operator sizes it.

Two operator reports, one file.

(a) "the platform just took a bot trade it seems on its own and the signal
    didn't disappear". A signal the OPERATOR acts on already slides out of
    the rail. A signal a BOT acts on did nothing at all: the card sat there
    looking like an untaken idea, which is how the same symbol got booked
    twice — once by a rule, once by hand.

    The card is MARKED, not removed. Vanishing is indistinguishable from
    expiring or from being dismissed, and the fact worth surfacing is
    precisely that the engine acted while nobody was watching. The join is
    derived, not stored: the manual path's exact metadata signal_id, or the
    bot path's STRING rule_name narrowed by symbol and by time.

(b) "add the option when we act on a trade to change the quantity or amount
    of money invested in". The risk-derived size stays the default, so
    doing nothing keeps the old behaviour exactly. An override is
    re-derived and re-judged on the server against the same three rules the
    automatic path obeys — the risk ceiling, the per-class notional cap,
    and the free capital in that class's pool.

Run with:  python manage.py test tests.test_signal_acted_and_sizing
"""
from decimal import Decimal

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


def _signal(inst, *, direction="bullish", entry=60000, stop=57000,
            target=66000, score=0.8, rule="acted_rule"):
    """A 5% stop by default: wide enough that doubling the size stays
    inside the 20% notional cap, so a sizing test measures the override
    and not the cap."""
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="high", title=f"{inst.symbol} {direction}", description="d",
        rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal(str(entry)),
        suggested_entry=Decimal(str(entry)),
        suggested_stop=Decimal(str(stop)),
        suggested_target=Decimal(str(target)), is_active=True)


def _bot_config(user, asset_class="crypto", name="Crypto Fleet",
                capital="10000"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=True,
        mode="paper", symbols=["BTCUSD"], capital=Decimal(capital))


def _bot_trade(cfg, *, symbol="BTCUSD", rule="acted_rule", side="BUY",
               qty="0.01", entry="60000", status="OPEN", metadata=None):
    """A position the ENGINE opened. opened_at is auto_now_add, so it lands
    after any signal created earlier in the test — which is the time half
    of the join."""
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=Decimal("57000"), take_profit=Decimal("66000"),
        status=status, paper=True, rule_name=rule,
        metadata=metadata if metadata is not None else {})


class SignalActedJoinTests(TestCase):
    """The join itself: what may claim a signal was acted on, and what
    may not."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("acted_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        self.cfg = _bot_config(self.user)

    def test_a_bot_position_on_the_same_rule_and_symbol_marks_the_signal(self):
        """The bot path stores no signal id — asset_engine.base._open copies
        BotDecision.rule_name, and decide() lifts that name off the winning
        Signal. The string rule_name IS the join."""
        sig = _signal(self.inst)
        trade = _bot_trade(self.cfg)
        acted = sig.acted
        self.assertIsNotNone(acted, "a live bot position did not mark its signal")
        self.assertEqual(acted["by"], "bot")
        self.assertEqual(acted["trade_id"], trade.id)
        self.assertEqual(acted["side"], "BUY")
        self.assertEqual(acted["venue"], "PAPER")
        self.assertEqual(acted["rule"], "acted_rule")

    def test_an_untaken_signal_is_not_marked(self):
        self.assertIsNone(_signal(self.inst).acted)

    def test_a_position_on_another_rule_does_not_claim_the_signal(self):
        _bot_trade(self.cfg, rule="some_other_rule")
        self.assertIsNone(_signal(self.inst).acted,
                          "an unrelated rule's position claimed this signal")

    def test_a_position_on_another_symbol_does_not_claim_the_signal(self):
        _quote("ETHUSD", 3000)
        _bot_trade(self.cfg, symbol="ETHUSD")
        self.assertIsNone(_signal(self.inst).acted)

    def test_a_position_opened_before_the_signal_does_not_claim_it(self):
        """A trade that already existed cannot have been opened because of
        a signal that had not fired yet. Without the time bound every new
        signal from a rule the bot holds would be born marked."""
        _bot_trade(self.cfg)
        sig = _signal(self.inst)
        self.assertIsNone(sig.acted)

    def test_a_closed_position_leaves_the_idea_open_again(self):
        """Only live exposure counts. A rule that entered and has already
        exited leaves the setup available; a permanent TAKEN badge over a
        flat book is the same lie pointing the other way."""
        sig = _signal(self.inst)
        _bot_trade(self.cfg, status="CLOSED")
        self.assertIsNone(sig.acted)

    def test_close_pending_still_counts_as_exposure(self):
        """CLOSE_PENDING is open at the broker while the bot wants it flat —
        the rest of the platform counts it as exposure and so must this."""
        sig = _signal(self.inst)
        _bot_trade(self.cfg, status="CLOSE_PENDING")
        self.assertIsNotNone(sig.acted)

    def test_the_manual_path_joins_on_its_exact_signal_id(self):
        """manual_trade stamps metadata['signal_id']. That beats the rule
        string: the trade's own rule_name is 'manual_take', which matches
        no Signal."""
        sig = _signal(self.inst)
        _bot_trade(self.cfg, rule="manual_take",
                   metadata={"manual": True, "signal_id": sig.pk})
        acted = sig.acted
        self.assertIsNotNone(acted)
        self.assertEqual(acted["by"], "manual")
        self.assertTrue(acted["exact"])

    def test_a_manual_trade_from_another_signal_is_not_claimed(self):
        sig = _signal(self.inst)
        other = _signal(self.inst, rule="acted_rule")
        _bot_trade(self.cfg, rule="manual_take",
                   metadata={"manual": True, "signal_id": other.pk})
        # `other` owns it; `sig` may not borrow it through the rule string,
        # because a manual trade's rule_name is never a Signal's.
        self.assertEqual(sig.acted, None)
        self.assertIsNotNone(other.acted)

    def test_a_ruleless_signal_never_matches_on_an_empty_string(self):
        """Signal.rule_name is blank-able and AssetBotTrade.rule_name is
        blank-able. Joining '' to '' would mark every ruleless signal with
        every ruleless trade on the symbol."""
        sig = _signal(self.inst, rule="")
        _bot_trade(self.cfg, rule="")
        self.assertIsNone(sig.acted)


class SignalRailRendersTakenTests(TestCase):
    """Both renderers of the rail — base.html's include and the WS partial
    swap — must agree, because they are the same template and the state is
    server-rendered rather than reapplied by script."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("railt_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        self.cfg = _bot_config(self.user)
        self.client.force_login(self.user)

    def _rail(self):
        resp = self.client.get("/partials/signal-rail/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", "replace")

    def test_a_bot_taken_signal_renders_its_taken_state(self):
        _signal(self.inst)
        _bot_trade(self.cfg)
        html = self._rail()
        self.assertIn('data-acted="bot"', html)
        self.assertIn("sr-acted", html)
        self.assertIn("sr-taken", html)
        self.assertIn("TAKEN", html)
        # The side and the venue are the point — "taken" alone does not tell
        # the operator what they are already holding.
        self.assertIn("BUY", html)
        self.assertIn("PAPER", html)

    def test_a_bot_taken_signal_does_not_disappear(self):
        """The steer, pinned: the card stays and ages out on its own
        lifecycle. Vanishing is indistinguishable from expiring."""
        sig = _signal(self.inst)
        _bot_trade(self.cfg)
        self.assertIn(f'data-signal-id="{sig.id}"', self._rail())

    def test_an_untaken_signal_carries_no_taken_markup(self):
        _signal(self.inst)
        html = self._rail()
        self.assertNotIn("data-acted", html)
        self.assertNotIn("sr-taken", html)
        self.assertIn("TAKE TRADE", html)

    def test_the_state_survives_a_rail_refresh(self):
        """The WS-driven partial swap replaces the rail's innerHTML with
        exactly this response. If the state lived only in the initial page
        render, the first refresh would erase it."""
        _signal(self.inst)
        first = self._rail()
        self.assertNotIn("data-acted", first)
        _bot_trade(self.cfg)
        second = self._rail()
        self.assertIn('data-acted="bot"', second)
        third = self._rail()
        self.assertIn('data-acted="bot"', third,
                      "the mark did not survive a second refresh")

    def test_the_full_page_render_agrees_with_the_partial(self):
        _signal(self.inst)
        _bot_trade(self.cfg)
        page = self.client.get("/signals/", HTTP_HOST="127.0.0.1")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode("utf-8", "replace")
        self.assertIn('data-acted="bot"', body)

    def test_the_take_button_renames_itself_on_a_taken_card(self):
        """The button stays — adding to a position is a real decision — but
        it stops calling itself a fresh entry."""
        _signal(self.inst)
        _bot_trade(self.cfg)
        html = self._rail()
        self.assertIn("ADD TO POSITION", html)
        self.assertIn("sr-pop-btn-add", html)

    def test_a_manual_take_renders_by_hand(self):
        sig = _signal(self.inst)
        _bot_trade(self.cfg, rule="manual_take",
                   metadata={"manual": True, "signal_id": sig.pk})
        html = self._rail()
        self.assertIn('data-acted="manual"', html)
        self.assertIn("BY HAND", html)


class ExposureWarningTests(TestCase):
    """The confirm step must name the position that already exists in this
    symbol — from ANY config, not just the manual one. Its absence is what
    let one symbol be booked twice."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("expo_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        self.cfg = _bot_config(self.user)

    def test_preview_reports_a_bot_position_in_the_same_symbol(self):
        from bot_program.manual_trade import preview_take_trade
        trade = _bot_trade(self.cfg)
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p)
        held = p["existing_exposure"]
        self.assertEqual([h["trade_id"] for h in held], [trade.id])
        self.assertEqual(held[0]["rule"], "acted_rule")
        self.assertFalse(held[0]["manual"])

    def test_an_empty_book_reports_no_exposure(self):
        from bot_program.manual_trade import preview_take_trade
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertEqual(p["existing_exposure"], [])


class SizingBoundsTests(TestCase):
    """What the preview hands the confirm step so it can show the
    consequence of a size before the click."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("bounds_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def test_preview_carries_the_per_unit_arithmetic(self):
        from bot_program.manual_trade import preview_take_trade
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p)
        self.assertGreater(p["qty_step"], 0)
        self.assertGreater(p["capital_use_per_unit"], 0)
        self.assertGreater(p["risk_per_unit"], 0)
        self.assertGreater(p["max_qty"], p["qty"],
                           "the default size is already at the ceiling")
        # 5.0% of a $10,000 pool — the hard cap from sizing.py, raised from
        # 1% so a SMALL account can risk enough for a win to clear its own
        # costs. Not the 0.25% default budget, which is unchanged.
        self.assertAlmostEqual(p["max_risk_dollars"], 500.0, places=2)
        # 20% notional for crypto.
        self.assertAlmostEqual(p["max_notional"], 2000.0, places=2)

    def test_the_max_size_obeys_the_binding_cap(self):
        """max_qty is the smallest of the three ceilings, floored to the
        venue's increment — a ceiling that rounds UP is not a ceiling."""
        from bot_program.manual_trade import preview_take_trade
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertLessEqual(p["max_qty"] * p["risk_per_unit"],
                             p["max_risk_dollars"] + 1e-6)
        self.assertLessEqual(p["max_qty"] * p["notional_per_unit"],
                             p["max_notional"] + 1e-6)
        self.assertLessEqual(p["max_qty"] * p["capital_use_per_unit"],
                             p["pool_free"] + 1e-6)

    def test_forex_bounds_are_margin_aware(self):
        """The 4.0 FX notional cap presumes the broker's leverage, and the
        pool is charged margin rather than levered notional. A ceiling that
        charged the notional would price every legal FX size out."""
        from bot_program.manual_trade import preview_take_trade
        fx = _quote("EURUSD", 1.10, asset_class="forex")
        p = preview_take_trade(self.user, _signal(
            fx, entry=1.10, stop=1.0967, target=1.1066))
        self.assertNotIn("error", p)
        self.assertLess(p["capital_use_per_unit"], p["notional_per_unit"])
        self.assertAlmostEqual(p["max_notional"], 40000.0, places=2)


class SizeOverrideTests(TestCase):
    """The override, on the engine."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("size_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def _open(self, **kw):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        out = execute_take_trade(self.user, _signal(self.inst), **kw)
        self.assertTrue(out.get("ok"), out)
        return out, AssetBotTrade.objects.get(pk=out["trade_id"])

    def test_omitting_the_override_reproduces_the_automatic_size(self):
        """The default is the right answer: a stop-out costs exactly the
        config's risk budget — 0.25% of $10,000. Nothing about the override
        may perturb the path that does not use it."""
        out, trade = self._open()
        self.assertEqual(out["sized_by"], "risk_budget")
        self.assertEqual(trade.metadata["size_source"], "risk_budget")
        self.assertAlmostEqual(trade.metadata["risk_dollars"], 25.0, places=6)
        realised = (float(trade.qty)
                    * abs(float(trade.entry_price) - float(trade.stop_loss))
                    * trade.metadata["value_per_unit"])
        self.assertAlmostEqual(realised, 25.0, places=1)

    def test_an_override_changes_the_executed_quantity(self):
        auto_out, auto = self._open()
        # A second signal: the dedupe is per signal, not per symbol.
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        wanted = round(float(auto.qty) * 2, 8)
        out = execute_take_trade(self.user, _signal(self.inst), qty=wanted)
        self.assertTrue(out.get("ok"), out)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertAlmostEqual(float(trade.qty), wanted, places=8)
        self.assertNotAlmostEqual(float(trade.qty), float(auto.qty), places=8)
        self.assertEqual(out["sized_by"], "operator")
        self.assertEqual(trade.metadata["size_source"], "operator")

    def test_an_operator_sized_trade_records_the_R_it_actually_carries(self):
        """Writing the config's risk budget on a hand-sized trade would
        denominate its realized_r against money that was never at risk —
        the one thing sizing.py exists to prevent."""
        _, auto = self._open()
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        wanted = round(float(auto.qty) * 2, 8)
        out = execute_take_trade(self.user, _signal(self.inst), qty=wanted)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        realised = (float(trade.qty)
                    * abs(float(trade.entry_price) - float(trade.stop_loss))
                    * trade.metadata["value_per_unit"])
        self.assertAlmostEqual(trade.metadata["risk_dollars"], realised,
                               places=4)
        self.assertGreater(trade.metadata["risk_dollars"], 40.0)

    def test_a_smaller_override_is_allowed(self):
        """Sizing down is the cheapest way to fit a trade the pool cannot
        take at full size — refusing it would send the operator to close
        positions to make room for a trade that already fits."""
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        _, auto = self._open()
        wanted = round(float(auto.qty) / 2, 8)
        out = execute_take_trade(self.user, _signal(self.inst), qty=wanted)
        self.assertTrue(out.get("ok"), out)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertAlmostEqual(float(trade.qty), wanted, places=8)


class SizeOverrideRefusalTests(TestCase):
    """Impossible numbers are refused WITH the arithmetic, never silently
    clamped to something the operator did not ask for."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("refuse_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def _refused(self, qty):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        out = execute_take_trade(self.user, _signal(self.inst), qty=qty)
        self.assertIn("error", out)
        self.assertFalse(
            AssetBotTrade.objects.filter(config__user=self.user,
                                         rule_name="manual_take").exists(),
            "a refused override still opened a position")
        return out["error"]

    def test_an_override_past_the_notional_cap_is_refused(self):
        """A stop TIGHTER than risk_cap/notional_cap (5% here) buys more
        units per dollar of risk than the class is allowed to hold, so the
        notional cap is the one that binds. Chosen to fire that cap alone —
        a size that also breaks the risk ceiling would be refused by the
        earlier check and prove nothing about this one."""
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        sig = _signal(self.inst, stop=59400, target=61200)
        p = preview_take_trade(self.user, sig)
        self.assertNotIn("error", p)
        by_notional = p["max_notional"] / p["notional_per_unit"]
        by_risk = p["max_risk_dollars"] / p["risk_per_unit"]
        self.assertLess(by_notional, by_risk,
                        "the notional cap is not the binding one here")
        out = execute_take_trade(self.user, sig,
                                 qty=round(by_notional * 1.5, 8))
        self.assertIn("error", out)
        self.assertIn("notional", out["error"])
        self.assertIn("2,000.00", out["error"])

    def test_an_override_past_the_risk_ceiling_is_refused(self):
        """MAX_RISK_FRACTION is documented as a hard cap, not a target. An
        override may reach it and not a cent past it, or realized_r stops
        being one unit across the book.

        Which of the two ceilings BINDS is set by the stop: sizing solves
        notional = equity x f / stop_fraction, so the risk ceiling binds
        only once the stop is wider than f / notional_cap. With f raised to
        5% and the default 20% cap that boundary is a 25% stop — wider than
        MAX_STOP_FRACTION allows — so this config lifts the notional cap in
        order to test the risk one at an ordinary stop distance.
        """
        from bot_program.manual_trade import (execute_take_trade,
                                              manual_config_for,
                                              preview_take_trade)
        cfg = manual_config_for(self.user, "crypto")
        cfg.extras = {"max_notional_fraction": 2.0}
        cfg.save(update_fields=["extras"])
        sig = _signal(self.inst, stop=54000, target=66000)
        p = preview_take_trade(self.user, sig)
        self.assertNotIn("error", p)
        by_risk = p["max_risk_dollars"] / p["risk_per_unit"]
        self.assertLess(by_risk, p["max_notional"] / p["notional_per_unit"],
                        "the risk ceiling is not the binding one here")
        out = execute_take_trade(self.user, sig, qty=round(by_risk * 1.5, 8))
        self.assertIn("error", out)
        self.assertIn("risks", out["error"])
        self.assertIn("ceiling", out["error"])

    def test_an_override_beyond_the_pool_is_refused_with_the_numbers(self):
        """The pool, not the caps: a position already holding most of the
        class's capital leaves less free than either cap would allow."""
        from bot_program.manual_trade import (execute_take_trade,
                                              manual_config_for,
                                              preview_take_trade)
        cfg = manual_config_for(self.user, "crypto")
        # $8,500 of the $10,000 crypto pool already committed, on the manual
        # config itself so _open_manual_trades counts it. Deliberately not
        # so much that the DEFAULT size stops fitting — a funding proposal
        # would give the override the closed capital back and the pool would
        # stop being the binding constraint.
        _bot_trade(cfg, rule="manual_take", qty="0.14166667", entry="60000",
                   metadata={"manual": True, "signal_id": None,
                             "value_per_unit": 1.0})
        sig = _signal(self.inst)
        p = preview_take_trade(self.user, sig)
        self.assertNotIn("error", p)
        self.assertTrue(p["sufficient"], p)
        by_pool = p["pool_free"] / p["capital_use_per_unit"]
        ceiling = min(p["max_risk_dollars"] / p["risk_per_unit"],
                      p["max_notional"] / p["notional_per_unit"])
        self.assertLess(by_pool, ceiling,
                        "the pool is not the binding constraint in this setup")
        # Between the two: legal under both caps, unaffordable in this pool.
        out = execute_take_trade(self.user, sig,
                                 qty=round((by_pool + ceiling) / 2, 8))
        self.assertIn("error", out)
        self.assertIn("ties up", out["error"])
        self.assertIn("is free in the crypto pool", out["error"])

    def test_a_size_below_the_venues_increment_is_refused_not_zeroed(self):
        """Rounding to zero used to mean 'nothing was sent' with no reason
        attached. The operator hears why."""
        why = self._refused(1e-12)
        self.assertIn("rounds to zero", why)

    def test_zero_and_negative_sizes_are_refused(self):
        self.assertIn("positive", self._refused(0))
        self.assertIn("positive", self._refused(-3))

    def test_a_non_numeric_size_is_refused_not_crashed(self):
        self.assertIn("number", self._refused("plenty"))

    def test_nan_and_infinity_are_refused(self):
        """Both fail isfinite before any arithmetic touches them — inf
        would otherwise sail through a naive `qty > 0` and multiply into
        every downstream number."""
        self.assertIn("positive", self._refused(float("nan")))
        self.assertIn("positive", self._refused(float("inf")))

    def test_a_boolean_is_not_a_size(self):
        """bool is an int in Python: float(True) is 1.0, so a JSON `true`
        would otherwise become a one-unit position."""
        self.assertIn("number", self._refused(True))


class ValidatorUnitTests(TestCase):
    """validate_qty_override on its own, so the refusal reasons are pinned
    without an execution around them."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("valid_u", password="x")

    def _cfg(self):
        from bot_program.manual_trade import manual_config_for
        return manual_config_for(self.user, "crypto")

    def _check(self, raw, **kw):
        from bot_program.manual_trade import validate_qty_override
        args = {"asset_class": "crypto", "entry": 60000.0, "stop": 57000.0,
                "value_per_unit": 1.0, "available": 10000.0,
                "round_qty": lambda q, p: round(float(q), 8)}
        args.update(kw)
        return validate_qty_override(self._cfg(), raw=raw, **args)

    def test_a_legal_size_comes_back_rounded(self):
        qty, why = self._check(0.0123456789)
        self.assertIsNone(why)
        self.assertAlmostEqual(qty, 0.01234568, places=8)

    def test_the_pool_ceiling_is_the_free_capital_not_the_whole_pool(self):
        qty, why = self._check(0.03, available=500.0)
        self.assertIsNone(qty)
        self.assertIn("only $500.00 is free", why)

    def test_forex_is_charged_margin_not_levered_notional(self):
        """1,000 units of EURUSD at 1.10 is $1,100 of notional but ~$36.67
        of margin. Charging the notional would refuse an ordinary FX size
        against an empty pool."""
        qty, why = self._check(1000.0, asset_class="forex", entry=1.10,
                               stop=1.0967, available=100.0)
        self.assertIsNone(why, why)
        self.assertEqual(qty, 1000.0)


class SizeOverrideEndpointTests(TestCase):
    """The wire. Everything above this line trusts a Python call; here the
    number arrives in a request body, which makes it a claim."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("wire_u", password="x")

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

    def test_a_body_without_a_size_takes_the_automatic_one(self):
        from bot_program.models import AssetBotTrade
        resp = self._post("{}")
        data = resp.json()
        self.assertTrue(data.get("ok"), data)
        trade = AssetBotTrade.objects.get(pk=data["trade_id"])
        self.assertEqual(trade.metadata["size_source"], "risk_budget")

    def test_a_size_in_the_body_is_honoured_when_it_is_legal(self):
        from bot_program.models import AssetBotTrade
        resp = self._post('{"qty": 0.01}')
        data = resp.json()
        self.assertTrue(data.get("ok"), data)
        trade = AssetBotTrade.objects.get(pk=data["trade_id"])
        self.assertAlmostEqual(float(trade.qty), 0.01, places=8)
        self.assertEqual(trade.metadata["size_source"], "operator")

    def test_the_browser_cannot_smuggle_a_size_past_validation(self):
        """The preview the browser saw is a payload it can edit. The size is
        re-derived under the execution lock against the real fill, the real
        pool and the real caps — so a hand-edited request is refused with a
        reason and leaves no row behind."""
        resp = self._post('{"qty": 500000}')
        self.assertEqual(resp.status_code, 200)
        why = resp.json().get("error", "")
        self.assertIn("risks", why)
        self.assertIn("ceiling", why)
        self.assertEqual(self._open_count(), 0)

    def test_a_negative_size_is_refused_at_the_wire(self):
        self.assertIn("positive", self._post('{"qty": -1}').json()["error"])
        self.assertEqual(self._open_count(), 0)

    def test_a_non_numeric_size_is_a_400_not_a_500(self):
        resp = self._post('{"qty": "lots"}')
        self.assertEqual(resp.status_code, 400)
        self.assertIn("number", resp.json()["error"])
        self.assertEqual(self._open_count(), 0)

    def test_a_json_true_is_not_one_unit(self):
        resp = self._post('{"qty": true}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._open_count(), 0)

    def test_infinity_is_refused_before_it_reaches_the_money_math(self):
        # JSON has no Infinity literal, but Python's decoder accepts it and
        # 1e999 overflows to inf on the way in.
        resp = self._post('{"qty": 1e999}')
        self.assertEqual(resp.status_code, 400)
        self.assertIn("finite", resp.json()["error"])
        self.assertEqual(self._open_count(), 0)

    def test_a_null_size_means_the_automatic_one(self):
        resp = self._post('{"qty": null}')
        data = resp.json()
        self.assertTrue(data.get("ok"), data)
        self.assertEqual(data["sized_by"], "risk_budget")

    def test_the_signal_less_instrument_path_takes_a_size_too(self):
        from bot_program.models import AssetBotTrade
        resp = self._post('{"side": "BUY", "qty": 0.01}',
                          url="/instruments/BTCUSD/take-trade/")
        data = resp.json()
        if data.get("error"):
            self.skipTest(f"no engine levels without bars: {data}")
        trade = AssetBotTrade.objects.get(pk=data["trade_id"])
        self.assertAlmostEqual(float(trade.qty), 0.01, places=8)
        self.assertEqual(trade.metadata["size_source"], "operator")
