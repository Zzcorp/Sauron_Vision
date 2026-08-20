"""Three gestures on a position row, three destinations.

The positions table used to answer every gesture with the same page. Hover
raised the dwell card, click opened the trade's forensics timeline — and the
symbol, the one word on the row that names a thing rather than a trade,
opened that same timeline. So an operator holding BTCUSD who wanted to look
at BTCUSD had to leave the book, open the instruments list and search for it
by hand, while the link that already said BTCUSD sat under their pointer.

What this file pins, in order:
  * the SYMBOL goes to the instrument and nothing else does — the row keeps
    the trade's detail, and the two destinations stay distinguishable before
    the click, not after it;
  * a link that cannot be built is not built: the `as` form of the url tag
    is the only one that does not raise, and a symbol the route cannot hold
    must cost that one row its link rather than 500 the whole book;
  * the row keeps a REAL anchor to the trade detail, because the dwell card
    is aria-hidden and pointer-only and would otherwise be the only way
    there;
  * a click on either link does not also fire the row's own navigation —
    one gesture, one destination, never a race between two;
  * the card's own chrome — the close proxy, the money block, the em-dash
    for an unmeasured value — is untouched by any of it;
  * the styling ships in this page's own <style> block, in tokens, with no
    raw hex, no raw z-index, and nothing that can push the table sideways.

Run with:  python manage.py test tests.test_position_card_ux
"""
import pathlib
import re
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase
from django.utils import timezone

POSITIONS = "/positions/"
HISTORY = "/positions/?tab=history"


def _static(*parts):
    return (pathlib.Path(settings.BASE_DIR).joinpath("static", *parts)
            .read_text(encoding="utf-8"))


def _template():
    return (pathlib.Path(settings.BASE_DIR)
            .joinpath("templates", "dashboard", "positions_list.html")
            .read_text(encoding="utf-8"))


def _style_block():
    """Everything between the template's <style> tags.

    The slice matters: the assertions below are about what THIS page ships,
    and a rule that only exists in the shared sheet is a rule another agent
    can move out from under it.
    """
    markup = _template()
    return markup[markup.index("<style>"):markup.rindex("</style>")]


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(inst, last):
    from market_data.models import LiveQuote
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "binance_public"})


def _trade(user, *, symbol="BTCUSD", entry=60000, stop=59000, target=62000,
           qty="0.5"):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    config = AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name="book-%s" % symbol, enabled=True,
        mode="paper", symbols=[], capital=Decimal("10000"))
    return AssetBotTrade.objects.create(
        config=config, asset_class="crypto", symbol=symbol, side="BUY",
        qty=Decimal(qty), entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)), take_profit=Decimal(str(target)),
        status="OPEN", paper=True, rule_name="breakout_1h",
        reason="trend up", composite_score=0.8, broker_order_id="OID-1",
        metadata={"value_per_unit": 1.0, "initial_stop_loss": float(stop)})


def _book_position(inst, *, closed=False, user=None):
    """A legacy portfolio.Position: no config, no trade, no timeline — and,
    until now, no way at all to reach the instrument it names.

    It goes on the USER'S book, because that is the one the positions pages
    read. They used to read the shared "Main" row, which is fed by a single
    global eToro key with no user attached and is therefore nobody's
    portfolio; a row parked there is now invisible to the page under test.
    """
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    return Position.objects.create(
        portfolio=get_or_create_default_portfolio(user=user), instrument=inst,
        direction="long", quantity=Decimal("1"),
        entry_price=Decimal("100"), current_price=Decimal("110"),
        unrealized_pnl=Decimal("10"), unrealized_pnl_pct=10.0,
        opened_at=timezone.now(),
        closed_at=timezone.now() if closed else None)


def _row(html):
    """The first position row's opening <tr ...> tag."""
    match = re.search(r"<tr data-sv-position-row.*?>", html, flags=re.S)
    return match.group(0) if match else ""


def _symbol_cell(html):
    match = re.search(r'<span class="pos-sym-cell">.*?</span></td>',
                      html, flags=re.S)
    return match.group(0) if match else ""


