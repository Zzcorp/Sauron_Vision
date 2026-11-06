"""O2b's FIRST COMMIT, THE ROUTE IN SHADOW (the O2 spec B.1-B.6, B.16c,
§1.2.5 P15 and P36-P39, §1.2.6 "The table" and the record half of "The
switch"; 2026-11-06).

A pure router (bot_program/orcs/router.py) chooses the rung of every
rendered wake from its band, its money world (the budget's: the seat AND
the row live, scheduler.is_real), the day and the effort map; the render
records the choice in components["route"], and r0 still answers every
wake a model reads. Nothing here turns a switch on: O2a's four gates
answer as they ship, and the router sends nothing.

- the table: band x world x day x gate gives the rung; h0 is never
  routed; demo and a row that states no world route as paper; extreme is
  r4 with its clause while the Fable gate is closed
- the effort map (mind.answering_map): without a PASS, r1 answers as r0
  and r3, r4 as r2, would_rung kept; a family's PASS gives the identity
- escalated: only a floor that raised the band
- probes[]: h0 and the boundary rung beside a paper wake on a calm day at
  score 27 (with Sonnet's PASS); none on a stormy day or on real money;
  without the PASS the collapsed pair is dropped
- the router is pure: no model id, the constants alone, no seat
- the record: every render writes the route, minds on and off; a real-
  money material wake records r2 while the fake records one request, on
  r0's model
- one render: the band, then the route, then ONE dossier.render; its
  hashes, tokens and the wake's headline O2a's; the effort map read once,
  outside the render's transaction
- P15: a merged survivor routes from the union
- the card: escalated and late through notes._intellect; the slot walk
  finds no model id or cost key (K-P16)
- B.6: an invalid answer is a refusal, one request, never a higher rung
- the Orc page: "would route: r2 (deep tier, medium effort)" while r0
  answered (B.16c)
- the words made true: complexity's and the weather's comments, the
  RUNBOOK's U-R6 lines

Run with:  python manage.py test tests.orcs.test_orc_o2b_router
"""
import ast
import copy
import inspect
import json
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone

from tests.orcs.helpers import _row, _switch, born
from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_admission import W2, W4, QueueFixture
from tests.orcs.test_orc_o2a_call import answer

BASE = Path(settings.BASE_DIR)
ROUTER = BASE / "bot_program" / "orcs" / "router.py"
RUNBOOK = BASE / "deploy" / "RUNBOOK.md"
W1 = {"code": "W1", "key": "W1", "t": "birth", "urgent": True}
BANDS = ("routine", "material", "complex", "extreme")
RUNGS = ("h0", "r0", "r1", "r2", "r3", "r4", "r5")
IDENTITY = {r: r for r in RUNGS}
#: B.5 with no recorded PASS: Sonnet's rungs answer as r0, Opus's as r2.
COLLAPSED = {"h0": "h0", "r0": "r0", "r1": "r0", "r2": "r2", "r3": "r2",
             "r4": "r2", "r5": "r5"}
#: Table v1 by (band, real money).
TABLE = {("routine", False): "r0", ("routine", True): "r0",
         ("material", False): "r1", ("material", True): "r2",
         ("complex", False): "r3", ("complex", True): "r3",
         ("extreme", False): "r4", ("extreme", True): "r4"}
#: The money worlds the router may be handed: only "live" is real money.
WORLDS = {"live": True, "demo": False, "paper": False, "": False,
          None: False}
#: A score far from every boundary (30, 55, 75): no boundary probe.
FAR = 42.0
ROUTE_WORDS = re.compile(r"^would route: r\d \([a-z]+ tier, [a-z]+ "
                         r"effort\)$")
MONEY_KEYS = {"cost_usd", "tokens_in", "tokens_out", "model_used", "model",
              "r_money", "spend", "spend_today_usd", "ai_cost_usd",
              "net_edge_money", "pnl", "balance", "equity", "est_usd",
              "bound", "tokens"}


def _route(band="routine", world="paper", *, day="calm", gate=None, left=0,
           effort=None, score=FAR, raw=None, kind="material"):
    """router.route with the commit's own defaults: the Fable gate closed
    and no frontier quota, as wake._render hands them."""
    from bot_program.orcs import router
    return router.route(band, world, kind, day, left,
                        router.GATE_CLOSED if gate is None else gate,
                        IDENTITY if effort is None else effort,
                        score=score, raw_band=band if raw is None else raw)


def _verdicts(**families):
    """The smoke's recorded verdicts (A.61): {family: "pass" | "fail"}."""
    from bot_program.orcs.models import OrcSetting
    OrcSetting.objects.update_or_create(key="smoke_verdict", defaults={
        "value": {fam: {"verdict": v, "reasons": [], "at": "x"}
                  for fam, v in families.items()}})


