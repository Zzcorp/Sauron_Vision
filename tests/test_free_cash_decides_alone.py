"""At 100%, eToro's free cash decides alone (2026-11-01).

The operator, 2026-10-31, answered "3 oui" to "at a 100% account pledge
ceiling, eToro's free cash decides alone", and set MAX ACCOUNT PLEDGED to
100% ("put max allocation to 100% too please"). Below 100% every eToro
order is refused when (used margin + margin pledged since the reading +
this order's margin) / equity passes the ceiling. The equity is eToro's
total, open P&L included, so an account carrying open losses was refused
orders its free cash covered.

WHAT THESE TESTS CONFRONT

  * At exactly 100% the gate (AssetBot._cash_gate) computes no ratio of
    its own: an order the ratio refused and eToro's free cash covers goes,
    on the bot send and on the TAKE TRADE ticket (preview and send), and
    the ticket's room is the free cash alone.
  * At 100% an order the free cash does not cover is still refused, in the
    cash words; so is one on an account whose equity is not above zero
    (today's ratio refused it; nothing above zero takes an order).
  * Below 100% (99%) the ratio still refuses, word for word.
  * An unreadable or out-of-bounds setting still reads 50%, never 100%.
  * The cells' age, the equity's age and the world still refuse at 100%:
    data health, not the pledge limit, and the words say so.
  * A read that carried the used margin and no available cash (the
    post-order re-read, the sync) writes the cash None instead of leaving
    an older one under its new stamp, where it read as seconds old: at
    100% that cash is the gate's only money input, and the bot send and
    the ticket refuse until a read carries it (review, 2026-11-01).
  * Morgul's G6 at 100% files a margin past the equity as CRITICAL with
    nothing to stop: it never brakes, the brake armed or not, and the
    alarm chat, which carries critical findings only, still hears it
    (review, 2026-11-01: a warning there silenced that chat). Stale cells
    past it stay a warning, as below 100%; at 99% it still brakes; an
    equity not above zero still brakes at 100%.
  * The /setup/ Risk Limits card, the preflight and the council's war say
    what 100% means.

Run with:  python manage.py test tests.test_free_cash_decides_alone
"""
import html
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tests.test_morgul import (SEND, _arm, _by_subject, _Case, _check,
                               _texts)
from tests.test_morgul import _cfg as _morgul_cfg
from tests.test_morgul import _etoro as _morgul_etoro
from tests.test_ticket_checks_like_the_send import REFRESH, _LiveEtoroTicket

ALONE = "eToro's free cash decides alone"
#: The gate's words for a cash a read did not carry (review, 2026-11-01).
NO_CASH = "carried no available cash figure"


def _set(pct):
    from portfolio.risk_gate import limits_book
    book = limits_book()
    book.max_pledged_pct = pct
    book.save(update_fields=["max_pledged_pct", "updated_at"])
    return book


def _no_cash(used, total):
    """The measured nested payload (tests.test_reread_after_orders
    ._payload) with no accountAvailableCash: eToro answered the used
    margin and the total alone."""
    return {"accountCurrency": "USD",
            "accountTotals": {"accountTotalValue": total,
                              "accountTotalUsedMargin": used}}


def _read_without_the_cash(case, acct, *, used, total, sync=False):
    """The post-order re-read (tasks.refresh_etoro_cells) or, with `sync`,
    one pass of the eToro sync, through the REAL adapter over a fake wire
    whose aggregate payload carries no available cash. The read is
    stamped now; `acct` comes back as stored."""
    from bot_program.tasks import refresh_etoro_cells
    from tests.test_etoro_client import _client
    from tests.test_reread_after_orders import TRADER, _components, _sync
    _components()
    routes = [("GET", "aggregate-portfolio", 200, _no_cash(used, total))]
    if sync:
        routes.append(("GET", "portfolio", 200,
                       {"clientPortfolio": {"positions": []}}))
    t, _ = _client(routes, env="demo")
    if sync:
        out = _sync(t)
        case.assertEqual(out["stored"], 1, out)
    else:
        with mock.patch(TRADER, return_value=t):
            out = refresh_etoro_cells(acct.pk, why="test")
        case.assertTrue(out["read"], out)
    acct.refresh_from_db()
    return acct


