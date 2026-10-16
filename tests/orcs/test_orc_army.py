"""THE ARMY TYPES, assigned and journaled (spec §1.6; the O1a part).

A type is real only where the job differs: each names what it changes
(`differs_by`), each is tighter than the mandate (§2), never looser, and
it is assigned by the measured situation, never by taste. O1 assigns and
journals; the types act from O2.

Run with:  python manage.py test tests.orcs.test_orc_army
"""
import ast
import inspect

from django.test import SimpleTestCase


def _sit(**kw):
    """A measured situation: a bot row, no persona, crypto, every ATR
    measured, nothing in deep water."""
    out = {"asset_class": "crypto", "manual": False, "persona": "",
           "hold_h": 72.0, "stop_distance": 2.0,
           "atr": {"1h": 1.0, "4h": 1.5, "1d": 4.0}, "spread": 0.05,
           "shuts": [], "crypto_weekend": False, "prints": 0,
           "exotic_legs": [], "gap_p90_r": None,
           "operator_horizon_h": None}
    out.update(kw)
    return out


def _hand(**kw):
    return _sit(manual=True, **kw)


ELITE = {"n": 25, "win_rate": 0.6, "avg_r": 0.3, "level": 2,
         "faults_in_block": 0}


class TheAssignmentTests(SimpleTestCase):

    def test_assignment_order(self):
        """Uruk-hai first (when its bar, rank and PIN hold), then
        Mercenaries, then Olog-hai, then Line."""
        from bot_program.orcs.army import assign
        scalp = _sit(persona="scalp")
        self.assertEqual(assign(scalp)["base"], "mercenaries")
        self.assertEqual(assign(scalp, lineage_record=ELITE,
                                privileges=frozenset({"uruk_hai"}))["base"],
                         "uruk_hai", "the privilege outranks the persona")
        # a scalp config with a two-week thesis horizon: Mercenaries first
        self.assertEqual(assign(_sit(persona="scalp",
                                     operator_horizon_h=400))["base"],
                         "mercenaries")
        self.assertEqual(assign(_sit(operator_horizon_h=400))["base"],
                         "olog_hai")

    def test_scalp_is_mercenaries_position_is_olog_hai_swing_or_none_is_line(self):
        from bot_program.orcs.army import assign
        a = assign(_sit(persona="scalp"))
        self.assertEqual(a["base"], "mercenaries")
        self.assertEqual(a["why"], ["the config wears the scalp persona"])
        self.assertEqual(assign(_sit(persona="position"))["base"],
                         "olog_hai")
        self.assertEqual(assign(_sit(persona="swing"))["base"], "line")
        none = assign(_sit())
        self.assertEqual(none["base"], "line")
        self.assertEqual(none["why"], ["the config wears no persona"])

    def test_a_hand_ticket_by_atr_bands(self):
        from bot_program.orcs.army import assign
        quick = assign(_hand(stop_distance=1.1, spread=0.08))
        self.assertEqual(quick["base"], "mercenaries")
        self.assertEqual(quick["why"], [
            "a hand ticket with a stop of 1.1 x ATR(1h) and a spread of "
            "0.08 x ATR(1h)"])
        self.assertEqual(assign(_hand(stop_distance=1.1, spread=0.2))["base"],
                         "line", "a wide spread is no quick strike")
        siege = assign(_hand(stop_distance=8.4))
        self.assertEqual(siege["base"], "olog_hai")
        self.assertEqual(siege["why"],
                         ["a hand ticket with a stop of 2.1 x ATR(1d)"])
        line = assign(_hand(stop_distance=2.4))
        self.assertEqual(line["base"], "line")
        self.assertEqual(line["why"],
                         ["a hand ticket with a stop of 1.6 x ATR(4h)"])
        wide = assign(_hand(stop_distance=6.0))
        self.assertEqual(wide["base"], "line")
        self.assertIn("4.0 x ATR(4h), outside every other type's band",
                      wide["why"][0])

    def test_unmeasured_atr_reads_line_with_its_reason(self):
        from bot_program.orcs.army import assign
        blind = assign(_hand(atr={"1h": None, "4h": None, "1d": None}))
        self.assertEqual(blind["base"], "line")
        self.assertEqual(blind["why"], [
            "no ATR is measured for this symbol: no venue or platform bars"])
        no_stop = assign(_hand(stop_distance=None))
        self.assertEqual(no_stop["base"], "line")
        self.assertEqual(no_stop["why"],
                         ["a hand ticket with no stop: nothing to measure"])
        part = assign(_hand(stop_distance=2.4,
                            atr={"1h": 1.0, "4h": None, "1d": 4.0}))
        self.assertEqual(part["base"], "line")
        self.assertIn("ATR(4h) is not measured", part["why"][0])

    def test_uruk_hai_needs_the_bar_the_rank_and_the_pin(self):
        from bot_program.orcs.army import assign
        pin = frozenset({"uruk_hai"})
        self.assertEqual(assign(_sit(), lineage_record=ELITE,
                                privileges=pin)["base"], "uruk_hai")
        self.assertEqual(assign(_sit(), lineage_record=ELITE)["base"],
                         "line", "no PIN, no privilege")
        for broken in ({"n": 19}, {"win_rate": 0.5}, {"avg_r": 0.1},
                       {"level": 1}, {"faults_in_block": 1}):
            with self.subTest(broken=broken):
                self.assertEqual(assign(_sit(),
                                        lineage_record={**ELITE, **broken},
                                        privileges=pin)["base"], "line")
        # O1 passes neither: unreachable
        self.assertEqual(assign(_sit())["base"], "line")

    def test_the_uruk_bar_is_the_elite_exceptions(self):
        from bot_program.orcs import constants as k
        from portfolio.risk_gate import (ELITE_MIN_AVG_R, ELITE_MIN_N,
                                         ELITE_MIN_WIN_RATE)
        self.assertEqual((k.URUK_MIN_N, k.URUK_MIN_WIN_RATE, k.URUK_MIN_AVG_R),
                         (ELITE_MIN_N, ELITE_MIN_WIN_RATE, ELITE_MIN_AVG_R))


