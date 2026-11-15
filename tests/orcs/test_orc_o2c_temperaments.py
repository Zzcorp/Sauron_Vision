"""O2c's TEMPERAMENTS, DRAWN JUST AFTER THE BIRTH BEHIND `orcs_temperaments`,
OFF (the O2 spec C.3-C.6 and N2 for `orcs_temperaments`; §1.3.6
"Temperaments" and "Every new switch"; §1.3.5 P25; §0 N1.2, N1 test item h,
N7, N8.3; §4 Q0, Q1, Q14; 2026-11-15).

- the lanes: every lane constant of bot_program/orcs/temperament.py appears
  word for word (whitespace folded) in its prompt in ai_agents/agents/
  council.py or trade_debate.py; this test imports ai_agents, the package
  never does; nothing reads a council weight
- the draw: 14 newborns on one seat with the switch ON draw 2 of each
  temperament (the six and the control), and the tie rule reproduces from
  the root trade id
- fixed for life: OFF then ON again does not redraw, and a second
  draw_quietly writes nothing
- OFF: no draw, no entry, temperament '', PS9's dash, and the next wake's
  request byte-identical
- ON: the draw's entry, and PS9's lanes in the next request (one request
  recorded); the draw itself sends no request (the pair)
- the draw is registered on the birth's commit (captureOnCommitCallbacks),
  takes the Orc's row lock only, within the entry path's lock budget; on
  PostgreSQL only, a thread holding the trade row's lock does not block it,
  and one holding the Orc's leaves the Orc undrawn within the budget;
  birth._create's pinned hash (FROZEN_SOURCES) is unchanged
- PS with PS9 at its cap and PS11's dash fits PS_TAIL_RESERVE, which does
  not move
- OrcTemperamentGrade per key with vs_control_mean, never pooled across
  venue or bar source, over grades with n_llm > 0 only, none for an Orc
  with no temperament; the grade's tag only with a temperament; with no
  graded Orc holding one, grade_closed writes nothing and its result gains
  no key
- N2: OFF in a fresh database; in BULK_ENABLE_EXEMPT and ORC_MIND_SWITCHES,
  never in LIVE_MONEY_SWITCHES; ON refused with no PIN, a wrong PIN and from
  the shell; ON with the PIN; OFF with none; its description under 300
- the words: the Orc page's temperament line, only with a temperament; the
  RUNBOOK's section

Run with:  python manage.py test tests.orcs.test_orc_o2c_temperaments
(PostgreSQL: DB_ENGINE=postgresql and the DB_* variables of a scratch
cluster, for the lock proof.)
"""
import ast
import inspect
import json
import random
import threading
import time
from collections import Counter
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tests.orcs import test_orc_o2a_shadow_pins as t1
from tests.orcs.helpers import (_config, _on, _paper_cap, _row, _switch,
                                _user, born)
from tests.orcs.helpers_o2 import (KB10_QTY, MindTestCase,
                                   MindTransactionTestCase, fake_answer)
from tests.orcs.test_orc_o2a_call import NOW, MindFixture, answer
from tests.orcs.test_orc_o2b_routed import TEST_PIN, WRONG_PIN, _row_of

BASE = Path(settings.BASE_DIR)
RUNBOOK = BASE / "deploy" / "RUNBOOK.md"
KEY = "orcs_temperaments"
NAME = "Orc Temperaments (in shadow)"
DESCRIPTION = ("Off (default). On: each newborn Orc draws a temperament (one "
               "council voice's lane, or a control with none), fixed for "
               "life. A model reading the Orc's wakes sees it in PS9 as a "
               "view; grades are kept by temperament, in shadow. It sends no "
               "order. Turning it on takes the PIN.")
#: The table, in its order: the six lead voices, then the control.
NAMES = ("striker", "fixer", "skeptic", "awakened", "executioner",
         "champion", "control")
#: birth._create's hash, as O2a left it (N1 test item h): the draw is not in
#: it.
CREATE_SHA = "201d02f6758d08a6d004029a39098585899db0c30806fbd295952f3321d691f8"
PS9_NONE = "— (no temperament drawn)"
PS9_CONTROL = "— (control: no lead voice)"
PS11_NONE = "— (no Captain seated yet)"
T0 = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)
PG = connection.vendor == "postgresql"
NOT_PG = "the lock proof needs PostgreSQL's row locks (SQLite has none)"
HOLD_S = 10.0
UNDER_S = 1.0