class SymbolLeadsToTheInstrumentTests(TestCase):
    """The gesture the table did not have."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pux_sym", password="x")

    def setUp(self):
        self.inst = _instrument()
        _quote(self.inst, 61000)
        self.trade = _trade(self.user)
        self.client.force_login(self.user)
        self.html = self.client.get(POSITIONS).content.decode("utf-8", "replace")

    def test_the_symbol_is_a_link_to_the_instrument_page(self):
        cell = _symbol_cell(self.html)
        self.assertIn('href="/instruments/BTCUSD/"', cell)
        self.assertIn("pos-sym-link", cell)

    def test_the_symbol_no_longer_points_at_the_trades_timeline(self):
        """It is the one word on the row that names the underlying rather
        than the trade, and it has to go where it says."""
        cell = _symbol_cell(self.html)
        symbol_link = re.search(r'<a href="([^"]+)" class="pos-sym-link"', cell)
        self.assertIsNotNone(symbol_link, "the symbol is not a link at all")
        self.assertNotIn("/forensics/", symbol_link.group(1))

    def test_the_row_still_carries_a_real_anchor_to_the_trade_detail(self):
        """The dwell card is aria-hidden and opens on a pointer it does not
        assume exists. Without this anchor the detail page would be
        unreachable for anyone driving the book from the keyboard."""
        cell = _symbol_cell(self.html)
        self.assertIn('href="/forensics/%d/"' % self.trade.id, cell)
        self.assertIn("pos-row-detail", cell)

    def test_the_row_hands_the_card_the_instrument_it_belongs_to(self):
        """The card's own title is that link, so it needs the destination on
        the row — the card is portalled to <body> and can read nothing else."""
        self.assertIn('data-pos-instrument-href="/instruments/BTCUSD/"',
                      _row(self.html))

    def test_the_row_click_destination_is_still_the_trades_own_page(self):
        """Adding a second destination must not have moved the first one."""
        self.assertIn('data-pos-href="/forensics/%d/"' % self.trade.id,
                      _row(self.html))

    def test_a_book_row_with_no_trade_still_reaches_its_instrument(self):
        """A row from the shared portfolio book has no trade, no timeline and
        nothing that could flatten it — it was a dead end in every direction.
        The instrument underneath it exists whether a bot opened the position
        or not, so that link is offered where the trade's is not.

        The symbol is deliberately one the fixed headband list does not
        carry: base.html links every headband symbol to its instrument page
        on every page of this platform, so a headband name would make the
        assertion pass whether this row linked anywhere or not.
        """
        _book_position(_instrument("ZBOOKUSD"), user=self.user)
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertIn('data-pos-instrument-href="/instruments/ZBOOKUSD/"', html)
        self.assertIn('href="/instruments/ZBOOKUSD/"', html)
        # ...and no detail link is invented for a page that does not exist.
        self.assertIn('data-pos-href=""', html)

    def test_a_symbol_the_route_cannot_hold_costs_one_link_not_the_page(self):
        """`<str:symbol>` will not match a slash, so reversing a forex pair
        quoted as EUR/USD raises NoReverseMatch. The plain url tag would take
        the entire book down with it over one row; the `as` form yields an
        empty string, and the cell renders the symbol as text."""
        _book_position(_instrument("EUR/USD", asset_class="forex"), user=self.user)
        resp = self.client.get(POSITIONS)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8", "replace")
        self.assertIn("EUR/USD", html)
        self.assertNotIn('href="/instruments/EUR/USD/"', html)
        # The row is still a row, with an honestly empty destination.
        self.assertIn('data-pos-instrument-href=""', html)
        # And the symbol still reads as itself rather than as a dead link.
        self.assertIn("pos-sym-plain", html)

    def test_another_users_trade_brings_no_link_of_any_kind(self):
        """Two destinations is two ways to leak a row that is not ours. The
        symbol is off the headband list on purpose — those are linked from
        base.html on every page and would mask a genuine leak here."""
        other = get_user_model().objects.create_user("pux_other", password="x")
        _instrument("ZLEAKUSD")
        theirs = _trade(other, symbol="ZLEAKUSD")
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertNotIn("/forensics/%d/" % theirs.id, html)
        self.assertNotIn("/instruments/ZLEAKUSD/", html)


class TheThreeGesturesStayDistinctTests(SimpleTestCase):
    """The interaction lives in JS, so nothing on the page would fail if the
    row started swallowing its own links' clicks again."""

    def setUp(self):
        self.js = _static("js", "sv-position-card.js")

    def test_a_click_on_a_link_or_a_button_is_not_a_click_on_the_row(self):
        """Both would navigate, to different pages, in the same tick. The
        guard is written once and shared by the pointer and the touch path
        so the two can never drift apart."""
        self.assertIn('if (e.target.closest("a, button")) return;', self.js)
        self.assertIn("click: rowNav", self.js)
        self.assertIn("tap: rowNav", self.js)

    def test_the_row_still_opens_the_trades_full_detail(self):
        block = self.js.split("function rowNav(", 1)[1].split("\n    }", 1)[0]
        self.assertIn('val(row, "href")', block)
        self.assertIn("follow(e, href)", block)

    def test_a_modifier_click_opens_a_tab_instead_of_taking_the_book(self):
        """A <tr> is not an anchor, so ctrl/cmd/shift-click had been quietly
        replacing the page the operator asked to open beside it."""
        block = self.js.split("function follow(", 1)[1].split("\n    }", 1)[0]
        self.assertIn("e.metaKey || e.ctrlKey || e.shiftKey", block)
        self.assertIn('w.open(href, "_blank", "noopener")', block)
        # And it still lands somewhere when the browser refuses the tab.
        self.assertIn("w.location.assign(href)", block)

    def test_the_cards_title_is_the_link_to_the_instrument(self):
        """Same word, same place, same destination as the cell in the table
        underneath it — otherwise the card teaches a different map."""
        self.assertIn('val(row, "instrument-href")', self.js)
        self.assertIn('"pos-pop-sym pos-sym-link"', self.js)

    def test_a_row_with_no_instrument_page_gets_plain_text_not_a_dead_link(self):
        block = self.js.split("var instHref = ", 1)[1].split("var side", 1)[0]
        self.assertIn('el(idBox, "div", "pos-pop-sym"', block)

    def test_the_card_offers_the_instrument_as_an_action_too(self):
        self.assertIn("▸ INSTRUMENT", self.js)
        self.assertIn("FULL DETAIL ›", self.js)

    def test_the_destructive_action_is_last_on_the_card(self):
        """The pointer travels to a page many times for every once it
        flattens a position, and the two sit one gap apart on a card that
        appears under a moving hand."""
        self.assertLess(self.js.index("▸ INSTRUMENT"),
                        self.js.index("pos-pop-close"))
        self.assertLess(self.js.index("FULL DETAIL ›"),
                        self.js.index("pos-pop-close"))

    def test_the_card_names_all_three_gestures_once(self):
        self.assertIn(
            "click the row for its full detail · the symbol for the instrument",
            self.js)

    def test_nothing_on_the_card_enters_the_tab_order(self):
        """It is aria-hidden: a focusable control inside it is a trap with
        no way out. Three controls now, three opt-outs."""
        self.assertGreaterEqual(self.js.count("tabIndex = -1"), 4)

    def test_the_close_is_still_a_proxy_for_the_rows_own_button(self):
        """Regression guard. The card gained two links; it must not have
        gained a second close path with them."""
        self.assertIn('row.querySelector("[data-sv-close-trade]")', self.js)
        self.assertIn("rowClose.click()", self.js)
        self.assertNotIn("close/preview", self.js)

    def test_the_money_block_still_prints_what_the_view_formatted(self):
        """parseFloat("1,540.00") is 1540. The ledger prints strings."""
        block = self.js.split("function ledger(", 1)[1].split("\n    }", 1)[0]
        self.assertNotIn("parseFloat", block)
        self.assertIn('margin ? "Margin" : "Cost at entry"', self.js)
        # The bottom line is now the one the eye lands on.
        self.assertIn('" is-net"', self.js)

    def test_an_unmeasured_value_is_still_an_em_dash(self):
        self.assertIn('DASH = "—"', self.js)
        self.assertIn("sv-unknown", self.js)

    def test_the_shared_dwell_engine_is_still_the_only_one(self):
        """No placement, no timing, no listeners of its own — the card grew
        actions, not an engine."""
        for copied in ("getBoundingClientRect", "setTimeout", "pointerover"):
            self.assertNotIn(copied, self.js)


