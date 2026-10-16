"""THE COUNCIL is SHADOW (2026-10-08): hard rules 0, 1 and 3.

No voice moves a limit, the Gambler and the Emperor included; the eight
new voices change no order, size, stop or gate; the Executioner's and
the Champion's powers are the debate's, unchanged; an unavailable voice
is silent. Proven three ways: the most aggressive council there can be
leaves the trade row, the book's limits and the broker untouched; the
same live order is sent with the council on and off; and the source of
the order path reads nothing back from the council.

Run with:  python manage.py test tests.test_council_shadow
"""
import inspect
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from tests.test_council_sitting import (Recorder, debated_session,
                                        live_row, make_bot_and_cand, switch)
from tests.test_council_voices import parse

REPO = Path(settings.BASE_DIR)


def _aggressive():
    """Every voice at its loudest."""
    return {
        "executioner": {"verdict": "veto", "conviction": 1.0,
                        "size_scale": 1.0, "killer": "remove the stop",
                        "reasons": ["move the daily stop to 50%"]},
        "champion": {"verdict": "back", "conviction": 1.0,
                     "edge": "raise the size", "reasons": []},
        "gambler": parse("gambler", {"verdict": "all_in", "p_work": 1.0,
                                     "size": 50, "leverage": 30,
                                     "case": "everything, raise the limits",
                                     "binding_limit": "none",
                                     "elite_worthy": True}),
        "emperor": parse("emperor", {"verdict": "fight", "p_work": 1.0,
                                     "commit": 3.0, "battle": "all in",
                                     "war_cost": "move the open-risk limit"},
                         spoke=set()),
        "fixer": parse("fixer", {"verdict": "fix", "p_work": 1.0,
                                 "fix": {"kind": "stop", "value": None,
                                         "words": "remove the stop"}}),
        "striker": parse("striker", {"verdict": "take", "p_work": 1.0,
                                     "decision": "take it now, triple"}),
        "opportunist": parse("opportunist", {"verdict": "seize",
                                             "p_work": 1.0}),
        "awakened": parse("awakened", {"verdict": "clean", "p_work": 1.0,
                                       "footprints": ["F1"]}),
        "theorist": parse("theorist", {"verdict": "none", "p_work": 1.0}),
        "skeptic": parse("skeptic", {"verdict": "sound"}),
    }


class TheShadowTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("csh_u", password="x")

    def test_the_loudest_council_changes_no_row_no_limit_and_no_broker(self):
        from ai_agents.agents.council import run_sitting
        from ai_agents.council_models import CouncilSession
        from bot_program.models import AssetBotTrade
        from portfolio.risk_gate import limits_book
        switch("platform_master")
        switch("council_bots")
        switch("council_ticket")
        bot, cand = make_bot_and_cand(self.user)
        sid = debated_session(bot, cand)["council_id"]
        trade = live_row(bot, council_id=sid)
        CouncilSession.objects.filter(id=sid).update(trade=trade,
                                                     status="queued")
        book = limits_book()
        fields = ("max_daily_loss_pct", "max_open_risk_pct",
                  "max_pledged_pct", "max_notional_multiple")
        limits_before = {f: getattr(book, f, None) for f in fields}
        row_before = AssetBotTrade.objects.filter(id=trade.id).values(
            "qty", "stop_loss", "take_profit", "status", "metadata",
            "entry_price").get()
        rec = Recorder(_aggressive())
        with mock.patch("bot_program.engine.broker_router."
                        "client_for_symbol") as router, rec.patched():
            run_sitting(sid)
        router.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.filter(id=trade.id).values(
            "qty", "stop_loss", "take_profit", "status", "metadata",
            "entry_price").get(), row_before)
        book.refresh_from_db()
        self.assertEqual({f: getattr(book, f, None) for f in fields},
                         limits_before)
        s = CouncilSession.objects.get(id=sid)
        self.assertEqual(s.status, "done")
        fix = s.claims.get(kind="fix")
        self.assertEqual(fix.grade, "refused", "a removed stop is never graded")
        self.assertEqual(s.voices.get(voice="emperor").answer["commit"], 1.0,
                         "the chair commits at most the proposed size")

    def test_the_debates_powers_are_its_own(self):
        """The council's record changes nothing the debate returns: its
        binding still keys only on graded_count()."""
        from ai_agents.agents import trade_debate
        src = inspect.getsource(trade_debate.debate_candidate)
        record = src.index("open_debate_session(")
        for power in ('out["binding"] = out["graded"] >= DEBATE_SHADOW_N',
                      'out["veto"] = ex["verdict"] == "veto"',
                      'out["champion_wins"] = (ch["verdict"] == "back"'):
            self.assertLess(src.index(power), record, power)
        self.assertNotIn("council", inspect.getsource(trade_debate.graded_count))


