"""MAX BOT LEVERAGE on /setup/ (2026-11-05): the bots measured, the
hand-taken ticket at the highest.

The operator, 2026-11-04: "restaurer achat et vente manuel en leverage max
et plus mesuré pour les bots" (restore manual buy and sell at max
leverage, and more measured for the bots). On 2026-10-05 he had said "pas
de limite à l'attaque" (no limit on the bots' attack mode); after a margin
brake on 2026-11-01 he wants the bots measured while his hand-taken
tickets stay at the highest. The one switch etoro_leverage_live opens
leverage for both, so the bots get their own cap on the limits book.

Pinned here: Portfolio.max_bot_leverage (a whole number of x, 1 to
MAX_ORDER_LEVERAGE, NULL by default: no cap, today's behaviour) and its
migration; base.bot_leverage_cap(), read at call time (blank, out of
bounds and an unreadable book answer no cap, the last two logged); the
/setup/ Risk Limits card (saves it with the others, all or none, its
bounds, a blank input stores NULL, an older form without the field still
saves); the attack mode's chooser picking at most the cap and saying so;
a typed multiplier above the cap sent at the cap, or, when eToro does not
take the cap itself (its steps: 2, 5, 10, 20, 30 as measured), at the
highest multiplier under the cap on the instrument's LIVE list (the
review of 2026-11-05: a cap between two steps sent as it was met the
instrument's own refusal on every tick, the bot stopped) — the cap
refuses nothing, and a refusal after it leads with its words; the
configured and the sent multiplier both on the row, every refusal of
main kept; a config without a key, the TAKE TRADE ticket (its choices
and its default) and every config named "manual" never capped;
preflight_live §4's lines; the /ops/ words of etoro_leverage_live.

Run with:  python manage.py test tests.test_max_bot_leverage
"""
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_attack_mode import PROVEN, PROVEN_LEV, _wire
from tests.test_desk_seam import _client as _mock_client
from tests.test_etoro_client import (ROW_AAPL_LIVE, ROW_EURUSD_LIVE,
                                     _clear_eligibility)
from tests.test_etoro_leverage import (ROUTER, _account, _book, _etoro,
                                       _order_posts, _switch)
from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument, _signal, _user

BASE_LOG = "bot_program.asset_engine.base"


def _cap(value):
    """MAX BOT LEVERAGE as the /setup/ card stores it, on the limits book."""
    from portfolio.risk_gate import limits_book
    book = limits_book()
    book.max_bot_leverage = value
    book.save(update_fields=["max_bot_leverage", "updated_at"])
    return book


# ── the setting ─────────────────────────────────────────────────────────

