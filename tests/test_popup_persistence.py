"""Popups survive being read, and the position card says what it cost.

TWO SUBJECTS, one file, because they are the same complaint from the same
seat: the operator hovers something, and what comes back is either taken away
before it can be read or does not answer the question.

── (a) A popup the operator has REACHED must stay reached ────────────────
Every dwell/hover engine on this platform hid on ANY scroll, in the CAPTURE
phase. Capture was chosen deliberately and correctly: the bell panel and the
table wrappers scroll internally, their scroll events do not bubble, and a
card anchored to a row inside one of them goes stale the moment that
container moves. But capture also catches the CARD scrolling itself — so the
instant the operator moved onto the card they had dwelled two seconds for and
scrolled to read the rest of it, it vanished. Four engines shipped that bug:
the shared SV.dwell cards (notifications, positions), base.html's portalled
headband/ticker/watchlist popups and its signals-rail card, the news feed and
the briefing history.

The fix is one question asked before any hide: did this scroll come from
INSIDE an open popup? The registry that answers it is published as SV.popup
from static/js/sv-notif-card.js, because a guard kept private to one engine
protects one engine. What this file pins:
  * the scroll handler consults the popup before hiding, in every engine;
  * NO engine anywhere hides unconditionally on scroll (a scanner, so the
    fifth engine cannot reintroduce it quietly);
  * resize follows the anchor instead of destroying the card;
  * a pointer that leaves the card only because it is dragging the card's
    own scrollbar is not a leave;
  * a wheel over a card with nothing to scroll does not chain to the page —
    which would scroll the anchor away and close the card "correctly";
  * the grace is honest: a popup the pointer has ENTERED is not on a
    countdown. It closes on a genuine leave of BOTH the popup and the cell,
    on Escape, or when the row it describes disappears.

── (b) The money the card never showed ───────────────────────────────────
The card gained the ladder, live R, the spark and the provenance, and still
could not answer "what did this cost me and what is it worth now". The
capital ledger adds it. The one figure that can lie is the committed capital:
on a levered class qty x entry is EXPOSURE — bot_program sizing lets forex
run to 400% of equity (asset_engine/sizing.MAX_NOTIONAL_FRACTION) because the
leverage sits at the broker — and the capital actually put up is margin,
which nothing on this platform records. So a forex position shows a dashed
margin and a separately-named notional, never the notional dressed as a cost.

And the numbers must agree with the two other places that answer the same
question. The exit cost comes from bot_program.manual_close._exit_fill, so
"if closed now" is arithmetically the P&L preview_close quotes; 1R comes from
_risk_dollars, which is what bot_grading books. Three different answers to
"what did this make me" is worse than one.

Run with:  python manage.py test tests.test_popup_persistence
"""
import pathlib
import re
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

POSITIONS = "/positions/"


def _read(*parts):
    return (pathlib.Path(settings.BASE_DIR).joinpath(*parts)
            .read_text(encoding="utf-8", errors="replace"))


def _static(*parts):
    return _read("static", *parts)


def _attr(html, name):
    """The first data-pos-<name> value in the page, or None when the
    attribute is absent altogether — a different failure from an empty one."""
    m = re.search(r'data-pos-%s="([^"]*)"' % re.escape(name), html)
    return None if m is None else m.group(1)


def _money(text):
    """The float behind a rendered money string ("1,540.00" -> 1540.0)."""
    return float(text.replace(",", ""))


# ── Fixtures ────────────────────────────────────────────────────────────

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


def _config(user, asset_class="crypto", name="book"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=True,
        mode="paper", symbols=[], capital=Decimal("10000"))


def _trade(user, *, symbol="BTCUSD", asset_class="crypto", entry=60000,
           stop=59000, target=62000, qty="0.5", vpu=1.0, paper=True,
           config=None):
    from bot_program.models import AssetBotTrade
    meta = {"value_per_unit": vpu}
    if stop is not None:
        meta["initial_stop_loss"] = float(stop)
    return AssetBotTrade.objects.create(
        config=config or _config(user, asset_class), asset_class=asset_class,
        symbol=symbol, side="BUY", qty=Decimal(qty),
        entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)) if stop is not None else None,
        take_profit=Decimal(str(target)) if target is not None else None,
        status="OPEN", paper=paper, rule_name="breakout_1h",
        reason="trend up", composite_score=0.8, broker_order_id="OID-1",
        metadata=meta)


