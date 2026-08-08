"""Phase-26 track-record decay tests:
  - bot_performance_summary user filter
  - check_user_decay flags decay (avg_r drop, win_rate drop, gone negative)
  - cooldown dedupe prevents re-alerting
  - resolution stamps resolved_at when rule recovers
  - sample-size gates skip when n is too small
  - notification fires with track_record_decay kind
  - beat schedule entry registered

Run with:  python manage.py test tests.test_phase26_track_record_decay
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="td_u"):
    return User.objects.create_user(username=name, password="x")


def _abc(user, asset_class="stock", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=defaults.pop("name", "T"),
        **defaults,
    )


def _closed_at(cfg, *, symbol, side, entry, exit, sl, tp, qty=10,
                rule_name="r1", outcome="hit_target", closed_at=None,
                pnl=None):
    """Create a CLOSED graded trade with controllable closed_at."""
    from bot_program.models import AssetBotTrade
    if pnl is None:
        if side == "BUY":
            pnl = Decimal(str((exit - entry) * qty))
        else:
            pnl = Decimal(str((entry - exit) * qty))
    risk_per_unit = abs(entry - sl)
    risk_dollars = risk_per_unit * qty
    realized_r = float(pnl) / risk_dollars if risk_dollars > 0 else 0
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)),
        entry_price=Decimal(str(entry)), exit_price=Decimal(str(exit)),
        stop_loss=Decimal(str(sl)), take_profit=Decimal(str(tp)),
        status="CLOSED", pnl=pnl, rule_name=rule_name,
        outcome=outcome, realized_r=round(realized_r, 4),
        duration_minutes=60,
    )
    # Default closed_at = now so default-call tests show up in date filters.
    if closed_at is None:
        closed_at = timezone.now()
    AssetBotTrade.objects.filter(pk=t.pk).update(closed_at=closed_at)
    t.refresh_from_db()
    return t


def _seed_history(cfg, *, rule, n_baseline_wins=10, n_baseline_losses=5,
                   n_recent_wins=1, n_recent_losses=8):
    """Seed a baseline window (15-30 days ago) and a recent window
    (1-6 days ago) with controllable win/loss counts.

    Default config produces: baseline ~+0.7R avg, recent ~-0.6R avg.
    """
    now = timezone.now()
    # Baseline window
    for i in range(n_baseline_wins):
        _closed_at(cfg, symbol=f"BW{i}", side="BUY",
                    entry=100, exit=110, sl=95, tp=110, qty=10,
                    rule_name=rule, outcome="hit_target",
                    closed_at=now - timedelta(days=20 - (i % 5)))
    for i in range(n_baseline_losses):
        _closed_at(cfg, symbol=f"BL{i}", side="BUY",
                    entry=100, exit=95, sl=95, tp=110, qty=10,
                    rule_name=rule, outcome="stopped_out",
                    closed_at=now - timedelta(days=20 - (i % 5)))
    # Recent window
    for i in range(n_recent_wins):
        _closed_at(cfg, symbol=f"RW{i}", side="BUY",
                    entry=100, exit=110, sl=95, tp=110, qty=10,
                    rule_name=rule, outcome="hit_target",
                    closed_at=now - timedelta(days=3))
    for i in range(n_recent_losses):
        _closed_at(cfg, symbol=f"RL{i}", side="BUY",
                    entry=100, exit=95, sl=95, tp=110, qty=10,
                    rule_name=rule, outcome="stopped_out",
                    closed_at=now - timedelta(days=2 + (i % 3)))


# ── bot_performance_summary user filter ──────────────────────────────────

class SummaryUserFilterTests(TestCase):
    def test_user_filter_isolates_history(self):
        from bot_program.bot_grading import bot_performance_summary
        u1 = _user("sf_u1")
        u2 = _user("sf_u2")
        c1 = _abc(u1, name="C1")
        c2 = _abc(u2, name="C2")
        _closed_at(c1, symbol="A", side="BUY", entry=100, exit=110,
                    sl=95, tp=110, rule_name="r1")
        _closed_at(c2, symbol="A", side="BUY", entry=100, exit=110,
                    sl=95, tp=110, rule_name="r1")
        rows1 = bot_performance_summary(user=u1, days=30)
        rows2 = bot_performance_summary(user=u2, days=30)
        self.assertEqual(rows1[0]["n"], 1)
        self.assertEqual(rows2[0]["n"], 1)


# ── Decay detection ───────────────────────────────────────────────────────

class CheckUserDecayTests(TestCase):
    def setUp(self):
        self.user = _user("dec_u")
        self.cfg = _abc(self.user, name="C")

    def test_decay_fires_alert(self):
        from bot_program.track_record_decay import check_user_decay
        from bot_program.models import RuleTrackRecordAlert
        from alerts.models import Notification
        # Strong baseline (positive), weak recent (negative).
        _seed_history(self.cfg, rule="declining",
                       n_baseline_wins=10, n_baseline_losses=5,
                       n_recent_wins=1, n_recent_losses=8)
        result = check_user_decay(self.user)
        self.assertEqual(result["alerts_fired"], 1)
        a = RuleTrackRecordAlert.objects.get(user=self.user)
        self.assertEqual(a.rule_name, "declining")
        self.assertEqual(a.asset_class, "stock")
        self.assertGreater(a.baseline_avg_r, 0)
        self.assertLess(a.recent_avg_r, 0)
        self.assertIn("gone_negative", a.triggers)
        # Notification fired.
        n = Notification.objects.filter(user=self.user,
                                          notification_type="bot").first()
        self.assertIsNotNone(n)
        self.assertIn("declining", n.title)
        self.assertIn("decay", n.title.lower())

    def test_stable_rule_no_alert(self):
        """Recent ≈ baseline → no alert."""
        from bot_program.track_record_decay import check_user_decay
        from bot_program.models import RuleTrackRecordAlert
        _seed_history(self.cfg, rule="stable",
                       n_baseline_wins=10, n_baseline_losses=5,
                       n_recent_wins=6, n_recent_losses=3)
        result = check_user_decay(self.user)
        self.assertEqual(result["alerts_fired"], 0)
        self.assertEqual(RuleTrackRecordAlert.objects.count(), 0)

    def test_below_min_n_skipped(self):
        """Recent has <5 trades → no decision."""
        from bot_program.track_record_decay import check_user_decay
        # Big baseline, only 2 recent trades.
        _seed_history(self.cfg, rule="thin",
                       n_baseline_wins=10, n_baseline_losses=5,
                       n_recent_wins=0, n_recent_losses=2)
        result = check_user_decay(self.user)
        self.assertEqual(result["alerts_fired"], 0)

    def test_dedupe_within_cooldown(self):
        """Second check within 7d → no duplicate alert."""
        from bot_program.track_record_decay import check_user_decay
        from bot_program.models import RuleTrackRecordAlert
        _seed_history(self.cfg, rule="d2",
                       n_baseline_wins=10, n_baseline_losses=5,
                       n_recent_wins=1, n_recent_losses=8)
        check_user_decay(self.user)
        check_user_decay(self.user)
        self.assertEqual(RuleTrackRecordAlert.objects.count(), 1)

    def test_resolution_stamps_resolved_at(self):
        """When recent recovers → open alert gets resolved_at."""
        from bot_program.track_record_decay import check_user_decay
        from bot_program.models import RuleTrackRecordAlert
        from bot_program.models import AssetBotTrade

        _seed_history(self.cfg, rule="recovery",
                       n_baseline_wins=10, n_baseline_losses=5,
                       n_recent_wins=1, n_recent_losses=8)
        check_user_decay(self.user)
        self.assertEqual(RuleTrackRecordAlert.objects.count(), 1)
        a = RuleTrackRecordAlert.objects.first()
        self.assertIsNone(a.resolved_at)

        # Simulate recovery — clear recent losses by closing them outside the
        # 7-day window, replace with wins inside.
        AssetBotTrade.objects.filter(
            config=self.cfg, rule_name="recovery",
            symbol__startswith="RL").delete()
        for i in range(7):
            _closed_at(self.cfg, symbol=f"REC{i}", side="BUY",
                        entry=100, exit=110, sl=95, tp=110, qty=10,
                        rule_name="recovery", outcome="hit_target",
                        closed_at=timezone.now() - timedelta(days=2))

        check_user_decay(self.user)
        a.refresh_from_db()
        self.assertIsNotNone(a.resolved_at)


# ── Aggregate walker ──────────────────────────────────────────────────────

class CheckAllUsersDecayTests(TestCase):
    def test_walks_distinct_users(self):
        from bot_program.track_record_decay import check_all_users_decay
        u1 = _user("aw_u1")
        u2 = _user("aw_u2")
        c1 = _abc(u1, name="C1")
        c2 = _abc(u2, name="C2")
        _seed_history(c1, rule="r1",
                       n_baseline_wins=10, n_baseline_losses=5,
                       n_recent_wins=1, n_recent_losses=8)
        _seed_history(c2, rule="r2",
                       n_baseline_wins=10, n_baseline_losses=5,
                       n_recent_wins=6, n_recent_losses=3)
        result = check_all_users_decay()
        self.assertEqual(result["users"], 2)
        # u1 should fire, u2 shouldn't.
        self.assertEqual(result["alerts_fired"], 1)


# ── Beat schedule ─────────────────────────────────────────────────────────

class BeatScheduleTests(TestCase):
    def test_track_record_decay_in_beat_schedule(self):
        from config.celery import app
        schedule = app.conf.beat_schedule
        self.assertIn("track-record-decay-check", schedule)
        self.assertEqual(schedule["track-record-decay-check"]["task"],
                          "bot_program.tasks.check_all_track_record_decay")