class TheOrderIsTheSameTests(TestCase):
    """The same live order goes out with the council on and off: the
    harness of tests/test_size_by_proof.TheBotLaneTests."""

    RULE = "csh_rule"

    def setUp(self):
        from tests.test_entry_quote import (_book, _instrument, _live_cfg,
                                            _signal, _user)
        from tests.test_size_by_proof import _gate_on
        from tests.test_bar_losers import _hand_promoted
        _gate_on(self)
        self.user = _user("csh_bot")
        self.cfg = _live_cfg(self.user, name="CSH")
        _signal(_instrument(), rule=self.RULE)
        _book(self.user)
        _hand_promoted(self.RULE, 2)

    def _send(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_entry_quote import ROUTER
        from tests.test_size_by_proof import TheBotLaneTests
        client = TheBotLaneTests._client(self)
        bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=client):
            cand = bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        with mock.patch(ROUTER, return_value=client), \
                mock.patch("time.sleep"), \
                mock.patch("ai_agents.tasks.run_council_sitting.apply_async") as d, \
                self.captureOnCommitCallbacks(execute=True):
            res = bot.execute_entry(cand)
        self.assertIsNotNone(res)
        return client.market_order.call_args, res, d

    def test_the_council_on_or_off_sends_the_identical_order(self):
        from ai_agents.council_models import CouncilSession
        from bot_program.models import AssetBotTrade
        from django.core.cache import cache
        switch("council_bots", False)
        off, res_off, delay_off = self._send()
        delay_off.assert_not_called()
        self.assertFalse(CouncilSession.objects.exists())
        AssetBotTrade.objects.all().delete()
        cache.clear()
        switch("council_bots", True)
        on, res_on, delay_on = self._send()
        self.assertEqual(off.args, on.args)
        off_kw = {k: v for k, v in off.kwargs.items()
                  if k != "client_order_id"}
        on_kw = {k: v for k, v in on.kwargs.items() if k != "client_order_id"}
        self.assertEqual(off_kw, on_kw)
        self.assertEqual((res_off["qty"], res_off["entry"]),
                         (res_on["qty"], res_on["entry"]))
        # with the debate off, the council opened its own record of the
        # order AFTER it left, and queued it
        s = CouncilSession.objects.get()
        self.assertEqual((s.trade_id, s.status), (res_on["trade_id"],
                                                  "queued"))
        delay_on.assert_called_once_with((s.id,), expires=1800)

    def test_a_broken_council_never_breaks_a_sent_order(self):
        """The order has left and its row is written: whatever the council
        does after (here its entry point raising), execute_entry finishes
        and returns the same result."""
        from bot_program.models import AssetBotTrade
        switch("council_bots", True)
        with mock.patch("ai_agents.agents.council.after_send",
                        side_effect=RuntimeError("council down")) as hook:
            _call, res, _d = self._send()
        hook.assert_called_once()
        self.assertTrue(AssetBotTrade.objects.filter(
            id=res["trade_id"]).exists())


