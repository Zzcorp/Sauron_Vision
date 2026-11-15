"""O2c's HONOR: THE CODE OF HONOR, AUDITED IN SHADOW AT THE GRADE (the O2 spec
C.1, C.2; §1.3.6 "Honor"; §0 N1, N5, N6, N7; 2026-11-15).

bot_program/orcs/honor.py's pure audits over one dead idea's shadow record,
run by its grade (bot_program/orcs/grading.py) before the grade's
transaction, on journals built by hand here:

- H1, an unacknowledged miss: the first decision the validator passed whose
  own dossier showed a missed expectation (evidence.py's fact) and that does
  not cite it; quiet when it cites it, and a decision whose dossier predates
  the miss is not the one judged
- H2, an unacted signpost: a met predicate or a thesis-check exit with no
  exit, trim or tighten proposed within one bar of the decision frame; quiet
  with a tighten inside that bar, and for an idea that ended inside it
- H3, the tripwire: the O arm, in would mode, closed below TRIPWIRE_IDEA_R;
  quiet at -1.0R and in O1's mode (the arm recording the row)
- no finding on a signpost before the idea's first wake a model read
- each finding a `breach` entry by code, mode shadow, with its evidence
  ids, its kind and author allowed; written once, with the grade
- the grade's tags carry shadow_breach:<code> and its body the class
  tribunal.classify gives with the breaches counted, while fell and
  sub_label stay binding: no idea is FAULT
- a breach-free idea's grade row, tags and body equal the grade without
  honor; refusals never count; the audit is pure
- honor sends no request (the pair, N7)
- the Orc page shows the shadow breaches by code, only when there are some

Run with:  python manage.py test tests.orcs.test_orc_o2c_honor
"""
import ast
import inspect
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse

from tests.orcs.helpers import _config, _on, _row, _switch, _user, born
from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_call import NOW, MindFixture, answer

#: A Wednesday, 10:00 UTC: the idea is born here and lives two days.
T0 = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)
#: Every arm's exit R, the O arm's set by each test.
EXITS = {"orc_shadow": 0.5, "care": 0.4, "playbook": 0.3,
         "chandelier3": 0.2, "staged": 0.1}
ORC_WORD = re.compile(r"\b(Orc|Orcs|Captain|Captains)\b")
VERB = re.compile(r"Orc\w*\s+(decided|closed|trimmed|tightened|added|moved|"
                  r"exited)")


def _at(hours):
    return T0 + timedelta(hours=hours)


