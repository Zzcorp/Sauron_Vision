"""Close every position in one decision, and say honestly what happened.

Position by position is the right default and the wrong tool when the reason
to get out is the market rather than the trade: five dialogs and five PIN
entries, while the thing that made the operator want out keeps moving.

Three things this must not get wrong.

It must not be mistaken for the kill switch. `flatten_all_positions` closes
the book AND disables every bot; this closes the book and leaves the platform
running, so an armed bot can open something new on its next beat. An operator
who believes they have stopped trading and has not is worse off than one who
never pressed the button, so the dialog says it.

It must not promise what it cannot do. Legacy `portfolio.Position` rows have
no close path anywhere on this platform — the headband labels them "manual"
for exactly that reason — so they are excluded from the count and reported
separately rather than silently folded in.

And it must never report success over a partial flatten. Believing the book
is flat while three rows are still live at the broker is how a hedge becomes
a naked position.

Run with:  python manage.py test tests.test_close_all
"""
import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

HOST = "127.0.0.1"


def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst,
        defaults={"last": Decimal(str(last)), "source": "test"})
    return inst


def _cfg(user, *, mode="paper", name="book"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name=name, enabled=True,
        mode=mode, symbols=[], capital=Decimal("10000"))


def _trade(user, *, symbol="BTCUSD", paper=True, mode="paper", qty="0.5",
           entry=60000, status="OPEN", cfg=None):
    from bot_program.models import AssetBotTrade
    _quote(symbol, entry)
    cfg = cfg or _cfg(user, mode=mode, name=f"cfg-{symbol}-{mode}")
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="crypto", symbol=symbol, side="BUY",
        qty=Decimal(qty), entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(entry * 0.98)),
        take_profit=Decimal(str(entry * 1.04)),
        status=status, paper=paper,
        metadata={"initial_stop_loss": entry * 0.98})


class PreviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ca_u", password="x")
        self.client.force_login(self.user)

    def _preview(self):
        resp = self.client.post("/positions/close-all/preview/",
                                data="{}", content_type="application/json",
                                HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return json.loads(resp.content)

    def test_an_empty_book_counts_nothing(self):
        out = self._preview()
        self.assertEqual(out["count"], 0)

    def test_it_counts_every_open_position(self):
        _trade(self.user, symbol="BTCUSD")
        _trade(self.user, symbol="ETHUSD", entry=3000)
        self.assertEqual(self._preview()["count"], 2)

    def test_a_close_pending_row_is_still_open_and_still_counted(self):
        """The broker refused a close; the position is live there."""
        _trade(self.user, status="CLOSE_PENDING")
        out = self._preview()
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["pending"], 1)

    def test_a_closed_row_is_not_counted(self):
        _trade(self.user, status="CLOSED")
        self.assertEqual(self._preview()["count"], 0)

    def test_another_users_positions_are_not_counted(self):
        theirs = get_user_model().objects.create_user("ca_other", password="x")
        _trade(theirs)
        self.assertEqual(self._preview()["count"], 0)

    def test_the_live_and_paper_split_is_reported(self):
        _trade(self.user, symbol="BTCUSD", paper=True)
        _trade(self.user, symbol="ETHUSD", entry=3000, paper=False, mode="live")
        out = self._preview()
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["live"], 1)
        self.assertEqual(out["paper"], 1)

    def test_any_live_position_arms_the_pin_for_the_whole_set(self):
        """Splitting the run into a PIN-less paper pass and a gated live one
        would close half the book and then stop to ask a question."""
        _trade(self.user, symbol="BTCUSD", paper=True)
        self.assertFalse(self._preview()["needs_pin"])
        _trade(self.user, symbol="ETHUSD", entry=3000, paper=False, mode="live")
        self.assertTrue(self._preview()["needs_pin"])

    def test_one_unmeasured_row_makes_the_whole_total_unmeasured(self):
        """Summing the rest and printing it as the whole understates what
        the operator is about to realise."""
        _trade(self.user, symbol="BTCUSD")
        _trade(self.user, symbol="NOQUOTE", entry=100, status="CLOSE_PENDING")
        self.assertIsNone(self._preview()["pnl"])

    def test_legacy_rows_are_reported_but_never_counted_as_closable(self):
        """Nothing on this platform can close one, so counting it here
        would promise something this endpoint cannot do."""
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        from django.utils import timezone
        book = get_or_create_default_portfolio(user=self.user)
        Position.objects.create(
            portfolio=book, instrument=_instrument("AAPL", "stock"),
            direction="long", quantity=Decimal("2"),
            entry_price=Decimal("100"), current_price=Decimal("100"),
            opened_at=timezone.now())
        out = self._preview()
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["unclosable"], 1)

    def test_a_get_is_refused(self):
        resp = self.client.get("/positions/close-all/preview/", HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 405)

    def test_it_needs_a_login(self):
        self.client.logout()
        resp = self.client.post("/positions/close-all/preview/",
                                data="{}", content_type="application/json",
                                HTTP_HOST=HOST)
        self.assertIn(resp.status_code, (302, 403))


class ExecuteTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ca_x", password="x")
        self.client.force_login(self.user)

    def _close_all(self, pin=""):
        resp = self.client.post(
            "/positions/close-all/", data=json.dumps({"pin": pin}),
            content_type="application/json", HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return json.loads(resp.content)

    def test_it_closes_every_paper_position(self):
        from bot_program.models import AssetBotTrade
        _trade(self.user, symbol="BTCUSD")
        _trade(self.user, symbol="ETHUSD", entry=3000)
        out = self._close_all()
        self.assertEqual(out["n_closed"], 2, out)
        self.assertEqual(out["n_failed"], 0, out)
        self.assertTrue(out["flat"])
        self.assertFalse(
            AssetBotTrade.objects.filter(config__user=self.user,
                                         status="OPEN").exists())

    def test_it_leaves_another_users_book_alone(self):
        from bot_program.models import AssetBotTrade
        theirs = get_user_model().objects.create_user("ca_them", password="x")
        their_trade = _trade(theirs, symbol="ETHUSD", entry=3000)
        _trade(self.user, symbol="BTCUSD")
        self._close_all()
        their_trade.refresh_from_db()
        self.assertEqual(their_trade.status, "OPEN")

    def test_a_live_position_without_the_pin_is_refused_and_reported(self):
        """Refused, not silently skipped — and the book is NOT flat."""
        _trade(self.user, symbol="BTCUSD", paper=False, mode="live")
        out = self._close_all(pin="")
        self.assertEqual(out["n_closed"], 0, out)
        self.assertEqual(out["n_failed"], 1, out)
        self.assertFalse(out["flat"])

    def test_a_partial_flatten_never_reports_flat(self):
        """The outcome that matters most: some closed, some still live."""
        _trade(self.user, symbol="BTCUSD")
        _trade(self.user, symbol="ETHUSD", entry=3000, paper=False, mode="live")
        out = self._close_all(pin="")
        self.assertEqual(out["n_closed"], 1, out)
        self.assertEqual(out["n_failed"], 1, out)
        self.assertFalse(out["flat"])
        self.assertTrue(out["failed"][0]["symbol"])

    def test_an_unclosable_legacy_row_keeps_the_book_from_being_flat(self):
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        from django.utils import timezone
        book = get_or_create_default_portfolio(user=self.user)
        Position.objects.create(
            portfolio=book, instrument=_instrument("AAPL", "stock"),
            direction="long", quantity=Decimal("2"),
            entry_price=Decimal("100"), current_price=Decimal("100"),
            opened_at=timezone.now())
        _trade(self.user, symbol="BTCUSD")
        out = self._close_all()
        self.assertEqual(out["n_closed"], 1)
        self.assertFalse(out["flat"], "a row nothing can close is not flat")
        self.assertEqual(out["unclosable"], 1)

    def test_an_empty_book_closes_nothing_and_does_not_error(self):
        out = self._close_all()
        self.assertEqual(out["n_closed"], 0)
        self.assertEqual(out["n_failed"], 0)

    def test_a_non_object_body_is_refused(self):
        resp = self.client.post("/positions/close-all/", data="[]",
                                content_type="application/json", HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 400)

    def test_a_get_is_refused(self):
        resp = self.client.get("/positions/close-all/", HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 405)


class TheButtonTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for d in settings.TEMPLATES[0]["DIRS"]:
            path = Path(d) / "dashboard" / "positions_list.html"
            if path.exists():
                cls.html = path.read_text(encoding="utf-8")
                return
        raise AssertionError("positions_list.html not found")

    def test_the_page_has_a_close_all_button(self):
        self.assertIn('id="svCloseAll"', self.html)

    def test_it_is_only_rendered_when_something_is_open(self):
        """A button that can only report "nothing to do" is noise."""
        idx = self.html.find('id="svCloseAll"')
        self.assertIn("{% if positions %}", self.html[max(0, idx - 400):idx])

    def test_it_confirms_before_doing_anything(self):
        script = self.html.split('id="svCloseAll"', 1)[1]
        self.assertIn("SV.overlay.confirm", script)

    def test_it_previews_before_it_confirms(self):
        """The dialog states counts and money, so it has to ask the server
        first rather than guessing from the rendered rows."""
        script = self.html.split("svCloseAll", 1)[1]
        preview_at = script.find("close-all/preview/")
        confirm_at = script.find("SV.overlay.confirm")
        self.assertGreater(preview_at, -1)
        self.assertGreater(confirm_at, preview_at)

    def test_the_dialog_says_bots_stay_armed(self):
        """The difference between this and the kill switch, in the one
        place where confusing them costs money."""
        script = self.html.split("svCloseAll", 1)[1]
        dialog = script[script.find("SV.overlay.confirm"):][:2000]
        self.assertIn("armed", dialog)

    def test_the_pin_is_demanded_only_when_the_set_holds_a_live_row(self):
        script = self.html.split("svCloseAll", 1)[1]
        self.assertIn("needs_pin", script)
        self.assertIn("Trading PIN", script)

    def test_an_unmeasured_total_renders_a_dash_and_not_a_zero(self):
        script = self.html.split("svCloseAll", 1)[1]
        self.assertIn("—", script.split("Realises", 1)[1][:200])

    def test_it_does_not_reload_over_a_partial_flatten(self):
        """A reload would re-render the rows that did NOT close and hide the
        failures behind them."""
        script = self.html.split("svCloseAll", 1)[1]
        reload_at = script.find("location.reload")
        self.assertGreater(reload_at, -1)
        self.assertIn("if (flat)", script[max(0, reload_at - 200):reload_at])


class FlatIsMeasuredNotDeducedTests(TestCase):
    """"Every close returned ok" is not the same claim as "nothing is open".

    A row can leave the loop in a state neither branch saw — abandoned after
    its retries, or reopened by a bot on its beat while the run was in
    flight. `flat` is the one field an operator acts on without reading
    further, so it is re-read from the book rather than inferred.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user("ca_f", password="x")
        self.client.force_login(self.user)

    def _close_all(self):
        resp = self.client.post("/positions/close-all/", data="{}",
                                content_type="application/json", HTTP_HOST=HOST)
        return json.loads(resp.content)

    def test_the_remainder_is_reported_as_a_count(self):
        _trade(self.user, symbol="BTCUSD")
        out = self._close_all()
        self.assertIn("still_open", out)
        self.assertEqual(out["still_open"], 0)
        self.assertTrue(out["flat"])

    def test_a_row_that_survives_the_run_is_counted_and_denies_flat(self):
        """The abandoned-close case, simulated by a row the loop cannot
        close: it is still OPEN when the book is re-read."""
        from unittest.mock import patch
        _trade(self.user, symbol="BTCUSD")
        with patch("bot_program.manual_close.execute_close",
                   return_value={"error": "broker refused"}):
            out = self._close_all()
        self.assertEqual(out["n_failed"], 1)
        self.assertEqual(out["still_open"], 1)
        self.assertFalse(out["flat"])

    def test_flat_and_unclosable_are_read_at_one_instant(self):
        """Two separate reads would describe two different moments."""
        import inspect
        from dashboard import views_close
        src = inspect.getsource(views_close.close_all_execute)
        self.assertEqual(src.count("_unclosable_count(request.user)"), 1)


class TheFetchChainsCannotStrandTheButtonTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for d in settings.TEMPLATES[0]["DIRS"]:
            path = Path(d) / "dashboard" / "positions_list.html"
            if path.exists():
                cls.js = path.read_text(encoding="utf-8").split("svCloseAll", 1)[1]
                return
        raise AssertionError("positions_list.html not found")

    def test_every_fetch_chain_has_a_catch(self):
        """Without one, a dropped connection leaves the button disabled at
        "Closing…" for the rest of the page's life — no retry, and no way to
        find out whether anything closed."""
        self.assertGreaterEqual(self.js.count(".catch(function"), 2)

    def test_a_lost_response_does_not_claim_nothing_was_closed(self):
        """The server commits each close as it goes, so a reply we could not
        read says nothing about what happened behind it."""
        self.assertNotIn('title: "Nothing was closed", message: res.error', self.js)
        self.assertIn("Result unknown", self.js)

    def test_the_partial_headline_names_how_many_are_still_open(self):
        self.assertIn("still_open", self.js)


class AnAbandonedCloseIsNotFlatTests(TestCase):
    """`pending_closes._give_up` flips a row to ERROR after 12 failed closes
    and never sets closed_at. The position is still open at the broker; the
    platform has only stopped firing orders at it.

    ERROR sits outside the ("OPEN", "CLOSE_PENDING") filter every open-book
    read uses, so the row is invisible to the positions page, to
    reconciliation and to the stranded-close health card. If it were also
    invisible here, pressing Close all on a book holding one would answer
    "Book is flat" over a live position nobody is watching.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user("ca_ab", password="x")
        self.client.force_login(self.user)

    def _close_all(self):
        resp = self.client.post("/positions/close-all/", data="{}",
                                content_type="application/json", HTTP_HOST=HOST)
        return json.loads(resp.content)

    def _abandoned(self):
        from bot_program.models import AssetBotTrade
        trade = _trade(self.user, symbol="BTCUSD")
        AssetBotTrade.objects.filter(pk=trade.pk).update(status="ERROR")
        return trade

    def test_an_abandoned_close_denies_flat(self):
        self._abandoned()
        out = self._close_all()
        self.assertEqual(out["abandoned"], 1)
        self.assertFalse(out["flat"], "reported flat over a live position")

    def test_it_is_reported_as_its_own_count(self):
        """Not folded into still_open: nothing is retrying these, so the
        operator has to close them at the broker themselves."""
        self._abandoned()
        out = self._close_all()
        self.assertEqual(out["still_open"], 0)
        self.assertEqual(out["abandoned"], 1)

    def test_a_row_abandoned_AND_closed_does_not_count(self):
        """closed_at set means it did eventually get closed."""
        from bot_program.models import AssetBotTrade
        from django.utils import timezone
        trade = self._abandoned()
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            closed_at=timezone.now())
        out = self._close_all()
        self.assertEqual(out["abandoned"], 0)
        self.assertTrue(out["flat"])

    def test_another_users_abandoned_close_is_not_counted(self):
        from bot_program.models import AssetBotTrade
        theirs = get_user_model().objects.create_user("ca_ab2", password="x")
        t = _trade(theirs, symbol="ETHUSD", entry=3000)
        AssetBotTrade.objects.filter(pk=t.pk).update(status="ERROR")
        out = self._close_all()
        self.assertEqual(out["abandoned"], 0)
        self.assertTrue(out["flat"])

    def test_the_dialog_names_it(self):
        from pathlib import Path as _P
        for d in settings.TEMPLATES[0]["DIRS"]:
            path = _P(d) / "dashboard" / "positions_list.html"
            if path.exists():
                js = path.read_text(encoding="utf-8").split("svCloseAll", 1)[1]
                self.assertIn("ABANDONED", js)
                self.assertIn("still open at the", js)
                return
        raise AssertionError("positions_list.html not found")