class TheSettingTests(TestCase):

    def test_blank_by_default_bounded_like_the_card(self):
        from bot_program.asset_engine.base import (BOT_LEVERAGE_BOUNDS,
                                                   MAX_ORDER_LEVERAGE)
        from dashboard.views import (RISK_LIMIT_BOUNDS, RISK_LIMIT_FIELDS,
                                     RISK_LIMIT_OPTIONAL)
        from portfolio.models import Portfolio
        from portfolio.risk_gate import limits_book
        field = Portfolio._meta.get_field("max_bot_leverage")
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
        self.assertIsNone(field.get_default())
        self.assertIsNone(limits_book().max_bot_leverage)
        self.assertEqual(BOT_LEVERAGE_BOUNDS, (1, MAX_ORDER_LEVERAGE))
        self.assertEqual(MAX_ORDER_LEVERAGE, 30)
        self.assertEqual(RISK_LIMIT_BOUNDS["max_bot_leverage"],
                         (1, 30, "Max bot leverage"))
        self.assertEqual(RISK_LIMIT_BOUNDS["max_bot_leverage"][:2],
                         BOT_LEVERAGE_BOUNDS)
        self.assertEqual(RISK_LIMIT_FIELDS["max_bot_leverage"],
                         "max_bot_leverage")
        self.assertIn("max_bot_leverage", RISK_LIMIT_OPTIONAL)

    def test_the_migration_adds_it_null_so_nothing_changes_on_deploy(self):
        from django.db.migrations.loader import MigrationLoader
        name = "0018_portfolio_max_bot_leverage"
        self.assertTrue(Path(f"portfolio/migrations/{name}.py").exists())
        loader = MigrationLoader(None, ignore_no_migrations=True)
        mig = loader.disk_migrations[("portfolio", name)]
        self.assertEqual(mig.dependencies,
                         [("portfolio", "0017_portfolio_max_notional_multiple")])
        self.assertEqual(len(mig.operations), 1)
        op = mig.operations[0]
        self.assertEqual((type(op).__name__, op.model_name, op.name),
                         ("AddField", "portfolio", "max_bot_leverage"))
        self.assertTrue(op.field.null)
        self.assertIsNone(op.field.get_default())

    def test_a_book_saved_before_the_setting_reads_no_cap(self):
        """A row created as every row was before the field existed (no
        value given) reads NULL, and the reader answers no cap."""
        from bot_program.asset_engine.base import bot_leverage_cap
        from portfolio.models import Portfolio
        Portfolio.objects.create(name="Main", initial_capital=Decimal("100"),
                                 current_value=Decimal("100"),
                                 cash_available=Decimal("100"))
        self.assertIsNone(Portfolio.objects.get(name="Main").max_bot_leverage)
        with self.assertNoLogs(BASE_LOG, "WARNING"):
            self.assertIsNone(bot_leverage_cap())

    def test_the_operators_cap_is_read_at_call_time(self):
        from bot_program.asset_engine.base import bot_leverage_cap
        _cap(2)
        self.assertEqual(bot_leverage_cap(), 2)
        _cap(10)
        self.assertEqual(bot_leverage_cap(), 10)
        _cap(None)
        self.assertIsNone(bot_leverage_cap())

    def test_out_of_bounds_reads_no_cap_and_says_so(self):
        from bot_program.asset_engine.base import bot_leverage_cap
        for value in (0, -1, 31, 100):
            _cap(value)
            with self.assertLogs(BASE_LOG, "WARNING") as logs:
                self.assertIsNone(bot_leverage_cap(), value)
            self.assertIn("MAX BOT LEVERAGE", logs.output[0])
            self.assertIn("no cap", logs.output[0])

    def test_a_value_that_is_not_a_whole_number_reads_no_cap(self):
        """A number only: a string, a bool, a fraction, NaN or a stand-in
        object (a MagicMock would read 1.0 through float()) is no cap, said;
        a whole float is its number."""
        from bot_program.asset_engine.base import bot_leverage_cap
        for raw in ("2", True, 2.5, float("nan"), mock.MagicMock()):
            with mock.patch("portfolio.risk_gate.limits_book",
                            return_value=SimpleNamespace(max_bot_leverage=raw)), \
                    self.assertLogs(BASE_LOG, "WARNING"):
                self.assertIsNone(bot_leverage_cap(), repr(raw))
        with mock.patch("portfolio.risk_gate.limits_book",
                        return_value=SimpleNamespace(max_bot_leverage=2.0)):
            self.assertEqual(bot_leverage_cap(), 2)

    def test_an_unreadable_book_reads_no_cap_as_main_did_and_says_so(self):
        """Fails to what every bot did before the setting existed (main,
        2026-11-04: no cap) — never to anything looser — and logs it."""
        from bot_program.asset_engine.base import bot_leverage_cap
        _cap(2)
        with mock.patch("portfolio.risk_gate.limits_book",
                        side_effect=RuntimeError("db gone")), \
                self.assertLogs(BASE_LOG, "WARNING") as logs:
            self.assertIsNone(bot_leverage_cap())
        self.assertIn("MAX BOT LEVERAGE unreadable (RuntimeError)",
                      logs.output[0])

    def test_the_manual_config_is_never_capped_and_never_reads_the_book(self):
        from bot_program.asset_engine.base import bot_leverage_cap
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        _cap(2)
        self.assertEqual(bot_leverage_cap(SimpleNamespace(name="FX bot")), 2)
        with mock.patch("portfolio.risk_gate.limits_book") as book:
            self.assertIsNone(bot_leverage_cap(
                SimpleNamespace(name=MANUAL_CONFIG_NAME)))
        book.assert_not_called()

    def test_etoros_steps_and_the_step_each_cap_reads_as(self):
        """The review of 2026-11-05: eToro takes only the multipliers on an
        instrument's LIVE list, and every list measured is a run of one
        ladder — 1, 2, 5, 10, 20, 30 (the measured rows below). The words
        that cannot ask eToro (preflight §4) read a cap between two steps
        as the step under it; the engine reads the instrument's own list."""
        from bot_program.asset_engine.base import (ETORO_LEVERAGE_STEPS,
                                                   MAX_ORDER_LEVERAGE,
                                                   bot_cap_step)
        from tests.test_attack_mode import ROW_SPX500_LIVE
        from tests.test_etoro_client import ROW_BTC_LIVE
        self.assertEqual(ETORO_LEVERAGE_STEPS, (1, 2, 5, 10, 20, 30))
        self.assertEqual(max(ETORO_LEVERAGE_STEPS), MAX_ORDER_LEVERAGE)
        for row in (ROW_EURUSD_LIVE, ROW_AAPL_LIVE, ROW_SPX500_LIVE,
                    ROW_BTC_LIVE):
            for entry in row["leverageConfigs"]:
                vals = sorted(entry["leverageValues"])
                self.assertEqual(vals, [s for s in ETORO_LEVERAGE_STEPS
                                        if vals[0] <= s <= vals[-1]],
                                 (row["symbol"], entry))
        expected = {1: 1, 2: 2, 3: 2, 4: 2, 5: 5, 6: 5, 9: 5, 10: 10,
                    11: 10, 19: 10, 20: 20, 21: 20, 29: 20, 30: 30}
        for cap, step in expected.items():
            self.assertEqual(bot_cap_step(cap), step, cap)


# ── the /setup/ card ────────────────────────────────────────────────────

class TheCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("botlev_ui",
                                                        password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _post(self, **overrides):
        data = {"action": "update_risk", "max_exposure": "100",
                "max_position": "20", "max_daily_loss": "8",
                "max_correlation": "0.7", "max_theme_legs": "3"}
        data.update(overrides)
        return self.client.post("/setup/", data, follow=True)

    def test_the_card_saves_it_with_the_others(self):
        from portfolio.risk_gate import limits_book
        r = self._post(max_bot_leverage="2", max_daily_loss="6")
        self.assertContains(r, "Risk limits updated")
        book = limits_book()
        self.assertEqual(book.max_bot_leverage, 2)
        self.assertAlmostEqual(book.max_daily_loss_pct, 6.0)

    def test_a_blank_input_stores_null(self):
        from portfolio.risk_gate import limits_book
        for blank in ("", "   "):
            _cap(5)
            r = self._post(max_bot_leverage=blank, max_daily_loss="6")
            self.assertContains(r, "Risk limits updated")
            book = limits_book()
            self.assertIsNone(book.max_bot_leverage, repr(blank))
            self.assertAlmostEqual(book.max_daily_loss_pct, 6.0)

    def test_out_of_bounds_or_not_whole_is_refused_and_nothing_is_saved(self):
        from portfolio.risk_gate import limits_book
        _cap(5)
        for raw in ("0", "-1", "31", "2.5", "abc"):
            r = self._post(max_bot_leverage=raw, max_daily_loss="4")
            self.assertContains(r, "NOT saved")
            self.assertContains(r, "Max bot leverage")
            book = limits_book()
            self.assertEqual(book.max_bot_leverage, 5, raw)
            self.assertNotAlmostEqual(book.max_daily_loss_pct, 4.0, msg=raw)

    def test_a_sibling_refused_saves_no_cap_either(self):
        from portfolio.risk_gate import limits_book
        r = self._post(max_bot_leverage="2", max_daily_loss="")
        self.assertContains(r, "NOT saved")
        self.assertIsNone(limits_book().max_bot_leverage)

    def test_a_form_without_the_field_still_saves(self):
        """A card rendered before the field existed: the others save, the
        cap stays blank on a fresh book, and a stored cap is kept (absent
        is not blank)."""
        from portfolio.risk_gate import limits_book
        r = self._post(max_daily_loss="6")
        self.assertContains(r, "Risk limits updated")
        book = limits_book()
        self.assertAlmostEqual(book.max_daily_loss_pct, 6.0)
        self.assertIsNone(book.max_bot_leverage)
        _cap(3)
        self._post(max_daily_loss="7")
        book = limits_book()
        self.assertAlmostEqual(book.max_daily_loss_pct, 7.0)
        self.assertEqual(book.max_bot_leverage, 3)

    def test_the_card_renders_it_blank_with_its_help(self):
        r = self.client.get("/setup/")
        self.assertContains(r, "MAX BOT LEVERAGE (x)")
        self.assertContains(r, 'name="max_bot_leverage" value=""')
        self.assertNotContains(r, 'name="max_bot_leverage" value="None"')
        self.assertContains(r, "Never the hand-taken TAKE TRADE ticket")
        self.assertContains(r, "blank = no cap")
        _cap(2)
        r = self.client.get("/setup/")
        self.assertContains(r, 'name="max_bot_leverage" value="2"')

    def test_the_help_says_a_cap_between_steps_goes_at_the_step_under_it(
            self):
        """The review of 2026-11-05: the card takes any whole number from 1
        to 30 and eToro only its steps; the help says what a cap between
        two steps sends."""
        r = self.client.get("/setup/")
        self.assertContains(r, "or at eToro&#x27;s highest step under it")
        self.assertContains(r, "its steps are 2, 5, 10, 20 and 30")
        self.assertNotContains(r, "sent at this instead.")

    def test_the_input_takes_a_blank_and_whole_numbers_only(self):
        """The browser must submit a blank (no `required`) and whole
        multipliers from 1 to 30 (step 1 from a base of 1)."""
        for d in settings.TEMPLATES[0]["DIRS"]:
            path = Path(d) / "dashboard/setup.html"
            if path.exists():
                body = path.read_text(encoding="utf-8")
                break
        tags = [t for t in re.findall(r"<input[^>]*>", body)
                if 'name="max_bot_leverage"' in t]
        self.assertEqual(len(tags), 1)
        tag = tags[0]
        self.assertIn('type="number"', tag)
        self.assertIn('step="1"', tag)
        self.assertIn('min="1"', tag)
        self.assertIn('max="30"', tag)
        self.assertNotIn("required", tag)


# ── the attack mode's chooser ───────────────────────────────────────────

class TheChooserTests(TestCase):
    """EURUSD at a 1.75% stop (the 7% cap's floor on forex): 30x puts the
    stop at 52.5% of the margin, past 70% of the assumed 50% band; 20x at
    35%, inside it. Without a cap the chooser picks 20."""

    ROWS = {"EURUSD": ROW_EURUSD_LIVE, "AAPL": ROW_AAPL_LIVE}

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.user = _user("botlev_pick")
        _instrument("EURUSD", "forex")
        _instrument("AAPL", "stock")
        self.cfg = _live_cfg(self.user, name="BLP")
        self.cfg.extras = {"leverage": "auto"}
        self.cfg.save(update_fields=["extras"])
        self.bot = StockBot(self.cfg)
        _switch(True)

    def _choose(self, symbol="EURUSD", *, price=1.0, stop=0.9825,
                side="BUY"):
        with mock.patch(PROVEN_LEV, {}):
            return self.bot._choose_auto_leverage(_wire(self.ROWS), symbol,
                                                  side, price, stop)

    def test_blank_picks_as_before(self):
        _cap(None)
        lev, why = self._choose()
        self.assertEqual(lev, 20)
        self.assertIn("inside the forex ceiling (30x); the stop is 35.0% of "
                      "the margin", why)
        self.assertNotIn("MAX BOT LEVERAGE", why)
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 30)

    def test_the_cap_binds_the_pick_and_the_words_say_so(self):
        _cap(2)
        lev, why = self._choose()
        self.assertEqual(lev, 2)
        self.assertIn("auto: 2x — the highest on EURUSD's LIVE long/cfd list "
                      "[2, 5, 10, 20, 30] inside the forex ceiling (30x), "
                      "capped at 2x by MAX BOT LEVERAGE; the stop is 3.5% of "
                      "the margin", why)
        _cap(10)
        lev, why = self._choose()
        self.assertEqual(lev, 10)
        self.assertIn("capped at 10x by MAX BOT LEVERAGE", why)

    def test_the_band_still_decides_under_a_higher_cap(self):
        """25x: 30 is out by the cap, 20 still fits the band: the pick
        does not move, and the words name the cap applied."""
        _cap(25)
        lev, why = self._choose()
        self.assertEqual(lev, 20)
        self.assertIn("capped at 25x by MAX BOT LEVERAGE", why)

    def test_a_cap_at_or_above_every_listed_multiplier_says_nothing(self):
        """30 on forex (its ceiling) and 5 on AAPL (its LIVE list [2, 5]
        and its ceiling): nothing the ceiling allows is out, so the pick
        and the words are main's."""
        _cap(30)
        lev, why = self._choose()
        self.assertEqual(lev, 20)
        self.assertNotIn("MAX BOT LEVERAGE", why)
        _cap(5)
        lev, why = self._choose("AAPL", price=100.0, stop=98.0)
        self.assertEqual(lev, 5)
        self.assertNotIn("MAX BOT LEVERAGE", why)

    def test_a_cap_of_one_is_the_unlevered_order(self):
        _cap(1)
        self.assertEqual(self._choose(),
                         (1, "auto: 1x — capped at 1x by MAX BOT LEVERAGE"))

    def test_a_short_is_capped_too(self):
        _cap(5)
        lev, why = self._choose(stop=1.0175, side="SELL")
        self.assertEqual(lev, 5)
        self.assertIn("LIVE short/cfd", why)
        self.assertIn("capped at 5x by MAX BOT LEVERAGE", why)

    def test_the_proposal_counts_the_capped_most(self):
        """MAX SINGLE POSITION before the order counts the most the chooser
        could pick: the cap now joins the class ceiling."""
        _cap(2)
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 2)
        self.assertEqual(self.bot._margin_leverage_hint("AAPL"), 2)
        _cap(10)
        self.assertEqual(self.bot._margin_leverage_hint("AAPL"), 5)
        _switch(False)
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 1)

    def test_the_order_carries_the_capped_pick(self):
        _book(self.user)
        _cap(2)
        with mock.patch(PROVEN_LEV, {}):
            out = self.bot._order_leverage(
                _wire({"EURUSD": ROW_EURUSD_LIVE}), "EURUSD", side="BUY",
                price=1.0, stop=0.9825)
        self.assertEqual(out, (2, ""))
        self.assertEqual(self.bot._auto_pick["EURUSD"]["leverage"], 2)
        self.assertIn("capped at 2x by MAX BOT LEVERAGE",
                      self.bot._auto_pick["EURUSD"]["why"])


