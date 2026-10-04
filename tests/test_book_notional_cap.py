"""The book's notional cap, pools bounded by the book, the book saying when
pools exceed it (2026-10-04).

A 500 book carried two hand-taken yen crosses of 14,800 — twenty-nine
times itself — inside "100% max total exposure", because that limit
counts a forex row at its margin (1/30): 494 at work. The manual pool
that sized them declared 10,000 nobody had, and the weekly review graded
the book "critical, -97.6% drawdown" on a ratio between two numbers that
do not know each other.

Pinned: Portfolio.max_notional_multiple (default 4, card bounds 1-50);
risk_gate.notional_state summing one venue's entry notional in account
money, with a candidate added, against the multiple of the venue's book
— a research pool against its own pool and its own rows, research rows
left out of the book's count; the gate in preflight (with `config`) and
on the bots' final size, and on the manual ticket as an advisory the
preview wires into book_advisory; pool_vs_book refusing a paper pool
larger than its owner's book at `bot on` and at can_open_new, exempting
research and live pools; sizing_gap's sentence; the weekly review naming
each snapshot's book and carrying the sentence.

Run with:  python manage.py test tests.test_book_notional_cap
"""
import io
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from tests.test_risk_limits_bind import _book, _config

YEN_PER_USD = 157.8


def _row(cfg, *, symbol="EURJPY", entry="179.5", qty="6400", paper=True,
         vpu=None, status="OPEN", stop=None):
    from bot_program.models import AssetBotTrade
    meta = {} if vpu is None else {"value_per_unit": vpu}
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal(qty), entry_price=Decimal(entry), status=status,
        stop_loss=None if stop is None else Decimal(stop),
        paper=paper, metadata=meta)


class TheLimitTests(SimpleTestCase):

    def test_the_default_and_the_card_bounds(self):
        from dashboard.views import (RISK_LIMIT_BOUNDS, RISK_LIMIT_FIELDS,
                                     RISK_LIMIT_OPTIONAL)
        from portfolio.models import Portfolio
        self.assertEqual(Portfolio._meta.get_field(
            "max_notional_multiple").default, 4.0)
        self.assertEqual(RISK_LIMIT_BOUNDS["max_notional_multiple"],
                         (1.0, 50.0, "Max notional multiple"))
        self.assertEqual(RISK_LIMIT_FIELDS["max_notional"],
                         "max_notional_multiple")
        self.assertIn("max_notional", RISK_LIMIT_OPTIONAL)

    def test_the_migration(self):
        path = Path("portfolio/migrations/0017_portfolio_max_notional_multiple.py")
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn('("portfolio", "0016_portfolio_max_open_risk_pct")', text)
        self.assertIn('name="max_notional_multiple"', text)

    def test_the_card_carries_the_field(self):
        html = Path("templates/dashboard/setup.html").read_text(encoding="utf-8")
        self.assertIn('name="max_notional"', html)
        self.assertIn("MAX NOTIONAL MULTIPLE", html)
        self.assertIn("risk_sizing_gap.text", html)


