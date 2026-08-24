"""Every dollar that leaves through the LLM lands in ONE ledger.

The operator's Anthropic console read $29.49 while the platform admitted
to roughly half of it. The ledger (AgentTask) was written by
BaseAgent.run() alone — and all seven brain modules call the provider
directly, so the platform's single largest recurring spender was
invisible to spent_today(), to the /ai-models/ readout, and to the daily
budget whose entire purpose is to govern it. Each brain module kept a
private cost column that displayed correctly on its own page, which is
how two true-looking numbers disagreed for a week.

The fix moves the ledger write INTO the provider — the one function the
money actually leaves through — so the next module cannot repeat the
bypass. What is pinned here:

  1. A provider call writes exactly one attributed AgentTask row, and
     the cost on it is the catalog's own arithmetic.
  2. record=False writes nothing — and only the callers that write their
     own richer row (BaseAgent.run, the two inline agents) may pass it.
  3. Every direct-provider call site in brain/ carries an agent_name, so
     the ledger reads like the platform: named spenders.
  4. spent_today() sees provider-recorded spend — the budget governs the
     whole burn now, which is also WHY the default ceiling moved 5 -> 15:
     an unchanged 5 against a suddenly-complete ledger would halt the
     brain mid-afternoon as a side effect of honest accounting.
  5. backfill_llm_ledger repairs history from the brain's own cost
     columns, idempotently, without ever double-copying a row the
     provider recorded live.

Run with:  python manage.py test tests.test_llm_ledger_truth
"""
import re
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

REPO = Path(__file__).resolve().parent.parent

# The direct-provider call sites and the attribution each must carry.
# The brain sites pass agent.agent_name — the instance's own canonical
# spelling — because the first cut of this wave used string literals and
# two of eight promptly drifted from the names the platform actually
# grades by ("position_review" vs the agent's own "position_reviewer").
# A new bypass caller belongs in this table — that is the convention this
# file exists to enforce.
BYPASS_SITES = {
    "brain/synthesizer.py": "agent.agent_name",
    "brain/critic.py": "agent.agent_name",
    "brain/strategist.py": "agent.agent_name",
    "brain/strategy_generator.py": "agent.agent_name",
    "brain/earnings_reviewer.py": "agent.agent_name",
    "brain/position_review_agent.py": "agent.agent_name",
    "brain/research_agent.py": "agent.agent_name",
    "ai_agents/consensus.py": '"consensus"',
}

# The only files allowed to opt out of the provider's ledger write —
# each writes its own, richer AgentTask row.
RECORD_FALSE_ALLOWED = {"ai_agents/base_agent.py", "ai_agents/tasks.py"}

# Packages whose sources are swept by the convention scans. tests/ is
# deliberately absent: this very file contains the strings it polices.
SCAN_DIRS = ("ai_agents", "brain", "dashboard", "bot_program", "core",
             "signals", "portfolio", "market_data", "scraping", "alerts",
             "strategies", "backtester", "instruments", "indicators")


def _client_returning(text="ok", input_tokens=1000, output_tokens=500):
    block = MagicMock()
    block.type = "text"
    block.text = text
    client = MagicMock()
    response = MagicMock(
        content=[block],
        usage=MagicMock(input_tokens=input_tokens,
                        output_tokens=output_tokens),
    )
    response.stop_reason = "end_turn"
    (client.messages.stream.return_value.__enter__
     .return_value.get_final_message.return_value) = response
    return client