# ── a typed multiplier ──────────────────────────────────────────────────

class TheTypedMultiplierTests(TestCase):
    """A stock config typed at 10 trading EURUSD (judged as forex: the
    30x ceiling), the switch ON and the operator's own book saved."""

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.user = _user("botlev_typed")
        _instrument("EURUSD", "forex")
        self.cfg = _live_cfg(self.user, name="BLT")
        self.cfg.extras = {"leverage": 10}
        self.cfg.save(update_fields=["extras"])
        self.bot = StockBot(self.cfg)
        _switch(True)
        _book(self.user)

    def _order(self):
        return self.bot._order_leverage(
            _wire({"EURUSD": ROW_EURUSD_LIVE}), "EURUSD", side="BUY",
            price=1.0, stop=0.9825)

    def _note(self):
        return (getattr(self.bot, "_bot_cap_note", None) or {}).get("EURUSD")

    def test_blank_sends_the_typed_number(self):
        _cap(None)
        self.assertEqual(self._order(), (10, ""))
        self.assertIsNone(self._note())
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 10)

    def test_above_the_cap_goes_at_the_cap_never_refused(self):
        _cap(2)
        with self.assertLogs(BASE_LOG, "INFO") as logs:
            self.assertEqual(self._order(), (2, ""))
        self.assertEqual(self._note(), {
            "cap": 2, "configured": 10, "sent": 2,
            "why": "capped at 2x by MAX BOT LEVERAGE (the config asks 10x)"})
        self.assertTrue(any("capped at 2x by MAX BOT LEVERAGE (the config "
                            "asks 10x)" in line for line in logs.output))

    def test_the_bots_own_hints_count_the_capped_number(self):
        _cap(2)
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 2)
        self.assertEqual(self.bot._bot_leverage_hint(), 2)
        self.assertEqual(self.bot._extras_leverage_hint(), 10,
                         "the typed number itself is unchanged")

    def test_at_or_under_the_cap_is_unchanged(self):
        for value in (10, 20, 30):
            _cap(value)
            self.assertEqual(self._order(), (10, ""), value)
            self.assertIsNone(self._note(), value)

    def test_a_cap_of_one_sends_the_unlevered_order(self):
        _cap(1)
        self.assertEqual(self._order(), (1, ""))
        self.assertEqual(self._note()["sent"], 1)

    def test_a_cap_between_etoros_steps_sends_the_highest_step_under_it(self):
        """The review of 2026-11-05: eToro takes only the multipliers on
        the instrument's LIVE list (EURUSD long: 2, 5, 10, 20, 30) and the
        card takes any whole number from 1 to 30. A typed 10 capped at 3
        and sent at 3 met the instrument's own refusal on every tick — the
        bot stopped, the opposite of the operator's order. It goes at 2x,
        the highest under the cap on that list, both multipliers on the row
        and the words saying why: never above the cap, never refused for
        it. Where the list cannot be read the cap is kept, and the
        instrument's own check refuses it as it refuses every levered order
        there (main refuses the typed 10 the same way), in words that lead
        with the cap."""
        _cap(3)
        with self.assertLogs(BASE_LOG, "INFO") as logs:
            self.assertEqual(self._order(), (2, ""))
        why = ("capped at 3x by MAX BOT LEVERAGE (the config asks 10x): 2x, "
               "the highest under 3x on eToro's LIVE list")
        self.assertEqual(self._note(), {"cap": 3, "configured": 10,
                                        "sent": 2, "why": why})
        self.assertTrue(any(why in line for line in logs.output))
        for cap, step in ((4, 2), (6, 5), (7, 5), (9, 5)):
            _cap(cap)
            self.assertEqual(self._order(), (step, ""), cap)
            self.assertEqual(self._note()["sent"], step, cap)
        _cap(3)
        lev, why = self.bot._order_leverage(
            _wire({}), "EURUSD", side="BUY", price=1.0, stop=0.9825)
        self.assertIsNone(lev)
        self.assertTrue(why.startswith(
            "capped at 3x by MAX BOT LEVERAGE (the config asks 10x): at 3x: "
            "eToro's eligibility row for EURUSD is unread today"), why)
        _cap(None)
        lev, why = self.bot._order_leverage(
            _wire({}), "EURUSD", side="BUY", price=1.0, stop=0.9825)
        self.assertIsNone(lev)
        self.assertTrue(why.startswith(
            "at 10x: eToro's eligibility row for EURUSD is unread today"), why)

    def test_every_cap_sends_a_step_etoro_takes_never_above_it(self):
        """A typed 30 on EURUSD (the forex ceiling) under every cap from 1
        to 30: the multiplier sent is the highest on its LIVE list at or
        under the cap — never above the cap, never refused."""
        self.cfg.extras = {"leverage": 30}
        for cap in range(1, 31):
            _cap(cap)
            step = max(s for s in (1, 2, 5, 10, 20, 30) if s <= cap)
            self.assertEqual(self._order(), (step, ""), cap)
            if cap < 30:
                self.assertEqual(
                    {k: self._note()[k] for k in ("cap", "configured",
                                                  "sent")},
                    {"cap": cap, "configured": 30, "sent": step}, cap)

    def test_nothing_above_one_under_the_cap_sends_the_unlevered_order(self):
        """A LIVE list whose levered steps all sit above the cap: the bot
        goes unlevered, judged by the instrument's own 1x rule as a typed
        1 is."""
        from tests.test_etoro_client import _elig_row, _lev
        row = _elig_row(1002, "EURUSD", [
            _lev("cfd", "long", [1], max_sl=100, min_amount=25),
            _lev("cfd", "long", [5, 10, 20, 30], min_amount=25)],
            min_exposure=1000, w8=False)
        _cap(3)
        self.assertEqual(self.bot._order_leverage(
            _wire({"EURUSD": row}), "EURUSD", side="BUY", price=1.0,
            stop=0.9825), (1, ""))
        self.assertEqual(self._note(), {
            "cap": 3, "configured": 10, "sent": 1,
            "why": ("capped at 3x by MAX BOT LEVERAGE (the config asks "
                    "10x): 1x, nothing above 1 under 3x on eToro's LIVE "
                    "list")})

    def test_a_stock_capped_between_its_two_steps_goes_at_two(self):
        """AAPL's LIVE long list is [2, 5] (a CFD; 1x is the real share): a
        typed 5 under a cap of 3 or 4 goes at 2x. A refusal after the cap
        — here the stop band at 2x — still leads with the cap's words."""
        _instrument("AAPL", "stock")
        self.cfg.extras = {"leverage": 5}
        wire = _wire({"AAPL": ROW_AAPL_LIVE})
        for cap in (3, 4):
            _cap(cap)
            self.assertEqual(self.bot._order_leverage(
                wire, "AAPL", side="BUY", price=100.0, stop=98.0), (2, ""),
                cap)
            self.assertEqual(self.bot._bot_cap_note["AAPL"]["sent"], 2, cap)
        # a stop 30% away is 60% of the margin at 2x: past AAPL's 50% band
        _cap(3)
        lev, why = self.bot._order_leverage(wire, "AAPL", side="BUY",
                                            price=100.0, stop=70.0)
        self.assertIsNone(lev)
        self.assertTrue(why.startswith(
            "capped at 3x by MAX BOT LEVERAGE (the config asks 5x): 2x, the "
            "highest under 3x on eToro's LIVE list: at 2x: the stop is "
            "60.0% of the margin at 2x"), why)

    def test_a_short_the_code_does_not_pin_goes_at_a_step_proven_for_it(self):
        """SPX500 (index: its short is not pinned in the code) goes short
        only at a multiplier the demo account measured, and the chooser
        stays on those. Proven at 2x and 10x, a typed 10 under a cap of 5
        goes at 2x: 5x is on eToro's LIVE list, but no short at 5x is
        proven and it would be refused on every tick. The eToro gate asks
        the proof at the same 2x."""
        from bot_program.asset_engine.base import missing_proofs
        from tests.test_attack_mode import ROW_SPX500_LIVE
        from tests.test_short_proofs import _proof
        _instrument("SPX500", "index")
        _proof("index", 2, symbol="SPX500")
        _proof("index", 10, symbol="SPX500")
        wire = _wire({"SPX500": ROW_SPX500_LIVE})
        _cap(None)
        self.assertEqual(self.bot._order_leverage(
            wire, "SPX500", side="SELL", price=5000.0, stop=5050.0), (10, ""))
        _cap(5)
        self.assertEqual(self.bot._order_leverage(
            wire, "SPX500", side="SELL", price=5000.0, stop=5050.0), (2, ""))
        self.assertEqual(self.bot._bot_cap_note["SPX500"], {
            "cap": 5, "configured": 10, "sent": 2,
            "why": ("capped at 5x by MAX BOT LEVERAGE (the config asks "
                    "10x): 2x, the highest under 5x on eToro's LIVE list "
                    "and the short's demo proofs")})
        hint = self.bot._bot_leverage_hint(wire, "SPX500", "SELL")
        self.assertEqual(hint, 2)
        self.assertEqual(missing_proofs("index", "SELL", leverage=hint), [])

    def test_the_gate_counts_the_step_the_order_is_sent_at(self):
        """The eToro gate in execute_entry asks at the multiplier the order
        will carry: on the client, the step under the cap. Before the
        order (MAX SINGLE POSITION at the proposal) the cap, the most it is
        sent at — judged again at the multiplier sent."""
        wire = _wire({"EURUSD": ROW_EURUSD_LIVE})
        _cap(3)
        self.assertEqual(self.bot._bot_leverage_hint(wire, "EURUSD", "BUY"),
                         2)
        self.assertEqual(self.bot._bot_leverage_hint(), 3)
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 3)
        _cap(5)
        self.assertEqual(self.bot._bot_leverage_hint(wire, "EURUSD", "BUY"),
                         5)
        _cap(None)
        self.assertEqual(self.bot._bot_leverage_hint(wire, "EURUSD", "BUY"),
                         10)

    def test_the_cap_never_lifts_a_refusal(self):
        """Nothing else moves: the switch, the platform cap and the class
        ceiling judge the TYPED number first, as on main."""
        _cap(2)
        _switch(False)
        lev, why = self._order()
        self.assertIsNone(lev)
        self.assertIn("at 10x: etoro_leverage_live is OFF", why)
        _switch(True)
        self.cfg.extras = {"leverage": 50}
        lev, why = self._order()
        self.assertIsNone(lev)
        self.assertIn("platform cap of 30x", why)

    def test_a_config_without_a_key_stays_unlevered(self):
        _cap(2)
        self.cfg.extras = {}
        self.assertEqual(self._order(), (None, ""))
        self.assertIsNone(self.bot._margin_leverage_hint("EURUSD"))
        self.assertIsNone(self.bot._bot_leverage_hint())


