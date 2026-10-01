"""One daily stop; past it, elite entries only, until the absolute stop.

The operator, 2026-10-01: a stop at 8%, but a restart when a signal is
purely interesting and profitable — "a resilient Sauron". He chose:

- ONE daily stop, the book's MAX DAILY LOSS. A bot's own percentage
  applies only when the book's cannot be measured.
- Past it, a bot may still open an ELITE entry: the rule's record on the
  venue the order goes to (n >= 20, win >= 55%, avg R >= +0.20) and a net
  reward:risk after costs >= 2.0 — at half size, at most 2 per venue in
  the trailing 24 h.
- At 1.5x the limit, the absolute stop: nothing opens.

Pinned here: the three modes of the day, the gate (open for elite only,
the allowance, the absolute stop), the one stop superseding a bot's own,
the elite verdict, the allowance count, and the wiring.

Run with:  python manage.py test tests.test_elite_past_daily_stop
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tests.test_risk_limits_bind import _book, _closed_trade, _config

RECORD = "bot_program.bot_grading.bot_track_record_detail"


def _elite_row(cfg, *, hours_ago=1, paper=True):
    from bot_program.models import AssetBotTrade
    from portfolio.risk_gate import ELITE_META_KEY
    row = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="BTCUSD", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
        paper=paper, metadata={ELITE_META_KEY: True})
    AssetBotTrade.objects.filter(pk=row.pk).update(
        opened_at=timezone.now() - timedelta(hours=hours_ago))
    return row


class TheModesTests(TestCase):
    """10,000 book at 3%: the floor -300, the absolute stop -450."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("el_modes",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        self.cfg = _config(self.user)

    def _state(self):
        from portfolio.risk_gate import daily_loss_state
        return daily_loss_state(self.user, venue="paper")

    def test_inside_the_limit_is_open(self):
        _closed_trade(self.cfg, -200)
        s = self._state()
        self.assertTrue(s["ok"])
        self.assertEqual(s["mode"], "open")
        self.assertEqual((s["hard_pct"], s["hard_money"]), (4.5, -450.0))

    def test_past_the_limit_is_elite_only_and_still_reads_hit(self):
        _closed_trade(self.cfg, -400)
        s = self._state()
        self.assertFalse(s["ok"])
        self.assertEqual(s["mode"], "elite")
        self.assertIn("daily loss limit hit", s["reason"])
        self.assertIn("elite entries only, at 0.5x size and at most 2 in "
                      "24h, until the absolute stop at -450.00", s["reason"])

    def test_past_the_absolute_stop_is_shut(self):
        _closed_trade(self.cfg, -450)
        s = self._state()
        self.assertFalse(s["ok"])
        self.assertEqual(s["mode"], "shut")
        self.assertIn("-300.00 floor", s["reason"])
        self.assertIn("past the -450.00 absolute stop (4.5%) — nothing "
                      "opens, elite entries included", s["reason"])

    def test_preflight_says_elite_only_when_nothing_else_binds(self):
        from portfolio.risk_gate import preflight
        _closed_trade(self.cfg, -400)
        self.assertTrue(preflight(self.user, venue="paper")["elite_only"])
        _closed_trade(self.cfg, -100)
        self.assertFalse(preflight(self.user, venue="paper")["elite_only"])

    def test_preflight_is_not_elite_only_when_exposure_binds_too(self):
        from portfolio.risk_gate import preflight
        from tests.test_risk_limits_bind import _open_trade
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0,
              max_total_exposure_pct=10.0)
        _closed_trade(self.cfg, -400)
        _open_trade(self.cfg, entry="5000", qty="1")
        out = preflight(self.user, venue="paper")
        self.assertFalse(out["ok"])
        self.assertFalse(out["elite_only"])


class TheGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("el_gate",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)

    def _bot(self, **kw):
        from bot_program.asset_engine.base import make_bot
        return make_bot(_config(self.user, symbols=["BTCUSD"], **kw))

    def test_past_the_limit_the_gate_is_open_for_elite_only(self):
        bot = self._bot()
        _closed_trade(bot.cfg, -400)
        ok, reason = bot.can_open_new()
        self.assertTrue(ok, reason)
        self.assertIn("elite entries only", bot._elite_only)

    def test_an_ordinary_day_carries_no_elite_flag(self):
        bot = self._bot()
        ok, _ = bot.can_open_new()
        self.assertTrue(ok)
        self.assertEqual(bot._elite_only, "")

    def test_the_allowance_spent_shuts_the_gate(self):
        bot = self._bot()
        _closed_trade(bot.cfg, -400)
        _elite_row(bot.cfg)
        _elite_row(bot.cfg)
        ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("the elite allowance is spent (2 of 2)", reason)

    def test_the_allowance_is_the_venues_and_the_windows(self):
        bot = self._bot()
        _closed_trade(bot.cfg, -400)
        _elite_row(bot.cfg, paper=False)
        _elite_row(bot.cfg, paper=False)
        _elite_row(bot.cfg, hours_ago=30)
        ok, reason = bot.can_open_new()
        self.assertTrue(ok, reason)

    def test_past_the_absolute_stop_nothing_opens(self):
        bot = self._bot()
        _closed_trade(bot.cfg, -500)
        ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("absolute stop", reason)