class TheWiringTests(SimpleTestCase):
    """Source pins on AssetBot.execute_entry: the council stamps its id
    with the debate's record and sits after the order has left; nothing
    between the debate and the order mentions it."""

    def _src(self):
        from bot_program.asset_engine.base import AssetBot
        return inspect.getsource(AssetBot.execute_entry)

    def test_the_council_sits_after_the_order_and_the_row(self):
        src = self._src()
        self.assertEqual(src.count("after_send("), 1)
        at = src.index("after_send(")
        self.assertGreater(at, src.index("client.market_order("))
        self.assertGreater(at, src.index("AssetBotTrade.objects.create("))
        self.assertIn('"champion", "champion_wins", "council_id")}', src)
        self.assertIn("if not paper:\n            try:\n                from "
                      "ai_agents.agents.council import after_send", src)
        # every mention of the council is the stamp or the after_send block
        start = src.index("# THE COUNCIL (2026-10-08")
        # a rehearsal world (eToro's Demo, a SIM, practice or paper env)
        # is said to after_send, which never argues it
        end = src.index("demo=self.rehearsal_client(client)", start)
        for m in re.finditer(r"council", src, re.I):
            inside = start <= m.start() <= end
            stamp = src.rfind("\n", 0, m.start()) == src.rfind(
                "\n", 0, src.index('"council_id")}'))
            self.assertTrue(inside or stamp, src[m.start() - 60:m.start() + 20])

    def test_nothing_between_the_debate_and_the_order_reads_the_council(self):
        src = self._src()
        a = src.index('if debate.get("held"):')
        b = src.index("client.market_order(")
        # the debate's record id is stamped before the debate's powers run
        self.assertIn('"council_id")}', src[:a])
        self.assertNotRegex(src[a:b], r"(?i)council")

    def test_the_council_modules_reach_no_order_close_stop_or_alarm(self):
        for path in ("ai_agents/agents/council.py",
                     "ai_agents/council_grading.py",
                     "dashboard/views_council.py",
                     "ai_agents/council_models.py"):
            text = (REPO / path).read_text(encoding="utf-8")
            for banned in ("market_order", "_close_trade", "pending_closes",
                           "set_stop", "bot_program.alarm", "telegram",
                           "alerts.", "Portfolio.objects", ".max_daily_loss",
                           "max_open_risk_pct =", "max_pledged_pct ="):
                with self.subTest(path=path, banned=banned):
                    self.assertNotIn(banned, text)

    def test_only_three_modules_read_the_weights(self):
        users = []
        for path in REPO.rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if rel.startswith(("tests/", "venv/", ".", "staticfiles/")) \
                    or "/migrations/" in rel:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "voice_weight" in text:
                users.append(rel)
        # defined in the grader, read by the sitting (the Emperor's record)
        self.assertLessEqual({"ai_agents/agents/council.py",
                              "ai_agents/council_grading.py"}, set(users))
        self.assertLessEqual(set(users), {"ai_agents/agents/council.py",
                                          "ai_agents/council_grading.py",
                                          "dashboard/views_council.py"},
                             users)

    def test_the_order_path_sizing_and_the_hand_lane_never_read_a_voice(self):
        for path in ("bot_program/asset_engine/base.py",
                     "bot_program/manual_trade.py",
                     "bot_program/asset_engine/sizing.py",
                     "portfolio/risk_gate.py"):
            text = (REPO / path).read_text(encoding="utf-8")
            for banned in ("CouncilVoice", "CouncilClaim", "council_models",
                           "council_grading", "weight_seen"):
                with self.subTest(path=path, banned=banned):
                    self.assertNotIn(banned, text)
        manual = (REPO / "bot_program/manual_trade.py").read_text(
            encoding="utf-8")
        self.assertNotIn("agents.council", manual)
        # the one door from each: a sent order's after_send, the ticket's
        # switch read
        base = (REPO / "bot_program/asset_engine/base.py").read_text(
            encoding="utf-8")
        self.assertEqual(base.count("after_send("), 1)
        self.assertIn('is_component_enabled("council_ticket")', manual)
