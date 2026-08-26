"""Funding alerts that could never reach the instrument they were about.

FundingRate.symbol and LiquidationEvent.symbol always hold Binance FUTURES
spelling — stream_binance_futures writes o["s"]/d["s"] verbatim, so BTCUSDT
— and the Instrument catalogue only ever holds BTCUSD. The scan resolved
the perp with a direct `symbol__iexact` match, which therefore found nothing
for any symbol on any pass.

Two things followed, neither of which looked like a failure. Every alert
degraded to the market-wide /liquidations/ feed instead of the asset's own
page, which is where its funding, mark and chart already are. And the
funding/price divergence block — the "shorts bleeding" / "longs bleeding"
squeeze notifications — sat behind `if not inst: continue`, so it had never
fired and never would. The scan still returned a healthy non-zero alert
count from the sign-flip and extreme branches.

Run with:  python manage.py test tests.test_funding_alerts
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _subscriber(name="funding_u"):
    from portfolio.trader_profile import TraderProfile
    user = User.objects.create_user(username=name, password="x")
    TraderProfile.objects.create(user=user, notify_signals=True)
    return user


def _perp(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    return Instrument.objects.create(
        symbol=symbol, name=symbol, asset_class=asset_class)


def _funding(symbol, rate, *, minutes_ago=0, mark="60000"):
    from market_data.models import FundingRate
    return FundingRate.objects.create(
        symbol=symbol, mark_price=Decimal(mark), index_price=Decimal(mark),
        funding_rate=Decimal(str(rate)),
        timestamp=timezone.now() - timedelta(minutes=minutes_ago))


def _quote(inst, change_pct, last="60000"):
    from market_data.models import LiveQuote
    return LiveQuote.objects.create(
        instrument=inst, last=Decimal(last),
        change_pct=Decimal(str(change_pct)), source="binance_ws")


class DivergenceTests(TestCase):
    def setUp(self):
        self.user = _subscriber()
        self.inst = _perp()

    def _notifications(self):
        from alerts.models import Notification
        return list(Notification.objects.filter(user=self.user))

    def test_a_short_squeeze_setup_on_a_perp_actually_notifies(self):
        """Price up, funding negative — the whole reason this block exists.
        The perp arrives as BTCUSDT and the catalogue says BTCUSD."""
        from market_data.funding_alerts import scan_funding_signals

        _funding("BTCUSDT", -0.0002, minutes_ago=10)
        _funding("BTCUSDT", -0.0003)
        _quote(self.inst, change_pct=2.4)

        scan_funding_signals()

        titles = [n.title for n in self._notifications()]
        self.assertTrue(any("shorts bleeding" in t for t in titles), titles)

    def test_a_long_squeeze_setup_notifies_the_other_way(self):
        from market_data.funding_alerts import scan_funding_signals

        _funding("BTCUSDT", 0.0002, minutes_ago=10)
        _funding("BTCUSDT", 0.0003)
        _quote(self.inst, change_pct=-2.4)

        scan_funding_signals()

        titles = [n.title for n in self._notifications()]
        self.assertTrue(any("longs bleeding" in t for t in titles), titles)

    def test_one_perp_raises_one_alert_however_many_snapshots_it_wrote(self):
        """FundingRate.Meta orders by -timestamp, and Django adds ordering
        columns to a DISTINCT select — so the symbol sweep used to return one
        entry per SNAPSHOT and sent the same squeeze notification once per
        30-second mark write in the window."""
        from market_data.funding_alerts import scan_funding_signals

        for minutes in range(0, 16, 2):
            _funding("BTCUSDT", -0.0003 - minutes / 100000, minutes_ago=minutes)
        _quote(self.inst, change_pct=2.4)

        scan_funding_signals()

        titles = [n.title for n in self._notifications()]
        self.assertEqual(len([t for t in titles if "shorts bleeding" in t]), 1,
                         titles)

    def test_a_flat_tape_raises_no_divergence(self):
        from market_data.funding_alerts import scan_funding_signals

        _funding("BTCUSDT", -0.0002, minutes_ago=10)
        _funding("BTCUSDT", -0.0003)
        _quote(self.inst, change_pct=0.2)

        scan_funding_signals()

        titles = [n.title for n in self._notifications()]
        self.assertFalse(any("divergence" in t for t in titles), titles)


class AlertLinkTests(TestCase):
    def setUp(self):
        self.user = _subscriber("link_u")

    def _urls(self):
        from alerts.models import Notification
        return {n.url for n in Notification.objects.filter(user=self.user)}

    def test_an_extreme_funding_alert_links_to_the_asset_page(self):
        from market_data.funding_alerts import scan_funding_signals

        inst = _perp("ETHUSD")
        _funding("ETHUSDT", 0.0015, minutes_ago=10)
        _funding("ETHUSDT", 0.0020)

        scan_funding_signals()

        self.assertEqual(self._urls(), {f"/instruments/{inst.symbol}/"})

    def test_a_perp_we_do_not_track_still_lands_on_the_feed(self):
        """The fallback is deliberate: an alert about a symbol with no page
        goes to the market-wide feed rather than to a plausible 404."""
        from market_data.funding_alerts import scan_funding_signals

        _funding("PEPEUSDT", 0.0015, minutes_ago=10)
        _funding("PEPEUSDT", 0.0020)

        scan_funding_signals()

        self.assertEqual(self._urls(), {"/liquidations/"})