# ── (a) The scroll that ate the card ────────────────────────────────────

class ScrollMustNotEatAnOpenCardTests(TestCase):
    """The capture-phase listener is right about stale anchors and wrong
    about the card itself. Both halves have to survive."""

    def test_the_shared_engine_asks_the_popup_before_it_hides(self):
        js = _static("js", "sv-notif-card.js")
        self.assertIn("insideOpenPopup", js)
        # The guard runs INSIDE the scroll handler, not somewhere nearby.
        i = js.index('w.addEventListener("scroll"')
        window = js[i:i + 700]
        self.assertIn("capture: true", window,
                      "the capture phase is what catches an inner container "
                      "scrolling an anchor away, and it has to stay")
        self.assertIn("insideOpenPopup(e.target)", window)
        # And the unconditional version it replaced must not come back.
        self.assertNotIn('w.addEventListener("scroll", function () { hideAll(null); }',
                         js)

    def test_the_page_scrolling_still_closes_the_card(self):
        """Half the fix is not breaking the other half: the document, the
        root and <body> contain every popup, so a naive contains() check
        would have made the card immortal on a page scroll — which is the
        one case where the anchor genuinely moved."""
        js = _static("js", "sv-notif-card.js")
        block = js.split("function insideOpenPopup", 1)[1].split("\n    }", 1)[0]
        for excluded in ("d.documentElement", "d.body", "node === d"):
            self.assertIn(excluded, block,
                          "a scroll of the page itself must still close the "
                          "card — %s is not excluded" % excluded)

    def test_the_registry_is_published_for_the_other_engines(self):
        """base.html carries two more popup engines and the feed pages carry
        two more after that. A guard that lives in one file protects one
        file, so the question is answered once and exported."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn("w.SV.popup", js)
        for name in ("opened:", "closed:", "inside:"):
            self.assertIn(name, js)

    def test_no_engine_anywhere_hides_unconditionally_on_scroll(self):
        """The scanner. Four engines had this bug independently, which means
        the next one written will have it too unless something fails."""
        hides = ("hide(", "hideAll(", "remove('show')", 'remove("show")',
                 "display = 'none'", 'display = "none"', "display='none'")
        guards = ("insideOpenPopup", "SV.popup", "pop.contains",
                  "popup.contains", "_svAnchor", "onReanchor")
        listener = re.compile(r"""addEventListener\(\s*['"]scroll['"]""")
        offenders = []
        root = pathlib.Path(settings.BASE_DIR)
        for folder, suffix in (("static/js", ".js"), ("templates", ".html")):
            for path in root.joinpath(folder).rglob("*" + suffix):
                src = path.read_text(encoding="utf-8", errors="replace")
                for m in listener.finditer(src):
                    window = src[m.start():m.start() + 700]
                    if not any(h in window for h in hides):
                        continue
                    if any(g in window for g in guards):
                        continue
                    offenders.append("%s:%d" % (
                        path.name, src.count("\n", 0, m.start()) + 1))
        self.assertEqual(offenders, [],
                         "a scroll handler hides a popup without first asking "
                         "whether the scroll came from inside it")

    def test_resize_follows_the_anchor_instead_of_destroying_the_card(self):
        """A snapped window or an opened devtools pane does move the anchor.
        The answer to that is to re-place the card, not to throw away what
        the operator was reading."""
        js = _static("js", "sv-notif-card.js")
        self.assertNotIn('w.addEventListener("resize", function () { hideAll(null); })',
                         js)
        self.assertIn("instances[i].reflow()", js)
        block = js.split("inst.reflow = function", 1)[1].split("};", 1)[0]
        self.assertIn("place(pop, inst.row)", block)
        # A row that has actually left the document is still a close.
        self.assertIn("inst.hide()", block)

    def test_dragging_the_cards_own_scrollbar_is_not_leaving_it(self):
        """A scrollbar drag carries the pointer outside the card's box and
        fires the very pointerleave that closes it — mid-drag, on the exact
        gesture the operator used to read further."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn('pop.addEventListener("pointerdown"', js)
        self.assertIn("inst.held = true", js)
        block = js.split('pop.addEventListener("pointerleave"', 1)[1] \
                  .split("});", 1)[0]
        self.assertIn("if (inst.held) return;", block)
        # And the drag has to be able to end, or the card becomes immortal.
        self.assertIn('w.addEventListener("pointerup"', js)

    def test_a_wheel_over_an_unscrollable_card_does_not_scroll_the_page(self):
        """With nothing to scroll the wheel chained to the page; the page
        moved, the anchor genuinely went stale, and the card was closed —
        correctly, one frame after the operator asked to see more of it."""
        js = _static("js", "sv-notif-card.js")
        block = js.split('pop.addEventListener("wheel"', 1)[1].split("});", 1)[0]
        self.assertIn("pop.scrollHeight > pop.clientHeight", block)
        self.assertIn("e.preventDefault()", block)
        css = _static("css", "sauron.css")
        # The CSS half: containment stops the chaining at the ENDS of a card
        # that does scroll, which the JS guard deliberately does not touch.
        self.assertIn("overscroll-behavior: contain",
                      css.split(".nf-pop {", 1)[1].split("}", 1)[0])

    def test_the_headband_and_watchlist_popups_carry_the_same_guards(self):
        html = _read("templates", "base.html")
        engine = html.split("function showPortalPopup", 1)[1] \
                     .split("// Data headband hover arrows", 1)[0]
        self.assertIn("popRegister(pop, true)", engine)
        self.assertIn("pop.scrollHeight > pop.clientHeight", engine)
        self.assertIn("SV.popup", html)

    def test_the_signals_rail_card_carries_them_too(self):
        html = _read("templates", "base.html")
        engine = html.split("function hidePopup(wrap)", 1)[1] \
                     .split("Phase 64.4", 1)[0]
        self.assertIn("SV.popup.closed(pop)", engine)
        self.assertIn("SV.popup.opened(pop)", engine)
        self.assertIn("pop.scrollHeight > pop.clientHeight", engine)

    def test_the_feed_and_briefing_previews_carry_them_too(self):
        """These two still run their own pre-SV.dwell copies of the engine,
        and they broke in exactly the same place."""
        for tpl in ("news_feed.html", "briefing.html"):
            src = _read("templates", "dashboard", tpl)
            self.assertIn("addEventListener('scroll'", src,
                          "%s lost its scroll listener" % tpl)
            i = src.index("addEventListener('scroll'")
            window = src[i:i + 700]
            self.assertIn("capture: true", window)
            self.assertIn("pop.contains(e.target)", window,
                          "%s still hides the card the operator is scrolling"
                          % tpl)


class TheGraceIsHonestTests(TestCase):
    """A popup the pointer has ENTERED does not close on a timer racing the
    operator's hand. The only thing a timer may cover is the few pixels of
    page between the cell and the card."""

    def test_the_dwell_card_closes_on_a_genuine_leave_and_not_on_a_clock(self):
        js = _static("js", "sv-notif-card.js")
        self.assertIn("LEAVE_GRACE_MS", js)
        # Arriving on either end cancels whatever was counting down, so
        # nothing is ever running while the pointer is on the card.
        self.assertIn('pop.addEventListener("pointerenter"', js)
        self.assertIn("inst.cancelLeave()", js)
        block = js.split("inst.scheduleLeave = function", 1)[1] \
                  .split("};", 1)[0]
        self.assertIn("inst.cancelLeave();", block)
        self.assertIn("if (inst.held) return;", block)

    def test_the_row_disappearing_still_closes_it(self):
        """The other two exits the spec allows. The row leaving the document
        is watched by the live-data observer; Escape is a document listener."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn("if (inst.row && !d.contains(inst.row)) inst.hide()", js)
        self.assertIn('if (e.key === "Escape" || e.key === "Esc") hideAll(null)',
                      js)

    def test_the_portal_popups_check_where_the_pointer_went(self):
        """The 140ms timer was started by the CELL's mouseleave — i.e. by the
        operator reaching for the popup. Where the pointer actually went is
        the only honest input."""
        html = _read("templates", "base.html")
        engine = html.split("function maybeHidePortalPopup", 1)[1] \
                     .split("function hidePortalPopup", 1)[0]
        self.assertIn("item.contains(to)", engine)
        self.assertIn("pop.contains(to)", engine)
        self.assertNotIn("}, 140);", html,
                         "a popup still closes on the 140ms race")

    def test_escape_closes_the_portal_popup_and_the_rail_card(self):
        """Neither offered a keyboard way out before."""
        html = _read("templates", "base.html")
        portal = html.split("function hidePortalPopup", 1)[1] \
                     .split("// Data headband popups", 1)[0]
        self.assertIn("hidePortalPopup(activePopup)", portal)
        self.assertIn("'Escape'", portal)
        self.assertIn("wrap._srHide()", html)

    def test_a_swapped_cell_takes_its_portalled_popup_with_it(self):
        """The popup is moved to <body>, so it outlives the cell it
        describes and would hang over the page pointing at nothing."""
        html = _read("templates", "base.html")
        self.assertIn("htmx:afterSwap", html.split(
            "function hidePortalPopup", 1)[1].split(
            "// Data headband popups", 1)[0])


# ── (b) The capital ledger ──────────────────────────────────────────────

class MoneyBlockTests(TestCase):
    """What was committed, what it is worth, and what closing it books."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pp_money", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _html(self):
        return self.client.get(POSITIONS).content.decode("utf-8", "replace")

    def test_a_cash_position_states_what_it_cost_and_what_it_is_worth(self):
        """0.5 units bought at 60,000 and marked at 61,000: 30,000 committed,
        30,500 at the mark. Neither number is on the row, and the operator
        was doing this multiplication in their head."""
        inst = _instrument()
        _quote(inst, 61000)
        _trade(self.user)
        html = self._html()
        self.assertEqual(_attr(html, "committed"), "30,000.00")
        self.assertEqual(_attr(html, "committed-kind"), "cost")
        self.assertEqual(_attr(html, "value-now"), "30,500.00")
        self.assertEqual(_attr(html, "ccy"), "USD")
        # Not levered, so there is no second exposure figure to name — and
        # printing the same number twice under two names is how a notional
        # eventually gets read as a cost.
        self.assertEqual(_attr(html, "notional"), "")

    def test_the_percentage_divides_the_currency_figures_it_is_shown_with(self):
        """The card prints the row's own P&L percent — the one the table's
        column prints — beside the committed capital. If those two disagree
        the card is showing an operator a percentage of something else."""
        inst = _instrument()
        _quote(inst, 61000)
        _trade(self.user)
        html = self._html()
        committed = _money(_attr(html, "committed"))
        change = float(_attr(html, "pnl"))
        pct = float(_attr(html, "pnl-pct"))
        self.assertAlmostEqual(change / committed * 100, pct, places=2)

    def test_a_forex_position_shows_margin_and_never_the_levered_notional(self):
        """1,000 units at 125.00 with the entry-time rate 0.008 is 1,000 of
        notional. What the account put up is MARGIN, and printing 1,000.00
        as "what this cost me" would overstate the position by the whole
        leverage — that is the thing this test exists to prevent, and it
        still does.

        What changed is the other half. The margin used to render as an
        em-dash, on the grounds that it is the broker's number and nothing
        here records it. `manual_trade.CAPITAL_USE_FRACTION` does record a
        model of it — 1/30 for forex — and the risk gates, the
        concentration ceiling and the book's own ALLOCATED figure all size
        against exactly that. Dashing it here made the one class where
        capital and exposure differ by thirty times the only class whose
        capital the card would not name, which is precisely backwards.

        So it is the modelled margin, labelled `margin` so it can never be
        read as cash spent, and it is emphatically not the notional.
        """
        inst = _instrument("USDJPY", "forex")
        _quote(inst, 126)
        _trade(self.user, symbol="USDJPY", asset_class="forex", entry=125,
               stop=124, target=128, qty="1000", vpu=0.008)
        html = self._html()
        self.assertEqual(_attr(html, "committed-kind"), "margin")
        committed = _attr(html, "committed")
        self.assertNotEqual(committed, "1,000.00",
                            "the notional was printed as the cost")
        # 1,000 of notional at the platform's own 1/30 forex fraction.
        self.assertEqual(committed, "33.33")
        self.assertEqual(_attr(html, "notional"), "1,000.00")
        self.assertEqual(_attr(html, "value-now"), "1,008.00")
        # And the percentage is then a percentage OF that notional, which is
        # what the card's caption says it is.
        self.assertAlmostEqual(
            float(_attr(html, "pnl")) / _money(_attr(html, "notional")) * 100,
            float(_attr(html, "pnl-pct")), places=2)

    def test_the_exit_cost_is_the_one_the_close_dialog_will_charge(self):
        """_close_trade charges a paper exit half the round trip adversely,
        so preview_close quotes the P&L at that FILL. A card quoting the raw
        mark-to-market would be the third answer to one question."""
        from bot_program.manual_close import _exit_fill
        from bot_program.models import AssetBotTrade
        inst = _instrument()
        _quote(inst, 61000)
        _trade(self.user)
        html = self._html()
        trade = AssetBotTrade.objects.get()
        fill = _exit_fill(trade, 61000.0)
        expected = abs(61000.0 - fill) * 0.5
        self.assertEqual(_attr(html, "exit-cost"), "{:,.2f}".format(expected))
        # "If closed now" is therefore exactly preview_close's pnl.
        self.assertEqual(_attr(html, "net-now"),
                         "{:,.2f}".format(float(_attr(html, "pnl")) - expected))

    def test_one_r_in_currency_is_the_number_grading_will_book(self):
        """bot_grading and manual_close both denominate R by the stop the
        trade OPENED with. The card takes the size from _risk_dollars rather
        than multiplying it out again."""
        from bot_program.manual_close import _risk_dollars
        from bot_program.models import AssetBotTrade
        inst = _instrument("USDJPY", "forex")
        _quote(inst, 126)
        _trade(self.user, symbol="USDJPY", asset_class="forex", entry=125,
               stop=124, target=128, qty="1000", vpu=0.008)
        html = self._html()
        trade = AssetBotTrade.objects.get()
        # 1 point of price x 1,000 units x the entry-time rate.
        self.assertEqual(_risk_dollars(trade), 8.0)
        self.assertEqual(_attr(html, "risk"), "8")

    def test_a_trailed_stop_does_not_rewrite_what_1r_cost(self):
        """The risk taken has not changed, only the stop protecting it."""
        from bot_program.models import AssetBotTrade
        inst = _instrument()
        _quote(inst, 61000)
        _trade(self.user)
        AssetBotTrade.objects.update(stop_loss=Decimal("60900"))
        html = self._html()
        self.assertEqual(_attr(html, "risk"), "500")

    def test_an_unpriced_position_dashes_the_figures_it_cannot_have(self):
        """No quote: nothing is worth anything measurable, and a 0.00 in the
        "at the mark" line reads as a position that has gone to nothing."""
        _instrument("ETHUSD")
        _trade(self.user, symbol="ETHUSD", entry=3000, stop=2900, target=3300)
        html = self._html()
        for key in ("value-now", "exit-cost", "net-now"):
            self.assertEqual(_attr(html, key), "",
                             "data-pos-%s fabricated a value with no quote"
                             % key)
        # What it COST is still known — that is history, not a mark.
        self.assertEqual(_attr(html, "committed"), "1,500.00")

    def test_a_book_row_with_no_trade_behind_it_still_renders(self):
        """A portfolio.Position has no config, no venue and no close path.
        Every figure that depends on one has to be a gap, not a zero."""
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        inst = _instrument()
        _quote(inst, 61000)
        # The user's own book: the positions page reads that one now, not
        # the shared "Main" row a single global eToro key writes to.
        Position.objects.create(
            portfolio=get_or_create_default_portfolio(user=self.user),
            instrument=inst,
            direction="long", quantity=Decimal("1"),
            entry_price=Decimal("60000"), current_price=Decimal("61000"),
            opened_at=timezone.now())
        resp = self.client.get(POSITIONS)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "committed"), "60,000.00")
        self.assertEqual(_attr(html, "ccy"), "")
        self.assertEqual(_attr(html, "exit-cost"), "")
        self.assertEqual(_attr(html, "net-now"), "")

    def test_an_open_trade_has_no_booked_r_yet(self):
        """realized_r is written by bot_grading on close. A 0 here would
        read as a scratched trade sitting next to a live +1.00R."""
        inst = _instrument()
        _quote(inst, 61000)
        _trade(self.user)
        self.assertEqual(_attr(self._html(), "realized-r"), "")


class MoneyBlockRendererTests(TestCase):
    """The card's half of the contract. The interaction lives in JS, so
    nothing else on the page would fail if the renderer stopped honouring
    the distinction the view went to the trouble of sending."""

    def test_the_card_labels_margin_as_margin(self):
        js = _static("js", "sv-position-card.js")
        self.assertIn('margin ? "Margin" : "Cost at entry"', js)
        self.assertIn('mrow(box, "Notional", val(row, "notional")', js)
        self.assertIn("levered exposure", js)

    def test_the_card_never_re_parses_a_grouped_money_string(self):
        """parseFloat("1,540.00") is 1540 — the decimals are silently gone.
        The view formats the money and the card prints what it was given."""
        js = _static("js", "sv-position-card.js")
        block = js.split("function ledger(", 1)[1].split("\n    }", 1)[0]
        self.assertNotIn("num(row, \"committed\")", block)
        self.assertNotIn("parseFloat", block)
        self.assertIn("moneySign", js)

    def test_an_absent_figure_renders_as_the_em_dash(self):
        js = _static("js", "sv-position-card.js")
        block = js.split("function mrow(", 1)[1].split("\n    }", 1)[0]
        self.assertIn("text || DASH", block)
        self.assertIn("sv-unknown", block)

    def test_one_r_is_stated_once(self):
        """It moved into the ledger, beside the money it is denominated in.
        Two copies of one number on one card is how they start disagreeing."""
        js = _static("js", "sv-position-card.js")
        self.assertEqual(js.count('val(row, "risk")'), 1)
        self.assertEqual(js.count('"1R is"'), 1)

    def test_the_view_does_not_carry_a_second_cost_model(self):
        src = _read("dashboard", "views.py")
        self.assertIn("from bot_program.manual_close import _exit_fill", src)
        self.assertNotIn("DEFAULT_COST_BPS", src)
        self.assertIn("_POS_LEVERED_CLASSES", src)

    def test_the_ledger_chrome_rides_the_theme_tokens(self):
        """Both themes, and no floating element gets its own z-index — the
        card is portalled to <body> precisely because the fixed bands above
        it carry backdrop-filter."""
        css = _static("css", "sauron.css")
        block = css.split(".pos-pop-ledger {", 1)[1].split(".pos-pop-ladder", 1)[0]
        self.assertNotIn("z-index", block)
        self.assertIn("var(--text-muted)", block)
        self.assertIn("var(--accent-red)", block)
        self.assertIn("var(--accent)", block)
        self.assertNotIn("#", block, "a raw hex colour cannot flip with the "
                                     "theme")

    def test_the_ledger_wraps_rather_than_pushing_the_card_sideways(self):
        css = _static("css", "sauron.css")
        block = css.split("@media (max-width: 420px) {", 1)[1] \
                   .split("\n        }", 1)[0]
        self.assertIn(".pos-pop-mrow { flex-wrap: wrap; }", block)
        self.assertIn("overflow-wrap: anywhere",
                      css.split(".pos-pop-mrow .mv {", 1)[1].split("}", 1)[0])