def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _model_words():
    """Every model id of the catalog, and the words that name one."""
    from ai_agents.catalog import MODELS
    return sorted(MODELS) + ["claude"]


# ── the table (pure) ─────────────────────────────────────────────────────

class TheTableTests(MindTestCase):
    """B.1, table v1: band x world x day x gate gives the rung."""

    def test_the_table_by_band_world_day_and_gate(self):
        from bot_program.orcs import router
        for band in BANDS:
            for world, real in WORLDS.items():
                for day in ("calm", "eventful", "stormy"):
                    for gate, left in ((router.GATE_CLOSED, 0),
                                       (router.GATE_CLOSED, 3), ("", 0)):
                        with self.subTest(band=band, world=world, day=day,
                                          gate=gate, left=left):
                            got = _route(band, world, day=day, gate=gate,
                                         left=left)
                            want = TABLE[(band, real)]
                            self.assertEqual(
                                (got["would_rung"], got["rung"]),
                                (want, want))
                            self.assertEqual(got["routing_version"],
                                             "table-v1")
                            self.assertFalse(got["twin"])
                            self.assertFalse(got["escalated"])
                            self.assertTrue(got["why"])
                            for t in got["why"]:
                                self.assertIsInstance(t, str)
        self.assertEqual(router.BANDS, BANDS)
        from bot_program.orcs.complexity import BANDS as SCORED
        self.assertEqual(router.BANDS, SCORED, "the bands the score gives")

    def test_h0_is_never_routed(self):
        """h0 is a paper probe's rung only: never the table's pick, and
        never the answering rung, whatever map the caller hands."""
        towards_h0 = {r: "h0" for r in RUNGS}
        for band in BANDS:
            for world in WORLDS:
                with self.subTest(band=band, world=world):
                    got = _route(band, world, effort=towards_h0)
                    self.assertNotEqual(got["would_rung"], "h0")
                    self.assertNotEqual(got["rung"], "h0")
                    self.assertEqual(got["rung"], got["would_rung"])
        # an unknown band is routine's r0, never a probe
        got = _route("nonsense", "live")
        self.assertEqual((got["would_rung"], got["rung"]), ("r0", "r0"))
        self.assertIn("an unknown band routes as routine", got["why"])

    def test_demo_and_a_row_that_states_no_world_route_as_paper(self):
        self.assertEqual(_route("material", "live")["would_rung"], "r2")
        self.assertEqual(_route("material", "paper")["would_rung"], "r1")
        self.assertIn("material on real money: r2",
                      _route("material", "live")["why"])
        self.assertIn("material on paper: r1",
                      _route("material", "paper")["why"])
        demo = _route("material", "demo")
        self.assertEqual((demo["would_rung"], demo["rung"]), ("r1", "r1"))
        self.assertIn("demo routes as paper", demo["why"])
        for world in ("", None, "elsewhere"):
            with self.subTest(world=world):
                got = _route("material", world)
                self.assertEqual(got["would_rung"], "r1")
                self.assertIn("a row that states no money world routes as "
                              "paper", got["why"])

    def test_extreme_is_r4_and_its_clause_while_the_gate_is_closed(self):
        """B.9: r5 only when every clause holds; the failing clause is in
        `why`. The router's own clauses are real money and a frontier
        quota left; the caller's verdict holds the rest. In this commit
        the caller hands the gate closed (B.9 is C4's)."""
        from bot_program.orcs import router
        self.assertEqual(router.GATE_CLOSED, "the Fable gate is closed")
        for world in ("live", "paper", "demo", ""):
            with self.subTest(world=world):
                got = _route("extreme", world, left=1)
                self.assertEqual((got["would_rung"], got["rung"]),
                                 ("r4", "r4"))
                self.assertIn("extreme: r4, the Fable gate is closed",
                              got["why"])
                self.assertFalse(got["twin"])
        # an unread gate is closed
        got = router.route("extreme", "live", "material", "calm", 1, None,
                           IDENTITY, score=80.0, raw_band="extreme")
        self.assertEqual(got["would_rung"], "r4")
        self.assertIn("extreme: r4, the Fable gate is closed", got["why"])
        # the router's own clauses, behind a gate the caller passed
        self.assertIn("extreme: r4, Fable answers real money only",
                      _route("extreme", "paper", gate="", left=1)["why"])
        self.assertIn("extreme: r4, no frontier quota is left today",
                      _route("extreme", "live", gate="", left=0)["why"])
        self.assertIn("extreme: r4, the pair does not fit",
                      _route("extreme", "live", gate="the pair does not "
                                                     "fit", left=1)["why"])
        # every clause holds: r5, with its blind twin (B.10)
        got = _route("extreme", "live", gate="", left=1)
        self.assertEqual((got["would_rung"], got["rung"], got["twin"]),
                         ("r5", "r5", True))