class TheStylingShipsWithThisPageTests(SimpleTestCase):
    """static/css/sauron.css belongs to the shared system and is not edited
    from here, so every rule this page adds lives in its own block."""

    def setUp(self):
        self.css = _style_block()

    def test_the_symbol_reads_as_a_link_before_the_pointer_arrives(self):
        """A link painted like the cell beside it is a link nobody presses,
        and the whole gesture is worth nothing unpressed."""
        block = self.css.split(".pos-sym-cell .pos-sym-link {", 1)[1] \
                        .split("}", 1)[0]
        self.assertIn("text-decoration: underline", block)
        self.assertIn("var(--accent)", block)

    def test_the_keyboard_can_see_where_it_is(self):
        self.assertIn(":focus-visible", self.css)
        self.assertIn("outline: 1px solid var(--accent)", self.css)

    def test_only_a_row_with_a_destination_behaves_like_one(self):
        """data-pos-href is empty on a row from the shared book. A pointer
        cursor there promises a page that does not exist."""
        self.assertIn('[data-sv-position-row]:not([data-pos-href=""]) '
                      '{ cursor: pointer; }', self.css)

    def test_nothing_in_the_symbol_cell_can_set_the_tables_floor_width(self):
        """Two links in one cell, one of them a token that can be twelve
        characters long. They wrap inside the cell or they widen the table
        until the page scrolls sideways."""
        block = self.css.split(".pos-sym-cell {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-wrap: wrap", block)
        self.assertIn("min-width: 0", block)
        # tbody td is nowrap globally, and a cell that cannot wrap cannot
        # flex-wrap either.
        self.assertIn("white-space: normal", block)
        self.assertIn("overflow-wrap: anywhere",
                      self.css.split(".pos-sym-cell .pos-sym-link {", 1)[1]
                              .split("}", 1)[0])

    def test_the_cards_actions_collapse_rather_than_set_a_width(self):
        """Three buttons on a 400px card, and at 420px the card is nearly the
        whole screen."""
        block = self.css.split(".pos-pop .pos-pop-actions {", 1)[1] \
                        .split("}", 1)[0]
        self.assertIn("minmax(min(8rem, 100%), 1fr)", block)
        self.assertIn("@media (max-width: 420px)", self.css)
        self.assertIn(".pos-pop .pos-pop-actions { grid-template-columns: 1fr; }",
                      self.css)

    def test_the_sections_of_the_card_are_named(self):
        """Four blocks divided by four identical dashed rules read as one
        long list."""
        self.assertIn(".pos-pop .pos-pop-sec-cap", self.css)
        js = _static("js", "sv-position-card.js")
        self.assertIn('"pos-pop-ledger-cap pos-pop-sec-cap"', js)
        for named in ("capital", "levels · distance to each", "provenance",
                      "why it was taken"):
            self.assertIn(named, js)

    def test_the_page_carries_no_raw_hex_colour(self):
        """A hex cannot flip with the theme, and this page has a light mode."""
        offenders = re.findall(r"#[0-9a-fA-F]{3,8}\b", self.css)
        self.assertEqual(offenders, [], "raw hex colours: %r" % offenders)

    def test_the_page_carries_no_raw_z_index(self):
        """The card is portalled to <body> precisely because the fixed bands
        above it create stacking contexts; a number here would be a promise
        the ladder cannot keep."""
        self.assertNotIn("z-index", self.css)

    def test_motion_is_optional(self):
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        block = self.css.rsplit("@media (prefers-reduced-motion: reduce)", 1)[1]
        self.assertIn("transition: none", block)

    def test_the_shared_sheet_was_not_edited_to_get_any_of_it(self):
        """File ownership, asserted rather than remembered: these selectors
        are this page's, and duplicating them into the shared sheet is how
        two definitions of one component start disagreeing."""
        shared = _static("css", "sauron.css")
        for selector in (".pos-sym-cell", ".pos-row-detail", ".pos-pop-sec-cap",
                         ".pos-pop-mrow.is-net", ".ph-sym"):
            self.assertNotIn(selector, shared,
                             "%s is defined in the shared sheet as well as in "
                             "the page" % selector)


class HistoryTabFollowsTheSameRuleTests(TestCase):
    """One page, one rule: a symbol is the instrument and goes to the
    instrument, whether the position is open or graded and gone."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pux_hist", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def test_a_closed_positions_symbol_links_to_its_instrument(self):
        """Off the headband list, or base.html would answer for it."""
        _book_position(_instrument("ZHISTUSD"), closed=True, user=self.user)
        html = self.client.get(HISTORY).content.decode("utf-8", "replace")
        self.assertIn('href="/instruments/ZHISTUSD/"', html)
        self.assertIn("ph-sym", html)

    def test_following_that_link_does_not_also_expand_the_card(self):
        """The history card toggles on click. Without the guard, leaving for
        the instrument also expanded the card being left."""
        markup = _template()
        self.assertIn("if (!event.target.closest('a')) "
                      "{ this.classList.toggle('expanded'); }", markup)

    def test_the_history_tab_still_renders_with_no_closed_trades(self):
        resp = self.client.get(HISTORY)
        self.assertEqual(resp.status_code, 200)
