"""Ticker popups carry the trade, and events raise a banner.

Two gaps this pins.

The signal popup showed score, urgency and direction — so hovering told you
a setup existed and nothing about the trade it proposes. The levels ARE the
signal: where to get in, where you are wrong, and what you are playing for.

And the platform pushed fill_open, fill_close and close_pending on a per-user
socket that nothing listened to, so a position opening or closing produced no
acknowledgement anywhere in the interface. new_signal did not exist at all.

Run with:  python manage.py test tests.test_ticker_and_banners
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": "Bitcoin", "asset_class": asset_class})
    return inst


class TickerCompositionTests(TestCase):
    """Everything in the ticker except news duplicated another surface:
    quotes duplicated the price headband above it, signals duplicated the
    rail beside it. The ticker is NEWS ONLY now — the one feed with no
    other home."""

    def setUp(self):
        self.user = User.objects.create_user(username="tq_u", password="x")
        self.inst = _instrument("ETHUSD")

    def _ticker(self):
        from core.context_processors import sauron_context
        req = RequestFactory().get("/")
        req.user = self.user
        return sauron_context(req).get("ticker_items") or []

    def test_quotes_never_reach_the_ticker(self):
        from market_data.models import LiveQuote
        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("2000"), "change_pct": Decimal("1.5")})
        self.assertFalse(
            [i for i in self._ticker() if i.get("type") == "quote"],
            "a quote item reached the ticker — prices belong to the headband")

    def test_news_still_reaches_the_ticker_and_signals_never_do(self):
        from django.utils import timezone as tz
        from scraping.models import NewsArticle
        from signals.models import Signal
        Signal.objects.create(
            instrument=self.inst, signal_type="technical",
            direction="bullish", urgency="high", title="ETH LONG",
            description="d", rule_name="r", score=0.7, sub_scores={},
            price_at_signal=Decimal("100"), is_active=True)
        NewsArticle.objects.create(
            title="Copper rallies", source="Reuters",
            url="https://example.test/copper", published_at=tz.now())
        types = {i.get("type") for i in self._ticker()}
        self.assertIn("news", types)
        self.assertNotIn("signal", types,
                         "a signal item reached the ticker — signals "
                         "belong to the rail")

    def test_new_signals_enter_the_rail_at_the_top(self):
        """The rail is a FEED — newest first. Ranking by score parked a
        strong old signal at the front for days while new arrivals appeared
        buried mid-stream; the score is already painted on every card, the
        position should carry recency."""
        from django.utils import timezone as tz
        from core.context_processors import sauron_context
        from signals.models import Signal

        def make(symbol, score):
            inst = _instrument(symbol)
            return Signal.objects.create(
                instrument=inst, signal_type="technical",
                direction="bullish", urgency="high", title=symbol,
                description="d", rule_name="r", score=score, sub_scores={},
                price_at_signal=Decimal("100"), is_active=True)

        old_strong = make("BTCUSD", 0.95)
        Signal.objects.filter(pk=old_strong.pk).update(
            created_at=tz.now() - timedelta(days=2))
        make("ETHUSD", 0.40)

        req = RequestFactory().get("/")
        req.user = self.user
        ctx = sauron_context(req)
        rail = ctx.get("panel_recent_signals") or []
        self.assertEqual(rail[0].instrument.symbol, "ETHUSD",
                         "the rail's top slot belongs to the newest signal")


class RailDismissTests(TestCase):
    """Dismissal existed only as PASS inside the hover popup — functional
    and undiscovered. Each rail card now carries its own ×, wired to the
    same client-side mechanism (localStorage hide: the engine still sees
    the signal; a UI click must never delete evidence the bots act on)."""

    def test_each_rail_card_carries_a_dismiss_button(self):
        from decimal import Decimal as D
        from signals.models import Signal
        user = User.objects.create_user(username="dx_u", password="x")
        inst = _instrument("BTCUSD")
        Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="high", title="t", description="d", rule_name="r",
            score=0.7, sub_scores={}, price_at_signal=D("100"),
            is_active=True)
        self.client.force_login(user)
        resp = self.client.get("/instruments/", HTTP_HOST="127.0.0.1")
        html = resp.content.decode()
        self.assertIn("sr-x", html)
        self.assertIn("dismissSignal", html)


class NewSignalEventTests(TestCase):
    """A new setup is the thing an operator most wants to know the moment it
    happens, and the socket carried only fills."""

    def test_persisting_a_signal_pushes_a_banner_event(self):
        from unittest.mock import patch
        inst = _instrument("SOLUSD")
        User.objects.create_user(username="banner_staff", password="x",
                                 is_staff=True)
        payload = {
            "symbol": "SOLUSD", "rule": "golden_cross", "direction": "LONG",
            "score": 0.8, "headline": "SOLUSD LONG", "thesis": "t",
            "entry": 100.0, "stop": 98.0, "target": 104.0,
        }
        with patch("dashboard.consumers.push_eye_event") as push:
            from signals.tasks import _create_signals_and_notify
            created = _create_signals_and_notify([payload])
        self.assertEqual(created, 1)
        kinds = [c.args[1] for c in push.call_args_list if len(c.args) > 1]
        self.assertIn("new_signal", kinds)

    def test_a_failed_push_never_loses_the_signal(self):
        """The row is already persisted; a broken socket must not abort the
        scan or roll anything back."""
        from unittest.mock import patch
        from signals.models import Signal
        _instrument("XRPUSD")
        User.objects.create_user(username="banner_staff2", password="x",
                                 is_staff=True)
        with patch("dashboard.consumers.push_eye_event",
                   side_effect=RuntimeError("socket down")):
            from signals.tasks import _create_signals_and_notify
            created = _create_signals_and_notify([{
                "symbol": "XRPUSD", "rule": "r", "direction": "LONG",
                "score": 0.7, "entry": 1.0,
            }])
        self.assertEqual(created, 1)
        self.assertEqual(Signal.objects.filter(rule_name="r").count(), 1)


class BannerMarkupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bm_u", password="x")
        self.client.force_login(self.user)

    def test_the_banner_stack_and_socket_client_ship_on_every_page(self):
        r = self.client.get("/asset-bots/", HTTP_HOST="127.0.0.1")
        body = r.content.decode("utf-8", "replace")
        self.assertIn('id="svBannerStack"', body)
        self.assertIn("/ws/eye/", body,
                      "the banner client is not connected to the event socket")

    def test_every_pushed_event_kind_is_handled_by_the_client(self):
        """A kind the client does not recognise renders nothing at all, so
        the two halves have to agree."""
        r = self.client.get("/asset-bots/", HTTP_HOST="127.0.0.1")
        body = r.content.decode("utf-8", "replace")
        for kind in ("new_signal", "fill_open", "fill_close", "close_pending"):
            self.assertIn(kind, body, msg=f"{kind} has no banner branch")

    def test_a_failed_close_banner_is_sticky(self):
        """Everything else self-dismisses; a position still open at the
        broker after a rejected close needs a human, so it must not vanish
        while nobody is looking."""
        r = self.client.get("/asset-bots/", HTTP_HOST="127.0.0.1")
        body = r.content.decode("utf-8", "replace")
        self.assertIn("close_pending: 0", body)


class LightModeShadowTests(TestCase):
    """The shadow stack was authored for a near-black ground. body.light-mode
    swapped the colour tokens and never touched box-shadow, so the same
    insets rendered as grey smudges pressed into the headband and cards."""

    def _css(self):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css").read_text(
            encoding="utf-8", errors="replace")

    def test_light_mode_overrides_the_headband_shadow(self):
        css = self._css()
        self.assertIn("body.light-mode .data-headband", css)

    def test_light_mode_overrides_the_card_shadow(self):
        self.assertIn("body.light-mode .card,", self._css())

    def test_the_modal_scrims_are_left_dark(self):
        """Those are `inset: 0` overlays that are supposed to be dark;
        lightening them would destroy the focus they exist to create."""
        css = self._css()
        self.assertNotIn("body.light-mode .modal-overlay", css)
        self.assertNotIn("body.light-mode .sidebar-overlay", css)


class SignalRailLiveTests(TestCase):
    """The WS push that was never wired: push_signal_notification had ZERO
    call sites, so the rail only ever changed on a page load. A post_save
    receiver is the one choke point every creation path shares, and the
    partial endpoint is what the browser refetches when the push fires —
    the new card slides in instead of waiting for a reload."""

    def setUp(self):
        self.user = User.objects.create_user(username="rl_u", password="x")

    def _signal(self, inst, **kw):
        from signals.models import Signal
        defaults = dict(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="high", title="t", description="d", rule_name="r",
            score=0.7, sub_scores={}, price_at_signal=Decimal("100"),
            is_active=True)
        defaults.update(kw)
        return Signal.objects.create(**defaults)

    def test_creating_an_active_signal_pushes_to_the_socket(self):
        from unittest.mock import patch
        inst = _instrument("BTCUSD")
        with patch("dashboard.consumers.push_signal_notification") as mock_push:
            self._signal(inst)
        mock_push.assert_called_once()
        self.assertEqual(mock_push.call_args.args[0]["symbol"], "BTCUSD")

    def test_inactive_creations_and_saves_stay_silent(self):
        from unittest.mock import patch
        inst = _instrument("ETHUSD")
        with patch("dashboard.consumers.push_signal_notification") as mock_push:
            sig = self._signal(inst, is_active=False)
        mock_push.assert_not_called()
        # Updates must not re-announce either — created only.
        with patch("dashboard.consumers.push_signal_notification") as mock_push:
            sig.score = 0.9
            sig.save(update_fields=["score"])
        mock_push.assert_not_called()

    def test_the_partial_returns_only_the_cards(self):
        inst = _instrument("BTCUSD")
        self._signal(inst)
        self.client.force_login(self.user)
        resp = self.client.get("/partials/signal-rail/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "sr-signal-wrap")
        self.assertNotContains(resp, "<html")

    def test_the_partial_requires_login(self):
        resp = self.client.get("/partials/signal-rail/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 302)


class TickerLiveTests(TestCase):
    """News enters the band live: both news scrapers announce stored
    articles on the socket and the browser refetches the marquee partial —
    fresh headlines glow as they ride past instead of waiting for a
    reload."""

    def setUp(self):
        self.user = User.objects.create_user(username="tl_u", password="x")

    def test_the_ticker_partial_returns_both_marquee_halves(self):
        from django.utils import timezone as tz
        from scraping.models import NewsArticle
        NewsArticle.objects.create(
            title="Copper rallies", source="Reuters",
            url="https://example.test/live-copper", published_at=tz.now())
        self.client.force_login(self.user)
        resp = self.client.get("/partials/ticker/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Copper rallies", html)
        # One tagged item per marquee half — the seamless scroll needs both.
        self.assertEqual(html.count("data-news-id="), 2)
        self.assertNotIn("<html", html)

    def test_the_partial_requires_login(self):
        resp = self.client.get("/partials/ticker/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 302)

    def test_the_crypto_scraper_announces_stored_articles(self):
        """fetch_breaking_news already announced; the crypto pass stored
        articles in silence, so crypto headlines never streamed in."""
        from unittest.mock import patch
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(
            key__in=["platform_master", "scraper_crypto_news"]).update(
            is_enabled=True)
        with patch("market_data.adapters.crypto_news.fetch_crypto_news",
                   return_value=3), \
             patch("dashboard.consumers.push_news_notification") as mock_push:
            from market_data.tasks import fetch_crypto_news_task
            out = fetch_crypto_news_task()
        self.assertEqual(out.get("articles"), 3)
        mock_push.assert_called_once()
        self.assertEqual(mock_push.call_args.args[0]["count"], 3)

    def test_a_dry_crypto_pass_stays_silent(self):
        from unittest.mock import patch
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(
            key__in=["platform_master", "scraper_crypto_news"]).update(
            is_enabled=True)
        with patch("market_data.adapters.crypto_news.fetch_crypto_news",
                   return_value=0), \
             patch("dashboard.consumers.push_news_notification") as mock_push:
            from market_data.tasks import fetch_crypto_news_task
            fetch_crypto_news_task()
        mock_push.assert_not_called()
