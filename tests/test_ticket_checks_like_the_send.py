"""The TAKE TRADE ticket asks the send's own cash check before the PIN
(2026-10-31).

The operator met eToro's free cash only after typing the PIN: _execute
asks AssetBot._leverage_headroom before a live eToro order and the preview
never did, so the ticket looked takeable and the send refused it ("needs X
of margin and Y is free (Z read N min ago ...)"). The ticket's "Capital
free" is the manual POOL, not eToro's cash.

WHAT THESE TESTS CONFRONT

  * The preview carries `cash_gate`: the cells (cash, used, equity), their
    age, the verdict at the default size, and the size the gate leaves
    room for — its free cash and the pledge ceiling, at the ticket's
    multiplier — which caps the size control.
  * The pool's own `available` and `deficit` are untouched: they drive
    this lane's refusals and its funding proposals.
  * Cells older than a minute ask the account to be read again, and the
    ticket says so; a refusal at the send judged on such cells names when
    that read lands, and still ends "nothing was sent".
  * The equity carries its own age: a re-read moves the cells alone, so
    an equity over an hour old refuses at the ticket and at the send, and
    nothing asks or promises a re-read that could not lift it.
  * A paper ticket and another carrier are not asked.
  * judge_qty's docstring names the 7% ceiling it enforces.

Run with:  python manage.py test tests.test_ticket_checks_like_the_send
"""
import inspect
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

REFRESH = "bot_program.etoro_cells.request_refresh"


class _LiveEtoroTicket(TestCase):
    """A LIVE crypto manual lane on the REAL eToro adapter (demo world)
    over a fake wire — tests.test_take_trade_live's own harness."""

    username = "tk_cash"

    def setUp(self):
        from tests.test_etoro_client import _clear_eligibility
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _quote)
        cache.clear()
        self.user = get_user_model().objects.create_user(self.username,
                                                         password="x")
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        p = patch("bot_program.asset_engine.base.ETORO_PROVEN",
                  frozenset({"crypto"}))
        p.start()
        self.addCleanup(p.stop)

    def _cells(self, **kw):
        from tests.test_etoro_leverage import _account
        kw.setdefault("cash", 1000)
        kw.setdefault("used", 2000)
        kw.setdefault("equity", 10000)
        return _account(self.user, **kw)

    def _etoro(self):
        from tests.test_etoro_client import ELIG_BTC, SEARCH_BTC, _client
        t, fake = _client([SEARCH_BTC, ELIG_BTC])
        p = patch.object(t, "ticker", return_value={"lastPrice": "60000"})
        p.start()
        self.addCleanup(p.stop)
        return t, fake

    def _preview(self, t):
        from bot_program.manual_trade import preview_take_trade
        from tests.test_take_trade_live import ROUTER, _signal
        self.signal = _signal(self.inst)
        with patch(ROUTER, return_value=t):
            return preview_take_trade(self.user, self.signal)


