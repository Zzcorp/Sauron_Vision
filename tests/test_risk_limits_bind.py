"""The /setup/ Risk Limits card, and whether it protects anything.

For most of this platform's life it did not. Four numbers were written onto
the shared "Main" portfolio and then:

  * `max_total_exposure_pct` had no reader anywhere in the repo;
  * `max_daily_loss_pct` reached a context processor (display) and an LLM
    prompt payload, and no entry gate;
  * `max_single_position_pct` and `max_correlation_threshold` reached trading
    only through `portfolio.risk_gate.evaluate_proposed_trade`, whose one
    caller is the legacy crypto runner — a module with no beat entry, which
    therefore never runs.

So an operator set MAX DAILY LOSS 3%, armed a bot, believed the platform
stopped after a 3% down day, and nothing did. These tests are the proof that
it does now: every one of them would have passed vacuously before, because
the gate did not exist to be asked.

Three things the first cut of that enforcement got wrong are pinned here too,
because each one is the same failure wearing a different hat — a protection
that reads as present and is not:

  * the options lane replaces `AssetBot.scan_symbol` wholesale, so the two
    size-dependent limits lived in a method it never runs;
  * the manual path's funding closes realise P&L, and a losing one could trip
    the daily-loss gate that then refused the trade those closes had just paid
    for, costing the operator both;
  * `preflight` fails open, and the card badged that state green.

The last section pins the SMC/ICT lane's vote into `AssetBot.decide()` — a
score that was computed for months and consumed only on the same dead legacy
path — the two rules that keep an unproven lane from behaving like a proven
one, and the seat in the conviction average it is not allowed to take.

Run with:  python manage.py test tests.test_risk_limits_bind
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


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


def _book(**limits):
    """The shared book the card writes to, with the limits under test."""
    from portfolio.risk_gate import limits_book
    pf = limits_book()
    for field, value in limits.items():
        setattr(pf, field, value)
    pf.save()
    return pf


def _config(user, asset_class="crypto", **kwargs):
    from bot_program.models import AssetBotConfig
    defaults = {"name": "t", "enabled": True, "mode": "paper",
                "symbols": [], "capital": Decimal("10000")}
    defaults.update(kwargs)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, **defaults)


def _closed_trade(cfg, pnl, *, hours_ago=1, symbol="BTCUSD"):
    """A CLOSED AssetBotTrade whose close lands `hours_ago` in the past.

    `closed_at` is moved after creation so the row is written exactly as an
    ordinary close writes it and only the close time differs. A negative
    `hours_ago` puts the close in the future, which is how the as-of bound on
    the window is tested.
    """
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("90"),
        status="CLOSED", pnl=Decimal(str(pnl)))
    t.closed_at = timezone.now() - timedelta(hours=hours_ago)
    t.save(update_fields=["closed_at"])
    return t


def _open_trade(cfg, *, entry="100", qty="1", symbol="BTCUSD",
                asset_class=None, metadata=None):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class, symbol=symbol,
        side="BUY", qty=Decimal(qty), entry_price=Decimal(entry),
        status="OPEN", metadata=metadata or {})


class DailyLossGateTests(TestCase):
    """MAX DAILY LOSS — the headline. It stops entries; it never closes."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rl_dl", password="x")

    def test_a_quiet_day_is_measured_as_zero_not_unknown(self):
        """Nothing closed IS a measurement. If this returned None the gate
        would report itself blind on every fresh install."""
        from portfolio.risk_gate import daily_loss_state
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        state = daily_loss_state(self.user)
        self.assertTrue(state["ok"])
        self.assertTrue(state["measured"])
        self.assertEqual(state["realized"], 0.0)

    def test_a_loss_past_the_limit_blocks_new_entries(self):
        from portfolio.risk_gate import daily_loss_state, preflight
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        cfg = _config(self.user)
        _closed_trade(cfg, -301)  # floor is -300 on a 10,000 book
        state = daily_loss_state(self.user)
        self.assertFalse(state["ok"])
        self.assertEqual(state["limit_money"], -300.0)
        self.assertIn("daily loss limit hit", state["reason"])
        self.assertFalse(preflight(self.user)["ok"])

    def test_a_loss_inside_the_limit_does_not(self):
        from portfolio.risk_gate import daily_loss_state
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        _closed_trade(_config(self.user), -299)
        self.assertTrue(daily_loss_state(self.user)["ok"])

    def test_the_window_is_the_same_trailing_24h_the_bot_config_uses(self):
        """`AssetBot.can_open_new` measures a trailing 24 hours against the
        per-config limit. A second definition of "today" on the same platform
        would let one screen say stopped and the other say trading."""
        from portfolio.risk_gate import DAILY_LOSS_WINDOW_HOURS, daily_loss_state
        self.assertEqual(DAILY_LOSS_WINDOW_HOURS, 24)
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        cfg = _config(self.user)
        _closed_trade(cfg, -5000, hours_ago=25)
        state = daily_loss_state(self.user)
        self.assertTrue(state["ok"], state["reason"])
        self.assertEqual(state["realized"], 0.0)

    def test_it_unions_both_position_books(self):
        """Half the loss in AssetBotTrade, half in the legacy Position book.
        Either alone is inside the limit; together they are not."""
        from portfolio.models import Position
        from portfolio.risk_gate import daily_loss_state
        pf = _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        _closed_trade(_config(self.user), -200)

        inst = _instrument("LEGACY", "stock")
        pos = Position.objects.create(
            portfolio=pf, instrument=inst, direction="long",
            quantity=Decimal("10"), entry_price=Decimal("100"),
            current_price=Decimal("85"),  # -150 realized
            opened_at=timezone.now() - timedelta(days=2))
        pos.closed_at = timezone.now() - timedelta(hours=2)
        pos.save(update_fields=["closed_at"])

        state = daily_loss_state(self.user)
        self.assertEqual(state["realized"], -350.0)
        self.assertFalse(state["ok"])

    def test_an_unpriceable_legacy_close_is_unmeasured_not_zero(self):
        """`Position` has no realized-P&L column: `unrealized_pnl` defaults to
        0 and only an hourly mark task writes it. Booking such a row as a
        scratch is how a losing day gets waved through."""
        from portfolio.models import Position
        from portfolio.risk_gate import realized_since
        pf = _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        inst = _instrument("NOMARK", "stock")
        pos = Position.objects.create(
            portfolio=pf, instrument=inst, direction="long",
            quantity=Decimal("10"), entry_price=Decimal("100"),
            current_price=Decimal("0"),
            opened_at=timezone.now() - timedelta(days=2))
        pos.closed_at = timezone.now() - timedelta(hours=2)
        pos.save(update_fields=["closed_at"])

        window = realized_since(self.user, pf)
        self.assertEqual(window["unmeasured"], 1)
        self.assertIsNone(window["realized"])
        # And the gate refuses to claim a verdict it cannot support.
        from portfolio.risk_gate import daily_loss_state
        state = daily_loss_state(self.user)
        self.assertTrue(state["ok"])
        self.assertFalse(state["measured"])
        self.assertIn("unknown", state["reason"])

    def test_a_close_booked_after_the_as_of_instant_is_outside_the_window(self):
        """`now` is an as-of instant, so the window is closed at both ends. A
        reading that counted closes booked after it would not be a reading of
        that instant — and that bound is what lets the manual take-trade path
        measure the day as it stood before its own funding closes."""
        from portfolio.risk_gate import realized_since
        pf = _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        as_of = timezone.now()
        _closed_trade(_config(self.user), -500, hours_ago=-1)
        window = realized_since(self.user, pf, now=as_of)
        self.assertEqual(window["n"], 0)
        self.assertEqual(window["realized"], 0.0)
        # And it IS counted once the clock has caught up with it.
        self.assertEqual(
            realized_since(self.user, pf,
                           now=as_of + timedelta(hours=2))["realized"], -500.0)

    def test_an_unset_book_value_is_not_a_zero_book(self):
        """A 3% limit on a book of unknown size is not "stop at zero" — it is
        not a limit. Halting the fleet on a number nobody entered would be the
        opposite failure to the one this card had."""
        from portfolio.risk_gate import daily_loss_state
        _book(current_value=Decimal("0"), max_daily_loss_pct=3.0)
        state = daily_loss_state(self.user)
        self.assertTrue(state["ok"])
        self.assertIsNone(state["book_value"])
        self.assertIn("never been set", state["reason"])


