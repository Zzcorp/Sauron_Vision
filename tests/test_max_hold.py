"""The time stop finally has a ceiling — and its exits finally have a name.

`AssetBot._time_stop_hit` has existed for a long time and its comment was
exactly right: a bracket holds the stop and the target, but nothing at the
broker will release capital from a thesis that simply never moved. It read
its ceiling from `extras["max_hold_hours"]`, and NOTHING ever wrote that key
— not the seeder, not the settings form, not a default. So the exit was off
everywhere, and every bot position was unbounded in time while every seeded
setup declared a horizon of 3 to 21 days.

These tests pin the four halves of the fix:

  * a blank config inherits a real, per-asset-class ceiling, derived from
    the longest horizon that class's own seeded setups declare;
  * 0 still means "no time stop", so an operator can switch it off on
    purpose, and blank never silently means the same thing;
  * the legacy extras key keeps working, and keeps WINNING, so no running
    install has its ceiling moved by a schema change;
  * a TIME exit grades as `time_stop` — its own outcome — because a rule
    whose trades keep timing out is saying something a stop-out is not.

Run with:  python manage.py test tests.test_max_hold
"""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings as dj_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone


# ── helpers ─────────────────────────────────────────────────────────────────

def _user(name="mh_u"):
    return User.objects.create_user(username=name, password="x")


def _superuser(name="mh_admin"):
    u = User.objects.create_user(username=name, password="x")
    u.is_staff = True
    u.is_superuser = True
    u.save()
    return u


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class="stock", name="MH", mode="paper",
                    symbols=["AAA"], capital=Decimal("10000"), enabled=True)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


def _trade(cfg, **kw):
    from bot_program.models import AssetBotTrade
    defaults = dict(config=cfg, asset_class=cfg.asset_class, symbol="AAA",
                    side="BUY", qty=Decimal("10"), entry_price=Decimal("100"),
                    stop_loss=Decimal("98"), take_profit=Decimal("110"),
                    status="OPEN", paper=True, rule_name="mh_rule",
                    metadata={"initial_stop_loss": 98.0})
    # opened_at is auto_now_add, so create() silently discards it — an age has
    # to be written back through the queryset or every trade here is two
    # seconds old and no time stop can ever fire.
    opened_at = kw.pop("opened_at", None)
    defaults.update(kw)
    t = AssetBotTrade.objects.create(**defaults)
    if opened_at is not None:
        AssetBotTrade.objects.filter(pk=t.pk).update(opened_at=opened_at)
        t.refresh_from_db()
    return t


def _managed(cfg, price="101"):
    """Run one manage_positions tick with a mark that crosses neither level."""
    from bot_program.asset_engine.stock_bot import StockBot
    from bot_program.asset_engine.crypto_bot import CryptoBot
    from bot_program.asset_engine.forex_bot import ForexBot
    bot_cls = {"stock": StockBot, "crypto": CryptoBot,
               "forex": ForexBot}[cfg.asset_class]
    client = MagicMock()
    client.ticker = MagicMock(return_value={"lastPrice": price})
    with patch("bot_program.engine.broker_router.client_for_symbol",
               return_value=client):
        return bot_cls(cfg).manage_positions()


def _seeded_horizons() -> dict:
    """{asset_class: longest suggested_horizon_days} across both seed packs.

    Read from the seeders rather than copied, so the guard below breaks when
    someone adds a setup whose horizon outlives its class's ceiling.
    """
    from signals.management.commands.seed_strategies import _setup_definitions
    from signals.management.commands import seed_advanced_strategies as adv

    specs = list(_setup_definitions())
    for attr in ("_setup_definitions", "_advanced_definitions",
                 "_definitions"):
        fn = getattr(adv, attr, None)
        if callable(fn):
            specs += list(fn())
            break

    longest: dict = {}
    for spec in specs:
        days = int(spec.get("suggested_horizon_days") or 0)
        for ac in spec.get("asset_classes") or []:
            longest[ac] = max(longest.get(ac, 0), days)
    return longest


# ── 1. The per-asset-class default ──────────────────────────────────────────

