"""Position detail card — hover reveals, click opens.

A row in the positions table is twelve numbers and no answer to the only
question an operator asks of an open position: what is it doing, and why is
it on. Entry and mark are printed; the distance from the mark to the stop is
not. The rule name is printed, truncated to twenty characters; the reason the
engine wrote when it DECIDED is not, nor the score, nor the signal behind it,
nor the stop the trade opened with — which is the only denominator under
which "live R" means anything once a trailing stop has rewritten stop_loss.

What this file pins, in order:
  * the row carries the whole data-pos-* contract, because nothing else on
    the page would notice if one attribute quietly went missing;
  * an unknown is an EMPTY attribute, never "0" and never "None" — the card
    renders empty as an em-dash, and a fabricated zero on a P&L reads as a
    measured flat;
  * the card is portalled to <body> and rides --z-hovercard, never a raw
    number: the fixed bands above it carry backdrop-filter, which creates a
    stacking context that clamps its children whatever they claim;
  * the close action on the card reaches the EXISTING endpoint through the
    row's own button, rather than being a second implementation of the flow;
  * a trade with no signal — a fork, a hand-taken entry, a rule since
    renamed — degrades to dashes instead of 500ing or inventing one;
  * the dwell engine is shared (SV.dwell), not copied a fourth time, and
    survives the other half of the page refreshing the row underneath it.

Run with:  python manage.py test tests.test_position_detail
"""
import pathlib
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

POSITIONS = "/positions/"


def _static(*parts):
    return (pathlib.Path(settings.BASE_DIR).joinpath("static", *parts)
            .read_text(encoding="utf-8"))


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


def _config(user, name="book"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name=name, enabled=True,
        mode="paper", symbols=[], capital=Decimal("10000"))


def _trade(user, *, symbol="BTCUSD", entry=60000, stop=59000, target=62000,
           qty="0.5", rule="breakout_1h", reason="trend up · vol expansion",
           score=0.82, paper=True, metadata=None, config=None):
    from bot_program.models import AssetBotTrade
    meta = {"value_per_unit": 1.0}
    if stop is not None:
        meta["initial_stop_loss"] = float(stop)
    meta.update(metadata or {})
    return AssetBotTrade.objects.create(
        config=config or _config(user), asset_class="crypto", symbol=symbol,
        side="BUY", qty=Decimal(qty), entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)) if stop is not None else None,
        take_profit=Decimal(str(target)) if target is not None else None,
        status="OPEN", paper=paper, rule_name=rule, reason=reason,
        composite_score=score, broker_order_id="OID-1", metadata=meta)


def _attr(html, name):
    """The value of the first data-pos-<name> attribute in the page, or None
    when the attribute is absent altogether — which is a different failure
    from an empty one and has to be distinguishable here."""
    import re
    m = re.search(r'data-pos-%s="([^"]*)"' % re.escape(name), html)
    return None if m is None else m.group(1)


