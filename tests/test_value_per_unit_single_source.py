"""One derivation of "money per price point per unit", not two.

The positions hover card grew a money block that needed the same
denomination the row is marked in, and it was written as a second copy of
the derivation with a comment promising to stay identical. It stopped being
identical the same day: a correction taught the options test to match the
platform's plural spelling in one copy and not the other, which would have
denominated a multiplier-less options row 100x apart in two numbers printed
on the same card — a percentage that does not divide its own currency
figures.

Run with:  python manage.py test tests.test_value_per_unit_single_source
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from portfolio.services import is_option_row, value_per_unit


def _trade(**kw):
    """Unsaved — every function under test reads fields, never the DB."""
    from bot_program.models import AssetBotTrade
    return AssetBotTrade(
        asset_class=kw.pop("asset_class", "stock"),
        symbol=kw.pop("symbol", "AAPL"), side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        metadata=kw.pop("metadata", {}), **kw)


class OptionRowDetectionTests(TestCase):
    def test_the_platform_spelling_is_recognised(self):
        """"options", plural — the token every other branch in the codebase
        uses. The singular was the only spelling here and matched nothing."""
        self.assertTrue(is_option_row(_trade(asset_class="options")))

    def test_the_legacy_singular_still_matches(self):
        """Kept so a row written under the old spelling is not repriced
        against the underlying the day this changed."""
        self.assertTrue(is_option_row(_trade(asset_class="option")))

    def test_the_multiplier_key_alone_is_enough(self):
        self.assertTrue(is_option_row(
            _trade(asset_class="stock", metadata={"multiplier": 100})))

    def test_an_ordinary_equity_is_not_an_option(self):
        self.assertFalse(is_option_row(_trade()))

    def test_none_is_not_an_option(self):
        """A legacy portfolio.Position row has no trade behind it."""
        self.assertFalse(is_option_row(None))


class ValuePerUnitTests(TestCase):
    def test_a_plain_equity_is_one(self):
        self.assertEqual(value_per_unit(_trade()), 1.0)

    def test_an_options_row_without_metadata_still_gets_the_multiplier(self):
        """The case the drift would have broken: no multiplier key, so only
        the asset_class test can catch it."""
        self.assertEqual(value_per_unit(_trade(asset_class="options")), 100.0)

    def test_the_recorded_multiplier_wins_over_the_default(self):
        self.assertEqual(
            value_per_unit(_trade(asset_class="options",
                                  metadata={"multiplier": 50})), 50.0)

    def test_forex_carries_its_recorded_rate(self):
        self.assertAlmostEqual(
            value_per_unit(_trade(asset_class="forex",
                                  metadata={"value_per_unit": 0.0067})),
            0.0067)

    def test_an_unparseable_value_does_not_raise(self):
        """extras and metadata are hand-editable. A typo costs one row's
        precision, never the positions page."""
        self.assertEqual(value_per_unit(
            _trade(metadata={"value_per_unit": "not a number"})), 1.0)

    def test_an_unparseable_multiplier_falls_back_to_a_hundred(self):
        self.assertEqual(value_per_unit(
            _trade(asset_class="options", metadata={"multiplier": "x"})),
            100.0)


class OneSourceTests(TestCase):
    """The view helper must CALL the services one, not reproduce it."""

    def test_the_card_and_the_row_agree_on_an_options_row(self):
        from dashboard.views import _pos_value_per_unit
        trade = _trade(asset_class="options")
        self.assertEqual(_pos_value_per_unit(trade), value_per_unit(trade))

    def test_they_agree_on_every_shape(self):
        from dashboard.views import _pos_value_per_unit
        for trade in (_trade(),
                      _trade(asset_class="options"),
                      _trade(asset_class="options", metadata={"multiplier": 10}),
                      _trade(asset_class="forex",
                             metadata={"value_per_unit": 0.0067}),
                      None):
            self.assertEqual(_pos_value_per_unit(trade), value_per_unit(trade))

    def test_the_view_no_longer_carries_its_own_options_test(self):
        """A second spelling of the same rule is what drifted."""
        import inspect

        from dashboard import views
        source = inspect.getsource(views._pos_value_per_unit)
        self.assertNotIn('"option"', source)
        self.assertIn("value_per_unit", source)
