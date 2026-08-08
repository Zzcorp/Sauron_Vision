"""Phase-28 audit log tests:
  - record_event creates a chained row + correct hash
  - hash_payload is deterministic
  - update / delete on AuditLogEntry raises IntegrityError
  - verify_chain returns ok for clean chain, breaks on tamper
  - hooks fire from trade_open + trade_close + gate_reject
  - admin-only views: dashboard renders, export returns CSV
  - non-admin redirected from /audit/

Run with:  python manage.py test tests.test_phase28_audit
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase, Client


def _user(name="au_u", staff=False):
    u = User.objects.create_user(username=name, password="x")
    if staff:
        u.is_staff = True
        u.save()
    return u


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


# ── hash_payload ─────────────────────────────────────────────────────────

class HashPayloadTests(TestCase):
    def test_deterministic(self):
        from bot_program.audit import hash_payload
        a = hash_payload("prev", "trade_open", {"x": 1, "y": 2})
        b = hash_payload("prev", "trade_open", {"y": 2, "x": 1})
        self.assertEqual(a, b)  # JSON canonicalised

    def test_hash_changes_on_data_change(self):
        from bot_program.audit import hash_payload
        a = hash_payload("prev", "trade_open", {"x": 1})
        b = hash_payload("prev", "trade_open", {"x": 2})
        self.assertNotEqual(a, b)


# ── Append-only ───────────────────────────────────────────────────────────

class ImmutabilityTests(TestCase):
    def test_record_event_creates_genesis_chain(self):
        from bot_program.audit import record_event
        from bot_program.audit_models import GENESIS_HASH
        e = record_event("system", {"hello": "world"})
        self.assertEqual(e.prev_hash, GENESIS_HASH)
        self.assertTrue(e.payload_hash)
        self.assertEqual(len(e.payload_hash), 64)

    def test_subsequent_entry_chains_to_previous(self):
        from bot_program.audit import record_event
        e1 = record_event("system", {"a": 1})
        e2 = record_event("system", {"b": 2})
        self.assertEqual(e2.prev_hash, e1.payload_hash)

    def test_save_on_existing_row_raises(self):
        from bot_program.audit import record_event
        e = record_event("system", {"a": 1})
        e.data = {"a": 999}
        with self.assertRaises(IntegrityError):
            e.save()

    def test_delete_raises(self):
        from bot_program.audit import record_event
        e = record_event("system", {"a": 1})
        with self.assertRaises(IntegrityError):
            e.delete()


# ── verify_chain ──────────────────────────────────────────────────────────

class VerifyChainTests(TestCase):
    def test_clean_chain_ok(self):
        from bot_program.audit import record_event, verify_chain
        for i in range(5):
            record_event("system", {"i": i})
        result = verify_chain()
        self.assertTrue(result["ok"])
        self.assertEqual(result["verified"], 5)
        self.assertEqual(result["breaks"], [])

    def test_tampered_payload_detected(self):
        from bot_program.audit import record_event, verify_chain
        from bot_program.models import AuditLogEntry
        record_event("system", {"a": 1})
        e2 = record_event("system", {"a": 2})
        record_event("system", {"a": 3})
        # Tamper directly via QuerySet.update (bypasses save() guard).
        AuditLogEntry.objects.filter(pk=e2.pk).update(data={"a": 999})
        result = verify_chain()
        self.assertFalse(result["ok"])
        self.assertTrue(any(b["type"] == "payload_tampered" for b in result["breaks"]))

    def test_prev_hash_mismatch_detected(self):
        from bot_program.audit import record_event, verify_chain
        from bot_program.models import AuditLogEntry
        record_event("system", {"a": 1})
        e2 = record_event("system", {"a": 2})
        # Corrupt e2's prev_hash.
        AuditLogEntry.objects.filter(pk=e2.pk).update(prev_hash="0" * 64)
        result = verify_chain()
        self.assertFalse(result["ok"])
        self.assertTrue(any(b["type"] == "prev_hash_mismatch" for b in result["breaks"]))


# ── Hook integration ─────────────────────────────────────────────────────

class HookIntegrationTests(TestCase):
    def test_trade_open_appends_to_audit(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AuditLogEntry
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from signals.models import Signal

        u = _user("hk_o_u")
        cfg = _abc(u, "stock", name="ST", symbols=["AAPL"])
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        LiveQuote.objects.create(instrument=inst, last=Decimal("100"))
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name="r1",
            score=0.85, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        )
        result = StockBot(cfg).scan_symbol("AAPL")
        self.assertIsNotNone(result)
        entries = AuditLogEntry.objects.filter(kind="trade_open")
        self.assertEqual(entries.count(), 1)
        e = entries.first()
        self.assertEqual(e.data["symbol"], "AAPL")
        self.assertEqual(e.data["side"], "BUY")
        self.assertEqual(e.user, u)

    def test_trade_close_appends_to_audit(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.engine.paper_trader import PaperTrader
        from bot_program.models import AssetBotTrade, AuditLogEntry

        u = _user("hk_c_u")
        cfg = _abc(u, "stock", name="ST")

        class _Stub(AssetBot):
            asset_class = "stock"
        bot = _Stub(cfg)

        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="OPEN", paper=True, rule_name="r1",
        )
        client = PaperTrader(cfg)
        bot._close_trade(trade, Decimal("104"), client, reason="TP")

        entries = AuditLogEntry.objects.filter(kind="trade_close")
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().data["symbol"], "AAPL")
        self.assertEqual(entries.first().data["outcome"], "hit_target")

    def test_gate_reject_appends_to_audit(self):
        from bot_program.orchestrator import gate_new_entry
        from bot_program.models import AssetBotTrade, AuditLogEntry
        from portfolio.trader_profile import TraderProfile

        u = _user("hk_g_u")
        TraderProfile.objects.create(
            user=u, cross_asset_orchestrator_enabled=True,
            max_equity_theme_exposure=2.0, max_usd_theme_exposure=10.0)
        st = _abc(u, "stock", name="ST")
        AssetBotTrade.objects.create(
            config=st, asset_class="stock", symbol="A", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN")
        AssetBotTrade.objects.create(
            config=st, asset_class="stock", symbol="B", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN")
        ok, _ = gate_new_entry(u, "stock", "C", "BUY")
        self.assertFalse(ok)
        entries = AuditLogEntry.objects.filter(kind="gate_reject")
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().data["symbol"], "C")
        self.assertIn("equity", entries.first().data["reason"])


# ── Admin views ───────────────────────────────────────────────────────────

class AdminViewTests(TestCase):
    def test_non_staff_redirected(self):
        u = _user("nostaff")
        c = Client()
        c.force_login(u)
        r = c.get("/audit/")
        self.assertIn(r.status_code, (302, 403))

    def test_staff_can_view_dashboard(self):
        from bot_program.audit import record_event
        u = _user("staff_u", staff=True)
        record_event("system", {"hello": "world"})
        c = Client()
        c.force_login(u)
        r = c.get("/audit/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "AUDIT LOG")
        self.assertContains(r, "✓ OK")  # chain integrity

    def test_csv_export_returns_attachment(self):
        from bot_program.audit import record_event
        u = _user("staff_csv", staff=True)
        record_event("trade_open", {"symbol": "AAPL", "side": "BUY"})
        c = Client()
        c.force_login(u)
        r = c.get("/audit/export/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn(b"trade_open", r.content)
        self.assertIn(b"AAPL", r.content)

    def test_export_filter_by_kind(self):
        from bot_program.audit import record_event
        u = _user("staff_filter", staff=True)
        record_event("trade_open", {"symbol": "A"})
        record_event("trade_close", {"symbol": "B"})
        c = Client()
        c.force_login(u)
        r = c.get("/audit/export/?kind=trade_open")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"trade_open", r.content)
        # b"trade_close" should NOT appear in filtered export
        self.assertNotIn(b"trade_close", r.content)