def _fold(text) -> str:
    return " ".join(str(text or "").split())


def _entries(orc, **filters):
    from bot_program.orcs.models import OrcJournal
    return list(OrcJournal.objects.filter(orc=orc, **filters)
                .order_by("at", "id"))


def _ps_of(req) -> dict:
    """The PS block a recorded request carries, its body read back."""
    [text] = [t for t in req.texts() if t.startswith("[PS Orc #")]
    return json.loads(text.split("\n", 1)[1])


# ── the lanes ────────────────────────────────────────────────────────────

class TheLanesTests(MindTestCase):

    def test_every_lane_is_its_prompts_own_words(self):
        """C.3: the lane texts are COPIED; this test, outside the package,
        imports the prompts and pins each copy to its words (the four
        council voices' "Your lane is ..." sentences, the debate's two
        "Your only job is ...": those prompts carry no lane sentence)."""
        from ai_agents.agents import council, trade_debate

        from bot_program.orcs import temperament

        def debate(cls):
            return cls.get_system_prompt(object.__new__(cls))
        prompts = {
            "striker": council.StrikerAgent.PROMPT,
            "fixer": council.FixerAgent.PROMPT,
            "skeptic": council.SkepticAgent.PROMPT,
            "awakened": council.AwakenedAgent.PROMPT,
            "executioner": debate(trade_debate.ExecutionerAgent),
            "champion": debate(trade_debate.ChampionAgent)}
        self.assertEqual(set(temperament.LANES), set(prompts))
        for voice, prompt in prompts.items():
            lane = temperament.LANES[voice]
            with self.subTest(voice):
                self.assertIn(_fold(lane), _fold(prompt))
                head = ("Your only job is" if voice in ("executioner",
                                                        "champion")
                        else "Your lane")
                self.assertTrue(lane.startswith(head), lane)
                self.assertTrue(lane.endswith("."), lane)
                # a whole sentence of the prompt: it starts one
                at = _fold(prompt).index(_fold(lane))
                self.assertIn(_fold(prompt)[max(0, at - 2):at], (". ", ""))
        self.assertEqual({v for v in prompts if v in council.COUNCIL_VOICES},
                         {"striker", "fixer", "skeptic", "awakened"})
        self.assertLessEqual(set(prompts), set(council.ALL_VOICES))
        # the voices' names, copied the same way ("the Striker")
        self.assertEqual(set(temperament.VOICE_NAMES), set(prompts))
        for voice, name in temperament.VOICE_NAMES.items():
            self.assertEqual("T" + name[1:], council.VOICE_NAMES[voice])

    def test_the_table_t1(self):
        from bot_program.orcs import temperament
        from bot_program.orcs.models import Orc, OrcTemperamentGrade
        self.assertEqual(temperament.VERSION, "t1")
        self.assertEqual(temperament.NAMES, NAMES)
        self.assertEqual(temperament.CONTROL, "control")
        for name in NAMES:
            with self.subTest(name):
                leads = temperament.LEADS[name]
                self.assertEqual(leads, () if name == "control" else (name,))
                self.assertLessEqual(len(name), Orc._meta.get_field(
                    "temperament").max_length)
                self.assertLessEqual(len(name), OrcTemperamentGrade._meta
                                     .get_field("temperament").max_length)

    def test_the_package_never_names_the_provider_nor_reads_a_weight(self):
        """The package imports nothing of ai_agents (only the gateway
        names it, N1.4); nothing reads voice_weight (C.3, so
        tests/test_council_shadow.py stays as it is)."""
        from bot_program.orcs import temperament
        path = t1.PKG / "temperament.py"
        self.assertEqual(t1.model_reach(t1.tree_of(path), "temperament"), [])
        for _mod, p in t1.package_files():
            with self.subTest(p.name):
                self.assertNotIn("voice_weight", p.read_text("utf-8"))
        self.assertIn("ai_agents/agents/council.py", temperament.__doc__)


# ── the draw ─────────────────────────────────────────────────────────────

class _Births(MindTestCase):

    def setUp(self):
        _on()
        _switch("aragorn")
        _paper_cap(200)
        cache.clear()
        self.user = _user(f"o2c_t_{type(self).__name__.lower()[:18]}")
        self.cfg = _config(self.user)

    def newborn(self, **kw):
        orc = born(self, _row(self.cfg, **kw))
        orc.refresh_from_db()
        return orc