class RowContractTests(TestCase):
    """The data the card reads off the row. These are contract assertions:
    the interaction lives in JS, so nothing else on the page would fail if
    an attribute stopped being written."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pd_row", password="x")

    def setUp(self):
        self.inst = _instrument()
        _quote(self.inst, 61000)
        self.trade = _trade(self.user)
        self.client.force_login(self.user)
        self.html = self.client.get(POSITIONS).content.decode("utf-8", "replace")

    def test_the_row_is_the_anchor_the_engine_looks_for(self):
        self.assertIn("data-sv-position-row", self.html)

    def test_the_prices_and_their_distances_are_on_the_row(self):
        """The card's whole reason to exist: not the levels, which the table
        already prints, but how far the mark is from each of them."""
        self.assertEqual(_attr(self.html, "entry"), "60000")
        self.assertEqual(_attr(self.html, "mark"), "61000")
        self.assertEqual(_attr(self.html, "stop"), "59000")
        self.assertEqual(_attr(self.html, "target"), "62000")
        self.assertEqual(_attr(self.html, "stop-pct"), "3.28")
        self.assertEqual(_attr(self.html, "target-pct"), "1.64")

    def test_the_card_quotes_the_rows_own_r_and_never_a_second_one(self):
        """The mark is 1000 above a 60000 entry against a 1000 entry-to-stop,
        so exactly +1R. The card floats directly over the column that prints
        that number, so it must take it from the row rather than recompute it
        — two R's on one row is the one disagreement an operator cannot
        resolve. What the card adds is the SIZE of 1R, which no column has:
        1000 of price on 0.5 units is 500 of currency at risk."""
        self.assertEqual(float(_attr(self.html, "r")), 1.0)
        self.assertEqual(_attr(self.html, "risk"), "500")

    def test_the_r_size_is_denominated_by_the_stop_the_trade_opened_with(self):
        """A trailing stop rewrites stop_loss. Against the CURRENT stop, risk
        and P&L become the same quantity and every trailed winner scores
        ~1.0R — which is why manual_close._initial_stop is the one source."""
        self.trade.stop_loss = Decimal("60900")
        self.trade.save(update_fields=["stop_loss"])
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        # Still 500: the risk taken has not changed, only the stop protecting
        # it. Reading the trailed stop would have said 50.
        self.assertEqual(_attr(html, "risk"), "500")

    def test_the_reason_and_the_score_the_table_cannot_show_are_carried(self):
        self.assertEqual(_attr(self.html, "reason"),
                         "trend up · vol expansion")
        self.assertEqual(_attr(self.html, "rule"), "breakout_1h")
        self.assertEqual(_attr(self.html, "score"), "0.82")

    def test_the_venue_is_stated_because_one_of_them_is_real_money(self):
        self.assertEqual(_attr(self.html, "venue"), "PAPER")

    def test_the_click_destination_is_the_forensics_timeline(self):
        """Not a dialog. The timeline already renders the lifecycle, the
        signals around the entry, the gate events and the audit chain — a
        second view of the same facts is a second truth to maintain."""
        self.assertEqual(_attr(self.html, "href"),
                         "/forensics/%d/" % self.trade.id)

    def test_the_row_also_links_to_it_for_the_keyboard(self):
        """The card is aria-hidden and pointer-only, so the timeline has to
        be reachable without one."""
        self.assertIn('href="/forensics/%d/"' % self.trade.id, self.html)
        self.assertIn("pos-sym-link", self.html)

    def test_a_moved_stop_is_visible_as_a_moved_stop(self):
        """A trail rewrites stop_loss. Showing only the current one hides
        that the risk on the table is no longer the risk that was taken."""
        self.trade.stop_loss = Decimal("60500")
        self.trade.save(update_fields=["stop_loss"])
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "stop"), "60500")
        self.assertEqual(_attr(html, "initial-stop"), "59000")

    def test_a_breached_level_says_so_rather_than_reading_as_room(self):
        """The mark through the stop while the fill has not landed is the
        single most urgent state a position can be in, and "0.5% away" is
        exactly the wrong way to render it."""
        _quote(self.inst, 58500)
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "stop-through"), "1")
        self.assertEqual(_attr(html, "target-through"), "")


class UnknownsRenderAsGapsTests(TestCase):
    """Nothing on this card may invent a number."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pd_gap", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def test_a_position_with_no_quote_carries_empty_marks_not_zeros(self):
        """No LiveQuote row for the symbol. The mark, the P&L, the distances,
        the R and the ladder progress are all unknown — and an unknown that
        arrives as "0" is indistinguishable from a position sitting exactly
        flat on its entry."""
        _instrument("ETHUSD")
        _trade(self.user, symbol="ETHUSD", entry=3000, stop=2900, target=3300)
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        for key in ("mark", "pnl", "pnl-pct", "stop-pct", "target-pct",
                    "progress", "r"):
            self.assertEqual(_attr(html, key), "",
                             "data-pos-%s fabricated a value with no quote" % key)
        # The levels the trade genuinely has are still stated.
        self.assertEqual(_attr(html, "entry"), "3000")
        self.assertEqual(_attr(html, "stop"), "2900")

    def test_the_visible_cell_stays_an_em_dash_too(self):
        """The card and the table have to agree about what is unknown."""
        _instrument("ETHUSD")
        _trade(self.user, symbol="ETHUSD", entry=3000, stop=2900, target=3300)
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertIn("sv-unknown", html)
        self.assertNotIn(">None<", html)

    def test_a_trade_with_no_stop_has_no_r_rather_than_a_zero_r(self):
        """A legacy row with no entry stop has no risk to divide by, and
        "0.00R" would read as a scratch trade."""
        inst = _instrument("SOLUSD")
        _quote(inst, 150)
        _trade(self.user, symbol="SOLUSD", entry=140, stop=None, target=None,
               metadata={"initial_stop_loss": None})
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "r"), "")
        self.assertEqual(_attr(html, "risk"), "")
        self.assertEqual(_attr(html, "stop"), "")

    def test_a_micro_priced_instrument_is_not_rounded_down_to_zero(self):
        """This book holds instruments quoted at 60000 and instruments
        quoted at 0.000012 in the same table. A fixed four decimals prints
        the second one's entry as a flat 0 — a price of zero on a position
        that is very much alive, which is the worst kind of dash-instead-of-
        zero failure: it is a zero instead of a NUMBER."""
        inst = _instrument("SHIBUSD")
        _quote(inst, "0.00001300")
        _trade(self.user, symbol="SHIBUSD", entry="0.00001200",
               stop="0.00001000", target="0.00001800", qty="1000000")
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "entry"), "0.000012")
        self.assertEqual(_attr(html, "stop"), "0.00001")
        self.assertEqual(_attr(html, "mark"), "0.000013")

    def test_a_never_scored_trade_shows_no_score_rather_than_zero(self):
        """composite_score defaults to 0 and a hand-taken entry never sets
        it, so 0 means "never scored", not "scored zero"."""
        inst = _instrument("ADAUSD")
        _quote(inst, 1)
        _trade(self.user, symbol="ADAUSD", entry=1, stop=0.9, target=1.2,
               score=0, rule="", reason="")
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "score"), "")


