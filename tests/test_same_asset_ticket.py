"""The same asset on the TAKE TRADE ticket: a warning naming the holder,
and a legacy row that says what it is and where it goes (2026-10-31).

The operator: "we cant open new trade on same assets". The ticket was
hard-refused when ANOTHER config (a bot) — or a legacy portfolio.Position
row — held the same symbol on the same side, with "... already on the
real-money book via <holder>". The legacy rows (the /setup/ eToro sync
button, the /setup/ 'add position' form, the chat trader) are never closed
by anything, so one forgotten row blocked a symbol and side for ever, and
the words "via portfolio position" did not say which row or where to
remove it.

WHAT THESE TESTS CONFRONT

  * The ticket warns instead of refusing, names the holder, and the live
    ticket still takes the PIN; the trade records duplicate_at_entry. The
    dialog opens on that warning and repeats it beside the PIN.
  * What stays a refusal on the ticket: the 60-second double-click window,
    the same-signal guard, and a holder the ticket did not show (a bot
    that opened the same bet between the preview and the click; the
    dialog sends back the holders it showed, by row).
  * The bots keep refusing (another config's holding, and their own
    config's: already_open).
  * Every refusal or warning that a legacy row causes names the row's
    kind, its book, the writer that can have made it, its age, and the
    page that closes it — the id and the page first, so a bot's recorded
    skip keeps them; that page closes a row with no stop or target;
    `manage.py legacy_positions` lists them all, read-only.

Run with:  python manage.py test tests.test_same_asset_ticket
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_one_bet_one_ticket import _book, _config, _instrument, _open


def _legacy(portfolio, symbol="AAPL", direction="long", days=40,
            asset_class="stock"):
    from portfolio.models import Position
    return Position.objects.create(
        portfolio=portfolio, instrument=_instrument(symbol, asset_class),
        direction=direction, quantity=Decimal("5"),
        entry_price=Decimal("200"), current_price=Decimal("200"),
        opened_at=timezone.now() - timedelta(days=days))


class _Ticket(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("sa_u", password="x")

    def setUp(self):
        from market_data.models import LiveQuote
        _book(current_value=Decimal("10000"), max_daily_loss_pct=100.0,
              max_total_exposure_pct=1000.0, max_single_position_pct=100.0,
              max_theme_legs=3)
        self.inst = _instrument("BTCUSD", "crypto", "CRYPTO")
        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("50000"), "source": "binance_public"})


class TheTicketWarnsTests(_Ticket):

    def test_the_preview_names_the_holder_and_stays_open(self):
        from bot_program.manual_trade import preview_asset_trade
        _open(_config(self.user, asset_class="crypto", name="trend"),
              "BTCUSD", rule="ema_cross", asset_class="crypto")
        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out, out)
        self.assertEqual(out["duplicate"]["holders"], ["ema_cross"])
        self.assertIn("BTCUSD long is already on the paper book via "
                      "ema_cross", out["duplicate"]["reason"])

    def test_a_clean_book_carries_a_quiet_duplicate_reading(self):
        from bot_program.manual_trade import preview_asset_trade
        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertEqual(out["duplicate"], {"ok": True, "reason": "",
                                            "holders": [], "holder_ids": [],
                                            "legacy": []})

    def test_the_trade_records_who_held_it(self):
        from bot_program.manual_trade import (execute_asset_trade,
                                              preview_asset_trade)
        from bot_program.models import AssetBotTrade
        _open(_config(self.user, asset_class="crypto", name="trend2"),
              "BTCUSD", rule="ema_cross", asset_class="crypto")
        shown = preview_asset_trade(self.user, self.inst, "BUY")["duplicate"]
        out = execute_asset_trade(self.user, self.inst, "BUY",
                                  dup_seen=shown["holder_ids"])
        self.assertTrue(out.get("ok"), out)
        meta = AssetBotTrade.objects.get(id=out["trade_id"]).metadata
        self.assertEqual(meta["duplicate_at_entry"]["holders"],
                         ["ema_cross"])

    def test_an_ordinary_ticket_keeps_its_metadata_shape(self):
        from bot_program.manual_trade import execute_asset_trade
        from bot_program.models import AssetBotTrade
        out = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertTrue(out.get("ok"), out)
        self.assertNotIn("duplicate_at_entry", AssetBotTrade.objects.get(
            id=out["trade_id"]).metadata)

    def test_the_double_click_window_still_refuses(self):
        from bot_program.manual_trade import execute_asset_trade
        first = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertTrue(first.get("ok"), first)
        again = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertIn("error", again)
        self.assertIn("treated as a double-click", again["error"])

    def test_the_same_signal_still_refuses(self):
        from bot_program.manual_trade import execute_take_trade
        from tests.test_take_trade_live import _signal
        sig = _signal(self.inst, entry=50000, stop=49200, target=51600)
        first = execute_take_trade(self.user, sig)
        self.assertTrue(first.get("ok"), first)
        again = execute_take_trade(self.user, sig)
        self.assertIn("This signal is already taken", again["error"])


class TheLiveTicketStillTakesThePinTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("sa_live",
                                                        password="x")

    def test_a_warned_live_ticket_without_the_pin_sends_nothing(self):
        from bot_program.manual_trade import execute_take_trade
        from tests.test_take_trade_live import (ROUTER, _arm_live,
                                                _components_on,
                                                _fake_live_client, _quote,
                                                _signal)
        from bot_program.manual_trade import preview_take_trade
        inst = _quote("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        holder = _config(self.user, asset_class="crypto", name="trend_live")
        row = _open(holder, "BTCUSD", rule="ema_cross", asset_class="crypto")
        row.paper = False
        row.save(update_fields=["paper"])
        fake = _fake_live_client()
        sig = _signal(inst)
        with patch(ROUTER, return_value=fake):
            shown = preview_take_trade(self.user, sig)["duplicate"]
        self.assertFalse(shown["ok"])
        self.assertEqual(shown["holder_ids"], [f"trade:{row.pk}"])
        with patch(ROUTER, return_value=fake):
            out = execute_take_trade(self.user, sig, pin_ok=False,
                                     dup_seen=shown["holder_ids"])
        self.assertIn("Enter your trading PIN", out["error"])
        fake.market_order.assert_not_called()
        with patch(ROUTER, return_value=fake):
            out = execute_take_trade(self.user, sig, pin_ok=True,
                                     dup_seen=shown["holder_ids"])
        self.assertTrue(out.get("ok"), out)
        fake.market_order.assert_called_once()

    def test_a_live_bot_opening_after_the_preview_stops_the_order(self):
        """The skeptic's live race (2026-10-31): the preview warned of
        nothing, a live bot then opened BTCUSD long, and the real-money
        order went out on a PIN typed against a dialog that said nothing.
        Refused now, by the holder's row; nothing is sent."""
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import (ROUTER, _arm_live,
                                                _components_on,
                                                _fake_live_client, _quote,
                                                _signal)
        inst = _quote("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        fake = _fake_live_client()
        sig = _signal(inst)
        with patch(ROUTER, return_value=fake):
            shown = preview_take_trade(self.user, sig)["duplicate"]
        self.assertTrue(shown["ok"], shown)
        holder = _config(self.user, asset_class="crypto", name="late_live")
        row = _open(holder, "BTCUSD", rule="ema_cross", asset_class="crypto")
        row.paper = False
        row.save(update_fields=["paper"])
        with patch(ROUTER, return_value=fake):
            out = execute_take_trade(self.user, sig, pin_ok=True,
                                     dup_seen=shown["holder_ids"])
        self.assertIn("since this ticket was shown", out.get("error", ""))
        self.assertIn("ema_cross", out["error"])
        self.assertTrue(out["error"].endswith("nothing was sent"),
                        out["error"])
        fake.market_order.assert_not_called()
        self.assertFalse(AssetBotTrade.objects.filter(
            metadata__manual=True).exists())


class AHolderTheTicketDidNotShowTests(_Ticket):
    """The warning is the operator's decision only where it was shown
    (review, 2026-10-31). The dialog sends back the holders it displayed
    (dup_seen, by row: two bots can share a rule's name); a holder the
    send finds that the ticket never showed refuses, and the ticket opened
    again shows it. Warned tickets still go through."""

    def _shown(self):
        from bot_program.manual_trade import preview_asset_trade
        return preview_asset_trade(self.user, self.inst, "BUY")["duplicate"]

    def _send(self, seen):
        from bot_program.manual_trade import execute_asset_trade
        return execute_asset_trade(self.user, self.inst, "BUY",
                                   dup_seen=seen)

    def _manual_rows(self):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.filter(metadata__manual=True).count()

    def test_a_holder_that_appeared_after_the_preview_is_refused(self):
        shown = self._shown()
        self.assertEqual(shown["holder_ids"], [])
        _open(_config(self.user, asset_class="crypto", name="late"),
              "BTCUSD", rule="ema_cross", asset_class="crypto")
        out = self._send(shown["holder_ids"])
        self.assertIn("BTCUSD long was opened by ema_cross since this ticket "
                      "was shown", out.get("error", ""))
        self.assertIn("open the ticket again", out["error"])
        self.assertEqual(self._manual_rows(), 0)

    def test_a_second_holder_under_the_same_name_is_refused(self):
        _open(_config(self.user, asset_class="crypto", name="one"),
              "BTCUSD", rule="ema_cross", asset_class="crypto")
        shown = self._shown()
        self.assertEqual(len(shown["holder_ids"]), 1)
        _open(_config(self.user, asset_class="crypto", name="two"),
              "BTCUSD", rule="ema_cross", asset_class="crypto")
        out = self._send(shown["holder_ids"])
        self.assertIn("since this ticket was shown", out.get("error", ""))
        self.assertEqual(self._manual_rows(), 0)

    def test_a_send_that_names_no_holder_is_refused_past_one(self):
        """An older dialog, or any caller, that says nothing of what was
        shown: nothing was, so a holder refuses."""
        from bot_program.manual_trade import execute_asset_trade
        _open(_config(self.user, asset_class="crypto", name="quiet"),
              "BTCUSD", rule="ema_cross", asset_class="crypto")
        out = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertIn("BTCUSD long is held by ema_cross, and this send names "
                      "none of the holders its ticket showed",
                      out.get("error", ""))
        self.assertIn("open the ticket again", out["error"])
        self.assertEqual(self._manual_rows(), 0)

    def test_a_shown_holder_that_closed_since_is_no_refusal(self):
        from bot_program.models import AssetBotTrade
        row = _open(_config(self.user, asset_class="crypto", name="gone"),
                    "BTCUSD", rule="ema_cross", asset_class="crypto")
        shown = self._shown()
        AssetBotTrade.objects.filter(pk=row.pk).update(status="CLOSED")
        out = self._send(shown["holder_ids"])
        self.assertTrue(out.get("ok"), out)
        self.assertNotIn("duplicate_at_entry", AssetBotTrade.objects.get(
            id=out["trade_id"]).metadata)

    def test_the_view_carries_what_the_dialog_showed(self):
        import json

        from django.test import RequestFactory

        from dashboard.views import _parse_trade_body

        def parse(body):
            req = RequestFactory().post("/x", data=json.dumps(body),
                                        content_type="application/json")
            return _parse_trade_body(req)

        self.assertIsNone(parse({})[0]["dup_seen"])
        self.assertEqual(parse({"dup_seen": ["trade:4", "position:9"]})[0]
                         ["dup_seen"], ["trade:4", "position:9"])
        self.assertEqual(parse({"dup_seen": []})[0]["dup_seen"], [])
        out, err = parse({"dup_seen": "trade:4"})
        self.assertIsNone(out)
        self.assertIn("dup_seen", err)
        # a junk entry is dropped, never matched
        self.assertEqual(parse({"dup_seen": ["trade:4", 7, None]})[0]
                         ["dup_seen"], ["trade:4"])

    def test_the_asset_view_passes_it_through(self):
        import json
        _open(_config(self.user, asset_class="crypto", name="viewed"),
              "BTCUSD", rule="ema_cross", asset_class="crypto")
        self.client.force_login(self.user)
        shown = self._shown()
        url = "/instruments/BTCUSD/take-trade/"
        res = self.client.post(url, json.dumps({"side": "BUY",
                                                "dup_seen": []}),
                               content_type="application/json").json()
        self.assertIn("since this ticket was shown", res.get("error", ""))
        res = self.client.post(url, json.dumps({
            "side": "BUY", "dup_seen": shown["holder_ids"]}),
            content_type="application/json").json()
        self.assertTrue(res.get("ok"), res)


class TheBotsStillRefuseTests(_Ticket):

    def test_a_bot_is_refused_on_a_bet_another_config_holds(self):
        from portfolio.risk_gate import duplicate_state
        manual = _config(self.user, asset_class="crypto", name="manual")
        _open(manual, "BTCUSD", rule="manual_take", asset_class="crypto")
        bot = _config(self.user, asset_class="crypto", name="trend3")
        state = duplicate_state(self.user, symbol="BTCUSD", side="BUY",
                                config_id=bot.id)
        self.assertFalse(state["ok"])
        self.assertIn("manual_take", state["reason"])


class ALegacyRowSaysWhatItIsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("sa_leg",
                                                        password="x")

    def test_a_shared_book_row_names_its_kind_book_origin_age_and_page(self):
        from portfolio.risk_gate import duplicate_state, limits_book
        pos = _legacy(limits_book(), days=40)
        state = duplicate_state(self.user, symbol="AAPL", side="BUY",
                                config_id=_config(self.user, name="b1",
                                                  asset_class="stock").id)
        self.assertFalse(state["ok"])
        reason = state["reason"]
        self.assertIn(f"legacy portfolio position #{pos.pk}", reason)
        self.assertIn("on the Main book", reason)
        self.assertIn("the /setup/ eToro sync button", reason)
        self.assertIn("dated 40 days ago", reason)
        self.assertIn(f"/admin/portfolio/position/{pos.pk}/change/", reason)
        self.assertIn("manage.py legacy_positions", reason)
        self.assertEqual(state["legacy"][0]["id"], pos.pk)
        self.assertEqual(state["legacy"][0]["age_days"], 40)

    def test_a_users_own_book_row_names_the_form_or_the_chat(self):
        from portfolio.risk_gate import duplicate_state
        from portfolio.services import get_or_create_default_portfolio
        pos = _legacy(get_or_create_default_portfolio(user=self.user),
                      days=3)
        state = duplicate_state(self.user, symbol="AAPL", side="BUY",
                                config_id=None)
        self.assertIn(f"#{pos.pk}", state["reason"])
        self.assertIn("the /setup/ 'add position' form or the chat trader",
                      state["reason"])
        self.assertIn("on the sa_leg_main book", state["reason"])

    def test_the_ticket_and_the_bots_carry_the_same_words(self):
        """The ticket's warning and a bot's skip read one sentence."""
        from bot_program.manual_trade import _duplicate_advisory
        from portfolio.risk_gate import duplicate_state, limits_book
        pos = _legacy(limits_book(), symbol="MSFT", days=2)
        state = duplicate_state(self.user, symbol="MSFT", side="BUY",
                                config_id=None, paper=False)
        adv = _duplicate_advisory(state)
        self.assertFalse(adv["ok"])
        self.assertEqual(adv["reason"], state["reason"])
        self.assertEqual(adv["legacy"][0]["remove_at"],
                         f"/admin/portfolio/position/{pos.pk}/change/")


class TheBotsSkipNamesTheLegacyRowTests(TestCase):
    """The bot's duplicate refusal is recorded through _skip, which keeps
    200 characters (skips.record), and why_no_trade shows 88 (review,
    2026-10-31): the legacy row's words came after the 175-character
    doubling sentence, so the stored skip ended "It is legacy portf" and
    the row's id and page reached only the worker log. They lead now, on
    the bot's real entry path."""

    def setUp(self):
        from tests.test_entry_quote import (_book, _instrument, _live_cfg,
                                            _signal, _user)
        self.user = _user("sa_skip")
        self.cfg = _live_cfg(self.user, name="SASKIP")
        self.inst = _instrument()
        _signal(self.inst, rule="sa_rule")
        _book(self.user)

    def _legacy_here(self, book, days=40):
        from portfolio.models import Position
        return Position.objects.create(
            portfolio=book, instrument=self.inst, direction="long",
            quantity=Decimal("5"), entry_price=Decimal("200"),
            current_price=Decimal("200"),
            opened_at=timezone.now() - timedelta(days=days))

    def _propose(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_desk_seam import _client as _mock_client
        from tests.test_entry_quote import ROUTER
        client = _mock_client("100.00")
        client.ticker.return_value = {"lastPrice": "100.00", "bid": "99.9",
                                      "ask": "100.1", "symbol": "AAPL"}
        with patch(ROUTER, return_value=client):
            return StockBot(self.cfg).propose_entry("AAPL")

    def _detail(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        note = skips.last_by_symbol(self.cfg)["AAPL"]
        self.assertEqual(note["code"], skips.GATE_BLOCKED)
        return note["detail"]

    def test_control_a_clean_book_proposes(self):
        self.assertIsNotNone(self._propose())

    def test_the_recorded_skip_names_the_row_and_where_it_closes(self):
        from portfolio.risk_gate import limits_book
        pos = self._legacy_here(limits_book())
        self.assertIsNone(self._propose())
        detail = self._detail()
        self.assertIn(f"legacy portfolio position #{pos.pk}", detail[:88])
        self.assertIn(f"/admin/portfolio/position/{pos.pk}/change/", detail)

    def test_a_row_on_the_users_own_book_too(self):
        from portfolio.services import get_or_create_default_portfolio
        pos = self._legacy_here(
            get_or_create_default_portfolio(user=self.user), days=3)
        self.assertIsNone(self._propose())
        detail = self._detail()
        self.assertIn(f"#{pos.pk}", detail[:88])
        self.assertIn(f"/admin/portfolio/position/{pos.pk}/change/", detail)


def _admin_post_data(form):
    """The change form's own values, as the browser posts them back."""
    from django import forms
    data = {}
    for name, field in form.fields.items():
        value = form[name].value()
        widget = getattr(field.widget, "widget", field.widget)
        if isinstance(widget, forms.MultiWidget):
            for i, (w, part) in enumerate(zip(widget.widgets,
                                              widget.decompress(value))):
                data[f"{name}_{i}"] = w.format_value(part) or ""
        else:
            data[name] = "" if value is None else str(value)
    return data


class ALegacyRowClosesWhereItsWordsSayTests(TestCase):
    """The words sent the operator to the admin page to "set Closed at";
    that page required a stop and a target, which the chat trader and a
    blank /setup/ 'add position' never write, so the save failed (review,
    2026-10-31). The page closes such a row now, and the words no longer
    say that nothing closes one (the chat trader's 'close' and the kill
    switch close <username>_main rows; no bot or reconcile does)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            "sa_adm", "sa_adm@example.test", "pw-of-the-test")

    def test_the_page_named_closes_a_row_with_no_stop_or_target(self):
        from portfolio.models import Position
        from portfolio.risk_gate import legacy_position_words
        from portfolio.services import get_or_create_default_portfolio
        self.client.force_login(self.admin)
        # shaped as the chat trader writes it: no stop, no target
        pos = _legacy(get_or_create_default_portfolio(user=self.admin),
                      days=3)
        self.assertIsNone(pos.stop_loss)
        self.assertIsNone(pos.take_profit)
        url = legacy_position_words(pos)["remove_at"]
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        data = _admin_post_data(page.context["adminform"].form)
        data["closed_at_0"] = data["opened_at_0"]
        data["closed_at_1"] = data["opened_at_1"]
        data["_save"] = "Save"
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302,
                         getattr(resp, "context", None)
                         and resp.context["adminform"].form.errors)
        pos = Position.objects.get(pk=pos.pk)
        self.assertIsNotNone(pos.closed_at)
        self.assertIsNone(pos.stop_loss)
        self.assertIsNone(pos.take_profit)

    def test_the_words_say_who_closes_one(self):
        import inspect

        from bot_program.management.commands import legacy_positions
        from portfolio import risk_gate
        from portfolio.risk_gate import legacy_position_words, limits_book
        words = legacy_position_words(_legacy(limits_book()))["words"]
        self.assertIn("no bot or reconcile closes it", words)
        self.assertNotIn("nothing closes it", words)
        self.assertIn("set Closed at", words)
        for module in (legacy_positions, risk_gate):
            self.assertNotIn("nothing ever closes", inspect.getsource(module))


class TheLegacyListTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("sa_cmd",
                                                        password="x")

    def _run(self, *args):
        out = StringIO()
        call_command("legacy_positions", *args, stdout=out)
        return out.getvalue()

    def test_it_lists_open_rows_by_symbol_with_origin_and_age(self):
        from portfolio.models import Position
        from portfolio.risk_gate import limits_book
        from portfolio.services import get_or_create_default_portfolio
        a = _legacy(limits_book(), "AAPL", days=12)
        b = _legacy(get_or_create_default_portfolio(user=self.user), "TSLA",
                    direction="short", days=1)
        closed = _legacy(limits_book(), "NVDA", days=5)
        closed.closed_at = timezone.now()
        closed.save(update_fields=["closed_at"])
        before = list(Position.objects.order_by("pk").values())
        text = self._run()
        self.assertIn("2 open legacy portfolio position(s)", text)
        self.assertLess(text.index("\nAAPL"), text.index("\nTSLA"))
        self.assertIn(f"#{a.pk}", text)
        self.assertIn("age 12d", text)
        self.assertIn("written by the /setup/ eToro sync button", text)
        self.assertIn(f"#{b.pk}", text)
        self.assertIn("short", text)
        self.assertIn("the /setup/ 'add position' form or the chat trader",
                      text)
        self.assertIn(f"/admin/portfolio/position/{b.pk}/change/", text)
        self.assertNotIn("NVDA", text)
        # read-only: every row as it was
        self.assertEqual(list(Position.objects.order_by("pk").values()),
                         before)

    def test_the_filters_and_the_empty_book(self):
        from portfolio.risk_gate import limits_book
        self.assertIn("No open legacy portfolio position", self._run())
        _legacy(limits_book(), "AAPL")
        _legacy(limits_book(), "TSLA")
        text = self._run("--symbol", "tsla")
        self.assertIn("TSLA", text)
        self.assertNotIn("AAPL", text)
        self.assertIn("1 open legacy", self._run("--user", "sa_cmd",
                                                 "--symbol", "AAPL"))


class TheTicketPageWarnsTests(SimpleTestCase):

    def test_the_dialog_renders_the_duplicate_as_a_warning(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "base.html"
               ).read_text(encoding="utf-8")
        fn = src[src.index("function sizeDialog(p)"):]
        fn = fn[:fn.index("var okBtn = host.querySelector")]
        block = fn[fn.index("var dupl = p.duplicate"):]
        block = block[:block.index("THE SEND'S CASH CHECK, on the ticket")]
        self.assertIn("IS ALREADY HELD ON THIS SIDE", block)
        self.assertIn("dupl.holders", block)
        self.assertIn("A warning, not a block", block)
        self.assertIn("Your bots refuse it", block)

    def _dialog(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "base.html"
               ).read_text(encoding="utf-8")
        fn = src[src.index("function sizeDialog(p)"):]
        return src, fn[:fn.index("function tradeFlow(")]

    def test_the_warning_is_on_screen_when_the_ticket_opens(self):
        """The dialog focused the size, so its body opened scrolled past
        every warning box at 1280x800 and 390x844 (review, 2026-10-31):
        the PIN and TAKE LIVE TRADE were on screen, the duplicate was
        not. It opens on the warning now, repeats it beside the PIN and
        the go button, and names the second ticket in its title."""
        _, fn = self._dialog()
        self.assertIn('data-role="dupwarn" tabindex="-1"', fn)
        self.assertIn('data-role="cashwarn" tabindex="-1"', fn)
        focus = fn[fn.index("host.setAttribute('data-sv-focus',"):]
        focus = focus[:focus.index(");")]
        self.assertLess(focus.index('[data-role="dupwarn"]'),
                        focus.index('[data-role="qty"]'))
        self.assertIn('[data-role="cashwarn"]', focus)
        # the notice beside the PIN and the go button
        self.assertIn('data-role="dupnotice"', fn)
        self.assertIn("'Second ticket on '", fn)
        self.assertIn("sizeHtml + sideNotes + pinHtml", fn)
        # the title says it is a second ticket, not an add to "this" one
        self.assertIn("'Take a second '", fn)

    def test_the_send_carries_the_holders_the_dialog_showed(self):
        src, fn = self._dialog()
        ok = fn[fn.index("okBtn.addEventListener('click'"):]
        ok = ok[:ok.index("host.querySelector('[data-role=\"cancel\"]')")]
        self.assertIn("dup_seen: (dupl.holder_ids || []).slice()", ok)
        flow = src[src.index("function tradeFlow("):]
        flow = flow[:flow.index("fetch(executeUrl")]
        self.assertIn("if (choice.dup_seen) body.dup_seen = choice.dup_seen;",
                      flow)