class TheDrawTests(_Births):

    def test_fourteen_newborns_draw_two_of_each_and_the_ties_reproduce(self):
        from bot_program.orcs import temperament
        _switch(KEY, True)
        orcs = [self.newborn() for _ in range(14)]
        self.assertEqual(len({o.seat_id for o in orcs}), 1, "one seat")
        self.assertEqual(Counter(o.temperament for o in orcs),
                         {n: 2 for n in NAMES})
        counts = {}
        for orc in orcs:
            low = min(counts.get(n, 0) for n in NAMES)
            tied = [n for n in NAMES if counts.get(n, 0) == low]
            want = random.Random(orc.root_trade_id).choice(tied)
            with self.subTest(orc=orc.root_trade_id):
                self.assertEqual(orc.temperament, want)
                self.assertEqual(temperament.draw(dict(counts),
                                                  orc.root_trade_id), want)
                [e] = _entries(orc, kind="temperament")
                self.assertEqual(e.author, "code")
                self.assertEqual(e.body, {"temperament": want,
                                          "version": "t1",
                                          "lead": list(temperament.LEADS[
                                              want]),
                                          "counts": {n: counts.get(n, 0)
                                                     for n in NAMES}})
                self.assertEqual(e.headline, temperament.entry_line(want))
            counts[want] = counts.get(want, 0) + 1

    def test_the_draw_takes_the_fewest_and_is_seeded(self):
        from bot_program.orcs import temperament
        full = {n: 1 for n in NAMES}
        for name in NAMES:
            counts = {**full, name: 0}
            for seed in (1, 7, 123456789):
                self.assertEqual(temperament.draw(counts, seed), name)
        self.assertEqual(temperament.draw({}, 42), temperament.draw({}, 42))
        self.assertEqual(temperament.draw({}, 42),
                         random.Random(42).choice(list(NAMES)))
        # a name of no table counts for nothing
        self.assertEqual(temperament.draw({"gambler": 0, **full,
                                           "fixer": 0}, 9), "fixer")

    def test_the_entrys_words(self):
        from bot_program.orcs import temperament
        self.assertEqual(temperament.entry_line("striker"),
                         "Temperament: Striker (lead voices: the Striker).")
        self.assertEqual(temperament.entry_line("control"),
                         "Temperament: control (lead voices: none).")


class TheFixedForLifeTests(_Births):

    def test_off_then_on_again_does_not_redraw(self):
        from bot_program.orcs import temperament
        from bot_program.orcs.models import Orc
        _switch(KEY, True)
        orc = self.newborn()
        name = orc.temperament
        self.assertIn(name, NAMES)
        _switch(KEY, False)
        _switch(KEY, True)
        before = len(_entries(orc))
        with CaptureQueriesContext(connection) as q:
            temperament.draw_quietly(orc.pk)
        writes = [x["sql"] for x in q.captured_queries
                  if x["sql"].lstrip().upper().startswith(("INSERT",
                                                          "UPDATE"))]
        self.assertEqual(writes, [], "a second draw writes nothing")
        self.assertEqual(Orc.objects.get(pk=orc.pk).temperament, name)
        self.assertEqual(len(_entries(orc)), before)
        self.assertEqual(len(_entries(orc, kind="temperament")), 1)

    def test_the_draw_is_called_from_the_birth_alone(self):
        """The switch governs new draws only: the one caller of
        draw_quietly is birth.ensure's commit."""
        calls = []
        for mod, path in t1.package_files():
            for node, scope in t1.scoped(t1.tree_of(path)):
                if isinstance(node, (ast.Name, ast.Attribute)) and (
                        getattr(node, "id", None) == "draw_quietly"
                        or getattr(node, "attr", None) == "draw_quietly"):
                    calls.append((mod, scope))
        self.assertEqual(calls, [("birth", "ensure")])


# ── OFF and ON ───────────────────────────────────────────────────────────

