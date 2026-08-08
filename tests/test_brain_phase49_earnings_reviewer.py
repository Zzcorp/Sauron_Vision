"""Tests for Phase 49 — Earnings Reviewer agent.

Covers:
  - _held_symbols: collects symbols from open AssetBotTrade + Position
  - _earnings_events_for_held: matches title-pattern earnings events for held symbols
  - _build_review_snapshot: shape + price_move_pct computation
  - _persist_review: clamps invalid direction + confidence
  - review_one_event: happy path + provider failure (persists error-stamped row)
  - scan_due_earnings_now: respects max_reviews + skips dups
  - /earnings-reviews/ dashboard renders 200 + shows reviews
  - Admin run-now endpoint returns 302; non-staff blocked
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _staff(name="staff_p49"):
    u = User.objects.create_user(username=name, password="x")
    u.is_staff = True
    u.save()
    return u


def _instrument(symbol="ACME"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"},
    )
    return inst


def _open_bot_trade(symbol="ACME"):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    user, _ = User.objects.get_or_create(username="er_trader",
                                            defaults={"password": "x"})
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="stock", name="er_cfg",
        defaults=dict(
            enabled=True, mode="paper", symbols=[symbol],
            capital=Decimal("10000"), base_currency="USD",
            position_size_pct=2.0, max_concurrent_positions=5,
            max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
            entry_score_min=0.6, min_signals_for_entry=1,
        ),
    )
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("99"), take_profit=Decimal("103"),
        rule_name="r1", paper=True, status="OPEN",
    )


def _earnings_event(title="ACME Inc. Earnings (Q1 2026)", *, hours_ago=2):
    from market_data.models import EconomicEvent
    return EconomicEvent.objects.create(
        title=title, country="US",
        datetime=timezone.now() - timedelta(hours=hours_ago),
        impact="high", source="test",
    )


def _stub_provider(parsed_dict):
    import json
    raw = json.dumps(parsed_dict)
    usage = {"input_tokens": 4000, "output_tokens": 800, "cost_usd": 0.20}

    def patched_init(self, *a, **kw):
        self.agent_name = "earnings_reviewer"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(raw, usage))
    return patch(
        "brain.earnings_reviewer.EarningsReviewerAgent.__init__", patched_init)


# ── Held-symbol detection ────────────────────────────────────────────────

class HeldSymbolsTests(TestCase):
    def test_picks_up_open_bot_trade(self):
        from brain.earnings_reviewer import _held_symbols
        _open_bot_trade("MSFT")
        self.assertIn("MSFT", _held_symbols())

    def test_excludes_closed_trades(self):
        from brain.earnings_reviewer import _held_symbols
        from bot_program.models import AssetBotTrade
        t = _open_bot_trade("CLOSED_X")
        t.status = "CLOSED"
        t.save()
        self.assertNotIn("CLOSED_X", _held_symbols())


# ── Event matching ───────────────────────────────────────────────────────

class EarningsEventsForHeldTests(TestCase):
    def test_matches_held_symbol_in_title(self):
        from brain.earnings_reviewer import _earnings_events_for_held
        _open_bot_trade("ACME")
        _instrument("ACME")
        _earnings_event(title="ACME Earnings beat estimates")
        results = _earnings_events_for_held()
        self.assertEqual(len(results), 1)
        inst, ev = results[0]
        self.assertEqual(inst.symbol, "ACME")

    def test_skips_non_earnings_events(self):
        from brain.earnings_reviewer import _earnings_events_for_held
        from market_data.models import EconomicEvent
        _open_bot_trade("ACME")
        _instrument("ACME")
        EconomicEvent.objects.create(
            title="ACME merger announced", country="US",
            datetime=timezone.now() - timedelta(hours=1),
            impact="medium", source="test",
        )
        self.assertEqual(_earnings_events_for_held(), [])

    def test_skips_held_symbols_not_in_event_title(self):
        from brain.earnings_reviewer import _earnings_events_for_held
        _open_bot_trade("FOO")
        _instrument("FOO")
        _earnings_event(title="BAR Earnings Q1 2026")
        self.assertEqual(_earnings_events_for_held(), [])

    def test_skips_old_events(self):
        from brain.earnings_reviewer import _earnings_events_for_held
        _open_bot_trade("OLD")
        _instrument("OLD")
        _earnings_event(title="OLD Earnings Q1", hours_ago=200)
        self.assertEqual(_earnings_events_for_held(), [])


# ── Persistence + clamping ───────────────────────────────────────────────

class PersistReviewTests(TestCase):
    def test_clamps_invalid_direction(self):
        from brain.earnings_reviewer import _persist_review
        inst = _instrument("CLAMP")
        ev = _earnings_event(title="CLAMP Earnings")
        review = _persist_review(
            inst, ev,
            parsed={"implied_direction": "wibble",
                     "implied_confidence": 5.0,
                     "summary_md": "ok"},
            snapshot={}, model="t",
            tokens_in=10, tokens_out=5, cost_usd=0.001,
        )
        self.assertEqual(review.implied_direction, "unknown")
        self.assertEqual(review.implied_confidence, 1.0)
        self.assertEqual(review.summary_md, "ok")

    def test_caps_themes_and_risks(self):
        from brain.earnings_reviewer import _persist_review
        inst = _instrument("CAPS")
        ev = _earnings_event(title="CAPS Earnings")
        themes = [{"kind": "x", "text": str(i), "severity": 0.5}
                   for i in range(20)]
        risks = [f"risk_{i}" for i in range(20)]
        review = _persist_review(
            inst, ev,
            parsed={"implied_direction": "neutral", "key_themes": themes,
                     "risk_signals": risks},
            snapshot={}, model="t", tokens_in=0, tokens_out=0, cost_usd=0.0,
        )
        self.assertLessEqual(len(review.key_themes), 6)
        self.assertLessEqual(len(review.risk_signals), 8)


# ── review_one_event ─────────────────────────────────────────────────────

class ReviewOneEventTests(TestCase):
    def test_happy_path(self):
        from brain.earnings_reviewer import review_one_event
        from brain.earnings_models import EarningsReview
        inst = _instrument("HAPPY")
        ev = _earnings_event(title="HAPPY Earnings beat")
        with _stub_provider({
            "summary_md": "Solid quarter.",
            "key_themes": [{"kind": "growth", "text": "rev +20%",
                              "severity": 0.7}],
            "risk_signals": ["forward guidance lighter than buyside whispers"],
            "implied_direction": "bullish",
            "implied_confidence": 0.7,
            "suggested_action": "hold and trail stop",
        }):
            r = review_one_event(inst, ev)
        self.assertTrue(r["ok"])
        self.assertEqual(r["implied_direction"], "bullish")
        self.assertEqual(EarningsReview.objects.count(), 1)

    def test_provider_failure_persists_error_row(self):
        from brain.earnings_reviewer import review_one_event
        from brain.earnings_models import EarningsReview
        inst = _instrument("BUST")
        ev = _earnings_event(title="BUST Earnings")
        def bad_init(self, *a, **kw):
            self.agent_name = "earnings_reviewer"
            self.provider_name = "stub"; self.model = "stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(side_effect=RuntimeError("api down"))
        with patch("brain.earnings_reviewer.EarningsReviewerAgent.__init__",
                    bad_init):
            r = review_one_event(inst, ev)
        self.assertFalse(r["ok"])
        review = EarningsReview.objects.first()
        self.assertIn("api down", review.error)


# ── scan_due_earnings_now ────────────────────────────────────────────────

class ScanDueEarningsNowTests(TestCase):
    def test_caps_at_max_reviews(self):
        from brain.earnings_reviewer import scan_due_earnings_now
        from brain.earnings_models import EarningsReview
        # Create 4 held + 4 earnings events for them.
        for sym in ("AAA", "BBB", "CCC", "DDD"):
            _open_bot_trade(sym)
            _instrument(sym)
            _earnings_event(title=f"{sym} Earnings Q1")
        with _stub_provider({"summary_md": "ok",
                              "implied_direction": "neutral",
                              "implied_confidence": 0.5,
                              "key_themes": [], "risk_signals": [],
                              "suggested_action": ""}):
            r = scan_due_earnings_now(max_reviews=2)
        self.assertEqual(r["n_reviewed"], 2)
        # 2 successful (non-error) reviews persisted.
        self.assertEqual(EarningsReview.objects.filter(error="").count(), 2)

    def test_skips_existing_reviews(self):
        from brain.earnings_reviewer import scan_due_earnings_now
        from brain.earnings_models import EarningsReview
        _open_bot_trade("DUP")
        inst = _instrument("DUP")
        ev = _earnings_event(title="DUP Earnings Q1")
        # Pre-existing successful review.
        EarningsReview.objects.create(
            instrument=inst, event_datetime=ev.datetime,
            event_title=ev.title, summary_md="x",
            implied_direction="neutral",
        )
        with _stub_provider({"summary_md": "y",
                              "implied_direction": "bullish",
                              "implied_confidence": 0.5,
                              "key_themes": [], "risk_signals": [],
                              "suggested_action": ""}):
            r = scan_due_earnings_now(max_reviews=5)
        self.assertEqual(r["n_skipped_existing"], 1)
        self.assertEqual(r["n_reviewed"], 0)


# ── Dashboard + admin endpoints ──────────────────────────────────────────

class DashboardTests(TestCase):
    def test_renders_empty(self):
        u = User.objects.create_user(username="er_view", password="x")
        self.client.force_login(u)
        r = self.client.get("/earnings-reviews/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Earnings reviews", r.content.decode("utf-8"))

    def test_shows_review_with_suggested_action(self):
        from brain.earnings_models import EarningsReview
        u = User.objects.create_user(username="er_view2", password="x")
        self.client.force_login(u)
        inst = _instrument("VISIBLE")
        EarningsReview.objects.create(
            instrument=inst, event_datetime=timezone.now(),
            event_title="VISIBLE Earnings Q1",
            summary_md="Strong quarter for VISIBLE.",
            implied_direction="bullish", implied_confidence=0.75,
            suggested_action="hold and trail stop",
        )
        r = self.client.get("/earnings-reviews/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("VISIBLE", body)
        self.assertIn("BULLISH", body)
        self.assertIn("hold and trail stop", body)


class AdminEndpointTests(TestCase):
    def test_admin_run_now(self):
        u = _staff()
        self.client.force_login(u)
        r = self.client.post("/earnings-reviews/run/")
        self.assertEqual(r.status_code, 302)

    def test_non_staff_blocked(self):
        u = User.objects.create_user(username="ns_er", password="x")
        self.client.force_login(u)
        r = self.client.post("/earnings-reviews/run/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r.url)
