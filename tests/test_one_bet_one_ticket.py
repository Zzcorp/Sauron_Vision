"""One bet, one ticket — and a leg cap on the currency it rides.

The morning brief led with the same finding four days straight: EURGBP and
EURJPY each held TWICE, by two different rules — manual_take on one leg,
bollinger_squeeze_breakout or golden_cross on the other — 2x the intended
size of one idea, flagged by the anomaly scanner fourteen times in a day,
refused by nothing. Every existing limit is money-scoped or symbol-scoped:
two half-size tickets clear the concentration ceiling, the single-position
cap and the exposure cap while still being one bet written twice. And six
of twelve open positions were EUR crosses — one ECB headline marking five
legs at once — with no gate anywhere that counts a THEME.

Two new answers in `portfolio.risk_gate`, pinned here:

  `duplicate_state` — the same symbol and direction, already held by a
  DIFFERENT author (another config's rule, the manual config, a legacy
  Position), refuses a new ticket outright. The asker's own config is
  exempt: adding to your own expression is sizing, and the money limits
  already govern it.

  `theme_state` — open forex tickets sharing a same-direction currency
  with the candidate are counted, and at `max_theme_legs` (the new card
  field; 0 = off) the next one is refused. Bots take both as hard
  refusals; the manual path refuses duplicates (a second author is not
  appetite) but only warns on theme, and records the override.

Run with:  python manage.py test tests.test_one_bet_one_ticket
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase


def _instrument(symbol, asset_class="forex", exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange})
    return inst


def _config(user, asset_class="forex", name="t", **kwargs):
    from bot_program.models import AssetBotConfig
    defaults = {"enabled": True, "mode": "paper", "symbols": [],
                "capital": Decimal("10000")}
    defaults.update(kwargs)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, **defaults)


def _open(cfg, symbol, side="BUY", rule="golden_cross", status="OPEN",
          asset_class=None):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class, symbol=symbol,
        side=side, qty=Decimal("1"), entry_price=Decimal("100"),
        status=status, rule_name=rule,
        metadata={"value_per_unit": 1.0})


def _book(**limits):
    from portfolio.risk_gate import limits_book
    pf = limits_book()
    for field, value in limits.items():
        setattr(pf, field, value)
    pf.save()
    return pf


class DuplicateStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("dup_u", password="x")

    def test_a_second_author_on_the_same_bet_is_refused(self):
        """The briefing's exact case: a rule already BUYs EURGBP, and a
        second config asks to BUY it again."""
        from portfolio.risk_gate import duplicate_state
        holder = _config(self.user, name="squeeze")
        _open(holder, "EURGBP", rule="bollinger_squeeze_breakout")
        asker = _config(self.user, name="manual")

        state = duplicate_state(self.user, symbol="EURGBP", side="BUY",
                                config_id=asker.id)
        self.assertFalse(state["ok"])
        self.assertIn("bollinger_squeeze_breakout", state["reason"])
        self.assertIn("doubles the bet", state["reason"])

    def test_the_askers_own_config_is_not_duplication(self):
        """Adding a clip to your own expression is sizing — the money
        ceilings govern it, this gate does not."""
        from portfolio.risk_gate import duplicate_state
        cfg = _config(self.user, name="own")
        _open(cfg, "EURGBP")
        state = duplicate_state(self.user, symbol="EURGBP", side="BUY",
                                config_id=cfg.id)
        self.assertTrue(state["ok"], state["reason"])

    def test_the_opposite_direction_is_not_duplication(self):
        from portfolio.risk_gate import duplicate_state
        holder = _config(self.user, name="squeeze2")
        _open(holder, "EURGBP", side="BUY")
        state = duplicate_state(self.user, symbol="EURGBP", side="SELL",
                                config_id=_config(self.user, name="m2").id)
        self.assertTrue(state["ok"], state["reason"])

    def test_a_close_that_has_not_filled_is_still_a_holder(self):
        """CLOSE_PENDING is still exposure everywhere else on this
        platform, and it is still a holder here — a duplicate opened in
        the gap before the close fills would end up alone and doubled by
        turns."""
        from portfolio.risk_gate import duplicate_state
        holder = _config(self.user, name="pending")
        _open(holder, "EURJPY", status="CLOSE_PENDING")
        state = duplicate_state(self.user, symbol="EURJPY", side="BUY",
                                config_id=_config(self.user, name="m3").id)
        self.assertFalse(state["ok"])

    def test_the_legacy_position_book_counts_as_an_author(self):
        """The bet does not care which table recorded it — the same rule
        symbol_side_exposure already follows."""
        from portfolio.models import Position
        from portfolio.risk_gate import duplicate_state, limits_book
        inst = _instrument("AAPL", "stock")
        from django.utils import timezone
        Position.objects.create(
            portfolio=limits_book(), instrument=inst, direction="long",
            quantity=Decimal("5"), entry_price=Decimal("200"),
            current_price=Decimal("200"), opened_at=timezone.now())
        state = duplicate_state(self.user, symbol="AAPL", side="BUY",
                                config_id=_config(self.user, name="m4",
                                                  asset_class="stock").id)
        self.assertFalse(state["ok"])
        self.assertIn("portfolio position", state["reason"])

    def test_the_users_own_book_counts_too(self):
        """The NL trader writes to `<username>_main`, not the shared
        limits book — a gate that scanned only the shared one would let a
        chat-opened AAPL long hide from the duplicate check the setup
        form's identical long trips."""
        from django.utils import timezone
        from portfolio.models import Position
        from portfolio.risk_gate import duplicate_state
        from portfolio.services import get_or_create_default_portfolio
        inst = _instrument("AAPL", "stock")
        Position.objects.create(
            portfolio=get_or_create_default_portfolio(user=self.user),
            instrument=inst, direction="long",
            quantity=Decimal("5"), entry_price=Decimal("200"),
            current_price=Decimal("200"), opened_at=timezone.now())
        state = duplicate_state(self.user, symbol="AAPL", side="BUY",
                                config_id=_config(self.user, name="m5",
                                                  asset_class="stock").id)
        self.assertFalse(state["ok"])

    def test_a_bought_put_is_a_short_holder_not_a_long_one(self):
        """The options lane always BUYS premium, so a bought PUT is a
        short expression stored as side="BUY". Read raw, it inverted this
        gate both ways: falsely refusing the OPPOSITE bet and waving
        through the SAME one doubled."""
        from bot_program.models import AssetBotTrade
        from portfolio.risk_gate import duplicate_state
        holder = _config(self.user, asset_class="options", name="puts")
        t = _open(holder, "AAPL", side="BUY", rule="earnings_put")
        AssetBotTrade.objects.filter(pk=t.pk).update(
            metadata={"underlying_signal_direction": "SELL", "right": "P"})

        short = duplicate_state(self.user, symbol="AAPL", side="SELL",
                                config_id=_config(self.user, name="m6",
                                                  asset_class="stock").id)
        self.assertFalse(short["ok"], "same short idea, one derivative over")
        long = duplicate_state(self.user, symbol="AAPL", side="BUY",
                               config_id=_config(self.user, name="m7",
                                                 asset_class="stock").id)
        self.assertTrue(long["ok"],
                        "the opposite of a held PUT is not a duplicate")

    def test_the_contract_right_answers_when_the_direction_is_missing(self):
        """Older options rows may lack underlying_signal_direction; the
        right is enough because this lane only ever buys premium."""
        from bot_program.models import AssetBotTrade
        from portfolio.risk_gate import duplicate_state
        holder = _config(self.user, asset_class="options", name="puts2")
        t = _open(holder, "MSFT", side="BUY", rule="hedge_put")
        AssetBotTrade.objects.filter(pk=t.pk).update(
            metadata={"right": "P"})
        state = duplicate_state(self.user, symbol="MSFT", side="SELL",
                                config_id=_config(self.user, name="m8",
                                                  asset_class="stock").id)
        self.assertFalse(state["ok"])


class ThemeStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("theme_u", password="x")

    def _crowd(self, *symbols, side="BUY"):
        """One ticket per symbol, each under its own config so nothing here
        trips the duplicate gate instead."""
        for i, sym in enumerate(symbols):
            _open(_config(self.user, name=f"c{i}_{sym.lower()}"), sym,
                  side=side)

    def test_the_eur_crowd_refuses_a_fourth_long_eur_leg(self):
        from portfolio.risk_gate import theme_state
        _book(max_theme_legs=3)
        self._crowd("EURUSD", "EURJPY", "EURCHF")
        state = theme_state(self.user, symbol="EURGBP", side="BUY",
                            asset_class="forex")
        self.assertFalse(state["ok"])
        self.assertEqual(state["currency"], "EUR")
        self.assertEqual(state["n"], 3)
        self.assertIn("long EUR", state["reason"])
        self.assertIn("EURUSD", state["reason"])

    def test_direction_matters_a_disagreeing_leg_does_not_stack(self):
        """Long EURUSD is SHORT USD — it does not crowd a long-USD
        candidate. Shared currency alone is not a shared bet."""
        from portfolio.risk_gate import theme_state
        _book(max_theme_legs=3)
        self._crowd("EURUSD", "EURJPY", "EURCHF")  # long EUR, short USD/JPY/CHF
        state = theme_state(self.user, symbol="USDJPY", side="BUY",
                            asset_class="forex")
        # Long USD shares nothing with short USD; short JPY shares one leg
        # with EURJPY's short JPY.
        self.assertTrue(state["ok"], state["reason"])
        self.assertEqual(state["currency"], "JPY")
        self.assertEqual(state["n"], 1)

    def test_a_short_crowd_counts_too(self):
        """The cap is on a directional crowd, not on longs: three tickets
        short JPY are one BoJ headline exactly as five long EUR are one
        ECB one."""
        from portfolio.risk_gate import theme_state
        _book(max_theme_legs=3)
        self._crowd("EURJPY", "GBPJPY", "AUDJPY")  # all short JPY
        state = theme_state(self.user, symbol="CADJPY", side="BUY",
                            asset_class="forex")
        self.assertFalse(state["ok"])
        self.assertEqual(state["currency"], "JPY")
        self.assertIn("short JPY", state["reason"])

    def test_zero_on_the_card_turns_the_gate_off(self):
        from portfolio.risk_gate import theme_state
        _book(max_theme_legs=0)
        self._crowd("EURUSD", "EURJPY", "EURCHF", "EURAUD")
        state = theme_state(self.user, symbol="EURGBP", side="BUY",
                            asset_class="forex")
        self.assertTrue(state["ok"])
        self.assertIn("no theme-leg cap", state["reason"])

    def test_only_forex_is_counted(self):
        """A ticker does not name its theme; pretending it does would make
        the gate lie. Equities pass with the reason stated."""
        from portfolio.risk_gate import theme_state
        _book(max_theme_legs=1)
        state = theme_state(self.user, symbol="AAPL", side="BUY",
                            asset_class="stock")
        self.assertTrue(state["ok"])
        self.assertIn("forex only", state["reason"])

    def test_a_close_that_has_not_filled_still_crowds(self):
        """CLOSE_PENDING is exposure everywhere on this platform — a
        broker position still on is one more leg the ECB headline hits."""
        from portfolio.risk_gate import theme_state
        _book(max_theme_legs=3)
        self._crowd("EURUSD", "EURJPY")
        _open(_config(self.user, name="cp_chf"), "EURCHF",
              status="CLOSE_PENDING")
        state = theme_state(self.user, symbol="EURGBP", side="BUY",
                            asset_class="forex")
        self.assertFalse(state["ok"])
        self.assertEqual(state["n"], 3)

    def test_the_legacy_position_book_joins_the_crowd(self):
        from django.utils import timezone
        from portfolio.models import Position
        from portfolio.risk_gate import limits_book, theme_state
        _book(max_theme_legs=3)
        self._crowd("EURUSD", "EURJPY")
        Position.objects.create(
            portfolio=limits_book(), instrument=_instrument("EURCHF"),
            direction="long", quantity=Decimal("1"),
            entry_price=Decimal("1.07"), current_price=Decimal("1.07"),
            opened_at=timezone.now())
        state = theme_state(self.user, symbol="EURGBP", side="BUY",
                            asset_class="forex")
        self.assertFalse(state["ok"])
        self.assertEqual(state["n"], 3)

    def test_gold_is_not_a_currency_even_when_misclassified(self):
        """XAUUSD is six letters and alpha, and a free-form symbols list
        can put it on a forex config. Parsed as a pair it would lend a
        short-USD leg to the USD crowd and fabricate an XAU theme — the
        vocabulary, not the length, decides what is a currency."""
        from portfolio.risk_gate import _currency_legs, theme_state
        self.assertEqual(_currency_legs("XAUUSD", "BUY"), {})
        self.assertEqual(_currency_legs("EURUSD", "BUY"),
                         {"EUR": 1, "USD": -1})

        _book(max_theme_legs=2)
        # Two forex-classed gold clips + one real short-USD ticket: only
        # the real one may count against a short-USD candidate.
        self._crowd("XAUUSD", "XAGUSD")   # forex-classed by the fixture
        self._crowd("EURUSD")             # genuinely short USD
        state = theme_state(self.user, symbol="GBPUSD", side="BUY",
                            asset_class="forex")
        self.assertTrue(state["ok"], state["reason"])
        self.assertEqual(state["n"], 1)
        self.assertEqual(state["currency"], "USD")