class AssetClassDefaultTests(TestCase):
    """The number a config gets when nobody has typed one."""

    def setUp(self):
        self.user = _user("mh_def")

    def test_every_selectable_asset_class_has_a_ceiling(self):
        """A class missing from the table would resolve to 0 under a naive
        `.get()`, and 0 means "no time stop" — the exact unbounded state the
        table exists to end."""
        from bot_program.asset_models import (
            AssetBotConfig, DEFAULT_MAX_HOLD_HOURS,
        )
        for value, _label in AssetBotConfig.ASSET_CLASS_CHOICES:
            self.assertIn(value, DEFAULT_MAX_HOLD_HOURS, value)
            self.assertGreater(DEFAULT_MAX_HOLD_HOURS[value], 0, value)

    def test_a_blank_config_inherits_its_class_ceiling(self):
        for asset_class, expected in (("stock", 336.0), ("forex", 720.0),
                                       ("commodity", 720.0), ("crypto", 192.0),
                                       ("options", 240.0)):
            cfg = _cfg(self.user, asset_class=asset_class,
                       name=f"blank_{asset_class}")
            ts = cfg.time_stop_setting()
            self.assertEqual(ts["hours"], expected, asset_class)
            self.assertTrue(ts["enabled"], asset_class)
            self.assertEqual(ts["source"], "class-default", asset_class)

    def test_the_classes_do_not_share_one_ceiling(self):
        """A forex breakout on a 1% stop and a three-week macro composite
        cannot live under the same number, and neither can an option paying
        theta and an equity that costs nothing to hold."""
        from bot_program.asset_models import DEFAULT_MAX_HOLD_HOURS
        self.assertGreater(DEFAULT_MAX_HOLD_HOURS["forex"],
                           DEFAULT_MAX_HOLD_HOURS["stock"])
        self.assertGreater(DEFAULT_MAX_HOLD_HOURS["stock"],
                           DEFAULT_MAX_HOLD_HOURS["options"])
        self.assertGreater(DEFAULT_MAX_HOLD_HOURS["options"],
                           DEFAULT_MAX_HOLD_HOURS["crypto"])

    def test_each_ceiling_outlives_the_longest_horizon_its_class_declares(self):
        """The defaults are derived from what the platform already believes.
        A ceiling shorter than a seeded setup's own horizon would convert that
        setup's winners into TIME exits and poison the rule's track record —
        so this guard fires the day someone seeds a longer thesis."""
        from bot_program.asset_models import AssetBotConfig
        for asset_class, days in _seeded_horizons().items():
            ceiling = AssetBotConfig.default_max_hold_hours(asset_class)
            self.assertGreaterEqual(
                ceiling, days * 24.0,
                f"{asset_class}: the class ceiling is {ceiling}h but its "
                f"longest seeded thesis declares {days}d ({days * 24}h)")

    def test_an_unknown_asset_class_still_gets_a_ceiling(self):
        """`.get(ac) or 0` would make a typo in asset_class silently restore
        the unbounded behaviour."""
        from bot_program.asset_models import (
            AssetBotConfig, UNKNOWN_CLASS_MAX_HOLD_HOURS,
        )
        self.assertEqual(AssetBotConfig.default_max_hold_hours("dogecoin_cfd"),
                         UNKNOWN_CLASS_MAX_HOLD_HOURS)
        self.assertGreater(UNKNOWN_CLASS_MAX_HOLD_HOURS, 0)

    def test_the_class_default_alone_closes_a_stale_position(self):
        """The whole gap in one test: nothing configured anywhere, and the
        position is still released instead of sitting forever."""
        cfg = _cfg(self.user, asset_class="crypto", name="inherit_close",
                   symbols=["AAA"])
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=200))
        self.assertEqual(_managed(cfg), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertIn("closed:TIME", t.reason)


# ── 2. Zero means off ───────────────────────────────────────────────────────

class ZeroDisablesTests(TestCase):
    def setUp(self):
        self.user = _user("mh_zero")

    def test_zero_disables_the_time_stop(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, name="off", max_hold_hours=0)
        ts = cfg.time_stop_setting()
        self.assertEqual(ts["hours"], 0.0)
        self.assertFalse(ts["enabled"])
        self.assertEqual(ts["source"], "config")
        t = _trade(cfg, opened_at=timezone.now() - timedelta(days=400))
        self.assertFalse(StockBot(cfg)._time_stop_hit(t))

    def test_zero_survives_a_whole_manage_tick(self):
        """The knob has to hold where it matters, not only in the resolver."""
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, name="off2", max_hold_hours=0)
        t = _trade(cfg, opened_at=timezone.now() - timedelta(days=400))
        self.assertEqual(_managed(cfg), 0)
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).status, "OPEN")

    def test_blank_is_not_the_same_as_zero(self):
        """An empty box must never be the way an operator accidentally
        removes the only exit that releases dead capital."""
        cfg = _cfg(self.user, name="blank")
        self.assertIsNone(cfg.max_hold_hours)
        self.assertTrue(cfg.time_stop_setting()["enabled"])

    def test_a_negative_ceiling_reads_as_off_rather_than_as_nonsense(self):
        """The form refuses negatives, but a fixture or a shell can still
        write one. Left alone it is silently inert — `held / -5` is never
        >= 1, so the stop never fires — while the UI prints a confident
        "-5h". Clamped to 0 it becomes the state it actually is: off."""
        cfg = _cfg(self.user, name="neg", max_hold_hours=-5)
        ts = cfg.time_stop_setting()
        self.assertEqual(ts["hours"], 0.0)
        self.assertFalse(ts["enabled"])