class TheEffortMapTests(MindTestCase):
    """B.5: one effort per model until the smoke's PASS for its family.
    The map is the caller's (mind.answering_map); the router reads it."""

    def test_without_a_pass_r1_answers_as_r0_and_r3_r4_as_r2(self):
        from bot_program.orcs import mind
        got = mind.answering_map()
        self.assertEqual(got, COLLAPSED)
        for band, world, would, rung in (
                ("routine", "paper", "r0", "r0"),
                ("material", "paper", "r1", "r0"),
                ("material", "live", "r2", "r2"),
                ("complex", "paper", "r3", "r2"),
                ("extreme", "live", "r4", "r2")):
            with self.subTest(band=band, world=world):
                r = _route(band, world, effort=got)
                self.assertEqual((r["would_rung"], r["rung"]), (would, rung))
        why = _route("complex", "paper", effort=got)["why"]
        self.assertIn("one effort per model until the smoke's PASS: r3 "
                      "answers as r2", why)

    def test_each_familys_pass_gives_the_identity(self):
        from bot_program.orcs import mind
        _verdicts(sonnet="pass")
        got = mind.answering_map()
        self.assertEqual((got["r0"], got["r1"], got["r2"], got["r3"],
                          got["r4"]), ("r0", "r1", "r2", "r2", "r2"))
        _verdicts(sonnet="fail", opus="pass")
        got = mind.answering_map()
        self.assertEqual((got["r1"], got["r3"], got["r4"]),
                         ("r0", "r3", "r4"))
        _verdicts(sonnet="pass", opus="pass", haiku="pass", fable="pass")
        self.assertEqual(mind.answering_map(), IDENTITY)
        r = _route("complex", "paper", effort=mind.answering_map())
        self.assertEqual((r["would_rung"], r["rung"]), ("r3", "r3"))

    def test_the_map_names_rungs_only_and_reads_the_verdicts_once(self):
        from bot_program.orcs import mind
        from bot_program.orcs.models import OrcSetting
        real_get = OrcSetting.get
        with patch.object(OrcSetting, "get", side_effect=real_get) as read:
            got = mind.answering_map()
        self.assertEqual([c.args[0] for c in read.call_args_list],
                         ["smoke_verdict"])
        self.assertEqual(set(got), set(RUNGS))
        self.assertLessEqual(set(got.values()), set(RUNGS))
        text = json.dumps(got)
        for word in _model_words():
            self.assertNotIn(word, text)


class EscalatedTests(MindTestCase):
    """B.6: escalated means only that a floor raised the band."""

    def test_escalated_only_when_a_floor_raised_the_band(self):
        got = _route("complex", "live", raw="routine")
        self.assertTrue(got["escalated"])
        self.assertIn("a floor raised the band from routine", got["why"])
        self.assertTrue(_route("material", "paper",
                               raw="routine")["escalated"])
        for band, raw in (("complex", "complex"), ("routine", "routine"),
                          ("material", "material"),
                          ("extreme", "extreme")):
            with self.subTest(band=band):
                got = _route(band, "live", raw=raw)
                self.assertFalse(got["escalated"])
                self.assertFalse([t for t in got["why"] if "floor" in t])
        # a band no floor reached is never escalated, even above its raw
        # band's spelling when that spelling is unknown
        self.assertFalse(_route("complex", "live", raw="?")["escalated"])


