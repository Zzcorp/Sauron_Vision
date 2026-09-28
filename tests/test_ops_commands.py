"""The admin pages' decisions, as shell commands.

The operator asked for commands that do the thing, not descriptions of
which toggle to find on which page. Three commands mirror three pages:
`component on|off|list` is the health page's toggle, `proposals
list|approve|reject` is the brain page's click, `open_trades` is the
positions view with the platform's own mark, unrealised P&L and R.

Run with:  python manage.py test tests.test_ops_commands
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

User = get_user_model()


def _run(*args, **kw):
    out = StringIO()
    call_command(*args, stdout=out, **kw)
    return out.getvalue()


class ComponentCommandTests(TestCase):

    def setUp(self):
        from core.platform_control import seed_components
        seed_components()

    def test_on_and_off_are_the_health_toggle(self):
        from core.platform_control import PlatformComponent
        out = _run("component", "on", "generator_auto_research")
        self.assertIn("generator_auto_research: OFF → ON", out)
        self.assertTrue(PlatformComponent.objects.get(
            key="generator_auto_research").is_enabled)
        out = _run("component", "off", "generator_auto_research")
        self.assertIn("ON → OFF", out)
        self.assertFalse(PlatformComponent.objects.get(
            key="generator_auto_research").is_enabled)
        out = _run("component", "off", "generator_auto_research")
        self.assertIn("(unchanged)", out)

    def test_an_unknown_key_is_refused_with_the_nearest_names(self):
        with self.assertRaises(CommandError) as ctx:
            _run("component", "on", "generator_auto_reserch")
        self.assertIn("unknown component", str(ctx.exception))
        self.assertIn("generator_auto_research", str(ctx.exception))

    def test_a_known_but_unregistered_key_is_seeded_then_set(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(key="generator_auto_research").delete()
        out = _run("component", "on", "generator_auto_research")
        self.assertIn("registered", out)
        self.assertTrue(PlatformComponent.objects.get(
            key="generator_auto_research").is_enabled)

    def test_list_shows_every_component_with_its_state(self):
        _run("component", "on", "platform_master")
        out = _run("component", "list")
        self.assertIn("ON   platform_master", out)
        self.assertIn("OFF  generator_auto_research", out)
        self.assertIn("[agent]", out)
        out = _run("component", "list", category="agent")
        self.assertNotIn("platform_master", out)
        self.assertIn("generator_auto_research", out)

    def test_master_off_says_what_it_did(self):
        _run("component", "on", "platform_master")
        out = _run("component", "off", "platform_master")
        self.assertIn("every automated task is stopped", out)

    def test_on_without_a_key_is_an_error(self):
        with self.assertRaises(CommandError):
            _run("component", "on")


def _proposal(slug, conditions=None):
    from brain.strategy_generator import _persist_proposal
    return _persist_proposal({
        "name_slug": slug, "rationale_md": "built on the ledger",
        "inspiration": "ledger", "direction": "bullish",
        "asset_classes": ["stock"],
        "conditions": conditions or [{"kind": "price_pattern",
                                      "params": {"pattern": "above_ma"},
                                      "weight": 1.0}],
        "min_match_score": 0.6, "suggested_horizon_days": 5,
        "confidence": 0.6,
    }, model="claude-fable-5-1", tokens_in=1, tokens_out=1, cost_usd=0.0)


class ProposalsCommandTests(TestCase):

    def test_approve_arms_in_research_like_the_page(self):
        from brain.generator_models import GeneratedSetupProposal as P
        row = _proposal("cli_armed")
        out = _run("proposals", "approve", str(row.pk))
        self.assertIn("ARMED in research", out)
        row.refresh_from_db()
        self.assertEqual(row.status, P.STATUS_APPROVED)
        self.assertEqual(row.reviewed_by, "cli")
        self.assertTrue(row.setup.is_active)
        self.assertEqual(row.rule_control.promotion_stage, "research")

    def test_a_blocked_approval_prints_the_blocker(self):
        from brain.generator_models import GeneratedSetupProposal as P
        row = _proposal("cli_blocked")
        # The page's own trap: a param the evaluator never reads, written
        # onto the setup after validation.
        row.setup.conditions = [{"kind": "price_pattern",
                                 "params": {"invented": 1}, "weight": 1.0}]
        row.setup.save()
        out = _run("proposals", "approve", str(row.pk))
        self.assertIn("NOT armed", out)
        self.assertIn("invented", out)
        row.refresh_from_db()
        self.assertEqual(row.status, P.STATUS_PENDING)

    def test_reject_and_already_decided(self):
        from brain.generator_models import GeneratedSetupProposal as P
        row = _proposal("cli_rejected")
        out = _run("proposals", "reject", str(row.pk), notes="twin of x")
        self.assertIn("rejected", out)
        row.refresh_from_db()
        self.assertEqual(row.status, P.STATUS_REJECTED)
        self.assertEqual(row.review_notes, "twin of x")
        out = _run("proposals", "approve", str(row.pk))
        self.assertIn("already rejected, untouched", out)
        out = _run("proposals", "approve", "999999")
        self.assertIn("not found", out)

    def test_list_shows_pending_and_the_decided_with_why(self):
        pending = _proposal("cli_pending")
        gone = _proposal("cli_gone")
        _run("proposals", "reject", str(gone.pk), notes="because")
        out = _run("proposals", "list")
        self.assertIn("PENDING (1)", out)
        self.assertIn(f"#{pending.pk}", out)
        self.assertIn("price_pattern", out)
        self.assertIn("built on the ledger", out)
        self.assertIn("REJECTED", out)
        self.assertIn("because", out)


class OpenTradesCommandTests(TestCase):

    def setUp(self):
        from bot_program.asset_models import AssetBotConfig
        self.user = User.objects.create_user("ot_u", password="x")
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="crypto", name="Crypto live",
            mode="live", symbols=["SOLUSD"], capital=Decimal("1000"),
            enabled=True)

    def _trade(self, **kw):
        from bot_program.asset_models import AssetBotTrade
        base = dict(config=self.cfg, asset_class="crypto", symbol="SOLUSD",
                    side="BUY", qty=Decimal("2"), entry_price=Decimal("200"),
                    stop_loss=Decimal("190"), take_profit=Decimal("230"),
                    status="OPEN", paper=False, rule_name="momo",
                    reason="breakout")
        base.update(kw)
        return AssetBotTrade.objects.create(**base)

    def test_a_live_position_is_marked_and_measured_in_r(self):
        self._trade()
        with patch("ai_agents.calibration.mark_for_symbol",
                   return_value=185.0):
            out = _run("open_trades")
        self.assertIn("LIVE", out)
        self.assertIn("(crypto/live)", out)
        self.assertIn("BUY 2 SOLUSD @ 200", out)
        self.assertIn("stop 190", out)
        self.assertIn("mark 185", out)
        # 2 × (185 − 200) = −30; (185 − 200) / 10 = −1.5R
        self.assertIn("unrealised -30.00", out)
        self.assertIn("-1.50R", out)
        self.assertIn("rule momo", out)
        self.assertIn("why: breakout", out)
        self.assertIn("1 live, 0 paper open", out)

    def test_a_position_without_a_stop_is_flagged(self):
        self._trade(stop_loss=None, paper=True)
        with patch("ai_agents.calibration.mark_for_symbol",
                   return_value=210.0):
            out = _run("open_trades")
        self.assertIn("NO STOP", out)
        self.assertIn("unrealised +20.00", out)
        self.assertIn("0 live, 1 paper open", out)

    def test_sell_side_and_no_mark(self):
        self._trade(side="SELL", stop_loss=Decimal("210"))
        with patch("ai_agents.calibration.mark_for_symbol",
                   return_value=None):
            out = _run("open_trades")
        self.assertIn("no mark", out)
        with patch("ai_agents.calibration.mark_for_symbol",
                   return_value=205.0):
            out = _run("open_trades")
        # short from 200, mark 205: −5 per unit × 2; risk 10 → −0.5R
        self.assertIn("unrealised -10.00", out)
        self.assertIn("-0.50R", out)

    def test_symbol_filter_and_empty(self):
        self._trade()
        with patch("ai_agents.calibration.mark_for_symbol",
                   return_value=200.0):
            self.assertIn("SOLUSD", _run("open_trades", symbol="sol"))
            self.assertIn("no open positions",
                          _run("open_trades", symbol="BTC"))

    def test_the_legacy_crypto_bot_is_read_too(self):
        """The Solana position lived in the legacy crypto bot (BotTrade,
        Binance) and the first cut of this command did not look there."""
        from bot_program.models import BotConfig, BotTrade
        legacy = BotConfig.objects.create(user=self.user, name="Sauron Bot",
                                          mode="paper", symbols=["SOLUSDT"])
        BotTrade.objects.create(
            config=legacy, symbol="SOLUSDT", side="BUY", qty=Decimal("10"),
            entry_price=Decimal("150"), stop_loss=Decimal("140"),
            status="OPEN", paper=True, reason="momentum")
        with patch("ai_agents.calibration.mark_for_symbol",
                   return_value=120.0):
            out = _run("open_trades", symbol="SOL")
        self.assertIn("[legacy] Sauron Bot (crypto/paper)", out)
        self.assertIn("BUY 10 SOLUSDT @ 150", out)
        # 10 × (120 − 150) = −300 USDT; (120 − 150) / 10 = −3R
        self.assertIn("unrealised -300.00 USDT", out)
        self.assertIn("-3.00R", out)
        self.assertIn("0 live, 1 paper open", out)

    def test_fx_pnl_names_its_quote_currency(self):
        """−8140 on EURJPY is yen, not euros; the line must say so."""
        self._trade(asset_class="forex", symbol="EURJPY", qty=Decimal("6400"),
                    entry_price=Decimal("179.5"), stop_loss=Decimal("177"),
                    take_profit=None)
        with patch("ai_agents.calibration.mark_for_symbol",
                   return_value=178.25):
            out = _run("open_trades")
        self.assertIn("unrealised -8000.00 JPY", out)
        self.assertIn("-0.50R", out)

    def test_all_includes_recent_closed_rows(self):
        from django.utils import timezone
        self._trade(status="CLOSED", exit_price=Decimal("230"),
                    closed_at=timezone.now())
        self.assertIn("no open positions", _run("open_trades"))
        out = _run("open_trades", all=True)
        self.assertIn("CLOSED", out)
        self.assertIn("+60.00", out)
        self.assertIn("+3.00R", out)