class ThePreviewAsksTheSendsCashCheckTests(_LiveEtoroTicket):

    def test_the_ticket_shows_the_refusal_the_send_would_give(self):
        """1,000 free, 2,000 used of 10,000: the default BTC ticket needs
        about 1,667 of margin at 1x — the send refuses it, and the ticket
        now says so before the PIN, with the cells and their age, and caps
        the size control at the 1,000 the gate leaves free."""
        acct = self._cells(age_s=30)
        t, _ = self._etoro()
        with patch(REFRESH) as asked:
            out = self._preview(t)
        self.assertNotIn("error", out, out)
        cg = out["cash_gate"]
        self.assertTrue(cg["asked"])
        self.assertFalse(cg["ok"])
        self.assertIn("1,000.00 is free", cg["reason"])
        self.assertIn("refused before the venue refuses it", cg["reason"])
        self.assertEqual((cg["cash"], cg["used"], cg["equity"]),
                         (1000.0, 2000.0, 10000.0))
        self.assertEqual(cg["currency"], "USD")
        self.assertEqual(cg["read_at"], acct.last_margin_at.isoformat())
        self.assertLess(abs(cg["age_s"] - 30), 5)
        self.assertEqual(cg["age_words"][-1:], "s")
        self.assertEqual(cg["free"], 1000.0)
        # the room: min(free 1,000; 50% of 10,000 - 2,000 used = 3,000)
        self.assertEqual(cg["room"], 1000.0)
        self.assertEqual(cg["margin_per_unit"], 60000.0)
        self.assertLessEqual(cg["max_qty"] * 60000.0, 1000.0 + 1e-6)
        self.assertGreater(cg["max_qty"], 0)
        self.assertLess(cg["max_qty"], out["qty"])
        # fresh cells: no re-read is asked
        asked.assert_not_called()
        self.assertEqual(cg["refresh"], {"asked": False, "in_s": None})

    def test_the_pools_own_fields_are_left_as_they_were(self):
        """`available` and `deficit` are the POOL's: lowering them to eToro's
        cash would refuse tickets and propose funding closes."""
        self._cells(age_s=30)
        t, _ = self._etoro()
        with patch(REFRESH):
            out = self._preview(t)
        self.assertEqual(out["available"], float(self.cfg.capital))
        self.assertEqual(out["deficit"], 0.0)
        self.assertTrue(out["sufficient"])
        self.assertEqual(out["close_proposal"], [])
        self.assertGreaterEqual(out["max_qty"], out["qty"])

    def test_the_pledge_ceiling_bounds_the_room_too(self):
        """5,000 free but 4,600 used of 10,000: the 50% ceiling leaves 400
        of margin, and that is the room the size control stops at."""
        self._cells(cash=5000, used=4600, age_s=30)
        t, _ = self._etoro()
        with patch(REFRESH):
            out = self._preview(t)
        cg = out["cash_gate"]
        self.assertAlmostEqual(cg["room"], 400.0, places=6)
        self.assertFalse(cg["ok"])
        self.assertIn("pledged", cg["reason"])

    def test_cells_older_than_a_minute_ask_a_re_read_and_say_so(self):
        acct = self._cells(age_s=600)
        t, _ = self._etoro()
        with patch(REFRESH, return_value=3.0) as asked:
            out = self._preview(t)
        asked.assert_called_once_with(acct.pk, why="ticket")
        self.assertEqual(out["cash_gate"]["refresh"],
                         {"asked": True, "in_s": 3})
        self.assertEqual(out["cash_gate"]["age_words"], "10 min")

    def test_the_ticket_dates_the_equity_apart_from_the_cells(self):
        """The re-read after an order dates the cells and never the equity
        (2026-10-31, review): the ticket said "... used of <equity> · read
        10 s ago", the cells' age on the equity."""
        from datetime import timedelta

        from django.utils import timezone

        from bot_program.models import EtoroAccount
        acct = self._cells(age_s=30)
        eq_at = timezone.now() - timedelta(minutes=20)
        EtoroAccount.objects.filter(pk=acct.pk).update(last_equity_at=eq_at)
        t, _ = self._etoro()
        with patch(REFRESH):
            cg = self._preview(t)["cash_gate"]
        self.assertEqual(cg["equity_age_words"], "20 min")
        self.assertEqual(cg["equity_read_at"], eq_at.isoformat())
        self.assertEqual(cg["age_words"][-1:], "s")

    def test_an_old_equity_asks_and_promises_no_re_read(self):
        """A re-read writes the cells and never the equity: on an equity
        over an hour old the ticket shows the refusal and asks nothing a
        re-read could not cure."""
        from datetime import timedelta

        from django.utils import timezone

        from bot_program.models import EtoroAccount
        acct = self._cells(age_s=600)
        EtoroAccount.objects.filter(pk=acct.pk).update(
            last_equity_at=timezone.now() - timedelta(hours=2))
        t, _ = self._etoro()
        with patch(REFRESH) as asked:
            cg = self._preview(t)["cash_gate"]
        asked.assert_not_called()
        self.assertEqual(cg["refresh"], {"asked": False, "in_s": None})
        self.assertFalse(cg["ok"])
        self.assertIn("equity reading 2.0h old", cg["reason"])

    def test_a_ticket_inside_the_cells_is_ok_and_uncapped_by_them(self):
        self._cells(cash=100000, used=0, equity=100000, age_s=30)
        t, _ = self._etoro()
        with patch(REFRESH):
            out = self._preview(t)
        cg = out["cash_gate"]
        self.assertTrue(cg["ok"], cg["reason"])
        self.assertGreater(cg["max_qty"], out["qty"])