class TheProbesTests(MindTestCase):
    """B.11, listed only in this commit (no probe is sent): paper and demo
    wakes; h0 on calm and eventful days; the boundary rung across 30, 55
    or 75 within BAND_HYSTERESIS, after the map, dropped when it is the
    wake's own answering rung."""

    def sonnet_pass(self):
        from bot_program.orcs import mind
        _verdicts(sonnet="pass")
        return mind.answering_map()

    def test_a_paper_wake_on_a_calm_day_at_27_lists_h0_and_r1(self):
        effort = self.sonnet_pass()
        for world, day in (("paper", "calm"), ("demo", "calm"),
                           ("paper", "eventful")):
            with self.subTest(world=world, day=day):
                got = _route("routine", world, day=day, score=27.0,
                             effort=effort)
                self.assertEqual(got["rung"], "r0")
                self.assertEqual(got["probes"], [
                    {"kind": "h0", "rung": "h0", "would_rung": "h0",
                     "boundary": None},
                    {"kind": "boundary", "rung": "r1", "would_rung": "r1",
                     "boundary": 30}])

    def test_a_stormy_day_lists_none(self):
        effort = self.sonnet_pass()
        self.assertTrue(_route("routine", "paper", day="calm", score=27.0,
                               effort=effort)["probes"])
        self.assertEqual(_route("routine", "paper", day="stormy",
                                score=27.0, effort=effort)["probes"], [])

    def test_real_money_lists_none(self):
        effort = self.sonnet_pass()
        self.assertEqual(_route("routine", "live", day="calm", score=27.0,
                                effort=effort)["probes"], [])
        self.assertEqual(_route("material", "live", day="calm", score=33.0,
                                effort=IDENTITY)["probes"], [])

    def test_without_the_pass_the_collapsed_pair_is_dropped(self):
        """r1 answers as r0 until Sonnet's PASS: the boundary probe would
        be the wake's own rung, so only h0 stays."""
        from bot_program.orcs import mind
        got = _route("routine", "paper", day="calm", score=27.0,
                     effort=mind.answering_map())
        self.assertEqual(got["probes"], [{"kind": "h0", "rung": "h0",
                                          "would_rung": "h0",
                                          "boundary": None}])

    def test_the_boundary_rung_is_the_one_across(self):
        cases = (
            # band, score, map, the boundary probe or None
            ("material", 33.0, IDENTITY, ("r0", "r0", 30)),
            ("material", 35.0, IDENTITY, ("r0", "r0", 30)),
            ("material", 36.0, IDENTITY, None),
            ("material", 52.0, IDENTITY, ("r3", "r3", 55)),
            ("complex", 57.0, IDENTITY, ("r1", "r1", 55)),
            ("complex", 72.0, IDENTITY, ("r4", "r4", 75)),
            ("complex", 72.0, COLLAPSED, None),
            ("complex", 57.0, COLLAPSED, ("r0", "r1", 55)),
            ("extreme", 78.0, IDENTITY, ("r3", "r3", 75)),
            # a band its score does not border (a held band): no probe
            ("routine", 57.0, IDENTITY, None),
        )
        for band, score, effort, want in cases:
            with self.subTest(band=band, score=score):
                got = [p for p in _route(band, "paper", day="calm",
                                         score=score,
                                         effort=effort)["probes"]
                       if p["kind"] == "boundary"]
                if want is None:
                    self.assertEqual(got, [])
                else:
                    rung, would, boundary = want
                    self.assertEqual(got, [{"kind": "boundary",
                                            "rung": rung,
                                            "would_rung": would,
                                            "boundary": boundary}])