class BotPathTests(TestCase):
    """The gates sit ON the entry path, not beside it — both lanes."""

    def test_scan_symbol_asks_both_questions(self):
        """AST-pinned on CALL nodes, the way the seeded-setup params are
        pinned: the options lane once proved a limit can live in a method
        a lane never runs — and a plain substring pin is satisfied by the
        import line alone, so a reverted call with a surviving import
        would keep this green while gating nothing."""
        import ast
        import inspect
        import textwrap
        from bot_program.asset_engine.base import AssetBot
        src = textwrap.dedent(inspect.getsource(AssetBot.scan_symbol))
        called = {
            (node.func.id if isinstance(node.func, ast.Name)
             else getattr(node.func, "attr", None))
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call)
        }
        self.assertIn("duplicate_state", called)
        self.assertIn("theme_state", called)

    def test_the_options_lane_asks_the_duplicate_question_too(self):
        import inspect
        from bot_program.asset_engine.options_bot import OptionsBot
        src = inspect.getsource(OptionsBot)
        self.assertIn("duplicate_state", src)
        self.assertIn("decision.direction", src.split("duplicate_state", 1)[1][:400])


class NLTraderGateTests(TestCase):
    """The chat lane opens real Position rows and had NO gate at all —
    and it books onto `<username>_main`, a table the gates now scan."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("nl_u", password="x")

    def setUp(self):
        from market_data.models import LiveQuote
        self.inst = _instrument("AAPL", "stock")
        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("200"), "source": "test"})
        _book(current_value=Decimal("100000"),
              max_single_position_pct=100.0, max_theme_legs=3)

    def _execute(self, action="buy", symbol="AAPL"):
        from bot_program.nl_trader import NLTradeParser
        return NLTradeParser().execute(
            {"action": action, "symbol": symbol, "quantity": 1,
             "confidence": 0.9}, self.user)

    def test_a_bet_a_bot_holds_refuses_the_chat_order(self):
        holder = _config(self.user, asset_class="stock", name="momentum")
        _open(holder, "AAPL", rule="golden_cross")
        out = self._execute("buy")
        self.assertEqual(out["status"], "error")
        self.assertIn("golden_cross", out["message"])
        from portfolio.models import Position
        self.assertFalse(Position.objects.filter(
            instrument=self.inst, closed_at__isnull=True).exists())

    def test_a_clean_book_still_executes(self):
        out = self._execute("buy")
        self.assertEqual(out["status"], "executed")

    def test_the_chat_orders_own_position_then_blocks_a_repeat(self):
        """The row it just booked lands on the user's own book — which
        the gates scan, so the SECOND identical chat order refuses. The
        lane that had no gate cannot even double itself now."""
        self.assertEqual(self._execute("buy")["status"], "executed")
        out = self._execute("buy")
        self.assertEqual(out["status"], "error")
        self.assertIn("portfolio position", out["message"])

    def test_the_theme_cap_refuses_in_chat_too(self):
        """No confirm step exists here to carry a warning into — an
        advisory would be a gate that only ever said yes."""
        from market_data.models import LiveQuote
        _book(max_theme_legs=2)
        for i, sym in enumerate(("EURUSD", "EURJPY")):
            _open(_config(self.user, name=f"fx{i}"), sym)
        eurgbp = _instrument("EURGBP", "forex")
        LiveQuote.objects.update_or_create(
            instrument=eurgbp,
            defaults={"last": Decimal("0.86"), "source": "test"})
        out = self._execute("buy", "EURGBP")
        self.assertEqual(out["status"], "error")
        self.assertIn("long EUR", out["message"])


class ManualPathTests(TestCase):
    """Duplicate refuses even the human path; theme warns and is recorded."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("mp_u", password="x")

    def setUp(self):
        from market_data.models import LiveQuote
        _book(current_value=Decimal("10000"), max_daily_loss_pct=100.0,
              max_total_exposure_pct=1000.0, max_single_position_pct=100.0,
              max_theme_legs=3)
        self.inst = _instrument("BTCUSD", "crypto", "CRYPTO")
        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("50000"), "source": "binance_public"})

    def test_preview_refuses_a_bet_a_bot_already_holds(self):
        from bot_program.manual_trade import preview_asset_trade
        holder = _config(self.user, asset_class="crypto", name="momentum")
        _open(holder, "BTCUSD", rule="golden_cross", asset_class="crypto")

        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertIn("error", out)
        self.assertIn("golden_cross", out["error"])

    def test_execute_refuses_it_too(self):
        """The preview is advice; the execute-side re-ask under the lock
        is the enforcement — a bot may have opened this exact bet between
        the popup and the click."""
        from bot_program.manual_trade import execute_asset_trade
        holder = _config(self.user, asset_class="crypto", name="momentum2")
        _open(holder, "BTCUSD", rule="golden_cross", asset_class="crypto")

        out = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertIn("error", out)
        self.assertIn("golden_cross", out["error"])
        from bot_program.models import AssetBotTrade
        self.assertFalse(AssetBotTrade.objects.filter(
            symbol="BTCUSD", status="OPEN",
            metadata__manual=True).exists())

    def test_the_short_side_of_the_same_symbol_is_still_takeable(self):
        from bot_program.manual_trade import preview_asset_trade
        holder = _config(self.user, asset_class="crypto", name="momentum3")
        _open(holder, "BTCUSD", rule="golden_cross", asset_class="crypto")
        out = preview_asset_trade(self.user, self.inst, "SELL")
        self.assertNotIn("error", out)

    def test_preview_carries_the_theme_reading(self):
        """The popup renders p.theme the way it renders book_advisory —
        the payload must carry it, stated even when it is quiet."""
        from bot_program.manual_trade import preview_asset_trade
        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out)
        self.assertIn("theme", out)
        self.assertTrue(out["theme"]["ok"])
        self.assertIn("forex only", out["theme"]["reason"])

    def test_a_taken_trade_records_the_theme_state_at_entry(self):
        """Same rule as its siblings: an override nobody recorded cannot
        be reviewed afterwards."""
        from bot_program.manual_trade import execute_asset_trade
        from bot_program.models import AssetBotTrade
        out = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out)
        trade = AssetBotTrade.objects.get(id=out["trade_id"])
        self.assertIn("theme_at_entry", trade.metadata)
        self.assertTrue(trade.metadata["theme_at_entry"]["ok"])