class TheSendNamesTheReReadTests(_LiveEtoroTicket):

    username = "tk_send"

    def _execute(self, t):
        from bot_program.manual_trade import execute_take_trade
        from tests.test_take_trade_live import ROUTER, _signal
        with patch.object(t, "market_order",
                          wraps=t.market_order) as spy, \
                patch(ROUTER, return_value=t):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        return out, spy

    def test_a_refusal_on_stale_cells_names_when_the_re_read_lands(self):
        acct = self._cells(age_s=600)
        t, _ = self._etoro()
        with patch(REFRESH, return_value=3.0) as asked:
            out, spy = self._execute(t)
        self.assertIn("error", out, out)
        self.assertTrue(out["error"].startswith(
            "eToro refusal (leverage_refused): at 1x: "), out["error"])
        self.assertIn("1,000.00 is free", out["error"])
        self.assertIn("the account's cells are 10 min old, so a fresh read "
                      "of the eToro account was asked: it lands in about "
                      "3 s — send again after it", out["error"])
        self.assertTrue(out["error"].endswith("nothing was sent"),
                        out["error"])
        self.assertIn(((acct.pk,), {"why": "ticket refused"}),
                      [(c.args, c.kwargs) for c in asked.call_args_list])
        spy.assert_not_called()

    def test_a_refusal_on_fresh_cells_asks_nothing(self):
        self._cells(age_s=20)
        t, _ = self._etoro()
        with patch(REFRESH) as asked:
            out, spy = self._execute(t)
        self.assertIn("1,000.00 is free", out["error"])
        self.assertNotIn("fresh read", out["error"])
        self.assertNotIn("ticket refused", [c.kwargs.get("why")
                                            for c in asked.call_args_list])
        spy.assert_not_called()

    def test_a_re_read_does_not_open_the_send_on_an_old_equity(self):
        """The skeptic's end to end (2026-10-31): a lane that does not
        follow the account, the default 50% ceiling, cells and equity
        three hours old as when celery beat is down. The send used to say
        "send again after it"; the re-read freshened the cells alone, and
        the second send reached eToro at 47% of the stale 10,000 — 55% of
        the 8,500 that same read carried. Now both sends are refused on
        the equity's age and nothing promises otherwise."""
        from bot_program.capital_truth import tracks_broker
        from bot_program.tasks import refresh_etoro_cells
        from tests.test_reread_after_orders import (TRADER, _account,
                                                    _components,
                                                    _snapshot_client)
        _components()
        self.assertFalse(tracks_broker(self.cfg))
        acct = _account(self.user, cash="3000.00", used="3000.00",
                        equity="10000.00", age_s=3 * 3600)
        t, _ = self._etoro()
        with patch(REFRESH) as asked:
            first, sent = self._execute(t)
        self.assertIn("equity reading 3.0h old", first.get("error", ""))
        self.assertNotIn("send again after it", first["error"])
        self.assertEqual(asked.call_count, 0)
        sent.assert_not_called()
        with patch(TRADER, return_value=_snapshot_client(3000.0, 3000.0,
                                                         8500.0)):
            self.assertTrue(refresh_etoro_cells(acct.pk,
                                                why="ticket refused")["read"])
        with patch(REFRESH):
            second, sent = self._execute(t)
        self.assertIn("equity reading 3.0h old", second.get("error", ""))
        self.assertTrue(second["error"].endswith("nothing was sent"),
                        second["error"])
        sent.assert_not_called()