class TheRouterIsPureTests(MindTestCase):
    """B.1, B.3 and complexity.py:23-25 (KEEP): rung names only, the
    constants alone, nothing of a seat."""

    def test_the_router_names_no_model_and_imports_only_constants(self):
        src = ROUTER.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imports = [n for n in ast.walk(tree)
                   if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(imports)
        for node in imports:
            self.assertIsInstance(node, ast.ImportFrom, ast.unparse(node))
            self.assertEqual(node.module, "bot_program.orcs.constants",
                             ast.unparse(node))
        for word in _model_words():
            self.assertNotIn(word, src.lower())

    def test_the_router_reads_no_seat_scar_probation_or_privilege(self):
        tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
        self.assertFalse(names & {
            "OrcSeat", "seat", "level", "levels", "scar", "scars",
            "probation", "privilege", "privileges", "objects",
            "mind_gateway", "catalog", "ai_agents", "anthropic"}, names)
        from bot_program.orcs import router
        params = list(inspect.signature(router.route).parameters)
        self.assertEqual(params, ["band", "world", "kind", "day_class",
                                  "frontier_left", "gate", "effort_mode",
                                  "score", "raw_band"])


# ── the record (the render pass, the fake model) ─────────────────────────

class _Route(QueueFixture):
    """QueueFixture's Orc and gates; the tick records each wake
    (wake.record) and the render pass does the rest."""

    def record(self, reasons, *, orc=None, at=None):
        from bot_program.orcs import wake
        orc = orc or self.orc
        orc.refresh_from_db()
        return wake.record(orc, orc.root_trade, list(reasons),
                           now=at or timezone.now(), price="100.5")

    def render_pass(self, at=None):
        from bot_program.orcs import wake
        if at is None:
            return wake.render_queued()
        with patch("django.utils.timezone.now", return_value=at):
            return wake.render_queued()

    def fresh(self, w):
        from bot_program.orcs.models import OrcWake
        return OrcWake.objects.get(pk=w.pk)

    def r0_model(self):
        from bot_program.orcs import mind_gateway
        return mind_gateway.rung("r0")["model"]

    def assert_route(self, w):
        """components["route"] as every render writes it."""
        route = (w.components or {}).get("route")
        self.assertIsInstance(route, dict, "the render records the route")
        self.assertEqual(route["version"], "table-v1")
        self.assertIn(route["would_rung"], RUNGS)
        self.assertNotEqual(route["would_rung"], "h0")
        self.assertIn(route["rung"], RUNGS)
        self.assertRegex(route["words"], ROUTE_WORDS)
        self.assertTrue(route["words"].startswith(
            f"would route: {route['would_rung']} ("))
        self.assertIsInstance(route["why"], list)
        text = json.dumps(route)
        for word in _model_words():
            self.assertNotIn(word, text)
        self.assertNotIn("$", text)
        return route


class TheRecordTests(_Route):
    """B.2a: every render writes the route at no cost; admission keeps
    O2a's r0."""

    def test_every_render_records_the_route_with_the_minds_on_and_off(self):
        """With every gate ON a model reads the wake: one request (the
        positive control). With the minds switch OFF the render still
        records the route, and no request follows (minds_off)."""
        w = self.record([W2])
        self.render_pass()
        w = self.fresh(w)
        self.assertEqual(w.status, "pending")
        route = self.assert_route(w)
        self.assertEqual(w.components["rung"], "r0", "O2a's rung answers")
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.fresh(w).components["route"], route,
                         "the route is kept beside the answer")
        _switch("orcs_minds", False)
        off = self.record([W4])
        self.render_pass()
        off = self.fresh(off)
        self.assertEqual((off.status, off.skipped_reason),
                         ("skipped", "minds_off"))
        self.assert_route(off)
        self.assertIsNone(self.serve()["wake"])
        self.assert_no_call(code="minds_off", got=off.skipped_reason)

    def test_a_real_money_material_wake_routes_r2_while_r0_answers(self):
        """The record half of "The switch" (§1.2.6): every gate ON, a
        real-money material wake records route r2; admission writes O2a's
        r0, and the fake records exactly one request, on r0's model. The
        wake entry's body carries the route."""
        from bot_program.orcs.models import OrcJournal
        live = self.live()
        w = self.record([W4], orc=live)
        with patch("bot_program.orcs.complexity.score", return_value=40.0):
            self.render_pass()
        w = self.fresh(w)
        self.assertEqual(w.band, "material")
        route = self.assert_route(w)
        self.assertEqual((route["would_rung"], route["rung"]), ("r2", "r2"))
        self.assertEqual(route["words"],
                         "would route: r2 (deep tier, medium effort)")
        self.assertIn("material on real money: r2", route["why"])
        self.assertEqual((w.status, w.components["rung"]), ("pending", "r0"))
        entry = OrcJournal.objects.get(orc=live, kind="wake", wake=w)
        self.assertEqual(entry.body["route"], route)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.r0_model())
        w = self.fresh(w)
        self.assertEqual((w.status, w.model, w.components["rung"]),
                         ("done", self.r0_model(), "r0"))
        self.assertEqual(w.components["route"], route)

    def test_the_money_world_is_the_budgets_never_the_births(self):
        """scheduler.is_real, which render_queued reads and hands on: a
        demo row routes as paper, and so does a live seat's row that
        states no world, which birth.world reads as live (the render's
        own `real`, which the route never reads)."""
        from bot_program.orcs.birth import world
        from bot_program.orcs.models import OrcSetting
        OrcSetting.objects.update_or_create(key="max_paper_orcs",
                                            defaults={"value": 100})
        demo_row = _row(self.cfg, paper=False, symbol=self.symbol,
                        meta={"broker_env": "paper"})
        demo = born(self, demo_row, at=self.orc.born_at)
        self.assertEqual(demo.seat.venue, "demo")
        w = self.record([W4], orc=demo)
        with patch("bot_program.orcs.complexity.score", return_value=40.0):
            self.render_pass()
        route = self.assert_route(self.fresh(w))
        # paper's r1, answered as r0 until Sonnet's PASS (B.5)
        self.assertEqual((route["would_rung"], route["rung"]), ("r1", "r0"))
        self.assertIn("demo routes as paper", route["why"])
        live = self.live()
        w = self.record([W4], orc=live)
        # the live seat's row as a row that states no world (the pattern
        # of test_orc_o2a_admission: world_of reads "")
        with patch("dashboard.position_summary.world_of", return_value=""), \
                patch("bot_program.orcs.complexity.score",
                      return_value=40.0):
            self.assertEqual(world(live.root_trade), "live",
                             "birth.world's guess, never the route's")
            self.render_pass()
        route = self.assert_route(self.fresh(w))
        self.assertEqual((route["would_rung"], route["rung"]), ("r1", "r0"))
        self.assertIn("a row that states no money world routes as paper",
                      route["why"])
        # the same live row, its world read: real money
        w = self.record([W4], orc=live)
        with patch("bot_program.orcs.complexity.score", return_value=40.0):
            self.render_pass()
        self.assertEqual(self.assert_route(self.fresh(w))["would_rung"],
                         "r2")


