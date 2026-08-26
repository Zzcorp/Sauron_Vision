"""Two gates that were not there.

SHADOW MODE. `OptionsBot.scan_symbol` overrides `AssetBot.scan_symbol`
wholesale and never re-implemented the shadow gate — the word "shadow"
did not appear anywhere in that file. So a live options config that the
console and the headband both labelled "Shadow mode: decides, submits
nothing" went on buying real premium at IBKR and writing paper=False
rows. Shadow mode is turned on precisely to be certain that cannot
happen, and options and CFDs route to IBKR unconditionally.

STALE BARS. `_latest_price` bounded its LiveQuote branch at
MAX_QUOTE_AGE_SECONDS and left the PriceData fallback directly beneath
it with no cutoff at all — while the sibling implementation in
performance.py bounds the identical fallback. A symbol whose ingestion
had stopped therefore returned the same fossil close on every pass, and
every ACTIVE card whose stop sat on the wrong side of it was stamped
INVALIDATED at -1.0R. Those are losses that never happened, and they
reach `get_hit_rate` as measurement and from there the composite that
sizes live entries.

Run with:  python manage.py test tests.test_shadow_and_stale_bars
"""
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


class TheOptionsLaneHonoursShadowModeTests(SimpleTestCase):
    def _src(self):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
                / "options_bot.py").read_text(encoding="utf-8")

    def test_the_options_lane_has_a_shadow_gate_at_all(self):
        src = self._src()
        self.assertIn("is_shadow(self.cfg)", src)
        self.assertIn("log_shadow_entry", src)

    def test_the_gate_stands_before_anything_is_submitted(self):
        """A gate after the order is not a gate. It must sit ahead of the
        paper/venue decision, the way base.scan_symbol places it."""
        src = self._src()
        gate = src.index("is_shadow(self.cfg)")
        for after in ("market_order_option", "submit_option", "paper ="):
            idx = src.find(after, gate)
            if idx != -1:
                self.assertGreater(idx, gate,
                                   f"{after} runs before the shadow gate")

    def test_it_refuses_with_the_same_skip_code_as_the_base_lane(self):
        """One vocabulary: the console counts SHADOW skips across lanes."""
        src = self._src()
        self.assertIn("skips.SHADOW", src)

    def test_the_base_lane_still_has_its_own(self):
        from pathlib import Path

        from django.conf import settings
        base = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
                / "base.py").read_text(encoding="utf-8")
        self.assertIn("is_shadow(self.cfg)", base)


class ABarTooOldIsNotAPriceTests(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        self.inst = Instrument.objects.create(
            symbol="STALEUSD", name="Stale", asset_class="crypto",
            is_active=True)

    def _bar(self, hours_ago, close="100"):
        from market_data.models import PriceData
        return PriceData.objects.create(
            instrument=self.inst, timeframe="1h",
            timestamp=timezone.now() - timedelta(hours=hours_ago),
            open=Decimal(close), high=Decimal(close), low=Decimal(close),
            close=Decimal(close), volume=Decimal("1"))

    def test_a_fossil_bar_is_refused(self):
        """The 1h bound is six hours; a bar from three days ago is not a
        price, it is the last thing anybody saw."""
        from signals.lifecycle import _latest_price
        self._bar(hours_ago=72)
        self.assertIsNone(_latest_price("STALEUSD", "1h"))

    def test_a_fresh_bar_is_still_a_price(self):
        from signals.lifecycle import _latest_price
        self._bar(hours_ago=1, close="123")
        self.assertEqual(float(_latest_price("STALEUSD", "1h")), 123.0)

    def test_the_bound_scales_with_the_timeframe(self):
        """A 1d card's newest bar is legitimately a day old — and four
        days old over a long weekend. A 5m card's is stale within the
        hour. One flat cutoff cannot serve both."""
        from signals.lifecycle import (
            MAX_BAR_AGE_SECONDS_BY_TIMEFRAME as BOUNDS,
        )
        self.assertLess(BOUNDS["5m"], BOUNDS["1h"])
        self.assertLess(BOUNDS["1h"], BOUNDS["4h"])
        self.assertLess(BOUNDS["4h"], BOUNDS["1d"])
        self.assertGreaterEqual(BOUNDS["1d"], 3 * 86400,
                                "a long weekend must not invalidate a "
                                "daily card")

    def test_a_daily_bar_that_would_fail_the_hourly_bound_still_passes(self):
        from signals.lifecycle import _latest_price
        from market_data.models import PriceData
        PriceData.objects.create(
            instrument=self.inst, timeframe="1d",
            timestamp=timezone.now() - timedelta(hours=30),
            open=Decimal("50"), high=Decimal("50"), low=Decimal("50"),
            close=Decimal("50"), volume=Decimal("1"))
        self.assertIsNone(_latest_price("STALEUSD", "1h"))
        self.assertIsNotNone(_latest_price("STALEUSD", "1d"))

    def test_an_unknown_timeframe_gets_a_default_bound(self):
        from signals.lifecycle import _latest_price
        self._bar(hours_ago=72)
        self.assertIsNone(_latest_price("STALEUSD", None))
        self.assertIsNone(_latest_price("STALEUSD", "nonsense"))


class TheExposurePanelQueriesFieldsThatExistTests(TestCase):
    """`analyze_exposure` filtered Position on is_open / market_value /
    side — none of which the model has — so a FieldError went into a
    bare except and the concentration chart rendered empty forever, with
    no error anywhere."""

    def test_position_has_the_fields_the_analyzer_uses(self):
        from portfolio.models import Position
        names = {f.name for f in Position._meta.get_fields()}
        for real in ("closed_at", "direction", "quantity", "entry_price",
                     "current_price"):
            self.assertIn(real, names)
        for absent in ("is_open", "market_value", "side"):
            self.assertNotIn(absent, names)

    def test_a_real_open_position_actually_reaches_the_panel(self):
        """The behaviour, not the source text: main returned {} here."""
        from django.contrib.auth.models import User

        from instruments.models import Instrument
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        from strategies.portfolio_analyzer import analyze_exposure

        user = User.objects.create_user("expo_u", password="x")
        pf = get_or_create_default_portfolio(user=user)
        inst = Instrument.objects.create(symbol="AAPL", name="Apple",
                                         asset_class="stock", is_active=True)
        Position.objects.create(
            portfolio=pf, instrument=inst, direction="long",
            quantity=Decimal("10"), entry_price=Decimal("100"),
            current_price=Decimal("110"), opened_at=timezone.now())

        out = analyze_exposure(pf)
        self.assertTrue(out, "the panel is empty on a book with a position")
        self.assertAlmostEqual(out["total"], 1100.0, places=2)
        self.assertIn("stock", out["by_asset_class"])

    def test_a_closed_position_is_excluded(self):
        from django.contrib.auth.models import User
        from django.utils import timezone as tz

        from instruments.models import Instrument
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        from strategies.portfolio_analyzer import analyze_exposure

        user = User.objects.create_user("expo_c", password="x")
        pf = get_or_create_default_portfolio(user=user)
        inst = Instrument.objects.create(symbol="MSFT", name="Microsoft",
                                         asset_class="stock", is_active=True)
        Position.objects.create(
            portfolio=pf, instrument=inst, direction="long",
            quantity=Decimal("10"), entry_price=Decimal("100"),
            current_price=Decimal("110"), opened_at=timezone.now(),
            closed_at=tz.now())
        self.assertEqual(analyze_exposure(pf).get("total"), 0)
