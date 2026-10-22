"""THE PLAYBOOK (bot_program/orcs/playbook.py, spec §5.4): pure, unordered,
and in O1 nothing that adds risk.

Run with:  python manage.py test tests.orcs.test_orc_playbook
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.test import SimpleTestCase

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=dt_tz.utc)
ATR = {"1h": 1.0, "4h": 2.0}


def _swing(lid, tf, price, stop, origin, side="below"):
    return {"id": lid, "kind": "swing", "tf": tf, "price": price,
            "stop": stop, "side": side, "origin": origin}


ROWS = [
    _swing("S1h-L1", "1h", 101.5, 101.0, 300),
    _swing("S1h-L2", "1h", 100.8, 100.3, 200),
    _swing("S4h-L1", "4h", 103.0, 102.2, 100),
    _swing("S4h-L2", "4h", 101.0, 100.0, 50),
    {"id": "CARE", "kind": "care_soft_stop", "tf": "4h", "price": 100.2},
    {"id": "BE", "kind": "breakeven_plus_cost", "tf": "4h", "price": 100.1},
]


class TheStructureTrailTests(SimpleTestCase):

    def test_structure_from_r_is_simulates(self):
        from backtester.proving.simulate import STRUCTURE_FROM_R

        from bot_program.orcs import playbook
        self.assertEqual(playbook.STRUCTURE_FROM_R, STRUCTURE_FROM_R)

    def test_t_struct_half_r_1h_then_4h_from_2r(self):
        from bot_program.orcs.playbook import t_struct
        self.assertIsNone(t_struct(ROWS, side="BUY", mfe_r=0.4, p=103.0,
                                   m=102.9, effective=100.2, atr=ATR))
        low = t_struct(ROWS, side="BUY", mfe_r=1.2, p=103.0, m=102.9,
                       effective=100.2, atr=ATR)
        self.assertEqual((low["tf"], low["level_id"], low["stop"]),
                         ("1h", "S1h-L1", 101.0), "the latest 1h swing")
        high = t_struct(ROWS, side="BUY", mfe_r=2.5, p=106.0, m=105.9,
                        effective=100.2, atr=ATR)
        self.assertEqual((high["tf"], high["level_id"]), ("4h", "S4h-L1"))

    def test_t_struct_beyond_the_pool_with_room_only_tighter(self):
        from bot_program.orcs.playbook import t_struct
        self.assertIsNone(t_struct(ROWS, side="BUY", mfe_r=1.2, p=101.3,
                                   m=101.2, effective=100.2, atr=ATR),
                          "under 0.5 x ATR(1h) of room on p")
        self.assertIsNone(t_struct(ROWS, side="BUY", mfe_r=1.2, p=103.0,
                                   m=101.3, effective=100.2, atr=ATR),
                          "the closing side has no room either")
        self.assertIsNone(t_struct(ROWS, side="BUY", mfe_r=1.2, p=103.0,
                                   m=102.9, effective=101.2, atr=ATR),
                          "only if tighter than the effective stop")
        self.assertIsNone(t_struct(ROWS, side="BUY", mfe_r=1.2, p=109.0,
                                   m=108.9, effective=100.2, atr=ATR),
                          "never further than 3 x ATR(4h) from the mark")
        short = [_swing("S1h-H1", "1h", 98.5, 99.0, 300, side="above")]
        got = t_struct(short, side="SELL", mfe_r=1.0, p=97.0, m=97.1,
                       effective=99.8, atr=ATR)
        self.assertEqual(got["stop"], 99.0)

    def test_t_care_h_hold_always(self):
        from bot_program.orcs.playbook import candidates
        ids = [c.id for c in candidates([], {})]
        self.assertEqual(ids, ["H-HOLD", "T-CARE"])
        care = [c for c in candidates(ROWS, {}) if c.id == "T-CARE"][0]
        self.assertEqual(care.level_ids, ("CARE",))

    def test_k_draw_paper_or_two_legs(self):
        from bot_program.orcs.playbook import k_draw
        draw = {"price": 104.0, "touches": 2}
        self.assertEqual(k_draw(side="BUY", m=103.2, draw=draw, atr4h=2.0,
                                paper=True)["level_id"], "DRAW-104")
        self.assertIsNone(k_draw(side="BUY", m=103.2, draw=draw, atr4h=2.0,
                                 paper=False, legs=1), "a real single leg")
        self.assertIsNotNone(k_draw(side="BUY", m=103.2, draw=draw,
                                    atr4h=2.0, paper=False, legs=2))
        self.assertIsNone(k_draw(side="BUY", m=102.0, draw=draw, atr4h=2.0,
                                 paper=True), "too far from the draw")
        self.assertIsNone(k_draw(side="BUY", m=103.2, draw=draw, atr4h=2.0,
                                 paper=True, done=["DRAW-104"]), "once")

    def test_x_thesis_on_exit_verdict_or_met_predicate(self):
        from bot_program.orcs.playbook import x_thesis
        fresh = {"verdict": "exit", "at": (NOW - timedelta(hours=2))
                 .isoformat()}
        self.assertEqual(x_thesis(fresh, [], NOW)["why"],
                         "the thesis check reads exit")
        stale = {"verdict": "exit", "at": (NOW - timedelta(hours=30))
                 .isoformat()}
        self.assertIsNone(x_thesis(stale, [], NOW))
        self.assertIsNone(x_thesis({"verdict": "hold", "at": NOW.isoformat()},
                                   [{"state": "unmet"}], NOW))
        met = x_thesis({}, [{"state": "met", "kind": "close_beyond"}], NOW)
        self.assertIn("close_beyond", met["why"])

    def test_p_hold_only_when_gap_clears(self):
        from bot_program.orcs.playbook import candidates
        ctx = {"print": {"title": "US CPI m/m", "minutes": 90},
               "waiver": (False, "unmeasured", None)}
        ids = [c.id for c in candidates([], ctx)]
        self.assertIn("P-LOCK", ids)
        self.assertIn("P-TRIM", ids)
        self.assertNotIn("P-HOLD", ids)
        ctx["waiver"] = (True, "clears", 0.2)
        self.assertIn("P-HOLD", [c.id for c in candidates([], ctx)])
        ctx["print"] = {"title": "x", "minutes": 400}
        self.assertNotIn("P-LOCK", [c.id for c in candidates([], ctx)],
                         "beyond 3 h")

    def test_no_risk_adding_candidate_in_o1(self):
        from bot_program.orcs.playbook import RISK_ADDING, candidates
        ctx = {"side": "BUY", "mfe_r": 2.5, "p": 106.0, "m": 105.9,
               "effective": 100.2, "atr": ATR, "paper": True,
               "draw": {"price": 106.5}, "now": NOW,
               "thesis": {"verdict": "exit", "at": NOW.isoformat()},
               "print": {"title": "x", "minutes": 30},
               "waiver": (True, "", 0.1)}
        cands = candidates(ROWS, ctx)
        self.assertFalse({c.id for c in cands} & set(RISK_ADDING))
        self.assertFalse({c.action for c in cands} & {"add", "reenter",
                                                       "reverse", "widen"})

    def test_candidates_sorted_by_id_never_ranked(self):
        from bot_program.orcs.playbook import candidates
        ctx = {"side": "BUY", "mfe_r": 1.2, "p": 103.0, "m": 102.9,
               "effective": 100.2, "atr": ATR, "paper": True,
               "draw": {"price": 103.5}, "now": NOW,
               "thesis": {"verdict": "exit", "at": NOW.isoformat()}}
        ids = [c.id for c in candidates(ROWS, ctx)]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(set(ids), {"H-HOLD", "K-DRAW", "T-CARE", "T-STRUCT",
                                    "X-THESIS"})
