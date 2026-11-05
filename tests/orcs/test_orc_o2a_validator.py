"""T7, THE VALIDATOR AND WHAT A KEPT ANSWER WRITES (the O2 spec A.30-A.35,
A.39, A.46, A.47, A.58; §1.1.7 T7 and its extras; 2026-11-05).

- V1-V14, table-driven: one refused and one kept answer per rule, on a
  validation context and a facts index written by hand
- V2 over 24 hours and its urgency; V5 "none" for a lock waiver; V6 on a
  reached level and on a menu rebuilt under the same id; V7 at BE and
  never at CARE or EFF; V10 on a drum of another symbol and on another
  event's calendar fact; V11 outside Latin-1; V12 near the mark; V14
- every V-refusal journaled with its rule and counted (P20)
- a kept plan revision writes plan v1 with the stored references
- PS3 shows the LAST decision's expectation with its result (P25)
- bar, gap and expectation facts only while the minds are on (A.46)
- PS5 shows a refusal across a wake answered by code (P26), and pins the
  takeover while the care holds the position (A.47)
- the grade counts the mind and says "the Orc's shadow arm" in would mode
  (A.58)

Run with:  python manage.py test tests.orcs.test_orc_o2a_validator
"""
import copy
import json
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_call import NOW, MindFixture, answer

UTC = dt_tz.utc
T = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

#: A validation context as the render writes it (A.8): a long at 100,
#: risk 2 a unit, the mark at 101, ATR(1h) 1 and ATR(4h) 2.
VCTX = {
    "allowed": ["hold", "revise_plan", "tighten", "exit", "trim",
                "lock_waive", "add"],
    "why_not": [], "f5": [],
    "candidates": [{"id": "T-STRUCT", "action": "tighten",
                    "level_ids": ["S1h-L1"]},
                   {"id": "H-HOLD", "action": "hold", "level_ids": []}],
    "menu": [
        {"id": "S1h-L1", "kind": "swing", "tf": "1h", "side": "below",
         "price": 99.0, "stop": 98.8, "watchable": True},
        {"id": "S1h-L2", "kind": "swing", "tf": "1h", "side": "below",
         "price": 100.95, "stop": 100.8, "watchable": False},
        {"id": "P1h-H1", "kind": "pool", "tf": "1h", "side": "above",
         "price": 103.0, "stop": 103.2, "watchable": True},
        {"id": "RN-1", "kind": "round", "tf": "", "side": "above",
         "price": 102.0, "stop": 102.3, "watchable": True},
        {"id": "BE", "kind": "breakeven_plus_cost", "tf": "4h",
         "side": "", "price": 100.2, "stop": None, "watchable": False},
        {"id": "CARE", "kind": "care_soft_stop", "tf": "4h", "side": "",
         "price": 98.5, "stop": None, "watchable": True},
        {"id": "EFF", "kind": "effective_stop", "tf": "4h", "side": "",
         "price": 98.5, "stop": None, "watchable": True}],
    "events": {"C7": {"at": "2026-11-05T13:30:00+00:00", "ccy": "USD",
                      "kind": "print", "minutes": 90}},
    "gaps": {"C7": {"kind": "print", "n": 9, "p90_r": 0.2,
                    "measured": True}},
    "effective": 98.0, "atr": {"1h": 1.0, "4h": 2.0}, "p": 101.0,
    "m": 101.0, "mark_fresh": True, "thesis_intact": True,
    "plan_version": 0, "plan_at": None, "max_fact": 7, "world": "paper",
    "urgent": False, "army_type": "line", "decision_tf": "4h",
    "decision_bars": [], "symbol": "BTCUSD", "side": "BUY", "entry": 100.0,
    "rpu": 2.0, "cf": 0.004, "as_of": T.isoformat()}
