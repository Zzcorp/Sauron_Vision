"""The system map names three kinds of "nothing consumes it", not one.

On 2026-09-11 the map listed nine components under "producing nothing
anything reads". Traced against the code, they were three different
things:

  * a MISSING EDGE — broker_account_sync. The table said "nothing
    downstream divides by it"; since pools can follow the account, every
    follower's capital is that reading times its share, and the entry
    path refuses to open on a stale one. It feeds the fleet.
  * READ BY PEOPLE — the briefings, the anomaly scan, the journal. Their
    output is rendered on a page and consumed by no other node. That is
    their job, and the map had no word for it, so it called them orphans
    for as long as it existed.
  * HONEST ORPHANS — agent_strategy and agent_optimization write a
    StrategyAdjustment table nothing reads and no page renders; the AI
    pre-trade gate is consulted only by the legacy crypto bot, which is
    not scheduled. Those two findings were buried among seven false ones.

Run with:  python manage.py test tests.test_system_map_wiring
"""
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase


class TheWiringTellsTheTruthTests(SimpleTestCase):

    def test_the_broker_sync_reaches_the_fleet(self):
        from dashboard.views_topology import WIRING
        sync = WIRING["broker_account_sync"]
        self.assertEqual(sync["feeds"], ["execute_bots"])
        self.assertIn("_follow_the_account", sync["note"])
        self.assertIn("tracking_freeze_reason", sync["note"])

    def test_human_facing_agents_name_their_pages(self):
        from dashboard.views_topology import WIRING
        for key in ("agent_anomaly", "agent_daily_briefing",
                    "agent_weekly_review", "agent_monday_plan"):
            self.assertIn("/ai/", WIRING[key]["pages"], key)
        self.assertEqual(WIRING["pipeline_ai_journal"]["pages"],
                         ["/ai-journal/"])

    def test_the_advisors_claims_are_graded_and_the_gate_stays_an_orphan(self):
        """agent_strategy and agent_optimization used to be honest orphans:
        a StrategyAdjustment table nothing read. Their proposals' legs are
        now registered as direction calls, and the calibration grades them
        — that edge is the only thing that reads them. The pre-trade gate
        still gates nothing here."""
        from dashboard.views_topology import WIRING
        for key in ("agent_strategy", "agent_optimization", "agent_anomaly",
                    "agent_daily_briefing", "agent_weekly_review",
                    "agent_monday_plan"):
            self.assertIn("pipeline_calibration", WIRING[key]["feeds"], key)
            self.assertIn("AgentPrediction", WIRING[key]["writes"], key)
        gate = WIRING["feature_ai_pretrade_gate"]
        self.assertEqual(gate["feeds"], [])
        self.assertFalse(gate.get("pages"))
        self.assertEqual(WIRING["pipeline_calibration"]["writes"],
                         ["AgentPrediction.was_correct"])

    def test_the_gate_switch_says_it_gates_nothing_here(self):
        from core.platform_control import DEFAULT_COMPONENTS
        gate = next(c for c in DEFAULT_COMPONENTS
                    if c["key"] == "feature_ai_pretrade_gate")
        self.assertIn("LEGACY", gate["description"])
        self.assertIn("Leave OFF", gate["description"])


class TheMapSortsThemTests(TestCase):

    def setUp(self):
        call_command("seed_components", verbosity=0)
        self.user = User.objects.create_user("map_u", password="x",
                                             is_staff=True)

    def test_the_sync_and_the_briefing_are_no_longer_orphans(self):
        from dashboard.views_topology import build_topology
        topo = build_topology(self.user)
        self.assertNotIn("broker_account_sync", topo["orphans"])
        self.assertNotIn("agent_daily_briefing", topo["orphans"])
        self.assertNotIn("agent_strategy", topo["orphans"])
        self.assertIn("feature_ai_pretrade_gate", topo["orphans"])
        readers = {h["key"]: h["pages"] for h in topo["human_read"]}
        # The journal writes for the operator and feeds no node: read by
        # people. The briefing now ALSO feeds the calibration with its calls
        # block, so it has an edge and leaves this list — which is the point.
        self.assertIn("/ai-journal/", readers["pipeline_ai_journal"])
        self.assertNotIn("agent_daily_briefing", readers)
        self.assertNotIn("broker_account_sync", readers)   # it has an edge

    def test_the_page_renders_both_lists(self):
        client = Client()
        client.force_login(self.user)
        r = client.get("/admin-dashboard/system-map/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("Read by people, not by machines", html)
        self.assertIn("Producing nothing anything reads", html)
