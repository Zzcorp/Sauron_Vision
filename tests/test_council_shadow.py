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
import contextlib
import inspect
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
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

    def test_the_stamp_is_the_only_new_word_on_the_order_path(self):
        """2026-10-16: the debate on a SIM, practice or paper client is
        stamped a rehearsal on its record, and nothing else changes: the
        stamp is one keyword of the debate call, read before it, and the
        method mentions the council exactly as often as before."""
        from unittest.mock import patch as _patch

        from bot_program.asset_engine.base import AssetBot
        src = self._src()
        self.assertEqual(src.count("rehearsal=_rehearsal"), 1)
        call = src.index("debate_candidate(self, cand, qty,")
        stamp = src.index("rehearsal=_rehearsal")
        self.assertLess(call, stamp)
        self.assertNotIn(")", src[call + len("debate_candidate("):stamp])
        self.assertLess(src.index("_rehearsal = self.rehearsal_or_unsure("
                                  "client)"), call)
        # the eToro demo world is still never argued, on the same test
        self.assertIn('if getattr(client, "demo", False) is True', src)
        self.assertEqual(len(re.findall(r"council", src, re.I)), 5)
        # unsure is not real money
        with _patch.object(AssetBot, "rehearsal_client",
                           side_effect=RuntimeError("venue unread")):
            self.assertTrue(AssetBot.rehearsal_or_unsure(object()))
        self.assertFalse(AssetBot.rehearsal_or_unsure(SimpleNamespace(
            env="live")))
        self.assertTrue(AssetBot.rehearsal_or_unsure(SimpleNamespace(
            env="sim")))

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
                     "ai_agents/council_models.py",
                     "ai_agents/council_mood.py"):
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