class ExposureGateTests(TestCase):
    """MAX TOTAL EXPOSURE — the field that had no reader at all."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rl_ex", password="x")

    def test_a_full_book_blocks_the_next_entry(self):
        from portfolio.risk_gate import exposure_state
        _book(current_value=Decimal("10000"), max_total_exposure_pct=50.0)
        cfg = _config(self.user)
        _open_trade(cfg, entry="1000", qty="6")  # 6,000 > 5,000 ceiling
        state = exposure_state(self.user)
        self.assertFalse(state["ok"])
        self.assertEqual(state["cap_money"], 5000.0)
        self.assertEqual(state["committed"], 6000.0)

    def test_close_pending_still_counts_as_exposure(self):
        """The broker position is still on while a close is being retried."""
        from bot_program.models import AssetBotTrade
        from portfolio.risk_gate import exposure_state
        _book(current_value=Decimal("10000"), max_total_exposure_pct=50.0)
        cfg = _config(self.user)
        t = _open_trade(cfg, entry="1000", qty="6")
        AssetBotTrade.objects.filter(pk=t.pk).update(status="CLOSE_PENDING")
        self.assertFalse(exposure_state(self.user)["ok"])

    def test_forex_is_charged_its_margin_not_its_levered_notional(self):
        """`sizing`'s 4.0x forex notional cap exists BECAUSE the leverage lives
        at the broker. Charging full notional here would refuse every FX entry
        the platform is designed to take — a halt dressed as a limit."""
        from portfolio.risk_gate import capital_at_work, exposure_state
        self.assertAlmostEqual(capital_at_work("forex", 30000.0), 1000.0)
        self.assertAlmostEqual(capital_at_work("stock", 30000.0), 30000.0)

        _book(current_value=Decimal("10000"), max_total_exposure_pct=100.0)
        cfg = _config(self.user, asset_class="forex")
        _open_trade(cfg, entry="1", qty="30000", symbol="EURUSD",
                    asset_class="forex")
        state = exposure_state(self.user)
        self.assertTrue(state["ok"], state["reason"])
        self.assertAlmostEqual(state["committed"], 1000.0, places=2)

    def test_it_counts_the_legacy_book_too(self):
        from portfolio.models import Position
        from portfolio.risk_gate import exposure_state
        pf = _book(current_value=Decimal("10000"), max_total_exposure_pct=50.0)
        Position.objects.create(
            portfolio=pf, instrument=_instrument("LEG2", "stock"),
            direction="long", quantity=Decimal("60"),
            entry_price=Decimal("100"), current_price=Decimal("100"),
            opened_at=timezone.now())
        self.assertFalse(exposure_state(self.user)["ok"])


class SinglePositionGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rl_sp", password="x")

    def test_an_oversized_position_is_refused_with_the_arithmetic(self):
        from portfolio.risk_gate import limits_book, single_position_state
        _book(current_value=Decimal("10000"), max_single_position_pct=10.0)
        state = single_position_state(limits_book(), asset_class="stock",
                                      notional=1500.0)
        self.assertFalse(state["ok"])
        self.assertEqual(state["cap_money"], 1000.0)
        # The refusal has to carry both numbers, or the operator cannot tell
        # whether to size down or to move the limit.
        self.assertIn("1,500.00", state["reason"])
        self.assertIn("1,000.00", state["reason"])

    def test_a_position_exactly_at_the_ceiling_passes(self):
        from portfolio.risk_gate import limits_book, single_position_state
        _book(current_value=Decimal("10000"), max_single_position_pct=10.0)
        self.assertTrue(single_position_state(
            limits_book(), asset_class="stock", notional=1000.0)["ok"])


class BotEntryGateTests(TestCase):
    """The gate reaches `AssetBot.can_open_new`, which is what every asset
    bot's tick asks before it scans anything."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rl_bot", password="x")

    def _bot(self):
        from bot_program.asset_engine.base import make_bot
        return make_bot(_config(self.user, asset_class="crypto",
                                symbols=["BTCUSD"]))

    def test_can_open_new_refuses_when_the_book_limit_is_breached(self):
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        bot = self._bot()
        _closed_trade(bot.cfg, -400)
        ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("book risk limits", reason)

    def test_the_per_config_drawbown_toggle_does_not_disable_the_book_limit(self):
        """`halt_on_drawdown` governs THIS config's own drawdown halt. Turning
        one bot's halt off is not consent to trade through the book's."""
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        from bot_program.asset_engine.base import make_bot
        cfg = _config(self.user, asset_class="crypto", symbols=["BTCUSD"],
                      halt_on_drawdown=False)
        _closed_trade(cfg, -400)
        ok, reason = make_bot(cfg).can_open_new()
        self.assertFalse(ok)
        self.assertIn("book risk limits", reason)

    def test_a_gate_that_cannot_read_the_book_fails_open_and_says_so(self):
        """Halting an entire fleet on a transient database error is a worse
        failure than the one unenforced tick it prevents — but it must never
        be silent."""
        from portfolio import risk_gate
        with patch.object(risk_gate, "daily_loss_state",
                          side_effect=RuntimeError("db gone")):
            with self.assertLogs("portfolio.risk_gate", level="ERROR"):
                out = risk_gate.preflight(self.user)
        self.assertTrue(out["ok"])
        self.assertIn("could not be read", out["reason"])


