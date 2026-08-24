"""The money question, answered once — pools, used, free, cash, and the
second percentage.

Two asks drove this wave, both the same complaint from different angles:
"the % of gain or loss is the global (leveraged) one" and "add the amount
of capital invested, used, the amount of cash". The pages quoted P&L
against NOTIONAL — true, and silent about the operator's cash: a forex
leg that moved +1% of notional moved +30% of the margin committed to it.
And no surface anywhere summed what the pools hold, what open tickets
commit, and what is still free.

One service (portfolio.services.capital_summary) and one helper
(pnl_on_capital_pct) answer both, and every surface — /portfolio/,
/positions/, the headband popups — reads them, so no two surfaces can
disagree about money.

Run with:  python manage.py test tests.test_capital_truth
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase


def _user(name="cap_u"):
    return get_user_model().objects.create_user(name, password="x")


def _config(user, asset_class, capital, *, enabled=True, name=None):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class,
        name=name or f"c_{asset_class}", enabled=enabled, mode="paper",
        symbols=[], capital=Decimal(str(capital)))


def _open(cfg, symbol, qty, entry, *, vpu=1.0):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        status="OPEN", metadata={"value_per_unit": vpu})


def _quote(symbol, last, asset_class="crypto"):
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    return inst


class CapitalSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _user()

    def test_pools_used_free_are_margin_aware_per_class(self):
        """A crypto ticket commits its notional; a forex ticket commits
        its MARGIN — the same CAPITAL_USE_FRACTION the pool accounting
        divides by, or the summary would refuse arithmetic the sizing
        engine performs daily."""
        from bot_program.manual_trade import CAPITAL_USE_FRACTION
        from portfolio.services import capital_summary

        crypto = _config(self.user, "crypto", 10000)
        _open(crypto, "BTCUSD", 1, 4000)
        fx = _config(self.user, "forex", 10000, name="fx")
        _open(fx, "EURUSD", 30000, 1.10)

        cap = capital_summary(self.user)
        by_class = {c["asset_class"]: c for c in cap["classes"]}

        self.assertEqual(by_class["crypto"]["pool"], 10000)
        self.assertEqual(by_class["crypto"]["used"], 4000)
        self.assertEqual(by_class["crypto"]["free"], 6000)

        fx_frac = CAPITAL_USE_FRACTION["forex"]
        self.assertAlmostEqual(by_class["forex"]["used"],
                               round(33000 * fx_frac, 2), places=2)
        self.assertEqual(cap["pool_total"], 20000)
        self.assertAlmostEqual(
            cap["free_total"],
            round(20000 - 4000 - 33000 * fx_frac, 2), places=2)

    def test_a_disabled_configs_pool_is_not_capital(self):
        """Disabled means its pool cannot be deployed; counting it would
        advertise free capital nothing can spend."""
        from portfolio.services import capital_summary
        _config(self.user, "crypto", 10000, enabled=False, name="off")
        self.assertEqual(capital_summary(self.user)["pool_total"], 0)

    def test_oversubscription_reads_negative_never_clamped(self):
        from portfolio.services import capital_summary
        cfg = _config(self.user, "crypto", 1000)
        _open(cfg, "BTCUSD", 1, 4000)
        cap = capital_summary(self.user)
        self.assertEqual(cap["free_total"], -3000)

    def test_cash_and_book_come_from_the_users_own_row(self):
        from portfolio.services import (capital_summary,
                                        get_or_create_default_portfolio)
        pf = get_or_create_default_portfolio(user=self.user)
        pf.cash_available = Decimal("1234.56")
        pf.current_value = Decimal("8765.43")
        pf.save()
        cap = capital_summary(self.user)
        self.assertAlmostEqual(cap["cash"], 1234.56, places=2)
        self.assertAlmostEqual(cap["book_value"], 8765.43, places=2)


class SecondPercentageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _user("cap_pct_u")

    def test_a_forex_row_carries_the_on_capital_percentage(self):
        """+1% of notional is +30% of committed margin — both true, both
        rendered, and the second one is the answer to 'how did my money
        do'."""
        from bot_program.manual_trade import CAPITAL_USE_FRACTION
        from portfolio.services import unified_open_positions

        fx = _config(self.user, "forex", 10000, name="fx2")
        _quote("EURUSD", 1.111, "forex")
        _open(fx, "EURUSD", 30000, 1.10)

        rows = [r for r in unified_open_positions(self.user)
                if getattr(r.instrument, "symbol", "") == "EURUSD"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row.unrealized_pnl_pct, 1.0, places=1)
        expected = round(
            row.unrealized_pnl / (33000 * CAPITAL_USE_FRACTION["forex"])
            * 100, 2)
        self.assertAlmostEqual(row.pnl_on_capital_pct, expected, places=1)

    def test_a_cash_funded_row_suppresses_at_the_source(self):
        """Crypto commits full notional, so the second percentage would
        be identical BY CONSTRUCTION — it is None from the service, not
        blanked downstream: a numeric comparison of two independently
        rounded values only ever matched on exact equality, and small
        notionals leaked a duplicate annotation through any epsilon."""
        from portfolio.services import unified_open_positions

        c = _config(self.user, "crypto", 10000, name="c2")
        _quote("BTCUSD", 4200, "crypto")
        _open(c, "BTCUSD", 1, 4000)

        row = [r for r in unified_open_positions(self.user)
               if getattr(r.instrument, "symbol", "") == "BTCUSD"][0]
        self.assertIsNotNone(row.unrealized_pnl_pct)
        self.assertIsNone(row.pnl_on_capital_pct)

    def test_the_legacy_position_row_answers_too(self):
        """Both row kinds flow to the same templates and obey the same
        suppression: a cash-funded stock row answers None (identical by
        construction), a forex-classed row answers the margin figure."""
        from django.utils import timezone

        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        inst = _quote("AAPL", 210, "stock")
        pos = Position.objects.create(
            portfolio=get_or_create_default_portfolio(user=self.user),
            instrument=inst, direction="long", quantity=Decimal("10"),
            entry_price=Decimal("200"), current_price=Decimal("210"),
            unrealized_pnl=Decimal("100"), unrealized_pnl_pct=5.0,
            opened_at=timezone.now())
        self.assertIsNone(pos.pnl_on_capital_pct)

        fx = _quote("EURUSD", 1.11, "forex")
        fx_pos = Position.objects.create(
            portfolio=get_or_create_default_portfolio(user=self.user),
            instrument=fx, direction="long", quantity=Decimal("30000"),
            entry_price=Decimal("1.10"), current_price=Decimal("1.11"),
            unrealized_pnl=Decimal("300"), unrealized_pnl_pct=0.9,
            opened_at=timezone.now())
        self.assertIsNotNone(fx_pos.pnl_on_capital_pct)
        self.assertGreater(fx_pos.pnl_on_capital_pct, 10)

    def test_unmeasured_pnl_stays_unmeasured_on_the_legacy_row(self):
        """The live re-price writes None in memory for an unpriced row;
        `or 0` here once turned that into a confident +0.00% — the exact
        zero the house forbids. None in, None out."""
        from django.utils import timezone

        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        inst = _quote("EURJPY", 160, "forex")
        pos = Position.objects.create(
            portfolio=get_or_create_default_portfolio(user=self.user),
            instrument=inst, direction="long", quantity=Decimal("1000"),
            entry_price=Decimal("160"), current_price=Decimal("160"),
            unrealized_pnl=Decimal("0"), unrealized_pnl_pct=0.0,
            opened_at=timezone.now())
        pos.unrealized_pnl = None  # what _open_book writes when unpriced
        self.assertIsNone(pos.pnl_on_capital_pct)