# ── 3. The legacy extras key ────────────────────────────────────────────────

class LegacyExtrasKeyTests(TestCase):
    """extras['max_hold_hours'] was the setting's only home. An install that
    set it is running with a ceiling it chose, and a schema change must not
    move a live risk knob without asking."""

    def setUp(self):
        self.user = _user("mh_legacy")

    def test_the_legacy_key_still_sets_the_ceiling(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, name="legacy", extras={"max_hold_hours": 6})
        ts = cfg.time_stop_setting()
        self.assertEqual(ts["hours"], 6.0)
        self.assertEqual(ts["source"], "extras")
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=8))
        self.assertTrue(StockBot(cfg)._time_stop_hit(t))

    def test_the_legacy_key_wins_over_the_new_field(self):
        cfg = _cfg(self.user, name="legacy_wins", max_hold_hours=500,
                   extras={"max_hold_hours": 6})
        self.assertEqual(cfg.time_stop_setting()["hours"], 6.0)

    def test_the_legacy_key_can_still_switch_it_off(self):
        cfg = _cfg(self.user, name="legacy_off", extras={"max_hold_hours": 0})
        ts = cfg.time_stop_setting()
        self.assertFalse(ts["enabled"])
        self.assertEqual(ts["source"], "extras")

    def test_a_legacy_time_stop_closes_through_the_engine(self):
        cfg = _cfg(self.user, name="legacy_close",
                   extras={"max_hold_hours": 24})
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=48))
        self.assertEqual(_managed(cfg), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertIn("closed:TIME", t.reason)

    def test_a_non_numeric_legacy_value_falls_back_instead_of_disabling(self):
        """extras is hand-edited JSON and "24h" is the obvious typo. Treating
        it as "off" would let a typo remove risk management silently."""
        cfg = _cfg(self.user, name="legacy_typo",
                   extras={"max_hold_hours": "two"})
        ts = cfg.time_stop_setting()
        self.assertEqual(ts["source"], "class-default")
        self.assertTrue(ts["enabled"])

    def test_a_non_numeric_legacy_value_defers_to_the_field_when_set(self):
        cfg = _cfg(self.user, name="legacy_typo2", max_hold_hours=12,
                   extras={"max_hold_hours": "two"})
        ts = cfg.time_stop_setting()
        self.assertEqual(ts["hours"], 12.0)
        self.assertEqual(ts["source"], "config")


# ── 4. The exit, and how it is graded ───────────────────────────────────────

class TimeStopExitTests(TestCase):
    def setUp(self):
        self.user = _user("mh_exit")

    def test_a_position_past_its_ceiling_closes_with_reason_time(self):
        cfg = _cfg(self.user, name="over", max_hold_hours=24)
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=48))
        self.assertEqual(_managed(cfg), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertIn("closed:TIME", t.reason)

    def test_a_position_below_its_ceiling_is_left_alone(self):
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, name="under", max_hold_hours=24)
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=12))
        self.assertEqual(_managed(cfg), 0)
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).status, "OPEN")

    def test_a_time_exit_grades_as_its_own_outcome(self):
        """It used to fall through to the price comparisons and grade
        `manual_close` — the engine's own risk decision filed as a human's,
        in the audit log, the notification icon and every dashboard."""
        cfg = _cfg(self.user, name="graded", max_hold_hours=24)
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=48))
        _managed(cfg)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "time_stop")
        self.assertNotEqual(t.outcome, "manual_close")
        self.assertNotEqual(t.outcome, "expired")

    def test_time_stop_is_a_declared_outcome_choice(self):
        """An outcome the model does not declare is invisible to every
        `get_outcome_display` and every admin filter."""
        from bot_program.models import AssetBotTrade
        self.assertIn("time_stop",
                      dict(AssetBotTrade.OUTCOME_CHOICES))

    def test_a_time_exit_still_carries_an_r_multiple(self):
        """R is denominated by the stop the trade OPENED with. A TIME exit is
        a real round trip and has to be comparable with every other one."""
        cfg = _cfg(self.user, name="graded_r", max_hold_hours=24)
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=48))
        _managed(cfg)
        t.refresh_from_db()
        self.assertIsNotNone(t.realized_r)

    def test_a_time_exit_counts_toward_the_rule_population(self):
        """A rule whose trades keep timing out is exactly the rule whose
        measured expectancy should be falling. An outcome missing from
        `bot_performance_summary`'s filter is invisible to the promotion
        ladder — the rule would be judged only on the trades that happened
        to reach a level."""
        from bot_program.bot_grading import bot_performance_summary
        cfg = _cfg(self.user, name="pop", max_hold_hours=24)
        _trade(cfg, opened_at=timezone.now() - timedelta(hours=48))
        _managed(cfg)
        rows = bot_performance_summary(rule_name="mh_rule",
                                        asset_class="stock", days=30)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["n"], 1)

    def test_an_expiry_close_is_still_expired_not_a_time_stop(self):
        """The options expiry gate is a different event: the CONTRACT ran
        out, not the thesis."""
        from bot_program.bot_grading import grade_bot_trade
        cfg = _cfg(self.user, asset_class="options", name="opt")
        t = _trade(cfg, status="CLOSED", exit_price=Decimal("101"),
                   reason="entry | closed:EXPIRY_CLOSE")
        t.closed_at = timezone.now()
        t.save(update_fields=["closed_at"])
        grade_bot_trade(t)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "expired")

    def test_the_time_stop_still_fires_on_a_broker_protected_trade(self):
        """A bracket holds the stop and the target, so protected trades skip
        the exit block entirely — correct for SL/TP, wrong for the one exit
        no broker will ever fire."""
        cfg = _cfg(self.user, name="prot", max_hold_hours=24)
        t = _trade(cfg, metadata={"protected": True,
                                   "initial_stop_loss": 98.0},
                   opened_at=timezone.now() - timedelta(hours=48))
        self.assertEqual(_managed(cfg), 1)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "time_stop")