class TheNotionalStateTests(TestCase):
    """A 500 paper book at 4x: a 2,000 notional ceiling."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("nc_state",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("500"), max_notional_multiple=4.0)
        self.cfg = _config(self.user, asset_class="forex")

    def _state(self, **kw):
        from portfolio.risk_gate import notional_state
        return notional_state(self.user, venue="paper", **kw)

    def test_the_isa_book_as_it_stood(self):
        """6,400 EURJPY at 179.5 and 5,500 GBPJPY at 209: about 14,600 of
        dollars on a 500 book — twenty-nine times it."""
        _row(self.cfg, vpu=1 / YEN_PER_USD)
        _row(self.cfg, symbol="GBPJPY", entry="209.0", qty="5500",
             vpu=1 / YEN_PER_USD)
        s = self._state()
        self.assertFalse(s["ok"])
        self.assertAlmostEqual(s["open_notional"],
                               (6400 * 179.5 + 5500 * 209.0) / YEN_PER_USD,
                               places=1)
        self.assertEqual((s["limit_money"], s["rows"], s["multiple"]),
                         (2000.0, 2, 4.0))
        self.assertIn("x the 500.00 book; the cap is 4x (2,000.00)", s["reason"])
        self.assertIn("29.", s["reason"])

    def test_inside_the_ceiling_and_the_candidate_that_passes_it(self):
        _row(self.cfg, symbol="AAPL", entry="100", qty="10")   # 1,000
        s = self._state()
        self.assertTrue(s["ok"], s["reason"])
        self.assertEqual(s["reason"],
                         "1,000.00 of 2,000.00 notional ceiling (4x the book)")
        s = self._state(adding=900)
        self.assertTrue(s["ok"])
        s = self._state(adding=1500)
        self.assertFalse(s["ok"])
        self.assertIn("2,500.00 of notional open with this entry — 5.0x the "
                      "500.00 book", s["reason"])

    def test_the_venues_are_judged_apart(self):
        _row(self.cfg, symbol="AAPL", entry="100", qty="100", paper=False)
        self.assertEqual(self._state()["open_notional"], 0.0)
        from portfolio.risk_gate import notional_state
        live = notional_state(self.user, venue="live")
        self.assertEqual(live["open_notional"], 10000.0)
        self.assertFalse(live["ok"])

    def test_a_research_pool_is_measured_against_itself(self):
        research = _config(self.user, asset_class="stock", name="research_x",
                           capital=Decimal("100000"),
                           extras={"research_fleet": True})
        _row(research, symbol="MSFT", entry="500", qty="100")   # 50,000
        # left out of the owner's book count …
        book = self._state()
        self.assertEqual((book["open_notional"], book["rows"]), (0.0, 0))
        self.assertTrue(book["ok"])
        # … and judged against its own pool, with its own rows
        from portfolio.risk_gate import notional_state
        own = notional_state(self.user, venue="paper", config=research)
        self.assertTrue(own["research"])
        self.assertEqual((own["base"], own["base_label"], own["open_notional"],
                          own["limit_money"]),
                         (100000.0, "research pool", 50000.0, 400000.0))
        self.assertTrue(own["ok"])
        self.assertIn("4x the research pool", own["reason"])
        self.assertFalse(notional_state(self.user, venue="paper",
                                        config=research, adding=360000)["ok"])
        # an ordinary config asking reads the book, not its pool
        plain = notional_state(self.user, venue="paper", config=self.cfg)
        self.assertEqual((plain["research"], plain["base"]), (False, 500.0))

    def test_no_multiple_or_no_book_measures_nothing(self):
        _book(max_notional_multiple=0)
        s = self._state()
        self.assertTrue(s["ok"])
        self.assertEqual(s["reason"], "no notional multiple set on the book")
        _book(max_notional_multiple=4.0, current_value=Decimal("0"))
        s = self._state()
        self.assertTrue(s["ok"])
        self.assertIn("never been set", s["reason"])

    def test_a_legacy_position_counts_on_the_live_venue_once(self):
        from portfolio.risk_gate import limits_book, notional_state
        from tests.test_portfolio_value_truth import _position
        _position(limits_book(), "NVDA", qty="5", entry="100", current="100")
        live = notional_state(self.user, venue="live")
        self.assertEqual((live["open_notional"], live["rows"]), (500.0, 1))
        # a bot row on the same symbol: the legacy mirror is not added
        _row(self.cfg, symbol="NVDA", entry="100", qty="5", paper=False)
        live = notional_state(self.user, venue="live")
        self.assertEqual((live["open_notional"], live["rows"]), (500.0, 1))

    def test_preflight_carries_it_and_reads_the_config(self):
        from portfolio.risk_gate import preflight
        _row(self.cfg, vpu=1 / YEN_PER_USD)
        out = preflight(self.user, venue="paper")
        self.assertIn("notional", out["checks"])
        self.assertFalse(out["ok"])
        self.assertIn("book risk limits:", out["reason"])
        self.assertIn("the cap is 4x", out["reason"])
        research = _config(self.user, asset_class="stock", name="research_y",
                           capital=Decimal("100000"),
                           extras={"research_fleet": True})
        own = preflight(self.user, venue="paper", config=research)
        self.assertTrue(own["checks"]["notional"]["research"])
        self.assertEqual(own["checks"]["notional"]["base"], 100000.0)


class ThePoolVsBookTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("nc_pool",
                                                        password="x")

    def setUp(self):
        # The book its owner SET: the cash (/setup/), not the marked value.
        _book(current_value=Decimal("273.07"), cash_available=Decimal("500"))

    def test_a_paper_pool_larger_than_the_book_is_refused(self):
        from portfolio.risk_gate import pool_vs_book
        cfg = _config(self.user, asset_class="forex", capital=Decimal("10000"))
        s = pool_vs_book(cfg)
        self.assertFalse(s["ok"])
        self.assertEqual((s["pool"], s["book"], s["research"], s["mode"]),
                         (10000.0, 500.0, False, "paper"))
        self.assertIn("pool 10,000.00 declares more than the 500.00 book its "
                      "owner set at /setup/ (20.0x)", s["reason"])
        cfg.capital = Decimal("500")
        cfg.save()
        s = pool_vs_book(cfg)
        self.assertTrue(s["ok"])
        self.assertEqual(s["reason"], "pool 500.00 inside the 500.00 book")

    def test_the_declaration_is_judged_not_the_marked_value(self):
        """A 10,000 pool on a 10,000 book stays a fit after a paper loss
        marks the book at 9,900 — the family books are seeded equal to
        their starter pools, and a bad day must not freeze their fleet."""
        from portfolio.risk_gate import declared_book, pool_vs_book
        _book(current_value=Decimal("9900"), cash_available=Decimal("10000"))
        cfg = _config(self.user, capital=Decimal("10000"))
        self.assertTrue(pool_vs_book(cfg)["ok"])
        self.assertEqual(declared_book(self.user, None), None)
        from portfolio.risk_gate import limits_book
        self.assertEqual(declared_book(self.user, limits_book()), 10000.0)
        # the owner's own row wins when it exists
        from portfolio.services import get_or_create_default_portfolio
        own = get_or_create_default_portfolio(user=self.user)
        own.cash_available = Decimal("500")
        own.save()
        self.assertEqual(declared_book(self.user, limits_book()), 500.0)
        self.assertFalse(pool_vs_book(cfg)["ok"])

    def test_research_and_live_pools_are_exempt_and_say_so(self):
        from portfolio.risk_gate import pool_vs_book
        research = _config(self.user, name="research_z",
                           capital=Decimal("100000"),
                           extras={"research_fleet": True})
        s = pool_vs_book(research)
        self.assertTrue(s["ok"])
        self.assertIn("research pool", s["reason"])
        live = _config(self.user, name="live_z", mode="live",
                       capital=Decimal("100000"))
        s = pool_vs_book(live)
        self.assertTrue(s["ok"])
        self.assertIn("live pool", s["reason"])

    def test_a_book_never_set_measures_nothing(self):
        from portfolio.risk_gate import pool_vs_book
        _book(current_value=Decimal("0"), cash_available=Decimal("0"))
        s = pool_vs_book(_config(self.user, capital=Decimal("10000")))
        self.assertTrue(s["ok"])
        self.assertIn("never been set", s["reason"])

    def test_bot_on_refuses_it_and_arms_a_fitting_one(self):
        cfg = _config(self.user, capital=Decimal("10000"), enabled=False)
        out = io.StringIO()
        call_command("bot", "on", str(cfg.pk), stdout=out)
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)
        self.assertIn("not armed — pool 10,000.00 declares more than the "
                      "500.00 book", out.getvalue())
        cfg.capital = Decimal("400")
        cfg.save()
        out = io.StringIO()
        call_command("bot", "on", str(cfg.pk), stdout=out)
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)
        self.assertIn("ENABLED", out.getvalue())
        # off never asks
        cfg.capital = Decimal("10000")
        cfg.save()
        call_command("bot", "off", str(cfg.pk), stdout=io.StringIO())
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)

    def test_can_open_new_refuses_it_first(self):
        from bot_program.asset_engine.base import make_bot
        cfg = _config(self.user, asset_class="stock", capital=Decimal("10000"),
                      symbols=["AAPL"])
        ok, why = make_bot(cfg).can_open_new()
        self.assertFalse(ok)
        self.assertIn("pool 10,000.00 declares more than the 500.00 book", why)

    def test_the_toggles_refuse_it_in_source(self):
        """The HQ toggle and the map toggle ask pool_vs_book before
        ARMING, never before disabling."""
        import inspect
        from dashboard import views_admin_hq, views_topology
        for fn in (views_admin_hq.hq_toggle_asset_bot,
                   views_topology.system_map_toggle):
            src = inspect.getsource(fn)
            self.assertIn("if not cfg.enabled:", src)
            self.assertIn("pool_vs_book(cfg)", src)


class TheSizingGapTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("nc_gap",
                                                        password="x")

    def test_the_sentence_when_the_pools_exceed_the_book(self):
        from portfolio.risk_gate import sizing_gap
        _book(current_value=Decimal("273.07"), cash_available=Decimal("500"))
        _config(self.user, name="manual", asset_class="forex",
                capital=Decimal("10000"))
        _config(self.user, name="starter", asset_class="stock",
                capital=Decimal("10000"))
        _config(self.user, name="research_1", asset_class="crypto",
                capital=Decimal("100000"), extras={"research_fleet": True})
        _config(self.user, name="off", asset_class="commodity",
                capital=Decimal("10000"), enabled=False)
        _config(self.user, name="live", asset_class="forex", mode="live",
                capital=Decimal("2000"))
        gap = sizing_gap(self.user)
        self.assertEqual((gap["book"], gap["pools"], gap["research_pools"],
                          gap["configs"]), (500.0, 20000.0, 100000.0, 2))
        self.assertEqual(gap["text"],
                         "Sized by 2 paper pools totalling 20,000.00 (and "
                         "100,000.00 of research pools) against a 500.00 book "
                         "— the percentages and the drawdown measure the book, "
                         "not the money that sized the positions.")

    def test_silent_when_they_fit(self):
        from portfolio.risk_gate import sizing_gap
        _book(current_value=Decimal("50000"), cash_available=Decimal("50000"))
        _config(self.user, name="manual", capital=Decimal("10000"))
        gap = sizing_gap(self.user)
        self.assertEqual(gap["text"], "")
        self.assertEqual(gap["pools"], 10000.0)


class TheReviewTests(TestCase):

    def test_the_notes_name_the_books_they_can(self):
        from ai_agents.tasks import _sizing_notes
        from portfolio.services import get_or_create_default_portfolio
        user = get_user_model().objects.create_user("nc_review", password="x")
        own = get_or_create_default_portfolio(user=user)
        own.current_value = Decimal("273.07")
        own.cash_available = Decimal("500")
        own.save()
        _config(user, name="manual", capital=Decimal("10000"))
        notes = _sizing_notes({own.name, "Main", "nobody_main"})
        self.assertIn("Sized by 1 paper pool totalling 10,000.00 against a "
                      "500.00 book", notes[own.name])
        self.assertEqual(notes["Main"], "")
        self.assertEqual(notes["nobody_main"], "")

    def test_the_review_reads_named_snapshots(self):
        import inspect
        from ai_agents import tasks
        from ai_agents.agents.weekly_reviewer import WeeklyReviewerAgent
        src = inspect.getsource(tasks.generate_weekly_review)
        self.assertIn('"portfolio__name"', src)
        self.assertIn('s["sizing_note"] = notes.get', src)
        self.assertIn("sizing_note", WeeklyReviewerAgent().get_system_prompt())


class TheTicketTests(SimpleTestCase):

    def test_the_preview_wires_both_into_the_book_advisory(self):
        import inspect
        from bot_program import manual_trade
        src = inspect.getsource(manual_trade._preview)
        self.assertIn("notional_state(user, portfolio=risk_book,", src)
        self.assertIn("pool_vs_book(cfg, portfolio=risk_book)", src)
        self.assertIn('"notional": notional_gate, "pool": pool_gate', src)

    def test_the_bots_final_size_asks_the_cap(self):
        import inspect
        from bot_program.asset_engine import base
        src = inspect.getsource(base.AssetBot)
        self.assertIn("ncap = notional_state(", src)
        self.assertIn("refused by the book's notional cap", src)
        self.assertIn("pool = pool_vs_book(self.cfg)", src)
        self.assertIn("config=self.cfg)", src)