class TheReaderTests(TestCase):
    """base.free_cash_decides_alone: exactly 100 inside its bounds, and
    nothing else, lets the free cash decide."""

    def test_exactly_one_hundred_lets_the_free_cash_decide(self):
        from bot_program.asset_engine.base import (free_cash_decides_alone,
                                                   pledged_ceiling)
        _set(100)
        self.assertEqual(pledged_ceiling(), 1.0)
        self.assertTrue(free_cash_decides_alone())
        self.assertTrue(free_cash_decides_alone(1.0))
        self.assertFalse(free_cash_decides_alone(0.99))
        self.assertFalse(free_cash_decides_alone("x"))

    def test_below_one_hundred_the_ratio_judges(self):
        from bot_program.asset_engine.base import free_cash_decides_alone
        for pct in (99, 99.99, 80, 50, 10):
            _set(pct)
            self.assertFalse(free_cash_decides_alone(), pct)

    def test_unreadable_or_out_of_bounds_reads_fifty_never_100(self):
        from bot_program.asset_engine.base import (free_cash_decides_alone,
                                                   pledged_ceiling)
        with mock.patch("portfolio.risk_gate.limits_book",
                        side_effect=RuntimeError("db gone")), \
                self.assertLogs("bot_program.asset_engine.base", "WARNING"):
            self.assertEqual(pledged_ceiling(), 0.5)
            self.assertFalse(free_cash_decides_alone())
        for pct in (100.1, 150, 1000, 5, -100):
            _set(pct)
            with self.assertLogs("bot_program.asset_engine.base", "WARNING"):
                self.assertEqual(pledged_ceiling(), 0.5, pct)
            with self.assertLogs("bot_program.asset_engine.base", "WARNING"):
                self.assertFalse(free_cash_decides_alone(), pct)