class OneRenderTests(_Route):
    """B.4: the band, then the route, then ONE render, still for the
    reference family; the reorder changes nothing the dossier reads."""

    def test_the_band_then_the_route_then_one_render(self):
        """The order inside the render: the effort map (once, before the
        render's transaction), the inputs, the route, the dossier. With
        the minds on and off."""
        from bot_program.orcs import dossier, mind, router, wake
        order, depth, families = [], {}, []
        real_inputs, real_route = wake._position_inputs, router.route
        real_render, real_map = dossier.render, mind.answering_map

        def inputs(*a, **k):
            order.append("inputs")
            return real_inputs(*a, **k)

        def route(*a, **k):
            order.append("route")
            return real_route(*a, **k)

        def render(*a, **k):
            # recorded, asserted after: the render pass fences a raise
            order.append("render")
            depth["render"] = len(connection.atomic_blocks)
            families.append(k.get("model", "the reference family"))
            return real_render(*a, **k)

        def amap():
            order.append("map")
            depth["map"] = len(connection.atomic_blocks)
            return real_map()

        for minds, reason in ((True, W2), (False, W4)):
            with self.subTest(minds=minds):
                order.clear()
                families.clear()
                _switch("orcs_minds", minds)
                w = self.record([reason])
                with patch.object(wake, "_position_inputs", inputs), \
                        patch.object(router, "route", route), \
                        patch.object(dossier, "render", render), \
                        patch.object(mind, "answering_map", amap):
                    out = self.render_pass()
                self.assertEqual(tuple(out), (1, 0))
                self.assertEqual(order, ["map", "inputs", "route", "render"])
                self.assertEqual(families, ["the reference family"])
                self.assertLess(depth["map"], depth["render"],
                                "the map is read outside the render's "
                                "transaction")
                self.assert_route(self.fresh(w))

    def test_the_dossier_and_the_headline_are_o2as(self):
        """A regression pin of the reorder: the dossier stored (its hashes
        and its tokens) is the one O2a's order renders first, on the same
        context before the inputs read it; the wake's headline keeps
        O2a's words. Minds on and off."""
        from bot_program.orcs import dossier, wake
        from bot_program.orcs.models import OrcJournal
        real_inputs, real_render = wake._position_inputs, dossier.render
        for minds, reason, status_t in (
                (False, W4, "Answered by code: the minds switch is off"),
                (True, W2, "Its dossier is written; a model may read it "
                           "next")):
            with self.subTest(minds=minds):
                ref, rendered, before = [], [], []

                def render(*a, **k):
                    rendered.append(1)
                    return real_render(*a, **k)

                def inputs(orc, trade, ctx, reasons, now, market):
                    # the renders so far, asserted after (a raise here is
                    # fenced by the render pass)
                    before.append(len(rendered))
                    if not ref:
                        sid = transaction.savepoint()
                        try:
                            ref.append(real_render(
                                orc, trade, copy.deepcopy(ctx), as_of=now))
                        finally:
                            transaction.savepoint_rollback(sid)
                    return real_inputs(orc, trade, ctx, reasons, now,
                                       market)
                _switch("orcs_minds", minds)
                w = self.record([reason])
                with patch.object(wake, "_position_inputs", inputs), \
                        patch.object(dossier, "render", render):
                    self.render_pass()
                w = self.fresh(w)
                self.assertEqual(before, [0], "the inputs before the "
                                              "dossier, which renders once")
                self.assertEqual(rendered, [1])
                self.assertEqual(len(ref), 1)
                self.assertEqual(w.block_hashes, ref[0]["hashes"])
                self.assertEqual(w.components["tokens"], ref[0]["tokens"])
                entry = OrcJournal.objects.get(kind="wake", wake=w)
                self.assertEqual(entry.headline, (
                    f"Wake detected: {reason['t']}. Complexity "
                    f"{w.score:.0f} ({w.band}); the day is {w.day_class}. "
                    f"{status_t}."))