class TheSwitchOffTests(MindFixture):

    def test_off_no_draw_no_entry_the_dash_and_the_same_request(self):
        from bot_program.orcs import mind, temperament
        _switch(KEY, False)
        other = born(self, _row(self.cfg, qty=str(KB10_QTY),
                                symbol=self.symbol),
                     at=NOW - timedelta(hours=1))
        other.refresh_from_db()
        self.assertEqual(other.temperament, "")
        self.assertEqual(_entries(other, kind="temperament"), [])
        first = mind.build_request(self.rendered(orc=other), "r0")
        temperament.draw_quietly(other.pk)
        other.refresh_from_db()
        self.assertEqual(other.temperament, "")
        self.assertEqual(_entries(other, kind="temperament"), [])
        again = mind.build_request(self.rendered(orc=other), "r0")
        for part in ("system_blocks", "shared_user_blocks",
                     "private_user_blocks"):
            self.assertEqual(again[part], first[part], part)
        [ps] = [b["text"] for b in first["private_user_blocks"]
                if b["text"].startswith("[PS Orc #")]
        self.assertIn('"ps9":"— (no temperament drawn)"', ps)


class TheSwitchOnTests(MindFixture):

    def _newborn(self):
        from bot_program.orcs.models import Orc
        # the seat's control is taken, so the newborn leans on a voice
        Orc.objects.filter(pk=self.orc.pk).update(temperament="control")
        _switch(KEY, True)
        other = born(self, _row(self.cfg, qty=str(KB10_QTY),
                                symbol=self.symbol),
                     at=NOW - timedelta(hours=1))
        other.refresh_from_db()
        return other

    def test_on_the_draws_entry_and_ps9s_lanes_in_the_next_request(self):
        from bot_program.orcs import fence, temperament
        from bot_program.orcs.constants import FENCE_CAPS
        other = self._newborn()
        name = other.temperament
        self.assertIn(name, NAMES[:-1])
        [e] = _entries(other, kind="temperament")
        self.assertEqual((e.author, e.fact_id), ("code", ""))
        self.assertEqual(e.headline, temperament.entry_line(name))
        w = self.claim(self.rendered(orc=other))
        self.think(w, fake_answer(answer()))
        self.assert_one_call()
        ps = _ps_of(self.requests[-1])
        view = fence.view("temperament", temperament.lanes_text(name),
                          FENCE_CAPS["temperament"])
        self.assertEqual(ps["ps9"], view)
        self.assertIn(_fold(temperament.LANES[name]), view)
        self.assertIn(temperament.VOICE_NAMES[name], view)
        self.assertNotIn(fence.WITHHELD, view)
        self.assertEqual(ps["ps11"], PS11_NONE)
        self.assert_no_account_figure()

    def test_the_draw_sends_no_request(self):
        """The positive control first (a wake read by the fake model), then
        a draw: no request, whatever it drew."""
        w = self.claim(self.rendered())
        self.think(w, fake_answer(answer()))
        self.assert_one_call()
        other = self._newborn()
        self.assertIn(other.temperament, NAMES)
        self.assert_no_call()


# ── after the commit, the Orc's row only ─────────────────────────────────

class TheDrawOnCommitTests(_Births):

    def test_the_draw_is_registered_on_the_births_commit(self):
        from bot_program.orcs import birth, temperament
        _switch(KEY, True)
        row = _row(self.cfg)
        with self.captureOnCommitCallbacks() as cbs:
            orc = birth.ensure(row)
        draws = [c for c in cbs
                 if getattr(c, "func", None) is temperament.draw_quietly]
        self.assertEqual(len(draws), 1)
        self.assertEqual(draws[0].args, (orc.pk,))
        orc.refresh_from_db()
        self.assertEqual(orc.temperament, "", "nothing before the commit")
        draws[0]()
        orc.refresh_from_db()
        self.assertIn(orc.temperament, NAMES)
        src = inspect.getsource(birth.ensure)
        self.assertIn("transaction.on_commit(partial(temperament."
                      "draw_quietly, orc.pk),", src)
        self.assertLess(src.index("orc = _create("),
                        src.index("draw_quietly"))

    def test_the_draw_locks_the_orc_only_within_the_entry_budget(self):
        """N1.2 and N8.3: one lock budget of ORC_LOCK_MONEY_MS, the Orc's
        row through journal.orc_lock, no trade row named."""
        from bot_program.orcs import temperament
        fn = ast.parse(inspect.getsource(temperament.draw_quietly)).body[0]
        withs = [ast.unparse(i.context_expr) for sub in ast.walk(fn)
                 if isinstance(sub, ast.With) for i in sub.items]
        self.assertIn("journal.lock_budget(ORC_LOCK_MONEY_MS)", withs)
        names = {n for n, _s in t1.identifiers(fn)}
        self.assertIn("orc_lock", names)
        tree = t1.tree_of(t1.PKG / "temperament.py")
        spelled = {n for n, _s in t1.identifiers(tree)}
        self.assertFalse(spelled & {"AssetBotTrade", "root_trade",
                                    "select_for_update"}, spelled)

    def test_create_keeps_its_pinned_hash(self):
        self.assertEqual(t1.FROZEN_SOURCES[("birth", "_create")], CREATE_SHA)
        self.assertEqual(t1.source_hash("birth", "_create"), CREATE_SHA)
        from bot_program.orcs import birth
        self.assertNotIn("temperament", inspect.getsource(birth._create))