#: The facts index (A.35).
FACTS = {
    "F1": {"kind": "structure", "symbol": "BTCUSD", "at": "a", "event": "",
           "drum_kind": "", "level": None},
    "F2": {"kind": "bar", "symbol": "BTCUSD", "at": "b", "event": "",
           "drum_kind": "", "level": None},
    "F3": {"kind": "level_reached", "symbol": "BTCUSD", "at": "c",
           "event": "", "drum_kind": "",
           "level": {"level_id": "P1h-H1", "kind": "pool", "tf": "1h",
                     "price": 103.0}},
    "F4": {"kind": "calendar", "symbol": "BTCUSD", "at": "d",
           "event": "C7", "drum_kind": "", "level": None},
    "F5": {"kind": "calendar", "symbol": "BTCUSD", "at": "e",
           "event": "C9", "drum_kind": "", "level": None},
    "DR1": {"kind": "drum", "symbol": "ETHUSD", "at": "f", "event": "",
            "drum_kind": "level_break", "level": None},
}


def check(ans=None, *, text=None, stop_reason="end_turn", vctx=None,
          facts=None, changes=(), version=0, plan_at=None, reasons=(),
          now=T):
    from bot_program.orcs import validator
    return validator.validate(
        json.dumps(ans) if text is None else text, stop_reason=stop_reason,
        vctx=vctx or VCTX, facts=FACTS if facts is None else facts,
        plan_changes=list(changes), plan_version=version, plan_at=plan_at,
        reasons=list(reasons), symbol="BTCUSD", side="BUY", now=now)


def with_vctx(**over):
    out = copy.deepcopy(VCTX)
    out.update(over)
    return out


def changes(*hours_ago):
    return [{"at": (T - timedelta(hours=h)).isoformat(), "urgent": False}
            for h in hours_ago]


PLAN = dict(action="revise_plan", facts_cited=["F1"],
            plan_clauses=[{"kind": "tighten", "level_id": "S1h-L1",
                           "trigger": "touch"}])
#: rule -> (a refused answer, a kept one): keyword arguments of `check`.
TABLE = {
    "V1": ({"text": '{"action": "hold"}'}, {"ans": answer()}),
    "V2": ({"ans": answer(**PLAN), "changes": changes(1, 2), "version": 1},
           {"ans": answer(**PLAN), "changes": changes(25, 26),
            "version": 1}),
    "V3": ({"ans": answer(action="add", level_id="S1h-L1",
                          risk_share="half", facts_cited=["F1"]),
            "vctx": with_vctx(allowed=["hold", "revise_plan"])},
           {"ans": answer()}),
    "V4": ({"ans": answer(action="exit", candidate="T-STRUCT",
                          level_id="P1h-H1", facts_cited=["F1", "F3"])},
           {"ans": answer(action="tighten", candidate="T-STRUCT",
                          level_id="S1h-L1", facts_cited=["F1"])}),
    "V5": ({"ans": answer(action="tighten", facts_cited=["F1"])},
           {"ans": answer(action="lock_waive", event_id="C7",
                          facts_cited=["F4"])}),
    "V6": ({"ans": answer(action="exit", level_id="P1h-H1",
                          facts_cited=["F1"])},
           {"ans": answer(action="exit", level_id="P1h-H1",
                          facts_cited=["F1", "F3"])}),
    "V7": ({"ans": answer(action="tighten", level_id="CARE",
                          facts_cited=["F1"])},
           {"ans": answer(action="tighten", level_id="S1h-L1",
                          facts_cited=["F1"])}),
    "V8": ({"ans": answer(action="trim", level_id="P1h-H1",
                          facts_cited=["F1", "F3"]),
            "vctx": with_vctx(f5=["the bars are stale"])},
           {"ans": answer(), "vctx": with_vctx(f5=["the bars are stale"])}),
    "V9": ({"ans": answer(next_wake_min=5)},
           {"ans": answer(next_wake_min=40)}),
    "V10": ({"ans": answer(action="tighten", level_id="S1h-L1",
                           facts_cited=["DR1"])},
            {"ans": answer(action="tighten", level_id="S1h-L1",
                           facts_cited=["F2"])}),
    "V11": ({"ans": answer(note="Держать позицию до уровня")},
            {"ans": answer(note="Holding: up 1.2R, the 4h swing intact.")}),
    "V12": ({"ans": answer(**{**PLAN, "plan_clauses": [
        {"kind": "tighten", "level_id": "S1h-L2", "trigger": "touch"}]})},
        {"ans": answer(**PLAN)}),
    "V13": ({"ans": answer(expectation={"kind": "closes_above",
                                        "level_id": "XX-9"})},
            {"ans": answer(expectation={"kind": "closes_above",
                                        "level_id": "RN-1"})}),
    "V14": ({"ans": answer(action="lock_waive", event_id="C9",
                           facts_cited=["F5"])},
            {"ans": answer(action="lock_waive", event_id="C7",
                           facts_cited=["F4"])}),
}


