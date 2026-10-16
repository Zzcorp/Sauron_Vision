"""The AI budget gets a second line for the Orcs, off until O2 (PR O0a).

Spec §7.1 (revised 2026-10-15): AI_DAILY_BUDGET_USD stays the TOTAL stop.
The Orcs' line is a cap (ORC_DAILY_BUDGET_USD, 0 = off). The core line
is the total minus what the Orcs have ACTUALLY spent today minus a $3
floor kept for their live urgent wakes, never minus their cap, and the
floor applies only while the Orcs' line is on. The deep tier's 70% share
is read against each line's live allowance. BaseAgent.run, which never
asked the budget, now refuses at the total and never before.

What is pinned here:
  1. With no line passed, every caller gets today's answers, word for
     word, from one query (the Orcs' line is off by default).
  2. The Orcs' line: its membership, its cap, the core's formula, the
     deep share, the total stop across both lines.
  3. BaseAgent.run: the total-only check, the pre-trade sanity agent's
     exemption, and source_ref on its row and into the provider.
  4. /ai-models/: the TODAY cell is unchanged with the line off and shows
     the three numbers with it on; an Orc agent key cannot be written.

Run with:  python manage.py test tests.test_ai_spend_lines
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings


def _cfg(total, orcs=None):
    """Both figures written, always: left out, the Orcs' cap would fall
    back to ORC_DAILY_BUDGET_USD in this process's environment (a box's
    .env), and these answers would depend on where the suite runs."""
    cfg = {"daily_budget_usd": total, "models": {},
           "default_provider": "claude",
           "orc_daily_budget_usd": 0.0 if orcs is None else orcs}
    return override_settings(AI_CONFIG=cfg)


def _task(cost, agent="news_analyst", source_ref=None):
    from ai_agents.models import AgentTask
    return AgentTask.objects.create(
        agent=agent, provider="claude", model="claude-opus-5",
        prompt_summary="p", cost_usd=Decimal(str(cost)), success=True,
        structured_output=({"source_ref": source_ref} if source_ref
                           else {}))


class TodaysAnswersTests(TestCase):
    """tests/test_ai_spend.py's scenarios, asked with no line and with
    line="core": the same booleans and the same strings."""

    def _both(self, **kw):
        from ai_agents.spend import can_spend
        a = can_spend(**kw)
        b = can_spend(line="core", **kw)
        self.assertEqual(a, b)
        return a

    @_cfg(1.0)
    def test_spent(self):
        _task(1.10)
        self.assertEqual(self._both(tier="balanced"),
                         (False, "daily AI budget spent ($1.10 of $1.00)"))

    @_cfg(1.0)
    def test_deep_share(self):
        _task(0.80)
        self.assertEqual(self._both(tier="deep"), (False, (
            "deep-tier reserve reached ($0.80 of $1.00; deep tier capped "
            "at 70%)")))
        self.assertEqual(self._both(tier="fast", estimated_usd=0.01),
                         (True, "$0.20 of $1.00 remaining"))

    @_cfg(1.0)
    def test_estimate(self):
        _task(0.50)
        self.assertEqual(self._both(tier="fast", estimated_usd=0.6),
                         (False, ("call would exceed the daily budget "
                                  "($0.50 left)")))

    @_cfg(0)
    def test_no_ceiling(self):
        _task(999)
        self.assertEqual(self._both(tier="deep"),
                         (True, "no budget configured"))

    @_cfg(1.0)
    def test_one_query(self):
        from ai_agents.spend import can_spend
        _task(0.25)
        with self.assertNumQueries(1):
            can_spend(tier="deep")

    @_cfg(2.0)
    def test_the_readouts(self):
        from ai_agents.spend import daily_budget, remaining_today, spent_today
        _task(0.5)
        self.assertEqual(daily_budget(), 2.0)
        self.assertAlmostEqual(spent_today(), 0.5)
        self.assertAlmostEqual(remaining_today(), 1.5)

    @_cfg(2.0)
    def test_the_guard_skips_as_it_did(self):
        from ai_agents.spend import guard
        _task(2.5)
        fn = guard(tier="deep")(lambda: "ran")
        self.assertEqual(fn()["status"], "skipped")

    def test_the_orcs_line_defaults_to_off(self):
        import importlib
        import os
        from unittest import mock
        import ai_agents.spend as spend
        self.addCleanup(importlib.reload, spend)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORC_DAILY_BUDGET_USD", None)
            importlib.reload(spend)
            self.assertEqual(spend.DEFAULT_ORC_DAILY_BUDGET_USD, 0.0)
            self.assertEqual(spend.ORC_LIVE_FLOOR_USD, 3.00)
            self.assertEqual(spend.LINES, ("core", "orcs"))

    def test_a_blank_or_bad_orcs_value_leaves_the_line_off(self):
        """A typo in ORC_DAILY_BUDGET_USD must not break the import every
        AI caller makes; the line stays off. AI_DAILY_BUDGET_USD keeps
        today's parse."""
        import importlib
        import os
        from unittest import mock
        import ai_agents.spend as spend
        self.addCleanup(importlib.reload, spend)
        with mock.patch.dict(os.environ, {"ORC_DAILY_BUDGET_USD": " "}):
            importlib.reload(spend)
            self.assertEqual(spend.DEFAULT_ORC_DAILY_BUDGET_USD, 0.0)
        with mock.patch.dict(os.environ,
                             {"ORC_DAILY_BUDGET_USD": "thirteen"}), \
                self.assertLogs("ai_agents.spend", level="ERROR"):
            importlib.reload(spend)
            self.assertEqual(spend.DEFAULT_ORC_DAILY_BUDGET_USD, 0.0)
        with mock.patch.dict(os.environ, {"ORC_DAILY_BUDGET_USD": "13"}):
            importlib.reload(spend)
            self.assertEqual(spend.DEFAULT_ORC_DAILY_BUDGET_USD, 13.0)

    @_cfg(27.0)
    def test_the_orcs_line_off_refuses_an_orc_call(self):
        from ai_agents.spend import can_spend, daily_budget
        self.assertEqual(daily_budget("orcs"), 0.0)
        self.assertEqual(daily_budget(), 27.0)  # no floor while off
        self.assertEqual(can_spend(tier="balanced", line="orcs"), (
            False, "the Orcs line is off (ORC_DAILY_BUDGET_USD=0)"))

    def test_an_unknown_line_is_an_error(self):
        from ai_agents.spend import can_spend
        with self.assertRaises(ValueError):
            can_spend(line="treasury")

    @_cfg(0)
    def test_no_total_lifts_the_core_but_the_orcs_line_off_still_refuses(self):
        """AI_DAILY_BUDGET_USD=0 lifts the total and the core line only:
        "0 = their line is off: no Orc call is allowed" holds with no
        total above it. The core and no-line answers stay word for word."""
        from ai_agents.spend import can_spend, remaining_today
        _task(999)
        self.assertEqual(can_spend(tier="balanced", line="orcs"), (
            False, "the Orcs line is off (ORC_DAILY_BUDGET_USD=0)"))
        self.assertEqual(can_spend(tier="deep", line="orcs",
                                   deep_share_exempt=True), (
            False, "the Orcs line is off (ORC_DAILY_BUDGET_USD=0)"))
        self.assertEqual(can_spend(tier="deep"),
                         (True, "no budget configured"))
        self.assertEqual(can_spend(tier="deep", line="core"),
                         (True, "no budget configured"))
        self.assertEqual(can_spend(tier="deep", line="core", total_only=True),
                         (True, "no budget configured"))
        self.assertEqual(remaining_today("orcs"), 0.0)
        self.assertEqual(remaining_today(), float("inf"))
        self.assertEqual(remaining_today("total"), float("inf"))