class _RowHolder:
    """Thread A: the trade row's lock, as the order path takes it, held
    until released (HOLD_S at most)."""

    def __init__(self, row_pk, *, orc_pk=None):
        self.row_pk, self.orc_pk = row_pk, orc_pk
        self.ready, self.release = threading.Event(), threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from django.db import connection as conn

        from bot_program.models import AssetBotTrade
        from bot_program.orcs import journal
        try:
            with transaction.atomic():
                if self.orc_pk is not None:
                    journal.orc_lock(self.orc_pk)
                else:
                    AssetBotTrade.objects.select_for_update().get(
                        pk=self.row_pk)
                self.ready.set()
                self.release.wait(HOLD_S)
        except Exception as e:  # noqa: BLE001 — told to the test thread
            self.error = e
            self.ready.set()
        finally:
            conn.close()

    def __enter__(self):
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            raise RuntimeError(f"thread A never held the lock: {self.error}")
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.thread.join(HOLD_S + 5)
        return False


@skipUnless(PG, NOT_PG)
class TheDrawNeverWaitsForTheTradeRowTests(MindTransactionTestCase):

    def setUp(self):
        _on()
        _switch("aragorn")
        self.user = _user("o2c_t_pg")
        self.cfg = _config(self.user)
        self.row = _row(self.cfg)
        from bot_program.orcs.birth import ensure
        self.orc = ensure(self.row)
        self.assertIsNotNone(self.orc)
        self.assertEqual(self.orc.temperament, "", "born with the switch "
                                                    "off")
        _switch(KEY, True)

    def test_a_held_trade_row_does_not_block_the_draw(self):
        from bot_program.orcs import temperament
        from bot_program.orcs.models import Orc
        with _RowHolder(self.row.pk):
            t0 = time.monotonic()
            temperament.draw_quietly(self.orc.pk)
            took = time.monotonic() - t0
        self.assertLess(took, UNDER_S)
        self.assertIn(Orc.objects.get(pk=self.orc.pk).temperament, NAMES)

    def test_a_held_orc_row_leaves_it_undrawn_within_the_budget(self):
        from bot_program.orcs import temperament
        from bot_program.orcs.models import Orc
        with _RowHolder(self.row.pk, orc_pk=self.orc.pk):
            t0 = time.monotonic()
            temperament.draw_quietly(self.orc.pk)
            took = time.monotonic() - t0
        self.assertLess(took, UNDER_S, "the entry path's budget, 200 ms")
        self.assertEqual(Orc.objects.get(pk=self.orc.pk).temperament, "")
        self.assertEqual(_entries(self.orc, kind="temperament"), [])


# ── PS9 ──────────────────────────────────────────────────────────────────

