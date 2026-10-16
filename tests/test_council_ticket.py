"""THE COUNCIL on the TAKE TRADE ticket (2026-10-08): hard rule 2.

A hand trade is never blocked by a voice. On a LIVE ticket the council is
advisory and on demand: only the "Ask the council" click runs it, never
the ticket's opening; a paper ticket is never argued; the trade's own
response is the execution's, and the sitting is linked to the trade only
AFTER it was taken.

Run with:  python manage.py test tests.test_council_ticket
"""
import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_council_sitting import switch

DELAY = "ai_agents.tasks.run_council_sitting.apply_async"
KEY = {"ANTHROPIC_API_KEY": "sk-test-not-a-key"}
TICKET = {"symbol": "BTCUSD", "side": "BUY", "stop": 59100, "target": 61800,
          "qty": 0.01, "entry": 60000, "leverage": 2, "signal_id": None}


def _etoro(user, *, demo):
    """An eToro row carrying the crypto lane, Demo ticked or not: the
    router then builds the EtoroTrader of that world (no network)."""
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(user=user, demo=demo,
                                       is_primary_for_crypto=True)
    acct.set_credentials("the-api-key", "the-user-key")
    acct.save()
    return acct


def _live_manual(user, asset_class="crypto", mode="live"):
    from bot_program.manual_trade import manual_config_for
    cfg = manual_config_for(user, asset_class)
    cfg.mode = mode
    cfg.save(update_fields=["mode"])
    return cfg


class TheAskTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ct_u", password="x")
        cls.other = get_user_model().objects.create_user("ct_o", password="x")
        cls.staff = get_user_model().objects.create_user(
            "ct_s", password="x", is_staff=True)

    def setUp(self):
        from tests.test_take_trade_live import _quote
        _quote("BTCUSD", 60000)
        self.cfg = _live_manual(self.user)
        # the venue the ticket fills through: eToro's real world (a lane
        # with no venue routes to the PaperTrader, which is no real money)
        self.acct = _etoro(self.user, demo=False)
        self.client.force_login(self.user)

    def _ask(self, body=None, **over):
        payload = dict(TICKET, **over) if body is None else body
        return self.client.post("/council/ask/", data=json.dumps(payload),
                                content_type="application/json")

    def test_off_the_council_says_so(self):
        from ai_agents.agents.council import OFF_WORDS
        resp = self._ask()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": False, "why": OFF_WORDS})

    def test_no_key_no_sitting(self):
        from ai_agents.agents.council import NO_KEY_WORDS
        switch("council_ticket")
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(self._ask().json()["why"], NO_KEY_WORDS)

    def test_a_paper_ticket_is_never_argued(self):
        from ai_agents.agents.council import PAPER_WORDS
        from ai_agents.council_models import CouncilSession
        switch("council_ticket")
        self.cfg.mode = "paper"
        self.cfg.save(update_fields=["mode"])
        with patch.dict("os.environ", KEY):
            self.assertEqual(self._ask().json()["why"], PAPER_WORDS)
            # a class with no manual lane at all reads as paper too
            from tests.test_take_trade_live import _quote
            _quote("EURUSD", "1.10", asset_class="forex")
            self.assertEqual(self._ask(symbol="EURUSD").json()["why"],
                             PAPER_WORDS)
        self.assertFalse(CouncilSession.objects.exists())

    def test_on_it_queues_one_sitting_and_answers_at_once(self):
        from ai_agents.council_models import CouncilSession
        switch("council_ticket")
        with patch.dict("os.environ", KEY), \
                patch("ai_agents.spend.can_spend",
                      return_value=(True, "")) as spend, \
                patch(DELAY) as delay, \
                self.captureOnCommitCallbacks(execute=True):
            resp = self._ask()
        self.assertEqual(resp.status_code, 202)
        sid = resp.json()["id"]
        # with an expiry: a ticket nobody is waiting for is never sat on
        delay.assert_called_once_with((sid,), expires=600)
        self.assertEqual(spend.call_args.kwargs["tier"], "balanced")
        s = CouncilSession.objects.get(id=sid)
        self.assertEqual((s.origin, s.venue, s.status, s.user_id),
                         ("ticket", "live", "queued", self.user.id))
        self.assertEqual((s.symbol, s.side, s.stop, s.target),
                         ("BTCUSD", "BUY", 59100.0, 61800.0))
        self.assertEqual(s.entry, 60000.0, "the platform's own mark")
        self.assertEqual(s.facts["leverage"], 2)
        self.assertFalse(s.facts["entry_unverified"])
        self.assertEqual(s.config_id, self.cfg.id)

    def test_the_same_ticket_twice_is_one_sitting(self):
        from ai_agents.council_models import CouncilSession
        switch("council_ticket")
        prev = CouncilSession.objects.create(
            origin="ticket", status="done", user=self.user, symbol="BTCUSD",
            side="BUY", stop=59100, target=61800)
        with patch.dict("os.environ", KEY), patch(DELAY) as delay:
            out = self._ask().json()
        self.assertEqual(out, {"ok": True, "id": prev.id, "reused": True})
        delay.assert_not_called()

    def test_the_same_ticket_still_sitting_is_reused_not_refused(self):
        """The reuse answers before the in-flight refusal: asking again
        about the ticket being argued shows that sitting, at no cost."""
        from ai_agents.council_models import CouncilSession
        switch("council_ticket")
        live = CouncilSession.objects.create(
            origin="ticket", status="sitting", user=self.user,
            symbol="BTCUSD", side="BUY", stop=59100, target=61800)
        with patch.dict("os.environ", KEY), patch(DELAY) as delay:
            resp = self._ask()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True, "id": live.id,
                                       "reused": True})
        delay.assert_not_called()

    def test_a_demo_world_ticket_is_never_argued(self):
        """A live config whose eToro row has Demo ticked places on eToro's
        DEMO portfolio: a rehearsal, refused like paper, unbilled."""
        from ai_agents.agents.council import PAPER_WORDS
        from ai_agents.council_models import CouncilSession
        switch("council_ticket")
        acct = self.acct
        acct.demo = True
        acct.save(update_fields=["demo"])
        self.user.refresh_from_db()
        with patch.dict("os.environ", KEY), \
                patch("ai_agents.spend.can_spend",
                      return_value=(True, "")) as spend, \
                patch(DELAY) as delay:
            resp = self._ask()
        self.assertEqual(resp.json(), {"ok": False, "why": PAPER_WORDS})
        self.assertFalse(CouncilSession.objects.exists())
        spend.assert_not_called()
        delay.assert_not_called()
        # Demo unticked: the same ticket is real money and sits
        acct.demo = False
        acct.save(update_fields=["demo"])
        self.user.refresh_from_db()
        with patch.dict("os.environ", KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "")), \
                patch(DELAY), self.captureOnCommitCallbacks(execute=True):
            resp = self._ask()
        self.assertEqual(resp.status_code, 202, resp.content)

    def test_a_lane_with_no_live_venue_is_never_argued(self):
        """The router substitutes the PaperTrader for a lane with no live
        venue: the ticket itself refuses it, and the council never argues
        a paper fill as real money."""
        from ai_agents.agents.council import PAPER_WORDS
        from ai_agents.council_models import CouncilSession
        switch("council_ticket")
        self.acct.delete()
        self.user.refresh_from_db()
        with patch.dict("os.environ", KEY), \
                patch("ai_agents.spend.can_spend",
                      return_value=(True, "")) as spend:
            self.assertEqual(self._ask().json(), {"ok": False,
                                                  "why": PAPER_WORDS})
        spend.assert_not_called()
        self.assertFalse(CouncilSession.objects.exists())

    def test_a_sim_or_practice_ticket_is_never_argued(self):
        """A Saxo SIM, OANDA practice or Alpaca paper client has no .demo:
        it fills in its venue's rehearsal world (AssetBot.VENUE_WORLDS,
        stamped broker_env "paper"), refused like paper, unbilled."""
        from unittest.mock import MagicMock

        from ai_agents.agents.council import PAPER_WORDS
        from ai_agents.council_models import CouncilSession
        from tests.test_take_trade_live import ROUTER
        switch("council_ticket")
        for env in ("sim", "practice", "paper"):
            client = MagicMock(name=f"a {env} client")
            client.env = env
            with self.subTest(env=env), patch.dict("os.environ", KEY), \
                    patch(ROUTER, return_value=client), \
                    patch("ai_agents.spend.can_spend",
                          return_value=(True, "")) as spend, \
                    patch(DELAY) as delay:
                resp = self._ask()
                self.assertEqual(resp.json(), {"ok": False,
                                               "why": PAPER_WORDS})
                spend.assert_not_called()
                delay.assert_not_called()
        self.assertFalse(CouncilSession.objects.exists())
        # the venue's live world is real money and sits
        live = MagicMock(name="a live client")
        live.env = "live"
        with patch.dict("os.environ", KEY), patch(ROUTER, return_value=live), \
                patch("ai_agents.spend.can_spend", return_value=(True, "")), \
                patch(DELAY), self.captureOnCommitCallbacks(execute=True):
            resp = self._ask()
        self.assertEqual(resp.status_code, 202, resp.content)

    def test_one_sitting_in_flight_at_a_time(self):
        from ai_agents.agents.council import BUSY_WORDS
        from ai_agents.council_models import CouncilSession
        switch("council_ticket")
        CouncilSession.objects.create(origin="ticket", status="sitting",
                                      user=self.user, symbol="BTCUSD",
                                      side="BUY", stop=59000, target=62000)
        with patch.dict("os.environ", KEY):
            resp = self._ask()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["why"], BUSY_WORDS)

    def test_the_days_cap_and_the_budget_refuse_in_words(self):
        from ai_agents.agents.council import (COUNCIL_TICKET_SITTINGS_PER_DAY,
                                              budget_words, cap_words)
        from ai_agents.council_models import CouncilSession
        switch("council_ticket")
        with patch.dict("os.environ", KEY), \
                patch("ai_agents.spend.can_spend",
                      return_value=(False, "daily AI budget spent")):
            self.assertEqual(self._ask().json()["why"],
                             budget_words("daily AI budget spent"))
        for i in range(COUNCIL_TICKET_SITTINGS_PER_DAY):
            CouncilSession.objects.create(origin="ticket", status="done",
                                          user=self.user, symbol="BTCUSD",
                                          side="SELL", stop=1 + i, target=2)
        with patch.dict("os.environ", KEY):
            self.assertEqual(self._ask().json()["why"], cap_words(12))
        self.assertIn("12 times", cap_words(12))

    def test_a_malformed_body_is_a_400(self):
        switch("council_ticket")
        with patch.dict("os.environ", KEY):
            for body, field in ((["x"], None),
                                (dict(TICKET, symbol="NOPE"), "symbol"),
                                (dict(TICKET, side="HOLD"), "side"),
                                (dict(TICKET, stop="abc"), "stop"),
                                (dict(TICKET, stop=True), "stop"),
                                (dict(TICKET, target=None), "target"),
                                (dict(TICKET, stop=-1), "stop"),
                                (dict(TICKET, qty="NaN"), "qty")):
                with self.subTest(field=field):
                    self.assertEqual(self._ask(body).status_code, 400)
            resp = self.client.post("/council/ask/", data="{oops",
                                    content_type="application/json")
            self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.client.get("/council/ask/").status_code, 405)

    def test_the_sitting_is_its_owners_or_staffs(self):
        from ai_agents.council_models import CouncilSession, CouncilVoice
        s = CouncilSession.objects.create(
            origin="ticket", status="done", user=self.user, symbol="BTCUSD",
            side="BUY", stop=59100, target=61800)
        CouncilVoice.objects.create(session=s, voice="gambler", wave=1,
                                    status="spoke", verdict="press",
                                    answer={"verdict": "press", "case": "c"},
                                    weight_seen=1.0,
                                    weight_reason="neutral: 0 graded calls "
                                                  "in this cell, 10 needed")
        out = self.client.get(f"/council/{s.id}/").json()
        self.assertEqual(out["asked"], {"stop": 59100.0, "target": 61800.0})
        self.assertEqual(out["voices"][0]["verdict_words"], "press")
        self.assertEqual(out["voices"][0]["name"], "The Gambler")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/council/{s.id}/").status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f"/council/{s.id}/").status_code, 200)


class ThePreviewRunsNothingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ct_p", password="x")

    def setUp(self):
        from tests.test_take_trade_live import _components_on, _quote
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        _live_manual(self.user)

    def test_previewing_a_ticket_reads_a_switch_and_runs_no_voice(self):
        from ai_agents.council_models import CouncilSession
        from bot_program.manual_trade import preview_take_trade
        from tests.test_take_trade_live import (ROUTER, _fake_live_client,
                                                _signal)
        switch("council_ticket")
        with patch(ROUTER, return_value=_fake_live_client()), \
                patch("ai_agents.agents.council.run_wave") as wave, \
                patch("ai_agents.base_agent.BaseAgent.run") as run, \
                patch(DELAY) as delay:
            p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p)
        self.assertIs(p["council_on"], True)
        wave.assert_not_called()
        run.assert_not_called()
        delay.assert_not_called()
        self.assertFalse(CouncilSession.objects.exists())
        # eToro's DEMO world is never offered the council
        demo = _fake_live_client()
        demo.demo = True
        with patch(ROUTER, return_value=demo):
            p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p)
        self.assertIs(p["council_on"], False)
        # nor a Saxo SIM / OANDA practice client (no .demo, a rehearsal env)
        for env in ("sim", "practice"):
            sim = _fake_live_client()
            sim.env = env
            with self.subTest(env=env), patch(ROUTER, return_value=sim):
                p = preview_take_trade(self.user, _signal(self.inst))
                self.assertNotIn("error", p)
                self.assertIs(p["council_on"], False)
        switch("council_ticket", False)
        with patch(ROUTER, return_value=_fake_live_client()):
            p = preview_take_trade(self.user, _signal(self.inst))
        self.assertIs(p["council_on"], False)