class TheRulesTests(MindTestCase):
    """V1-V14, one refused and one kept answer each (A.31, A.32)."""

    def test_every_rule_refuses_its_red_and_keeps_its_green(self):
        from bot_program.orcs.constants import V_PART, V_RULES
        self.assertEqual(list(TABLE), list(V_RULES))
        for rule, (red, green) in TABLE.items():
            with self.subTest(rule=rule):
                bad, good = check(**red), check(**green)
                self.assertTrue(bad["verdicts"][rule].startswith(
                    ("refused", "dropped", "withheld")), bad["verdicts"])
                self.assertIn(rule, [r["rule"] for r in bad["refusals"]])
                self.assertEqual(good["verdicts"][rule], "pass",
                                 good["verdicts"])
                self.assertEqual(good["status"], "done", good["refusals"])
                if rule in V_PART:
                    self.assertEqual(bad["status"], "done",
                                     "a part refusal keeps the rest")
                else:
                    self.assertEqual((bad["status"], bad["rule"]),
                                     ("refused", rule))

    def test_v1_reads_the_stop_and_the_shape(self):
        from bot_program.orcs.validator import WORDS
        cut = check(answer(), stop_reason="max_tokens")
        self.assertEqual(cut["refusals"][0]["words"], WORDS["V1_cut"])
        for text in ("", "[]", "not json", json.dumps({**answer(),
                                                       "reasoning": "x"}),
                     json.dumps({**answer(), "next_wake_min": True}),
                     json.dumps({**answer(), "action": "reverse"})):
            with self.subTest(text=text[:30]):
                self.assertEqual(check(text=text)["rule"], "V1")

    def test_v2_counts_the_last_24_hours_and_urgency(self):
        """P19: two changes 25 h ago pass; two inside 24 h refuse a third
        non-urgent change; an urgent wake may pass; a wake urgent only by
        its plan's own watch is not urgent here; the first plan is free."""
        urgent = [{"code": "W5", "urgent": True}]
        watch = [{"code": "W3", "urgent": True, "source": "plan"}]
        self.assertEqual(check(answer(**PLAN), changes=changes(25, 30),
                               version=2)["status"], "done")
        self.assertEqual(check(answer(**PLAN), changes=changes(1, 3),
                               version=2)["rule"], "V2")
        self.assertEqual(check(answer(**PLAN), changes=changes(1, 3),
                               version=2, reasons=urgent)["status"], "done")
        self.assertEqual(check(answer(**PLAN), changes=changes(1, 3),
                               version=2, reasons=watch)["rule"], "V2")
        self.assertEqual(check(answer(**PLAN), changes=changes(1, 3),
                               version=0)["status"], "done", "the first")

    def test_v6_on_a_menu_rebuilt_under_the_same_id(self):
        """P21: an old fact on an id that now names another pool fails."""
        moved = with_vctx(menu=[dict(lv, price=104.0) if lv["id"] == "P1h-H1"
                                else lv for lv in VCTX["menu"]])
        out = check(answer(action="exit", level_id="P1h-H1",
                           facts_cited=["F1", "F3"]), vctx=moved)
        self.assertEqual(out["rule"], "V6")
        broken = check(answer(action="exit", level_id="P1h-H1",
                              facts_cited=["F1", "F3"]),
                       vctx=with_vctx(thesis_intact=False))
        self.assertEqual(broken["verdicts"]["V6"], "pass",
                         "a broken thesis needs no reached level")

    def test_v7_puts_a_be_tighten_at_the_be_rows_price(self):
        # BE sits on the 4h frame: its room is 0.5 ATR(4h) from the mark
        out = check(answer(action="tighten", level_id="BE",
                           facts_cited=["F1"]),
                    vctx=with_vctx(p=102.0, m=102.0))
        self.assertEqual(out["status"], "done", out["refusals"])
        self.assertEqual(out["would_stop"], 100.2)
        self.assertEqual(out["level"], {"level_id": "BE",
                                        "kind": "breakeven_plus_cost",
                                        "tf": "4h", "price": 100.2,
                                        "stop": None})
        for lid in ("CARE", "EFF"):
            self.assertEqual(check(answer(action="tighten", level_id=lid,
                                          facts_cited=["F1"]))["rule"], "V7")
        near = check(answer(action="tighten", level_id="S1h-L2",
                            facts_cited=["F1"]))
        self.assertEqual(near["rule"], "V7", "no room from the mark")

    def test_v10_names_its_own_words_and_the_events(self):
        from bot_program.orcs.validator import WORDS
        drum = check(answer(action="tighten", level_id="S1h-L1",
                            facts_cited=["DR1"]))
        self.assertEqual(drum["rule"], "V10")
        self.assertNotIn("advisory to the phone",
                         json.dumps(drum["refusals"]))
        self.assertEqual(drum["refusals"][0]["words"], WORDS["V10"])
        other = check(answer(action="lock_waive", event_id="C7",
                             facts_cited=["F5"]))
        self.assertEqual(other["rule"], "V10", "another event's calendar")

    def test_v5_takes_none_for_a_waiver_and_a_market_exit(self):
        for ans in (answer(action="lock_waive", event_id="C7",
                           facts_cited=["F4"]),
                    answer(action="exit", facts_cited=["F1"])):
            self.assertEqual(check(ans, vctx=with_vctx(
                thesis_intact=False))["verdicts"]["V5"], "pass")

    def test_v11_withholds_money_and_keeps_r(self):
        from bot_program.orcs.validator import NOTE_WITHHELD
        out = check(answer(note="P/L -350 since entry"))
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["answer"]["note"], NOTE_WITHHELD)
        kept = check(answer(note="Holding: down 0.5R since entry."))
        self.assertEqual(kept["answer"]["note"],
                         "Holding: down 0.5R since entry.")