class ThePS9Tests(MindFixture):

    def _ps(self, name):
        from bot_program.orcs import dossier_position
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(temperament=name)
        self.orc.refresh_from_db()
        return dossier_position.ps(self.orc, self.row, {"now": NOW})

    def test_ps9_none_a_voice_and_the_control(self):
        from bot_program.orcs import fence, temperament
        from bot_program.orcs.constants import FENCE_CAPS
        self.assertEqual(self._ps("")["ps9"], PS9_NONE)
        self.assertEqual(self._ps("control")["ps9"], PS9_CONTROL)
        for name in NAMES[:-1]:
            with self.subTest(name):
                ps9 = self._ps(name)["ps9"]
                self.assertEqual(ps9, fence.view(
                    "temperament", temperament.lanes_text(name),
                    FENCE_CAPS["temperament"]))
                self.assertTrue(ps9.startswith(
                    '<view source="temperament" note="may be wrong; facts '
                    'win">'))
                self.assertIn(temperament.VOICE_NAMES[name], ps9)
                self.assertIn(_fold(temperament.LANES[name]), ps9)
                self.assertNotIn(fence.WITHHELD, ps9)
                self.assertLess(len(temperament.lanes_text(name)),
                                FENCE_CAPS["temperament"])
        self.assertEqual(self._ps("striker")["ps11"], PS11_NONE)

    def test_ps_with_ps9_at_its_cap_fits_the_reserve(self):
        from bot_program.orcs import dossier, fence, temperament
        from bot_program.orcs.constants import FENCE_CAPS
        from bot_program.orcs.dossier_instrument import (PS_TAIL_RESERVE,
                                                         tape_rows)
        from bot_program.orcs.models import Orc, OrcDossierBlock
        self.assertEqual(PS_TAIL_RESERVE, 6600, "the reserve does not move")
        cap = FENCE_CAPS["temperament"]
        Orc.objects.filter(pk=self.orc.pk).update(temperament="executioner")
        long = "the case against it, " * 60
        with patch.dict(temperament.LANES, {"executioner": long}):
            want = fence.sanitize(temperament.lanes_text("executioner"), cap)
            w = self.rendered()
        self.assertGreater(len(temperament.lanes_text("executioner")), 0)
        ps_hash, tail_hash = w.block_hashes[-2], w.block_hashes[-1]
        ps = OrcDossierBlock.objects.get(hash=ps_hash)
        tail = OrcDossierBlock.objects.get(hash=tail_hash)
        self.assertEqual((ps.kind, tail.kind), ("ps", "tail"))
        body = json.loads(ps.text.split("\n", 1)[1])
        inner = body["ps9"].split(">", 1)[1].rsplit("</view>", 1)[0]
        self.assertEqual(inner, want)
        self.assertGreater(len(inner), cap - 3, "at its cap")
        self.assertEqual(body["ps11"], PS11_NONE)
        tail_body = json.loads(tail.text.split("\n", 1)[1])
        model = w.components.get("model") or ps.model
        used = (dossier.estimate_tokens(ps.text, 0, model)
                + dossier.estimate_tokens(tail.text,
                                          tape_rows(tail_body["in_today"]),
                                          model))
        self.assertLessEqual(used, PS_TAIL_RESERVE)
        self.assertLessEqual(ps.tokens_est + tail.tokens_est, PS_TAIL_RESERVE)


# ── the grade ────────────────────────────────────────────────────────────