class OrcLineTests(TestCase):
    """Cap $13, total $27 (D18)."""

    @_cfg(27.0, orcs=13.0)
    def test_membership_by_agent_and_by_source_ref(self):
        from ai_agents.spend import spent_today
        for agent in ("orc", "orc_confirm", "orc_question", "orc_postmortem",
                      "captain", "captain_fx"):
            _task(1.0, agent=agent)
        _task(0.5, agent="debate_executioner", source_ref="Orc:7:Add:x")
        _task(0.5, agent="debate_champion", source_ref="Captain:fx:Wake:2")
        # Not the Orcs: a name that merely starts with the letters, a
        # source_ref of another kind, a row with no source_ref.
        _task(0.25, agent="orchestra_tuner")
        _task(0.25, agent="captainship")
        _task(0.25, agent="research", source_ref="Orchestra:1")
        _task(0.25, agent="sauron_mind")
        self.assertAlmostEqual(spent_today("orcs"), 7.0)
        self.assertAlmostEqual(spent_today("core"), 1.0)
        self.assertAlmostEqual(spent_today("total"), 8.0)

    @_cfg(27.0, orcs=13.0)
    def test_core_is_the_total_minus_actual_orc_spend_minus_the_floor(self):
        from ai_agents.spend import daily_budget
        self.assertEqual(daily_budget("core"), 24.0)   # nothing spent yet
        _task(5.0, agent="orc")
        _task(4.0, agent="sauron_mind")
        self.assertEqual(daily_budget("core"), 19.0)   # never 27 - 13
        self.assertEqual(daily_budget("orcs"), 13.0)
        self.assertEqual(daily_budget("total"), 27.0)

    @_cfg(27.0, orcs=13.0)
    def test_the_total_stop_refuses_both_lines(self):
        from ai_agents.spend import can_spend
        _task(12.0, agent="orc")
        _task(15.5, agent="critic")
        for line in ("core", "orcs"):
            ok, why = can_spend(tier="fast", estimated_usd=0.01, line=line)
            self.assertFalse(ok, line)
            self.assertEqual(why, "daily AI budget spent ($27.50 of $27.00)")

    @_cfg(27.0, orcs=13.0)
    def test_the_orcs_cap_binds_and_the_core_runs_on(self):
        from ai_agents.spend import can_spend
        _task(13.5, agent="orc")
        ok, why = can_spend(tier="balanced", line="orcs")
        self.assertFalse(ok)
        self.assertIn("Orcs line is spent", why)
        ok, _ = can_spend(tier="balanced", line="core")
        self.assertTrue(ok)  # core 27 - 13.5 - 3 = 10.5, nothing spent

    @_cfg(27.0, orcs=13.0)
    def test_the_core_line_spent_before_the_total(self):
        from ai_agents.spend import can_spend
        _task(10.0, agent="orc")
        _task(14.5, agent="critic")       # core budget 27 - 10 - 3 = 14
        ok, why = can_spend(tier="fast", estimated_usd=0.01)
        self.assertFalse(ok)
        self.assertIn("core AI line is spent", why)
        # The total-only question (BaseAgent.run's) still answers yes.
        self.assertTrue(can_spend(tier="fast", total_only=True)[0])

    @_cfg(27.0, orcs=13.0)
    def test_the_deep_share_reads_the_live_allowance(self):
        """Core allowance 27 - 5 - 3 = 19; 70% of it is 13.30. Against the
        cap (14) it would have been 9.80; against the total, 18.90."""
        from ai_agents.spend import can_spend
        _task(5.0, agent="orc")
        _task(13.2, agent="critic")
        self.assertTrue(can_spend(tier="deep", estimated_usd=0.01)[0])
        _task(0.2, agent="critic")
        ok, why = can_spend(tier="deep", estimated_usd=0.01)
        self.assertFalse(ok)
        self.assertEqual(why, ("deep-tier reserve reached ($13.40 of $19.00; "
                               "deep tier capped at 70%)"))

    @_cfg(27.0, orcs=13.0)
    def test_the_orcs_deep_share_and_its_exemption(self):
        """D30: inside the Orcs' line a live urgent or confirm wake is
        never refused by the 70% share; the exemption is the caller's."""
        from ai_agents.spend import can_spend
        _task(9.2, agent="orc")            # over 13 x 0.7 = 9.10
        self.assertFalse(can_spend(tier="deep", estimated_usd=0.1,
                                   line="orcs")[0])
        self.assertTrue(can_spend(tier="deep", estimated_usd=0.1,
                                  line="orcs", deep_share_exempt=True)[0])

    @_cfg(27.0, orcs=13.0)
    def test_the_exemption_means_nothing_on_the_core_line(self):
        from ai_agents.spend import can_spend
        _task(18.0, agent="critic")        # core 24, 70% = 16.80
        self.assertFalse(can_spend(tier="deep", deep_share_exempt=True)[0])

    @_cfg(27.0, orcs=13.0)
    def test_total_only_refuses_only_at_the_total(self):
        from ai_agents.spend import can_spend
        _task(26.0, agent="critic")
        self.assertTrue(can_spend(tier="deep", line="core",
                                  total_only=True)[0])
        _task(1.0, agent="critic")
        self.assertFalse(can_spend(tier="deep", line="core",
                                   total_only=True)[0])

    @_cfg(27.0, orcs=13.0)
    def test_the_estimate_is_checked_against_the_lines_remaining(self):
        from ai_agents.spend import can_spend
        _task(12.9, agent="orc")
        self.assertEqual(
            can_spend(tier="balanced", estimated_usd=0.5, line="orcs"),
            (False, "call would exceed the daily budget ($0.10 left)"))

    @_cfg(0, orcs=13.0)
    def test_with_no_total_the_orcs_cap_still_binds(self):
        """§7.1: the Orc figure is a cap the Orcs may not exceed. With no
        total it is the only ceiling on their line; the core has none."""
        from ai_agents.spend import can_spend, remaining_today
        _task(50.0, agent="orc")
        self.assertEqual(can_spend(tier="deep", line="orcs"), (
            False, "the Orcs line is spent ($50.00 of $13.00)"))
        self.assertEqual(can_spend(tier="deep", line="orcs",
                                   deep_share_exempt=True), (
            False, "the Orcs line is spent ($50.00 of $13.00)"))
        self.assertEqual(remaining_today("orcs"), 0.0)
        self.assertEqual(can_spend(tier="deep"),
                         (True, "no budget configured"))
        self.assertEqual(remaining_today(), float("inf"))

    @_cfg(0, orcs=13.0)
    def test_with_no_total_the_orcs_share_and_estimate_still_apply(self):
        from ai_agents.spend import can_spend, remaining_today
        _task(5.0, agent="orc")
        _task(400.0, agent="critic")       # the core's, unbounded today
        self.assertEqual(can_spend(tier="balanced", line="orcs"),
                         (True, "$8.00 of $13.00 remaining"))
        self.assertAlmostEqual(remaining_today("orcs"), 8.0)
        self.assertEqual(
            can_spend(tier="balanced", estimated_usd=8.5, line="orcs"),
            (False, "call would exceed the daily budget ($8.00 left)"))
        _task(4.2, agent="orc")            # 9.20, over 13 x 0.7 = 9.10
        self.assertEqual(can_spend(tier="deep", line="orcs"), (
            False, "deep-tier reserve reached ($9.20 of $13.00; deep tier "
                   "capped at 70%)"))
        self.assertTrue(can_spend(tier="deep", line="orcs",
                                  deep_share_exempt=True)[0])

    @_cfg(27.0, orcs=13.0)
    def test_the_summary_for_the_page(self):
        from ai_agents.spend import lines_summary
        _task(5.0, agent="orc")
        _task(4.0, agent="critic")
        s = lines_summary()
        self.assertTrue(s["orcs_enabled"])
        self.assertEqual((s["total"], s["spent_total"]), (27.0, 9.0))
        self.assertEqual((s["orcs_cap"], s["orcs_spent"]), (13.0, 5.0))
        self.assertEqual((s["core_budget"], s["core_spent"]), (19.0, 4.0))
        self.assertEqual(s["floor"], 3.0)


