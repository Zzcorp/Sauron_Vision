"""MAX OPEN RISK: what the open positions may lose together (2026-10-01).

The operator, with 25 live bots drawing on one shared account: "15% de
risque ouvert max". Each position risks a small share of the account at
its stop and the daily stop counts only what has CLOSED, so nothing bound
what the open ones would lose together. risk_gate.open_risk_state sums
qty x |entry - stop| x value_per_unit over every open row of one venue (a
row with no stop counts its whole notional; a stop trailed through the
entry counts nothing), against Portfolio.max_open_risk_pct (default 15)
of the venue's book. Hard for the bots — in preflight with nothing added,
and on the final size of each entry — and stated on the manual ticket
through the book advisory, like the other book limits.

Run with:  python manage.py test tests.test_open_risk
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from tests.test_risk_limits_bind import _book, _config


def _row(cfg, *, entry="100", stop="90", qty="10", side="BUY", paper=True,
         status="OPEN", metadata=None):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="BTCUSD", side=side,
        qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=None if stop is None else Decimal(stop), status=status,
        paper=paper, metadata=metadata or {})


class TheRowRiskTests(SimpleTestCase):

    def test_a_long_and_a_short_risk_their_distance_to_the_stop(self):
        from portfolio.risk_gate import _row_risk
        self.assertEqual(_row_risk(10, 100, 90, "BUY"), (100.0, True))
        self.assertEqual(_row_risk(10, 100, 110, "SELL"), (100.0, True))

    def test_the_value_per_unit_converts(self):
        from portfolio.risk_gate import _row_risk
        self.assertAlmostEqual(_row_risk(1000, 1.10, 1.09, "BUY", 1.25)[0],
                               12.5)

    def test_a_stop_trailed_through_the_entry_risks_nothing(self):
        from portfolio.risk_gate import _row_risk
        self.assertEqual(_row_risk(10, 100, 105, "BUY"), (0.0, True))

    def test_no_stop_counts_the_whole_notional(self):
        from portfolio.risk_gate import _row_risk
        self.assertEqual(_row_risk(10, 100, None, "BUY"), (1000.0, False))
        self.assertEqual(_row_risk(10, 100, 0, "BUY"), (1000.0, False))


class TheStateTests(TestCase):
    """A 10,000 paper book at 15%: a 1,500 ceiling."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("or_state",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("10000"), max_open_risk_pct=15.0)
        self.cfg = _config(self.user)

    def _state(self, **kw):
        from portfolio.risk_gate import open_risk_state
        return open_risk_state(self.user, venue="paper", **kw)

    def test_the_default_is_fifteen(self):
        from portfolio.models import Portfolio
        self.assertEqual(Portfolio._meta.get_field(
            "max_open_risk_pct").default, 15)

    def test_inside_the_ceiling(self):
        _row(self.cfg)                      # 100 at the stop
        s = self._state()
        self.assertTrue(s["ok"], s["reason"])
        self.assertEqual((s["open_risk"], s["limit_money"], s["rows"]),
                         (100.0, 1500.0, 1))

    def test_an_entry_that_would_pass_it_is_refused_with_both_numbers(self):
        _row(self.cfg, qty="140")           # 1,400 at the stop
        s = self._state(adding=200.0)
        self.assertFalse(s["ok"])
        self.assertIn("open risk limit: 1,400.00 at the stops of 1 open "
                      "position(s) + 200.00 for this entry against a "
                      "1,500.00 ceiling (15% of the 10,000.00 book)",
                      s["reason"])

    def test_a_row_without_a_stop_counts_its_notional_and_is_named(self):
        _row(self.cfg, stop=None, qty="16")   # 1,600 of notional
        s = self._state()
        self.assertFalse(s["ok"])
        self.assertEqual(s["unstopped"], 1)
        self.assertIn("1 without a stop, counted at their whole notional",
                      s["reason"])

    def test_the_venues_are_judged_apart(self):
        _row(self.cfg, qty="140", paper=False)
        self.assertEqual(self._state()["open_risk"], 0.0)

    def test_closed_rows_risk_nothing_and_close_pending_still_does(self):
        _row(self.cfg, status="CLOSED", qty="500")
        _row(self.cfg, status="CLOSE_PENDING")
        self.assertEqual(self._state()["open_risk"], 100.0)

    def test_no_limit_and_no_book_bind_nothing(self):
        _row(self.cfg, qty="500")
        _book(max_open_risk_pct=0)
        self.assertTrue(self._state()["ok"])
        _book(max_open_risk_pct=15.0, current_value=Decimal("0"))
        s = self._state()
        self.assertTrue(s["ok"])
        self.assertIn("never been set", s["reason"])