class TheTemperamentGradeTests(_Births):

    def idea(self, name, *, o_r, care_r=0.1, venue="paper", source="etoro",
             read=True):
        """A dead idea of temperament `name` ('' for none) whose O arm
        closed at `o_r` and its care ghost at `care_r`."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc, OrcTrack, OrcWake
        kw = {"paper": venue == "paper"}
        if venue == "demo":
            kw["meta"] = {"broker_env": "paper"}
        row = _row(self.cfg, **kw)
        orc = born(self, row, at=T0)
        Orc.objects.filter(pk=orc.pk).update(temperament=name)
        if read:
            OrcWake.objects.create(orc=orc, status="done",
                                   dedupe_key=f"o2c:t:{orc.pk}")
        exits = {"orc_shadow": o_r, "care": care_r, "playbook": 0.0,
                 "chandelier3": 0.0, "staged": 0.0}
        for t in OrcTrack.objects.filter(orc=orc):
            st = dict(t.state)
            st["bar_sources"] = [source]
            OrcTrack.objects.filter(pk=t.pk).update(
                open=False, exit_r=exits[t.arm], exit_price=Decimal("101"),
                exit_at=T0 + timedelta(hours=5), exit_why="x", state=st)
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CLOSED", outcome="stopped_out",
            exit_price=Decimal("101"), closed_at=T0 + timedelta(hours=5))
        orc.refresh_from_db()
        seen = dict(orc.seen)
        seen["menu_source"] = source
        Orc.objects.filter(pk=orc.pk).update(
            state="dead", died_at=T0 + timedelta(hours=5), seen=seen)
        orc.refresh_from_db()
        return orc

    def rows(self):
        from bot_program.orcs.models import OrcTemperamentGrade
        return {(g.temperament, g.version, g.venue, g.asset_class,
                 g.bar_source): g for g in OrcTemperamentGrade.objects.all()}

    def test_per_key_against_the_control_never_pooled(self):
        from bot_program.orcs import tasks, tribunal
        from bot_program.orcs.models import OrcGrade
        a = self.idea("striker", o_r=0.6)
        b = self.idea("striker", o_r=1.1)
        self.idea("control", o_r=0.3)
        self.idea("striker", o_r=-0.5, venue="demo")
        self.idea("striker", o_r=2.0, source="platform")
        self.idea("striker", o_r=5.0, read=False)
        plain = self.idea("", o_r=0.9)
        out = tasks.grade_closed()
        self.assertEqual(out["graded"], 7)
        rows = self.rows()
        key = ("striker", "t1", "paper", "crypto", "etoro")
        self.assertEqual(set(rows), {
            key, ("control", "t1", "paper", "crypto", "etoro"),
            ("striker", "t1", "demo", "crypto", "etoro"),
            ("striker", "t1", "paper", "crypto", "platform")})
        self.assertEqual(out["temperament_grades"], len(rows))
        st = tribunal.block_stats([0.5, 1.0])
        g = rows[key]
        self.assertEqual(g.n, 2, "n_llm > 0 only: the unread idea is out")
        for field in ("mean", "se", "lb80", "ub80"):
            self.assertAlmostEqual(getattr(g, field), st[field])
        self.assertAlmostEqual(g.vs_control_mean, st["mean"] - 0.2)
        self.assertEqual(g.block, 0, "no full block of SEAT_WINDOW yet")
        ctl = rows[("control", "t1", "paper", "crypto", "etoro")]
        self.assertAlmostEqual(ctl.mean, 0.2)
        self.assertIsNone(ctl.vs_control_mean, "the control itself")
        # no control in the demo or platform group: no difference
        self.assertIsNone(rows[("striker", "t1", "demo", "crypto",
                                "etoro")].vs_control_mean)
        # the grade's tag, only with a temperament
        self.assertIn("temperament:striker:t1",
                      OrcGrade.objects.get(orc=a).tags)
        self.assertIn("temperament:striker:t1",
                      OrcGrade.objects.get(orc=b).tags)
        self.assertFalse([t for t in OrcGrade.objects.get(orc=plain).tags
                          if t.startswith("temperament:")])

    def test_the_controls_row_moving_refreshes_its_group(self):
        from bot_program.orcs import tasks
        self.idea("fixer", o_r=0.6)
        tasks.grade_closed()
        before = self.rows()[("fixer", "t1", "paper", "crypto", "etoro")]
        self.assertIsNone(before.vs_control_mean)
        self.idea("control", o_r=0.2)
        tasks.grade_closed()
        after = self.rows()[("fixer", "t1", "paper", "crypto", "etoro")]
        self.assertAlmostEqual(after.vs_control_mean, 0.5 - 0.1)

    def test_no_graded_orc_with_a_temperament_writes_nothing(self):
        from bot_program.orcs import tasks
        self.idea("", o_r=0.9)
        out = tasks.grade_closed()
        self.assertEqual(out, {"status": "success", "graded": 1,
                               "waiting": 0})
        self.assertEqual(self.rows(), {})


# ── N2: the switch itself ────────────────────────────────────────────────

class TheTemperamentsSwitchShipsOffTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()

    def test_it_is_seeded_off_beside_the_frontier(self):
        from core.platform_control import DEFAULT_COMPONENTS

        from bot_program.orcs import switches
        row = _row_of(KEY)
        self.assertFalse(row.is_enabled)
        self.assertEqual((row.name, row.category), (NAME, "system"))
        self.assertEqual(row.description, DESCRIPTION)
        self.assertLess(len(row.description), 300)
        entry = [c for c in DEFAULT_COMPONENTS if c["key"] == KEY]
        self.assertEqual(len(entry), 1)
        self.assertNotIn("is_enabled", entry[0], "it arrives OFF")
        self.assertNotIn("enabled", entry[0])
        keys = [c["key"] for c in DEFAULT_COMPONENTS]
        self.assertEqual(keys.index(KEY), keys.index("orcs_frontier") + 1)
        self.assertFalse(switches.temperaments_on())
        _switch(KEY, True)
        self.assertTrue(switches.temperaments_on())
        with patch("core.platform_control.is_component_enabled",
                   side_effect=RuntimeError("the table is gone")):
            self.assertFalse(switches.temperaments_on())

    def test_it_is_exempt_held_back_and_never_live(self):
        from core import switch_pin
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           LIVE_MONEY_SWITCHES,
                                           ORC_MIND_SWITCHES, PIN_SWITCHES)
        self.assertIn(KEY, ORC_MIND_SWITCHES)
        self.assertIn(KEY, BULK_ENABLE_EXEMPT)
        self.assertIn(KEY, PIN_SWITCHES)
        self.assertNotIn(KEY, LIVE_MONEY_SWITCHES)
        switch_pin.set_category("system", True, via=switch_pin.VIA_ALL_ON)
        self.assertFalse(_row_of(KEY).is_enabled,
                         '"all on" never reaches it')


class OnlyThePinTurnsTheTemperamentsOnTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        from portfolio.trader_profile import get_or_create_profile
        cache.clear()
        seed_components()
        self.admin = get_user_model().objects.create_superuser(
            "o2c_temper_admin", "o2c_temper@example.test", "x")
        prof = get_or_create_profile(self.admin)
        prof.set_pin(TEST_PIN)
        prof.save()
        self.client.force_login(self.admin)

    def ops(self, **extra):
        return self.client.post("/admin-dashboard/toggle/",
                                {"key": KEY, "next": "ops", **extra})

    def test_every_door_refuses_on_without_the_pin(self):
        self.ops()
        self.ops(want="on")
        self.ops(want="on", pin="")
        self.ops(want="on", pin=WRONG_PIN)
        self.client.post("/admin-dashboard/system-map/toggle/",
                         {"kind": "component", "key": KEY})
        with self.assertRaises(CommandError) as ctx:
            call_command("component", "on", KEY, stdout=StringIO())
        self.assertIn("/ops/", str(ctx.exception))
        from core import switch_pin
        self.assertFalse(switch_pin.set_switch(
            KEY, True, via=switch_pin.VIA_SHELL).ok)
        self.assertFalse(_row_of(KEY).is_enabled, "no door armed it")

    def test_the_right_pin_turns_it_on_and_off_takes_none(self):
        from bot_program.audit_models import AuditLogEntry
        self.ops(want="on", pin=TEST_PIN)
        self.assertTrue(_row_of(KEY).is_enabled)
        armed = [e for e in AuditLogEntry.objects.filter(kind="switch_armed")
                 if (e.data or {}).get("key") == KEY]
        self.assertEqual(len(armed), 1)
        out = StringIO()
        call_command("component", "off", KEY, stdout=out)
        self.assertIn(f"{KEY}: ON → OFF", out.getvalue())
        self.assertFalse(_row_of(KEY).is_enabled)


# ── the words ────────────────────────────────────────────────────────────

class TheTemperamentWordsTests(_Births):

    def _page(self, orc):
        self.client.force_login(self.user)
        return self.client.get(reverse("orc_detail", args=[
            orc.root_trade_id])).content.decode()

    def test_the_page_shows_the_temperament_only_when_there_is_one(self):
        from bot_program.orcs import temperament
        plain = self.newborn()
        self.assertNotIn('<span class="k">Temperament</span>',
                         self._page(plain))
        _switch(KEY, True)
        drawn = self.newborn()
        html = self._page(drawn)
        self.assertIn('<span class="k">Temperament</span><span>'
                      + temperament.page_line(drawn.temperament)
                      + "</span>", html)
        self.assertEqual(temperament.page_line("striker"),
                         "Striker: lead voice the Striker; drawn at birth, "
                         "fixed for life (t1)")
        self.assertEqual(temperament.page_line("control"),
                         "control: no lead voice; drawn at birth, fixed for "
                         "life (t1)")
        self.assertEqual(temperament.page_line(""), "")

    def test_the_runbook_says_the_pin_step_and_that_honor_always_runs(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        head = "### The Orcs' temperaments (O2c)"
        self.assertIn(head, text)
        section = text.split(head, 1)[1].split("\n## ", 1)[0] \
            .split("\n### ", 1)[0]
        flat = _fold(section)
        for words in (NAME, KEY, "/ops/", "trading PIN", "takes no PIN",
                      "fixed for life", "PS9", "whatever the switches say"):
            with self.subTest(words):
                self.assertIn(words, flat)
