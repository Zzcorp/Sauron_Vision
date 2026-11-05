"""T16, THE O2 TESTS AND THEIR HARNESS PROVE THEMSELVES (the O2 spec N7,
§1.1.7; P36, P37; 2026-11-05).

- Every TestCase of tests/orcs/test_orc_o2{a,b,c,d}_*.py inherits
  MindTestCase or MindTransactionTestCase (tests/orcs/helpers_o2.py), so
  every O2 test runs with no network, the behavioural guard and the stack
  proof.
- Every test that claims "no call" is a pair inside one method: its
  positive control (`assert_one_call`) comes before its zero-call half
  (`assert_no_call`), and no test proves an empty call list by hand.
- Every zero-call branch of T3 (test_orc_o2a_admission.py) and T10
  (test_orc_o2a_queue.py) ran: each module declares its table
  (`ZERO_CALL_CODES`, a gate's code -> the test that proves it), read here
  from the source; together they cover P36's branches. The clause binds
  from the commit that adds admission (scheduler.admit), with its tests.
- The harness itself: the network is refused; the fake client answers on
  both stream paths, scripts an error mid-stream and counts tokens apart;
  the stack proof fails a request that bypassed the gateway or its line
  check; the behavioural guard catches the Orcs' writes and only theirs;
  minds_on() opens the four gates; the K-B10 walk finds a figure in any
  format.

Run with:  python manage.py test tests.orcs.test_orc_o2a_meta
"""
import ast
import importlib
import inspect
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings

from tests.orcs.helpers_o2 import (KB10_BALANCE, KB10_QTY, KB10_R_MONEY,
                                   MIND_GATES, MINDS_LINE_USD, FakeClient,
                                   MindTestCase, MindTestMixin,
                                   MindTransactionTestCase, PreStream, Sent,
                                   fake_answer, kb10_hits, mid_stream_error,
                                   minds_on, stack_proof_errors)

TESTS = Path(__file__).resolve().parent
O2_TEST_GLOB = "test_orc_o2[abcd]_*.py"
#: This module: the claim words below are its subject, not its claims.
SELF = Path(__file__).stem
#: P36's branches, each a code with an empty call list asserted.
P36_BRANCHES = ("minds_off", "line_off", "day_cap", "triage", "spacing",
                "dead", "row_closed", "over_budget", "quiet", "merged",
                "stale")
#: T3 and T10, and the table each declares.
ZERO_CALL_MODULES = ("test_orc_o2a_admission", "test_orc_o2a_queue")
ZERO_CALL_TABLE = "ZERO_CALL_CODES"
POSITIVE = "assert_one_call"
ZERO = "assert_no_call"
#: The words of a zero-call claim, in a test's name or docstring (its
#: underscores read as spaces): "no call", "no model call", "no request",
#: "empty call list", "zero-call".
CLAIMS = re.compile(r"\bno (?:model )?(?:calls?|requests?)\b"
                    r"|\bempty call list\b|\bzero[- ]calls?\b")
SKIPS = {"skip", "skipIf", "skipUnless", "expectedFailure",
         "skipUnlessDBFeature", "skipIfDBFeature"}
GATEWAY_FILE = str(Path(settings.BASE_DIR) / "bot_program" / "orcs"
                   / "mind_gateway.py")
PLANTED_ORC_FILE = str(Path(settings.BASE_DIR) / "bot_program" / "orcs"
                       / "_planted_o2.py")


def o2_test_modules():
    return sorted(TESTS.glob(O2_TEST_GLOB))


def _calls(fn, name):
    return sorted(sub.lineno for sub in ast.walk(fn)
                  if isinstance(sub, ast.Call)
                  and isinstance(sub.func, (ast.Attribute, ast.Name))
                  and (sub.func.attr if isinstance(sub.func, ast.Attribute)
                       else sub.func.id) == name)


def _empty_by_hand(fn) -> list:
    """Assertions that a `.requests` list is empty, written by hand."""
    out = []
    for sub in ast.walk(fn):
        if not (isinstance(sub, ast.Call) and isinstance(sub.func,
                                                         ast.Attribute)):
            continue
        name, args = sub.func.attr, sub.args
        text = [ast.unparse(a) for a in args]
        if not any("requests" in t for t in text):
            continue
        if name == "assertFalse" or (
                name == "assertEqual" and len(args) == 2 and (
                    {"[]", "0"} & set(text))):
            out.append(sub.lineno)
    return out