# ── BaseAgent.run ────────────────────────────────────────────────────────

def _probe_agent(tier="deep"):
    from ai_agents.base_agent import BaseAgent

    class ProbeAgent(BaseAgent):
        agent_name = "probe_agent"
        default_tier = tier

        def get_system_prompt(self):
            return "sys"

        def build_context(self, **kwargs):
            self.seen = dict(kwargs)
            return "context " + ",".join(sorted(kwargs))

        def parse_response(self, raw):
            return {"raw": raw}

    agent = ProbeAgent()
    agent.provider = MagicMock()
    agent.provider.complete.return_value = (
        "answer", {"input_tokens": 10, "output_tokens": 5,
                   "cost_usd": 0.01, "model": agent.model,
                   "cache_read_input_tokens": 7,
                   "cache_creation_input_tokens": 3})
    return agent


class BaseAgentTotalCheckTests(TestCase):

    @_cfg(10.0)
    def test_refused_at_the_total_with_no_row_and_no_call(self):
        from ai_agents.models import AgentTask
        from ai_agents.spend import BudgetRefused
        _task(10.0)
        agent = _probe_agent()
        with self.assertRaises(BudgetRefused) as ctx, \
                self.assertLogs("ai_agents.base_agent", level="WARNING"):
            agent.run(x=1)
        self.assertIn("daily AI budget spent", str(ctx.exception))
        agent.provider.complete.assert_not_called()
        self.assertEqual(AgentTask.objects.count(), 1)  # only the seed

    @_cfg(10.0)
    def test_a_deep_agent_runs_at_ninety_percent(self):
        """The check is the total alone: no deep share, no estimate."""
        from ai_agents.models import AgentTask
        _task(9.0)
        agent = _probe_agent(tier="deep")
        self.assertEqual(agent.run(x=1), {"raw": "answer"})
        self.assertEqual(AgentTask.objects.filter(
            agent="probe_agent").count(), 1)

    @_cfg(10.0)
    def test_a_budget_read_error_refuses_nothing(self):
        agent = _probe_agent()
        with patch("ai_agents.spend.can_spend",
                   side_effect=RuntimeError("db gone")), \
                self.assertLogs("ai_agents.base_agent", level="WARNING"):
            self.assertEqual(agent.run(), {"raw": "answer"})

    @_cfg(10.0)
    def test_the_pretrade_sanity_agent_is_exempt(self):
        """portfolio/risk_gate.py fails OPEN when the AI check raises
        ("verdict go, scale 1.0"): gating it at the total would change
        the order path's sizing, so it keeps today's behaviour."""
        from ai_agents.agents.pretrade_sanity import PreTradeSanityAgent
        from ai_agents.base_agent import BaseAgent
        self.assertTrue(BaseAgent.total_budget_gate)
        self.assertFalse(PreTradeSanityAgent.total_budget_gate)
        _task(10.0)
        agent = PreTradeSanityAgent()
        agent.provider = MagicMock()
        agent.provider.complete.return_value = (
            '{"verdict": "go", "scale": 1.0, "concerns": [], '
            '"rationale": "ok"}', {"input_tokens": 1, "output_tokens": 1,
                                   "cost_usd": 0.0})
        out = agent.run(symbol="X", direction="BUY", entry=1, stop=0.9,
                        target=1.2, rule_name="r", regime_summary="",
                        news_summary="", rule_perf_summary="")
        self.assertEqual(out["verdict"], "go")
        agent.provider.complete.assert_called_once()

    @_cfg(10.0)
    def test_a_default_run_calls_the_provider_exactly_as_before(self):
        from ai_agents.models import AgentTask
        agent = _probe_agent()
        agent.run(x=1)
        self.assertEqual(agent.provider.complete.call_args.kwargs, {
            "system_prompt": "sys", "user_message": "context x",
            "model": agent.model, "effort": agent.effort, "record": False})
        self.assertEqual(agent.seen, {"x": 1})
        row = AgentTask.objects.get(agent="probe_agent")
        self.assertEqual(row.structured_output, {"raw": "answer"})
        self.assertEqual((row.cache_read_tokens, row.cache_write_tokens),
                         (7, 3))

    @_cfg(10.0)
    def test_source_ref_rides_to_the_provider_and_the_row(self):
        from ai_agents.models import AgentTask
        agent = _probe_agent()
        agent.run(source_ref="Orc:7:Add:x", x=1)
        self.assertEqual(agent.seen, {"x": 1},
                         "source_ref never reaches build_context")
        self.assertEqual(
            agent.provider.complete.call_args.kwargs["source_ref"],
            "Orc:7:Add:x")
        row = AgentTask.objects.get(agent="probe_agent")
        self.assertEqual(row.structured_output,
                         {"raw": "answer", "source_ref": "Orc:7:Add:x"})

    @_cfg(10.0)
    def test_source_ref_rides_on_the_failure_row(self):
        from ai_agents.models import AgentTask
        agent = _probe_agent()
        agent.provider.complete.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError), \
                self.assertLogs("ai_agents.base_agent", level="ERROR"):
            agent.run(source_ref="Orc:7:Add:x", x=1)
        row = AgentTask.objects.get(agent="probe_agent")
        self.assertFalse(row.success)
        self.assertEqual(row.structured_output, {"source_ref": "Orc:7:Add:x"})
        self.assertEqual(row.prompt_summary, "{'x': 1}")

    @_cfg(10.0)
    def test_a_billed_failure_row_carries_its_cache_columns(self):
        """A refused or truncated call raises with its usage attached; the
        failure row books its cost AND its cache tokens."""
        from ai_agents.models import AgentTask
        agent = _probe_agent()
        err = RuntimeError("declined")
        err.usage = {"input_tokens": 10, "output_tokens": 0,
                     "cost_usd": 0.02, "model": agent.model,
                     "cache_read_input_tokens": 7,
                     "cache_creation_input_tokens": 3}
        agent.provider.complete.side_effect = err
        with self.assertRaises(RuntimeError), \
                self.assertLogs("ai_agents.base_agent", level="ERROR"):
            agent.run(x=1)
        row = AgentTask.objects.get(agent="probe_agent")
        self.assertFalse(row.success)
        self.assertEqual((row.cache_read_tokens, row.cache_write_tokens),
                         (7, 3))
        self.assertEqual((row.input_tokens, row.output_tokens), (10, 0))
        self.assertAlmostEqual(float(row.cost_usd), 0.02)
        self.assertEqual(row.structured_output, {})

    @_cfg(27.0, orcs=13.0)
    def test_the_model_cannot_bill_a_core_row_to_the_orcs(self):
        """The line is decided by the CALLER's source_ref. A model that
        writes "source_ref": "Orc:…" into its own JSON (the news analyst
        reads untrusted articles) leaves it off the ledger row, and the
        call stays on the core line; run() still returns what it parsed."""
        import json
        from ai_agents.models import AgentTask
        from ai_agents.spend import spent_today
        agent = _probe_agent()
        agent.parse_response = json.loads
        agent.provider.complete.return_value = (
            '{"x": 1, "source_ref": "Orc:9:Wake:9"}',
            {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.5,
             "model": agent.model})
        out = agent.run(x=1)
        self.assertEqual(out, {"x": 1, "source_ref": "Orc:9:Wake:9"})
        row = AgentTask.objects.get(agent="probe_agent")
        self.assertEqual(row.structured_output, {"x": 1})
        self.assertAlmostEqual(spent_today("orcs"), 0.0)
        self.assertAlmostEqual(spent_today("core"), 0.5)
        # The caller's own source_ref still wins over the model's.
        agent.run(source_ref="BrainReport:4", x=1)
        self.assertEqual(
            AgentTask.objects.filter(agent="probe_agent")
            .order_by("-id").first().structured_output,
            {"x": 1, "source_ref": "BrainReport:4"})
        self.assertAlmostEqual(spent_today("orcs"), 0.0)

    def test_a_result_without_the_key_is_stored_as_it_always_was(self):
        from ai_agents.base_agent import BaseAgent
        result = {"grade": "B", "tags": ["x"]}
        self.assertIs(BaseAgent._with_source_ref(result, ""), result)
        listed = [{"source_ref": "Orc:1"}]
        self.assertIs(BaseAgent._with_source_ref(listed, ""), listed)
        self.assertIsNone(BaseAgent._with_source_ref(None, ""))

    @_cfg(27.0, orcs=13.0)
    def test_a_debate_billed_to_an_orc_lands_on_the_orcs_line(self):
        """§7.1: the debate's agents keep their names; the source_ref
        written by BaseAgent.run is what puts the row on the Orcs line."""
        from ai_agents.spend import spent_today
        agent = _probe_agent()
        agent.agent_name = "debate_executioner"
        agent.run(source_ref="Orc:7:Add:x")
        self.assertAlmostEqual(spent_today("orcs"), 0.01)
        self.assertAlmostEqual(spent_today("core"), 0.0)


