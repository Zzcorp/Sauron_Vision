"""Phase-33 production hardening tests.

Five sub-areas:
  33.1 — Dockerfile.prod healthcheck URL matches the registered route.
  33.2 — Sentry settings block exists and is gated by SENTRY_DSN.
  33.3 — AssetBot live entries pass deterministic client_order_id.
  33.4 — Reconciliation closes orphan trades + skips when broker can't tell.
  33.5 — Daily backup gracefully skips on sqlite, runs subprocess on postgres.

Run with:  python manage.py test tests.test_phase33_hardening
"""
import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase


REPO = Path(settings.BASE_DIR)


def _user(name="ph33_u"):
    return User.objects.create_user(username=name, password="x")


# ── 33.1 ─────────────────────────────────────────────────────────────────

class HealthcheckURLTests(TestCase):
    def test_the_image_declares_no_healthcheck(self):
        """The probe belongs on the web service, not the image. Every service
        is built from this one image -- both Celery workers, beat and the
        five streamers -- and none of them serve HTTP, so an image-level HTTP
        probe reported all of them `unhealthy` forever and buried the single
        signal that meant anything."""
        text = (REPO / "Dockerfile.prod").read_text(encoding="utf-8",
                                                     errors="replace")
        self.assertNotIn("\nHEALTHCHECK", text)

    def test_the_web_service_probes_healthz(self):
        import yaml
        compose = yaml.safe_load(
            (REPO / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
        probe = str(compose["services"]["web"]["healthcheck"]["test"])
        self.assertIn("/healthz/", probe)

    def test_healthz_route_renders_200(self):
        # Sanity — anonymous request should reach the health endpoint.
        r = self.client.get("/healthz/")
        self.assertEqual(r.status_code, 200)


# ── 33.2 ─────────────────────────────────────────────────────────────────

class SentrySettingsTests(TestCase):
    def test_settings_has_sentry_block(self):
        text = (REPO / "config" / "settings.py").read_text()
        self.assertIn("SENTRY_DSN", text)
        self.assertIn("sentry_sdk.init", text)
        self.assertIn("DjangoIntegration", text)
        self.assertIn("CeleryIntegration", text)

    def test_sentry_init_only_when_dsn_set(self):
        text = (REPO / "config" / "settings.py").read_text()
        # The init must be inside an `if SENTRY_DSN:` block.
        idx_dsn = text.find("if SENTRY_DSN:")
        idx_init = text.find("sentry_sdk.init")
        self.assertGreater(idx_dsn, 0)
        self.assertGreater(idx_init, idx_dsn)

    def test_sentry_in_requirements(self):
        text = (REPO / "requirements.txt").read_text()
        self.assertIn("sentry-sdk", text)


# ── 33.3 ─────────────────────────────────────────────────────────────────

def _abc(user, asset_class="stock", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="live", symbols=[],
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


class IdempotencyTests(TestCase):
    def test_make_client_order_id_deterministic(self):
        from bot_program.engine.idempotency import make_client_order_id
        a = make_client_order_id(config_id=1, symbol="AAPL", signal_id="r1",
                                   intent="ENTRY", bar_ts="202605030900")
        b = make_client_order_id(config_id=1, symbol="AAPL", signal_id="r1",
                                   intent="ENTRY", bar_ts="202605030900")
        self.assertEqual(a, b)
        # Different inputs → different ids.
        c = make_client_order_id(config_id=2, symbol="AAPL", signal_id="r1",
                                   intent="ENTRY", bar_ts="202605030900")
        self.assertNotEqual(a, c)
        # Length safe for Binance (≤36 chars).
        self.assertLessEqual(len(a), 36)

    def test_assetbot_passes_client_order_id_to_market_order(self):
        """Live-mode entry must call market_order with a client_order_id kwarg."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from signals.models import Signal

        u = _user("idem_u")
        # A live broker order requires a rule promoted to a live stage — an
        # unregistered rule is confined to the paper venue however the config
        # is set, so without this the entry never reaches market_order.
        from signals.models_control import RuleControl
        RuleControl.objects.get_or_create(rule_name="r1",
                                          defaults={"promotion_stage": "live_full"})
        cfg = _abc(u, "stock", name="ST", symbols=["AAPL"], mode="live")
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        LiveQuote.objects.create(instrument=inst, last=Decimal("100"))
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name="r1",
            score=0.85, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        )

        fake_client = MagicMock()
        fake_client.ticker = MagicMock(return_value={"lastPrice": "100"})
        fake_client.market_order = MagicMock(return_value={
            "orderId": "BROKER-123", "status": "FILLED",
        })

        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            res = StockBot(cfg).scan_symbol("AAPL")

        self.assertIsNotNone(res)
        # market_order called with client_order_id kwarg starting "sv-"
        call_kwargs = fake_client.market_order.call_args.kwargs
        self.assertIn("client_order_id", call_kwargs)
        self.assertTrue(call_kwargs["client_order_id"].startswith("sv-"))

    def test_assetbot_skips_trade_on_dedup_rejection(self):
        """Broker returning status=REJECTED → no AssetBotTrade row created."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from signals.models import Signal

        u = _user("idem_dedup_u")
        from signals.models_control import RuleControl
        RuleControl.objects.get_or_create(rule_name="r1",
                                          defaults={"promotion_stage": "live_full"})
        cfg = _abc(u, "stock", name="ST", symbols=["AAPL"], mode="live")
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        LiveQuote.objects.create(instrument=inst, last=Decimal("100"))
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name="r1",
            score=0.85, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        )
        fake_client = MagicMock()
        fake_client.ticker = MagicMock(return_value={"lastPrice": "100"})
        fake_client.market_order = MagicMock(return_value={
            "orderId": "", "status": "REJECTED",
        })
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            res = StockBot(cfg).scan_symbol("AAPL")
        self.assertIsNone(res)
        self.assertEqual(AssetBotTrade.objects.filter(
            config__user=u, symbol="AAPL").count(), 0)


# ── 33.4 ─────────────────────────────────────────────────────────────────

class ReconciliationTests(TestCase):
    def setUp(self):
        self.user = _user("recon_u")
        self.cfg = _abc(self.user, "stock", name="ST", mode="live")

    def _open_trade(self, symbol="AAPL"):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol=symbol, side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="OPEN", paper=False,
        )

    def test_closes_orphan_when_broker_doesnt_report_position(self):
        from bot_program.reconcile_asset import reconcile_user
        from bot_program.models import AssetBotTrade

        trade = self._open_trade()
        # Broker says no positions open.
        fake_client = MagicMock()
        fake_client.get_positions = MagicMock(return_value=[])
        fake_client.ticker = MagicMock(return_value={"lastPrice": "105"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            r = reconcile_user(self.user)
        self.assertEqual(r["closed_as_orphan"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        # Classified by the grader, not hardcoded. Reconciliation is how
        # every bracket-protected exit is finalised, so hardcoding
        # "manual_close" and leaving realized_r NULL meant stock and forex
        # contributed zero graded trades however long they ran.
        self.assertEqual(trade.outcome, "hit_target")
        self.assertIsNotNone(trade.realized_r)
        self.assertTrue(trade.metadata.get("exit_price_inferred"),
                        "an inferred exit price must be flagged as such")
        # Exit price reflects last broker tick (105) not entry (100).
        self.assertEqual(trade.exit_price, Decimal("105"))

    def test_keeps_open_when_broker_confirms_position(self):
        from bot_program.reconcile_asset import reconcile_user

        trade = self._open_trade("MSFT")
        fake_client = MagicMock()
        fake_client.get_positions = MagicMock(return_value=[
            {"symbol": "MSFT"},
        ])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            r = reconcile_user(self.user)
        self.assertEqual(r["closed_as_orphan"], 0)
        self.assertEqual(r["checked"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_broker_unavailable_skips_without_closing(self):
        """If broker doesn't expose get_positions, we don't reconcile."""
        from bot_program.reconcile_asset import reconcile_user

        trade = self._open_trade("NVDA")
        fake_client = MagicMock(spec=[])  # no get_positions attr
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            r = reconcile_user(self.user)
        self.assertEqual(r["broker_unavailable"], 1)
        self.assertEqual(r["closed_as_orphan"], 0)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_paper_trades_are_skipped(self):
        from bot_program.reconcile_asset import reconcile_user
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="PAPRX", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            status="OPEN", paper=True,
        )
        r = reconcile_user(self.user)
        self.assertEqual(r["checked"], 0)

    # ── options rows: symbol conventions differ per broker ──────────────

    def _open_options_trade(self, occ="AAPL250620C00190000"):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="options", symbol="AAPL", side="BUY",
            qty=Decimal("2"), entry_price=Decimal("3.00"),
            stop_loss=Decimal("2.40"), take_profit=Decimal("3.60"),
            status="OPEN", paper=False,
            metadata={"right": "C", "strike": 190.0, "expiry": "2026-06-20",
                       "multiplier": 100, "occ_symbol": occ},
        )

    def test_options_row_kept_open_when_broker_lists_occ_symbol(self):
        """Alpaca-style feed: the option appears under its OCC symbol, never
        the underlying. Matching trade.symbol against the stock feed used to
        orphan-close a still-open live option."""
        from bot_program.reconcile_asset import reconcile_user

        trade = self._open_options_trade()
        fake_client = MagicMock()
        fake_client.get_positions = MagicMock(return_value=[
            {"symbol": "AAPL250620C00190000"},
        ])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            r = reconcile_user(self.user)
        self.assertEqual(r["closed_as_orphan"], 0)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_options_row_kept_open_when_ibkr_reports_opt_underlying(self):
        """IBKR-style feed: OPT positions report the underlying + sec_type."""
        from bot_program.reconcile_asset import reconcile_user

        trade = self._open_options_trade(occ="")
        fake_client = MagicMock()
        fake_client.get_positions = MagicMock(return_value=[
            {"symbol": "AAPL", "sec_type": "OPT"},
        ])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            r = reconcile_user(self.user)
        self.assertEqual(r["closed_as_orphan"], 0)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_options_row_not_closed_when_feed_cannot_see_options(self):
        """No OCC symbol recorded and an untyped feed (e.g. only stock rows):
        we cannot tell whether the option is open — never guess-close it."""
        from bot_program.reconcile_asset import reconcile_user

        trade = self._open_options_trade(occ="")
        fake_client = MagicMock()
        fake_client.get_positions = MagicMock(return_value=[
            {"symbol": "AAPL"},  # the user's stock position, not the option
        ])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            r = reconcile_user(self.user)
        self.assertEqual(r["closed_as_orphan"], 0)
        self.assertEqual(r["broker_unavailable"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_options_orphan_closed_at_premium_scale(self):
        """A genuinely-closed option (sec-typed feed, no OPT rows) is closed
        at the entry premium (unknown current premium → zero P&L), never at
        the underlying's stock price."""
        from bot_program.reconcile_asset import reconcile_user

        trade = self._open_options_trade()
        fake_client = MagicMock()
        fake_client.get_positions = MagicMock(return_value=[
            {"symbol": "AAPL", "sec_type": "STK"},  # stock only, option gone
        ])
        fake_client.ticker = MagicMock(return_value={"lastPrice": "190"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=fake_client):
            r = reconcile_user(self.user)
        self.assertEqual(r["closed_as_orphan"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        # Premium scale (entry 3.00), NOT the underlying's 190.
        self.assertEqual(trade.exit_price, Decimal("3.00"))
        self.assertEqual(trade.pnl, Decimal("0.00"))


class BeatScheduleTests(TestCase):
    def test_reconciliation_in_beat(self):
        from config.celery import app
        self.assertIn("reconcile-asset-bot-trades", app.conf.beat_schedule)
        self.assertEqual(
            app.conf.beat_schedule["reconcile-asset-bot-trades"]["task"],
            "bot_program.tasks.reconcile_all_asset_bot_trades",
        )

    def test_no_in_app_backup_is_scheduled(self):
        """The in-app nightly dump shells out to pg_dump, which is not in the
        application image, and returns ok=False instead of raising -- so it
        recorded a SUCCESS in django-celery-results every night while
        producing nothing, and wrote to a path in no volume. The `backup`
        service in deploy/docker-compose.yml is the single real path."""
        from config.celery import app
        self.assertNotIn("daily-postgres-backup", app.conf.beat_schedule)


# ── 33.5 ─────────────────────────────────────────────────────────────────

class BackupTaskTests(TestCase):
    def test_skipped_on_sqlite(self):
        """Test database is sqlite in CI — backup must skip cleanly."""
        from core.backups import run_postgres_backup
        # The current test settings use sqlite by default.
        with patch.dict(settings.DATABASES["default"],
                         {"ENGINE": "django.db.backends.sqlite3"}):
            r = run_postgres_backup()
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "not_postgres")

    def test_skipped_when_pg_dump_missing(self):
        """pg_dump not on PATH → returns reason='pg_dump_not_found'."""
        from core.backups import run_postgres_backup
        with patch.dict(settings.DATABASES["default"],
                         {"ENGINE": "django.db.backends.postgresql"}), \
             patch("core.backups.shutil.which", return_value=None):
            r = run_postgres_backup()
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "pg_dump_not_found")

    def test_pg_dump_invocation(self):
        """When pg_dump exists + dir writable, subprocess.run gets the right args."""
        from core import backups
        with patch.dict(settings.DATABASES["default"], {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "test_db", "USER": "test_user", "PASSWORD": "p",
                "HOST": "test_host", "PORT": "5432",
            }), \
             patch("core.backups.shutil.which", return_value="/usr/bin/pg_dump"), \
             patch("core.backups.subprocess.run") as mock_run, \
             patch("core.backups._backup_dir",
                    return_value=Path(os.path.join(settings.BASE_DIR, "test_backups"))):
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            # Make the test backup dir.
            (Path(settings.BASE_DIR) / "test_backups").mkdir(exist_ok=True)
            try:
                r = backups.run_postgres_backup()
            finally:
                # Best-effort cleanup of any test artefacts.
                for f in (Path(settings.BASE_DIR) / "test_backups").glob("sauron-*.dump"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
        # subprocess.run called with pg_dump + -Fc.
        call_args = mock_run.call_args.args[0]
        self.assertEqual(call_args[0], "/usr/bin/pg_dump")
        self.assertIn("-Fc", call_args)
        self.assertIn("test_db", call_args)
        self.assertIn("test_user", call_args)