class _Record(MindTestCase):
    """One paper bot idea born at T0, its shadow record written by hand:
    wakes (a model read them when their status is one of MODEL_ANSWERED),
    facts, decisions and proposals at chosen moments; then its death and
    its grade."""

    def setUp(self):
        _on()
        _switch("aragorn")
        self.user = _user(f"o2c_h_{type(self).__name__.lower()[:18]}")
        self.cfg = _config(self.user)
        self.row = _row(self.cfg)
        self.orc = born(self, self.row, at=T0)

    # ── the record, by hand ──────────────────────────────────────────────

    def span(self):
        from bot_program.orcs import bars, dossier
        return bars.span_of(dossier.decision_tf(self.orc))

    def wake(self, hours, status="done", *, max_fact=None):
        from bot_program.orcs.models import OrcWake
        comps = {} if max_fact is None else {"vctx": {"max_fact": max_fact}}
        w = OrcWake.objects.create(
            orc=self.orc, status=status, components=comps,
            dedupe_key=f"o2c:honor:{OrcWake.objects.count()}")
        read = status in ("done", "refused", "late")
        OrcWake.objects.filter(pk=w.pk).update(
            created_at=_at(hours), started_at=_at(hours) if read else None,
            finished_at=_at(hours) if read else None)
        w.refresh_from_db()
        return w

    def fact(self, hours, body, text):
        from bot_program.orcs import journal
        return journal.append(self.orc, "fact", text, body=body, fact=True,
                              at=_at(hours))

    def missed(self, hours):
        return self.fact(hours, {"fk": "expectation", "decision": 1,
                                 "kind": "closes_above", "result": "missed",
                                 "symbol": "BTCUSD"},
                         "The expectation set at 10:00 UTC (a close above "
                         "S4h-L1 (101)) was missed.")

    def met(self, hours):
        return self.fact(hours, {
            "predicate": {"kind": "displaced_bos_against", "tf": "4h",
                          "by": "code"},
            "result": {"key": "displaced_bos_against:4h:",
                       "kind": "displaced_bos_against", "state": "met",
                       "why": "", "bar_at": None}},
            "Invalidation met: a displaced break against the position on "
            "the 4h at 12:00 UTC.")

    def thesis_exit(self, hours):
        return self.fact(hours, {"verdict": "exit", "stop": None},
                         "The thesis check reads exit.")

    def review_exit(self, hours):
        """The position reviewer's exit: no signpost of H2's."""
        return self.fact(hours, {"review": 1, "verdict": "exit", "leg": 1},
                         "The reviewer reads exit.")

    def decision(self, hours, *, cited=(), status="done", wake=None):
        from bot_program.orcs import journal
        return journal.append(
            self.orc, "decision", "Decision in shadow: hold.", author="orc",
            body={"wake": getattr(wake, "pk", None), "rung": "r0",
                  "answer": {"action": "hold", "facts_cited": list(cited)},
                  "status": status, "rule": "" if status == "done" else "V3",
                  "expectation": None},
            wake=wake, at=_at(hours))

    def refusal(self, hours, decision):
        from bot_program.orcs import journal
        return journal.append(
            self.orc, "refusal", "Refused by the validator (V3).",
            body={"rule": "V3", "part": "whole", "words": "x",
                  "decision": decision.pk}, at=_at(hours))

    def intent(self, hours, kind="tighten", *, status="simulated",
               mode="shadow"):
        from bot_program.orcs.models import OrcIntent
        it = OrcIntent.objects.create(orc=self.orc, kind=kind, mode=mode,
                                      status=status, rung="r0",
                                      s_version="s1", schema_version="v1")
        OrcIntent.objects.filter(pk=it.pk).update(created_at=_at(hours))
        return it

    def dead(self, hours=48, *, o_r=0.5, mode="real", o_exit_hours=None):
        """Every arm closed (the O arm at `o_r`, in `mode`, out at
        `o_exit_hours`), the row closed and the idea dead at `hours`."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc, OrcTrack
        exits = {**EXITS, "orc_shadow": o_r}
        out = _at(hours if o_exit_hours is None else o_exit_hours)
        for t in OrcTrack.objects.filter(orc=self.orc):
            st = dict(t.state)
            st["bar_sources"] = ["etoro"]
            if t.arm == "orc_shadow":
                st["best_m_r"] = 1.6
                st["mode"] = mode
            OrcTrack.objects.filter(pk=t.pk).update(
                open=False, exit_r=exits[t.arm], exit_price=Decimal("101"),
                exit_at=out if t.arm == "orc_shadow" else _at(hours),
                exit_why="x", state=st)
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            status="CLOSED", outcome="stopped_out", pnl=Decimal("3"),
            exit_price=Decimal("101"), closed_at=_at(hours))
        seen = dict(self.orc.seen)
        seen["menu_source"] = "etoro"
        Orc.objects.filter(pk=self.orc.pk).update(
            state="dead", died_at=_at(hours), seen=seen)
        self.orc.refresh_from_db()

    def findings(self):
        from bot_program.orcs import grading
        return grading.shadow_findings(self.orc)

    def codes(self):
        return [f["code"] for f in self.findings()]

    def grade(self, hours=49):
        from bot_program.orcs.grading import grade
        return grade(self.orc, now=_at(hours))

    def entries(self, **filters):
        from bot_program.orcs.models import OrcJournal
        return list(OrcJournal.objects.filter(orc=self.orc, **filters)
                    .order_by("at", "id"))


# ── H1, an unacknowledged miss ───────────────────────────────────────────

class TheUnacknowledgedMissTests(_Record):

    def test_h1_fires_when_the_next_decision_does_not_cite_the_miss(self):
        self.wake(1)
        self.decision(1)
        miss = self.missed(5)
        self.decision(6, cited=["F1"])
        self.dead()
        [found] = self.findings()
        self.assertEqual(found["code"], "H1")
        self.assertEqual(found["evidence"], [miss.fact_id])
        self.assertEqual(found["at"], _at(6), "at the uncited decision")
        self.assertIn(miss.fact_id, found["t"])

    def test_h1_is_quiet_when_the_next_decision_cites_it(self):
        self.wake(1)
        miss = self.missed(5)
        self.decision(6, cited=[miss.fact_id])
        # a later decision that cites it no more is no breach: the miss was
        # acknowledged by the decision that saw it first
        self.decision(10)
        self.dead()
        self.assertEqual(self.codes(), [])

    def test_a_decision_whose_dossier_predates_the_miss_is_not_judged(self):
        """A call in flight while a new bar closes: its dossier was written
        before the miss, so the decision that judges it is the first one
        whose dossier showed it (its wake's vctx.max_fact)."""
        self.wake(1)
        miss = self.missed(5)
        n = int(miss.fact_id[1:])
        early = self.wake(4, max_fact=n - 1)
        self.decision(6, wake=early)
        late = self.wake(7, max_fact=n)
        self.decision(8, cited=[miss.fact_id], wake=late)
        self.dead()
        self.assertEqual(self.codes(), [])
        # a later decision that cites it no more is no breach either
        self.decision(9, wake=self.wake(9, max_fact=n + 1))
        self.assertEqual(self.codes(), [])

    def test_the_decision_that_saw_the_miss_and_did_not_cite_it(self):
        self.wake(1)
        miss = self.missed(5)
        n = int(miss.fact_id[1:])
        self.decision(6, wake=self.wake(4, max_fact=n - 1))
        self.decision(8, wake=self.wake(7, max_fact=n))
        self.dead()
        [found] = self.findings()
        self.assertEqual((found["code"], found["evidence"], found["at"]),
                         ("H1", [miss.fact_id], _at(8)))


# ── H2, an unacted signpost ──────────────────────────────────────────────

class TheUnactedSignpostTests(_Record):

    def test_h2_fires_on_a_met_predicate_left_unacted_one_bar(self):
        self.wake(1)
        met = self.met(5)
        span = self.span()
        self.dead()
        [found] = self.findings()
        self.assertEqual(found["code"], "H2")
        self.assertEqual(found["evidence"], [met.fact_id])
        self.assertEqual(found["at"], _at(5) + span,
                         "at the end of the bar left unacted")
        self.assertIn(met.fact_id, found["t"])

    def test_h2_fires_on_a_thesis_check_exit_left_unacted(self):
        self.wake(1)
        ex = self.thesis_exit(5)
        self.review_exit(6)
        self.dead()
        [found] = self.findings()
        self.assertEqual((found["code"], found["evidence"]),
                         ("H2", [ex.fact_id]))

    def test_a_tighten_inside_that_bar_acts_on_it(self):
        self.wake(1)
        self.met(5)
        span = self.span()
        self.intent(5 + span.total_seconds() / 3600 * 0.5, "tighten")
        self.dead()
        self.assertEqual(self.codes(), [])

    def test_a_trim_or_an_exit_inside_that_bar_acts_and_a_late_one_not(self):
        span_h = self.span().total_seconds() / 3600
        self.wake(1)
        self.met(5)
        self.intent(5 + span_h / 2, "trim")
        self.thesis_exit(20)
        self.intent(20 + span_h / 4, "exit")
        third = self.met(30)
        self.intent(30 + span_h + 0.5, "tighten")
        self.intent(30 + span_h / 2, "lock_waive")
        self.dead()
        found = self.findings()
        self.assertEqual([(f["code"], f["evidence"]) for f in found],
                         [("H2", [third.fact_id])],
                         "a tighten after the bar, or a lock waiver, does "
                         "not act on it")

    def test_an_idea_that_ended_inside_that_bar_is_not_judged(self):
        """A signpost the idea did not outlive by one decision bar was
        never left unacted past one decision bar (tribunal.IdeaFacts)."""
        span_h = self.span().total_seconds() / 3600
        self.wake(1)
        self.met(40)
        self.dead(hours=40 + span_h / 2)
        self.assertEqual(self.codes(), [])

    def test_an_arm_that_closed_inside_that_bar_leaves_it_unjudged(self):
        span_h = self.span().total_seconds() / 3600
        self.wake(1)
        self.met(20)
        self.dead(hours=48, mode="would", o_exit_hours=20 + span_h / 2)
        self.assertEqual(self.codes(), [])

    def test_h2_is_exposed_for_o2ds_signpost_unacted(self):
        """D.12: O2d's IdeaFacts.signpost_unacted comes from h2."""
        from bot_program.orcs import dossier, honor
        from bot_program.orcs.models import OrcIntent, OrcJournal, OrcWake
        self.wake(1)
        met = self.met(5)
        self.dead()
        found = honor.h2(
            list(OrcJournal.objects.filter(orc=self.orc)),
            list(OrcIntent.objects.filter(orc=self.orc)),
            wakes=list(OrcWake.objects.filter(orc=self.orc)),
            decision_tf=dossier.decision_tf(self.orc),
            until=self.orc.died_at)
        self.assertEqual([f["evidence"] for f in found], [[met.fact_id]])
        self.assertEqual(found, [f for f in self.findings()
                                 if f["code"] == "H2"])


# ── H3, the tripwire ─────────────────────────────────────────────────────

class TheTripwireTests(_Record):

    def _exit_fact(self, r):
        return self.fact(47, {"arm": "orc_shadow", "exit_r": r, "why": "x",
                              "tail_capped": False},
                         f"The shadow arm exited: x at 97 ({r:+.2f}R).")

    def test_h3_fires_below_minus_1_2r_in_would_mode(self):
        from bot_program.orcs.constants import TRIPWIRE_IDEA_R
        self.assertEqual(TRIPWIRE_IDEA_R, -1.2)
        ex = self._exit_fact(-1.25)
        self.dead(o_r=-1.25, mode="would", o_exit_hours=47)
        [found] = self.findings()
        self.assertEqual((found["code"], found["evidence"], found["at"]),
                         ("H3", [ex.fact_id], _at(47)))
        self.assertIn("the stop did not hold", found["t"])

    def test_h3_is_quiet_at_minus_1_0r(self):
        self._exit_fact(-1.0)
        self.dead(o_r=-1.0, mode="would", o_exit_hours=47)
        self.assertEqual(self.codes(), [])

    def test_h3_is_quiet_in_o1s_mode(self):
        """The O arm recording the row (mode real: no proposal of the
        Orc's ever stepped it) is the care's loss, never a breach."""
        self._exit_fact(-1.25)
        self.dead(o_r=-1.25, mode="real", o_exit_hours=47)
        self.assertEqual(self.codes(), [])


# ── the first model-read wake ────────────────────────────────────────────

class TheFirstReadTests(_Record):

    def test_no_finding_before_the_ideas_first_model_read_wake(self):
        """An Orc no model read could not have proposed anything: H1 and
        H2 read only the signposts at or after its first wake a model
        read."""
        self.wake(1, status="quiet")
        self.wake(2, status="skipped")
        self.missed(3)
        self.met(3)
        self.wake(10)
        self.decision(10)
        self.dead()
        self.assertEqual(self.codes(), [])
        # the same signposts once a model has read the idea: judged
        self.missed(12)
        self.met(12)
        self.decision(13)
        self.assertEqual(sorted(self.codes()), ["H1", "H2"])

    def test_an_idea_no_model_read_has_no_finding(self):
        self.wake(1, status="quiet")
        self.missed(3)
        self.met(3)
        self.decision(4)
        self.dead()
        self.assertEqual(self.codes(), [])


# ── what the grade writes ────────────────────────────────────────────────

class TheBreachEntriesTests(_Record):

    def _three(self):
        """One finding of each code."""
        self.wake(1)
        miss = self.missed(5)
        self.decision(6)
        met = self.met(10)
        ex = self.fact(47, {"arm": "orc_shadow", "exit_r": -1.25, "why": "x",
                            "tail_capped": False},
                       "The shadow arm exited: x at 97 (-1.25R).")
        self.dead(o_r=-1.25, mode="would", o_exit_hours=47)
        return miss, met, ex

    def test_each_finding_is_a_breach_entry_by_code_in_shadow(self):
        from bot_program.orcs.constants import AUTHORS, JOURNAL_KINDS
        miss, met, ex = self._three()
        g = self.grade()
        self.assertIsNotNone(g)
        breaches = self.entries(kind="breach")
        self.assertEqual([(e.body, e.author, e.at) for e in breaches], [
            ({"code": "H1", "mode": "shadow", "evidence": [miss.fact_id]},
             "code", _at(6)),
            ({"code": "H2", "mode": "shadow", "evidence": [met.fact_id]},
             "code", _at(10) + self.span()),
            ({"code": "H3", "mode": "shadow", "evidence": [ex.fact_id]},
             "code", _at(47))])
        for e in breaches:
            self.assertIn(e.kind, JOURNAL_KINDS)
            self.assertIn(e.author, AUTHORS)
            self.assertEqual(e.fact_id, "", "a finding is no fact")
            self.assertTrue(e.headline.startswith(
                f"Shadow breach {e.body['code']}, "), e.headline)
        # written once, with the grade: a second grade writes none
        self.grade(hours=60)
        self.assertEqual(len(self.entries(kind="breach")), 3)
        # the grade's own line comes after its findings
        last = self.entries()[-1]
        self.assertEqual(last.kind, "grade")

    def test_the_tags_and_the_shadow_class_while_fell_stays_binding(self):
        from bot_program.orcs import tribunal
        from bot_program.orcs.constants import FELL_FAULT
        self._three()
        g = self.grade()
        self.assertEqual([t for t in g.tags if t.startswith("shadow_")],
                         ["shadow_breach:H1", "shadow_breach:H2",
                          "shadow_breach:H3"])
        self.assertNotEqual(g.fell, FELL_FAULT, "no idea is FAULT in O2")
        [entry] = self.entries(kind="grade")
        body = entry.body
        binding = tribunal.classify(tribunal.IdeaFacts(
            orc_r_gross=-1.25, ghost_r=0.4, delta_care=-1.65,
            first_divergence=g.first_divergence))
        shadow = tribunal.classify(tribunal.IdeaFacts(
            orc_r_gross=-1.25, ghost_r=0.4, delta_care=-1.65,
            first_divergence=g.first_divergence, breaches=3))
        self.assertEqual((g.fell, g.sub_label), (binding.fell,
                                                 binding.sub_label))
        self.assertEqual((body["fell"], body["sub_label"]),
                         (g.fell, g.sub_label))
        self.assertEqual(body["shadow"], {"fell": shadow.fell,
                                          "sub_label": shadow.sub_label,
                                          "causes": list(shadow.causes)})
        self.assertEqual(body["shadow"]["fell"], FELL_FAULT,
                         "the class the idea would get if they bound")
        self.assertNotIn("Fault", entry.headline)

    def test_codes_are_distinct_and_sorted_in_the_tags(self):
        self.wake(1)
        self.met(5)
        self.met(20)
        self.missed(25)
        self.decision(26)
        self.dead()
        g = self.grade()
        self.assertEqual([t for t in g.tags if t.startswith("shadow_")],
                         ["shadow_breach:H1", "shadow_breach:H2"])
        self.assertEqual(len(self.entries(kind="breach")), 3)

    def test_a_breach_free_grade_equals_the_grade_without_honor(self):
        from bot_program.orcs.models import OrcGrade, OrcJournal
        self.wake(1)
        miss = self.missed(5)
        self.decision(6, cited=[miss.fact_id])
        self.met(10)
        self.intent(11, "tighten")
        self.dead()

        def snap():
            g = OrcGrade.objects.get(orc=self.orc)
            row = {f.name: getattr(g, f.name) for f in OrcGrade._meta.fields
                   if f.name not in ("id",)}
            [e] = OrcJournal.objects.filter(orc=self.orc, kind="grade")
            return row, list(g.tags), e.headline, e.body
        with patch("bot_program.orcs.honor.audit", return_value=[]):
            self.grade()
        without = snap()
        OrcGrade.objects.filter(orc=self.orc).delete()
        OrcJournal.objects.filter(orc=self.orc, kind="grade").delete()
        self.grade()
        self.assertEqual(snap(), without)
        self.assertEqual(self.entries(kind="breach"), [])
        self.assertNotIn("shadow", without[3])

    def test_refusals_never_count(self):
        """A refused answer is no breach (tribunal.py): a decision the
        validator refused neither breaches H1 nor acknowledges the miss,
        and a refused proposal acts on a signpost."""
        self.wake(1)
        self.missed(5)
        refused = self.decision(6, status="refused")
        self.refusal(6, refused)
        self.met(10)
        self.intent(11, "tighten", status="refused", mode="refused")
        self.dead()
        g = self.grade()
        self.assertEqual(self.entries(kind="breach"), [])
        self.assertFalse([t for t in g.tags if t.startswith("shadow_")])
        self.assertGreater(g.n_refused, 0, "counted elsewhere")
        [entry] = self.entries(kind="grade")
        self.assertNotIn("shadow", entry.body)

    def test_an_unreadable_record_still_grades_and_says_so(self):
        self.wake(1)
        self.met(5)
        self.dead()
        with patch("bot_program.orcs.honor.audit",
                   side_effect=RuntimeError("unread")):
            g = self.grade()
        self.assertIsNotNone(g)
        self.assertIn("honor_unread", g.tags)
        self.assertEqual(self.entries(kind="breach"), [])

    def test_the_audit_is_pure(self):
        """honor.audit reads what it is given: no query, no write."""
        from bot_program.orcs import dossier, honor
        from bot_program.orcs.models import (OrcIntent, OrcJournal,
                                             OrcTrack, OrcWake)
        self.wake(1)
        self.missed(5)
        self.decision(6)
        self.dead()
        entries = list(OrcJournal.objects.filter(orc=self.orc))
        intents = list(OrcIntent.objects.filter(orc=self.orc))
        wakes = list(OrcWake.objects.filter(orc=self.orc))
        o_arm = OrcTrack.objects.get(orc=self.orc, arm="orc_shadow")
        tf = dossier.decision_tf(self.orc)
        with self.assertNumQueries(0):
            found = honor.audit(entries=entries, intents=intents,
                                wakes=wakes, o_track=o_arm, decision_tf=tf,
                                died_at=self.orc.died_at)
        self.assertEqual([f["code"] for f in found], ["H1"])
        # plain dicts read the same
        def d(obj, *names):
            return {n: getattr(obj, n) for n in names}
        self.assertEqual(honor.audit(
            entries=[d(e, "id", "kind", "author", "fact_id", "body", "at",
                       "wake_id") for e in entries],
            intents=[d(i, "id", "kind", "created_at") for i in intents],
            wakes=[d(w, "id", "status", "created_at", "components")
                   for w in wakes],
            o_track=d(o_arm, "state", "open", "exit_r", "exit_at"),
            decision_tf=tf, died_at=self.orc.died_at), found)
        # nothing in it reaches the database
        tree = ast.parse(inspect.getsource(honor))
        imported = {n.module for n in ast.walk(tree)
                    if isinstance(n, ast.ImportFrom)}
        imported |= {a.name for n in ast.walk(tree)
                     if isinstance(n, ast.Import) for a in n.names}
        self.assertEqual({m for m in imported if m and (
            m.startswith("django") or m.endswith(("models", "journal")))},
            set())
        attrs = {n.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute)}
        self.assertEqual(attrs & {"objects", "save", "atomic",
                                  "select_for_update", "orc_lock"}, set())

    def test_the_orcs_own_dead_is_not_measured_in_o2(self):
        from bot_program.orcs import honor, validator
        doc = " ".join((honor.__doc__ or "").split())
        self.assertIn("not measured in O2", doc)
        self.assertIn("SCHEMA_V1", doc)
        self.assertNotIn("dead", validator.KEYS)
        self.assertEqual(honor.CODES, ("H1", "H2", "H3"))