class ManualTradeGateTests(TestCase):
    """The TAKE TRADE path enforced per-trade risk, the class notional cap and
    the pool's free capital — and no daily-loss stop at all."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rl_mt", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def test_the_preview_REPORTS_the_daily_loss_limit_rather_than_refusing(self):
        """These two limits are RISK APPETITE, and on a hand-taken trade
        there is a human entitled to change their mind about their own
        appetite with the numbers in front of them. It used to refuse.

        Reported in full, arithmetic included, so overriding it is a
        decision rather than a shrug."""
        from bot_program.manual_trade import (manual_config_for,
                                              preview_asset_trade)
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        _closed_trade(manual_config_for(self.user, "crypto"), -500)
        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out)
        advisory = out["book_advisory"]
        self.assertFalse(advisory["ok"])
        self.assertIn("daily loss limit hit", advisory["reason"])
        self.assertIn("-300.00", advisory["reason"], "no arithmetic to judge")

    def test_the_operator_can_take_it_anyway(self):
        """The point of the change. The trade opens."""
        from bot_program.manual_trade import (execute_asset_trade,
                                              manual_config_for)
        from bot_program.models import AssetBotTrade
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        _closed_trade(manual_config_for(self.user, "crypto"), -500)
        out = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out)
        self.assertTrue(AssetBotTrade.objects.filter(
            symbol="BTCUSD", status="OPEN").exists())

    def test_taking_it_anyway_is_recorded_on_the_trade(self):
        """A limit overridden without a trace is indistinguishable
        afterwards from a limit that was never reached."""
        from bot_program.manual_trade import (execute_asset_trade,
                                              manual_config_for)
        from bot_program.models import AssetBotTrade
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        _closed_trade(manual_config_for(self.user, "crypto"), -500)
        out = execute_asset_trade(self.user, self.inst, "BUY")
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        recorded = trade.metadata.get("book_limit_at_entry") or {}
        self.assertFalse(recorded.get("ok"))
        self.assertIn("daily loss limit hit", recorded.get("reason", ""))

    def test_a_clean_book_records_that_it_was_clean(self):
        from bot_program.manual_trade import execute_asset_trade
        from bot_program.models import AssetBotTrade
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        out = execute_asset_trade(self.user, self.inst, "BUY")
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertTrue(trade.metadata["book_limit_at_entry"]["ok"])

    def test_the_bots_are_still_hard_stopped_by_it(self):
        """The asymmetry is the whole design: a bot has nobody on the other
        end to weigh the number, so for it the limit stays a refusal."""
        from portfolio.risk_gate import preflight
        from bot_program.manual_trade import manual_config_for
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        _closed_trade(manual_config_for(self.user, "crypto"), -500)
        state = preflight(self.user)
        self.assertFalse(state["ok"])
        self.assertIn("daily loss limit hit", state["reason"])

    def test_a_losing_funding_close_cannot_refuse_the_trade_it_paid_for(self):
        """The funding closes are irreversible and they REALISE P&L, which is
        the exact quantity MAX DAILY LOSS measures over the trailing 24h. A
        gate that read them would refuse the trade they were executed to fund,
        and one click would cost the operator the position AND the trade.

        The closes cannot move to after the gate — they are what frees the
        capital — so the gate is asked as of the instant before them.
        """
        from bot_program.manual_trade import (execute_asset_trade,
                                              manual_config_for)
        from bot_program.models import AssetBotTrade
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0,
              max_total_exposure_pct=100.0, max_single_position_pct=100.0)
        cfg = manual_config_for(self.user, "crypto")
        _quote("ETHUSD", 3800)
        # 9,600 of a 10,000 pool tied up, so the new ticket cannot be funded
        # without closing it — and closing it books ~-480 against a -300 floor.
        held = AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="ETHUSD", side="BUY",
            qty=Decimal("2.4"), entry_price=Decimal("4000"), status="OPEN",
            paper=True, metadata={"manual": True, "value_per_unit": 1.0})

        out = execute_asset_trade(self.user, self.inst, "BUY",
                                  close_ids=[held.id])

        self.assertNotIn("error", out)
        self.assertEqual(out["closed"], ["ETHUSD"])
        self.assertTrue(AssetBotTrade.objects.filter(
            symbol="BTCUSD", status="OPEN").exists())
        # The close really did lose more than the floor allows — the trade
        # opened because the gate was asked about the book BEFORE it, not
        # because nothing was there to measure.
        held.refresh_from_db()
        self.assertLess(float(held.pnl), -300.0)
        # And the NEXT click reads the new reality, closes included — as a
        # warning now rather than as a refusal, but measured just the same.
        from bot_program.manual_trade import preview_asset_trade
        nxt = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertIn("daily loss limit hit",
                      nxt["book_advisory"]["reason"])

    def test_the_preview_reports_correlation_rather_than_applying_it(self):
        """Same posture as `existing_exposure`: adding correlated exposure on
        purpose is a legitimate decision, and taking it without being told is
        not. The size the operator sees must be the size that is sent."""
        from bot_program.manual_trade import preview_asset_trade
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0,
              max_single_position_pct=100.0, max_correlation_threshold=0.7)
        with patch("portfolio.risk_gate.correlation_state",
                   return_value={"scale": 0.25, "max_corr": 0.98,
                                 "peer": "ETHUSD", "threshold": 0.7,
                                 "measured": True, "reason": "very correlated"}):
            out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out)
        self.assertEqual(out["correlation"]["scale"], 0.25)
        self.assertEqual(out["correlation"]["peer"], "ETHUSD")
        # The proposed size is the risk-derived one, untouched by the taper.
        self.assertAlmostEqual(out["risk_dollars"], 25.0, places=2)


class SetupCardTests(TestCase):
    """The card itself: what it accepts, and what it claims."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rl_ui", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _post(self, **overrides):
        data = {"action": "update_risk", "max_exposure": "100",
                "max_position": "10", "max_daily_loss": "3",
                "max_correlation": "0.7", "max_theme_legs": "3"}
        data.update(overrides)
        return self.client.post("/setup/", data, follow=True)

    def test_a_valid_save_lands_on_the_shared_book(self):
        from portfolio.risk_gate import limits_book
        self._post(max_daily_loss="2.5")
        self.assertAlmostEqual(limits_book().max_daily_loss_pct, 2.5)

    def test_zero_is_refused_because_it_now_means_halt(self):
        """Before this the four fields took any float. A 0 daily loss stops the
        fleet at the first cent lost, and it used to be one keystroke away."""
        from portfolio.risk_gate import limits_book
        before = limits_book().max_daily_loss_pct
        r = self._post(max_daily_loss="0")
        self.assertContains(r, "NOT saved")
        self.assertAlmostEqual(limits_book().max_daily_loss_pct, before)

    def test_a_blank_field_does_not_500_the_settings_page(self):
        """`float(request.POST.get("max_exposure", 100))` raised ValueError
        straight out of the view whenever the field was cleared."""
        r = self._post(max_exposure="")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "NOT saved")

    def test_nothing_is_saved_when_one_field_is_rejected(self):
        """A partial save gives the operator a policy they did not ask for,
        under a green success message."""
        from portfolio.risk_gate import limits_book
        self._post(max_exposure="80", max_position="9", max_daily_loss="2",
                   max_correlation="0.6")
        self._post(max_exposure="55", max_position="5", max_daily_loss="0",
                   max_correlation="0.5")
        pf = limits_book()
        self.assertAlmostEqual(pf.max_total_exposure_pct, 80)
        self.assertAlmostEqual(pf.max_single_position_pct, 9)
        self.assertAlmostEqual(pf.max_correlation_threshold, 0.6)

    def test_a_gate_that_could_not_be_read_is_never_badged_as_enforced(self):
        """`preflight` FAILS OPEN: `ok` stays True and entries go through
        ungated. A green ENFORCED badge in that state is the card at its most
        reassuring exactly when the limits are applying to nothing, which is
        worse than no badge at all."""
        from portfolio import risk_gate
        with patch.object(risk_gate, "daily_loss_state",
                          side_effect=RuntimeError("db gone")):
            with self.assertLogs("portfolio.risk_gate", level="ERROR"):
                r = self.client.get("/setup/")
        body = r.content.decode("utf-8", "replace")
        self.assertNotIn("ENFORCED", body)
        self.assertIn("NOT ENFORCING", body)
        self.assertIn("not being applied to entries", body)

    def test_a_readable_book_inside_its_limits_is_badged_enforced(self):
        """The converse, so the badge above cannot be made honest by never
        being green."""
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        body = self.client.get("/setup/").content.decode("utf-8", "replace")
        self.assertIn("ENFORCED", body)
        self.assertNotIn("NOT ENFORCING", body)

    def test_the_card_states_that_the_limits_are_enforced(self):
        """No screen may claim a protection that does not exist — and the
        converse: a protection that now exists has to be readable as one."""
        r = self.client.get("/setup/")
        body = r.content.decode("utf-8", "replace")
        self.assertIn("Checked before every bot entry", body)
        # The correlation field is a taper, and says so rather than reading as
        # a block it has never been.
        self.assertIn("CORRELATION SIZE TAPER", body)
        self.assertIn("A taper, not a block", body)