# ── what a kept or refused answer writes ─────────────────────────────────

class TheWritesTests(MindFixture):

    def _menu(self, w, *, watchable=True):
        return [lv for lv in w.components["vctx"]["menu"]
                if lv.get("kind") in ("swing", "pool", "round")
                and bool(lv.get("watchable")) == watchable]

    def _fact(self, kind):
        from bot_program.orcs.validator import facts_index
        w = self.base
        idx = facts_index(self.orc, as_of=NOW, vctx=w.components["vctx"])
        return [k for k, v in idx.items() if v["kind"] == kind]

    def setUp(self):
        super().setUp()
        self.base = self.rendered()

    def test_every_v_refusal_is_journaled_with_its_rule(self):
        """A.33, P20: a refusal entry per rule, its intent stored refused,
        and the refusals counted by the grade's counters."""
        from bot_program.orcs.grading import mind_counts
        from bot_program.orcs.models import OrcIntent
        drum = self._drum_on("ETHUSD")
        cases = {
            "V1": fake_answer(text="no json at all"),
            "V5": fake_answer(answer(action="tighten", level_id="XX-1")),
            "V9": fake_answer(answer(next_wake_min=3)),
            "V10": fake_answer(answer(action="tighten",
                                      level_id=self._tightenable(),
                                      facts_cited=[drum])),
            "V11": fake_answer(answer(note="Держать позицию до уровня")),
            "V13": fake_answer(answer(expectation={"kind": "closes_below",
                                                   "level_id": "XX-2"})),
            "V14": fake_answer(answer(event_id="C42")),
        }
        made = {}
        for rule, reply in cases.items():
            with self.subTest(rule=rule):
                w = made[rule] = self.copy_of(self.base)
                self.think(w, reply)
                refusals = self.entries(kind="refusal", wake=w)
                self.assertIn(rule, [e.body["rule"] for e in refusals])
                for e in refusals:
                    self.assertTrue(e.headline.startswith(
                        f"Refused by the validator ({e.body['rule']}): "),
                        e.headline)
        intent = OrcIntent.objects.get(wake=made["V10"])
        self.assertEqual(intent.kind, "tighten")
        self.assertEqual((intent.mode, intent.status), ("refused",
                                                        "refused"))
        self.assertEqual(mind_counts(self.orc)["n_refused"],
                         len(self.entries(kind="refusal")))

    def _drum_on(self, symbol):
        from bot_program.orcs import journal
        e = journal.append(self.orc, "drum", "DR: a level broke elsewhere.",
                           body={"fk": "drum", "drum_kind": "level_break",
                                 "symbol": symbol}, fact=True, id_prefix="DR",
                           at=NOW - timedelta(minutes=5))
        return e.fact_id

    def _tightenable(self):
        """A menu level a tighten may name on this render (V7's room)."""
        from bot_program.orcs import validator
        vctx = self.base.components["vctx"]
        for lv in vctx["menu"]:
            if lv.get("kind") in ("swing", "pool", "round") and \
                    lv.get("stop") is not None:
                stop, words = validator._v7(lv, vctx, "BUY")
                if not words:
                    return lv["id"]
        self.skipTest("no level of this menu leaves the stop room")

    def test_a_kept_plan_revision_writes_plan_v1_with_stored_references(
            self):
        """A.39: the plan, its version, its 24-hour list and its watches,
        every price copied from the wake's menu, and a plan entry drawn by
        code."""
        from bot_program.orcs.facts import px
        level = self._menu(self.base)[0]
        cite = self._fact("structure") or self._fact("venue")
        w = self.copy_of(self.base)
        self.think(w, fake_answer(answer(
            action="revise_plan", facts_cited=cite[:1],
            plan_clauses=[{"kind": "exit", "level_id": level["id"],
                           "trigger": "close_beyond"}],
            expectation={"kind": "closes_above", "level_id": level["id"]},
            note="Plan: exit beyond the level.")))
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.plan_version, 1)
        plan = self.orc.plan
        self.assertEqual(plan["v"], 1)
        clause = plan["clauses"][0]
        self.assertEqual({k: clause[k] for k in ("level_id", "kind", "tf",
                                                 "price", "stop")},
                         {"level_id": level["id"], "kind": level["kind"],
                          "tf": level["tf"], "price": level["price"],
                          "stop": level["stop"]})
        self.assertEqual(plan["expectation"]["level"]["price"],
                         level["price"])
        self.assertEqual(len(self.orc.plan_changes_24h), 1)
        self.assertEqual(self.orc.watches[0]["price"], level["price"])
        entry = self.entries(kind="plan")[-1]
        self.assertEqual(entry.author, "orc")
        self.assertEqual(entry.headline, f"Plan v1 in shadow: exit at "
                         f"{level['id']} ({px(self.row, level['price'])}) on "
                         f"a close beyond; expects a close above "
                         f"{level['id']} ({px(self.row, level['price'])}).")
        self.assertEqual(entry.body["plan"]["decision"],
                         self.entries(kind="decision")[-1].pk)

    def test_ps3_shows_the_last_decisions_expectation_and_its_result(self):
        """P25: three decisions; PS3 shows the THIRD one's expectation,
        pending until its bar is final, then its result."""
        from bot_program.orcs import dossier_position, journal
        levels = self._menu(self.base) + self._menu(self.base,
                                                    watchable=False)
        made = []
        for i, lv in enumerate(levels[:3]):
            ref = {"level_id": lv["id"], "kind": lv["kind"], "tf": lv["tf"],
                   "price": lv["price"], "stop": lv["stop"]}
            made.append(journal.append(
                self.orc, "decision", "Decision in shadow: hold.",
                author="orc", at=NOW + timedelta(minutes=i),
                body={"answer": {"action": "hold"},
                      "expectation": {"kind": "closes_below",
                                      "level": ref}}))
        ps3 = dossier_position._ps3(self.orc, {})
        last = ps3["last_expectation"]
        self.assertEqual(last["result"], "pending")
        self.assertIn(levels[2]["id"], last["words"])
        journal.append(self.orc, "fact", "The expectation set at x was met.",
                       fact=True, at=NOW + timedelta(hours=4),
                       body={"fk": "expectation", "decision": made[2].pk,
                             "result": "hit"})
        journal.append(self.orc, "fact", "An older one was missed.",
                       fact=True, at=NOW + timedelta(hours=4),
                       body={"fk": "expectation", "decision": made[1].pk,
                             "result": "missed"})
        self.assertEqual(dossier_position._ps3(self.orc, {})[
            "last_expectation"]["result"], "hit")

    def test_the_evidence_facts_are_written_only_while_the_minds_are_on(
            self):
        """A.46: with the minds off the journal stays O1's; on, the gap of
        a print within PRINT_WITHIN_H, the final decision bar of a W2 wake
        and an earlier decision's expectation are facts with their fk."""
        from bot_program.orcs import journal
        from bot_program.orcs.models import OrcJournal
        from tests.orcs.helpers import _switch
        from tests.orcs.test_orc_dossier import _print
        _print("Core CPI m/m", NOW + timedelta(minutes=90))
        lv = self._menu(self.base)[0]
        journal.append(self.orc, "decision", "Decision in shadow: hold.",
                       author="orc", at=NOW - timedelta(hours=9),
                       body={"answer": {"action": "hold"},
                             "expectation": {"kind": "closes_above",
                                             "level": {
                                                 "level_id": lv["id"],
                                                 "kind": lv["kind"],
                                                 "tf": lv["tf"],
                                                 "price": lv["price"],
                                                 "stop": lv["stop"]}}})
        w2 = {"code": "W2", "key": "W2:4h:x", "t": "4h bar closed",
              "urgent": False}

        def fks():
            return sorted({(e.body or {}).get("fk") for e in
                           OrcJournal.objects.filter(
                               orc=self.orc, body__fk__in=(
                                   "bar", "gap", "expectation",
                                   "level_reached"))})
        before = fks()
        _switch("orcs_minds", False)
        self.rendered(reasons=[w2], at=NOW + timedelta(minutes=10))
        self.assertEqual(fks(), before, "the minds off: O1's journal")
        _switch("orcs_minds", True)
        self.rendered(reasons=[w2], at=NOW + timedelta(minutes=20))
        got = fks()
        for fk in ("bar", "gap", "expectation"):
            self.assertIn(fk, got)
        gap = OrcJournal.objects.filter(orc=self.orc, body__fk="gap").first()
        self.assertTrue(gap.fact_id.startswith("F"))
        self.assertRegex(gap.body["event"], r"^C\d+$", "a code id, no title")
        self.assertNotIn("CPI", gap.headline)

    def test_level_reached_once_per_level_by_its_reference(self):
        """A.46, P21: a final 1h venue bar since the last check that traded
        through a menu pool writes one level_reached fact; the same level
        again writes none; a later level under the same id at another
        price is a new fact. The memory keeps (kind, tf, price), never the
        id."""
        from bot_program.orcs import bars, evidence
        from bot_program.orcs.models import OrcJournal
        f1h = bars.frame(self.symbol, "1h", asset_class="crypto", now=NOW)
        end, _o, high, low, _c = evidence._final_rows(f1h, NOW)[-1]
        mid = round((high + low) / 2, 2)
        pool = {"id": "P1h-H1", "kind": "pool", "tf": "1h", "side": "above",
                "price": mid, "stop": mid + 0.2, "watchable": True}
        own = {"id": "BE", "kind": "breakeven_plus_cost", "tf": "4h",
               "price": mid, "stop": None, "watchable": False}
        vctx = {"menu": [pool, own]}

        def reached():
            return list(OrcJournal.objects.filter(
                orc=self.orc, body__fk="level_reached").order_by("id"))
        before = len(reached())
        self.orc.refresh_from_db()
        self.orc.seen = {**self.orc.seen,
                         "reached_at": (end - timedelta(hours=1))
                         .isoformat()}
        evidence._level_reached(self.orc, self.row, {}, vctx, NOW)
        got = reached()[before:]
        self.assertEqual(len(got), 1, "the pool, never BE")
        self.assertEqual((got[0].body["level_id"], got[0].body["price"],
                          got[0].body["kind"]), ("P1h-H1", mid, "pool"))
        self.assertTrue(got[0].fact_id.startswith("F"))
        self.orc.refresh_from_db()
        self.assertIn(evidence.level_key(pool), self.orc.seen["reached"])
        self.orc.seen = {**self.orc.seen,
                         "reached_at": (end - timedelta(hours=1))
                         .isoformat()}
        evidence._level_reached(self.orc, self.row, {}, vctx, NOW)
        self.assertEqual(len(reached()), before + 1, "once per level")
        moved = dict(pool, price=round(low + (high - low) / 4, 2))
        self.orc.refresh_from_db()
        self.orc.seen = {**self.orc.seen,
                         "reached_at": (end - timedelta(hours=1))
                         .isoformat()}
        evidence._level_reached(self.orc, self.row, {}, {"menu": [moved]},
                                NOW)
        self.assertEqual(len(reached()), before + 2,
                         "a new level under the same id is a new fact")

    def test_ps5_shows_a_refusal_across_a_wake_answered_by_code(self):
        """P26: a refusal at wake N, a code answer at N+1, and N+2's PS5
        still lists N's refusal with its rule."""
        from bot_program.orcs import dossier, dossier_position
        from bot_program.orcs.models import OrcWake
        w = self.copy_of(self.base)
        self.think(w, fake_answer(answer(action="tighten",
                                         level_id="XX-1")))
        coded = self.copy_of(self.base)
        OrcWake.objects.filter(pk=coded.pk).update(status="skipped",
                                                   skipped_reason="day_cap")
        ctx = dossier.context_for(self.orc, self.row, price="100.5", now=NOW)
        notes = dossier_position.ps5_notes(self.orc, ctx)
        text = " ".join(notes)
        self.assertIn("refused (V5)", text)
        self.assertTrue(all(n.startswith('<view source="orc"') for n in notes))

    def test_the_takeover_is_pinned_while_the_care_holds_the_position(self):
        """A.47: the takeover fact stays in PS5 even once twelve newer
        facts pushed it out."""
        from bot_program.orcs import dossier_position, journal
        from bot_program.orcs.models import Orc
        took = journal.append(self.orc, "takeover", "The care holds this "
                              "position: two refused answers.", fact=True,
                              body={"fk": "care", "reason": "x"},
                              at=NOW - timedelta(minutes=50))
        for i in range(14):
            journal.append(self.orc, "fact", f"A code fact {i}.", fact=True,
                           at=NOW - timedelta(minutes=40 - i))
        self.assertNotIn(took.fact_id, [f["id"] for f in
                                        dossier_position._ps5(self.orc)
                                        ["facts"]])
        Orc.objects.filter(pk=self.orc.pk).update(state="care_owned")
        self.orc.refresh_from_db()
        facts = dossier_position._ps5(self.orc)["facts"]
        self.assertEqual(facts[0]["id"], took.fact_id)
        self.assertTrue(facts[0]["pinned"])


