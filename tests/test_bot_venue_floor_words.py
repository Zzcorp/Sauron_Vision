"""The venue floor's line in why_no_trade and preflight_live (2026-11-12).

One line under each bot, from one function (asset_engine/base
.venue_floor_words): the switch's state and the ceiling, or why the floor
does not apply to that config. Read-only: neither command writes anything
or asks a broker.

Run with:  python manage.py test tests.test_bot_venue_floor_words
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from tests import bot_venue_floor_harness as H


def _why() -> str:
    out = StringIO()
    call_command("why_no_trade", stdout=out)
    return out.getvalue()


def _under(text, name) -> list:
    """The lines printed under the config named `name` in section 4."""
    part = text.split("4. WHY EACH ENABLED CONFIG DID NOT OPEN", 1)[1]
    part = part.split("5. FUEL", 1)[0]
    lines, mine = part.splitlines(), []
    for i, line in enumerate(lines):
        if line.strip().endswith(f"] {name}"):
            for nxt in lines[i + 1:]:
                if nxt.strip().startswith("["):
                    break
                mine.append(nxt.strip())
    return mine


class TheWordsTests(TestCase):

    def test_the_one_sentence_for_every_state(self):
        from bot_program.asset_engine.base import venue_floor_words
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        live = H.arm("forex_under_min", "w")["cfg"]
        paper = H.arm("forex_paper_config", "w")["cfg"]
        off = ("venue floor OFF (bots_venue_floor_live): an order under "
               "the venue's smallest size is refused, as before")
        self.assertEqual(venue_floor_words(live), off)
        H.switch(H.SWITCH, False)
        self.assertEqual(venue_floor_words(live), off)
        H.switch(H.SWITCH, True)
        self.assertEqual(
            venue_floor_words(live),
            "venue floor ON: an order under eToro's smallest size opens at "
            "that size when it risks at most 2% of this pool (MAX BOT "
            "FLOOR RISK on /setup/); a bot with no multiplier of its own "
            "lets the chooser pick one for that entry")
        # the floor is eToro's alone: a live bot routed elsewhere is told
        # so, when the caller knows the route (preflight_live does)
        self.assertEqual(
            venue_floor_words(live, venue="oanda"),
            "venue floor does not apply: this class is routed to oanda, "
            "not eToro")
        self.assertEqual(
            venue_floor_words(live, venue=""),
            "venue floor does not apply: this class is routed to no venue, "
            "not eToro")
        self.assertIn("venue floor ON", venue_floor_words(live,
                                                          venue="etoro"))
        H.ceiling(1.5)
        self.assertIn("at most 1.5% of this pool", venue_floor_words(live))
        H.ceiling(25)
        self.assertEqual(
            venue_floor_words(live),
            "venue floor ON, and MAX BOT FLOOR RISK cannot be read: no "
            "order is raised until it is set on /setup/ (0.1 to 7)")
        self.assertEqual(
            venue_floor_words(paper),
            "venue floor does not apply: a paper bot has no venue minimum")
        live.name = MANUAL_CONFIG_NAME
        self.assertEqual(
            venue_floor_words(live),
            "venue floor does not apply: the hand ticket has its own "
            "smallest size")

    def test_why_no_trade_says_it_under_each_bot(self):
        live = H.arm("forex_under_min", "w")["cfg"]
        paper = H.arm("forex_paper_config", "w")["cfg"]
        text = _why()
        self.assertIn(
            "venue floor OFF (bots_venue_floor_live): an order under the "
            "venue's smallest size is refused, as before",
            _under(text, live.name))
        self.assertIn(
            "venue floor does not apply: a paper bot has no venue minimum",
            _under(text, paper.name))
        H.switch(H.SWITCH, True)
        self.assertIn(
            "venue floor ON: an order under eToro's smallest size opens at "
            "that size when it risks at most 2% of this pool (MAX BOT "
            "FLOOR RISK on /setup/); a bot with no multiplier of its own "
            "lets the chooser pick one for that entry",
            _under(_why(), live.name))
        # never a blocker: a switch that is off is a decision
        self.assertNotIn("venue floor", _why().split("=" * 66)[-2])

    def test_a_live_bot_no_etoro_account_carries_is_told_so(self):
        """The floor is eToro's alone. A live bot whose class no eToro row
        carries never reads "ON", in either command, whatever the switch
        (preflight_live has nothing to arm for an account with no broker
        row, and names that a blocker of its own)."""
        from django.contrib.auth import get_user_model
        from tests.test_preflight_live import _run
        user = get_user_model().objects.create_user("floor_noroute",
                                                    password="x")
        cfg = H._live_cfg(user, "forex", name="F noroute")
        for state in (None, True):
            H.switch(H.SWITCH, state)
            self.assertIn(
                "venue floor does not apply: this class is routed to no "
                "venue, not eToro", _under(_why(), cfg.name))
            self.assertNotIn("VENUE FLOOR ON", _run())

    def test_why_no_trade_shows_the_reason_inside_a_refusal(self):
        """The skip's own words carry why nothing was raised, inside the 88
        characters section 4 prints of a detail."""
        world = H.arm("forex_under_min", "w")
        H.switch(H.SWITCH, True)
        H.switch(H.LEVERAGE, True)
        H.ceiling(0.5)
        H.run(world)
        lines = _under(_why(), world["cfg"].name)
        self.assertIn(
            "last EURUSD     venue_min_size: this bot's smallest size "
            "would risk 0.81% of the pool, above your 0.5% ceiling (MAX "
            "BOT", lines)

    def test_preflight_live_says_it_under_each_live_config(self):
        from tests.test_preflight_live import _run
        world = H.arm("forex_under_min", "pf")
        text = _run()
        self.assertIn(
            "        VENUE FLOOR OFF (bots_venue_floor_live): an order "
            "under the venue's smallest size is refused, as before", text)
        H.switch(H.SWITCH, True)
        text = _run()
        self.assertIn(
            "        VENUE FLOOR ON: an order under eToro's smallest size "
            "opens at that size when it risks at most 2% of this pool (MAX "
            "BOT FLOOR RISK on /setup/)", text)
        self.assertNotIn("VENUE FLOOR", text.split("BLOCKERS")[-1]
                         if "BLOCKERS" in text else "")
        del world

    def test_preflight_live_says_the_multiplier_of_a_raised_entry(self):
        """A bot with no multiplier of its own: "the adapter sends 1" is
        the whole truth with the floor OFF. ON, an entry raised to the
        venue's smallest size lets the chooser pick: said on the leverage
        line, per instrument class with the most it may pick, and with
        the financing warning the attack mode carries. Never a blocker."""
        from tests.test_preflight_live import _run
        world = H.arm("forex_under_min", "pfl")
        H.switch(H.LEVERAGE, True)
        one = ("        leverage —  (no extras['leverage']; the adapter "
               "sends 1)")
        self.assertIn(one + "\n", _run())
        H.switch(H.SWITCH, True)
        text = _run()
        self.assertNotIn(one + "\n", text)
        self.assertIn(
            "        leverage —  (no extras['leverage']; the adapter sends "
            "1, except an entry raised to the venue's smallest size: the "
            "chooser picks its multiplier, up to MAX BOT LEVERAGE and the "
            "class ceiling)", text)
        self.assertIn("          forex: a raised entry goes at up to 30x, "
                      "on eToro's LIVE list and inside the stop band", text)
        name = world["cfg"].name
        self.assertIn(
            f"({name}): an entry raised to the venue's smallest size goes "
            f"at up to 30x on forex: financing (overnight/weekend fees on "
            f"a levered CFD) is charged by NOTHING here", text)
        self.assertNotIn("raised to the venue's smallest size",
                         text.split("WORTH READING")[0].split("BLOCKERS")[-1]
                         if "BLOCKERS" in text else "")
        # MAX BOT LEVERAGE bounds it; the live leverage switch OFF is 1x
        H.limit(max_bot_leverage=5)
        self.assertIn("          forex: a raised entry goes at up to 5x "
                      "(capped at 5x by MAX BOT LEVERAGE)", _run())
        H.switch(H.LEVERAGE, False)
        self.assertIn("          forex: a raised entry goes at up to 1x, "
                      "on eToro's LIVE list and inside the stop band "
                      "(etoro_leverage_live is OFF: every order goes at 1x)",
                      _run())
