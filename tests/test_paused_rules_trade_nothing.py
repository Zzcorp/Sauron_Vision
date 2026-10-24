"""A PAUSED RULE PLACES NO NEW ENTRY (2026-10-24).

A pause (RuleAction "pause_rule" from the decay investigator's proposals,
or brain.demoter.demote_rule) stops a rule's NEW signals only. The
signals it fired before the pause stay active for max_signal_age_hours
(24 h by default), and nothing between the vote and the order read the
pause: decide() filtered votes on stage_policy alone, which never reads
RuleControl.status, and admin_allocator_multiplier honours the weight
only for a "reduced" rule, so a paused rule's weight of 0 read as 1.0. A
paused live_full rule's older signals won the vote and entered at full
real-money size.

Now a paused rule casts no vote in decide(), and the stage gate of the
bot lane and of the options lane refuses an entry whose winning rule is
paused (STAGE_BLOCKED, "rule paused — no new entries"). A pause whose
paused_until has passed is no pause. Only fewer entries; nothing else
moves.

Run with:  python manage.py test tests.test_paused_rules_trade_nothing
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from tests.test_evidence_honesty import _cfg, _instrument, _signal


def _control(rule, *, stage="live_full", paused=True, until_days=7):
    from signals.models import RuleControl
    return RuleControl.objects.create(
        rule_name=rule, promotion_stage=stage,
        status=RuleControl.STATUS_PAUSED if paused else
        RuleControl.STATUS_ACTIVE,
        weight_multiplier=0.0 if paused else 1.0,
        paused_until=timezone.now() + timedelta(days=until_days)
        if paused else None)


class TheVoteTests(TestCase):
    """The review's probe: two paused live_full rules, one active bullish
    signal each, fired before the pause, on a live stock config that
    needs two votes."""

    def setUp(self):
        self.user = User.objects.create_user("pz_u", password="x")
        self.inst = _instrument("VOTEX", asset_class="stock")
        self.cfg = _cfg(self.user, asset_class="stock", name="Paused",
                        mode="live", symbols=["VOTEX"],
                        capital=Decimal("10000"), min_signals_for_entry=2)

    def _decide(self):
        from bot_program.asset_engine import StockBot
        return StockBot(self.cfg).decide("VOTEX")

    def _two(self, **kw):
        for rn in ("golden_cross", "macd_cross"):
            _control(rn, **kw)
            _signal(self.inst, rule=rn, score=0.85)

    def test_a_paused_rule_casts_no_vote(self):
        self._two()
        d = self._decide()
        self.assertEqual(d.direction, "HOLD", d.reasons)
        self.assertIn("paused", " ".join(d.reasons))

    def test_an_active_rule_still_votes(self):
        """A regression pin: the same two rules active trade as before."""
        self._two(paused=False)
        d = self._decide()
        self.assertEqual(d.direction, "BUY", d.reasons)

    def test_a_pause_past_its_end_is_no_pause(self):
        self._two(until_days=-1)
        self.assertEqual(self._decide().direction, "BUY")

    def test_one_paused_rule_leaves_the_other_short_of_the_two_votes(self):
        _control("golden_cross")
        _control("macd_cross", paused=False)
        for rn in ("golden_cross", "macd_cross"):
            _signal(self.inst, rule=rn, score=0.85)
        d = self._decide()
        self.assertEqual(d.direction, "HOLD", d.reasons)
        self.assertNotEqual(d.rule_name, "golden_cross")

    def test_an_unread_control_casts_no_vote(self):
        self._two(paused=False)
        with patch("signals.rule_actuator.is_rule_active",
                   side_effect=RuntimeError("db gone")):
            self.assertEqual(self._decide().direction, "HOLD")


class TheBotLaneGateTests(TestCase):
    """The stage gate itself: a decision whose winning rule is paused
    (however it got there) is skipped STAGE_BLOCKED before any size."""

    def setUp(self):
        self.user = User.objects.create_user("pz_g", password="x")
        _instrument()

    def _scan(self, cfg):
        from bot_program.asset_engine import make_bot
        from bot_program.asset_engine.base import BotDecision
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        client.get_positions = MagicMock(return_value=[])
        bot = make_bot(cfg)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client), \
                patch.object(bot, "decide", return_value=BotDecision(
                    "BUY", 0.9, ["signal"], rule_name="r_chain")):
            return bot.scan_symbol("BTCUSD")

    def test_a_paused_winning_rule_is_stage_blocked(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        _control("r_chain", stage="paper")
        cfg = _cfg(self.user, name="PZ1")
        self.assertIsNone(self._scan(cfg))
        self.assertFalse(AssetBotTrade.objects.filter(config=cfg).exists())
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg)["BTCUSD"]
        self.assertEqual(note["code"], skips.STAGE_BLOCKED)
        self.assertEqual(note["detail"], "rule paused — no new entries")
        self.assertIn("or it is paused", skips.diagnose(cfg))

    def test_the_same_rule_active_still_trades(self):
        """A regression pin: the gate reads the pause, nothing else."""
        from bot_program.models import AssetBotTrade
        _control("r_chain", stage="paper", paused=False)
        cfg = _cfg(self.user, name="PZ2")
        self._scan(cfg)
        self.assertTrue(AssetBotTrade.objects.filter(config=cfg).exists())

    def test_the_phone_words_name_the_pause(self):
        from bot_program.asset_engine import skips
        from bot_program.telegram_eye import SKIP_WORDS
        self.assertIn("paused", SKIP_WORDS[skips.STAGE_BLOCKED])


class TheOptionsLaneGateTests(TestCase):
    """The options lane replaces scan_symbol and has its own stage gate."""

    RULE = "pz_opt_rule"

    def setUp(self):
        from tests.test_paper_market_hours import _user
        self.user = _user("pz_opt")
        self.n = 0

    def _scan(self, client, *, paused):
        from bot_program.asset_engine.base import BotDecision
        from bot_program.asset_engine.options_bot import OptionsBot
        from bot_program.models import AssetBotConfig
        from bot_program.options_models import OptionContract
        from portfolio.risk_gate import limits_book
        from signals.models import RuleControl
        from tests.test_paper_market_hours import ROUTER, _inst
        RuleControl.objects.filter(rule_name=self.RULE).delete()
        _control(self.RULE, stage="live_full", paused=paused)
        pf = limits_book()
        pf.current_value = Decimal("10000")
        pf.max_single_position_pct = 100.0
        pf.save()
        inst = _inst("AAPL", "stock")
        self.n += 1
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="options", name=f"pz_opt_{self.n}",
            enabled=True, mode="live", symbols=["AAPL"],
            capital=Decimal("1000000"), stop_loss_pct=20.0,
            take_profit_pct=50.0)
        OptionContract.objects.get_or_create(
            underlying=inst, strike=Decimal("180"),
            expiry=timezone.now().date() + timedelta(days=30), right="C",
            defaults=dict(multiplier=100, bid=Decimal("1.00"),
                          ask=Decimal("1.02"), last_price=Decimal("1.01"),
                          iv=0.30, delta=0.41))
        bot = OptionsBot(cfg)
        corr = {"scale": 1.0, "max_corr": 0.0, "peer": "",
                "threshold": 0.7, "measured": True, "reason": ""}
        with mock.patch.object(bot, "decide", return_value=BotDecision(
                "BUY", 0.9, ["signal"], rule_name=self.RULE)), \
                mock.patch(ROUTER, return_value=client), \
                mock.patch("portfolio.risk_gate.correlation_state",
                           return_value=corr):
            return bot.scan_symbol("AAPL")

    @staticmethod
    def _client():
        client = mock.MagicMock(name="fake_live_options_client")
        client.market_order_option.side_effect = RuntimeError("socket closed")
        return client

    def test_a_paused_rule_sends_no_option_order(self):
        client = self._client()
        self.assertIsNone(self._scan(client, paused=True))
        client.market_order_option.assert_not_called()
        # a regression pin: the same rule active reaches the venue
        client = self._client()
        self._scan(client, paused=False)
        client.market_order_option.assert_called_once()


class TheBookSaysItTests(TestCase):

    def test_the_book_says_a_paused_rule_opens_nothing_new(self):
        from core import book_content as book
        text = [i["text"] for c in book.CHAPTERS
                for i in (c.get("items") or [])
                if isinstance(i, dict) and i.get("title") == "The brain"][0]
        self.assertIn("a paused rule opens nothing new, not even on the "
                      "signals it gave before the pause", text)
