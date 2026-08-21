"""The regime probe has to measure the book, not the alphabet.

The operator's briefing said it three days running: 36% of the book sat in
XAUUSD, "an asset no regime probe covers", "you are max-long an asset you
are not measuring".

The cause was the candidate ordering. `-is_watchlist, symbol` was already
an improvement on an arbitrary slice, but with nothing starred — the
shipped state — it degenerates to ALPHABETICAL, so out of 177 instruments
the probe read AAPL, AAVEUSD, ABBV, ADAUSD, AGG, ALUMUSD, AMD, AMZN and
reported on none of the eight positions actually being carried.

A regime read that skips the positions is answering a question nobody
asked, and the brain then spent a week reporting "regime unknown" for the
one asset that mattered.

Run with:  python manage.py test tests.test_regime_probe_covers_the_book
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase


def _instrument(symbol, asset_class="commodity", watch=False):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class,
                  "is_active": True})
    if inst.is_watchlist != watch:
        inst.is_watchlist = watch
        inst.save(update_fields=["is_watchlist"])
    return inst


def _candidates():
    """The selection the probe makes, reproduced from the shipped rule."""
    from instruments.models import Instrument
    from brain.synthesizer import _held_symbols
    held = _held_symbols()
    ordered = sorted(
        Instrument.objects.filter(is_active=True),
        key=lambda i: (0 if i.symbol in held else 1,
                       0 if i.is_watchlist else 1,
                       i.symbol))
    return [i.symbol for i in ordered[:max(8, min(len(held), 16))]]


class HeldSymbolsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("rp_u", password="x")

    def _bot_trade(self, symbol, status="OPEN"):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.user, asset_class="commodity", name="rp",
            defaults={"capital": Decimal("10000")})
        _instrument(symbol)
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="commodity", symbol=symbol, side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status=status,
            paper=True)

    def test_it_sees_an_open_bot_trade(self):
        from brain.synthesizer import _held_symbols
        self._bot_trade("XAUUSD")
        self.assertIn("XAUUSD", _held_symbols())

    def test_a_close_pending_row_is_still_held(self):
        """The broker still has it; the regime still matters."""
        from brain.synthesizer import _held_symbols
        self._bot_trade("XAUUSD", status="CLOSE_PENDING")
        self.assertIn("XAUUSD", _held_symbols())

    def test_a_closed_row_is_not(self):
        from brain.synthesizer import _held_symbols
        self._bot_trade("XAUUSD", status="CLOSED")
        self.assertNotIn("XAUUSD", _held_symbols())

    def test_it_sees_the_legacy_book_too(self):
        """Both books, or the probe misses whatever the other one holds."""
        from django.utils import timezone
        from brain.synthesizer import _held_symbols
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        Position.objects.create(
            portfolio=get_or_create_default_portfolio(user=self.user),
            instrument=_instrument("SILVER"), direction="long",
            quantity=Decimal("1"), entry_price=Decimal("30"),
            current_price=Decimal("30"), opened_at=timezone.now())
        self.assertIn("SILVER", _held_symbols())

    def test_an_empty_book_is_an_empty_set_not_a_crash(self):
        from brain.synthesizer import _held_symbols
        self.assertEqual(_held_symbols(), set())


class TheProbeCoversWhatIsHeldTests(TestCase):
    """The regression, reproduced with the alphabet stacked against it."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("rp_c", password="x")
        # Instruments that sort BEFORE the held one, exactly like the real
        # catalogue does: AAPL and friends beat XAUUSD every time.
        for sym in ("AAPL", "AAVEUSD", "ABBV", "ADAUSD",
                    "AGG", "ALUMUSD", "AMD", "AMZN", "ARKK"):
            _instrument(sym, asset_class="stock")

    def _hold(self, symbol):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.user, asset_class="commodity", name="rp",
            defaults={"capital": Decimal("10000")})
        _instrument(symbol)
        AssetBotTrade.objects.create(
            config=cfg, asset_class="commodity", symbol=symbol, side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
            paper=True)

    def test_a_held_symbol_at_the_end_of_the_alphabet_is_still_probed(self):
        """XAUUSD, the exact case from the briefing."""
        self._hold("XAUUSD")
        self.assertIn("XAUUSD", _candidates())

    def test_it_comes_first_rather_than_merely_being_included(self):
        """Included-but-truncated is the same bug one instrument later."""
        self._hold("XAUUSD")
        self.assertEqual(_candidates()[0], "XAUUSD")

    def test_every_held_symbol_is_covered_even_when_there_are_many(self):
        for sym in ("XAUUSD", "EURGBP", "HGUSD", "USDCHF", "EURJPY"):
            self._hold(sym)
        picked = set(_candidates())
        from brain.synthesizer import _held_symbols
        self.assertTrue(_held_symbols().issubset(picked))

    def test_the_watchlist_still_outranks_the_alphabet(self):
        """The previous rule was right about watchlist-over-alphabet; this
        only inserts the book above it."""
        _instrument("ZZZWATCH", asset_class="stock", watch=True)
        self.assertIn("ZZZWATCH", _candidates())

    def test_held_outranks_watchlisted(self):
        _instrument("AAAWATCH", asset_class="stock", watch=True)
        self._hold("XAUUSD")
        picked = _candidates()
        self.assertLess(picked.index("XAUUSD"), picked.index("AAAWATCH"))

    def test_an_empty_book_still_probes_eight(self):
        """Nothing held is not a reason to probe nothing."""
        self.assertEqual(len(_candidates()), 8)