def pair_problems(tree, *, claims=True) -> list:
    """Every test method of the module's classes: a zero-call half needs
    its positive control before it; a claim in the name or docstring
    needs the pair; an empty list is never proven by hand."""
    out = []
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)
                   and n.name.startswith("test")):
            where = f"{cls.name}.{fn.name}"
            ones, zeros = _calls(fn, POSITIVE), _calls(fn, ZERO)
            if zeros and (not ones or ones[0] > zeros[0]):
                out.append(f"{where}: a zero-call half before its positive "
                           f"control")
            text = (fn.name.replace("_", " ") + " "
                    + (ast.get_docstring(fn) or "")).lower()
            if claims and CLAIMS.search(text) and not (ones and zeros):
                out.append(f"{where}: claims no call without the pair")
            if _empty_by_hand(fn):
                out.append(f"{where}: an empty call list asserted by hand; "
                           f"use assert_no_call")
    return out


def zero_call_table(tree):
    """The module's ZERO_CALL_CODES literal: {code: test name}, or None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == ZERO_CALL_TABLE
                for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def _decorators(node) -> set:
    out = set()
    for d in node.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        out.add(target.attr if isinstance(target, ast.Attribute)
                else getattr(target, "id", ""))
    return out


def table_problems(tree, table) -> list:
    """Each code's test exists in a TestCase of the module, is not
    skipped, names the code and holds its pair in order."""
    methods = {}
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
            methods[fn.name] = (cls, fn)
            methods[f"{cls.name}.{fn.name}"] = (cls, fn)
    out = []
    for code, test in table.items():
        if test not in methods:
            out.append(f"{code}: no test {test}")
            continue
        cls, fn = methods[test]
        if (_decorators(cls) | _decorators(fn)) & SKIPS:
            out.append(f"{code}: {test} may be skipped")
        consts = {c.value for c in ast.walk(fn) if isinstance(c, ast.Constant)}
        if code not in consts:
            out.append(f"{code}: {test} never names its code")
        ones, zeros = _calls(fn, POSITIVE), _calls(fn, ZERO)
        if not (ones and zeros and ones[0] < zeros[0]):
            out.append(f"{code}: {test} holds no pair in order")
    return out


class EveryO2TestRunsUnderTheHarnessTests(MindTestCase):

    def test_every_testcase_inherits_a_mind_base(self):
        found = {}
        for path in o2_test_modules():
            mod = importlib.import_module(f"tests.orcs.{path.stem}")
            for _name, obj in vars(mod).items():
                if inspect.isclass(obj) and issubclass(
                        obj, unittest.TestCase) and \
                        obj.__module__ == mod.__name__:
                    found[f"{path.stem}.{obj.__name__}"] = obj
        self.assertIn(f"{SELF}.{type(self).__name__}", found,
                      "the scan sees this very module")
        for name, cls in sorted(found.items()):
            with self.subTest(name):
                self.assertTrue(issubclass(cls, (MindTestCase,
                                                 MindTransactionTestCase)))

    def test_every_claim_holds_its_pair(self):
        modules = o2_test_modules()
        self.assertIn(Path(__file__).resolve(), modules)
        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(path.stem):
                self.assertEqual(pair_problems(tree,
                                               claims=path.stem != SELF), [])

    def test_every_zero_call_branch_of_t3_and_t10_ran(self):
        present = [m for m in ZERO_CALL_MODULES
                   if (TESTS / f"{m}.py").exists()]
        if not present:
            # binds from the commit that adds admission, with its proofs
            try:
                scheduler = importlib.import_module(
                    "bot_program.orcs.scheduler")
            except ImportError:
                scheduler = None
            self.assertFalse(hasattr(scheduler, "admit"),
                             "admission exists: T3 and T10 must declare "
                             f"their {ZERO_CALL_TABLE}")
            return
        self.assertEqual(present, list(ZERO_CALL_MODULES),
                         "T3 and T10 arrive together")
        covered = set()
        for name in ZERO_CALL_MODULES:
            path = TESTS / f"{name}.py"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            table = zero_call_table(tree)
            with self.subTest(name):
                self.assertIsInstance(table, dict, ZERO_CALL_TABLE)
                self.assertEqual(table_problems(tree, table), [])
            covered |= set(table or {})
        self.assertEqual(set(P36_BRANCHES) - covered, set(),
                         "every branch of P36 is proven")


class TheMetaRulesCanFailTests(MindTestCase):
    """The rules above, on planted test modules."""

    BAD = '''
class T:
    def test_gate_off_makes_no_call(self):
        run()
        self.assertEqual(code, "minds_off")

    def test_references_no_callable_of_the_order_path(self):
        """Not a claim: its word is callable."""

    def test_inverted(self):
        self.assert_no_call(code="line_off", got=x)
        self.assert_one_call()

    def test_by_hand(self):
        self.assert_one_call()
        self.assertEqual(self.fake.requests, [])
'''
    GOOD = '''
ZERO_CALL_CODES = {"minds_off": "test_pair"}

class T:
    @staticmethod
    def helper():
        pass

    def test_pair(self):
        self.assert_one_call()
        self.assert_no_call(code="minds_off", got=got)
'''

    def test_a_claim_without_its_pair_is_found(self):
        problems = pair_problems(ast.parse(self.BAD))
        self.assertEqual(len(problems), 3, problems)
        self.assertEqual(pair_problems(ast.parse(self.GOOD)), [])

    def test_a_table_that_names_a_missing_or_skipped_test_is_found(self):
        tree = ast.parse(self.GOOD)
        self.assertEqual(zero_call_table(tree), {"minds_off": "test_pair"})
        self.assertEqual(table_problems(tree, zero_call_table(tree)), [])
        self.assertEqual(len(table_problems(tree, {"dead": "test_gone"})), 1)
        self.assertEqual(len(table_problems(tree, {"dead": "test_pair"})), 1,
                         "a test that never names the code")
        skipped = ast.parse(self.GOOD.replace(
            "    def test_pair",
            "    @skipUnless(pg, 'pg')\n    def test_pair"))
        self.assertEqual(len(table_problems(skipped, {"minds_off":
                                                      "test_pair"})), 1)


class TheNetworkIsRefusedTests(MindTestCase):

    def test_sockets_requests_and_the_sdk_client_are_refused(self):
        import socket
        import urllib.request

        import anthropic
        import requests
        attempts = (
            lambda: socket.create_connection(("127.0.0.1", 9), timeout=1),
            lambda: urllib.request.urlopen("http://127.0.0.1:9/", timeout=1),
            lambda: requests.get("http://127.0.0.1:9/"),
            lambda: requests.post("http://127.0.0.1:9/"),
            lambda: requests.Session().request("GET", "http://127.0.0.1:9/"),
            lambda: anthropic.Anthropic(api_key="sk-test-not-a-key"),
        )
        for n, attempt in enumerate(attempts):
            with self.subTest(n), self.assertRaises(Exception) as cm:
                attempt()
            self.assertIn("N7", str(cm.exception) + str(
                cm.exception.__context__ or ""), n)

    def test_every_provider_gets_the_fake(self):
        from ai_agents.providers.claude_provider import ClaudeProvider
        provider = ClaudeProvider()
        self.assertIs(provider.client, self.fake)
        self.assertIs(provider._get_client(), self.fake)


class TheFakeClientTests(MindTestCase):

    def _model(self):
        from ai_agents.catalog import ORC_LADDER_V1
        return {r["rung"]: r["model"] for r in ORC_LADDER_V1}["r0"]

    def _done(self):
        """These requests were sent from the test on purpose, never from
        the gateway: the stack proof says so, then they are let go."""
        self.assertEqual(len(stack_proof_errors(self.requests,
                                                self.spend_calls)),
                         len(self.requests))
        del self.requests[:]

    def test_both_stream_paths_are_recorded_with_their_stack(self):
        from ai_agents.providers.claude_provider import ClaudeProvider
        self.use_fake(fake_answer({"action": "hold"}),
                      fake_answer(text="the second"))
        text, usage = ClaudeProvider().complete(
            "sys", "q", model=self._model(), agent_name="orc",
            source_ref="Orc:1:Wake:1:r0", line="orcs",
            client_refusal_rerun=False, max_tokens=8000)
        self.assertEqual(text, '{"action": "hold"}')
        text, _ = ClaudeProvider().complete(
            "", "", model=self._model(), effort="low", agent_name="orc",
            line="orcs", client_refusal_rerun=False, max_tokens=8000,
            system_blocks=[{"text": "S", "cache_ttl": "1h"}],
            shared_user_blocks=[{"text": "MK", "cache_ttl": "1h"}],
            private_user_blocks=[{"text": "PS", "cache_ttl": None}],
            turn_effort="low")
        self.assertEqual(text, "the second")
        self.assertEqual([r.path for r in self.requests], ["plain", "beta"])
        here = "test_both_stream_paths_are_recorded_with_their_stack"
        for r in self.requests:
            self.assertIn(here, [f.name for f in r.stack])
            self.assertIn("complete", [f.name for f in r.stack])
        self.assertEqual(self.requests[0].texts(), ["sys", "q"])
        self.assertEqual(self.requests[1].texts(), ["S", "MK", "PS"])
        self.assertLess(self.requests[0].seq, self.requests[1].seq)
        self.assertEqual(usage["input_tokens"], 1200)
        self._done()

    def test_an_error_event_mid_stream_and_an_error_before_it(self):
        """The provider re-sends the whole request after a mid-stream
        overloaded event (two attempts by default): the fake records
        both sends, the reason O2 calls it once (A.21)."""
        from ai_agents.providers.claude_provider import ClaudeProvider
        err = mid_stream_error()
        import anthropic
        self.assertIsInstance(err.exc, anthropic.APIStatusError)
        self.assertIn("overloaded_error", str(err.exc))
        self.use_fake(err, fake_answer(text="after the retry"))
        with patch("ai_agents.providers.claude_provider.time.sleep"):
            text, _ = ClaudeProvider().complete(
                "s", "q", model=self._model(), agent_name="orc",
                client_refusal_rerun=False, max_tokens=8000)
        self.assertEqual(text, "after the retry")
        self.assertEqual(len(self.requests), 2)
        self.use_fake(PreStream(ValueError("a request the API refused")))
        with self.assertRaises(ValueError):
            ClaudeProvider().complete("s", "q", model=self._model(),
                                      agent_name="orc", max_tokens=8000)
        self.assertEqual(len(self.requests), 3, "sent, then refused")
        self._done()

    def test_token_counts_go_to_their_own_list(self):
        from ai_agents.providers.claude_provider import ClaudeProvider
        n = ClaudeProvider().count_tokens(model=self._model(),
                                          system_prompt="S",
                                          user_message="the dossier")
        self.assertEqual(n, self.fake.count_answer)
        self.assertEqual(len(self.count_requests), 1)
        self.assertEqual(self.count_requests[0].texts(), ["S", "the dossier"])
        self.assertEqual([r.path for r in self.count_requests + self.requests],
                         ["count"], "a count is never a messages request")


class TheStackProofTests(MindTestCase):
    """A request passes only when it was sent from inside
    mind_gateway.call, after can_spend(line="orcs", total_only=False)
    answered allowed in that same call. The gateway does not exist yet:
    a planted function stands in for it, compiled under its file name."""

    GATEWAY = '''
def call(ask=True, line="orcs", total_only=False, send=True):
    from ai_agents import spend
    from ai_agents.providers.claude_provider import ClaudeProvider
    if ask:
        spend.can_spend(tier="balanced", estimated_usd=0.2, line=line,
                        total_only=total_only)
    if not send:
        return None
    provider = ClaudeProvider()
    return provider.complete("s", "q", model=MODEL, agent_name="orc",
                             source_ref="Orc:1:Wake:1:r0", line="orcs",
                             client_refusal_rerun=False, max_tokens=8000)


def ask_only():
    from ai_agents import spend
    spend.can_spend(tier="balanced", estimated_usd=0.2, line="orcs")
'''

    def setUp(self):
        from ai_agents.catalog import ORC_LADDER_V1
        ns = {"MODEL": ORC_LADDER_V1[1]["model"]}
        exec(compile(self.GATEWAY, GATEWAY_FILE, "exec"), ns)  # noqa: S102
        self.call, self.ask_only = ns["call"], ns["ask_only"]
        minds_on(self)

    def _proof(self):
        out = stack_proof_errors(self.requests, self.spend_calls)
        del self.requests[:]
        del self.spend_calls[:]
        return out

    def test_a_request_through_the_gateway_after_an_allowed_check(self):
        self.call()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self._proof(), [])

    def test_every_way_round_the_check_is_found(self):
        cases = {
            "no check": dict(ask=False),
            "the total only": dict(total_only=True),
            "the core line": dict(line="core"),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                self.call(**kwargs)
                self.assertEqual(len(self._proof()), 1)
        with self.subTest("a check in an earlier call"):
            self.call(send=False)
            self.call(ask=False)
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(len(self._proof()), 1)

    def test_a_refused_check_is_found(self):
        from django.test import override_settings
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}):
            self.call()
        self.assertFalse(self.spend_calls[0].result[0], "the line is off")
        self.assertEqual(len(self._proof()), 1)

    def test_a_request_from_outside_the_gateway_is_found(self):
        from ai_agents.providers.claude_provider import ClaudeProvider
        self.ask_only()
        ClaudeProvider().complete("s", "q", model=ORC_R0(), agent_name="orc",
                                  max_tokens=8000)
        self.assertEqual(self._proof(), ["request 1 was not sent through "
                                         "mind_gateway.call (plain path)"])


def ORC_R0():
    from ai_agents.catalog import ORC_LADDER_V1
    return ORC_LADDER_V1[1]["model"]


class TheBehaviouralGuardTests(MindTestCase):
    """The guard records what the Orcs' own code changed (a planted
    function, compiled under a file name of the package), never the
    test's fixtures or the care."""

    ORC_CODE = '''
def write(orc, seat, trade, Orc, OrcSeat, AssetBotTrade):
    orc.stood_down = True
    orc.save(update_fields=["stood_down"])
    Orc.objects.filter(pk=orc.pk).update(commission="trail")
    orc.stop_level = 101
    Orc.objects.bulk_update([orc], ["stop_level"])
    seat.level = 2
    seat.save()
    trade.metadata = {**(trade.metadata or {}), "care": {"soft_stop": 1}}
    trade.save(update_fields=["metadata"])
    AssetBotTrade.objects.filter(pk=trade.pk).update(stop_loss=95)


def stamp(trade):
    trade.metadata = {**(trade.metadata or {}), "orc": {"idea": 1}}
    trade.save(update_fields=["metadata"])


def plan(orc):
    orc.plan = {"v": 1}
    orc.save(update_fields=["plan"])
'''

    def setUp(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc, OrcSeat
        from tests.orcs.helpers import _config, _row, _user
        ns = {}
        code = compile(self.ORC_CODE, PLANTED_ORC_FILE, "exec")
        exec(code, ns)  # noqa: S102 — a planted function of the package
        self.ns = ns
        user = _user("o2_guard")
        cfg = _config(user)
        self.trade = _row(cfg)
        self.seat = OrcSeat.objects.create(venue="paper", asset_class="crypto")
        self.orc = Orc.objects.create(
            seat=self.seat, user=user, config=cfg, root_trade=self.trade,
            symbol=self.trade.symbol, side=self.trade.side,
            asset_class=self.trade.asset_class)
        self.models = (Orc, OrcSeat, AssetBotTrade)

    def test_the_orcs_writes_with_power_are_caught(self):
        self.ns["write"](self.orc, self.seat, self.trade, *self.models)
        found = list(self.mind_guard.violations)
        del self.mind_guard.violations[:]
        self.assertEqual(len(found), 6, found)
        for word in ("stood_down", "commission", "stop_level", "level",
                     "a metadata key other than \"orc\"", "stop_loss"):
            self.assertTrue(any(word in v for v in found), word)
        self.assertTrue(all("_planted_o2.py" in v for v in found))

    def test_the_stamp_and_the_plan_are_not_power(self):
        self.ns["stamp"](self.trade)
        self.ns["plan"](self.orc)
        self.assertEqual(self.mind_guard.violations, [])

    def test_the_tests_own_writes_are_not_the_orcs(self):
        from bot_program.orcs.models import Orc
        self.orc.stood_down = True
        self.orc.save()
        Orc.objects.filter(pk=self.orc.pk).update(commission="trail")
        self.trade.stop_loss = 97
        self.trade.metadata = {"care": {}}
        self.trade.save()
        self.seat.level = 1
        self.seat.save()
        self.assertEqual(self.mind_guard.violations, [])


class TheGatesAndThePairTests(MindTestCase):

    def test_minds_on_opens_the_four_gates(self):
        from ai_agents import spend
        from core.platform_control import is_component_enabled
        self.assertEqual(spend.orc_line_cap(), 0.0, "the line ships at 0")
        allowed, why = spend.can_spend(line="orcs", estimated_usd=0.2)
        self.assertFalse(allowed)
        del self.spend_calls[:]
        minds_on(self)
        self.assertEqual([is_component_enabled(k) for k in MIND_GATES],
                         [True, True, True])
        self.assertEqual(spend.orc_line_cap(), MINDS_LINE_USD)
        allowed, why = spend.can_spend(line="orcs", estimated_usd=0.2)
        self.assertTrue(allowed, why)

    def test_the_zero_call_half_needs_its_positive_control(self):
        fake = FakeClient()
        half = getattr(self, ZERO)   # called by name: the rule's own test
        with self.assertRaises(AssertionError):
            half(fake)
        fake.messages.stream(model="m", messages=[])
        self.assert_one_call(fake)
        half(fake)
        fake.messages.stream(model="m", messages=[])
        with self.assertRaises(AssertionError):
            half(fake)
        with self.assertRaises(AssertionError):
            self.assert_one_call(FakeClient())


class TheAccountFiguresWalkTests(MindTestCase):

    def _req(self, text):
        return Sent("plain", {"system": [{"type": "text", "text": "S"}],
                              "messages": [{"role": "user",
                                            "content": text}]},
                    [], 0, None)

    def test_a_figure_is_found_in_any_format(self):
        self.assertEqual((KB10_BALANCE, KB10_R_MONEY, KB10_QTY),
                         tuple(map(type(KB10_QTY), ("123456.78", "987.65",
                                                    "4321"))))
        for text in ("a balance of 123456.78", "123,456.78 on the account",
                     "about 123457", "1R is 987.65", "R near 987.7",
                     "a size of 4321", "4,321 units"):
            with self.subTest(text):
                self.assertEqual(len(kb10_hits([self._req(text)])), 1)
        for text in ("price 102.25, ATR(1h) 1.4", "1.5R from the entry",
                     "S4h-L1 (2,612.00)", "a 12% move"):
            with self.subTest(text):
                self.assertEqual(kb10_hits([self._req(text)]), [])

    def test_the_mixins_walk_reads_both_lists(self):
        self.count_requests.append(self._req("4321 units"))
        with self.assertRaises(AssertionError):
            self.assert_no_account_figure()
        del self.count_requests[:]
        self.assert_no_account_figure()


class TheMixinsBaseTests(MindTestCase):

    def test_the_two_bases_are_the_mixin_on_djangos_cases(self):
        from django.test import TestCase, TransactionTestCase
        self.assertTrue(issubclass(MindTestCase, MindTestMixin))
        self.assertTrue(issubclass(MindTestCase, TestCase))
        self.assertTrue(issubclass(MindTransactionTestCase, MindTestMixin))
        self.assertTrue(issubclass(MindTransactionTestCase,
                                   TransactionTestCase))
        self.assertFalse(issubclass(MindTransactionTestCase, TestCase))

    def test_a_class_whose_setup_skips_super_is_still_guarded(self):
        class Bare(MindTestCase):
            def setUp(self):
                self.ran = True

            def test_x(self):
                import socket
                with self.assertRaises(AssertionError):
                    socket.create_connection(("127.0.0.1", 9), timeout=1)

        result = unittest.TestResult()
        Bare("test_x").run(result)
        self.assertEqual((result.testsRun, result.errors, result.failures),
                         (1, [], []))

    def test_a_dirty_test_fails_in_its_teardown(self):
        class Dirty(MindTestCase):
            def test_x(self):
                self.requests.append(SimpleNamespace(
                    stack=[], gateway=None, seq=1, path="plain"))

        result = unittest.TestResult()
        Dirty("test_x").run(result)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("not sent through mind_gateway.call",
                      result.failures[0][1])