class ProviderLedgerTests(TestCase):
    def _complete(self, **kwargs):
        from ai_agents.providers.claude_provider import ClaudeProvider
        provider = ClaudeProvider()
        with patch.object(provider, "_get_client",
                          return_value=_client_returning()):
            return provider.complete("sys", "the question", **kwargs)

    def test_a_call_writes_one_attributed_row_with_the_catalog_cost(self):
        from ai_agents.catalog import pricing_for
        from ai_agents.models import AgentTask

        _, usage = self._complete(model="claude-opus-5",
                                  agent_name="sauron_mind")

        rows = list(AgentTask.objects.all())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.agent, "sauron_mind")
        self.assertEqual(row.model, "claude-opus-5")
        self.assertEqual(row.input_tokens, 1000)
        self.assertEqual(row.output_tokens, 500)
        p = pricing_for("claude-opus-5")
        expected = round((1000 * p["input"] + 500 * p["output"]) / 1e6, 6)
        self.assertEqual(float(row.cost_usd), expected)
        self.assertEqual(usage["cost_usd"], expected)

    def test_record_false_writes_nothing(self):
        from ai_agents.models import AgentTask
        self._complete(model="claude-opus-5", record=False)
        self.assertFalse(AgentTask.objects.exists())

    def test_an_unattributed_call_is_still_ledgered(self):
        """A missing name must never mean a missing dollar — the failure
        mode this wave ends is spend that vanishes, not spend that is
        badly labelled."""
        from ai_agents.models import AgentTask
        self._complete(model="claude-opus-5")
        row = AgentTask.objects.get()
        self.assertEqual(row.agent, "unattributed")

    def test_a_ledger_failure_does_not_kill_the_call(self):
        """The fence: a broken ledger under-counts loudly; it must not
        turn a paid, successful generation into an exception."""
        from ai_agents.models import AgentTask
        with patch.object(AgentTask.objects, "create",
                          side_effect=RuntimeError("db gone")), \
             self.assertLogs("ai_agents.providers.claude_provider",
                             level="ERROR"):
            text, usage = self._complete(model="claude-opus-5")
        self.assertEqual(text, "ok")
        self.assertGreater(usage["cost_usd"], 0)

    def test_base_agent_run_yields_exactly_one_row(self):
        """BaseAgent passes record=False and writes its own richer row —
        without the opt-out every classic agent call would ledger twice
        and the budget would exhaust at half the real spend."""
        from ai_agents.agents.anomaly_detector import AnomalyDetectorAgent
        from ai_agents.models import AgentTask

        agent = AnomalyDetectorAgent()
        with patch.object(agent.provider, "_get_client",
                          return_value=_client_returning(
                              text='{"anomalies": []}')):
            agent.run(market_data="snapshot")
        self.assertEqual(AgentTask.objects.count(), 1)
        self.assertEqual(AgentTask.objects.get().agent, "anomaly_detector")

    def test_the_ledger_reaches_the_daily_budget(self):
        from ai_agents.spend import spent_today
        before = spent_today()
        self._complete(model="claude-opus-5", agent_name="sauron_mind")
        self.assertGreater(spent_today(), before)

    def test_a_refused_generation_is_still_ledgered(self):
        """Anthropic bills a refusal; a ledger that only counts the calls
        that went well is the same under-reporting one failure mode over.
        The exception also carries the usage, so record=False callers can
        book the cost in their own failure rows."""
        from ai_agents.models import AgentTask
        from ai_agents.providers.claude_provider import ClaudeProvider

        client = _client_returning(text="")
        (client.messages.stream.return_value.__enter__
         .return_value.get_final_message.return_value
         ).stop_reason = "refusal"
        provider = ClaudeProvider()
        with patch.object(provider, "_get_client", return_value=client):
            with self.assertRaises(RuntimeError) as ctx:
                provider.complete("sys", "q", model="claude-opus-5",
                                  agent_name="sauron_mind")
        row = AgentTask.objects.get()
        self.assertFalse(row.success)
        self.assertGreater(float(row.cost_usd), 0)
        self.assertIn("declined", row.error)
        self.assertGreater(ctx.exception.usage["cost_usd"], 0)

    def test_a_parse_crash_still_books_the_billed_call(self):
        """parse_response fails AFTER the generation was paid for — the
        failure row must carry the real cost, not a $0 that undercounts."""
        from ai_agents.agents.anomaly_detector import AnomalyDetectorAgent
        from ai_agents.models import AgentTask

        agent = AnomalyDetectorAgent()
        with patch.object(agent.provider, "_get_client",
                          return_value=_client_returning(text="not json")), \
             patch.object(agent, "parse_response",
                          side_effect=ValueError("bad shape")), \
             self.assertRaises(ValueError):
            agent.run(market_data="snapshot")
        row = AgentTask.objects.get()
        self.assertFalse(row.success)
        self.assertGreater(float(row.cost_usd), 0,
                           "the call was billed; the row must say so")

    def test_a_source_ref_rides_into_the_ledger_row(self):
        from ai_agents.models import AgentTask
        self._complete(model="claude-opus-5", agent_name="research",
                       source_ref="ResearchMessage:42")
        row = AgentTask.objects.get()
        self.assertEqual(row.structured_output,
                         {"source_ref": "ResearchMessage:42"})


