"""One open card must not freeze the whole page, and a suggested price
must not carry eight decimals.

Four things the operator reported, and one of them explains another.

THE HEADBAND WAS NOT LIVE. `apply()` computed `busy = engaged()` — a
PAGE-WIDE answer — and deferred every region when it was true. So
reading any hover card froze the headband, the bottom panel and every
strip on screen until the pointer moved off. That is exactly the
whole-page deferral the sweep's own comment says was removed in favour
of per-region holds. It now asks which region a card is anchored in.

THE CARD SOMETIMES STOPPED SHOWING. `inst.held` latches on a pointerdown
on a card and is cleared by a window pointerup or pointercancel — both
of which can be missed when the release happens outside the browser
window. A latch cleared only by an event that can go missing is one that
eventually sticks, and a stuck one leaves the card unclosable and, now
that the sweep reads it, holds that region for the rest of the session.
It self-releases.

THE SIGNAL CARD PRINTED RAW DECIMALS. `suggested_entry` is
`decimal_places=8` and was rendered with no filter at all, so 82.45 came
out as 82.45000000.

Run with:  python manage.py test tests.test_headband_depth_2
"""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

BASE = Path(settings.BASE_DIR)


class ThePageStaysLiveWhileOneCardIsReadTests(SimpleTestCase):
    def _sweep(self):
        return (BASE / "templates" / "_partials" / "live_region.html").read_text(
            encoding="utf-8")

    def test_the_sweep_asks_which_region_not_whether_any(self):
        s = self._sweep()
        self.assertIn("readingFrom(node)", s)
        self.assertNotIn("var busy = engaged();", s)

    def test_the_engine_can_answer_per_region(self):
        js = (BASE / "static" / "js" / "sv-notif-card.js").read_text(
            encoding="utf-8")
        self.assertIn("anchoredIn:", js)

    def test_it_falls_back_to_the_page_wide_answer(self):
        """An older engine must defer more, not less: a stale cell beats
        one that changes under the operator's eyes."""
        seg = self._sweep().split("function readingFrom")[1][:400]
        self.assertIn("return engaged();", seg)

    def test_a_hovered_region_still_holds(self):
        """The per-region hold is the point, not a casualty of the fix."""
        self.assertIn("node.matches(':hover')", self._sweep())


class TheHeldLatchReleasesItselfTests(SimpleTestCase):
    def test_a_press_that_never_lifts_does_not_latch_forever(self):
        js = (BASE / "static" / "js" / "sv-notif-card.js").read_text(
            encoding="utf-8")
        seg = js.split('pop.addEventListener("pointerdown"')[1][:1200]
        self.assertIn("heldTimer", seg)
        self.assertIn("inst.held = false", seg)

    def test_the_window_clears_are_still_there(self):
        """The timeout is a backstop, not a replacement — a normal
        release must still clear it immediately."""
        js = (BASE / "static" / "js" / "sv-notif-card.js").read_text(
            encoding="utf-8")
        self.assertIn('w.addEventListener("pointerup"', js)
        self.assertIn('w.addEventListener("pointercancel"', js)


class TheSignalCardPrintsRealPricesTests(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        self.user = User.objects.create_user("sig_u", password="x")
        self.client.force_login(self.user)
        self.inst = Instrument.objects.create(
            symbol="EURUSD", name="Euro", asset_class="forex", is_active=True)
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("1.08425"),
                                 source="oanda")

    def _signal(self, **kw):
        from signals.models import Signal
        defaults = dict(
            instrument=self.inst, signal_type="technical", direction="bullish",
            urgency="medium", title="t", description="d", rule_name="r",
            score=0.7, price_at_signal=Decimal("1.08425"),
            suggested_entry=Decimal("1.08425"),
            suggested_stop=Decimal("1.08000"),
            suggested_target=Decimal("1.09200"), is_active=True)
        defaults.update(kw)
        return Signal.objects.create(**defaults)

    def test_the_template_uses_the_shared_precision_tag(self):
        src = (BASE / "templates" / "_partials"
               / "signal_rail_items.html").read_text(encoding="utf-8")
        self.assertIn("{% px s.suggested_entry", src)
        self.assertIn("{% px s.suggested_stop", src)
        self.assertIn("{% px s.suggested_target", src)

    def test_no_price_is_rendered_raw_any_more(self):
        """`decimal_places=8` printed unfiltered is where 82.45000000
        came from."""
        src = (BASE / "templates" / "_partials"
               / "signal_rail_items.html").read_text(encoding="utf-8")
        for raw in ('{{ s.suggested_entry|default:"—" }}',
                    '{{ s.suggested_stop|default:"—" }}',
                    '{{ s.suggested_target|default:"—" }}'):
            self.assertNotIn(raw, src)

    def test_the_rr_is_rounded(self):
        src = (BASE / "templates" / "_partials"
               / "signal_rail_items.html").read_text(encoding="utf-8")
        self.assertIn("s.risk_reward_ratio|floatformat:2", src)

    def test_the_card_shows_the_mark_the_levels_are_measured_against(self):
        src = (BASE / "templates" / "_partials"
               / "signal_rail_items.html").read_text(encoding="utf-8")
        self.assertIn("s.instrument.live_quote.last", src)


