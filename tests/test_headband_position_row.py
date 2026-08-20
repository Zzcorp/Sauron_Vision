"""The POSITIONS cell's dropdown, which the operator called hideous.

It was one flex line holding eight things — symbol, side, size, R, %, a
`closing` chip, a `paper` chip and a close button — inside a panel capped
at 360px. Every element fought for the same line, so the numbers never
landed in the same column twice and the close button was sized by whatever
space the percentage happened to leave behind.

It is a two-line grid now: identity on top, size and state below, R
directly above % in one right-hand column, and the close button in its own
column spanning both lines. The tests below pin the parts that carry
meaning rather than the pixels.

Run with:  python manage.py test tests.test_headband_position_row
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase


def _css():
    return (Path(settings.BASE_DIR) / "static" / "css" / "sv-overlay.css") \
        .read_text(encoding="utf-8")


class RowLayoutTests(SimpleTestCase):
    def test_the_row_is_a_grid_and_not_one_flex_line(self):
        css = _css()
        self.assertIn(".ip-dropdown .ip-pos {", css)
        block = css.split(".ip-dropdown .ip-pos {", 1)[1].split("}", 1)[0]
        self.assertIn("grid", block)
        self.assertIn("grid-template-areas", block)

    def test_r_sits_directly_above_the_percentage(self):
        """The point of the second line: one numeric column, not two
        numbers competing for horizontal space."""
        css = _css()
        areas = css.split("grid-template-areas:", 1)[1].split(";", 1)[0]
        self.assertIn('"id   r   act"', areas)
        self.assertIn('"meta pct act"', areas)

    def test_both_numbers_share_one_column_width(self):
        css = _css()
        for sel in (".ip-dropdown .ip-pos .ipr-r", ".ip-dropdown .ip-pos .ipr-pct"):
            block = css.split(sel + " {", 1)[1].split("}", 1)[0]
            self.assertIn("min-width: 58px", block, sel)
            self.assertIn("text-align: right", block, sel)

    def test_the_single_line_margin_is_cancelled_inside_the_grid(self):
        """`.ipr-r` carries `margin-left:auto` for the OTHER panels' rows.
        Left in place here it shoves the number out of its grid column."""
        block = _css().split(".ip-dropdown .ip-pos .ipr-r {", 1)[1] \
            .split("}", 1)[0]
        self.assertIn("margin-left: 0", block)

    def test_the_numbers_are_tabular_so_a_book_scans_down(self):
        block = _css().split(".ip-dropdown .ip-pos {", 1)[1].split("}", 1)[0]
        self.assertIn("tabular-nums", block)

    def test_the_close_button_has_its_own_column(self):
        block = _css().split(".ip-dropdown .ip-pos-close {", 1)[1] \
            .split("}", 1)[0]
        self.assertIn("grid-area: act", block)

    def test_the_close_button_is_muted_until_reached_for(self):
        """A permanently red button in a panel opened to READ the book
        invites the one click here that cannot be taken back."""
        css = _css()
        resting = css.split(".ip-dropdown .ip-pos-close {", 1)[1] \
            .split("}", 1)[0]
        self.assertIn("background: transparent", resting)
        self.assertNotIn("--accent-red", resting)
        hover = css.split(".ip-dropdown .ip-pos-close:hover,", 1)[1] \
            .split("}", 1)[0]
        self.assertIn("--accent-red", hover)

    def test_the_side_stripe_covers_both_vocabularies(self):
        """The bot book says BUY/SELL and the legacy book says LONG/SHORT.
        A stripe matching one of them colours half the book."""
        css = _css()
        for token in ("ip-pos--buy", "ip-pos--long",
                      "ip-pos--sell", "ip-pos--short"):
            self.assertIn(token, css)


class RowRendersTests(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from bot_program.models import AssetBotConfig, AssetBotTrade

        self.user = get_user_model().objects.create_user("hbrow", password="x")
        self.client.force_login(self.user)
        inst, _ = Instrument.objects.get_or_create(
            symbol="XAUUSD",
            defaults={"name": "Gold", "asset_class": "commodity"})
        LiveQuote.objects.update_or_create(
            instrument=inst,
            defaults={"last": Decimal("2450"), "source": "test"})
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name="hb",
            capital=Decimal("10000"))
        self.trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="commodity", symbol="XAUUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("2400"),
            stop_loss=Decimal("2380"), status="OPEN", paper=True,
            metadata={"initial_stop_loss": 2380})

    def _body(self):
        resp = self.client.get("/positions/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", "replace")

    def _row(self):
        import re
        body = self._body()
        seg = body[body.find('data-sv-live="hb-pos-detail"'):][:2000]
        match = re.search(r'<div class="ip-pos [^"]*">.*?(?=<div class="ip-pos |'
                          r'<div class="ip-dd-note")', seg, re.S)
        self.assertIsNotNone(match, "no ip-pos row rendered")
        return match.group(0)

    def test_the_row_renders_in_the_new_shape(self):
        row = self._row()
        for part in ("ip-pos-id", "ip-pos-meta", "ipr-r", "ipr-pct"):
            self.assertIn(part, row)

    def test_the_side_modifier_matches_the_side_token_actually_used(self):
        """This is how the stripe silently missed: the row renders LONG,
        not BUY, and a `--buy`-only rule matched nothing."""
        import re
        row = self._row()
        modifier = re.search(r'ip-pos ip-pos--(\w+)', row).group(1)
        self.assertIn("ip-pos--" + modifier, _css(),
                      f"nothing styles the side token this row renders "
                      f"({modifier!r})")

    def test_the_close_control_survived_the_restyle(self):
        row = self._row()
        self.assertIn(f'data-sv-close-trade="{self.trade.id}"', row)
        self.assertIn("ip-pos-close", row)

    def test_a_position_with_no_live_mark_dashes_rather_than_blanks(self):
        from market_data.models import LiveQuote
        LiveQuote.objects.all().delete()
        row = self._row()
        self.assertIn("&mdash;", row)
