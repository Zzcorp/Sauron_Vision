"""The headband's OPEN P&L cell, the long/short split, and the one hover beat.

Two operator complaints, one slice.

The first: open P&L — the number the operator glances at most — was the 9px
sub-line under the POSITIONS count, the smallest text on the band. It now has
its own cell, OPEN P&L, right after POSITIONS, rendered at headline size in
the up/down tone, with a dropdown of its own (open P&L, open R, the split, a
Measured stamp). The POSITIONS sub-line that used to carry it now reads
"N long · M short", and the POSITIONS dropdown opens with a split strip above
the rows. All of it comes out of the one context dict the band already reads,
so the new cell can never disagree with the popups that quote the same figure.

The second: hover cards across the platform opened on 90ms, 450ms, 1000ms,
1500ms, 2000ms and on no delay at all, depending on which strip the pointer
was over. There is now ONE beat — window.SV_HOVER_BEAT_MS = 450, declared
inline in base.html's head before any deferred script, with a CSS twin in
sauron.css — and every arming site reads it. Departure grace timers (the
120/260/80ms hides) are deliberately NOT on the beat: leaving is a different
gesture from arriving, and those are pinned unchanged here.

Run with:  python manage.py test tests.test_headband_pnl_and_beat
"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from tests.test_headband_truth import (
    DASH, HOST, LIVE_SOURCE, _components, _config, _ctx, _position, _quote,
    _tick, _trade, _user, cell, dd_value, regions,
)


def _src(*parts):
    return (Path(settings.BASE_DIR).joinpath(*parts)).read_text(
        encoding="utf-8")


def _region(body, name):
    """The inner HTML of a data-sv-live region, up to its sibling cell."""
    m = re.search(r'data-sv-live="%s"[^>]*>' % re.escape(name), body)
    assert m, name
    return body[m.end():m.end() + 6000]


# ── A. The context processor counts sides ────────────────────────────────

class SplitCountTests(TestCase):
    def setUp(self):
        self.user = _user("hb_split")
        _components()
        _tick(_config(self.user))

    def test_an_empty_book_is_zero_long_and_zero_short(self):
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_positions"], 0)
        self.assertEqual((ctx["panel_n_long"], ctx["panel_n_short"]), (0, 0))

    def test_a_bot_buy_and_a_legacy_short_count_one_each(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", side="BUY")
        _quote("AAPL", "100", asset_class="stock")
        _position(self.user, "AAPL", direction="short", current="100")
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_positions"], 2)
        self.assertEqual(ctx["panel_n_long"], 1)
        self.assertEqual(ctx["panel_n_short"], 1)

    def test_a_side_nothing_can_read_dashes_the_split_instead_of_filing_it_long(self):
        """The row itself still renders LONG (the sign has to default
        somewhere for its P&L), but the COUNT must not claim it."""
        _quote("AAPL", "100", asset_class="stock")
        _position(self.user, "AAPL", direction="")
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_positions"], 1)
        self.assertIsNone(ctx["panel_n_long"])
        self.assertIsNone(ctx["panel_n_short"])


# ── B. The cells render, agree, and dash when unmeasured ─────────────────

class OpenPnlCellTests(TestCase):
    def setUp(self):
        self.user = _user("hb_pnl")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def _page(self):
        return self.client.get(LIVE_SOURCE, HTTP_HOST=HOST).content.decode()

    def test_the_open_pnl_cell_sits_right_after_positions_with_its_own_regions(self):
        body = self._page()
        found = regions(body)
        for name in ("hb-pnl", "hb-pnl-sub", "hb-pnl-detail"):
            self.assertIn(name, found, name)
        self.assertLess(body.index('data-sv-live="hb-pos-detail"'),
                        body.index('data-sv-live="hb-pnl"'))
        self.assertLess(body.index('data-sv-live="hb-pnl"'),
                        body.index('data-sv-live="hb-bot-state"'))
        self.assertIn('class="ip-cat ip-cat-link ip-cat-pnl"', body)

    def test_the_cell_quotes_the_same_open_pnl_as_the_portfolio_popup(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", entry="100")
        body = self._page()
        value = cell(body, "hb-pnl")
        self.assertEqual(value, "+10.00")
        self.assertEqual(value, dd_value(body, "OPEN P&L"))
        self.assertIn("across 1 position<", _region(body, "hb-pnl-sub"))

    def test_the_cell_carries_its_tone_on_a_child_so_a_refresh_keeps_it(self):
        _quote("BTCUSD", "90")
        _trade(self.user, "BTCUSD", entry="100")
        pnl = _region(self._page(), "hb-pnl")[:200]
        self.assertIn('<span class="down"', pnl)

    def test_an_unmarked_book_dashes_the_cell_and_never_prints_zero(self):
        _trade(self.user, "NOQUOTE", entry="100")
        body = self._page()
        self.assertEqual(cell(body, "hb-pnl"), DASH)
        # The figure sums the PRICED rows only — with none priced the
        # sub must say so rather than claim coverage it lacks.
        self.assertIn("across 0 of 1 positions", _region(body, "hb-pnl-sub"))

    def test_an_empty_book_says_none_open_under_a_dash(self):
        body = self._page()
        self.assertEqual(cell(body, "hb-pnl"), DASH)
        self.assertIn("none open", _region(body, "hb-pnl-sub")[:120])

    def test_the_pnl_popup_states_when_it_was_measured_as_ephemeral(self):
        detail = _region(self._page(), "hb-pnl-detail")
        self.assertRegex(
            detail, r"<span data-sv-live-ephemeral>Measured \d\d:\d\d:\d\d UTC")
        for label in ("OPEN R", "LONG", "SHORT", "GRADED", "PRICED"):
            self.assertIn('<span class="dk">%s</span>' % label, detail, label)

    def test_the_pnl_popup_split_matches_the_positions_sub_line(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", side="BUY")
        _quote("AAPL", "100", asset_class="stock")
        _position(self.user, "AAPL", direction="short", current="100")
        body = self._page()
        detail = _region(body, "hb-pnl-detail")
        self.assertEqual(dd_value(detail, "LONG"), "1")
        self.assertEqual(dd_value(detail, "SHORT"), "1")
        sub = _region(body, "hb-pos-sub")[:400]
        self.assertIn('<span class="up">1 long</span>', sub)
        self.assertIn('<span class="down">1 short</span>', sub)


class PositionsSplitStripTests(TestCase):
    def setUp(self):
        self.user = _user("hb_strip")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def _page(self):
        return self.client.get(LIVE_SOURCE, HTTP_HOST=HOST).content.decode()

    def test_the_strip_sits_above_the_rows_inside_the_live_region(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", entry="100", stop_loss=Decimal("95"))
        detail = _region(self._page(), "hb-pos-detail")
        strip = detail.index('class="ip-split"')
        self.assertLess(strip, detail.index('class="ip-pos '))
        self.assertIn("&#9650; 1 LONG", detail)
        self.assertIn("&#9660; 0 SHORT", detail)
        self.assertRegex(detail, r'ip-split-pnl up">\s*\+10\.00')

    def test_an_empty_book_draws_no_strip(self):
        detail = _region(self._page(), "hb-pos-detail")
        self.assertNotIn('class="ip-split"', detail[:3000])
        self.assertIn("none open", _region(self._page(), "hb-pos-sub")[:80])

    def test_an_unreadable_side_dashes_the_strip_and_the_sub_line(self):
        _quote("AAPL", "100", asset_class="stock")
        _position(self.user, "AAPL", direction="")
        body = self._page()
        self.assertIn("sv-unknown", _region(body, "hb-pos-sub")[:200])
        self.assertNotIn("1 long", _region(body, "hb-pos-sub")[:200])
        self.assertIn('ip-split-side sv-unknown', _region(body, "hb-pos-detail"))

    def test_the_positions_cell_and_its_strip_still_flash_through_one_refresher(self):
        css = _src("static", "css", "sauron.css")
        self.assertIn(".ip-cat-pnl .ip-count {", css)
        self.assertIn(".ip-split {", css)


# ── C. One hover beat ────────────────────────────────────────────────────

class HoverBeatTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = _src("templates", "base.html")
        cls.css = _src("static", "css", "sauron.css")
        cls.engine = _src("static", "js", "sv-notif-card.js")
        cls.dwell = _src("static", "js", "sv-news-dwell.js")
        cls.briefing = _src("templates", "dashboard", "briefing.html")
        cls.feed = _src("templates", "dashboard", "news_feed.html")

    def test_the_pnl_sub_owns_up_to_a_partial_book(self):
        """The figure sums only the PRICED rows — saying "across 4
        positions" over a sum of two is a small lie in a big font."""
        self.assertIn("panel_positions_priced < panel_positions", self.base)
        self.assertIn("of {{ panel_positions }} positions", self.base)
        self.assertIn('data-sv-live="hb-pnl-sub" title="{{ panel_book_coverage }}"',
                      self.base)

    def test_the_beat_is_declared_in_head_before_any_deferred_script(self):
        head = self.base[:self.base.index("</head>")]
        decl = head.index("window.SV_HOVER_BEAT_MS = 450;")
        self.assertLess(decl, head.index(" defer>"))
        self.assertLess(decl, head.index("sv-notif-card.js"))

    def test_the_beat_has_exactly_one_source(self):
        """A CSS twin nothing consumed was a second number free to
        drift from the one every hover actually reads."""
        self.assertNotIn("--sv-hover-beat", self.css)
        self.assertNotIn("--sv-hover-beat", self.base)

    def test_the_dwell_engine_reads_the_beat_and_still_exports_it(self):
        self.assertIn("HOVER_DELAY_MS = (w.SV_HOVER_BEAT_MS || 450)",
                      self.engine)
        self.assertIn("HOVER_DELAY_MS: HOVER_DELAY_MS", self.engine)
        self.assertNotIn("HOVER_DELAY_MS = 2000", self.engine)

    def test_the_news_dwell_client_stops_overriding_the_delay(self):
        self.assertNotRegex(self.dwell, r"delay:\s*\d")

    def test_the_feed_and_the_briefing_read_the_beat(self):
        for src in (self.briefing, self.feed):
            self.assertIn("HOVER_DELAY_MS = (window.SV_HOVER_BEAT_MS || 450)",
                          src)
            self.assertNotIn("HOVER_DELAY_MS = 2000", src)

    def test_the_signals_rail_arms_on_the_beat_and_cancels_on_leave(self):
        rail = self.base[self.base.index("enterTimer = setTimeout("):][:900]
        self.assertIn("}, window.SV_HOVER_BEAT_MS || 450);", rail)
        self.assertNotIn("}, 90);", rail)
        self.assertIn("if (enterTimer) { clearTimeout(enterTimer); "
                      "enterTimer = null; }", rail)

    def test_the_instrument_preview_arms_on_the_beat(self):
        start = self.base.index("// Instrument preview on hover")
        block = self.base[start:start + 700]
        self.assertIn("}, window.SV_HOVER_BEAT_MS || 450);", block)
        self.assertNotIn("1500", block)
        self.assertIn("if (hoverTimer) clearTimeout(hoverTimer);", block)

    def test_the_portal_popups_arm_on_the_beat_and_cancel_on_leave(self):
        start = self.base.index("function armPortal(")
        arm = self.base[start:start + 700]
        self.assertIn("}, window.SV_HOVER_BEAT_MS || 450);", arm)
        self.assertIn("if (item._svBeat) { clearTimeout(item._svBeat); "
                      "item._svBeat = null; }", arm)
        for sel in ("'.dh-pop', 380", "'.wl-pop', 380, 'left'",
                    "'.ticker-popup', 420"):
            self.assertIn("armPortal(item, %s)" % sel, self.base, sel)
        self.assertNotRegex(
            self.base,
            r"mouseenter', function\(\)\{ showPortalPopup\(")

    def test_the_band_dropdowns_arm_on_the_beat_and_cancel_on_leave(self):
        start = self.base.index("var openTimer = null;")
        block = self.base[start:start + 2600]
        self.assertIn("window.SV_HOVER_BEAT_MS || 450);", block)
        self.assertIn("if (openTimer) { clearTimeout(openTimer); "
                      "openTimer = null; }", block)
        # An already-open dropdown is not re-armed on re-entry.
        self.assertIn("if (dd.style.display === 'block') return;", block)

    def test_departure_grace_timers_are_not_on_the_beat(self):
        """Hides are a different gesture: the 120ms band grace, the 260ms
        rail grace and the 80ms tooltip grace stay exactly as they were."""
        self.assertIn("}, 120);", self.base)
        self.assertIn("hideTimer = setTimeout(function() { hidePopup(wrap); }, 260);",
                      self.base)
        self.assertIn("}, 80);", self.base)

    def test_no_hover_card_site_keeps_a_private_delay(self):
        for src, name in ((self.base, "base"), (self.engine, "engine"),
                          (self.briefing, "briefing"), (self.feed, "feed")):
            self.assertNotIn("HOVER_DELAY_MS = 2000", src, name)
        self.assertNotIn("delay: 1000", self.dwell)