class TheMergeRoutesFromTheUnionTests(_Route):
    """P15 (B.2): absorb runs before the render, so a merged survivor's
    route is the union's."""

    def test_a_routine_wake_absorbing_a_real_birth_routes_from_the_union(
            self):
        """A routine wake absorbs the real Orc's older birth wake (W1): the
        union is a birth, F2's floor raises the band to complex, the
        route is r3 (answered as r2 until Opus's PASS), escalated."""
        live = self.live()
        first = timezone.now() - timedelta(minutes=70)
        older = self.record([W1], orc=live, at=first)
        with patch("bot_program.orcs.complexity.score", return_value=12.0):
            self.render_pass(at=first)
            self.assertEqual(self.fresh(older).status, "pending")
            newer = self.record([W2], orc=live)
            self.render_pass()
        older, newer = self.fresh(older), self.fresh(newer)
        self.assertEqual((older.status, older.components["merged_into"]),
                         ("merged", newer.pk))
        self.assertEqual({r["key"] for r in newer.reasons},
                         {W1["key"], W2["key"]})
        self.assertEqual(newer.kind, "birth")
        self.assertEqual((newer.components["floor"], newer.band),
                         ("complex", "complex"))
        route = self.assert_route(newer)
        self.assertEqual((route["would_rung"], route["rung"]), ("r3", "r2"))
        self.assertTrue(route["escalated"])
        self.assertIn("a floor raised the band from routine", route["why"])
        live.refresh_from_db()
        self.assertIs(live.card["intellect"]["escalated"], True)
        self.assertEqual(live.card["intellect"]["wake"], newer.pk)


class TheCardTests(_Route):
    """B.6, U-P15: the render writes the true escalated on the card, and
    notes._intellect reads it beside late."""

    def test_the_card_carries_escalated_and_notes_reads_it_and_late(self):
        from bot_program.orcs import notes
        live = self.live()
        self.record([W1], orc=live)
        with patch("bot_program.orcs.complexity.score", return_value=12.0):
            self.render_pass()
        live.refresh_from_db()
        it = live.card["intellect"]
        self.assertIs(it["escalated"], True, "F2 raised a real birth")
        sl = notes.slot(live, trade=live.root_trade)
        self.assertIs(sl["intellect"]["escalated"], True)
        self.assertIs(sl["intellect"]["late"], False)
        for value, said in ((True, True), (False, False), ("yes", False),
                            (1, False), (None, False)):
            with self.subTest(value=value):
                got = notes._intellect({"intellect": {
                    **it, "escalated": value, "late": value}})
                self.assertIs(got["escalated"], said)
                self.assertIs(got["late"], said)
        got = notes._intellect({"intellect": {
            k: v for k, v in it.items() if k not in ("escalated", "late")}})
        self.assertIs(got["escalated"], False)
        # a paper wake no floor raised says so
        self.record([W2])
        self.render_pass()
        self.orc.refresh_from_db()
        self.assertIs(self.orc.card["intellect"]["escalated"], False)

    def test_the_slot_walk_finds_no_model_id_or_cost_key(self):
        """K-P16 (N5, N6): with the route recorded and a model's answer
        settled, the slot carries no model id and no cost, token, model
        or spend key at any depth; nor does the route's own record."""
        from bot_program.orcs import notes
        w = self.record([W2])
        self.render_pass()
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.card["intellect"]["rung_t"],
                         "r0 · balanced tier, low effort")
        for minds in (True, False):
            sl = notes.slot(self.orc, trade=self.orc.root_trade,
                            minds=minds)
            self.assertFalse(_keys(sl) & MONEY_KEYS, _keys(sl) & MONEY_KEYS)
            text = json.dumps(sl, ensure_ascii=False).lower()
            for word in _model_words() + ["sonnet", "opus", "haiku",
                                          "fable"]:
                self.assertNotIn(word, text)
            self.assertNotIn("$", text)
        route = self.fresh(w).components["route"]
        self.assertFalse(_keys(route) & MONEY_KEYS)


class NoSecondAskTests(_Route):
    """B.6 (N4): O2b never asks a wake again after an invalid answer."""

    def test_an_invalid_answer_is_a_refusal_on_one_request_never_higher(self):
        """A paper material wake whose route says r1, with Sonnet's PASS
        recorded: its answer the validator refuses is a refusal after
        exactly one request, on r0's model; the next claim finds nothing,
        and no request follows on any rung."""
        from bot_program.orcs.models import OrcJournal
        _verdicts(sonnet="pass")
        w = self.record([W4])
        with patch("bot_program.orcs.complexity.score", return_value=40.0):
            self.render_pass()
        w = self.fresh(w)
        route = self.assert_route(w)
        self.assertEqual((route["would_rung"], route["rung"]), ("r1", "r1"))
        got = self.serve(script=fake_answer(text="not an answer"))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.r0_model())
        w = self.fresh(w)
        self.assertEqual((w.status, w.components["rung"]), ("refused", "r0"))
        decision = OrcJournal.objects.get(kind="decision", wake=w)
        self.assertEqual(decision.body["rung"], "r0")
        self.assertIsNone(self.serve()["wake"], "nothing is asked again")
        self.assert_no_call()


