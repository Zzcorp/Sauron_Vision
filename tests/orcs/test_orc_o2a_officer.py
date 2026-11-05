"""T9, THE OFFICER IN WOULD-MODE (the O2 spec A.36-A.38, A.41, A.47; P30,
P31; §1.1.7 T9 and its extras; 2026-11-05).

- allowed_actions: the L0 vocabulary, an add judged as if it bound, the
  army type's flags (a Mercenaries Orc has no lock waiver and no add, each
  with its why-not), F5's shrink; PS1 prints them with the events by code
- I2 gross (the exit cost at the stop, prior losses), I3 an add's facts and
  the root's stop at break-even, I3c break-even with its costs (BE differs
  from the entry when the cost fraction is above 0), I3h the gap, I4 the
  share cut then refused below a quarter, I5 adds left and exotic legs, I6
  before a shut, I12 the step budget and the bars since an add or a trim:
  each with its numbers in R
- I12's counters advance from accepted proposals only; PS4 shows every
  counter V2, I5 and I12 read; PS12 marks each row's watch and BE's cost
- a care_owned Orc's accepted proposals are recorded, never queued

Run with:  python manage.py test tests.orcs.test_orc_o2a_officer
"""
import copy
import json
from datetime import timedelta
from types import SimpleNamespace

from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_call import NOW, MindFixture, answer
from tests.orcs.test_orc_o2a_validator import VCTX

#: A long at 100, risk 2 a unit, its round trip 0.4% (BE at 100.4), the
#: mark at 102.
BASE = copy.deepcopy(VCTX)
BASE.update(p=102.0, m=102.0, cf=0.004, events={}, gaps={},
            decision_bars=["2026-11-05T00:00:00+00:00",
                           "2026-11-05T04:00:00+00:00",
                           "2026-11-05T08:00:00+00:00"])
for lv in BASE["menu"]:
    if lv["id"] == "BE":
        lv["price"] = 100.4
FACTS = {"F1": {"kind": "structure", "symbol": "BTCUSD", "at": "a",
                "event": "", "drum_kind": "", "level": None}}
DAY = "2026-11-05"


def orc(**over):
    """An Orc as the officer reads it (no database)."""
    out = SimpleNamespace(pk=None, army_type="line", army_why={}, seen={},
                          adds_used=0, symbol="BTCUSD", side="BUY",
                          plan_version=0, plan_changes_24h=[])
    for k, v in over.items():
        setattr(out, k, v)
    return out


def world(**over):
    out = {"side": "BUY", "entry": 100.0, "rpu": 2.0, "open_frac": 1.0,
           "eff_stop": 101.0, "banked_r": 0.0, "losses_r": 0.0,
           "cf": 0.004, "mode": "real", "open": True}
    out.update(over)
    return out


def judge(action="add", *, o=None, w=None, vctx=None, share=0.5,
          cited=("F1",), event_id="", legs=()):
    from bot_program.orcs import mandate
    return mandate.judge(o or orc(), action=action, vctx=vctx or BASE,
                         facts=FACTS, cited=list(cited), share=share,
                         event_id=event_id, world=w or world(), day=DAY,
                         exotic_legs=list(legs))


class TheAllowedListTests(MindTestCase):

    def test_line_adds_in_would_mode_and_a_mercenary_neither_adds_nor_waives(
            self):
        from bot_program.orcs import mandate
        allowed, why = mandate.allowed_actions(orc(), {"f5": False,
                                                       "mark_fresh": True})
        self.assertEqual(allowed, ["hold", "revise_plan", "tighten", "exit",
                                   "trim", "lock_waive", "add"])
        self.assertEqual(why, [mandate.WHY_L0, mandate.WHY_ADD,
                               mandate.WHY_NOT_O2])
        allowed, why = mandate.allowed_actions(orc(army_type="mercenaries"),
                                               {"f5": False})
        self.assertNotIn("lock_waive", allowed)
        self.assertNotIn("add", allowed)
        self.assertIn("lock_waive: not for Mercenaries", why)
        self.assertIn("add: not for Mercenaries", why)

    def test_f5_shrinks_as_o1_did_and_no_add_is_left_after_two(self):
        from bot_program.orcs import integrity, mandate
        for fresh in (True, False):
            mine, why = mandate.allowed_actions(
                orc(), {"f5": ["the bars are stale"], "mark_fresh": fresh})
            o1, _ = integrity.allowed_actions_l0(f5=["the bars are stale"],
                                                 mark_fresh=fresh)
            self.assertEqual(mine, o1)
            self.assertIn(mandate.WHY_F5_ADD, why)
        spent = orc(adds_used=1, seen={"officer": {"would_adds": 1}})
        allowed, why = mandate.allowed_actions(spent, {"f5": False})
        self.assertNotIn("add", allowed)
        self.assertIn("add: no add left (2 of 2 used or accepted)", why)