# ── the order, end to end ───────────────────────────────────────────────

class TheEntryTests(TestCase):
    """execute_entry on the measured AAPL rows (tests/test_attack_mode.py's
    harness): the candidate priced through the desk-seam MagicMock, the
    order through the REAL EtoroTrader over a fake wire. One user per run."""

    def setUp(self):
        _signal(_instrument(), rule="botlev_rule")
        _switch(True)
        p = mock.patch(PROVEN, frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _cfg(self, name, extras):
        user = _user(name)
        cfg = _live_cfg(user, name=name.upper())
        cfg.base_currency = "USD"
        cfg.extras = dict(extras)
        cfg.save(update_fields=["base_currency", "extras"])
        _book(user)
        _account(user, cash=100000)
        return cfg

    def _run(self, cfg):
        from bot_program.asset_engine.stock_bot import StockBot
        _clear_eligibility()
        bot = StockBot(cfg)
        with mock.patch(PROVEN_LEV, {"stock": 5}):
            with mock.patch(ROUTER, return_value=_mock_client("100.00")):
                cand = bot.propose_entry("AAPL")
            self.assertIsNotNone(cand)
            t, fake = _etoro()
            with mock.patch(ROUTER, return_value=t), \
                    mock.patch("time.sleep"), \
                    mock.patch("bot_program.notifications."
                               "notify_bot_fill_open"):
                res = bot.execute_entry(cand)
        return cand, res, fake

    def test_the_row_records_the_configured_and_the_sent_multiplier(self):
        from bot_program.models import AssetBotTrade
        _cap(None)
        cand5, res5, fake5 = self._run(self._cfg("blev_five", {"leverage": 5}))
        self.assertIsNotNone(res5)
        body5 = _order_posts(fake5)[0][2]["json"]
        row5 = AssetBotTrade.objects.get(id=res5["trade_id"])
        self.assertEqual(body5["leverage"], 5)
        self.assertEqual(row5.metadata["leverage"], 5)
        self.assertNotIn("max_bot_leverage", row5.metadata)
        _cap(2)
        cand2, res2, fake2 = self._run(self._cfg("blev_two", {"leverage": 5}))
        self.assertIsNotNone(res2)
        body2 = _order_posts(fake2)[0][2]["json"]
        row2 = AssetBotTrade.objects.get(id=res2["trade_id"])
        self.assertEqual(body2["leverage"], 2)
        self.assertEqual(row2.metadata["leverage"], 2)
        self.assertEqual(row2.metadata["max_bot_leverage"], {
            "cap": 2, "configured": 5, "sent": 2,
            "why": "capped at 2x by MAX BOT LEVERAGE (the config asks 5x)"})
        # house rule 5: the multiplier never touches units
        self.assertEqual(cand5.qty_default, cand2.qty_default)
        self.assertAlmostEqual(body5["units"], body2["units"], places=9)

    def test_a_cap_between_steps_is_sent_at_the_step_under_it(self):
        """The review's probe (2026-11-05): AAPL's LIVE long list is [2, 5];
        a typed 5 under a cap of 3 sent nothing on every tick (3x refused
        by the instrument's own list, leverage_refused). It is sent at 2x,
        the eToro gate asked at 2x, both multipliers on the row."""
        from bot_program.asset_engine.base import AssetBot
        from bot_program.models import AssetBotTrade
        _cap(3)
        with mock.patch.object(
                AssetBot, "_etoro_entry_refusal",
                wraps=AssetBot._etoro_entry_refusal) as gate:
            _cand, res, fake = self._run(self._cfg("blev_three",
                                                   {"leverage": 5}))
        self.assertIsNotNone(res)
        self.assertEqual(
            {c.kwargs["leverage_hint"] for c in gate.call_args_list}, {2})
        body = _order_posts(fake)[0][2]["json"]
        self.assertEqual(body["leverage"], 2)
        row = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(row.metadata["leverage"], 2)
        self.assertEqual(row.metadata["max_bot_leverage"], {
            "cap": 3, "configured": 5, "sent": 2,
            "why": ("capped at 3x by MAX BOT LEVERAGE (the config asks 5x): "
                    "2x, the highest under 3x on eToro's LIVE list")})

    def test_an_attack_row_carries_the_cap_in_its_words(self):
        from bot_program.models import AssetBotTrade
        _cap(2)
        _, res, fake = self._run(self._cfg("blev_auto", {"leverage": "auto"}))
        self.assertIsNotNone(res)
        self.assertEqual(_order_posts(fake)[0][2]["json"]["leverage"], 2)
        row = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(row.metadata["leverage"], 2)
        self.assertEqual(row.metadata["attack"]["leverage"], 2)
        self.assertIn("capped at 2x by MAX BOT LEVERAGE",
                      row.metadata["attack"]["leverage_why"])


# ── never the ticket, never "manual" ────────────────────────────────────

class TheTicketIsNeverCappedTests(TestCase):
    """The real _ticket_leverage with the real judge_order_leverage on
    EURUSD's measured LIVE list, 2 to 30 (forex ceiling 30), the switch ON
    and the operator's own book saved: at a cap of 2 the ticket's choices
    and its default are exactly what they are without one."""

    def setUp(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.manual_trade import manual_config_for
        self.user = get_user_model().objects.create_user("botlev_tk",
                                                         password="x")
        _instrument("EURUSD", "forex")
        self.cfg = manual_config_for(self.user, "forex")
        self.bot = make_bot(self.cfg)
        _switch(True)
        _book(self.user)

    def _ticket(self, side="BUY", asked=None):
        from bot_program.manual_trade import _ticket_leverage
        stop = 1.1295 if side == "BUY" else 1.1305
        return _ticket_leverage(self.bot, self.cfg,
                                _wire({"EURUSD": ROW_EURUSD_LIVE}), "EURUSD",
                                side, 1.13, stop, asked=asked)

    def test_the_choices_and_the_highest_stay_at_a_cap_of_two(self):
        _cap(None)
        uncapped = {side: self._ticket(side) for side in ("BUY", "SELL")}
        _cap(2)
        for side in ("BUY", "SELL"):
            out = self._ticket(side)
            self.assertEqual(out["choices"], [1, 2, 5, 10, 20, 30], side)
            self.assertEqual((out["max"], out["chosen"]), (30, 30), side)
            self.assertEqual(out["error"], "", side)
            self.assertEqual(out, uncapped[side], side)
            self.assertEqual(self._ticket(side, asked=30)["chosen"], 30, side)

    def test_the_shared_rule_never_caps(self):
        """judge_order_leverage, which the ticket imports with a proxy
        config, answers a multiplier above the cap as on main."""
        from bot_program.asset_engine.base import judge_order_leverage
        _cap(2)
        proxy = SimpleNamespace(extras={"leverage": 30}, user=self.user)
        self.assertEqual(judge_order_leverage(proxy, "forex", "etoro"),
                         (30, ""))

    def test_a_config_named_manual_is_never_capped_in_the_engine(self):
        _cap(2)
        wire = _wire({"EURUSD": ROW_EURUSD_LIVE})
        self.cfg.extras = {"leverage": 10}
        self.assertEqual(self.bot._order_leverage(
            wire, "EURUSD", side="BUY", price=1.0, stop=0.9825), (10, ""))
        self.assertIsNone((getattr(self.bot, "_bot_cap_note", None)
                           or {}).get("EURUSD"))
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 10)
        self.cfg.extras = {"leverage": "auto"}
        with mock.patch(PROVEN_LEV, {}):
            lev, why = self.bot._choose_auto_leverage(wire, "EURUSD", "BUY",
                                                      1.0, 0.9825)
        self.assertEqual(lev, 20)
        self.assertNotIn("MAX BOT LEVERAGE", why)
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 30)


