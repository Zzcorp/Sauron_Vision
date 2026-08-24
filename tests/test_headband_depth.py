"""The headband's popups say more, and say WHEN.

Two asks: richer popup details — the news rows especially, which now
carry a dwell-card (summary, sentiment, source, age) after a second's
hover — and an age stamp on the money popups, because a 20-second-cached
figure labelled as live is a small lie repeated forever.

Run with:  python manage.py test tests.test_headband_depth
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


class NewsDwellTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("hbd_u",
                                                         password="x")
        self.client.force_login(self.user)

    def _article(self, **kw):
        from scraping.models import NewsArticle
        defaults = dict(title="Fed cuts rates", source="Reuters",
                        url="https://example.com/fed",
                        published_at=timezone.now(),
                        content_summary="A short machine summary.",
                        ai_sentiment_score=0.42)
        defaults.update(kw)
        return NewsArticle.objects.create(**defaults)

    def test_news_rows_carry_the_dwell_payload(self):
        """The card's facts ride the row as data attributes — the engine
        never fetches, so what the row carries is all the card can say."""
        self._article()
        body = self.client.get("/instruments/").content.decode()
        self.assertIn("hb-news-row", body)
        self.assertIn('data-nw-source="Reuters"', body)
        self.assertIn("data-nw-sent=\"0.42\"", body)
        self.assertIn("A short machine summary.", body)
        self.assertIn("js/sv-news-dwell.js", body)

    def test_an_unscored_article_ships_an_empty_sentiment_not_a_zero(self):
        """0.00 sentiment is a MEASURED neutral; an article the analyst
        pass has not reached must ship nothing at all."""
        self._article(ai_sentiment_score=None, title="Unscored piece")
        body = self.client.get("/instruments/").content.decode()
        self.assertIn('data-nw-sent=""', body)

    def test_a_hostile_headline_cannot_break_out_of_its_attribute(self):
        """Headlines are scraped third-party text riding data attributes;
        autoescape must hold after truncatechars or a crafted title is an
        attribute-injection vector on every authenticated page."""
        self._article(title='Fed "pivots" & cuts <fast>',
                      source='A&B "Wire"',
                      content_summary='He said "sell" & <run>')
        body = self.client.get("/instruments/").content.decode()
        self.assertIn(
            'data-nw-title="Fed &quot;pivots&quot; &amp; cuts &lt;fast&gt;"',
            body)
        self.assertIn('data-nw-source="A&amp;B &quot;Wire&quot;"', body)
        self.assertNotIn('data-nw-title="Fed "', body)

    def test_the_dead_url_attribute_stays_dead(self):
        """The card routes to the internal news page, never the article's
        own domain — so the row carries no external URL at all."""
        self._article()
        body = self.client.get("/instruments/").content.decode()
        self.assertNotIn("data-nw-url", body)

    def test_the_card_acts_for_the_audience_that_sees_it(self):
        """Only hover devices ever see the card, and the engine routes
        their clicks through `click:` — a tap-only handler advertised
        an action no viewer could take. Both worlds share one follow()."""
        src = self._dwell_src()
        self.assertIn("click: follow", src)
        self.assertIn("tap: follow", src)
        self.assertIn("opens the news page", src)
        self.assertIn("nf-pop-summary", src)
        self.assertNotIn("nfi-detail", src)

    def test_the_card_and_the_dropdown_share_a_grace(self):
        """The portalled dropdown's 120ms leave-timer fired when the
        pointer stepped onto the card — folding the NEWS panel under it.
        The bridge and the hide-with-panel hook must both exist."""
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        dwell = self._dwell_src()
        self.assertIn("_svCancelHide", dwell)
        self.assertIn("_svHideSoon", dwell)
        shell = (base / "templates" / "base.html").read_text(
            encoding="utf-8")
        self.assertIn("dd._svCancelHide = cancelHide", shell)
        self.assertIn("dd._svHideSoon = hideSoon", shell)
        self.assertIn("hideWithin(dd)", shell)
        engine = (base / "static" / "js" / "sv-notif-card.js").read_text(
            encoding="utf-8")
        self.assertIn("hideWithin:", engine)

    def _dwell_src(self):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "static" / "js"
                / "sv-news-dwell.js").read_text(encoding="utf-8")

    def test_the_dwell_client_asks_for_the_deliberate_second(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "static" / "js"
               / "sv-news-dwell.js").read_text(encoding="utf-8")
        self.assertIn("delay: 1000", src)
        self.assertIn('rows: ".hb-news-row"', src)
        self.assertIn("SV.dwell.attach", src)


class AgeStampTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("hbd_v",
                                                         password="x")
        self.client.force_login(self.user)

    def test_the_portfolio_popup_states_when_it_was_measured(self):
        """panel_* is cached PANEL_TTL seconds; the note owns up to it
        with the computation time instead of impersonating a live tick."""
        body = self.client.get("/instruments/").content.decode()
        self.assertIn("Measured ", body)
        self.assertIn(" UTC.", body)

    def test_the_measured_stamp_is_marked_ephemeral(self):
        """The stamp moves with every render by design; unmarked, it made
        the headband's no-change short-circuit fire never, platform-wide."""
        body = self.client.get("/instruments/").content.decode()
        self.assertIn("data-sv-live-ephemeral>Measured", body)


