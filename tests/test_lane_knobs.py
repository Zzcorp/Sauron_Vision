"""The manual lane's own knobs, set on its card behind the trading PIN
(2026-10-31).

Three keys of the manual config's extras decide how big one hand-taken
ticket is: risk_per_trade_pct (the default size; 0.25% when absent),
max_single_position_pct (the lane's own MAX SINGLE POSITION,
lane_single_position_pct) and max_notional_fraction (the lane's notional
cap, sizing.max_notional_fraction). Only a Django shell could set them;
the HQ asset-bot form rewrites the whole row and refuses crypto.

WHAT THESE TESTS CONFRONT

  * set_lane_knobs sets, clears (back to the default) and leaves alone,
    within bounds: risk above 0 and at most the 7% ceiling, the single
    position above 0 and at most 100, the notional cap above 0 and at
    most the widest the class table carries. Every number is checked
    before the PIN is asked; then the PIN, whatever the lane's mode.
  * One audit row per save that changed something, before and after.
  * The values reach sizing; the defaults are unchanged when nothing is
    set.
  * The view is an ACT door: the right PIN saves, a wrong one is counted
    and saves nothing; the card renders the form, and each row's refusal
    lands beside its own button, named by its lane.

Run with:  python manage.py test tests.test_lane_knobs
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tests.test_switch_pin import TEST_PIN, WRONG_PIN, _set_pin


class _Gate:
    """A PIN verdict that counts how often it is asked."""

    def __init__(self, ok=True):
        self.ok, self.asked = ok, 0

    def __bool__(self):
        self.asked += 1
        return self.ok


class SetLaneKnobsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("kn_u", password="x")

    def _set(self, knobs, gate=None, cls="stock"):
        from bot_program.manual_trade import set_lane_knobs
        gate = _Gate() if gate is None else gate
        return set_lane_knobs(self.user, asset_class=cls, knobs=knobs,
                              pin_ok=gate, who="kn_u"), gate

    def _cfg(self, cls="stock"):
        from bot_program.manual_trade import manual_config_for
        return manual_config_for(self.user, cls)

    def test_the_three_knobs_land_and_reach_sizing(self):
        from bot_program.asset_engine.sizing import (max_notional_fraction,
                                                     risk_fraction)
        from bot_program.manual_trade import lane_single_position_pct
        out, gate = self._set({"risk_per_trade_pct": "1.5",
                               "max_single_position_pct": 35,
                               "max_notional_fraction": "0.6"})
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["changed"])
        self.assertEqual(gate.asked, 1)
        cfg = self._cfg()
        self.assertEqual(cfg.extras["risk_per_trade_pct"], 1.5)
        self.assertAlmostEqual(risk_fraction(cfg), 0.015)
        self.assertEqual(lane_single_position_pct(cfg), 35.0)
        self.assertEqual(max_notional_fraction(cfg, "stock"), 0.6)

    def test_blank_clears_a_knob_and_absent_leaves_it(self):
        self._set({"risk_per_trade_pct": "2", "max_notional_fraction": "0.5"})
        out, _ = self._set({"risk_per_trade_pct": ""})
        self.assertTrue(out["changed"])
        cfg = self._cfg()
        self.assertNotIn("risk_per_trade_pct", cfg.extras)
        self.assertEqual(cfg.extras["max_notional_fraction"], 0.5)

    def test_the_bounds_and_the_ceiling(self):
        from bot_program.asset_engine.sizing import MAX_RISK_FRACTION
        for knobs, words in (
                ({"risk_per_trade_pct": MAX_RISK_FRACTION * 100 + 0.01},
                 "at most 7"),
                ({"risk_per_trade_pct": 0}, "must be above 0"),
                ({"max_single_position_pct": 101}, "at most 100"),
                ({"max_notional_fraction": 4.5}, "at most 4"),
                ({"max_notional_fraction": "-1"}, "must be above 0"),
                ({"risk_per_trade_pct": "lots"}, "must be a number"),
                ({"risk_per_trade_pct": True}, "must be a number"),
                ({"risk_per_trade_pct": float("nan")}, "must be above 0"),
                ({"leverage": 5}, "Unknown knob")):
            with self.subTest(knobs=knobs):
                out, gate = self._set(knobs)
                self.assertIn(words, out.get("error", ""), out)
                # a typo never costs a PIN attempt
                self.assertEqual(gate.asked, 0)
        self.assertEqual(self._cfg().extras or {}, {})
        out, _ = self._set({"risk_per_trade_pct": MAX_RISK_FRACTION * 100})
        self.assertTrue(out["ok"], out)

    def test_no_pin_saves_nothing_whatever_the_mode(self):
        out, gate = self._set({"risk_per_trade_pct": "1"}, _Gate(ok=False))
        self.assertIn("takes the trading PIN", out["error"])
        self.assertEqual(gate.asked, 1)
        self.assertNotIn("risk_per_trade_pct", self._cfg().extras or {})

    def test_one_audit_row_per_change_with_before_and_after(self):
        from bot_program.audit import LANE_KNOBS_SET
        from bot_program.audit_models import AuditLogEntry
        self._set({"max_single_position_pct": "30"})
        self._set({"max_single_position_pct": "30"})        # no change
        self._set({"max_single_position_pct": ""})
        rows = list(AuditLogEntry.objects.filter(kind=LANE_KNOBS_SET)
                    .order_by("id"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].data["before"]["max_single_position_pct"],
                         None)
        self.assertEqual(rows[0].data["after"]["max_single_position_pct"],
                         30.0)
        self.assertEqual(rows[1].data["after"]["max_single_position_pct"],
                         None)
        self.assertEqual(rows[0].data["who"], "kn_u")
        self.assertEqual(rows[0].data["asset_class"], "stock")
        self.assertLessEqual(len(LANE_KNOBS_SET), 20)

    def test_the_defaults_are_unchanged_when_nothing_is_set(self):
        from bot_program.asset_engine.sizing import (DEFAULT_RISK_FRACTION,
                                                     MAX_NOTIONAL_FRACTION,
                                                     risk_fraction)
        from bot_program.manual_trade import (lane_knob_defaults,
                                              lane_knobs,
                                              lane_single_position_pct)
        cfg = self._cfg("crypto")
        self.assertEqual(lane_knobs(cfg), {"risk_per_trade_pct": None,
                                           "max_single_position_pct": None,
                                           "max_notional_fraction": None})
        self.assertEqual(risk_fraction(cfg), DEFAULT_RISK_FRACTION)
        self.assertIsNone(lane_single_position_pct(cfg))
        d = lane_knob_defaults(cfg)
        self.assertEqual(d["risk_per_trade_pct"], 0.25)
        self.assertEqual(d["max_notional_fraction"],
                         MAX_NOTIONAL_FRACTION["crypto"])

    def test_a_user_config_named_manual_with_symbols_is_refused(self):
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.create(user=self.user, asset_class="forex",
                                      name="manual", symbols=["EURUSD"])
        out, gate = self._set({"risk_per_trade_pct": "1"}, cls="forex")
        self.assertIn("rename that bot first", out["error"])
        self.assertEqual(gate.asked, 0)

    def test_an_unknown_class_is_refused(self):
        out, _ = self._set({"risk_per_trade_pct": "1"}, cls="options")
        self.assertIn("Unknown asset class", out["error"])


class TheKnobsDoorTests(TestCase):

    URL = "/take-trade/lane-knobs/"

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()
        self.admin = get_user_model().objects.create_superuser(
            "kn_admin", "kn_admin@example.test", "pw-of-the-test")
        _set_pin(self.admin)
        self.client.force_login(self.admin)

    def _post(self, body):
        return self.client.post(self.URL, json.dumps(body),
                                content_type="application/json").json()

    def test_the_right_pin_saves_and_the_wrong_one_saves_nothing(self):
        from bot_program.manual_trade import manual_config_for
        from core.trading_pin import ATTEMPTS_KEY
        out = self._post({"asset_class": "crypto", "pin": WRONG_PIN,
                          "risk_per_trade_pct": "1"})
        self.assertIn("Incorrect trading PIN", out["error"])
        self.assertIn("nothing was saved", out["error"])
        self.assertTrue(out["pin_required"])
        self.assertEqual(self.client.session.get(ATTEMPTS_KEY), 1)
        self.assertNotIn("risk_per_trade_pct",
                         manual_config_for(self.admin, "crypto").extras or {})
        out = self._post({"asset_class": "crypto", "pin": TEST_PIN,
                          "risk_per_trade_pct": "1",
                          "max_notional_fraction": ""})
        self.assertTrue(out["ok"], out)
        self.assertEqual(manual_config_for(self.admin, "crypto")
                         .extras["risk_per_trade_pct"], 1.0)

    def test_a_bad_number_never_reaches_the_pin(self):
        from core.trading_pin import ATTEMPTS_KEY
        out = self._post({"asset_class": "crypto", "pin": WRONG_PIN,
                          "risk_per_trade_pct": "9"})
        self.assertIn("at most 7", out["error"])
        self.assertFalse(self.client.session.get(ATTEMPTS_KEY))

    def test_only_a_post_and_a_json_object(self):
        self.assertEqual(self.client.get(self.URL).status_code, 405)
        r = self.client.post(self.URL, "[1]", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_the_card_renders_the_form_with_its_defaults(self):
        with patch("bot_program.capital_truth.account_equity",
                   return_value=None):
            html = self.client.get("/admin-dashboard/").content.decode()
        self.assertIn('data-knob-save="crypto"', html)
        self.assertIn('data-knob="risk_per_trade_pct"', html)
        self.assertIn('placeholder="default 0.25"', html)
        self.assertIn("take-trade/lane-knobs/", html)
        i = html.index("data-knob-save")
        script = html[i:]
        self.assertIn(".logged_out", script)
        self.assertIn("/wall/", script)

    def test_each_refusal_lands_beside_its_own_button(self):
        """The knobs wrote their refusals into the card's one line, below
        all four rows: on a 390x844 phone a refused COMMODITY save printed
        about 700 px under its button, off screen, naming no lane, and
        ARM LIVE's refusals moved down with it (review, 2026-10-31). Each
        row has its own line now, named by its lane, scrolled into view;
        the arm line sits under the arm table again, and a refused PIN is
        cleared so a second tap cannot cost another attempt."""
        with patch("bot_program.capital_truth.account_equity",
                   return_value=None):
            html = self.client.get("/admin-dashboard/").content.decode()
        lanes = ("commodity", "crypto", "forex", "stock")
        for n, cls in enumerate(lanes):
            with self.subTest(cls=cls):
                row = html[html.index(f'data-knobs-row="{cls}"'):]
                if n + 1 < len(lanes):
                    row = row[:row.index(
                        f'data-knobs-row="{lanes[n + 1]}"')]
                self.assertLess(row.index(f'data-knob-save="{cls}"'),
                                row.index(f'data-knob-msg="{cls}"'))
        self.assertLess(html.index("data-lane-msg"),
                        html.index("LANE KNOBS"))
        script = html[html.index(
            "document.querySelectorAll('[data-knob-save]')"):]
        script = script[:script.index("</script>")]
        self.assertIn("'[data-knob-msg=\"' + cls + '\"]'", script)
        self.assertIn("refused(line, cls.toUpperCase() + ': ' + res.error, "
                      "pinEl)", script)
        helper = html[html.index("function refused(el, text, pinEl)"):]
        helper = helper[:helper.index("\n  }")]
        self.assertIn("pinEl.value = ''", helper)
        self.assertIn("scrollIntoView", helper)
        arm = html[html.index("function post(body, cls)"):]
        arm = arm[:arm.index("window.location.reload();")]
        self.assertIn("refused(msg, cls.toUpperCase() + ': ' + res.error, "
                      "pinEl)", arm)