class NoSignalDegradesCleanlyTests(TestCase):
    """A fork, a hand-taken entry, or a rule renamed since the entry — none
    of them has a Signal to join, and the card must survive all three."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pd_sig", password="x")

    def setUp(self):
        self.inst = _instrument()
        _quote(self.inst, 61000)
        self.client.force_login(self.user)

    def test_a_manual_trade_with_no_signal_renders_empty_signal_fields(self):
        _trade(self.user, rule="manual", reason="operator entry")
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "signal"), "")
        self.assertEqual(_attr(html, "signal-score"), "")
        self.assertEqual(_attr(html, "signal-sub"), "")
        # The rest of the card is unaffected — a missing signal must not
        # take the reason and the score down with it.
        self.assertEqual(_attr(html, "reason"), "operator entry")

    def test_a_fork_named_rule_with_no_matching_signal_is_not_mismatched(self):
        """`parent_evolved_v2` has its own signals or none. Falling back to
        the PARENT's signal would attribute the fork's trade to evidence it
        never saw, which is the one thing worse than showing nothing."""
        from signals.models import Signal
        Signal.objects.create(
            instrument=self.inst, signal_type="technical", direction="bullish",
            urgency="high", title="parent fired", description="d",
            rule_name="breakout_1h", score=0.9, sub_scores={"trend": 0.9},
            price_at_signal=Decimal("60000"), is_active=True)
        _trade(self.user, rule="breakout_1h_evolved_v2")
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "signal"), "")

    def test_a_recorded_signal_id_wins_and_brings_its_sub_scores(self):
        from signals.models import Signal
        sig = Signal.objects.create(
            instrument=self.inst, signal_type="technical", direction="bullish",
            urgency="high", title="20d breakout on 3x volume", description="d",
            rule_name="breakout_1h", score=0.79,
            sub_scores={"trend": 0.9, "volume": 0.7},
            price_at_signal=Decimal("60000"), is_active=True)
        _trade(self.user, metadata={"signal_id": sig.id})
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertEqual(_attr(html, "signal"), "20d breakout on 3x volume")
        self.assertEqual(_attr(html, "signal-score"), "0.79")
        self.assertEqual(_attr(html, "signal-dir"), "bullish")
        self.assertIn("trend 0.90", _attr(html, "signal-sub"))

    def test_a_book_position_with_no_trade_behind_it_still_renders(self):
        """portfolio.Position rows come from the shared book. They have no
        trade, no forensics page and nothing that could flatten them — the
        row must render with empty attributes rather than 500."""
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        Position.objects.create(
            portfolio=get_or_create_default_portfolio(), instrument=self.inst,
            direction="long", quantity=Decimal("1"),
            entry_price=Decimal("60000"), current_price=Decimal("61000"),
            opened_at=timezone.now())
        resp = self.client.get(POSITIONS)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8", "replace")
        # No timeline is offered for a row that has none.
        self.assertIn('data-pos-href=""', html)


class CloseActionTests(TestCase):
    """The operator should not have to hunt for the row again after reading
    on the card why the position is losing."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pd_close", password="x")

    def setUp(self):
        self.inst = _instrument()
        _quote(self.inst, 61000)
        self.trade = _trade(self.user)
        self.client.force_login(self.user)

    def test_the_row_still_carries_the_close_button_the_card_proxies_to(self):
        """The card's button is a proxy: it clicks THIS one, so base.html's
        delegated flow runs unchanged and can still find the row to retire.
        A copy of the flow on a body-portalled card would have closed the
        position and left the row reading OPEN."""
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertIn('data-sv-close-trade="%d"' % self.trade.id, html)
        js = _static("js", "sv-position-card.js")
        self.assertIn('row.querySelector("[data-sv-close-trade]")', js)
        self.assertIn("rowClose.click()", js)

    def test_the_card_never_implements_the_close_itself(self):
        """One close path, one confirm, one PIN rule. A fetch on this card
        would be a second one, and the second one is the one that forgets
        the PIN gate."""
        js = _static("js", "sv-position-card.js")
        self.assertNotIn("close/preview", js)
        self.assertNotIn("SV.overlay.confirm", js)

    def test_the_existing_endpoint_is_what_that_button_reaches(self):
        """Pinned at the route, so a rename on either side fails here rather
        than silently at the operator's fingertip. What the preview then
        ANSWERS is tests/test_manual_close.py's subject, not this file's —
        duplicating it here would be a second set of expectations about one
        endpoint, which is the same mistake the card itself refuses to make."""
        from django.urls import resolve
        url = "/positions/%d/close/preview/" % self.trade.id
        self.assertEqual(resolve(url).url_name, "close_position_preview")
        # A state change on GET is refused — the route is live and gated.
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_another_users_trade_is_not_on_this_page_at_all(self):
        """The card would happily render whatever the row carried, so the
        scoping has to hold at the queryset."""
        other = get_user_model().objects.create_user("pd_other", password="x")
        theirs = _trade(other, symbol="BTCUSD", config=_config(other, "theirs"))
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertNotIn('data-sv-close-trade="%d"' % theirs.id, html)
        self.assertNotIn("/forensics/%d/" % theirs.id, html)