class TheTicketBriefTests(TestCase):
    """The ticket's brief is built in the task, from the preview, at the
    levels its owner asked about; it argues the entry the sitting will be
    graded from."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ct_b", password="x")

    def setUp(self):
        from tests.test_take_trade_live import _components_on, _quote
        cache.clear()
        _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _live_manual(self.user)

    def _session(self, **over):
        from ai_agents.council_models import CouncilSession
        fields = dict(origin="ticket", status="sitting", user=self.user,
                      config=self.cfg, symbol="BTCUSD", asset_class="crypto",
                      side="BUY", entry=60000.0, stop=59000.0,
                      target=62000.0, qty=0.01,
                      facts={"entry_unverified": False})
        fields.update(over)
        return CouncilSession.objects.create(**fields)

    def _brief(self, s):
        from ai_agents.agents.council import ticket_brief
        from tests.test_take_trade_live import ROUTER, _fake_live_client
        with patch(ROUTER, return_value=_fake_live_client()), \
                patch("ai_agents.base_agent.BaseAgent.run") as run:
            brief = ticket_brief(s)
        run.assert_not_called()
        s.refresh_from_db()
        return brief

    def test_the_brief_is_the_hand_ticket_at_the_asked_levels(self):
        # the mark recorded at the click (60500) differs from the
        # preview's live price (60000): the brief argues the recorded one,
        # the price the sitting will be graded from
        s = self._session(entry=60500.0)
        brief = self._brief(s)
        self.assertIn("BTCUSD (crypto) BUY — a HAND trade: the operator's "
                      "own call; no rule's record applies", brief)
        self.assertIn("entry 60500, stop 59000 (2.48% away), target 62000 "
                      "(2.48% away)", brief)
        self.assertNotIn("entry 60000,", brief)
        self.assertIn("net reward:risk", brief)
        self.assertIn("of the lane's capital", brief)
        self.assertEqual(s.entry, 60500.0, "the mark it is graded from")
        self.assertGreater(s.value_per_unit, 0)

    def test_an_unverified_entry_takes_the_previews_mark(self):
        s = self._session(entry=61000.0, facts={"entry_unverified": True})
        brief = self._brief(s)
        self.assertIn("NOTE: the platform had no fresh mark", brief)
        self.assertEqual(s.entry, 60000.0)

    def _held(self, side, entry, *, paper=False, status="OPEN"):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="crypto", symbol="BTCUSD",
            side=side, qty=Decimal("0.01"), entry_price=Decimal(str(entry)),
            stop_loss=Decimal("50000") if side == "BUY" else Decimal("70000"),
            status=status, paper=paper, rule_name="manual_take")

    def test_a_ticket_that_adds_to_a_losing_position_says_so(self):
        """The ticket that titles itself "Add to this LIVE position?" must
        reach the voices as an add: on a loser, an average-down, which the
        law forbids any voice to argue for."""
        self._held("BUY", 61000)
        self._held("BUY", 30000, paper=True)        # paper: not the book
        self._held("BUY", 20000, status="CLOSED")    # closed: not held
        brief = self._brief(self._session())
        self.assertIn("ALREADY HELD ON THIS SYMBOL (this ticket ADDS to it): "
                      "BUY opened at 61000, now -1.64%; adding to it is "
                      "averaging down a loser", brief)
        self.assertEqual(brief.count("ALREADY HELD"), 1, brief)

    def test_a_demo_world_holding_is_not_already_held(self):
        """An open row from when Demo was ticked is paper=False (the
        preview's "LIVE") but eToro's DEMO world (broker_env "paper"): no
        real money is held, so no ALREADY HELD line and no average-down."""
        demo = self._held("BUY", 61000)
        demo.metadata = {"broker_env": "paper"}
        demo.save(update_fields=["metadata"])
        brief = self._brief(self._session())
        self.assertNotIn("ALREADY HELD", brief)
        self.assertNotIn("averaging down", brief)
        real = self._held("BUY", 61000)
        real.metadata = {"broker_env": "live"}
        real.save(update_fields=["metadata"])
        brief = self._brief(self._session())
        self.assertEqual(brief.count("ALREADY HELD"), 1, brief)
        self.assertIn("averaging down a loser", brief)

    def test_a_winning_or_opposite_holding_is_said_without_the_warning(self):
        self._held("BUY", 59000)
        self._held("SELL", 59500)
        brief = self._brief(self._session())
        self.assertIn("(this ticket ADDS to it): BUY opened at 59000, now "
                      "+1.69%", brief)
        self.assertIn("(this ticket stands against it): SELL opened at "
                      "59500, now -0.84%", brief)
        self.assertNotIn("averaging down", brief)

    def _fixed_preview(self, **over):
        p = {"entry": 60000.0, "stop": 59500.0, "target": 60400.0,
             "capital": 100000.0, "value_per_unit": 1.0, "qty": 0.01,
             "levels": {"cost_fraction": 0.001}, "existing_exposure": [],
             "reward_risk": {"ok": True, "reason": ""},
             "cost_advisory": {"ok": False,
                               "reason": "THE DEFAULT LEVELS DO NOT CLEAR "
                                         "THEIR ROUND TRIP"}}
        p.update(over)
        return patch("bot_program.manual_trade._preview", return_value=p)

    def test_moved_levels_are_judged_at_the_asked_levels(self):
        """The preview judges its own default levels; the council argues
        the asked ones. Its reward:risk is judged again at them, and its
        cost advisory (computed for untouched levels only) is not quoted
        for levels it never saw."""
        from ai_agents.agents.council import ticket_brief
        stale = {"ok": False, "reason": "This ticket risks 0.83% to make "
                                        "0.67% — reward:risk 0.80."}
        moved = self._session(stop=59000.0, target=60500.0)
        with self._fixed_preview(reward_risk=stale):
            brief = ticket_brief(moved)
        self.assertIn("reward:risk: This ticket risks 1.67% to make 0.83% — "
                      "reward:risk 0.50.", brief)
        self.assertNotIn("reward:risk 0.80", brief)
        self.assertNotIn("DO NOT CLEAR", brief)
        good = self._session(stop=59000.0, target=62000.0)
        with self._fixed_preview(reward_risk=stale):
            brief = ticket_brief(good)
        self.assertNotIn("reward:risk:", brief, "2.00 is no warning")
        same = self._session(stop=59500.0, target=60400.0)
        with self._fixed_preview():
            brief = ticket_brief(same)
        self.assertIn("cost: THE DEFAULT LEVELS DO NOT CLEAR THEIR ROUND "
                      "TRIP", brief)
        self.assertIn("reward:risk 0.80", brief)


class TheBodyAndTheLinkTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ct_l", password="x")
        cls.other = get_user_model().objects.create_user("ct_l2",
                                                         password="x")

    def test_the_body_keeps_a_positive_integer_and_drops_the_rest(self):
        from dashboard.views import _parse_trade_body

        def parse(body):
            req = RequestFactory().post("/x", data=json.dumps(body),
                                        content_type="application/json")
            return _parse_trade_body(req)

        self.assertEqual(parse({"council_session": 12})[0]["council_session"],
                         12)
        self.assertEqual(parse({"council_session": "7"})[0]["council_session"],
                         7)
        for junk in (None, 0, -3, "x", True, 2.5, [1], {"a": 1}, "1e3"):
            with self.subTest(junk=junk):
                out, err = parse({"council_session": junk})
                self.assertIsNone(err)
                self.assertIsNone(out["council_session"])

    def _trade(self, user, symbol="BTCUSD", side="BUY", stop="59100",
               target="61800"):
        from bot_program.manual_trade import MANUAL_RULE
        from bot_program.models import AssetBotTrade
        cfg = _live_manual(user)
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol=symbol, side=side,
            qty=Decimal("0.01"), entry_price=Decimal("60000"),
            stop_loss=Decimal(stop), take_profit=Decimal(target),
            rule_name=MANUAL_RULE, paper=False,
            metadata={"manual": True, "initial_stop_loss": float(stop)})

    def _session(self, user, **over):
        from ai_agents.council_models import CouncilSession
        fields = dict(origin="ticket", status="done", user=user,
                      symbol="BTCUSD", side="BUY", stop=59100.0,
                      target=61800.0)
        fields.update(over)
        return CouncilSession.objects.create(**fields)

    def test_a_valid_own_sitting_is_linked_with_its_levels_judged(self):
        from dashboard.views_council import link_ticket_session
        s = self._session(self.user)
        t = self._trade(self.user)
        link_ticket_session(self.user, s.id, t.id)
        s.refresh_from_db()
        self.assertEqual((s.trade_id, s.linked_by, s.levels_match),
                         (t.id, "body", True))
        s2 = self._session(self.user)
        t2 = self._trade(self.user, stop="59500")
        link_ticket_session(self.user, s2.id, t2.id)
        s2.refresh_from_db()
        self.assertEqual((s2.trade_id, s2.levels_match), (t2.id, False))

    def test_never_another_users_another_symbol_or_an_old_sitting(self):
        from ai_agents.council_models import CouncilSession
        from dashboard.views_council import link_ticket_session
        theirs = self._session(self.other)
        t = self._trade(self.user)
        link_ticket_session(self.user, theirs.id, t.id)
        wrong_symbol = self._session(self.user, symbol="ETHUSD")
        link_ticket_session(self.user, wrong_symbol.id, t.id)
        wrong_side = self._session(self.user, side="SELL")
        link_ticket_session(self.user, wrong_side.id, t.id)
        old = self._session(self.user)
        CouncilSession.objects.filter(id=old.id).update(
            created_at=timezone.now() - timedelta(hours=3))
        link_ticket_session(self.user, old.id, t.id)
        link_ticket_session(self.user, "garbage", t.id)   # never raises
        self.assertFalse(CouncilSession.objects.filter(
            trade__isnull=False).exists())

    def test_a_demo_world_row_is_never_linked(self):
        """A hand trade placed on eToro's DEMO portfolio (its row stamped
        broker_env "paper") never grades into the live record."""
        from ai_agents.council_models import CouncilSession
        from dashboard.views_council import link_ticket_session
        s = self._session(self.user)
        t = self._trade(self.user)
        t.metadata = dict(t.metadata, broker_env="paper")
        t.save(update_fields=["metadata"])
        link_ticket_session(self.user, s.id, t.id)
        self.assertIsNone(CouncilSession.objects.get(id=s.id).trade_id)
        real = self._trade(self.user)
        real.metadata = dict(real.metadata, broker_env="live")
        real.save(update_fields=["metadata"])
        link_ticket_session(self.user, s.id, real.id)
        self.assertEqual(CouncilSession.objects.get(id=s.id).trade_id,
                         real.id)

    def test_the_execute_response_is_the_executions_own(self):
        """The view links after the result and returns it untouched, with
        and without the field."""
        from bot_program.manual_trade import MANUAL_RULE  # noqa: F401
        from tests.test_take_trade_live import _quote
        _quote("BTCUSD", 60000)
        self.client.force_login(self.user)
        result = {"ok": True, "trade_id": 991, "symbol": "BTCUSD",
                  "side": "BUY", "qty": 0.01}
        with patch("bot_program.manual_trade.execute_asset_trade",
                   return_value=dict(result)), \
                patch("dashboard.views_council.link_ticket_session") as link:
            plain = self.client.post(
                "/instruments/BTCUSD/take-trade/",
                data=json.dumps({"side": "BUY"}),
                content_type="application/json")
            link.assert_not_called()
            asked = self.client.post(
                "/instruments/BTCUSD/take-trade/",
                data=json.dumps({"side": "BUY", "council_session": 5}),
                content_type="application/json")
            link.assert_called_once_with(self.user, 5, 991)
        self.assertEqual(plain.content, asked.content)
        self.assertEqual(json.loads(asked.content), result)
        with patch("bot_program.manual_trade.execute_asset_trade",
                   return_value={"error": "PIN"}), \
                patch("dashboard.views_council.link_ticket_session") as link:
            self.client.post("/instruments/BTCUSD/take-trade/",
                             data=json.dumps({"side": "BUY",
                                              "council_session": 5}),
                             content_type="application/json")
        link.assert_not_called()

    def test_the_signal_ticket_links_after_its_result_too(self):
        from tests.test_take_trade_live import _quote, _signal
        sig = _signal(_quote("BTCUSD", 60000))
        self.client.force_login(self.user)
        result = {"ok": True, "trade_id": 77, "symbol": "BTCUSD"}
        url = f"/signals/{sig.id}/take-trade/"
        with patch("bot_program.manual_trade.execute_take_trade",
                   return_value=dict(result)), \
                patch("dashboard.views_council.link_ticket_session") as link:
            plain = self.client.post(url, data=json.dumps({}),
                                     content_type="application/json")
            link.assert_not_called()
            asked = self.client.post(
                url, data=json.dumps({"council_session": "9"}),
                content_type="application/json")
        link.assert_called_once_with(self.user, 9, 77)
        self.assertEqual(plain.content, asked.content)

    def test_a_real_live_ticket_links_its_sitting(self):
        """End to end on the live lane: the PIN, the order, then the link."""
        from ai_agents.council_models import CouncilSession
        from portfolio.trader_profile import get_or_create_profile
        from tests.test_take_trade_live import (ROUTER, _components_on,
                                                _fake_live_client, _quote)
        cache.clear()
        prof = get_or_create_profile(self.user)
        prof.set_pin("4321")
        prof.save()
        _quote("BTCUSD", 60000)
        _components_on()
        _live_manual(self.user)
        s = self._session(self.user, stop=1.0, target=2.0)
        self.client.force_login(self.user)
        with patch(ROUTER, return_value=_fake_live_client()):
            out = self.client.post(
                "/instruments/BTCUSD/take-trade/",
                data=json.dumps({"side": "BUY", "pin": "4321",
                                 "council_session": s.id}),
                content_type="application/json", HTTP_HOST="127.0.0.1").json()
        self.assertTrue(out.get("ok"), out)
        s = CouncilSession.objects.get(id=s.id)
        self.assertEqual((s.trade_id, s.linked_by, s.levels_match),
                         (out["trade_id"], "body", False))


class TheTicketSourceTests(SimpleTestCase):

    def _base(self):
        return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")

    def test_the_region_exists_only_on_a_live_ticket_with_its_switch(self):
        base = self._base()
        self.assertEqual(base.count('data-role="council"'), 2)
        self.assertIn("((live && p.council_on) ? '<div data-role=\"council\" "
                      "aria-live=\"polite\"></div>' : '')", base)
        self.assertIn("SV.council.mount(councilEl", base)
        self.assertIn("{% static 'js/sv-council.js' %}", base)

    def test_the_ok_button_never_reads_the_council(self):
        base = self._base()
        start = base.index("okBtn.addEventListener('click'")
        end = base.index("host.querySelector('[data-role=\"cancel\"]')", start)
        self.assertNotRegex(base[start:end], r"(?i)council")
        # the sitting's id is read once, in finish(), after the decision
        fin = base.index("function finish(v)")
        self.assertIn("councilEl.dataset.session",
                      base[fin:base.index("SV.overlay.close(host)", fin)])
        disabled = re.findall(r"okBtn\.disabled = [^;]*;", base, re.S)
        self.assertTrue(disabled)
        for line in disabled:
            self.assertNotIn("council", line)

    def test_the_execute_body_carries_the_sitting_only_from_the_choice(self):
        base = self._base()
        self.assertEqual(base.count("body.council_session"), 1)
        self.assertIn("if (choice.council) body.council_session = "
                      "choice.council;", base)
        self.assertIn("if (v && councilEl) v.council = "
                      "Number(councilEl.dataset.session) || null;", base)

    def test_the_script_runs_nothing_until_its_button_is_clicked(self):
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-council.js").read_text(encoding="utf-8")
        mount = js[js.index("function mount("):js.index("SV.council = ")]
        before_click = mount[:mount.index("btn.addEventListener('click'")]
        self.assertNotIn("fetch(", before_click)
        self.assertIn("/council/ask/", js)
        self.assertIn("Ask the council", js)
        self.assertNotIn("okBtn", js)
        self.assertTrue(js.isascii())