class TheCorsairTests(SimpleTestCase):

    def test_corsair_on_overnight_weekend_and_holiday_shuts(self):
        from bot_program.orcs.army import assign, corsair_overlay
        for kind in ("overnight", "weekend", "holiday"):
            with self.subTest(kind=kind):
                sit = _sit(asset_class="stock", shuts=[
                    {"at": "2026-10-16T20:00:00+00:00",
                     "words": "Friday 20:00 UTC", "kind": kind,
                     "hours": 65.5}])
                on, why = corsair_overlay(sit)
                self.assertTrue(on)
                article = "an" if kind == "overnight" else "a"
                self.assertEqual(why, [f"{article} {kind} shut inside the "
                                       f"expected hold (Friday 20:00 UTC)"])
                a = assign(sit)
                self.assertEqual((a["base"], a["overlay"]),
                                 ("line", "corsairs"))
        brk = _sit(asset_class="commodity", shuts=[
            {"at": "2026-10-14T21:00:00+00:00", "words": "Wednesday 21:00 UTC",
             "kind": "break", "hours": 1.0}])
        self.assertEqual(corsair_overlay(brk), (False, []),
                         "a one-hour daily break is not deep water")

    def test_corsair_on_two_prints_exotic_pair_crypto_weekend_and_measured_gap(self):
        from bot_program.orcs.army import corsair_overlay
        self.assertEqual(corsair_overlay(_sit(prints=2)), (True, [
            "2 high-impact prints on its currencies inside the expected "
            "hold"]))
        self.assertEqual(corsair_overlay(_sit(prints=1)), (False, []))
        self.assertEqual(corsair_overlay(_sit(asset_class="forex",
                                              exotic_legs=["THB"])),
                         (True, ["an exotic pair: THB is outside the theme "
                                 "currencies"]))
        self.assertEqual(corsair_overlay(_sit(crypto_weekend=True)), (True, [
            "a crypto weekend inside the expected hold: thin books, no shut "
            "to wait behind"]))
        self.assertEqual(corsair_overlay(_sit(gap_p90_r=0.6)),
                         (True, ["a measured gap p90 of 0.60R"]))

    def test_an_unmeasured_gap_makes_no_corsair(self):
        from bot_program.orcs.army import corsair_overlay
        self.assertEqual(corsair_overlay(_sit(gap_p90_r=None)), (False, []))
        self.assertEqual(corsair_overlay(_sit(gap_p90_r=0.4)), (False, []))


