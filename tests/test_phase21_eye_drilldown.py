"""Phase-21 Eye drill-down tests:
  - eye_gate_events: filter by decision/asset_class/symbol/q, pagination, stats
  - eye_fills: filter by asset_class/symbol/side/outcome/mode, stats
  - eye_exposure: per-position contribution table reflects classify_full
  - per-user scoping (user A doesn't see user B's events/trades)
  - main Eye page contains the drill-down links

Run with:  python manage.py test tests.test_phase21_eye_drilldown
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone


def _user(name="dd_u"):
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


def _gate_event(user, *, asset_class="stock", symbol="A", side="BUY",
                  decision="reject", reason="theme cap", **kw):
    from bot_program.models import OrchestratorEvent
    return OrchestratorEvent.objects.create(
        user=user, asset_class=asset_class, symbol=symbol, side=side,
        decision=decision, reason=reason,
        exposure_before={"usd": 0, "equity": 0},
        exposure_after={"usd": 0, "equity": 1},
        caps={"usd": 5, "equity": 5},
        **kw,
    )


def _trade(cfg, *, symbol, side, status="OPEN", **kw):
    from bot_program.models import AssetBotTrade
    defaults = dict(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal("1"), entry_price=Decimal("100"),
        status=status, paper=True,
    )
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


# ── eye_gate_events ───────────────────────────────────────────────────────

class GateEventsViewTests(TestCase):
    def setUp(self):
        self.user = _user("ge_u")
        self.client.force_login(self.user)

    def test_renders_empty(self):
        r = self.client.get("/eye/gate-events/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "GATE DECISIONS")
        self.assertContains(r, "No gate events match")

    def test_renders_events(self):
        _gate_event(self.user, symbol="AAA", decision="reject")
        _gate_event(self.user, symbol="BBB", decision="allow")
        r = self.client.get("/eye/gate-events/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "AAA")
        self.assertContains(r, "BBB")

    def test_decision_filter(self):
        _gate_event(self.user, symbol="REJECTED", decision="reject")
        _gate_event(self.user, symbol="ALLOWED", decision="allow")
        r = self.client.get("/eye/gate-events/?decision=reject")
        self.assertContains(r, "REJECTED")
        self.assertNotContains(r, "ALLOWED")

    def test_asset_class_filter(self):
        _gate_event(self.user, asset_class="stock", symbol="STK")
        _gate_event(self.user, asset_class="forex", symbol="FXX")
        r = self.client.get("/eye/gate-events/?asset_class=forex")
        self.assertContains(r, "FXX")
        self.assertNotContains(r, "STK")

    def test_symbol_filter_case_insensitive(self):
        _gate_event(self.user, symbol="aapl")
        r = self.client.get("/eye/gate-events/?symbol=AAPL")
        self.assertContains(r, "aapl")

    def test_q_search_in_reason(self):
        _gate_event(self.user, symbol="X", reason="orchestrator: equity theme cap")
        _gate_event(self.user, symbol="Y", reason="orchestrator: usd theme cap")
        r = self.client.get("/eye/gate-events/?q=equity")
        self.assertContains(r, "X")
        self.assertNotContains(r, "<td><strong>Y</strong></td>")

    def test_user_scoping(self):
        other = _user("ge_other")
        _gate_event(other, symbol="OTHER")
        _gate_event(self.user, symbol="MINE")
        r = self.client.get("/eye/gate-events/")
        self.assertContains(r, "MINE")
        self.assertNotContains(r, "OTHER")

    def test_pagination_two_pages(self):
        for i in range(60):
            _gate_event(self.user, symbol=f"S{i:03d}")
        r1 = self.client.get("/eye/gate-events/")
        self.assertEqual(r1.status_code, 200)
        # Page should have a "next" link.
        self.assertContains(r1, "next")
        r2 = self.client.get("/eye/gate-events/?page=2")
        self.assertEqual(r2.status_code, 200)

    def test_stats_on_page(self):
        for _ in range(3):
            _gate_event(self.user, decision="reject")
        for _ in range(7):
            _gate_event(self.user, decision="allow")
        r = self.client.get("/eye/gate-events/")
        self.assertContains(r, "0.30")  # 3/10 rejection rate


def _symbols(response):
    """Symbols in the fills TABLE, not in the whole document.

    The info-panel headband in base.html now lists the operator's OPEN
    positions on every page, so a symbol belonging to one of them appears in
    the chrome of every response — correctly. Asserting its absence from the
    raw HTML therefore tests the headband, not the filter. Assert on the rows
    the view actually selected instead.
    """
    return [t.symbol for t in response.context["page"]]

# ── eye_fills ─────────────────────────────────────────────────────────────

class FillsViewTests(TestCase):
    def setUp(self):
        self.user = _user("fl_u")
        self.cfg = _abc(self.user, "stock", name="ST")
        self.client.force_login(self.user)

    def test_renders_empty(self):
        r = self.client.get("/eye/fills/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "BOT TRADE HISTORY")

    def test_renders_trades(self):
        _trade(self.cfg, symbol="AAA", side="BUY")
        _trade(self.cfg, symbol="BBB", side="SELL")
        r = self.client.get("/eye/fills/")
        self.assertContains(r, "AAA")
        self.assertContains(r, "BBB")

    def test_side_filter(self):
        _trade(self.cfg, symbol="LONGSYM", side="BUY")
        _trade(self.cfg, symbol="DOWNSYM", side="SELL")
        r = self.client.get("/eye/fills/?side=BUY")
        self.assertEqual(_symbols(r), ["LONGSYM"])

    def test_outcome_filter(self):
        _trade(self.cfg, symbol="WIN", side="BUY", status="CLOSED",
                outcome="hit_target", realized_r=2.0,
                exit_price=Decimal("110"), pnl=Decimal("10"))
        _trade(self.cfg, symbol="LOSS", side="BUY", status="CLOSED",
                outcome="stopped_out", realized_r=-1.0,
                exit_price=Decimal("95"), pnl=Decimal("-5"))
        r = self.client.get("/eye/fills/?outcome=hit_target")
        self.assertEqual(_symbols(r), ["WIN"])

    def test_mode_filter(self):
        # Symbols must not collide with words rendered by the base-template
        # chrome (e.g. the ambient terminal stream prints PAPER / LIVE_SMALL),
        # or the contains-assertions test the decoration instead of the table.
        _trade(self.cfg, symbol="PAPSYM", side="BUY", paper=True)
        _trade(self.cfg, symbol="LIVSYM", side="BUY", paper=False)
        r = self.client.get("/eye/fills/?mode=live")
        self.assertEqual(_symbols(r), ["LIVSYM"])

    def test_user_scoping(self):
        other = _user("fl_other")
        other_cfg = _abc(other, "stock", name="OTH")
        _trade(other_cfg, symbol="OTHER", side="BUY")
        _trade(self.cfg, symbol="MINE", side="BUY")
        r = self.client.get("/eye/fills/")
        self.assertEqual(_symbols(r), ["MINE"])


# ── eye_exposure ──────────────────────────────────────────────────────────

class ExposureViewTests(TestCase):
    def setUp(self):
        self.user = _user("ex_u")
        self.client.force_login(self.user)

    def test_renders_empty(self):
        r = self.client.get("/eye/exposure/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "EXPOSURE BREAKDOWN")
        self.assertContains(r, "No open positions")

    def test_per_position_contributions_table(self):
        cfg = _abc(self.user, "forex", name="FX")
        _trade(cfg, symbol="EURUSD", side="BUY")
        r = self.client.get("/eye/exposure/")
        self.assertContains(r, "EURUSD")
        # Currency cell should contain EUR + USD entries.
        self.assertContains(r, "EUR")
        self.assertContains(r, "USD")

    def test_size_weighted_pill_when_enabled(self):
        from portfolio.trader_profile import TraderProfile
        TraderProfile.objects.create(user=self.user,
                                       size_weighted_orchestrator=True)
        r = self.client.get("/eye/exposure/")
        self.assertContains(r, "size-weighted")


# ── Eye main page contains drill-down links ──────────────────────────────

class EyeLinksTests(TestCase):
    def test_eye_page_has_drilldown_links(self):
        u = _user("links_u")
        c = Client()
        c.force_login(u)
        r = c.get("/eye/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "history →")     # gate events
        self.assertContains(r, "all fills →")   # fills
        self.assertContains(r, "breakdown →")   # exposure