class SurfacesTests(TestCase):
    def setUp(self):
        self.user = _user("cap_page_u")
        self.client.force_login(self.user)
        cfg = _config(self.user, "crypto", 10000, name="page_c")
        _quote("BTCUSD", 4200, "crypto")
        _open(cfg, "BTCUSD", 1, 4000)

    def test_both_money_pages_render_the_capital_card(self):
        for url in ("/portfolio/", "/positions/"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, "Capital · pools")
            self.assertContains(resp, "POOL")
            self.assertContains(resp, "10,000")

    def test_the_headband_popup_carries_the_pool_cells(self):
        resp = self.client.get("/positions/")
        self.assertContains(resp, "POOL USED")
        self.assertContains(resp, "POOL FREE")

    def test_the_cap_percentage_attaches_to_margined_rows_only(self):
        """Before the forex leg exists the page must be span-free (the
        crypto row suppresses at the source); after, exactly one span —
        the annotation attaches to the margined row, not to the page."""
        resp = self.client.get("/positions/")
        self.assertNotContains(resp, "cap-pct")

        fx = _config(self.user, "forex", 10000, name="page_fx")
        _quote("EURUSD", 1.111, "forex")
        _open(fx, "EURUSD", 30000, 1.10)
        resp = self.client.get("/positions/")
        self.assertEqual(resp.content.count(b'class="cap-pct"'), 1)

    def test_the_card_splits_paper_from_live_pools(self):
        _config(self.user, "crypto", 5000, name="live_c")             .__class__.objects.filter(name="live_c").update(mode="live")
        resp = self.client.get("/positions/")
        self.assertContains(resp, "LIVE")
        self.assertContains(resp, "paper 10,000")
        self.assertContains(resp, "live 5,000")

    def test_the_card_is_a_live_region_on_both_pages(self):
        """The wrapper renders OUTSIDE the capital guard so a transiently
        unreadable pool cannot freeze the card at its last reading —
        live_region.apply() leaves absent regions alone."""
        for url in ("/portfolio/", "/positions/"):
            resp = self.client.get(url)
            self.assertContains(resp, 'data-sv-live="cap-card"')
            self.assertContains(resp, 'data-sv-live-key="cap.used"')