class TheRehearsalStampTests(TestCase):
    """THE GAP the council's first version left open (2026-10-16): main's
    debate checks only eToro's .demo before arguing, so a Saxo SIM, OANDA
    practice or Alpaca paper candidate argued and then NOT sent had its
    record replayed as "not sent" into the live weights. Fixed without
    changing any order behaviour: the debate runs exactly as before on
    every client; only its record is stamped a rehearsal
    (AssetBot.rehearsal_or_unsure), and the grader closes such a record
    ungraded. Each client is sent twice: A, the real code; B, the stamp
    forced off. Everything the order path does must be byte-identical."""

    RULE = "csh_reh"
    CLIENTS = ("live", "etoro_demo", "sim", "practice", "paper")

    def setUp(self):
        TheOrderIsTheSameTests.setUp(self)
        switch("trade_debate")

    def _client(self, kind):
        from tests.test_size_by_proof import TheBotLaneTests
        client = TheBotLaneTests._client(self)
        if kind == "etoro_demo":
            client.demo = True
        elif kind in ("sim", "practice", "paper"):
            client.env = kind
        return client

    def _send(self, kind, *, stamp=True, binding=False):
        from ai_agents.agents import trade_debate
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        from django.core.cache import cache
        from tests.test_council_sitting import CH_RUN, EX_RUN, SPEND
        from tests.test_entry_quote import ROUTER
        AssetBotTrade.objects.all().delete()
        cache.clear()
        self.cfg.refresh_from_db()
        self.cfg.extras = {k: v for k, v in (self.cfg.extras or {}).items()
                           if k not in ("skips", "skip_counts")}
        self.cfg.save(update_fields=["extras"])
        client = self._client(kind)
        bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=client):
            cand = bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        ex = ({"verdict": "veto", "conviction": 0.9, "size_scale": 1.0,
               "killer": "fights the trend", "reasons": []} if binding else
              {"verdict": "pass", "conviction": 0.3, "size_scale": 1.0,
               "killer": "k", "reasons": []})
        real = trade_debate.debate_candidate
        with mock.patch(ROUTER, return_value=client), \
                mock.patch("time.sleep"), \
                mock.patch("ai_agents.tasks.run_council_sitting.apply_async"), \
                mock.patch(SPEND, return_value=(True, "")), \
                mock.patch(EX_RUN, return_value=ex), \
                mock.patch(CH_RUN, return_value={
                    "verdict": "back", "conviction": 0.6, "edge": "e",
                    "reasons": []}), \
                mock.patch("ai_agents.agents.trade_debate.graded_count",
                           return_value=30 if binding else 0), \
                mock.patch("ai_agents.agents.trade_debate.debate_candidate",
                           side_effect=real) as spy, \
                (mock.patch.object(AssetBot, "rehearsal_or_unsure",
                                   return_value=False) if not stamp
                 else contextlib.nullcontext()), \
                self.captureOnCommitCallbacks(execute=True):
            res = bot.execute_entry(cand)
        row = (AssetBotTrade.objects.filter(id=res["trade_id"]).first()
               if res else None)
        debate = dict((row.metadata or {}).get("debate") or {}) if row else None
        council_id = (debate or {}).pop("council_id", None)
        self.cfg.refresh_from_db()
        skipped = {sym: (d["code"], d["detail"])
                   for sym, d in skips.last_by_symbol(self.cfg).items()}
        sent = client.market_order.call_args
        return {"args": sent.args if sent else None,
                "kwargs": ({k: v for k, v in sent.kwargs.items()
                            if k != "client_order_id"} if sent else None),
                "res": (res["qty"], res["entry"]) if res else None,
                "debate": debate, "skips": skipped, "spy": spy,
                "council_id": council_id}

    def _venues(self):
        from ai_agents.council_models import CouncilSession
        return list(CouncilSession.objects.order_by("id").values_list(
            "venue", flat=True))

    def test_every_client_sends_the_same_order_and_only_the_stamp_differs(self):
        from ai_agents.council_models import CouncilClaim, CouncilSession
        for kind in self.CLIENTS:
            with self.subTest(client=kind):
                CouncilSession.objects.all().delete()
                a = self._send(kind)
                venues_a = self._venues()
                CouncilSession.objects.all().delete()
                b = self._send(kind, stamp=False)
                venues_b = self._venues()
                for key in ("args", "kwargs", "res", "debate", "skips"):
                    self.assertEqual(a[key], b[key], key)
                self.assertIsNotNone(a["args"], "the order was sent")
                if kind == "etoro_demo":
                    # never argued, as before: no debate, no record
                    a["spy"].assert_not_called()
                    b["spy"].assert_not_called()
                    self.assertEqual((venues_a, venues_b), ([], []))
                    self.assertEqual(a["debate"], {}, "nothing stamped")
                    continue
                self.assertEqual(a["spy"].call_count, 1)
                self.assertEqual(a["spy"].call_args.kwargs,
                                 {"rehearsal": kind != "live"})
                self.assertEqual(b["spy"].call_args.kwargs,
                                 {"rehearsal": False})
                self.assertTrue(a["debate"]["ran"])
                self.assertEqual(venues_a,
                                 ["live" if kind == "live" else "demo"])
                self.assertEqual(venues_b, ["live"])
        # a rehearsal's claims carry its venue: none is a live weight claim
        CouncilSession.objects.all().delete()
        self._send("sim")
        s = CouncilSession.objects.get()
        self.assertEqual(set(s.claims.values_list("venue", flat=True)),
                         {"demo"})
        self.assertFalse(CouncilClaim.objects.filter(venue="live").exists())

    def test_a_vetoed_sim_candidate_is_never_replayed_into_the_live_weights(self):
        from ai_agents.council_grading import (REHEARSAL_ARGUED_NOTES,
                                               grade_session)
        from ai_agents.council_models import CouncilSession
        from bot_program.asset_engine import skips
        from tests.test_council_grading import _bars
        a = self._send("sim", binding=True)
        b = self._send("sim", stamp=False, binding=True)
        self.assertIsNone(a["args"], "the veto sent nothing")
        for key in ("args", "kwargs", "res", "skips"):
            self.assertEqual(a[key], b[key], key)
        self.assertEqual(a["skips"]["AAPL"][0], skips.GATE_BLOCKED)
        self.assertIn("the Executioner vetoed it", a["skips"]["AAPL"][1])
        first, second = CouncilSession.objects.order_by("id")
        self.assertEqual((first.venue, second.venue), ("demo", "live"))
        self.assertEqual((first.trade_id, second.trade_id), (None, None))
        # 48h later, the trade it would have been was stopped
        for s in (first, second):
            CouncilSession.objects.filter(id=s.id).update(
                created_at=s.created_at - timedelta(hours=48),
                horizon_hours=24.0)
        first.refresh_from_db()
        _bars(first.created_at,
              [(first.entry * 1.001, first.stop * 0.999, first.stop)],
              symbol="AAPL")
        now = first.created_at + timedelta(hours=48)
        grade_session(CouncilSession.objects.get(id=first.id), now)
        grade_session(CouncilSession.objects.get(id=second.id), now)
        first.refresh_from_db()
        second.refresh_from_db()
        # A: closed, never replayed, nothing graded
        self.assertEqual(first.grade_notes, REHEARSAL_ARGUED_NOTES)
        self.assertEqual((first.truth, first.truth_r, first.replay_r),
                         ("", None, None))
        self.assertEqual(set(first.claims.values_list("grade", flat=True)),
                         {"ungraded"})
        # B, the gap: the same record stamped live is replayed "not sent"
        # into the live weights (not a repeat of the rehearsal before it)
        self.assertEqual((second.truth, second.grade_notes),
                         ("replay", "replayed: not sent"))
        self.assertTrue(second.claims.filter(y__isnull=False).exists())

    def test_the_debate_returns_the_same_whatever_the_stamp(self):
        from ai_agents.agents.trade_debate import debate_candidate
        from ai_agents.council_models import CouncilSession
        from tests.test_council_sitting import (CH_RUN, EX_RUN, SPEND,
                                                make_bot_and_cand)
        user = get_user_model().objects.create_user("csh_st", password="x")
        bot, cand = make_bot_and_cand(user)
        outs = {}
        for rehearsal in (True, False):
            with mock.patch(SPEND, return_value=(True, "")), \
                    mock.patch(EX_RUN, return_value={
                        "verdict": "cut", "conviction": 0.7,
                        "size_scale": 0.5, "killer": "k", "reasons": []}), \
                    mock.patch(CH_RUN, return_value={
                        "verdict": "back", "conviction": 0.6, "edge": "e",
                        "reasons": []}):
                outs[rehearsal] = debate_candidate(bot, cand, 0.01,
                                                   rehearsal=rehearsal)
        ids = {k: v.pop("council_id") for k, v in outs.items()}
        self.assertEqual(outs[True], outs[False])
        for rehearsal, venue in ((True, "demo"), (False, "live")):
            s = CouncilSession.objects.get(id=ids[rehearsal])
            self.assertEqual(s.venue, venue)
            self.assertEqual(set(s.claims.values_list("venue", flat=True)),
                             {venue})