class TheTypesTests(SimpleTestCase):

    def test_every_type_but_line_names_what_it_changes(self):
        from bot_program.orcs.army import ARMY_TYPES
        self.assertEqual(set(ARMY_TYPES), {"line", "mercenaries", "olog_hai",
                                           "uruk_hai", "corsairs"})
        self.assertEqual(ARMY_TYPES["line"].differs_by, ())
        for key, t in ARMY_TYPES.items():
            if key == "line":
                continue
            with self.subTest(key):
                self.assertTrue(t.differs_by)
                for param, step in t.differs_by:
                    self.assertTrue(hasattr(t, param), param)
                    self.assertNotEqual(getattr(t, param),
                                        getattr(ARMY_TYPES["line"], param),
                                        f"{key} claims to change {param}")
                    self.assertTrue(str(step).strip())
        self.assertTrue(ARMY_TYPES["corsairs"].overlay)
        self.assertFalse(ARMY_TYPES["mercenaries"].adds)
        self.assertFalse(ARMY_TYPES["mercenaries"].reentry)
        self.assertFalse(ARMY_TYPES["mercenaries"].lock_waiver)
        self.assertEqual(ARMY_TYPES["line"].risk_share_max, 0.5)
        self.assertEqual(ARMY_TYPES["uruk_hai"].risk_share_max, 1.0)
        self.assertEqual(ARMY_TYPES["olog_hai"].decision_tf, "1d")

    def test_a_type_with_no_step_cannot_register(self):
        from bot_program.orcs.army import ARMY_TYPES, ArmyType, register
        registry = dict(ARMY_TYPES)
        with self.assertRaises(ValueError):
            register(ArmyType("marines", "Marines"), registry=registry)
        # a declared step whose vector equals another type's is a merge
        twin = ArmyType("raiders", "Raiders",
                        differs_by=(("metronome_h", "1 h"),),
                        **{f: getattr(ARMY_TYPES["mercenaries"], f)
                           for f in ArmyType.VECTOR})
        with self.assertRaises(ValueError):
            register(twin, registry=registry)
        self.assertNotIn("marines", registry)
        self.assertNotIn("raiders", registry)

    def test_types_are_tighter_never_looser(self):
        from bot_program.orcs import constants as k
        from bot_program.orcs.army import ARMY_TYPES
        for key, t in ARMY_TYPES.items():
            with self.subTest(key):
                self.assertLessEqual(t.risk_share_max, max(k.RISK_SHARES))
                self.assertGreaterEqual(t.waiver_floor_r,
                                        k.EVENT_WAIVER_FLOOR_R)
                self.assertGreaterEqual(t.gap_min_samples, k.GAP_MIN_SAMPLES)
                self.assertGreaterEqual(t.add_pre_shut_h, k.ADD_PRE_SHUT_H)
                self.assertLessEqual(t.max_adds, k.MAX_ADDS)
                self.assertLessEqual(t.max_reentries, k.MAX_REENTRIES)

    def test_army_is_pure(self):
        from bot_program.orcs import army
        tree = ast.parse(inspect.getsource(army))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module or "")
        for m in modules:
            self.assertFalse(m.startswith("django"), m)
            self.assertNotIn("models", m, m)
            self.assertFalse(m.startswith("market_data"), m)