class _BotSend(TestCase):
    """execute_entry on a LIVE stock config through the REAL EtoroTrader
    over a fake wire: tests.test_etoro_leverage's own harness (2x)."""

    def setUp(self):
        from tests.test_etoro_client import _clear_eligibility
        from tests.test_etoro_leverage import _book, _switch
        from tests.test_execution_trust import _cfg as _live_cfg
        from tests.test_execution_trust import _instrument, _signal, _user
        self.user = _user("alone_bot")
        self.cfg = _live_cfg(self.user, name="ALONE")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {"leverage": 2}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="alone_rule")
        _book(self.user)
        _switch(True)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _cand(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_desk_seam import _client as _mock_client
        from tests.test_etoro_leverage import ROUTER
        self.bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = self.bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        self.assertGreater(cand.qty_default, 0)
        # the margin at 2x at the proposal's price (the send's own price
        # is the venue's within a tick of it)
        self.need = float(cand.qty_default) * 100.0 / 2.0
        return cand

    def _cells(self, *, cash, used, equity=100000, **kw):
        from tests.test_etoro_leverage import _account
        return _account(self.user, cash=cash, used=used, equity=equity, **kw)

    def _send(self, cand):
        from tests.test_etoro_leverage import ROUTER, _etoro, _order_posts
        t, fake = _etoro()
        self.t = t
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            res = self.bot.execute_entry(cand)
        return res, _order_posts(fake)

    def _skip_note(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)["AAPL"]

    def _gate(self, cand):
        from tests.test_etoro_leverage import _etoro
        t, _ = _etoro()
        return self.bot._cash_gate(t, "AAPL", qty=float(cand.qty_default),
                                   price=100.0, leverage=2)

    def _over_the_ratio(self, cand, cash_times=3.0):
        """The account just under the whole of its equity, so this order
        takes it past 100% of it; eToro's free cash `cash_times` the
        order's margin."""
        return self._cells(cash=round(self.need * cash_times, 2),
                           used=round(100000 - self.need / 2, 2))


class TheBotSendTests(_BotSend):

    def test_at_100_an_order_the_ratio_refused_and_the_cash_covers_goes(self):
        from bot_program.models import AssetBotTrade
        _set(100)
        cand = self._cand()
        self._over_the_ratio(cand)
        gate = self._gate(cand)
        self.assertEqual(gate["refusal"], "")
        self.assertIs(gate["cash_alone"], True)
        self.assertIsNone(gate["after"], "no ratio is computed at 100%")
        self.assertEqual(gate["ceiling"], 1.0)
        # the room is the free cash alone, not what a ratio would leave
        self.assertAlmostEqual(gate["room"], gate["free"], places=6)
        self.assertAlmostEqual(gate["free"], round(self.need * 3.0, 2),
                               places=6)
        res, posts = self._send(cand)
        self.assertIsNotNone(res, None if res is not None
                             else self._skip_note())
        self.assertEqual(len(posts), 1)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(trade.metadata["broker"], "etoro")

    def test_at_100_an_order_the_free_cash_does_not_cover_is_refused(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        _set(100)
        cand = self._cand()
        self._over_the_ratio(cand, cash_times=0.5)
        gate = self._gate(cand)
        self.assertIs(gate["cash_alone"], True)
        self.assertIn("of margin and", gate["refusal"])
        res, posts = self._send(cand)
        self.assertIsNone(res)
        self.assertEqual(posts, [], "an order left the box")
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        note = self._skip_note()
        self.assertEqual(note["code"], skips.LEVERAGE_REFUSED)
        self.assertIn("of margin and", note["detail"])
        self.assertIn("is free", note["detail"])
        self.assertNotIn("pledged after", note["detail"])

    def test_at_99_the_ratio_still_refuses_the_same_order(self):
        from bot_program.asset_engine import skips
        _set(99)
        cand = self._cand()
        self._over_the_ratio(cand)
        gate = self._gate(cand)
        self.assertIs(gate["cash_alone"], False)
        self.assertIn("the ceiling is 99%", gate["refusal"])
        self.assertGreater(gate["after"], 0.99)
        res, posts = self._send(cand)
        self.assertIsNone(res)
        self.assertEqual(posts, [])
        note = self._skip_note()
        self.assertEqual(note["code"], skips.LEVERAGE_REFUSED)
        self.assertIn("pledged after", note["detail"])
        self.assertIn("the ceiling is 99%", note["detail"])

    def test_an_unreadable_or_out_of_bounds_setting_still_reads_50(self):
        """The order the 100% test sends, at a 60% used account: 50%
        refuses it, so the fallback never reads as 100%."""
        cand = self._cand()
        self._cells(cash=10 ** 6, used=60000)
        with mock.patch("portfolio.risk_gate.limits_book",
                        side_effect=RuntimeError("db gone")), \
                self.assertLogs("bot_program.asset_engine.base", "WARNING"):
            gate = self._gate(cand)
        self.assertIs(gate["cash_alone"], False)
        self.assertIn("the ceiling is 50%", gate["refusal"])
        _set(100.1)
        with self.assertLogs("bot_program.asset_engine.base", "WARNING"):
            res, posts = self._send(cand)
        self.assertIsNone(res)
        self.assertEqual(posts, [])
        self.assertIn("the ceiling is 50%", self._skip_note()["detail"])

    def test_at_100_the_ages_and_the_world_still_refuse_as_data_health(self):
        """The cells' age, the equity's age (only the sync writes it: an
        equity over an hour old says the sync has stopped) and the world
        are data health, not the pledge limit: they refuse at 100% too,
        and an undated equity no longer blames the pledge ceiling."""
        from bot_program.models import EtoroAccount
        _set(100)
        cand = self._cand()
        acct = self._over_the_ratio(cand)
        now = timezone.now()
        EtoroAccount.objects.filter(pk=acct.pk).update(
            last_equity_at=now - timedelta(hours=2))
        self.assertIn("equity reading 2.0h old", self._gate(cand)["refusal"])
        EtoroAccount.objects.filter(pk=acct.pk).update(
            last_equity_at=now, last_margin_at=now - timedelta(hours=2))
        self.assertIn("cash reading 2.0h old", self._gate(cand)["refusal"])
        EtoroAccount.objects.filter(pk=acct.pk).update(
            last_margin_at=now, last_margin_world="live")
        self.assertIn("cash read in the live world",
                      self._gate(cand)["refusal"])
        EtoroAccount.objects.filter(pk=acct.pk).update(
            last_margin_world="demo", last_equity_at=None)
        undated = self._gate(cand)["refusal"]
        self.assertIn("equity carries no reading time", undated)
        self.assertIn("refused", undated)
        self.assertIn("data health, not MAX ACCOUNT PLEDGED", undated)
        self.assertNotIn("the pledge ceiling is not judged", undated)
        res, posts = self._send(cand)
        self.assertIsNone(res)
        self.assertEqual(posts, [])
        self.assertIn("equity carries no reading time",
                      self._skip_note()["detail"])

    def test_below_100_an_undated_equity_keeps_its_words(self):
        from bot_program.models import EtoroAccount
        _set(99)
        cand = self._cand()
        acct = self._over_the_ratio(cand)
        EtoroAccount.objects.filter(pk=acct.pk).update(last_equity_at=None)
        refusal = self._gate(cand)["refusal"]
        self.assertIn("the pledge ceiling is not judged against an equity "
                      "of unknown age", refusal)

    def test_at_100_an_equity_not_above_zero_is_still_refused(self):
        """Today's ratio refused every order on an equity at or under zero
        (it divides by it). At 100% no ratio is computed, and an account
        with nothing above zero still takes no order, whatever its cash
        cell says; the ticket's room is nothing."""
        _set(100)
        cand = self._cand()
        self._cells(cash=round(self.need * 3.0, 2), used=0, equity=0)
        gate = self._gate(cand)
        self.assertIs(gate["cash_alone"], True)
        self.assertIn("not above zero", gate["refusal"])
        self.assertEqual(gate["room"], 0.0)
        res, posts = self._send(cand)
        self.assertIsNone(res)
        self.assertEqual(posts, [])
        self.assertIn("not above zero", self._skip_note()["detail"])

    def test_at_100_a_reread_without_the_cash_refuses_the_send(self):
        """Review, 2026-11-01. A read that carried the used margin and no
        available cash restamped the cells and kept the older cash, which
        the gate then read as seconds old. Below 100% the ratio, fed the
        fresh used margin, refused this order; at 100% the cash is the
        gate's only money input, and the order went on an older cash of
        three margins that eToro's latest read did not carry. The cash a
        read did not carry is now written None, and every eToro order is
        refused until a read carries it again, at 99% as at 100% (data
        health, not the pledge limit)."""
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        _set(100)
        cand = self._cand()
        # ten minutes ago: three margins of this order free, nothing used
        acct = self._cells(cash=round(self.need * 3.0, 2), used=0,
                           age_s=600)
        t0 = timezone.now()
        used = round(100000 - self.need / 2, 2)
        acct = _read_without_the_cash(self, acct, used=used, total=100000.0)
        self.assertIsNone(acct.last_available_cash)
        self.assertAlmostEqual(float(acct.last_used_margin), used, places=2)
        self.assertGreaterEqual(acct.last_margin_at, t0)
        gate = self._gate(cand)
        self.assertIn(NO_CASH, gate["refusal"])
        self.assertIn("refused until a reading carries one", gate["refusal"])
        self.assertNotIn("never been stored", gate["refusal"])
        self.assertIsNone(gate["free"])
        self.assertIsNone(gate["room"])
        res, posts = self._send(cand)
        self.assertIsNone(res)
        self.assertEqual(posts, [], "an order left the box")
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        note = self._skip_note()
        self.assertEqual(note["code"], skips.LEVERAGE_REFUSED)
        self.assertIn(NO_CASH, note["detail"])
        _set(99)
        self.assertIn(NO_CASH, self._gate(cand)["refusal"])

    def test_at_100_a_sync_without_the_cash_refuses_the_send_too(self):
        """The sync writes the cells through the same function: one pass
        whose payload carries no available cash leaves none either."""
        _set(100)
        cand = self._cand()
        acct = self._cells(cash=round(self.need * 3.0, 2), used=0,
                           age_s=600)
        acct = _read_without_the_cash(
            self, acct, used=round(100000 - self.need / 2, 2),
            total=100000.0, sync=True)
        self.assertIsNone(acct.last_available_cash)
        self.assertIn(NO_CASH, self._gate(cand)["refusal"])
        res, posts = self._send(cand)
        self.assertIsNone(res)
        self.assertEqual(posts, [], "an order left the box")
        self.assertIn(NO_CASH, self._skip_note()["detail"])


class TheTicketTests(_LiveEtoroTicket):
    """The TAKE TRADE preview asks the send's own judgement
    (_cash_gate_advisory) and the send asks it again before the order."""

    username = "alone_ticket"

    def _execute(self, t, **mo):
        from bot_program.manual_trade import execute_take_trade
        from tests.test_take_trade_live import ROUTER, _signal
        with mock.patch.object(t, "market_order", **mo) as spy, \
                mock.patch(ROUTER, return_value=t), mock.patch(REFRESH):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        return out, spy

    def test_at_100_the_preview_lets_the_free_cash_decide(self):
        """5,000 free, 9,600 used of a 10,000 equity: the default BTC
        ticket (about 1,667 of margin at 1x) takes the account to about
        113% of its equity. At 100% eToro's free cash covers it: the
        ticket is takeable, and its size control stops at the 5,000 free,
        not at what a ratio would leave (400)."""
        _set(100)
        self._cells(cash=5000, used=9600, equity=10000, age_s=30)
        t, _ = self._etoro()
        with mock.patch(REFRESH):
            out = self._preview(t)
        self.assertNotIn("error", out, out)
        cg = out["cash_gate"]
        self.assertTrue(cg["asked"])
        self.assertTrue(cg["ok"], cg["reason"])
        self.assertEqual(cg["reason"], "")
        self.assertIs(cg["cash_alone"], True)
        self.assertIsNone(cg["after"])
        self.assertEqual(cg["free"], 5000.0)
        self.assertEqual(cg["room"], 5000.0)
        self.assertLessEqual(cg["max_qty"] * 60000.0, 5000.0 + 1e-6)
        self.assertGreater(cg["max_qty"], out["qty"])
        # the default ticket really is past the whole equity
        self.assertGreater((9600 + out["qty"] * 60000.0) / 10000, 1.0)

    def test_at_100_the_send_goes_where_the_ratio_refused(self):
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import _filled_response
        _set(100)
        self._cells(cash=5000, used=9600, equity=10000, age_s=30)
        t, _ = self._etoro()
        out, mo = self._execute(t, return_value=_filled_response(
            positionId="3603281458"))
        self.assertTrue(out.get("ok"), out)
        mo.assert_called_once()
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(trade.metadata["broker"], "etoro")

    def test_at_100_a_ticket_the_free_cash_does_not_cover_is_refused(self):
        _set(100)
        self._cells(cash=1000, used=9600, equity=10000, age_s=30)
        t, _ = self._etoro()
        with mock.patch(REFRESH):
            cg = self._preview(t)["cash_gate"]
        self.assertIs(cg["cash_alone"], True)
        self.assertFalse(cg["ok"])
        self.assertIn("1,000.00 is free", cg["reason"])
        self.assertIn("refused before the venue refuses it", cg["reason"])
        self.assertNotIn("pledged after", cg["reason"])
        self.assertEqual(cg["room"], 1000.0)
        t, _ = self._etoro()
        out, spy = self._execute(t, wraps=t.market_order)
        self.assertIn("1,000.00 is free", out.get("error", ""))
        self.assertTrue(out["error"].endswith("nothing was sent"),
                        out["error"])
        spy.assert_not_called()

    def test_at_100_a_ticket_after_a_read_without_the_cash_is_refused(self):
        """5,000 free ten minutes ago, then a re-read that answered 9,600
        used of a 10,000 equity and no cash (review, 2026-11-01). The older
        5,000 stayed under the new stamp: at 100% the ticket was takeable
        and its size control opened to it. Now the preview and the send
        refuse in the gate's words, the re-read they ask is said as what
        it is, and nothing is sent."""
        _set(100)
        acct = self._cells(cash=5000, used=0, equity=10000, age_s=600)
        acct = _read_without_the_cash(self, acct, used=9600.0,
                                      total=10000.0)
        self.assertIsNone(acct.last_available_cash)
        t, _ = self._etoro()
        with mock.patch(REFRESH):
            cg = self._preview(t)["cash_gate"]
        self.assertTrue(cg["asked"])
        self.assertFalse(cg["ok"])
        self.assertIn(NO_CASH, cg["reason"])
        self.assertIsNone(cg["room"])
        self.assertIsNone(cg["max_qty"])
        t, _ = self._etoro()
        out, spy = self._execute(t, wraps=t.market_order)
        error = out.get("error", "")
        self.assertIn(NO_CASH, error)
        self.assertIn("a fresh read of the eToro account was asked", error)
        self.assertNotIn("never stored", error)
        self.assertTrue(error.endswith("nothing was sent"), error)
        spy.assert_not_called()

    def test_at_99_the_ratio_still_refuses_the_ticket(self):
        _set(99)
        self._cells(cash=5000, used=9600, equity=10000, age_s=30)
        t, _ = self._etoro()
        with mock.patch(REFRESH):
            cg = self._preview(t)["cash_gate"]
        self.assertIs(cg["cash_alone"], False)
        self.assertFalse(cg["ok"])
        self.assertIn("pledged after", cg["reason"])
        self.assertIn("the ceiling is 99%", cg["reason"])
        # min(5,000 free; 99% of 10,000 - 9,600 used = 300)
        self.assertAlmostEqual(cg["room"], 300.0, places=6)
        t, _ = self._etoro()
        out, spy = self._execute(t, wraps=t.market_order)
        self.assertIn("the ceiling is 99%", out.get("error", ""))
        spy.assert_not_called()


class MorgulAtOneHundredTests(_Case):
    """G6 reads the gate's own ceiling: at 100% the gate judges no ratio,
    so a brake on the ratio would stop every live bot the moment an order
    the gate allowed filled. A margin past the whole equity is still
    CRITICAL there, with nothing to stop (review, 2026-11-01): the alarm
    chat carries critical findings only, and a warning left it silent
    where it had rung since 2026-10-05."""

    NO_BRAKE = f"No brake: at 100%, {ALONE} (MAX ACCOUNT PLEDGED on /setup/)"

    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.cfg = _morgul_cfg(self.user, "Stocks live", "stock",
                               mode="live")

    def _acct(self, used, equity="100"):
        # one sync's reading: the equity and the cells under one stamp
        return _morgul_etoro(
            self.user, demo=False, is_primary_for_stocks=True,
            last_equity=Decimal(equity), last_equity_currency="USD",
            last_equity_at=self.now - timedelta(minutes=5),
            last_used_margin=Decimal(str(used)),
            last_margin_at=self.now - timedelta(minutes=5),
            last_margin_world="live")

    def test_at_100_past_the_equity_is_critical_and_never_brakes(self):
        _set(100)
        acct = self._acct(101)
        f = _by_subject(_check("margin", self.now)[1])[
            f"account:{acct.pk}:pledged"]
        self.assertEqual(f.severity, "critical")
        self.assertFalse(f.brakes)
        self.assertEqual(f.configs, [])
        self.assertEqual(f.title,
                         "Morgul — the margin used is past the equity")
        self.assertIn("Pledged: 101.0% of equity, past the whole account",
                      f.facts)
        self.assertIn(self.NO_BRAKE, f.facts)
        self.assertEqual([x for x in f.facts if "A warning only" in x], [])

    def test_at_100_the_armed_brake_stops_nothing(self):
        _set(100)
        _arm()
        self._acct(130)
        from bot_program import morgul
        with mock.patch(SEND, return_value=True) as send:
            morgul.cycle(now=self.now, send=True,
                         guards=[morgul.GUARD["margin"]])
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.enabled)
        # the chat's text is HTML: its apostrophes are escaped
        text = html.unescape("\n".join(_texts(send)))
        self.assertIn("Severity: critical", text)
        self.assertIn(self.NO_BRAKE, text)
        self.assertIn("the margin used is past the equity", text)
        self.assertNotIn("Stopped:", text)
        self.assertNotIn("Would stop", text)

    def test_at_100_the_alarm_chat_still_hears_it(self):
        """Morgul's beat as tasks.run_morgul_guards runs it (cycle, then
        alarm.relay_morgul), the alarm bot on: the chat hears the title
        and the label, never an amount, and no brake, armed as it is."""
        import os

        from bot_program import alarm, morgul
        from tests.test_alarm_bot import ENV, MONEY, POST, _ok
        from tests.test_alarm_bot import _texts as _alarm_texts
        from tests.test_morgul import _component
        _set(100)
        _arm()
        acct = self._acct(130)
        _component(alarm.COMPONENT_KEY)
        with mock.patch.dict(os.environ, ENV), \
                mock.patch(SEND, return_value=True), \
                mock.patch(POST, side_effect=_ok) as post:
            report = morgul.cycle(now=self.now, send=True,
                                  guards=[morgul.GUARD["margin"]])
            out = alarm.relay_morgul(report)
        said = [html.unescape(t) for t in _alarm_texts(post)]
        self.assertEqual(out.get("sent"), 1, out)
        self.assertEqual(len(said), 1, said)
        self.assertIn("Sauron alarm — the margin used is past the equity",
                      said[0])
        self.assertIn(f"eToro live account ({acct.label})", said[0])
        self.assertNotIn("the brake stopped", said[0])
        self.assertIsNone(MONEY.search(said[0]), said[0])
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.enabled)

    def test_at_100_stale_cells_past_the_equity_stay_a_warning(self):
        """As below 100%: cells the gate would not trust are a warning
        that says why, which the alarm chat does not carry."""
        from bot_program import alarm, morgul
        _set(100)
        acct = self._acct(130)
        acct.last_margin_at = self.now - timedelta(hours=2)
        acct.save(update_fields=["last_margin_at"])
        ctx, found = _check("margin", self.now)
        f = _by_subject(found)[f"account:{acct.pk}:pledged"]
        self.assertEqual(f.severity, "warning")
        self.assertFalse(f.brakes)
        self.assertEqual(f.configs, [])
        self.assertIn("A warning only, and no brake: read 2 h ago", f.facts)
        self.assertIn(self.NO_BRAKE, f.facts)
        report = morgul.Report(ctx, [morgul.GUARD["margin"]], found, [],
                               {"status": "success"}, [], {})
        self.assertEqual(alarm.morgul_alarms(report), [])

    def test_at_99_past_the_alarm_still_brakes(self):
        _set(99)
        acct = self._acct(101)
        f = _by_subject(_check("margin", self.now)[1])[
            f"account:{acct.pk}:pledged"]
        self.assertEqual(f.severity, "critical")
        self.assertTrue(f.brakes)
        self.assertEqual(f.configs, [self.cfg.pk])
        self.assertIn("Pledged: 101.0% of equity; the limit is 99.0%, the "
                      "alarm 100.0%", f.facts)
        self.assertEqual(f.title,
                         "Morgul — the margin pledged is past the limit")

    def test_at_100_an_equity_not_above_zero_still_brakes(self):
        """Not a ratio: an account with nothing above zero, which the gate
        refuses at 100% too."""
        _set(100)
        acct = self._acct(10, equity="0")
        f = _by_subject(_check("margin", self.now)[1])[
            f"account:{acct.pk}:pledged"]
        self.assertEqual(f.severity, "critical")
        self.assertTrue(f.brakes)
        self.assertIn("Pledged: all of it, the equity is not above zero",
                      f.facts)

    def test_at_100_under_the_equity_is_quiet(self):
        _set(100)
        self._acct(99)
        self.assertEqual(_check("margin", self.now)[1], [])