class EngineHoldTests(TestCase):
    """The shared sweep engine: fetch always, hold only what the operator
    is actually reading, and never mistake client-painted text for data."""

    def _engine_src(self):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "templates" / "_partials"
                / "live_region.html").read_text(encoding="utf-8")

    def test_the_sweep_holds_only_the_hovered_region(self):
        """The old whole-page deferral let a pointer resting anywhere
        freeze every region on screen — headband included."""
        src = self._engine_src()
        self.assertIn("releaseHeld", src)
        self.assertIn("matches(':hover')", src)
        self.assertIn("held[name] = fresh.innerHTML", src)

    def test_the_fetch_is_never_gated_by_the_pointer(self):
        """Deferral moved into apply(): data always arrives, only the
        swap under the cursor waits for the pointer to move off."""
        src = self._engine_src()
        self.assertIn("Fetch unconditionally", src)

    def test_an_open_card_holds_every_swap(self):
        """A dwell card is a body child — no region's :hover can see the
        operator reading it. The popup registry can, and the sweep asks."""
        src = self._engine_src()
        self.assertIn("window.SV.popup.engaged", src)
        from pathlib import Path

        from django.conf import settings
        card = (Path(settings.BASE_DIR) / "static" / "js"
                / "sv-notif-card.js").read_text(encoding="utf-8")
        self.assertIn("engaged: function", card)

    def test_client_painted_text_does_not_count_as_change(self):
        """Chips, pass stamps and Measured notes are rewritten client-side
        or move with every render — comparing them to raw server markup
        made EVERY sweep a full swap of a page where nothing moved."""
        src = self._engine_src()
        self.assertIn("function canon", src)
        self.assertIn(
            "'[data-sv-live-ephemeral],[data-sv-live-stamp]"
            ",[data-sv-live-status]'", src)

    def test_a_swap_repaints_chips_and_stamps(self):
        """A swap writes the server's raw chip back into the region; the
        engine must repaint from client state or LIVE degrades to a dot."""
        src = self._engine_src()
        between = src.split("function finishSwap")[1].split(
            "function stampSweep")[0]
        self.assertIn("paintChips();", between)
        self.assertIn("stampSweep(carried)", src)


class RiskPageIsLiveTests(TestCase):
    """/risk/ rendered once and froze — the depth view now keeps the
    portfolio page's contract: one live region, a live twin re-rendering
    the same body, refreshed on fills plus the slow sweep."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("risk_live_u",
                                                         password="x")
        self.client.force_login(self.user)

    def test_the_page_carries_its_live_region_and_the_twin_answers(self):
        resp = self.client.get("/risk/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-sv-live="risk-depth"')
        self.assertContains(resp, "/risk/live/")

        live = self.client.get("/risk/live/")
        self.assertEqual(live.status_code, 200)
        self.assertContains(live, 'data-sv-live="risk-depth"')

    def test_the_twin_is_regions_only_never_the_shell(self):
        """The live payload must not carry a second app shell — the swap
        matches regions, and a nested shell would be swapped INTO the
        page wholesale."""
        live = self.client.get("/risk/live/").content.decode()
        self.assertNotIn("sidebar-nav", live)
        self.assertNotIn("info-panel-bar", live)
        # Nor the refresher's own engine: the include is gated behind
        # not-live_only, so the payload is regions, not plumbing.
        self.assertNotIn("<script", live)
        self.assertNotIn("<style", live)

    def test_the_pass_stamp_is_a_client_stamped_readout(self):
        """A raw now-stamp inside the region defeated the no-change
        short-circuit every sweep; the stamp span is repainted client-side
        only by sweeps whose payload carried the risk region."""
        body = self.client.get("/risk/").content.decode()
        self.assertIn('data-sv-live-stamp="risk-depth"', body)


class RiskCostTests(TestCase):
    """/risk/live/ is on a 20s cadence whenever the socket is down — the
    platform's most expensive view cannot be recomputed on every poll."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = get_user_model().objects.create_user("risk_cost_u",
                                                         password="x")
        self.client.force_login(self.user)

    def test_the_heavy_quartet_is_cached_between_sweeps(self):
        from unittest.mock import MagicMock, patch
        cm = MagicMock()
        cm.symbols = []
        with patch("portfolio.correlation.portfolio_correlation",
                   return_value=cm) as pc:
            self.client.get("/risk/live/")
            self.client.get("/risk/live/")
        self.assertEqual(pc.call_count, 1)

    def test_a_changed_book_busts_the_cache_instantly(self):
        """A fill changes the open-position set, and the risk of the NEW
        book must not wait out a TTL measured for the old one."""
        from unittest.mock import MagicMock, patch

        from instruments.models import Instrument
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        cm = MagicMock()
        cm.symbols = []
        with patch("portfolio.correlation.portfolio_correlation",
                   return_value=cm) as pc:
            self.client.get("/risk/live/")
            book = get_or_create_default_portfolio(user=self.user)
            inst, _ = Instrument.objects.get_or_create(
                symbol="RCT", defaults={"name": "RCT",
                                        "asset_class": "stock"})
            Position.objects.create(
                portfolio=book, instrument=inst, direction="long",
                quantity=Decimal("1"), entry_price=Decimal("100"),
                current_price=Decimal("100"),
                opened_at=timezone.now())
            self.client.get("/risk/live/")
        self.assertEqual(pc.call_count, 2)

    def test_the_engine_scans_history_once_for_metrics_and_var(self):
        """calculate_risk_metrics and calculate_var ask for the same
        252-day series; the memo must hand back the very same object."""
        from portfolio.risk_engine import RiskEngine
        from portfolio.services import get_or_create_default_portfolio
        engine = RiskEngine(get_or_create_default_portfolio(user=self.user))
        self.assertIs(engine._get_position_returns([]),
                      engine._get_position_returns([]))