# ── 5. Warned before it fires ───────────────────────────────────────────────

class TimeStopWarningTests(TestCase):
    """A time stop that only announces itself by closing the trade is a
    surprise: the operator finds the position gone with no window in which
    they could have cut it early or raised the ceiling."""

    def setUp(self):
        self.user = _user("mh_warn")

    def _warnings(self):
        from alerts.models import Notification
        return Notification.objects.filter(
            user=self.user, title__startswith="⧗ Time stop nearing")

    def test_a_position_approaching_its_ceiling_is_announced(self):
        cfg = _cfg(self.user, name="warn", max_hold_hours=100)
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=90))
        self.assertEqual(_managed(cfg), 0)
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertEqual(self._warnings().count(), 1)
        self.assertIn("TIME", self._warnings().first().body)

    def test_the_warning_fires_once_per_position(self):
        """The bot ticks every five minutes; a per-hour title dedupe would
        still send twelve alerts a day for the last fifth of the window."""
        cfg = _cfg(self.user, name="warn_once", max_hold_hours=100)
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=90))
        _managed(cfg)
        _managed(cfg)
        _managed(cfg)
        self.assertEqual(self._warnings().count(), 1)
        t.refresh_from_db()
        self.assertTrue(t.metadata.get("time_stop_warned"))

    def test_a_fresh_position_is_not_announced(self):
        cfg = _cfg(self.user, name="warn_fresh", max_hold_hours=100)
        _trade(cfg, opened_at=timezone.now() - timedelta(hours=10))
        _managed(cfg)
        self.assertEqual(self._warnings().count(), 0)

    def test_a_position_already_past_its_ceiling_is_not_warned_then_closed(self):
        """"This will close soon" arriving in the same tick as "this closed"
        is noise, not a warning — which is what a bot restarted after a week
        of downtime would otherwise send for every open position."""
        cfg = _cfg(self.user, name="warn_late", max_hold_hours=24)
        _trade(cfg, opened_at=timezone.now() - timedelta(hours=200))
        self.assertEqual(_managed(cfg), 1)
        self.assertEqual(self._warnings().count(), 0)

    def test_the_status_helper_reports_what_a_card_needs(self):
        from bot_program.asset_engine.base import time_stop_status
        cfg = _cfg(self.user, name="status", max_hold_hours=100)
        t = _trade(cfg, opened_at=timezone.now() - timedelta(hours=90))
        st = time_stop_status(t, config=cfg)
        self.assertTrue(st["applies"])
        self.assertTrue(st["enabled"])
        self.assertTrue(st["approaching"])
        self.assertFalse(st["hit"])
        self.assertEqual(st["max_hold_hours"], 100.0)
        self.assertAlmostEqual(st["hours_left"], 10.0, delta=0.2)
        self.assertEqual(st["source"], "config")

    def test_the_status_helper_declines_the_other_position_book(self):
        """The platform keeps TWO position books. `portfolio.Position` has an
        `opened_at` too, so a duck-typed read would print a confident
        countdown for a manual position no bot manages and no time stop will
        ever close. That must render as an em-dash, not a number."""
        from bot_program.asset_engine.base import time_stop_status
        from instruments.models import Instrument
        from portfolio.models import Portfolio, Position
        inst = Instrument.objects.create(symbol="MHPOS", name="MHPOS",
                                          asset_class="stock")
        pf = Portfolio.objects.create(
            name="mh", initial_capital=Decimal("1000"),
            current_value=Decimal("1000"), cash_available=Decimal("1000"))
        pos = Position.objects.create(
            portfolio=pf, instrument=inst, direction="long",
            quantity=Decimal("1"), entry_price=Decimal("100"),
            current_price=Decimal("100"),
            opened_at=timezone.now() - timedelta(days=400))
        st = time_stop_status(pos)
        self.assertFalse(st["applies"])
        self.assertFalse(st["hit"])
        self.assertIsNone(st["max_hold_hours"])