class CallSiteConventionTests(TestCase):
    """Source-pinned, because the original defect WAS a convention that
    only lived in people's heads: per-caller ledger writes that six
    modules never made."""

    @staticmethod
    def _scan_files():
        for d in SCAN_DIRS:
            for p in (REPO / d).glob("**/*.py"):
                rel = p.relative_to(REPO).as_posix()
                if "/migrations/" in rel:
                    continue
                yield rel, p.read_text(encoding="utf-8", errors="replace")

    def test_every_bypass_site_carries_its_attribution(self):
        for rel, expected in BYPASS_SITES.items():
            src = (REPO / rel).read_text(encoding="utf-8")
            for m in re.finditer(r"provider\.complete\(", src):
                window = src[m.start():m.start() + 500]
                self.assertIn(f"agent_name={expected}", window,
                              f"{rel}: a provider.complete call without "
                              f"its attribution")

    def test_no_bypass_caller_exists_outside_the_table(self):
        """Completeness: the table cannot silently lag reality — a NEW
        direct caller fails the suite until it is listed and attributed.
        This is the test the original defect never had."""
        known = set(BYPASS_SITES) | RECORD_FALSE_ALLOWED
        offenders = [
            rel for rel, src in self._scan_files()
            if "provider" not in rel  # the providers define complete()
            and re.search(r"\bprovider\.complete\(|_provider\.complete\(",
                          src)
            and rel not in known
        ]
        self.assertEqual(offenders, [],
                         "a direct provider.complete caller is not in "
                         "BYPASS_SITES/RECORD_FALSE_ALLOWED — its spend "
                         "may be unattributed")

    def test_record_false_stays_inside_the_sanctioned_files(self):
        """Plain-token scan, deliberately: the first cut anchored the
        regex to the call paren and nested parentheses in an argument
        list blinded it to the exact shape it policed."""
        offenders = [
            rel for rel, src in self._scan_files()
            if rel not in RECORD_FALSE_ALLOWED
            and "providers/" not in rel  # the signature defines the kwarg
            and re.search(r"record\s*=\s*False", src)
        ]
        self.assertEqual(offenders, [],
                         "record=False outside the files that write their "
                         "own ledger row re-opens the invisible-spend hole")

    def test_the_sanctioned_files_really_use_their_exemption(self):
        """An allowlist entry that matches nothing is a hole waiting to
        be misread as coverage."""
        for rel in RECORD_FALSE_ALLOWED:
            src = (REPO / rel).read_text(encoding="utf-8")
            self.assertRegex(src, r"record\s*=\s*False",
                             f"{rel} is allowlisted but never opts out")

    def test_the_default_budget_matches_the_complete_ledger(self):
        """5 governed half the burn; 15 governs all of it. If this moves
        again it should move on purpose, with the arithmetic re-done.
        The restore is a registered cleanup so a failing assertion cannot
        leave a reloaded module (with a test-mangled env) in sys.modules
        for every later test."""
        import importlib
        import os
        from unittest import mock
        import ai_agents.spend as spend
        self.addCleanup(importlib.reload, spend)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_DAILY_BUDGET_USD", None)
            importlib.reload(spend)
            self.assertEqual(spend.DEFAULT_DAILY_BUDGET_USD, 15.0)


