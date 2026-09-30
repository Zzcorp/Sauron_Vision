"""Each bot is judged on its own venue's book (2026-09-30).

The live box, 2026-09-30: every bot's heartbeat read "total exposure limit
reached: 4 open position(s) tie up 11,102.76 against a 9,398.99 ceiling
(live 0.00 across 0, paper 11,102.76 across 4 — each judged on its own,
never added)". open_capital_at_work had split the venues long ago, and
exposure_state could judge one alone, but AssetBot.can_open_new called
preflight with no venue, so "whichever binds" was the paper book, and four
simulated positions refused every LIVE bot with nothing live open.

Pinned here:
  - preflight and daily_loss_state take a venue, and judge that venue's
    ceiling and that venue's day alone; unnamed they read both, as the
    cards always did;
  - can_open_new names its config's venue: a live bot is not refused by
    paper positions or a paper loss, and a paper bot still is;
  - a LIVE config's paper-stage entry is still bounded by the paper book,
    in execute_entry, where its venue is known (_paper_book_refusal).

Run with:  python manage.py test tests.test_venue_book_limits
"""
import inspect
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


def _book(value="10000", exposure_pct=10, daily_loss_pct=3.0):
    from portfolio.risk_gate import limits_book
    pf = limits_book()
    pf.current_value = Decimal(value)
    pf.max_total_exposure_pct = exposure_pct
    pf.max_daily_loss_pct = daily_loss_pct
    pf.save()
    return pf


def _config(user, mode, name):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name=name, mode=mode,
        symbols=["BTCUSD"], capital=Decimal("10000"), enabled=True)


def _open(cfg, notional, *, paper):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
        qty=Decimal("1"), entry_price=Decimal(str(notional)), status="OPEN",
        paper=paper, opened_at=timezone.now())


def _closed(cfg, pnl, *, paper):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("100"), pnl=Decimal(str(pnl)), status="CLOSED",
        paper=paper, opened_at=timezone.now() - timedelta(hours=2),
        closed_at=timezone.now() - timedelta(hours=1))