class CardChromeTests(TestCase):
    """Where the card is painted, and in what."""

    def test_the_card_is_portalled_to_body(self):
        """A fixed band above it carries backdrop-filter, which creates a
        stacking context and clamps every child inside it — so the card
        cannot live in the table."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn("d.body.appendChild(pop)", js)

    def test_the_card_rides_the_hovercard_token_and_no_raw_number(self):
        css = _static("css", "sauron.css")
        self.assertIn(".pos-pop", css)
        block = css.split(".pos-pop {", 1)[1].split(".pop-spark {", 1)[0]
        self.assertNotIn("z-index", block,
                         "a floating element with its own numeric z-index "
                         "is a bug — the ladder tokens are the only answer")
        # It inherits the token from .nf-pop, which the ladder also restates.
        self.assertIn("z-index: var(--z-hovercard", css)
        self.assertIn(".nf-pop", _static("css", "sv-overlay.css"))

    def test_the_card_states_gaps_in_the_house_style(self):
        js = _static("js", "sv-position-card.js")
        self.assertIn('DASH = "—"', js)
        self.assertIn("sv-unknown", js)

    def test_gold_that_prints_on_white_uses_the_ink_token(self):
        """--accent-gold is dark-theme neon and is nearly invisible on the
        light card."""
        css = _static("css", "sauron.css")
        block = css.split(".pos-pop-pending {", 1)[1].split("}", 1)[0]
        self.assertIn("--accent-gold-ink", block)
        self.assertNotIn("var(--accent-gold)", block)

    def test_the_card_honours_reduced_motion(self):
        css = _static("css", "sauron.css")
        self.assertRegex(
            css,
            r"@media \(prefers-reduced-motion: reduce\) \{\s*\.pos-pop \{ animation: none")

    def test_the_card_cannot_scroll_sideways_on_a_360px_screen(self):
        """.nf-pop's 340px floor plus its padding is wider than the room a
        360px viewport leaves, and every long token on the card — a rule
        name, a symbol, a reason — has to wrap rather than push."""
        css = _static("css", "sauron.css")
        self.assertIn("@media (max-width: 420px)", css)
        block = css.split("@media (max-width: 420px) {", 1)[1].split("\n        }", 1)[0]
        self.assertIn(".pos-pop { min-width: 0", block)
        self.assertIn("overflow-wrap: anywhere",
                      css.split(".pos-pop-why-body {", 1)[1].split("}", 1)[0])


class SharedDwellEngineTests(TestCase):
    """One engine, four consumers. The news feed, the briefing history and
    the notification card each shipped their own copy of this; the position
    card was the point at which it was lifted out instead of copied again."""

    def test_the_engine_is_published_rather_than_duplicated(self):
        js = _static("js", "sv-notif-card.js")
        self.assertIn("w.SV.dwell", js)
        self.assertIn("function attach(opts)", js)
        card = _static("js", "sv-position-card.js")
        self.assertIn("w.SV.dwell.attach", card)
        # The card must not have grown its own placement or timing code.
        for copied in ("getBoundingClientRect", "setTimeout", "pointerover"):
            self.assertNotIn(copied, card,
                             "the position card re-implemented %r instead of "
                             "using the shared engine" % copied)

    def test_the_dwell_contract_the_other_three_paid_for_survives(self):
        js = _static("js", "sv-notif-card.js")
        self.assertIn("HOVER_DELAY_MS = 2000", js)
        self.assertIn("pop.contains(to)", js)
        self.assertIn("pointerleave", js)
        self.assertIn("isCollapsed", js)
        self.assertIn("(hover: hover)", js)
        self.assertIn('row.closest("[data-sv-overlay]")', js)

    def test_it_is_delegated_from_document_so_a_swapped_row_still_opens(self):
        """The other half of this page owns the refresh region. A listener
        bound to the table would die with the first swap, and the row that
        replaced it would be inert."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn('d.addEventListener("pointerover"', js)
        self.assertIn('d.addEventListener("click"', js)

    def test_an_open_card_redraws_or_closes_when_the_row_changes(self):
        """A card quoting the mark from before the last refresh is worse
        than no card: the operator reads a stale distance-to-stop and acts
        on it."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn("MutationObserver", js)
        self.assertIn("if (inst.row && !d.contains(inst.row)) inst.hide()", js)
        self.assertIn("inst.rowObs.observe(inst.row", js)

    def test_the_page_ships_the_consumer(self):
        user = get_user_model().objects.create_user("pd_ship", password="x")
        self.client.force_login(user)
        html = self.client.get(POSITIONS).content.decode("utf-8", "replace")
        self.assertIn("js/sv-position-card.js", html)

    def test_the_notification_card_still_works_off_the_same_engine(self):
        """Generalising it must not have cost the consumer it came from."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn('rows: ROW', js)
        self.assertIn("nf-pop nc-pop", js)
        self.assertIn("data-nc-row", js)