class TheLegacyRowsTests(TestCase):
    """Review, 2026-10-02: closed legacy Position rows were counted for
    ever, and a Position the legacy eToro import wrote for a position a bot
    row already counts was counted twice."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("or_legacy",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("10000"), max_open_risk_pct=15.0)
        self.cfg = _config(self.user)

    def _position(self, symbol, *, closed=False):
        from django.utils import timezone

        from instruments.models import Instrument
        from portfolio.models import Position
        from portfolio.risk_gate import limits_book
        inst, _ = Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "crypto"})
        return Position.objects.create(
            portfolio=limits_book(), instrument=inst, direction="long",
            quantity=Decimal("10"), entry_price=Decimal("100"),
            current_price=Decimal("100"), stop_loss=Decimal("90"),
            opened_at=timezone.now(),
            closed_at=timezone.now() if closed else None)

    def test_a_closed_or_mirrored_legacy_row_counts_nothing(self):
        from portfolio.risk_gate import open_risk_state
        _row(self.cfg, paper=False)                  # BTCUSD: 100 at risk
        self._position("BTCUSD")                     # its legacy mirror
        self._position("ETHUSD", closed=True)        # closed long ago
        st = open_risk_state(self.user, venue="live")
        self.assertEqual((st["open_risk"], st["rows"]), (100.0, 1))
        self._position("SOLUSD")                     # an open hand-added one
        st = open_risk_state(self.user, venue="live")
        self.assertEqual((st["open_risk"], st["rows"]), (200.0, 2))

    def test_an_options_row_counts_its_contract_multiplier(self):
        from portfolio.risk_gate import open_risk_state
        cfg = _config(self.user, asset_class="options")
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.create(
            config=cfg, asset_class="options", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("5"),
            stop_loss=Decimal("3"), status="OPEN", paper=True,
            metadata={"multiplier": 100})
        st = open_risk_state(self.user, venue="paper")
        self.assertEqual(st["open_risk"], 200.0)


class TheGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("or_gate",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("10000"), max_open_risk_pct=15.0)

    def test_past_the_ceiling_no_bot_entry_opens(self):
        from bot_program.asset_engine.base import make_bot
        bot = make_bot(_config(self.user, symbols=["BTCUSD"]))
        _row(bot.cfg, qty="160")            # 1,600 at the stops
        ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("open risk limit", reason)

    def test_the_final_size_is_judged_with_its_own_risk(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot._judge_final_size)
        self.assertIn("orisk = open_risk_state(", src)
        self.assertIn("adding = qty * abs(float(price) - float(sl))", src)
        self.assertIn("self._skip(symbol, skips.GATE_BLOCKED, note + "
                      "orisk[\"reason\"])", src)

    def test_the_manual_ticket_is_told_not_refused(self):
        """A hand-taken ticket reads the book limits as an advisory: the
        open-risk check rides book_advisory's checks."""
        from portfolio.risk_gate import preflight
        cfg = _config(self.user, symbols=[])
        _row(cfg, qty="160", paper=False)
        out = preflight(self.user)
        self.assertIn("open_risk", out["checks"])


class TheCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("or_card",
                                                        password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _post(self, **overrides):
        data = {"action": "update_risk", "max_exposure": "100",
                "max_position": "20", "max_daily_loss": "8",
                "max_correlation": "0.7", "max_theme_legs": "3"}
        data.update(overrides)
        return self.client.post("/setup/", data, follow=True)

    def test_the_card_saves_it_and_renders_it(self):
        from portfolio.risk_gate import limits_book
        self._post(max_open_risk="15")
        self.assertAlmostEqual(limits_book().max_open_risk_pct, 15.0)
        r = self.client.get("/setup/")
        self.assertContains(r, 'name="max_open_risk"')
        self.assertContains(r, "MAX OPEN RISK")

    def test_out_of_bounds_is_refused_and_absent_keeps_it(self):
        from portfolio.risk_gate import limits_book
        _book(max_open_risk_pct=15.0)
        for raw in ("0", "150", "abc"):
            self.assertContains(self._post(max_open_risk=raw), "NOT saved")
            self.assertAlmostEqual(limits_book().max_open_risk_pct, 15.0)
        self._post(max_daily_loss="6")
        self.assertAlmostEqual(limits_book().max_open_risk_pct, 15.0)