class _Base(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("venue_book",
                                                         password="x")
        self.live_cfg = _config(self.user, "live", "LIVE BTC")
        self.paper_cfg = _config(self.user, "paper", "PAPER BTC")

    def _paper_over_the_ceiling(self):
        """The live box's shape: a 1,000 ceiling, paper holding 1,400."""
        _book()
        _open(self.paper_cfg, 700, paper=True)
        _open(self.paper_cfg, 700, paper=True)


class PreflightByVenueTests(_Base):

    def test_paper_positions_do_not_refuse_the_live_book(self):
        from portfolio.risk_gate import preflight
        self._paper_over_the_ceiling()
        live = preflight(self.user, venue="live")
        self.assertTrue(live["ok"], live["reason"])
        paper = preflight(self.user, venue="paper")
        self.assertFalse(paper["ok"])
        self.assertIn("total exposure", paper["reason"])

    def test_unnamed_still_reads_whichever_binds(self):
        """The cards and the manual preview name no venue, and must go on
        saying the paper book is full."""
        from portfolio.risk_gate import preflight
        self._paper_over_the_ceiling()
        both = preflight(self.user)
        self.assertFalse(both["ok"])
        self.assertIn("paper", both["reason"].lower())

    def test_live_positions_over_the_ceiling_still_refuse_live(self):
        from portfolio.risk_gate import preflight
        _book()
        _open(self.live_cfg, 1200, paper=False)
        self.assertFalse(preflight(self.user, venue="live")["ok"])
        self.assertTrue(preflight(self.user, venue="paper")["ok"])

    def test_the_venue_reaches_both_limits(self):
        from portfolio import risk_gate
        with patch.object(risk_gate, "daily_loss_state",
                          wraps=risk_gate.daily_loss_state) as dl, \
                patch.object(risk_gate, "exposure_state",
                             wraps=risk_gate.exposure_state) as ex:
            risk_gate.preflight(self.user, venue="live")
        self.assertEqual(dl.call_args.kwargs["venue"], "live")
        self.assertEqual(ex.call_args.kwargs["venue"], "live")


class DailyLossByVenueTests(_Base):

    def test_a_paper_loss_does_not_stop_the_live_day(self):
        from portfolio.risk_gate import daily_loss_state
        _book()
        _closed(self.paper_cfg, -400, paper=True)
        live = daily_loss_state(self.user, venue="live")
        self.assertTrue(live["ok"], live["reason"])
        self.assertEqual(live["realized"], 0.0)
        self.assertEqual(live["venue"], "live")
        self.assertFalse(daily_loss_state(self.user, venue="paper")["ok"])

    def test_a_live_loss_stops_the_live_day_and_not_the_paper_one(self):
        from portfolio.risk_gate import daily_loss_state
        _book()
        _closed(self.live_cfg, -400, paper=False)
        _closed(self.paper_cfg, 50, paper=True)
        live = daily_loss_state(self.user, venue="live")
        self.assertFalse(live["ok"])
        self.assertEqual(live["realized"], -400.0)
        paper = daily_loss_state(self.user, venue="paper")
        self.assertTrue(paper["ok"], paper["reason"])
        self.assertEqual(paper["realized"], 50.0)

    def test_unnamed_is_the_worse_of_the_two_as_before(self):
        from portfolio.risk_gate import daily_loss_state
        _book()
        _closed(self.live_cfg, 500, paper=False)
        _closed(self.paper_cfg, -400, paper=True)
        both = daily_loss_state(self.user)
        self.assertFalse(both["ok"])
        self.assertEqual(both["realized"], -400.0)
        self.assertNotIn("venue", both)

    def test_an_unmeasurable_day_stays_unknown_on_a_named_venue(self):
        """Rows that closed and none measurable are unknown, not flat: the
        venue filter must not turn that None into a confident 0.00."""
        from bot_program.models import AssetBotTrade
        from portfolio.risk_gate import daily_loss_state
        _book()
        t = _closed(self.live_cfg, -400, paper=False)
        AssetBotTrade.objects.filter(pk=t.pk).update(pnl=None)
        state = daily_loss_state(self.user, venue="live")
        self.assertIsNone(state["realized"])


class TheBotNamesItsVenueTests(_Base):

    def _bot(self, cfg):
        from bot_program.asset_engine.base import make_bot
        return make_bot(cfg)

    def test_a_live_bot_is_not_refused_by_the_paper_book(self):
        """The live box's heartbeat, 2026-09-30, is this test's failure."""
        self._paper_over_the_ceiling()
        ok, reason = self._bot(self.live_cfg).can_open_new()
        self.assertNotIn("total exposure", reason)
        self.assertNotIn("book risk limits", reason)

    def test_a_paper_bot_is_still_refused_by_the_paper_book(self):
        self._paper_over_the_ceiling()
        ok, reason = self._bot(self.paper_cfg).can_open_new()
        self.assertFalse(ok)
        self.assertIn("total exposure", reason)

    def test_can_open_new_asks_preflight_with_the_configs_venue(self):
        from portfolio import risk_gate
        for cfg, venue in ((self.live_cfg, "live"), (self.paper_cfg, "paper")):
            with patch.object(risk_gate, "preflight",
                              wraps=risk_gate.preflight) as pf:
                self._bot(cfg).can_open_new()
            self.assertEqual(pf.call_args.kwargs.get("venue"), venue,
                             cfg.mode)


class ThePreflightSaysItTests(_Base):
    """preflight_live never read the book limits: on the live box it said
    NO BLOCKERS while every live bot was refused. Section 6b reads them as
    a live bot does."""

    def _run(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("preflight_live", f"--user={self.user.username}",
                     stdout=out)
        return out.getvalue()

    def test_a_full_paper_book_is_printed_and_blocks_nothing_live(self):
        self._paper_over_the_ceiling()
        text = self._run()
        self.assertIn("6b. BOOK LIMITS — venue_book: live clear, paper "
                      "REFUSES", text)
        self.assertIn("(bounds paper entries only)", text)
        self.assertNotIn("the live book limits refuse", text)

    def test_a_full_live_book_blocks_while_a_live_config_is_armed(self):
        _book()
        _open(self.live_cfg, 1200, paper=False)
        text = self._run()
        self.assertIn("live REFUSES, paper clear", text)
        verdict = text[text.index("BLOCKERS — do not arm"):]
        self.assertIn("venue_book: the live book limits refuse every live "
                      "entry — ", verdict)

    def test_with_nothing_armed_it_is_only_worth_reading(self):
        from bot_program.models import AssetBotConfig
        _book()
        _open(self.live_cfg, 1200, paper=False)
        AssetBotConfig.objects.filter(mode="live").update(enabled=False)
        text = self._run()
        worth = text[text.index("WORTH READING:"):]
        self.assertIn("the live book limits refuse every live entry", worth)


class ThePaperStageEntryTests(_Base):

    def test_the_paper_book_bounds_a_live_configs_paper_entry(self):
        from bot_program.asset_engine.base import make_bot
        self._paper_over_the_ceiling()
        why = make_bot(self.live_cfg)._paper_book_refusal()
        self.assertIn("total exposure", why)

    def test_a_paper_book_with_room_says_nothing(self):
        from bot_program.asset_engine.base import make_bot
        _book()
        _open(self.live_cfg, 900, paper=False)
        self.assertEqual(make_bot(self.live_cfg)._paper_book_refusal(), "")

    def test_execute_entry_asks_it_on_the_paper_branch_of_a_live_config(self):
        """Only a LIVE config's paper-stage entry: a paper config was judged
        on the paper book by can_open_new already, and a live order is
        judged on the live book there too."""
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        self.assertEqual(src.count("self._paper_book_refusal()"), 1)
        at = src.index("self._paper_book_refusal()")
        self.assertIn("if not paper_now:", src[at - 200:at])
        self.assertLess(src.index("if paper:"), at)
        self.assertIn("return self._skip(symbol, skips.GATE_BLOCKED, _why)",
                      src[at:at + 200])


class TheLiveLimitsReadTheRealAccountTests(_Base):
    """The live box, 2026-09-30: the /setup/ book read 9,420 EUR, the
    eToro account 2,249.65 USD, so "3% max daily loss" stopped real money
    at ~282 — 12.5% of it. A LIVE judgement now reads the account's last
    equity reading; paper keeps the /setup/ book, whose research pools are
    100,000 each and would all be refused against the account."""

    def _account(self, equity="2249.65", age_minutes=5):
        from datetime import timedelta as _td

        from bot_program.models import EtoroAccount
        acct = EtoroAccount.objects.create(
            user=self.user, is_primary_for_forex=True,
            is_primary_for_crypto=True, last_equity=Decimal(equity),
            last_equity_currency="USD",
            last_equity_at=timezone.now() - _td(minutes=age_minutes))
        acct.set_credentials("the-api-key", "the-user-key")
        acct.save()
        return acct

    def test_a_live_judgement_reads_the_account(self):
        from portfolio.risk_gate import limits_book, venue_book_value
        _book(value="9420")
        self._account()
        self.assertEqual(venue_book_value(self.user, limits_book(), "live"),
                         (2249.65, "the broker account"))

    def test_paper_and_unnamed_keep_the_setup_book(self):
        from portfolio.risk_gate import limits_book, venue_book_value
        _book(value="9420")
        self._account()
        for venue in ("paper", ""):
            value, source = venue_book_value(self.user, limits_book(), venue)
            self.assertEqual(value, 9420.0, venue)
            self.assertEqual(source, "the /setup/ book", venue)

    def test_a_stale_or_missing_reading_falls_back_and_says_so(self):
        from portfolio.risk_gate import limits_book, venue_book_value
        _book(value="9420")
        value, source = venue_book_value(self.user, limits_book(), "live")
        self.assertEqual(value, 9420.0)
        self.assertIn("no fresh broker reading", source)
        self._account(age_minutes=3 * 60)
        value, source = venue_book_value(self.user, limits_book(), "live")
        self.assertEqual(value, 9420.0)
        self.assertIn("no fresh broker reading", source)

    def test_the_live_daily_floor_is_a_share_of_real_money(self):
        """8% of 2,249.65 is 179.97: the operator's chosen brake."""
        from portfolio.risk_gate import daily_loss_state
        _book(value="9420", daily_loss_pct=8.0)
        self._account()
        live = daily_loss_state(self.user, venue="live")
        self.assertAlmostEqual(live["limit_money"], -179.97, places=2)
        self.assertEqual(live["book_source"], "the broker account")
        paper = daily_loss_state(self.user, venue="paper")
        self.assertAlmostEqual(paper["limit_money"], -753.6, places=2)

    def test_a_live_loss_past_the_floor_refuses_and_names_the_account(self):
        from portfolio.risk_gate import daily_loss_state
        _book(value="9420", daily_loss_pct=8.0)
        self._account()
        _closed(self.live_cfg, -200, paper=False)
        state = daily_loss_state(self.user, venue="live")
        self.assertFalse(state["ok"])
        self.assertIn("2,249.65, the broker account", state["reason"])
        # The same 200 of real money passes against the 9,420 book: the
        # unnamed judgement (the cards) keeps the book, as before.
        self.assertTrue(daily_loss_state(self.user)["ok"])

    def test_the_live_exposure_ceiling_is_the_account(self):
        from portfolio.risk_gate import exposure_state
        _book(value="9420", exposure_pct=100)
        self._account()
        state = exposure_state(self.user, venue="live")
        self.assertAlmostEqual(state["cap_money"], 2249.65, places=2)
        self.assertEqual(state["book_source"], "the broker account")
        paper = exposure_state(self.user, venue="paper")
        self.assertAlmostEqual(paper["cap_money"], 9420.0, places=2)
