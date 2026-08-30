"""The command that answers "why is Sauron not trading" in one pass.

The question has about nine possible answers spread across four apps, and
several of them are SILENT: a component with no row no-ops forever and
leaves `last_run_at` NULL — indistinguishable from never wired — and an
enabled config with an empty symbol list opens nothing while
`check_live_mode_readiness` still reports it green.

These tests pin the two things that make the command worth running: it
never writes anything, and it NAMES the blocker rather than printing
facts and leaving the operator to spot which one matters.

Run with:  python manage.py test tests.test_why_no_trade
"""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase


def _run(**kw):
    out = StringIO()
    call_command("why_no_trade", stdout=out, **kw)
    return out.getvalue()


def _config(name="C", enabled=True, symbols=("AAPL",), asset_class="stock"):
    from bot_program.models import AssetBotConfig
    u = User.objects.create_user(f"wnt_{name}", password="x")
    return AssetBotConfig.objects.create(
        user=u, asset_class=asset_class, name=name, mode="paper",
        symbols=list(symbols), capital=Decimal("10000"), enabled=enabled)


class ItNamesTheBlockerTests(TestCase):

    def test_a_missing_component_row_is_called_out(self):
        """The silent one: no row means the gated task no-ops forever and
        `last_run_at` stays NULL, which looks identical to never wired."""
        out = _run()
        self.assertIn("NO ROW", out)
        self.assertIn("seed_components", out)

    def test_an_enabled_config_with_no_symbols_is_called_out(self):
        """It opens nothing and the health page reports it green."""
        _config(name="EMPTY", symbols=())
        out = _run()
        self.assertIn("ENABLED WITH NO SYMBOLS", out)
        self.assertIn("empty symbol list", out)

    def test_a_config_with_symbols_is_not_flagged_for_it(self):
        _config(name="FULL", symbols=("AAPL",))
        out = _run()
        self.assertNotIn("ENABLED WITH NO SYMBOLS", out)

    def test_a_disabled_config_is_not_flagged_for_empty_symbols(self):
        """Disabled is a decision, not a fault — it is not a blocker."""
        _config(name="OFF", enabled=False, symbols=())
        out = _run()
        self.assertNotIn("ENABLED WITH NO SYMBOLS", out)

    def test_the_verdict_is_an_ordered_list_not_a_wall_of_facts(self):
        out = _run()
        self.assertIn("BLOCKERS", out)
        self.assertIn("1.", out)

    def test_the_recorded_skips_are_surfaced(self):
        """`skips.record` writes the refusal into cfg.extras and nothing
        ever read it back. That is the answer in most real cases: the
        bots ARE running and refusing, and a skip code is a decision."""
        c = _config(name="SKIPPED")
        c.extras = {"skip_counts": {"cost_filter": 7},
                    "skips": {"AAPL": {"code": "cost_filter",
                                       "detail": "planned move too small",
                                       "at": "2026-08-31T00:00:00Z"}}}
        c.save(update_fields=["extras"])
        out = _run()
        self.assertIn("cost_filter", out)
        self.assertIn("planned move too small", out)

    def test_a_config_that_was_never_reached_says_so(self):
        """No recorded skip is itself evidence — it means the tick never
        got to this config, which is a different problem from refusing."""
        _config(name="UNREACHED")
        out = _run()
        self.assertIn("never have reached", out)


class ItWritesNothingTests(TestCase):
    """It is a diagnostic. It runs on a live trading box, often while the
    operator is worried, and it must not be one of the things that can
    change the situation it is describing."""

    def test_it_places_no_order_and_changes_no_row(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        c = _config(name="RO")
        before = (AssetBotConfig.objects.get(pk=c.pk).extras,
                  AssetBotTrade.objects.count())
        _run()
        after = (AssetBotConfig.objects.get(pk=c.pk).extras,
                 AssetBotTrade.objects.count())
        self.assertEqual(before, after)

    def test_it_survives_an_empty_platform(self):
        """No configs, no components, no bars — the worst case is also
        the most likely time to reach for it."""
        out = _run()
        self.assertIn("WHY IS SAURON NOT TRADING", out)
        self.assertIn("NONE", out)


class TheManualConfigIsNotABlockerTests(TestCase):
    """TAKE TRADE's per-class config is enabled with an EMPTY symbol list
    ON PURPOSE — `manual_config_for` creates it that way so it manages
    hand-taken positions and never scans for its own.

    Production carries four of them (one per asset class). Flagging them
    would send the operator to "fix" the only configs that are already
    correct, and `_config_error` treats symbols ON that config as the
    fault. A diagnostic that cries wolf four times costs more than it
    saves.
    """

    def _manual(self, asset_class="forex"):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        return _config(name=MANUAL_CONFIG_NAME, symbols=(),
                       asset_class=asset_class)

    def test_it_is_not_flagged_for_having_no_symbols(self):
        self._manual()
        out = _run()
        self.assertNotIn("ENABLED WITH NO SYMBOLS", out)
        self.assertNotIn("empty symbol list", out)

    def test_it_is_labelled_so_the_reading_is_obvious(self):
        self._manual()
        self.assertIn("manages, never scans", _run())

    def test_its_lack_of_skips_is_not_reported_as_a_missed_tick(self):
        """It scans nothing, so it records nothing — that is the design,
        not evidence the tick never reached it."""
        self._manual()
        out = _run()
        self.assertIn("nothing to record", out)
        self.assertNotIn("never have reached", out)

    def test_a_REAL_config_with_no_symbols_is_still_flagged(self):
        """The guard must not swallow the case it was written for."""
        _config(name="starter_fx", symbols=())
        out = _run()
        self.assertIn("ENABLED WITH NO SYMBOLS", out)