class TheWouldVerdictsTests(MindTestCase):
    """A.37, each rule with its numbers in R."""

    def test_i2_counts_the_exit_cost_at_the_stop_and_prior_losses(self):
        from bot_program.orcs import mandate
        below = world(eff_stop=99.0)
        risk = mandate.root_risk_r(below)
        self.assertAlmostEqual(risk, 0.5 + 99.0 * 0.004 / 2 / 2.0)
        self.assertGreater(risk, 0.5, "the exit's half spread at the stop")
        at_cost = mandate.root_risk_r(world())
        self.assertAlmostEqual(at_cost, 101.0 * 0.004 / 2 / 2.0)
        refused = judge(w=world(banked_r=-1.95, losses_r=1.95))
        self.assertEqual((refused["verdict"], refused["rule"]),
                         ("refuse", "I2"))
        self.assertAlmostEqual(refused["gross_r"], at_cost + 1.95)

    def test_i3_and_i3c_read_break_even_with_its_costs(self):
        """BE is the entry plus its round trip (100.4, not 100); I3c adds
        the exit's half spread at the mark. A root stop between the raw
        entry and BE is refused."""
        from bot_program.orcs import mandate
        be = mandate.break_even(BASE, world())
        self.assertAlmostEqual(be, 100.4 + 102.0 * 0.004 / 2)
        self.assertNotEqual(be, 100.0)
        between = judge(w=world(eff_stop=100.2))
        self.assertEqual(between["rule"], "I3")
        under_costs = judge(w=world(eff_stop=100.5))
        self.assertEqual(under_costs["rule"], "I3c")
        no_fact = judge(cited=())
        self.assertEqual(no_fact["rule"], "I3")
        self.assertEqual(judge()["verdict"], "allow")

    def test_i3h_refuses_an_unmeasured_gap_and_a_waiver_past_its_floor(self):
        ev = {"C7": {"at": "x", "ccy": "USD", "kind": "print",
                     "minutes": 60}}
        thin = dict(BASE, events=ev, gaps={"C7": {"kind": "print", "n": 3,
                                                  "p90_r": 0.2,
                                                  "measured": False}})
        self.assertEqual(judge(vctx=thin)["rule"], "I3h")
        self.assertEqual(judge("lock_waive", vctx=thin,
                               event_id="C7")["rule"], "I3h")
        deep = dict(BASE, events=ev, gaps={"C7": {"kind": "print", "n": 9,
                                                  "p90_r": 0.4,
                                                  "measured": True}})
        # the worst case at the stop 99.5 is -0.25R; less the gap -0.65R
        self.assertEqual(judge("lock_waive", vctx=deep, event_id="C7",
                               w=world(eff_stop=99.5))["rule"], "I3h")
        self.assertEqual(judge("lock_waive", vctx=deep, event_id="C7")
                         ["verdict"], "allow")

    def test_i4_cuts_the_share_then_refuses_it_below_a_quarter(self):
        cut = judge(share=1.0)
        self.assertEqual((cut["verdict"], cut["rule"], cut["share"]),
                         ("cut", "I4", 0.5), "Line adds at half size")
        uruk = judge(share=1.0, o=orc(army_type="uruk_hai"),
                     w=world(banked_r=-1.3, losses_r=1.3))
        room = 2.0 - (101.0 * 0.004 / 4 + 1.3)
        self.assertEqual(uruk["verdict"], "cut")
        self.assertAlmostEqual(uruk["share"], round(room, 4))
        small = judge(w=world(banked_r=-1.7, losses_r=1.7))
        self.assertEqual((small["verdict"], small["rule"]), ("refuse", "I4"))

    def test_i5_adds_left_and_exotic_legs(self):
        self.assertEqual(judge(o=orc(adds_used=2))["rule"], "I5")
        self.assertEqual(judge(o=orc(adds_used=1, seen={
            "officer": {"would_adds": 1}}))["rule"], "I5")
        corsair = orc(army_why={"overlay": "corsairs"})
        self.assertEqual(judge(o=corsair, legs=["ZAR"])["rule"], "I5")
        self.assertEqual(judge(legs=["ZAR"])["verdict"], "allow",
                         "Line takes an exotic add")

    def test_i6_no_add_near_a_shut(self):
        shut = dict(BASE, events={"SH2611061700": {
            "at": "x", "ccy": "", "kind": "shut", "minutes": 120}},
            gaps={"SH2611061700": {"kind": "weekend", "n": 20,
                                   "p90_r": 0.3, "measured": True}})
        self.assertEqual(judge(vctx=shut)["rule"], "I6")

    def test_i12_the_step_budget_and_the_bars_since_an_add_or_a_trim(self):
        bars = BASE["decision_bars"]
        four = orc(seen={"officer": {"day": DAY, "steps_today": 4}})
        self.assertEqual(judge("tighten", o=four)["rule"], "I12")
        yesterday = orc(seen={"officer": {"day": "2026-11-04",
                                          "steps_today": 4}})
        self.assertEqual(judge("tighten", o=yesterday)["verdict"], "allow",
                         "the budget resets at the trading-day roll")
        trimmed = orc(seen={"officer": {"last_trim_bar": bars[-1]}})
        self.assertEqual(judge("trim", o=trimmed)["rule"], "I12")
        self.assertEqual(judge("trim", o=orc(seen={"officer": {
            "last_trim_bar": bars[-2]}}))["verdict"], "allow")
        added = orc(seen={"officer": {"last_add_bar": bars[-2],
                                      "would_adds": 0}})
        self.assertEqual(judge(o=added)["rule"], "I12")
        self.assertEqual(judge(o=orc(seen={"officer": {
            "last_add_bar": bars[0]}}))["verdict"], "allow")

    def test_accept_advances_the_counters(self):
        from bot_program.orcs import mandate
        st = mandate.accept({}, action="tighten", day=DAY, bar="b1")
        st = mandate.accept(st, action="add", day=DAY, bar="b2")
        st = mandate.accept(st, action="trim", day=DAY, bar="b3")
        self.assertEqual(st, {"day": DAY, "steps_today": 1,
                              "last_add_bar": "b2", "would_adds": 1,
                              "last_trim_bar": "b3"})
        rolled = mandate.accept(st, action="tighten", day="2026-11-06",
                                bar="b4")
        self.assertEqual(rolled["steps_today"], 1)


