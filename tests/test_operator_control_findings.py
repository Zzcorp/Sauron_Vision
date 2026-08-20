"""Regressions for the defects the operator-control review confirmed.

Four surfaces, one theme: a number or a link that was confidently wrong
about something the platform could have checked.

Run with:  python manage.py test tests.test_operator_control_findings
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase


def _cfg(user, name, asset_class="stock", symbols=None):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name,
        symbols=symbols if symbols is not None else [],
        enabled=True, mode="paper", capital=Decimal("10000"))


def _open_trade(cfg, symbol="AAPL"):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
        paper=True)


class LiveBotCountTests(TestCase):
    """The BOT cell counts the FLEET, and a hand-taken position is not it.

    The server-rendered cell had already learned this. `panel_counts_json`
    — the endpoint the /ws/eye/ listener refetches on every fill — had not,
    so pressing TAKE TRADE flipped the sub-line to "1 open" within a second
    while the dropdown directly beneath it still said zero. Two surfaces,
    one book, opposite answers, one click apart.
    """

    def setUp(self):
        self.user = User.objects.create_user("count_u", password="x")
        self.client.force_login(self.user)

    def _counts(self):
        return self.client.get("/partials/panel-counts/").json()

    def test_a_hand_taken_position_is_not_a_bot_position(self):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        _open_trade(_cfg(self.user, MANUAL_CONFIG_NAME))
        self.assertEqual(self._counts()["bot_open"], 0)

    def test_a_real_bot_position_still_counts(self):
        _open_trade(_cfg(self.user, "momentum bot", symbols=["AAPL"]))
        self.assertEqual(self._counts()["bot_open"], 1)

    def test_a_user_config_named_manual_with_symbols_is_a_real_bot(self):
        """manual_trade refuses to trade through that config precisely
        because it is somebody's real bot — so it must still be counted."""
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        _open_trade(_cfg(self.user, MANUAL_CONFIG_NAME, symbols=["AAPL"]))
        self.assertEqual(self._counts()["bot_open"], 1)

    def test_exposure_still_counts_every_open_row(self):
        """POSITIONS is about exposure, and exposure does not care who
        opened it — the carve-out must not leak into that cell."""
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        _open_trade(_cfg(self.user, MANUAL_CONFIG_NAME), symbol="GOLD")
        _open_trade(_cfg(self.user, "bot one", symbols=["AAPL"]))
        counts = self._counts()
        self.assertEqual(counts["positions"], 2)

    def test_the_hand_taken_book_is_published_not_hidden(self):
        """A carve-out must not become a hiding place."""
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        _open_trade(_cfg(self.user, MANUAL_CONFIG_NAME))
        self.assertEqual(self._counts()["manual_open"], 1)


class InstrumentPageTests(TestCase):
    """A route proves the STRING fits the pattern, never that the row exists."""

    def test_a_saved_instrument_has_a_page(self):
        from instruments.models import Instrument
        inst = Instrument.objects.create(
            symbol="AAPL", name="Apple", asset_class="stock")
        self.assertTrue(inst.has_page)

    def test_an_unsaved_instrument_does_not(self):
        from instruments.models import Instrument
        self.assertFalse(Instrument(symbol="NOPE", name="x").has_page)

    def test_the_stand_in_does_not(self):
        """This is the case that rendered a live link to a 404 — a bot
        holding BTCUSDT while the table holds BTCUSD."""
        from portfolio.services import _InstrumentShim
        self.assertFalse(_InstrumentShim("BTCUSDT", "crypto").has_page)

    def test_the_flag_is_positive_on_the_row_that_has_the_page(self):
        """Django resolves a missing attribute to False, so a NEGATIVE flag
        would read False on every real Instrument too and take every
        working link down with it."""
        from instruments.models import Instrument
        self.assertTrue(hasattr(Instrument, "has_page"))

    def test_every_symbol_link_is_gated(self):
        page = (Path(settings.BASE_DIR) / "templates" / "dashboard"
                / "positions_list.html").read_text(encoding="utf-8")
        for line in page.splitlines():
            if "url 'instrument_detail'" in line:
                self.assertIn("has_page", line,
                              f"ungated instrument link: {line.strip()[:90]}")


class BestWorstPairTests(TestCase):
    """Whether the pair means anything is not a question about how many
    closes were graded — it is whether the two are the same row.

    Counting was the first fix and it was not enough. max() and min() both
    return the FIRST extremum, so any tie hands back one object twice, and
    ties are ordinary: portfolio.Position.unrealized_pnl defaults to 0.00
    and nothing marks a closed legacy row.
    """

    def setUp(self):
        self.user = User.objects.create_user("pair_u", password="x")
        self.client.force_login(self.user)

    def _closed(self, symbol, pnl):
        from bot_program.models import AssetBotTrade
        from django.utils import timezone
        cfg = _cfg(self.user, f"bot {symbol}", symbols=[symbol])
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol=symbol, side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            exit_price=Decimal("100") + Decimal(str(pnl)),
            status="CLOSED", pnl=Decimal(str(pnl)), paper=True,
            closed_at=timezone.now())

    def _history(self):
        return self.client.get("/positions/?tab=history")

    def test_two_closes_that_tie_do_not_make_a_pair(self):
        self._closed("TIEA", 0)
        self._closed("TIEB", 0)
        resp = self._history()
        self.assertFalse(resp.context["have_pair"])
        body = resp.content.decode("utf-8", "replace")
        self.assertNotIn("Best Trade", body)
        self.assertNotIn("Worst Trade", body)

    def test_the_tie_says_so_rather_than_claiming_it_is_the_only_close(self):
        self._closed("TIEA", 0)
        self._closed("TIEB", 0)
        body = self._history().content.decode("utf-8", "replace")
        self.assertIn("all level", body.lower())
        self.assertNotIn("Only closed trade", body)

    def test_two_different_closes_do_make_a_pair(self):
        self._closed("WON", 40)
        self._closed("LOST", -40)
        resp = self._history()
        self.assertTrue(resp.context["have_pair"])
        body = resp.content.decode("utf-8", "replace")
        self.assertIn("Best Trade", body)
        self.assertIn("Worst Trade", body)

    def test_one_close_is_still_the_only_close(self):
        self._closed("ONE", -12)
        resp = self._history()
        self.assertFalse(resp.context["have_pair"])
        self.assertIn("Only closed trade",
                      resp.content.decode("utf-8", "replace"))


class ModifierClickTests(TestCase):
    """`window.open(url, "_blank", "noopener")` ALWAYS returns null.

    That is specified, not a failure — a noopener window is deliberately
    unreachable from its opener, so there is no handle to hand back.
    Testing it for success therefore never succeeded, and the fall-through
    ran on every Ctrl-click: the page opened in a new tab AND this tab left
    the book behind.
    """

    def test_the_return_value_is_not_treated_as_success(self):
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-position-card.js").read_text(encoding="utf-8")
        self.assertNotIn('if (w.open(href, "_blank", "noopener")) return;', js)

    def test_a_modifier_click_does_not_also_navigate_this_tab(self):
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-position-card.js").read_text(encoding="utf-8")
        follow = js[js.index("function follow"):]
        follow = follow[:follow.index("\n    }")]
        opened = follow.index("w.open(")
        returned = follow.index("return;", opened)
        assigned = follow.index("w.location.assign")
        self.assertLess(returned, assigned,
                        "the same-tab navigation is still reachable after "
                        "the new tab was opened")