class TheTakeTradeLaneTests(TestCase):
    """The TAKE TRADE lane end to end (tests/test_manual_ticket_leverage.py's
    harness: the real _ticket_leverage, eToro's LIVE list 1 to 30 on the
    fake, its gates stated with a 30x ceiling): at a cap of 2, a ticket sent
    with no pick goes at the highest, a BUY and a SELL alike."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("botlev_lane",
                                                        password="x")

    def test_a_ticket_with_no_pick_is_sent_at_the_highest(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        from tests.test_manual_ticket_leverage import (INSTRUMENT,
                                                       _real_ticket)
        from tests.test_take_trade_live import ROUTER as TT_ROUTER
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _fake_live_client,
                                                _filled_response, _quote)
        from tests.test_take_trade_live import _signal as _tt_signal
        inst = _quote("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        _cap(2)
        bear = {"direction": "bearish", "entry": 60000, "stop": 60900,
                "target": 58200}
        for side, kw in (("BUY", {}), ("SELL", bear)):
            cache.clear()
            fake = _fake_live_client(_filled_response(side=side))
            fake.settlement_for.return_value = "cfd"
            fake.leverage_values.return_value = [1, 2, 5, 10, 20, 30]
            with mock.patch(TT_ROUTER, return_value=fake), \
                    _real_ticket(ceiling=30), \
                    mock.patch(INSTRUMENT, return_value=""):
                out = execute_take_trade(self.user, _tt_signal(inst, **kw),
                                         pin_ok=True)
            self.assertNotIn("error", out, out)
            self.assertEqual(fake.market_order.call_args.args[:2],
                             ("BTCUSD", side))
            self.assertEqual(fake.market_order.call_args.kwargs["leverage"],
                             30, side)
            row = AssetBotTrade.objects.get(pk=out["trade_id"])
            self.assertEqual(row.metadata["leverage"], 30, side)
            self.assertNotIn("max_bot_leverage", row.metadata)
            row.delete()


# ── where the operator reads it ─────────────────────────────────────────

class ThePreflightTests(TestCase):
    """Section 4: beside each live config's leverage line, the cap."""

    def _venue(self, u, *, asset_class):
        from bot_program.models import EtoroAccount
        acct = EtoroAccount.objects.create(
            user=u, demo=False, label="Main",
            is_primary_for_stocks=(asset_class == "stock"),
            is_primary_for_forex=(asset_class == "forex"))
        acct.set_credentials("k", "u")
        acct.last_equity = Decimal("100000")
        acct.last_equity_currency = "USD"
        acct.last_equity_at = timezone.now()
        acct.last_available_cash = Decimal("100000")
        acct.last_used_margin = Decimal("0")
        acct.last_margin_at = timezone.now()
        acct.save()
        return acct

    def _armed(self, *, extras, asset_class="stock", symbol="AAPL",
               name="starter", symbols=None):
        from instruments.models import Instrument
        from tests.test_preflight_live import _bars, _cfg, _pin
        from tests.test_preflight_live import _user as _pf_user
        u = _pf_user()
        self._venue(u, asset_class=asset_class)
        _book(u)
        _pin(u)
        symbols = (symbol,) if symbols is None else tuple(symbols)
        cfg = _cfg(u, capital="5000", base_currency="USD",
                   asset_class=asset_class, symbols=symbols, name=name)
        cfg.extras = extras
        cfg.save(update_fields=["extras"])
        for sym in symbols:
            Instrument.objects.get_or_create(symbol=sym, defaults={
                "name": sym, "asset_class": asset_class})
            _bars(sym, age_hours=1.0)
        _switch(True)
        return cfg

    def test_a_typed_config_says_what_it_is_sent_at(self):
        from tests.test_preflight_live import _blockers, _run, _worth
        cfg = self._armed(extras={"leverage": 10}, asset_class="forex",
                          symbol="EURUSD")
        _cap(2)
        out = _run()
        self.assertIn("leverage 10x (extras), sent at 2x (capped at 2x by MAX "
                      "BOT LEVERAGE) — rides the eToro order body", out)
        self.assertIn("cash pledged per position is notional/2 ", out)
        self.assertIn("MAX BOT LEVERAGE 2x (/setup/) — this bot's multiplier "
                      "at eToro is at most 2x", out)
        self.assertIn(f"config {cfg.id} ({cfg.name}) at 2x: financing",
                      _worth(out))
        self.assertNotIn("MAX BOT LEVERAGE", _blockers(out))

    def test_a_cap_between_steps_says_the_step_it_is_sent_at(self):
        """The review of 2026-11-05: the engine sends a typed bot capped
        between two of eToro's steps at the step under the cap, and the
        line says that one, with the cash it pledges — never "sent at 3x",
        which eToro does not take. Nothing refuses it, so nothing blocks."""
        from tests.test_preflight_live import _blockers, _run, _worth
        cfg = self._armed(extras={"leverage": 10}, asset_class="forex",
                          symbol="EURUSD")
        _cap(3)
        out = _run()
        self.assertIn("leverage 10x (extras), sent at 2x, eToro's highest "
                      "step at or under 3x (capped at 3x by MAX BOT "
                      "LEVERAGE) — rides the eToro order body", out)
        self.assertIn("cash pledged per position is notional/2 ", out)
        self.assertNotIn("sent at 3x", out)
        self.assertIn(f"config {cfg.id} ({cfg.name}) at 2x: financing",
                      _worth(out))
        self.assertNotIn("MAX BOT LEVERAGE", _blockers(out))

    def test_a_stock_capped_between_its_steps_says_two(self):
        from tests.test_preflight_live import _run
        self._armed(extras={"leverage": 5})
        _cap(4)
        out = _run()
        self.assertIn("leverage 5x (extras), sent at 2x, eToro's highest step "
                      "at or under 4x (capped at 4x by MAX BOT LEVERAGE)", out)
        self.assertIn("cash pledged per position is notional/2 ", out)

    def test_blank_says_no_cap_and_the_typed_line_is_unchanged(self):
        from tests.test_preflight_live import _run
        self._armed(extras={"leverage": 10}, asset_class="forex",
                    symbol="EURUSD")
        _cap(None)
        out = _run()
        self.assertIn("leverage 10x (extras) — rides the eToro order body",
                      out)
        self.assertIn("cash pledged per position is notional/10 ", out)
        self.assertIn("MAX BOT LEVERAGE —  (blank on /setup/: no cap on the "
                      "bots' multiplier)", out)

    def test_a_cap_of_one_reads_as_the_unlevered_order(self):
        from tests.test_preflight_live import _run, _worth
        self._armed(extras={"leverage": 10}, asset_class="forex",
                    symbol="EURUSD")
        _cap(1)
        out = _run()
        self.assertIn("leverage 10x (extras), sent at 1x (capped at 1x by MAX "
                      "BOT LEVERAGE) — the adapter's default, recorded on the "
                      "row", out)
        self.assertNotIn("financing", _worth(out))

    def test_the_attack_mode_line_names_the_cap(self):
        from tests.test_preflight_live import _run
        self._armed(extras={"leverage": "auto"})
        _cap(2)
        out = _run()
        self.assertIn("stock: ceiling 5x (the venue's class maximum), "
                      "measured at 1x — the chooser picks at most 2x (capped "
                      "at 2x by MAX BOT LEVERAGE), on eToro's LIVE list and "
                      "inside the stop band", out)
        self.assertIn("MAX BOT LEVERAGE 2x (/setup/)", out)

    def test_the_manual_config_says_the_ticket_is_never_capped(self):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        from tests.test_preflight_live import _run
        self._armed(extras={}, name=MANUAL_CONFIG_NAME, symbols=())
        _cap(2)
        out = _run()
        self.assertIn("MAX BOT LEVERAGE does not apply — the hand-taken TAKE "
                      "TRADE ticket is never capped", out)
        self.assertNotIn("MAX BOT LEVERAGE 2x", out)


class TheOpsWordsTests(SimpleTestCase):

    def test_the_switch_tells_the_truth_and_names_the_cap(self):
        """The /ops/ words said "up to 20x" and "'auto' is held to its
        proven multiplier": forex's ceiling is 30 and no proven bound holds
        the chooser since 2026-10-05."""
        from bot_program.asset_engine.base import ORDER_LEVERAGE_CEILING
        from core.platform_control import DEFAULT_COMPONENTS
        text = next(c for c in DEFAULT_COMPONENTS
                    if c["key"] == "etoro_leverage_live")["description"]
        self.assertLessEqual(len(text), 300)
        self.assertNotIn("proven multiplier", text)
        self.assertNotIn("up to 20x", text)
        for cls in ("forex", "index", "commodity", "stock", "crypto"):
            self.assertIn(f"{cls} {ORDER_LEVERAGE_CEILING[cls]}x", text)
        self.assertIn("MAX BOT LEVERAGE", text)
        self.assertIn("TAKE TRADE ticket", text)
        self.assertIn("REFUSED", text)