# ── on a rendered wake ───────────────────────────────────────────────────

class TheOfficerOnAWakeTests(MindFixture):

    def setUp(self):
        from bot_program.models import AssetBotTrade
        super().setUp()
        meta = dict(self.row.metadata or {}, cost_fraction_charged=0.004)
        AssetBotTrade.objects.filter(pk=self.row.pk).update(metadata=meta)
        self.row.refresh_from_db()

    def _ps(self, w):
        from bot_program.orcs.models import OrcDossierBlock
        shared = int(w.components["shared"])
        ps = OrcDossierBlock.objects.get(hash=w.block_hashes[shared])
        tail = OrcDossierBlock.objects.get(hash=w.block_hashes[shared + 1])
        return (json.loads(ps.text.partition("\n")[2]),
                json.loads(tail.text.partition("\n")[2]))

    def _tighten(self, w):
        from bot_program.orcs import validator
        vctx = w.components["vctx"]
        for lv in vctx["menu"]:
            if lv.get("kind") in ("swing", "pool", "round") and \
                    lv.get("stop") is not None and \
                    not validator._v7(lv, vctx, "BUY")[1]:
                return lv["id"]
        self.skipTest("no level of this menu leaves the stop room")

    def _structure(self):
        from bot_program.orcs.validator import facts_index
        return [k for k, v in facts_index(self.orc, as_of=NOW).items()
                if v["kind"] in ("structure", "bar", "care")]

    def test_ps1_prints_the_officers_list_and_the_events_by_code(self):
        from tests.orcs.test_orc_dossier import _print
        ev = _print("Core CPI m/m", NOW + timedelta(minutes=90))
        ps, _tail = self._ps(self.rendered())
        ps1 = ps["ps1"]
        self.assertEqual(ps1["level"], "L0 shadow")
        self.assertIn("add", ps1["allowed_actions"])
        self.assertIn("add: judged by the officer as if binding, never "
                      "applied in O2", ps1["why_not"])
        self.assertEqual(ps1["events"], [f"C{ev.pk}: a USD print in 1 h "
                                         f"30 min"])
        self.assertNotIn("CPI", json.dumps(ps1))

    def test_ps12_marks_the_watch_and_bes_cost(self):
        """A.8, A.47: BE is the entry plus its round trip, so its R and its
        cost move with the cost fraction; each row says whether a clause
        may watch it."""
        w = self.rendered()
        _ps, tail = self._ps(w)
        rows = {r["id"]: r for r in tail["ps12"]["menu"]}
        self.assertEqual(rows["BE"]["cost"], "+0.20R")
        menu = {lv["id"]: lv for lv in w.components["vctx"]["menu"]}
        self.assertAlmostEqual(menu["BE"]["price"], 100.4)
        for lid, r in rows.items():
            self.assertEqual(r["watch"], "yes" if menu[lid]["watchable"]
                             else "no: too near the mark", lid)
        self.assertIn("no: too near the mark",
                      [r["watch"] for r in rows.values()])

    def test_ps4_shows_every_counter_the_refusals_read(self):
        from bot_program.orcs import dossier, dossier_position
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(adds_used=1, seen={
            **self.orc.seen, "officer": {"would_adds": 1, "steps_today": 3,
                                         "day": "2026-10-22"}})
        self.orc.refresh_from_db()
        ctx = dossier.context_for(self.orc, self.row, price="100.5",
                                  now=NOW)
        ps4 = dossier_position._ps4(self.orc, self.row, ctx)
        self.assertEqual(ps4["adds_left"], 0)
        self.assertEqual(ps4["plan_changes_left"], 2)
        self.assertEqual(ps4["steps_left_today"], 1)
        self.assertEqual((ps4["bars_since_add"], ps4["bars_since_trim"]),
                         ("— (none yet)", "— (none yet)"))
        self.assertEqual(ps4["loss"], "+0.00R")
        Orc.objects.filter(pk=self.orc.pk).update(army_type="mercenaries")
        self.orc.refresh_from_db()
        self.assertEqual(dossier_position._ps4(self.orc, self.row, ctx)[
            "adds_left"], 0)

    def test_the_counters_advance_from_accepted_proposals_only(self):
        """A.38, P30: an accepted tighten counts a step; a refused one, by
        the validator or the officer, counts nothing."""
        from bot_program.orcs.models import Orc
        base = self.rendered()
        lid = self._tighten(base)
        cite = self._structure()[:1]
        self.assertTrue(cite, "a structure fact to cite")
        self.think(self.copy_of(base), fake_answer(answer(
            action="tighten", level_id=lid, facts_cited=cite)))
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.seen["officer"]["steps_today"], 1)
        self.think(self.copy_of(base), fake_answer(answer(
            action="tighten", level_id="XX-1", facts_cited=cite)))
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.seen["officer"]["steps_today"], 1,
                         "a V-refused tighten counts nothing")
        Orc.objects.filter(pk=self.orc.pk).update(seen={
            **self.orc.seen, "officer": {**self.orc.seen["officer"],
                                         "steps_today": 4}})
        self.think(self.copy_of(base), fake_answer(answer(
            action="tighten", level_id=lid, facts_cited=cite)))
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.seen["officer"]["steps_today"], 4,
                         "an officer-refused tighten counts nothing")
        refusal = self.entries(kind="refusal")[-1]
        self.assertTrue(refusal.headline.startswith(
            "Would be refused by the officer (I12): "))

    def test_an_accepted_proposal_is_queued_with_its_stored_level(self):
        """A.41: one OrcIntent, its level copied from the wake's menu, its
        expiry INTENT_TTL_S after the validation, its id in
        seen["intents_queued"], the card's newest three rewritten."""
        from bot_program.orcs.models import OrcIntent
        base = self.rendered()
        lid = self._tighten(base)
        w = self.copy_of(base)
        self.think(w, fake_answer(answer(
            action="tighten", level_id=lid,
            facts_cited=self._structure()[:1])))
        it = OrcIntent.objects.get(wake=w)
        menu = {lv["id"]: lv for lv in base.components["vctx"]["menu"]}
        self.assertEqual((it.kind, it.mode, it.status),
                         ("tighten", "shadow", "queued"))
        self.assertEqual(it.level["price"], menu[lid]["price"])
        self.assertEqual(float(it.would_stop), menu[lid]["stop"])
        self.assertEqual((it.rung, it.s_version, it.schema_version),
                         ("r0", "s1", "d1"))
        self.assertAlmostEqual((it.expires_at - it.created_at)
                               .total_seconds(), 600, delta=5)
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.seen["intents_queued"], [it.pk])
        card = self.orc.card["intents"]
        self.assertEqual(card[-1]["mode"], "shadow")
        self.assertTrue(card[-1]["kind_t"].startswith(
            f"proposed in shadow: tighten to {lid} ("))
        entry = self.entries(kind="intent")[-1]
        self.assertTrue(entry.headline.startswith(
            f"Proposed in shadow: tighten to {lid} ("))

    def test_a_care_owned_orcs_accepted_proposals_are_recorded(self):
        """A.41, A.53: while the care holds the position, the would-world
        is the care's too: an accepted proposal is recorded, never
        queued."""
        from bot_program.orcs.models import Orc, OrcIntent
        base = self.rendered()
        lid = self._tighten(base)
        Orc.objects.filter(pk=self.orc.pk).update(state="care_owned")
        w = self.copy_of(base)
        self.think(w, fake_answer(answer(
            action="tighten", level_id=lid,
            facts_cited=self._structure()[:1])))
        it = OrcIntent.objects.get(wake=w)
        self.assertEqual((it.mode, it.status), ("shadow", "recorded"))
        self.assertIsNone(it.expires_at)
        self.orc.refresh_from_db()
        self.assertFalse(self.orc.seen.get("intents_queued"))