# ── 6. The setting round-trips through the UI ───────────────────────────────

class SettingsUIRoundTripTests(TestCase):
    """A hidden key in a JSON blob is not a setting. This is the surface an
    operator actually edits."""

    URL = "/admin-dashboard/asset-bots/create/"

    def setUp(self):
        self.admin = _superuser("mh_hq")
        self.client = Client()
        self.client.force_login(self.admin)

    def _post(self, **extra):
        payload = {
            "asset_class": "forex", "name": "ui_bot", "mode": "paper",
            "symbols": '["EURUSD"]', "extras": "{}",
            "capital": "10000", "base_currency": "USD",
            "position_size_pct": "2", "max_concurrent_positions": "5",
            "max_daily_loss_pct": "2", "stop_loss_pct": "1.5",
            "take_profit_pct": "3", "entry_score_min": "0.6",
        }
        payload.update(extra)
        return self.client.post(self.URL, payload)

    def _cfg(self):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.get(user=self.admin, name="ui_bot")

    def test_the_form_offers_the_field(self):
        """The whole point of the change: the ceiling is edited where the
        other bot settings are, not buried in the extras JSON."""
        path = (Path(dj_settings.BASE_DIR) / "templates" / "dashboard"
                / "admin_dashboard.html")
        markup = path.read_text(encoding="utf-8")
        self.assertIn('name="max_hold_hours"', markup)

    def test_a_typed_ceiling_round_trips(self):
        self._post(max_hold_hours="72")
        cfg = self._cfg()
        self.assertEqual(cfg.max_hold_hours, 72.0)
        self.assertEqual(cfg.time_stop_setting()["hours"], 72.0)
        self.assertEqual(cfg.time_stop_setting()["source"], "config")

    def test_zero_round_trips_as_off_not_as_blank(self):
        self._post(max_hold_hours="0")
        cfg = self._cfg()
        self.assertEqual(cfg.max_hold_hours, 0.0)
        self.assertFalse(cfg.time_stop_setting()["enabled"])

    def test_blank_round_trips_as_inherit(self):
        self._post(max_hold_hours="")
        cfg = self._cfg()
        self.assertIsNone(cfg.max_hold_hours)
        self.assertEqual(cfg.time_stop_setting()["source"], "class-default")
        self.assertTrue(cfg.time_stop_setting()["enabled"])

    def test_a_negative_ceiling_is_refused_rather_than_stored(self):
        from bot_program.models import AssetBotConfig
        self._post(max_hold_hours="-5")
        self.assertFalse(
            AssetBotConfig.objects.filter(user=self.admin,
                                           name="ui_bot").exists())

    def test_a_legacy_extras_key_is_drained_into_the_field(self):
        """Left in extras it would WIN at runtime, making the visible field
        decorative: the operator would type a ceiling, save, and the engine
        would keep enforcing the old one."""
        self._post(extras='{"max_hold_hours": 48, "trail_pct": 2}')
        cfg = self._cfg()
        self.assertEqual(cfg.max_hold_hours, 48.0)
        self.assertNotIn("max_hold_hours", cfg.extras)
        self.assertEqual(cfg.extras.get("trail_pct"), 2)
        self.assertEqual(cfg.time_stop_setting()["source"], "config")

    def test_the_typed_field_beats_a_stale_extras_key(self):
        self._post(max_hold_hours="12",
                   extras='{"max_hold_hours": 48}')
        cfg = self._cfg()
        self.assertEqual(cfg.max_hold_hours, 12.0)
        self.assertNotIn("max_hold_hours", cfg.extras)
        self.assertEqual(cfg.effective_max_hold_hours(), 12.0)

    def test_the_saved_ceiling_is_readable_back_off_the_bot_list(self):
        """The create form is write-only, so a saved value has to be visible
        somewhere or "blank" stays invisible forever."""
        self._post(max_hold_hours="72")
        r = self.client.get("/asset-bots/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Max hold", body)
        self.assertIn("72h", body)


# ── 7. The seeded fleet is not exempt ───────────────────────────────────────

class SeededFleetTests(TestCase):
    def test_every_seeded_config_ends_up_with_a_time_stop(self):
        """The starter fleet is the platform's own answer to "what should I
        run?". Shipping it with no ceiling is shipping the bug."""
        from django.core.management import call_command
        from io import StringIO
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        from bot_program.management.commands.seed_bots import FLEET

        for _ac, _name, symbols in FLEET:
            for s in symbols:
                Instrument.objects.get_or_create(
                    symbol=s, defaults={"name": s, "asset_class": "stock"})
        admin = _superuser("mh_seed")
        out = StringIO()
        call_command("seed_bots", "--user", admin.username, stdout=out,
                     stderr=StringIO())

        configs = list(AssetBotConfig.objects.filter(user=admin))
        self.assertTrue(configs)
        for cfg in configs:
            ts = cfg.time_stop_setting()
            self.assertTrue(ts["enabled"], cfg.name)
            self.assertIsNone(cfg.max_hold_hours, cfg.name)
            self.assertEqual(ts["source"], "class-default", cfg.name)
        self.assertIn("Time stops", out.getvalue())