class TheCardSaysItTests(TestCase):

    def test_the_risk_limits_card_says_what_100_means(self):
        user = get_user_model().objects.create_user("alone_ui",
                                                    password="x")
        self.client.force_login(user)
        _set(100)
        r = self.client.get("/setup/")
        self.assertContains(r, 'name="max_pledged"')
        self.assertContains(r, f"at 100%, {ALONE}")
        self.assertContains(r, "one gap can take the whole account")
        # the margin watchdog does not go quiet at 100% (review,
        # 2026-11-01): critical, with nothing to stop
        self.assertContains(r, "The margin watchdog still raises a critical "
                               "alarm")
        self.assertContains(r, "once the margin used passes the equity, and "
                               "stops no bot.")
        self.assertNotContains(r, "the margin watchdog warns")


class ThePreflightSaysItTests(TestCase):

    def _run(self):
        from tests.test_pools_are_shares_of_the_account import (_acct, _cfg,
                                                                _user)
        from tests.test_shared_capital import _switch
        _switch(True)
        u = _user()
        _acct(u)
        _cfg(u, name="a", tracks=True, capital="500")
        _cfg(u, name="b", tracks=True, capital="500")
        out = StringIO()
        call_command("preflight_live", stdout=out)
        return out.getvalue()

    def test_at_100_what_binds_is_the_free_cash(self):
        _set(100)
        self.assertIn(f"MAX ACCOUNT PLEDGED 100% ({ALONE}), the book's daily "
                      f"loss", self._run())

    def test_below_100_the_line_is_as_before(self):
        _set(80)
        out = self._run()
        self.assertIn("MAX ACCOUNT PLEDGED 80%, the book's daily loss", out)
        self.assertNotIn(ALONE, out)


class TheWarSaysItTests(TestCase):
    """THE WAR, the council's brief of the limits (percent and R only)."""

    def _war(self):
        from ai_agents.agents.council import war_text
        user = get_user_model().objects.create_user("alone_war",
                                                    password="x")
        session = SimpleNamespace(
            user=user, origin="bot", symbol="AAPL", asset_class="stock",
            side="BUY", qty=1, entry=100, stop=98, value_per_unit=1.0,
            config_id=None, config=None)
        return war_text(session)

    def test_at_100_the_pledge_cap_line_says_the_free_cash_decides(self):
        _set(100)
        self.assertIn(f"  pledge cap: 100% of the account (at 100%, {ALONE}: "
                      f"no ratio refuses an order); the account's current "
                      f"pledge is not read here", self._war())

    def test_below_100_the_pledge_cap_line_is_as_before(self):
        _set(80)
        war = self._war()
        self.assertIn("  pledge cap: 80% of the account; the account's "
                      "current pledge is not read here", war)
        self.assertNotIn(ALONE, war)
