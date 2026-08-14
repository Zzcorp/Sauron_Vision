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


class SignalTickerPayloadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tk_u", password="x")
        self.inst = _instrument()

    def _signal(self, **kw):
        from signals.models import Signal
        defaults = dict(
            instrument=self.inst, signal_type="technical", direction="bullish",
            urgency="high", title="BTCUSD LONG — golden cross",
            description="SMA50 crossed above SMA200.", rule_name="golden_cross",
            score=0.72, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), suggested_stop=Decimal("98"),
            suggested_target=Decimal("106"), is_active=True)
        defaults.update(kw)
        return Signal.objects.create(**defaults)

    def _ticker(self):
        from core.context_processors import sauron_context
        req = RequestFactory().get("/")
        req.user = self.user
        return sauron_context(req).get("ticker_items") or []

    def _first_signal_item(self):
        return next((i for i in self._ticker() if i.get("type") == "signal"), None)

    def test_the_popup_carries_the_levels(self):
        """Without entry, stop and target the card describes a setup you
        cannot act on."""
        self._signal()
        item = self._first_signal_item()
        self.assertIsNotNone(item, "no signal reached the ticker")
        self.assertEqual(float(item["entry"]), 100.0)
        self.assertEqual(float(item["stop"]), 98.0)
        self.assertEqual(float(item["target"]), 106.0)

    def test_reward_to_risk_is_derived_when_the_row_lacks_it(self):
        self._signal(risk_reward_ratio=None)
        item = self._first_signal_item()
        # entry 100, stop 98 -> 2 of risk; target 106 -> 6 of reward.
        self.assertAlmostEqual(float(item["rr"]), 3.0, places=2)

    def test_it_carries_the_rule_and_the_thesis(self):
        self._signal()
        item = self._first_signal_item()
        self.assertEqual(item["rule_name"], "golden_cross")
        self.assertIn("SMA50", item["description"])

    def test_the_score_is_expressed_as_a_percentage_for_the_bar(self):
        """A bare 0.72 means nothing without the scale it sits on."""
        self._signal(score=0.72)
        self.assertEqual(self._first_signal_item()["score_pct"], 72)

    def test_it_reports_how_far_price_has_moved_since_the_signal(self):
        """A setup is only actionable while price is near its entry."""
        from market_data.models import LiveQuote
        LiveQuote.objects.update_or_create(
            instrument=self.inst, defaults={"last": Decimal("103")})
        self._signal()
        self.assertAlmostEqual(float(self._first_signal_item()["drift_pct"]),
                               3.0, places=2)

    def test_age_is_reported(self):
        s = self._signal()
        from signals.models import Signal
        Signal.objects.filter(pk=s.pk).update(
            created_at=timezone.now() - timedelta(minutes=90))
        self.assertGreaterEqual(self._first_signal_item()["age_min"], 89)


class QuoteTickerPayloadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tq_u", password="x")
        self.inst = _instrument("ETHUSD")

    def _ticker(self):
        from core.context_processors import sauron_context
        req = RequestFactory().get("/")
        req.user = self.user
        return sauron_context(req).get("ticker_items") or []

    def test_a_quote_states_its_age(self):
        """The pollers are rate-limited enough that a "live" price can be
        hours old, and a price with no age is one you cannot act on."""
        from market_data.models import LiveQuote
        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("2000"), "change_pct": Decimal("1.5")})
        item = next(i for i in self._ticker() if i.get("type") == "quote")
        self.assertIn("age_display", item)
        self.assertFalse(item["stale"], "a fresh quote should not read stale")

    def test_an_old_quote_is_flagged_stale(self):
        from market_data.models import LiveQuote
        q, _ = LiveQuote.objects.update_or_create(
            instrument=self.inst, defaults={"last": Decimal("2000")})
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(hours=6))
        item = next(i for i in self._ticker() if i.get("type") == "quote")
        self.assertTrue(item["stale"])
        self.assertIn("ago", item["age_display"])


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