# ── /ai-models/ ──────────────────────────────────────────────────────────

class AiModelsPageTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="lines_staff", password="x", is_staff=True,
            is_superuser=True)
        self.client.force_login(self.staff)

    @_cfg(15.0)
    def test_line_off_the_today_cell_is_unchanged(self):
        _task(2.5)
        r = self.client.get("/ai-models/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("$12.5 left of $15.0", html)
        self.assertIn("Orcs line off (ORC_DAILY_BUDGET_USD=0) · total stop "
                      "$15.00", html)
        self.assertEqual(r.context["budget_daily"], 15.0)
        self.assertEqual(r.context["budget_spent_today"], 2.5)
        self.assertEqual(r.context["budget_remaining"], 12.5)

    @_cfg(27.0, orcs=13.0)
    def test_line_on_shows_the_three_numbers(self):
        _task(5.0, agent="orc")
        _task(4.0, agent="critic")
        html = self.client.get("/ai-models/").content.decode()
        self.assertIn("AI $4.00 of $19.00 (= $27.00 − Orcs spent − $3.00 "
                      "floor) · Orcs $5.00 of $13.00 · total $9.00 of "
                      "$27.00", html)

    @_cfg(15.0)
    def test_the_orc_ladder_and_keys_are_read_only(self):
        from ai_agents.models import AIModelSetting
        html = self.client.get("/ai-models/").content.decode()
        self.assertIn("an unvalidated prior", html)
        for key in ("orc", "orc_confirm", "orc_question", "orc_postmortem",
                    "orc_tribunal", "orc_emperor", "orc_skeptic", "captain"):
            self.assertIn(key, html)
        from django.contrib.messages import get_messages
        r = self.client.post("/ai-models/", {
            "scope": "agent", "key": "orc", "model_id": "claude-opus-5-5",
            "effort": ""})
        self.assertIn("Unknown agent: orc",
                      [str(m) for m in get_messages(r.wsgi_request)])
        self.assertFalse(AIModelSetting.objects.exists())

    @_cfg(15.0)
    def test_the_catalog_shows_the_cache_columns(self):
        """The headers AND the cells: one model's row, read cell by cell
        from the rendered table, carries its cache price and minimum."""
        import re
        from ai_agents.catalog import MODELS
        r = self.client.get("/ai-models/")
        html = r.content.decode()
        self.assertIn("$/M cache read", html)
        self.assertIn("min cache", html)

        def cells(model_id):
            row = re.search(r"<tr>\s*<td>[^<]*<div[^>]*>" + re.escape(model_id)
                            + r"</div></td>(.*?)</tr>", html, re.S)
            self.assertIsNotNone(row, model_id)
            return [c.strip() for c in
                    re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)]

        haiku55 = cells("claude-haiku-5-5")
        self.assertEqual(haiku55[2:4], ["$0.01", "512"])
        self.assertEqual(MODELS["claude-haiku-5-5"]["cache_read"], 0.01)
        haiku45 = cells("claude-haiku-4-5")
        self.assertEqual(haiku45[2:4], ["$0.1", "4096"])
        sonnet55 = cells("claude-sonnet-5-5")
        self.assertEqual(sonnet55[:4], ["$2.0", "$10.0", "$0.1", "512"])
        by_id = {m["id"]: m for m in r.context["catalog"]}
        self.assertEqual(by_id["claude-haiku-4-5"]["min_cache_tokens"], 4096)