class TheOneStopTests(TestCase):
    """A bot's own 2% of its pool no longer stops it before the book's."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("el_one",
                                                        password="x")

    def _bot(self):
        from bot_program.asset_engine.base import make_bot
        return make_bot(_config(self.user, symbols=["BTCUSD"],
                                max_daily_loss_pct=2.0))

    def test_the_books_stop_supersedes_the_bots_own(self):
        _book(current_value=Decimal("10000"), max_daily_loss_pct=3.0)
        bot = self._bot()
        _closed_trade(bot.cfg, -250)      # past 2% of the pool, inside 3%
        ok, reason = bot.can_open_new()
        self.assertTrue(ok, reason)

    def test_without_a_measurable_book_the_bots_own_applies(self):
        _book(current_value=Decimal("0"), max_daily_loss_pct=3.0)
        bot = self._bot()
        _closed_trade(bot.cfg, -250)
        ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("daily loss limit hit (-250.00", reason)


class TheVerdictTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("el_verdict",
                                                        password="x")

    def setUp(self):
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(_config(self.user, symbols=["BTCUSD"]))
        self.decision = SimpleNamespace(rule_name="golden_cross",
                                        direction="BUY", score=0.9)

    def _verdict(self, rec, *, tp=106.0, cost=0.0):
        with patch(RECORD, return_value=rec) as read:
            out = self.bot._elite_verdict("BTCUSD", self.decision,
                                          price=100.0, sl=98.0, tp=tp,
                                          cost_fraction=cost)
        return out, read

    def test_a_measured_edge_and_a_wide_target_is_elite(self):
        out, read = self._verdict({"n": 25, "win_rate": 0.60,
                                   "expectancy": 0.30})
        self.assertTrue(out["elite"], out["why"])
        self.assertEqual(out["net_rr"], 3.0)
        # the venue the order goes to, never the pooled record
        self.assertEqual(read.call_args.kwargs["venue"], "paper")

    def test_each_missing_half_is_named(self):
        for rec, words in (
                ({"n": 10, "win_rate": 0.70, "expectancy": 0.50}, "n 10"),
                ({"n": 30, "win_rate": 0.50, "expectancy": 0.40}, "win 50%"),
                ({"n": 30, "win_rate": 0.60, "expectancy": 0.10},
                 "avg R +0.10")):
            out, _ = self._verdict(rec)
            self.assertFalse(out["elite"], rec)
            self.assertIn(words, out["why"])
            self.assertIn("elite needs n >= 20", out["why"])

    def test_a_target_too_close_after_costs_is_not_elite(self):
        out, read = self._verdict({"n": 25, "win_rate": 0.60,
                                   "expectancy": 0.30}, tp=104.0, cost=0.002)
        self.assertFalse(out["elite"])
        self.assertIn("net reward:risk 1.73 after costs, elite needs 2.00",
                      out["why"])
        read.assert_not_called()

    def test_an_unread_record_is_never_elite(self):
        with patch(RECORD, side_effect=RuntimeError("db")), \
                self.assertLogs("bot_program.asset_engine.base", "WARNING"):
            out = self.bot._elite_verdict("BTCUSD", self.decision,
                                          price=100.0, sl=98.0, tp=106.0)
        self.assertFalse(out["elite"])

    def test_no_rule_is_never_elite(self):
        self.decision.rule_name = ""
        out, _ = self._verdict({"n": 25, "win_rate": 0.6, "expectancy": 0.3})
        self.assertFalse(out["elite"])


class TheWiringTests(TestCase):

    def test_propose_halves_an_elite_candidate_and_carries_the_verdict(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        self.assertIn('if getattr(self, "_elite_only", ""):', src)
        self.assertIn("qty *= ELITE_SIZE_SCALE", src)
        self.assertIn("elite=dict(elite)", src)
        # before the rounding and the final judgement
        self.assertLess(src.index("qty *= ELITE_SIZE_SCALE"),
                        src.index("self._judge_final_size("))

    def test_execute_counts_the_allowance_again_and_stamps_the_row(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        self.assertIn("_used >= ELITE_MAX_PER_WINDOW", src)
        self.assertIn("entry_meta[ELITE_META_KEY] = True", src)
        self.assertLess(src.index("_used >= ELITE_MAX_PER_WINDOW"),
                        src.index("client = client_for_symbol("))