class SmcVoteTests(TestCase):
    """`smc_score_for_symbol` returned 0.0 through a dead import for its whole
    life, and its only consumer was the legacy runner that no beat starts. The
    ICT lane has therefore never reached a position."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rl_smc", password="x")

    def _bot(self, **cfg_kwargs):
        from bot_program.asset_engine.base import make_bot
        return make_bot(_config(self.user, asset_class="crypto",
                                symbols=["BTCUSD"], **cfg_kwargs))

    class _Vote:
        """A rule vote, the two attributes the consensus reads."""
        def __init__(self, rule_name, score=0.8):
            self.rule_name = rule_name
            self.score = score
            self.title = "t"

    def test_the_vote_enters_at_the_weight_a_measured_loser_carries(self):
        """0.25 is `aggregation.MIN_WEIGHT` — the floor for a rule this
        platform has measured as its worst. A lane with no record at all has
        not earned more than that."""
        from bot_program.asset_engine import aggregation
        from bot_program.asset_engine.base import SMC_VOTE_WEIGHT
        self.assertEqual(SMC_VOTE_WEIGHT, aggregation.MIN_WEIGHT)

    def test_a_full_conviction_vote_cannot_clear_the_default_entry_bar(self):
        """min_signals_for_entry x entry_score_min = 1 x 0.60. At maximum
        conviction the lane contributes 0.25 — it can tip a close call, never
        make one."""
        from bot_program.asset_engine.base import SMC_VOTE_WEIGHT
        bot = self._bot()
        bar = bot.cfg.min_signals_for_entry * bot.cfg.entry_score_min
        self.assertLess(1.0 * SMC_VOTE_WEIGHT, bar)

    def test_it_joins_a_side_that_already_has_its_quorum(self):
        from bot_program.asset_engine.base import SMC_RULE_NAME
        bot = self._bot()
        bull = [self._Vote("rule_a")]
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0.8, ["smc"])):
            new_bull, new_bear = bot._with_smc_vote("BTCUSD", bull, [])
        self.assertEqual(len(new_bull), 2)
        self.assertEqual(new_bull[-1].rule_name, SMC_RULE_NAME)
        self.assertAlmostEqual(new_bull[-1].score, 0.2)  # 0.8 x 0.25
        self.assertEqual(new_bear, [])

    def test_it_is_dropped_from_a_side_with_no_rule_votes_of_its_own(self):
        """It must never satisfy `min_signals_for_entry` by itself, in either
        direction: an unproven lane that could block a trade would be exactly
        as unearned as one that could open it."""
        bot = self._bot(min_signals_for_entry=1)
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(-0.9, ["smc"])):
            new_bull, new_bear = bot._with_smc_vote(
                "BTCUSD", [self._Vote("rule_a")], [])
        self.assertEqual(len(new_bull), 1)
        self.assertEqual(new_bear, [])

    def test_a_two_signal_config_needs_two_real_rules_before_smc_speaks(self):
        bot = self._bot(min_signals_for_entry=2)
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0.9, ["smc"])):
            one, _ = bot._with_smc_vote("BTCUSD", [self._Vote("rule_a")], [])
            two, _ = bot._with_smc_vote(
                "BTCUSD", [self._Vote("rule_a"), self._Vote("rule_b")], [])
        self.assertEqual(len(one), 1)
        self.assertEqual(len(two), 3)

    def test_a_neutral_score_is_not_a_vote_for_hold(self):
        bot = self._bot()
        bull = [self._Vote("rule_a")]
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0.0, [])):
            new_bull, new_bear = bot._with_smc_vote("BTCUSD", bull, [])
        self.assertEqual(new_bull, bull)
        self.assertEqual(new_bear, [])

    def test_a_broken_bridge_degrades_loudly_instead_of_silently(self):
        """`smc_score_for_symbol` RAISES on a missing `get_hit_rate` on
        purpose. Letting that propagate would take every entry decision on the
        platform down with one lane; swallowing it quietly is how this lane
        spent its life at zero."""
        bot = self._bot()
        bull = [self._Vote("rule_a")]
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   side_effect=ImportError("get_hit_rate")):
            with self.assertLogs("bot_program.asset_engine.base",
                                 level="ERROR"):
                new_bull, new_bear = bot._with_smc_vote("BTCUSD", bull, [])
        self.assertEqual(new_bull, bull)
        self.assertEqual(new_bear, [])

    def test_decide_asks_the_lane_on_the_weighted_path(self):
        """The wire itself: without this call the score goes on being computed
        and thrown away, which is the whole defect."""
        from signals.models import Signal
        inst = _quote("BTCUSD", 60000)
        Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="high", title="up", description="d", rule_name="rule_a",
            score=0.9, sub_scores={}, is_active=True,
            price_at_signal=Decimal("60000"),
            suggested_entry=Decimal("60000"))
        bot = self._bot()
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0.5, ["smc"])) as spy:
            bot.decide("BTCUSD")
        spy.assert_called_once_with("BTCUSD")

    def _signal(self, rule, *, direction="bullish", score=0.9):
        from signals.models import Signal
        inst = _quote("BTCUSD", 60000)
        # price_at_signal is NOT NULL on this model — the row is what every
        # later grade is measured against, so a signal with no price is a
        # signal nothing can score.
        return Signal.objects.create(
            instrument=inst, signal_type="technical", direction=direction,
            urgency="high", title=direction, description="d", rule_name=rule,
            score=score, sub_scores={}, is_active=True,
            price_at_signal=Decimal("60000"),
            suggested_entry=Decimal("60000"))

    def _two_bullish_signals(self, score=0.9):
        for rule in ("rule_a", "rule_b"):
            self._signal(rule, score=score)

    def test_the_vote_does_not_lower_the_conviction_it_confirms(self):
        """`weighted_consensus` scores a side as its total evidence over the
        number of votes in it, and the SMC vote is capped below every real
        vote beside it — so a seat in that average could only ever drag it.
        Arming the lane would have written a WORSE composite_score onto
        exactly the entries it agreed with, which is a confirmation nobody
        would want."""
        self._two_bullish_signals(score=0.9)
        bot = self._bot()
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0.0, [])):
            alone = bot.decide("BTCUSD")
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0.8, ["smc"])):
            confirmed = bot.decide("BTCUSD")
        self.assertEqual(alone.direction, "BUY")
        self.assertEqual(confirmed.direction, "BUY")
        self.assertAlmostEqual(alone.score, 0.9, places=4)
        self.assertAlmostEqual(confirmed.score, alone.score, places=4)

    def test_the_vote_still_tips_the_gate_it_gave_up_its_seat_in(self):
        """The seat it gives up is in the AVERAGE, not in the net weight.
        Two bullish rules at 0.9 against one bearish at 0.75 net 1.05, just
        under the 1.20 bar two signals demand — the close call the lane exists
        to tip. It tips it, and the conviction recorded is still the 0.90 the
        rules themselves earned rather than the 0.68 a third seat would have
        averaged it down to."""
        self._two_bullish_signals(score=0.9)
        self._signal("rule_c", direction="bearish", score=0.75)
        bot = self._bot(min_signals_for_entry=2)
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0.0, [])):
            self.assertEqual(bot.decide("BTCUSD").direction, "HOLD")
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(1.0, ["smc"])):
            tipped = bot.decide("BTCUSD")
        self.assertEqual(tipped.direction, "BUY")
        self.assertAlmostEqual(tipped.score, 0.9, places=4)


class OptionsLaneGateTests(TestCase):
    """Options is a real lane with a real entry path, and `OptionsBot` replaces
    `AssetBot.scan_symbol` wholesale — so the two size-dependent limits from
    /setup/ lived entirely in the method it overrides. MAX DAILY LOSS and MAX
    TOTAL EXPOSURE arrive with the inherited `can_open_new`; these two did not
    arrive at all.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rl_opt", password="x")

    def setUp(self):
        from bot_program.options_models import OptionContract
        self.inst = _instrument("AAPL", "stock")
        # A large pool so the risk budget buys enough contracts for a taper to
        # be visible as a change in the count rather than as rounding.
        self.cfg = _config(self.user, asset_class="options", symbols=["AAPL"],
                           capital=Decimal("1000000"), stop_loss_pct=20.0,
                           take_profit_pct=50.0)
        self.contract = OptionContract.objects.create(
            underlying=self.inst, strike=Decimal("180"),
            expiry=timezone.now().date() + timedelta(days=30), right="C",
            multiplier=100, bid=Decimal("1.00"), ask=Decimal("1.02"),
            last_price=Decimal("1.01"), iv=0.30, delta=0.41)

    def _scan(self, *, corr_scale=1.0):
        """One options entry pass, with the signal vote and broker stubbed.

        `decide` is stubbed rather than fed Signal rows because what is under
        test is everything AFTER the direction is chosen.
        """
        from bot_program.asset_engine.base import BotDecision
        from bot_program.asset_engine.options_bot import OptionsBot
        bot = OptionsBot(self.cfg)
        corr = {"scale": corr_scale, "max_corr": 0.98, "peer": "MSFT",
                "threshold": 0.7, "measured": True,
                "reason": "correlation 0.98 to MSFT"}
        with patch.object(bot, "decide",
                          return_value=BotDecision("BUY", 0.9, ["signal"])), \
                patch("bot_program.engine.broker_router.client_for_symbol"), \
                patch("portfolio.risk_gate.correlation_state",
                      return_value=corr):
            return bot.scan_symbol("AAPL")

    def test_the_single_position_ceiling_refuses_an_options_ticket(self):
        """The premium is paid in full, so the contracts' cost IS the capital
        they tie up — and a ceiling every other lane enforces was not enforced
        on the one lane whose positions are bought outright.

        The ceiling is a share of the POOL that sized the ticket, not of the
        portfolio book: this config is armed with 1,000,000 and the ticket
        costs ~12,400, so 1% is the percentage that bites. Expressing it
        against the book instead is what made this gate refuse correctly
        sized entries on every account whose pool exceeded its recorded
        book.
        """
        from bot_program.models import AssetBotTrade
        _book(current_value=Decimal("10000"), max_single_position_pct=1.0)
        self.assertIsNone(self._scan())
        self.assertFalse(AssetBotTrade.objects.exists())

    def test_a_ticket_inside_the_ceiling_still_opens(self):
        """The converse: a limit that refuses everything is not a limit."""
        _book(current_value=Decimal("10000"), max_single_position_pct=100.0)
        out = self._scan()
        self.assertIsNotNone(out)
        self.assertGreater(out["contracts"], 0)

    def test_the_correlation_taper_reaches_the_contract_count(self):
        from bot_program.models import AssetBotTrade
        _book(current_value=Decimal("10000000"),
              max_single_position_pct=100.0)
        full = self._scan()["contracts"]
        AssetBotTrade.objects.all().delete()
        tapered = self._scan(corr_scale=0.25)["contracts"]
        self.assertLess(tapered, full)
        self.assertAlmostEqual(tapered / full, 0.25, delta=0.02)