# ── the grade counts the mind (A.58) ─────────────────────────────────────

class TheGradeOfTheMindTests(MindFixture):

    def test_the_counters_the_cost_the_tags_and_the_would_mode_line(self):
        from bot_program.orcs import journal
        from bot_program.orcs.grading import grade_line, mind_counts, \
            mind_tags
        from bot_program.orcs.models import OrcIntent, OrcWake
        base = self.rendered()
        for status in ("done", "refused", "late", "skipped", "quiet"):
            OrcWake.objects.create(orc=self.orc, reasons=[], status=status,
                                   dedupe_key=f"g{status}")
        for i, cost in enumerate(("0.040000", "0.030000")):
            journal.append(self.orc, "decision", "Decision in shadow: hold.",
                           author="orc", booking={"cost_usd": Decimal(cost),
                                                  "model": "m"},
                           body={"rung": "r0", "s_version": "s1",
                                 "schema_version": "d1"})
        journal.append(self.orc, "error", "The model call failed.",
                       booking={"cost_usd": Decimal("0.010000")})
        journal.append(self.orc, "refusal", "Refused by the validator (V5).",
                       body={"rule": "V5"})
        for result in ("hit", "missed", "hit"):
            journal.append(self.orc, "fact", "An expectation graded.",
                           fact=True, body={"fk": "expectation",
                                            "result": result})
        for clauses in ([1], [2], [1]):
            journal.append(self.orc, "plan", "Plan in shadow.", author="orc",
                           body={"plan": {"clauses": [
                               {"clause": "exit", "level_id": f"L{c}",
                                "price": c} for c in clauses]}})
        OrcIntent.objects.create(orc=self.orc, wake=base, kind="tighten",
                                 mode="shadow", status="simulated",
                                 rung="r0", s_version="s1",
                                 schema_version="d1")
        counts = mind_counts(self.orc)
        n_wakes = OrcWake.objects.filter(orc=self.orc).count()
        self.assertEqual((counts["n_wakes"], counts["n_llm"],
                          counts["n_actions"], counts["n_refused"]),
                         (n_wakes, 3, 1, 1))
        self.assertAlmostEqual(counts["invalid"], 1 / 3)
        self.assertAlmostEqual(counts["expectation_hit_rate"], 2 / 3)
        self.assertAlmostEqual(counts["flipflop_rate"], 1 / 3)
        self.assertEqual(counts["ai_cost_usd"], Decimal("0.08"))
        self.assertEqual(mind_tags(counts), ["s:s1", "schema:d1", "rung:r0",
                                             "invalid:0.33"])
        from types import SimpleNamespace
        nums = {"orc_r_gross": 0.8, "ghost_r": 1.1, "play_r": 0.9,
                "delta_care": -0.3}
        verdict = SimpleNamespace(fell="won", causes=[])
        line = grade_line(nums, verdict, would=True)
        self.assertEqual(line, "Graded in shadow: the Orc's shadow arm "
                               "+0.80R, the care ghost +1.10R, the playbook "
                               "+0.90R; Δ against the care -0.30R. Won.")
        from bot_program.orcs.notes import is_reserved
        self.assertTrue(is_reserved(line.rsplit(" Won.", 1)[0]),
                        "a sentence that names an Orc is registered")
        self.assertTrue(grade_line(nums, verdict).startswith(
            "Graded in shadow: the position +0.80R"))

    def test_the_ai_cost_lands_in_the_grade_in_the_orcs_currency(self):
        """A.58: the AI cost of the idea's decisions and errors, passed to
        the grade's numbers; an Orc in a currency with no rate keeps its
        net edge unknown, tagged."""
        from bot_program.orcs import journal
        from bot_program.orcs.grading import numbers
        from bot_program.orcs.models import Orc
        journal.append(self.orc, "decision", "Decision in shadow: hold.",
                       author="orc", booking={"cost_usd": Decimal("0.5")},
                       body={"rung": "r0", "s_version": "s1",
                             "schema_version": "d1"})
        with_cost = numbers(exits={"orc_shadow": 1.0, "care": 0.5},
                            r_money=100, ai_cost=0.5)
        self.assertAlmostEqual(with_cost["net_edge_money"], 49.5)
        self.assertAlmostEqual(with_cost["orc_r"], 0.995)
        Orc.objects.filter(pk=self.orc.pk).update(ccy="ZZZ")
        self.orc.refresh_from_db()
        from bot_program.orcs.grading import _usd_per
        self.assertIsNone(_usd_per("ZZZ"))
        self.assertEqual(_usd_per("USD"), 1.0)
        self.assertEqual(_usd_per(""), 1.0)