class TheOrcPageTests(_Route):
    """B.16c: the Rung column shows the rung a model was sent and, while
    that is not the router's choice, the choice in tier words."""

    def block(self, orc):
        self.client.force_login(self.user)
        html = self.client.get(reverse("orc_detail", args=[
            orc.root_trade_id])).content.decode()
        return html, html.split('id="orc-wakes"', 1)[1].split("</table>",
                                                              1)[0]

    def test_the_rung_column_says_would_route_while_r0_answered(self):
        live = self.live()
        w = self.record([W4], orc=live)
        with patch("bot_program.orcs.complexity.score", return_value=40.0):
            self.render_pass()
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        _switch("orcs_minds", False)
        coded = self.record([W4], orc=live)
        with patch("bot_program.orcs.complexity.score", return_value=40.0):
            self.render_pass()
        self.assertEqual(self.fresh(coded).skipped_reason, "minds_off")
        html, block = self.block(live)
        self.assertIn(">r0 · would route: r2 (deep tier, medium effort)<",
                      block)
        self.assertIn(">would route: r2 (deep tier, medium effort)<", block)
        for word in _model_words():
            self.assertNotIn(word, html)
        self.assertNotIn("$", block)

    def test_the_column_shows_only_code_written_route_words(self):
        """A code answer shows the router's choice alone; a quiet wake
        shows none; a route that is the rung sent adds nothing; words that
        are not the router's tier words are never shown."""
        from bot_program.orcs.models import OrcWake
        route = {"rung": "r0", "would_rung": "r0", "why": [],
                 "version": "table-v1",
                 "words": "would route: r0 (balanced tier, low effort)"}
        deep = {**route, "rung": "r2", "would_rung": "r2",
                "words": "would route: r2 (deep tier, medium effort)"}
        OrcWake.objects.create(orc=self.orc, reasons=[], dedupe_key="q",
                               status="quiet", kind="routine",
                               components={"route": deep})
        OrcWake.objects.create(orc=self.orc, reasons=[], dedupe_key="d",
                               status="done", kind="routine",
                               started_at=timezone.now(),
                               components={"rung": "r0", "route": route})
        OrcWake.objects.create(orc=self.orc, reasons=[], dedupe_key="s",
                               status="skipped", skipped_reason="minds_off",
                               kind="material", components={"route": deep})
        OrcWake.objects.create(orc=self.orc, reasons=[], dedupe_key="x",
                               status="skipped", skipped_reason="minds_off",
                               kind="routine", components={"route": {
                                   **deep, "words": "would route: claude "
                                                    "(x)"}})
        _html, block = self.block(self.orc)
        cells = re.findall(r'<td data-label="Rung">([^<]*)</td>', block)
        self.assertEqual(sorted(cells), [
            "r0", "would route: r2 (deep tier, medium effort)", "—", "—"])
        self.assertNotIn("claude", block)


# ── the words made true (§1.0 items 6 and 7) ─────────────────────────────

class TheWordsTests(MindTestCase):

    def test_the_comments_say_the_route_is_recorded_in_shadow(self):
        from bot_program.orcs import complexity, weather
        self.assertNotIn("routes NOTHING (the router is O2's)",
                         " ".join(complexity.__doc__.split()))
        self.assertIn("bot_program/orcs/router.py", complexity.__doc__)
        src = inspect.getsource(weather)
        self.assertNotIn("until O2b", src)
        self.assertNotIn("(O2b's)", src)
        self.assertNotIn("the router is O2b's", " ".join(src.split()))
        self.assertIn("recorded in shadow", " ".join(
            weather.__doc__.split()))

    def test_the_runbook_says_routing_is_recorded_and_r0_answers(self):
        """U-R6: the /ai-models/ card's paragraph."""
        text = RUNBOOK.read_text(encoding="utf-8")
        para = " ".join(text.split("The card \"The Orcs (read-only)\"",
                                   1)[1].split("\n\n", 1)[0].split())
        self.assertIn("every wake a model reads is answered on r0", para)
        self.assertIn("recorded in shadow", para)
        self.assertIn("would route: r2 (deep tier, medium effort)", para)
        self.assertNotIn("a router comes with O2b", para)
        self.assertIn("No tier setting on this page ever moves the ladder "
                      "or the route", para)
        self.assertIn("no override can be saved for an Orc agent name",
                      para)