class BackfillTests(TestCase):
    def _report(self, cost, when=None, tokens=(100, 50)):
        from django.utils import timezone
        from brain.models import BrainReport
        row = BrainReport.objects.create(
            tokens_in=tokens[0], tokens_out=tokens[1],
            cost_usd=Decimal(str(cost)))
        if when:
            BrainReport.objects.filter(pk=row.pk).update(created_at=when)
            row.refresh_from_db()
        return row

    def test_history_lands_once_with_its_own_timestamp(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        from ai_agents.models import AgentTask

        old = timezone.now() - timedelta(days=3)
        self._report("0.14", when=old)

        call_command("backfill_llm_ledger", verbosity=0)
        row = AgentTask.objects.get(agent="sauron_mind")
        self.assertEqual(float(row.cost_usd), 0.14)
        self.assertLess(abs((row.created_at - old).total_seconds()), 2,
                        "the money left three days ago, not today")

        call_command("backfill_llm_ledger", verbosity=0)
        self.assertEqual(AgentTask.objects.filter(
            agent="sauron_mind").count(), 1, "re-running must not double")

    def test_one_generator_call_fanned_over_proposals_books_once(self):
        """The generator stamps ONE call's full cost onto EVERY proposal
        it persists — up to three. Copied row-for-row, a $0.90 call
        backfills as $2.70 and the markers make the inflation permanent."""
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        from ai_agents.models import AgentTask
        from brain.generator_models import GeneratedSetupProposal

        base = timezone.now() - timedelta(days=2)
        for i in range(3):  # three siblings of one $0.90 call
            row = GeneratedSetupProposal.objects.create(
                cost_usd=Decimal("0.90"), tokens_in=9000, tokens_out=1200)
            GeneratedSetupProposal.objects.filter(pk=row.pk).update(
                created_at=base + timedelta(seconds=i))
        # A different call ten minutes later, same table.
        other = GeneratedSetupProposal.objects.create(
            cost_usd=Decimal("0.40"), tokens_in=4000, tokens_out=600)
        GeneratedSetupProposal.objects.filter(pk=other.pk).update(
            created_at=base + timedelta(minutes=10))

        call_command("backfill_llm_ledger", verbosity=0)
        rows = AgentTask.objects.filter(agent="strategy_generator")
        self.assertEqual(rows.count(), 2, "two calls, two rows")
        self.assertEqual(sorted(float(r.cost_usd) for r in rows),
                         [0.40, 0.90])

    def test_a_row_a_live_ledger_entry_references_is_skipped(self):
        """The research pending row is written BEFORE the call that pays
        for it, so it predates the live ledger row and slides under any
        timestamp cut — the source_ref linkage is what catches it."""
        from decimal import Decimal as D

        from django.core.management import call_command

        from django.contrib.auth import get_user_model

        from ai_agents.models import AgentTask
        from brain.research_models import ResearchConversation, ResearchMessage

        conv = ResearchConversation.objects.create(
            user=get_user_model().objects.create_user("ledger_ask"))
        msg = ResearchMessage.objects.create(
            conversation=conv, role="assistant", content="answer",
            cost_usd=D("0.21"))
        AgentTask.objects.create(
            agent="research", provider="claude", model="claude-opus-5",
            prompt_summary="live", cost_usd=D("0.21"),
            structured_output={"source_ref": f"ResearchMessage:{msg.pk}"})

        call_command("backfill_llm_ledger", verbosity=0)
        self.assertEqual(AgentTask.objects.filter(agent="research").count(),
                         1, "the live row is the only row")

    def test_backfilled_rows_carry_the_source_model_not_unknown(self):
        from django.core.management import call_command

        from ai_agents.models import AgentTask
        from brain.models import BrainReport

        BrainReport.objects.create(tokens_in=100, tokens_out=50,
                                   cost_usd=Decimal("0.05"),
                                   model_used="claude-opus-5")
        call_command("backfill_llm_ledger", verbosity=0)
        self.assertEqual(AgentTask.objects.get(agent="sauron_mind").model,
                         "claude-opus-5")

    def test_rows_the_provider_recorded_live_are_never_copied(self):
        """After the fix ships, the synthesizer's calls land in the
        ledger at call time AND in BrainReport — a backfill that copied
        the report row too would double every future run."""
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        from ai_agents.models import AgentTask

        # The live ledger row the provider wrote at call time...
        live = AgentTask.objects.create(
            agent="sauron_mind", provider="claude", model="claude-opus-5",
            prompt_summary="live", cost_usd=Decimal("0.10"))
        # ...and the BrainReport row the same call produced, minutes later.
        self._report("0.10", when=live.created_at + timedelta(minutes=1))
        # Plus one genuinely pre-fix report.
        self._report("0.20", when=live.created_at - timedelta(days=1))

        call_command("backfill_llm_ledger", verbosity=0)
        costs = sorted(float(r.cost_usd) for r in
                       AgentTask.objects.filter(agent="sauron_mind"))
        self.assertEqual(costs, [0.10, 0.20],
                         "only the pre-fix history may be copied")