class APaperTicketIsNotAskedTests(TestCase):

    def test_a_paper_ticket_carries_no_cash_gate(self):
        from bot_program.manual_trade import preview_asset_trade
        from tests.test_one_bet_one_ticket import _book, _instrument
        from market_data.models import LiveQuote
        from decimal import Decimal
        user = get_user_model().objects.create_user("tk_paper", password="x")
        _book(current_value=Decimal("10000"), max_daily_loss_pct=100.0,
              max_total_exposure_pct=1000.0, max_single_position_pct=100.0)
        inst = _instrument("BTCUSD", "crypto", "CRYPTO")
        LiveQuote.objects.update_or_create(
            instrument=inst, defaults={"last": Decimal("50000"),
                                       "source": "binance_public"})
        out = preview_asset_trade(user, inst, "BUY")
        self.assertNotIn("error", out, out)
        self.assertIsNone(out["cash_gate"])


class TheCashGateKeepsItsWordsTests(_LiveEtoroTicket):
    """_leverage_headroom answers _cash_gate's refusal, word for word, and
    None where the gate passes; another carrier is not judged at all."""

    username = "tk_words"

    def test_the_headroom_is_the_gates_refusal(self):
        from unittest.mock import MagicMock

        from bot_program.asset_engine.base import make_bot
        bot = make_bot(self.cfg)
        t, _ = self._etoro()
        kw = dict(qty=0.03, price=60000.0, leverage=1)
        none = bot._cash_gate(t, "BTCUSD", **kw)
        self.assertIn("have never been stored by the sync", none["refusal"])
        self.assertEqual(bot._leverage_headroom(t, "BTCUSD", **kw),
                         none["refusal"])
        self._cells(age_s=30)
        short = bot._cash_gate(t, "BTCUSD", **kw)
        self.assertEqual(bot._leverage_headroom(t, "BTCUSD", **kw),
                         short["refusal"])
        self.assertIn("1,000.00 is free", short["refusal"])
        self.assertIsNone(bot._leverage_headroom(t, "BTCUSD", qty=0.01,
                                                 price=60000.0, leverage=1))
        # another carrier: not an eToro judgement (the ticket asks nothing),
        # and the headroom keeps its old answer for it — no cells to read
        other = bot._cash_gate(MagicMock(), "BTCUSD", **kw)
        self.assertFalse(other["asked"])
        self.assertEqual(bot._leverage_headroom(MagicMock(), "BTCUSD", **kw),
                         other["refusal"])


class TheTicketPageReadsItTests(SimpleTestCase):
    """The confirm dialog renders the cells, the refusal and the re-read,
    and its size judge stops at the gate's room."""

    def test_the_dialog_reads_the_cash_gate(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "base.html"
               ).read_text(encoding="utf-8")
        fn = src[src.index("function sizeDialog(p)"):]
        fn = fn[:fn.index("var okBtn = host.querySelector")]
        self.assertIn("p.cash_gate", fn)
        self.assertIn("'eToro cash'", fn)
        self.assertIn("cg.refresh.asked", fn)
        # the equity carries its own age, apart from the cells' (2026-10-31)
        cash_line = fn[fn.index("facts.push(['eToro cash'"):]
        cash_line = cash_line[:cash_line.index("]);")]
        self.assertIn("cg.equity_age_words", cash_line)
        self.assertIn(" used · cells read ", cash_line)
        self.assertNotIn("' used of '", cash_line)
        # a refusal with no room figure is not called a size refusal
        self.assertIn("(cashMax !== null ? 'SIZE' : 'TICKET')", fn)
        judge = fn[fn.index("function judgeSize(q)"):]
        judge = judge[:judge.index("/* ── Markup")]
        self.assertIn("cashMax", judge)
        self.assertIn("The send would refuse it", judge)


class JudgeQtySaysItsCeilingTests(SimpleTestCase):

    def test_the_docstring_names_the_seven_percent_ceiling(self):
        from bot_program.asset_engine.sizing import MAX_RISK_FRACTION
        from bot_program.manual_trade import judge_qty
        doc = inspect.getdoc(judge_qty)
        self.assertNotIn("1.0% ceiling", doc)
        self.assertIn(f"{MAX_RISK_FRACTION * 100:g}% ceiling", doc)
