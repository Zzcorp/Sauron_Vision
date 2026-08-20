"""Best and worst mean nothing until two trades have been graded.

The operator reported a closed SHORT showing as a positive trade — "like
best and like worst". The P&L maths was right (`_trade_pnl` signs by side,
so a short's realised number is entry−exit), but the page crowned the only
graded close as BEST in a green card that hardcoded a `+` in front of the
number, and then showed that same row again as WORST. One losing trade, two
cards, one of them claiming a profit that never existed.

Run with:  python manage.py test tests.test_position_history_honesty
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _closed_short(user, *, symbol, entry, exit_price, qty=100):
    """A CLOSED short carrying the P&L the engine itself would book."""
    from bot_program.models import AssetBotConfig, AssetBotTrade
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="stock", name="history test bot",
        defaults={"capital": Decimal("10000")})
    pnl = (Decimal(str(entry)) - Decimal(str(exit_price))) * Decimal(str(qty))
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side="SELL",
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        exit_price=Decimal(str(exit_price)), status="CLOSED", pnl=pnl,
        closed_at=timezone.now(), paper=True)


class ShortPnlSignTests(TestCase):
    """The half of the report that turned out NOT to be broken.

    Pinned anyway: `_trade_pnl` is the only place the short branch is
    subtracted the other way round, and a refactor that lost it would put
    every short on the wrong side of the book with nothing to catch it.
    """

    def test_a_short_that_lost_books_a_negative_number(self):
        # Sold at 100, bought back at 110 — the short lost 10 a share.
        self.assertLess(_pnl(side="SELL", entry=100, exit_price=110), 0)

    def test_a_short_that_won_books_a_positive_number(self):
        self.assertGreater(_pnl(side="SELL", entry=100, exit_price=90), 0)

    def test_a_long_keeps_the_ordinary_sign(self):
        self.assertGreater(_pnl(side="BUY", entry=100, exit_price=110), 0)
        self.assertLess(_pnl(side="BUY", entry=100, exit_price=90), 0)


def _pnl(*, side, entry, exit_price, qty=100):
    """What the engine books for closing this trade at `exit_price`.

    `_trade_pnl` touches no instance state, so it is called off the class
    with the receiver left empty rather than standing a whole bot up.
    """
    from bot_program.asset_engine.base import AssetBot
    from bot_program.models import AssetBotTrade
    trade = AssetBotTrade(side=side, entry_price=Decimal(str(entry)),
                          qty=Decimal(str(qty)), asset_class="stock",
                          symbol="STUB")
    return float(AssetBot._trade_pnl(None, trade, Decimal(str(exit_price))))


class SingleGradedCloseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hist_u", password="x")
        self.client.force_login(self.user)

    def _history(self):
        return self.client.get("/positions/?tab=history")

    def _visible_text(self):
        """The page with its <script> and <style> blocks removed.

        `assertNotIn("+-", body)` over the whole document is not a test of
        what the operator SEES: the page ships JavaScript, and a number
        regex in it contains the character class `[+-]?`. That is script
        source, not a rendered figure, and matching it made a passing page
        look like it was printing "+-12.00" again.
        """
        import re
        body = self._history().content.decode("utf-8", "replace")
        return re.sub(r"<(script|style)\b.*?</\1>", " ", body,
                      flags=re.S | re.I)

    def test_one_losing_close_is_not_crowned_best(self):
        _closed_short(self.user, symbol="ONLY1", entry=100, exit_price=112)
        body = self._history().content.decode("utf-8", "replace")
        self.assertIn("Only closed trade", body)
        self.assertNotIn("Best Trade", body)
        self.assertNotIn("Worst Trade", body)

    def test_the_sign_is_never_forced_onto_a_loss(self):
        """`+{{ pnl }}` printed a plus in front of a negative number."""
        _closed_short(self.user, symbol="ONLY2", entry=100, exit_price=112)
        text = self._visible_text()
        self.assertNotIn("+-", text)
        # The loss is still ON the page — a version that rendered nothing
        # at all would also contain no "+-".
        self.assertIn("ONLY2", text)

    def test_a_plus_is_never_printed_in_front_of_an_unmeasured_value(self):
        """The em-dash case. `{% if pct > 0 %}+{% endif %}` is correct where
        `>= 0` would not be: smart-if swallows the TypeError from comparing
        None and evaluates it False, which is right for the sign and wrong
        for the colour — so the sign is guarded here and the colour comes
        from `sign_class`."""
        _closed_short(self.user, symbol="ONLY3", entry=100, exit_price=112)
        text = self._visible_text()
        self.assertNotIn("+—", text)
        self.assertNotIn("+&mdash;", text)

    def test_two_graded_closes_bring_the_pair_back(self):
        _closed_short(self.user, symbol="WINNER", entry=100, exit_price=80)
        _closed_short(self.user, symbol="LOSER", entry=100, exit_price=115)
        body = self._history().content.decode("utf-8", "replace")
        self.assertIn("Best Trade", body)
        self.assertIn("Worst Trade", body)
        self.assertNotIn("Only closed trade", body)

    def test_the_better_short_is_the_one_that_made_money(self):
        _closed_short(self.user, symbol="WINNER", entry=100, exit_price=80)
        _closed_short(self.user, symbol="LOSER", entry=100, exit_price=115)
        resp = self._history()
        self.assertEqual(resp.context["best_trade"].instrument.symbol, "WINNER")
        self.assertEqual(resp.context["worst_trade"].instrument.symbol, "LOSER")
        self.assertGreater(float(resp.context["best_trade"].unrealized_pnl), 0)
        self.assertLess(float(resp.context["worst_trade"].unrealized_pnl), 0)

    def test_no_closes_shows_neither_card(self):
        body = self._history().content.decode("utf-8", "replace")
        self.assertNotIn("Best Trade", body)
        self.assertNotIn("Only closed trade", body)


class HistoryBarTests(TestCase):
    """The mini bar under each history row.

    It drew `width: {{ pct }}%` for a long — negative for a loss, which CSS
    discards, so every losing long collapsed to the same 4px stub whatever
    it lost — and a hardcoded `width: 50%` for a short, which described
    nothing at all. The short branch is the one the reported trade landed in.
    """

    def setUp(self):
        self.user = User.objects.create_user("bar_u", password="x")
        self.client.force_login(self.user)

    def _rows(self):
        return self.client.get("/positions/?tab=history").context[
            "closed_positions"]

    def test_the_biggest_move_fills_the_track(self):
        _closed_short(self.user, symbol="BIG", entry=100, exit_price=60)
        _closed_short(self.user, symbol="SMALL", entry=100, exit_price=98)
        bars = {r.instrument.symbol: r.bar_pct for r in self._rows()}
        self.assertEqual(bars["BIG"], 100.0)
        self.assertLess(bars["SMALL"], bars["BIG"])

    def test_a_loss_is_drawn_at_its_size_not_as_a_stub(self):
        """The whole defect: magnitude survives the sign."""
        _closed_short(self.user, symbol="BADLOSS", entry=100, exit_price=140)
        _closed_short(self.user, symbol="TINY", entry=100, exit_price=99)
        bars = {r.instrument.symbol: r.bar_pct for r in self._rows()}
        self.assertEqual(bars["BADLOSS"], 100.0)
        self.assertGreater(bars["BADLOSS"], bars["TINY"])

    def test_a_bar_is_never_negative(self):
        _closed_short(self.user, symbol="L1", entry=100, exit_price=130)
        for row in self._rows():
            self.assertGreaterEqual(row.bar_pct, 0)

    def test_the_short_bar_is_no_longer_a_constant(self):
        """Two shorts of different sizes drew identical 50% bars."""
        _closed_short(self.user, symbol="S1", entry=100, exit_price=70)
        _closed_short(self.user, symbol="S2", entry=100, exit_price=97)
        bars = [r.bar_pct for r in self._rows()]
        self.assertNotEqual(bars[0], bars[1])

    def test_the_rendered_width_is_a_positive_length(self):
        _closed_short(self.user, symbol="RENDER", entry=100, exit_price=130)
        body = self.client.get(
            "/positions/?tab=history").content.decode("utf-8", "replace")
        self.assertNotIn("width:-", body)
