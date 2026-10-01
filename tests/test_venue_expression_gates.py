"""Paper and real money are judged on their own books (2026-10-01).

The operator, on a real-money EURAUD ticket: "seriously? The paper and
live are still on a joint brain?" It was refused with "EURAUD long is
already on the book via golden_cross — a second ticket doubles the bet":
the holder was a PAPER bot. Simulated money doubles no real bet. The money
limits already judged each venue apart (open_capital_at_work,
realized_since); the expression gates — duplicate, theme, concentration,
correlation — read every open row of both.

Each now takes `paper`: True reads the simulated book, False the real one
(legacy portfolio.Position rows, which carry no venue, count as live),
None both as before. The manual lane passes its own venue, the bot path
the venue its entry is filed under.

Run with:  python manage.py test tests.test_venue_expression_gates
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from tests.test_one_bet_one_ticket import _book, _config, _instrument, _open


def _live(row):
    row.paper = False
    row.save(update_fields=["paper"])
    return row


class TheDuplicateGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_dup",
                                                        password="x")

    def setUp(self):
        self.asker = _config(self.user, name="manual")

    def test_a_paper_holder_does_not_refuse_a_real_money_ticket(self):
        """The operator's EURAUD."""
        from portfolio.risk_gate import duplicate_state
        _open(_config(self.user, name="research_forex_1"), "EURAUD")
        live = duplicate_state(self.user, symbol="EURAUD", side="BUY",
                               config_id=self.asker.id, paper=False)
        self.assertTrue(live["ok"], live["reason"])

    def test_a_paper_holder_still_refuses_a_paper_ticket(self):
        from portfolio.risk_gate import duplicate_state
        _open(_config(self.user, name="research_forex_1"), "EURAUD")
        state = duplicate_state(self.user, symbol="EURAUD", side="BUY",
                                config_id=self.asker.id, paper=True)
        self.assertFalse(state["ok"])
        self.assertIn("already on the paper book via golden_cross",
                      state["reason"])

    def test_a_real_holder_refuses_a_real_ticket_and_not_a_paper_one(self):
        from portfolio.risk_gate import duplicate_state
        _live(_open(_config(self.user, name="fx_majors_live"), "EURAUD"))
        live = duplicate_state(self.user, symbol="EURAUD", side="BUY",
                               config_id=self.asker.id, paper=False)
        self.assertFalse(live["ok"])
        self.assertIn("already on the real-money book", live["reason"])
        self.assertTrue(duplicate_state(
            self.user, symbol="EURAUD", side="BUY",
            config_id=self.asker.id, paper=True)["ok"])

    def test_unnamed_reads_both_books_as_before(self):
        from portfolio.risk_gate import duplicate_state
        _open(_config(self.user, name="research_forex_1"), "EURAUD")
        state = duplicate_state(self.user, symbol="EURAUD", side="BUY",
                                config_id=self.asker.id)
        self.assertFalse(state["ok"])
        self.assertIn("already on the book via", state["reason"])

    def test_a_legacy_position_is_live_never_paper(self):
        from portfolio.models import Position
        from portfolio.risk_gate import duplicate_state, limits_book
        from django.utils import timezone
        Position.objects.create(
            portfolio=limits_book(), instrument=_instrument("EURAUD"),
            direction="long", entry_price=Decimal("1.7"),
            current_price=Decimal("1.7"), quantity=Decimal("1000"),
            opened_at=timezone.now())
        self.assertFalse(duplicate_state(
            self.user, symbol="EURAUD", side="BUY",
            config_id=self.asker.id, paper=False)["ok"])
        self.assertTrue(duplicate_state(
            self.user, symbol="EURAUD", side="BUY",
            config_id=self.asker.id, paper=True)["ok"])


class TheThemeGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_theme",
                                                        password="x")

    def test_paper_legs_crowd_no_real_currency(self):
        from portfolio.risk_gate import theme_state
        _book(max_theme_legs=3)
        holder = _config(self.user, name="research")
        for sym in ("EURUSD", "EURJPY", "EURGBP"):
            _open(holder, sym, rule="r")
        paper = theme_state(self.user, symbol="EURAUD", side="BUY",
                            asset_class="forex", paper=True)
        self.assertFalse(paper["ok"])
        live = theme_state(self.user, symbol="EURAUD", side="BUY",
                           asset_class="forex", paper=False)
        self.assertTrue(live["ok"], live["reason"])


class TheConcentrationGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_conc",
                                                        password="x")

    def test_paper_exposure_is_not_held_against_a_real_ticket(self):
        from portfolio.risk_gate import (concentration_state,
                                         symbol_side_exposure)
        _book(max_single_position_pct=20.0)
        holder = _config(self.user, asset_class="stock", name="research")
        row = _open(holder, "AAPL", rule="r")
        row.qty = Decimal("50")          # 5,000 at 100 — paper
        row.save(update_fields=["qty"])
        self.assertEqual(symbol_side_exposure(
            self.user, "AAPL", "BUY", paper=False)["n"], 0)
        self.assertEqual(symbol_side_exposure(
            self.user, "AAPL", "BUY", paper=True)["n"], 1)
        kw = dict(symbol="AAPL", side="BUY", asset_class="stock",
                  notional=100.0, capital_base=1000.0)
        self.assertFalse(concentration_state(self.user, paper=True,
                                             **kw)["ok"])
        self.assertTrue(concentration_state(self.user, paper=False,
                                            **kw)["ok"])


class TheCorrelationTaperTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_corr",
                                                        password="x")

    def test_a_real_ticket_has_nothing_to_correlate_with_a_paper_book(self):
        from portfolio.risk_gate import correlation_state
        _book(max_correlation_threshold=0.7)
        _open(_config(self.user, name="research"), "EURUSD", rule="r")
        _instrument("EURUSD")
        state = correlation_state(self.user, _instrument("GBPUSD"),
                                  paper=False)
        self.assertEqual(state["reason"], "nothing open to be correlated with")


class TheManualLaneTests(TestCase):
    """The ticket passes its own venue: a paper lane is judged on the
    paper book, so a REAL bot's long no longer refuses it — and a live
    lane is judged on the real book (the operator's EURAUD), which the
    gate tests above pin."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_lane",
                                                        password="x")

    def setUp(self):
        from market_data.models import LiveQuote
        _book(current_value=Decimal("10000"), max_daily_loss_pct=100.0,
              max_total_exposure_pct=1000.0, max_single_position_pct=100.0,
              max_theme_legs=3)
        self.inst = _instrument("BTCUSD", "crypto", "CRYPTO")
        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("50000"), "source": "binance_public"})

    def test_a_real_holder_does_not_refuse_a_paper_ticket(self):
        from bot_program.manual_trade import preview_asset_trade
        holder = _config(self.user, asset_class="crypto", name="btc_live",
                         mode="live")
        _live(_open(holder, "BTCUSD", rule="golden_cross",
                    asset_class="crypto"))
        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out)

    def test_a_paper_holder_still_refuses_a_paper_ticket(self):
        from bot_program.manual_trade import preview_asset_trade
        holder = _config(self.user, asset_class="crypto", name="momentum")
        _open(holder, "BTCUSD", rule="golden_cross", asset_class="crypto")
        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertIn("already on the paper book via golden_cross",
                      out.get("error", ""))


class TheBotPathTests(TestCase):
    """The bot passes the venue its entry is filed under, on both halves
    of the entry path and to the correlation taper."""

    def test_the_entry_path_names_its_venue(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        judge = inspect.getsource(AssetBot._judge_final_size)
        self.assertIn("paper = None if venue is None else (venue == \"paper\")",
                      judge)
        self.assertIn("config_id=self.cfg.id, paper=paper)", judge)
        self.assertIn("asset_class=self.asset_class, paper=paper)", judge)
        self.assertIn("venue=cand.venue", inspect.getsource(
            AssetBot.execute_entry))
        propose = inspect.getsource(AssetBot.propose_entry)
        self.assertIn('venue=("paper" if (self.cfg.mode == "paper"', propose)
        self.assertIn("correlation_state(\n                self.user, inst,\n"
                      "                paper=", propose)