class TheBreachWordsTests(_Record):

    def test_the_words_name_no_orc_act_and_fit_a_headline(self):
        from bot_program.orcs import honor, notes
        from bot_program.orcs.journal import HEADLINE_MAX
        self.wake(1)
        self.missed(5)
        self.decision(6)
        self.met(10)
        self.fact(47, {"arm": "orc_shadow", "exit_r": -1.25, "why": "x",
                       "tail_capped": False}, "The shadow arm exited.")
        self.dead(o_r=-1.25, mode="would", o_exit_hours=47)
        found = self.findings()
        self.assertEqual([f["code"] for f in found], ["H1", "H2", "H3"])
        texts = [f["t"] for f in found] + list(honor.WORDS.values())
        for text in texts:
            self.assertLessEqual(len(text), HEADLINE_MAX)
            self.assertIsNone(VERB.search(text), text)
            for s in re.split(r"(?<=[.!?])\s+", text):
                if ORC_WORD.search(s):
                    self.assertTrue(notes.is_reserved(s), s)


# ── honor sends no request ───────────────────────────────────────────────

class HonorSendsNoRequestTests(MindFixture):

    def test_honor_sends_no_request_across_the_grade(self):
        """The positive control, one wake read by the fake model; then the
        idea's grade, with honor's audit over that record: no request."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import grading
        from bot_program.orcs.models import Orc, OrcTrack
        w = self.claim(self.rendered())
        self.think(w, fake_answer(answer()))
        self.assert_one_call()
        for t in OrcTrack.objects.filter(orc=self.orc):
            OrcTrack.objects.filter(pk=t.pk).update(
                open=False, exit_r=0.2, exit_price=Decimal("100.7"),
                exit_at=NOW + timedelta(hours=1), exit_why="x")
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            status="CLOSED", outcome="stopped_out", pnl=Decimal("1"),
            exit_price=Decimal("100.7"), closed_at=NOW + timedelta(hours=1))
        Orc.objects.filter(pk=self.orc.pk).update(
            state="dead", died_at=NOW + timedelta(hours=1))
        self.orc.refresh_from_db()
        self.assertEqual(grading.shadow_findings(self.orc), [])
        g = grading.grade(self.orc, now=NOW + timedelta(hours=2))
        self.assertIsNotNone(g)
        self.assertEqual(g.n_llm, 1)
        self.assert_no_call()


# ── the Orc page ─────────────────────────────────────────────────────────

class TheBreachesOnThePageTests(_Record):

    def _page(self):
        self.client.force_login(self.user)
        return self.client.get(reverse("orc_detail", args=[self.row.pk])
                               ).content.decode()

    def test_the_page_shows_the_breaches_by_code_only_when_present(self):
        self.wake(1)
        self.met(5)
        self.dead()
        self.grade()
        html = self._page()
        self.assertIn("Shadow breaches (in shadow, none binds): H2 an "
                      "unacted signpost.", html)

    def test_a_breach_free_page_says_nothing_of_them(self):
        self.wake(1)
        self.dead()
        self.grade()
        html = self._page()
        self.assertNotIn("Shadow breach", html)