class TheTakenBannerSaysWhatThePositionIsDoingTests(TestCase):
    def setUp(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        self.user = User.objects.create_user("act_u", password="x")
        self.inst = Instrument.objects.create(
            symbol="BRNUSD", name="Brent", asset_class="commodity",
            is_active=True)
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("84.00"),
                                 source="ibkr")
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name="C", mode="paper",
            symbols=["BRNUSD"], capital=Decimal("10000"), enabled=True)

    def _taken(self, **meta):
        from bot_program.models import AssetBotTrade
        from signals.models import Signal
        sig = Signal.objects.create(
            instrument=self.inst, signal_type="technical", direction="bullish",
            urgency="medium", title="t", description="d",
            rule_name="squeeze", score=0.7,
            price_at_signal=Decimal("82"), is_active=True)
        AssetBotTrade.objects.create(
            config=self.cfg, asset_class="commodity", symbol="BRNUSD",
            side="BUY", qty=Decimal("10"), entry_price=Decimal("82"),
            stop_loss=Decimal("80"), take_profit=Decimal("88"),
            status="OPEN", paper=True, rule_name="squeeze",
            opened_at=timezone.now() + timedelta(seconds=1),
            metadata=meta or {})
        return sig

    def test_the_payload_carries_the_live_levels(self):
        acted = self._taken().acted
        self.assertIsNotNone(acted)
        self.assertEqual(acted["entry"], 82.0)
        self.assertEqual(acted["stop"], 80.0)
        self.assertEqual(acted["target"], 88.0)

    def test_it_carries_the_money_the_bet_is_making(self):
        """(84 - 82) x 10 = 20."""
        self.assertAlmostEqual(self._taken().acted["pnl"], 20.0, places=2)

    def test_it_says_whether_the_stop_rests_at_the_broker(self):
        """The difference between protected while the platform is down
        and protected only while it is up."""
        self.assertTrue(self._taken(protected=True).acted["protected"])
        self.assertFalse(self._taken().acted["protected"])

    def test_an_unquotable_instrument_gives_none_not_zero(self):
        from market_data.models import LiveQuote
        LiveQuote.objects.filter(instrument=self.inst).delete()
        self.inst.refresh_from_db()
        sig = self._taken()
        sig.instrument.refresh_from_db()
        self.assertIsNone(sig.acted["pnl"])


class TheNewsCellCarriesADayOfSentimentTests(TestCase):
    def _article(self, hours_ago, score, title="n"):
        from scraping.models import NewsArticle
        return NewsArticle.objects.create(
            title=title, source="Reuters",
            url=f"https://example.com/{title}-{hours_ago}-{score}",
            published_at=timezone.now() - timedelta(hours=hours_ago),
            content_summary="x", ai_sentiment_score=score)

    def _series(self):
        from core.context_processors import _news_sentiment_24h
        from scraping.models import NewsArticle
        return _news_sentiment_24h(NewsArticle)

    def test_nothing_scored_means_no_graph_rather_than_a_flat_line(self):
        self._article(2, None)
        self.assertIsNone(self._series())

    def test_it_buckets_by_hour(self):
        self._article(3, 0.5, "a")
        self._article(1, -0.4, "b")
        s = self._series()
        self.assertIsNotNone(s)
        self.assertGreaterEqual(len(s["points"]), 2)

    def test_an_unscored_article_is_not_averaged_in_as_neutral(self):
        """The analyst's backlog would otherwise read as equanimity."""
        self._article(2, 0.8, "scored")
        self._article(2, None, "unscored")
        self.assertAlmostEqual(self._series()["mean"], 0.8, places=3)

    def test_the_trend_reads_the_direction(self):
        for h in (23, 22, 21):
            self._article(h, -0.6, f"early{h}")
        for h in (3, 2, 1):
            self._article(h, 0.6, f"late{h}")
        self.assertEqual(self._series()["trend"], "up")

    def test_the_count_is_articles_not_buckets(self):
        self._article(2, 0.5, "a")
        self._article(2, 0.5, "b")
        self.assertEqual(self._series()["n"], 2)