class CardTests(TestCase):
    """The new knob rides the same all-or-none save as its siblings."""

    def test_a_whole_number_saves_and_a_fraction_is_rejected_not_rounded(self):
        from dashboard.views import _apply_risk_limits
        from portfolio.risk_gate import limits_book
        pf = _book()
        ok, rejected = _apply_risk_limits(pf, {
            "max_exposure": "100", "max_position": "10",
            "max_daily_loss": "3", "max_correlation": "0.7",
            "max_theme_legs": "2"})
        self.assertTrue(ok, rejected)
        self.assertEqual(limits_book().max_theme_legs, 2)

        ok, rejected = _apply_risk_limits(pf, {
            "max_exposure": "100", "max_position": "10",
            "max_daily_loss": "3", "max_correlation": "0.7",
            "max_theme_legs": "2.5"})
        self.assertFalse(ok)
        self.assertTrue(any("whole number" in r for r in rejected))
        self.assertEqual(limits_book().max_theme_legs, 2,
                         "a rejected save must not have half-written")

    def test_zero_is_a_legal_off_switch_here(self):
        """0 means halt on the sibling limits and is out of their bounds;
        on a count it means OFF, and the operator may say so."""
        from dashboard.views import _apply_risk_limits
        from portfolio.risk_gate import limits_book
        ok, rejected = _apply_risk_limits(_book(), {
            "max_exposure": "100", "max_position": "10",
            "max_daily_loss": "3", "max_correlation": "0.7",
            "max_theme_legs": "0"})
        self.assertTrue(ok, rejected)
        self.assertEqual(limits_book().max_theme_legs, 0)
