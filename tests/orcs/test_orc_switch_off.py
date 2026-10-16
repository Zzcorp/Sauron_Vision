"""HARD RULE 1 (spec §11, O1): with the `orcs` switch OFF the platform's
behaviour and its outbound requests are byte-identical to before; with it
ON, a row that has no Orc is managed exactly as before; no order path,
stop, size, gate or reviewer changes. The Orcs import no order path and no
model, a birth makes no broker call, and every hook is fenced.

Run with:  python manage.py test tests.orcs.test_orc_switch_off
"""
import ast
import inspect
import json
import os
from contextlib import ExitStack
from datetime import datetime
from datetime import timezone as dt_tz
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from tests.orcs.helpers import ROUTER, _config, _on, _row, _switch, _user, born

FIXED = datetime(2026, 10, 14, 15, 0, tzinfo=dt_tz.utc)
HOOK = "bot_program.orcs.observe.after_care"
ENSURE = "bot_program.orcs.birth.ensure_on_commit"


def _snap(row):
    """What a run leaves on a row, ids and the creation stamp aside."""
    row.refresh_from_db()
    return {"status": row.status, "qty": str(row.qty),
            "stop_loss": str(row.stop_loss), "exit_price": str(row.exit_price),
            "pnl": str(row.pnl), "reason": row.reason,
            "outcome": row.outcome, "realized_r": row.realized_r,
            "metadata": json.loads(json.dumps(row.metadata, sort_keys=True,
                                              default=str))}


def _client(price="102.2"):
    client = MagicMock()
    client.ticker.return_value = {"lastPrice": price}
    client.get_positions.return_value = []
    return client


#: Metadata keys whose values differ between two identical runs by
#: construction: ids and moments.
VOLATILE_KEYS = {"at", "when", "ts", "time", "timestamp", "id"}


def _volatile(key) -> bool:
    key = str(key).lower()
    return (key in VOLATILE_KEYS or key.endswith("_at") or key.endswith("_id")
            or key.endswith("_ids"))


def _masked(value):
    if isinstance(value, dict):
        return {k: ("<masked>" if _volatile(k) else _masked(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_masked(v) for v in value]
    return value


def _masked_call(call):
    """repr of a mock call, the row's own id masked (each run books its
    own row)."""
    import re
    return re.sub(r"\b(trade_id|position_id|id)=\d+", r"\1=<id>", repr(call))


class TheSwitchTests(TestCase):

    def test_the_switch_is_a_system_key_off_on_arrival(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES,
                                           is_component_enabled,
                                           seed_components)
        entry = next(c for c in DEFAULT_COMPONENTS if c["key"] == "orcs")
        self.assertEqual(entry["category"], "system")
        self.assertLess(len(entry["description"]), 300)
        self.assertTrue(entry["description"].startswith("Off (default)."))
        self.assertIn("No model, no order, no stop moved",
                      entry["description"])
        self.assertNotIn("orcs", LIVE_MONEY_SWITCHES)
        self.assertNotIn("orcs", BULK_ENABLE_EXEMPT)
        seed_components()
        self.assertFalse(is_component_enabled("orcs"))

    def test_an_unreadable_switch_reads_off(self):
        from bot_program.orcs.switches import orcs_on
        self.assertFalse(orcs_on(), "a missing row reads OFF")
        _on()
        self.assertTrue(orcs_on())
        with patch("core.platform_control.is_component_enabled",
                   side_effect=RuntimeError("db down")):
            self.assertFalse(orcs_on())


class TheTickTests(TestCase):
    maxDiff = None
    """manage_positions on a paper row the care moves to break-even, with
    the Orc hook taken out against with it in: the row, the care's journal,
    the client's calls and the query count are equal."""

    def setUp(self):
        _switch("aragorn")
        self.user = _user("orc_tick")
        from tests.test_risk_limits_bind import _quote
        _quote("BTCUSD", "102.2")
        warm = _config(self.user, name="warm")
        self._run(warm, _row(warm), hooked=True)

    def _run(self, cfg, row, *, hooked, hook=None):
        from bot_program.aragorn_models import AragornAction
        from bot_program.asset_engine.base import make_bot
        client = _client()
        bot = make_bot(cfg)
        AragornAction.objects.all().delete()
        with ExitStack() as stack:
            stack.enter_context(patch(ROUTER, return_value=client))
            stack.enter_context(patch("django.utils.timezone.now",
                                      return_value=FIXED))
            if not hooked:
                stack.enter_context(patch(HOOK, return_value=None))
            elif hook is not None:
                stack.enter_context(patch(HOOK, side_effect=hook))
            stack.enter_context(self.captureOnCommitCallbacks(execute=True))
            q = stack.enter_context(CaptureQueriesContext(connection))
            closed = bot.manage_positions()
        actions = list(AragornAction.objects.values_list("kind", "detail"))
        return {"closed": closed, "row": _snap(row), "actions": actions,
                "calls": [repr(c) for c in client.mock_calls],
                "queries": len(q.captured_queries)}

    def _pair(self):
        """Two configs, two rows, the same in everything but their ids
        (their open time too: the paper replay records it)."""
        from datetime import timedelta

        from bot_program.models import AssetBotTrade
        a = _config(self.user, name="a")
        b = _config(self.user, name="b")
        ra, rb = _row(a), _row(b)
        AssetBotTrade.objects.filter(pk__in=[ra.pk, rb.pk]).update(
            opened_at=FIXED - timedelta(hours=1))
        ra.refresh_from_db()
        rb.refresh_from_db()
        return (a, ra), (b, rb)

    def test_tick_is_byte_identical_with_the_switch_off(self):
        from bot_program.orcs.models import Orc, OrcJournal
        (a, ra), (b, rb) = self._pair()
        out = self._run(a, ra, hooked=False)
        real = self._run(b, rb, hooked=True)
        self.assertEqual(out["row"]["metadata"]["care"]["soft_why"],
                         "breakeven", "the care did act")
        self.assertEqual(out, real)
        self.assertEqual((Orc.objects.count(), OrcJournal.objects.count()),
                         (0, 0))

    def test_tick_is_byte_identical_for_an_unborn_row_while_on(self):
        from bot_program.orcs.models import Orc
        _on()
        (a, ra), (b, rb) = self._pair()
        self.assertEqual(self._run(a, ra, hooked=False),
                         self._run(b, rb, hooked=True))
        self.assertEqual(Orc.objects.count(), 0)

    def test_a_born_row_is_managed_the_same_and_its_care_journaled(self):
        """A row WITH an Orc, the switch ON: the hook taken out against the
        hook in, the same row (its stamp aside), the same Aragorn actions
        and the same client calls; only the hooked row's Orc journals what
        the care did. A hook that stopped running (an `if False:` around
        the call keeps the source pin green) fails here."""
        from tests.orcs.helpers import headlines
        _on()
        (a, ra), (b, rb) = self._pair()
        orc_a, orc_b = born(self, ra), born(self, rb)
        ra.refresh_from_db()
        rb.refresh_from_db()
        out = self._run(a, ra, hooked=False)
        real = self._run(b, rb, hooked=True)
        out.pop("queries")
        real.pop("queries")
        for run in (out, real):
            self.assertIsInstance(run["row"]["metadata"].pop("orc"), dict)
        self.assertEqual(out["row"]["metadata"]["care"]["soft_why"],
                         "breakeven", "the care did act")
        self.assertEqual(out, real)
        line = "The care moved its stop to 100.20 (breakeven), +0.10R."
        self.assertIn(line, headlines(orc_b, kind="fact"))
        self.assertNotIn(line, headlines(orc_a, kind="fact"))

    def test_switching_off_stops_the_journal_of_a_born_row(self):
        """RUNBOOK: switching OFF stops new journal lines at the next tick,
        for the Orcs already born too."""
        from bot_program.orcs.models import Orc, OrcJournal
        _on()
        (_a, _ra), (b, rb) = self._pair()
        orc = born(self, rb)
        rb.refresh_from_db()
        n = OrcJournal.objects.count()
        seen = Orc.objects.get(pk=orc.pk).seen
        _on(False)
        out = self._run(b, rb, hooked=True)
        self.assertEqual(out["row"]["metadata"]["care"]["soft_why"],
                         "breakeven", "the care did act")
        self.assertEqual(OrcJournal.objects.count(), n)
        self.assertEqual(Orc.objects.get(pk=orc.pk).seen, seen)

    def test_after_care_never_raises(self):
        from bot_program.orcs.observe import after_care
        _on()
        row = _row(_config(self.user, name="c"))
        born(self, row)
        bot = SimpleNamespace(_tick_broker_cache={})
        with patch("bot_program.orcs.facts.observe_tick",
                   side_effect=RuntimeError("a step broke")):
            self.assertIsNone(after_care(bot, row, "101", ""))
        with patch("bot_program.orcs.models.Orc.objects") as objects:
            objects.filter.side_effect = RuntimeError("db gone")
            self.assertIsNone(after_care(bot, row, "101", ""))
        # and the tick around a hook that raises manages the row as before
        (a, ra), (b, rb) = self._pair()

        def boom(*_a, **_k):
            raise RuntimeError("the hook itself broke")
        self.assertEqual(self._run(a, ra, hooked=False)["row"],
                         self._run(b, rb, hooked=True, hook=boom)["row"])

    def test_after_care_does_no_query_for_an_unstamped_row(self):
        from bot_program.orcs.observe import after_care
        _on()
        row = _row(_config(self.user, name="d"))
        bot = SimpleNamespace(_tick_broker_cache={})
        with self.assertNumQueries(0):
            after_care(bot, row, "101", "")
            after_care(bot, row, "101", "closed")


class TheCarePlanTests(SimpleTestCase):

    def test_care_plan_is_unchanged_by_the_stamp(self):
        from bot_program.position_care import plan
        from tests.test_aragorn import _row as _care_row
        friday = datetime(2026, 10, 2, 20, 0, tzinfo=dt_tz.utc)
        cases = [
            (dict(), 102.2, {}), (dict(), 104.0, {}),
            (dict(side="SELL", stop=102.0), 96.0, {}),
            (dict(), 98.9, dict(posture_level="crisis", kind="risk_on_long",
                                live=True)),
            (dict(), 98.9, dict(posture_level="crisis", kind="risk_on_long",
                                live=True, manual=True)),
            (dict(lev=10, cls="forex"), 99.5, dict(now=friday, live=True)),
            (dict(cls="forex"), 101.2, dict(now=friday)),
            (dict(hours=500, cls="stock"), 100.2, {}),
            (dict(paper=True), 102.2, dict(scale=True)),
        ]
        for row_kw, price, kw in cases:
            with self.subTest(row=row_kw, price=price, kw=kw):
                plain = _care_row(**row_kw)
                stamped = _care_row(**row_kw)
                stamped.metadata = {**stamped.metadata,
                                    "orc": {"idea": 7, "leg": 1,
                                            "kind": "root",
                                            "parent_rule": "r"}}
                kw = {"now": FIXED, **kw}
                a = json.dumps(plan(plain, price, **kw), sort_keys=True,
                               default=str)
                b = json.dumps(plan(stamped, price, **kw), sort_keys=True,
                               default=str)
                self.assertEqual(a, b)


class TheEntryPathsTests(TestCase):
    """execute_entry, TAKE TRADE's _book_row and the working fill, each
    against a run with the birth hook taken out: no Orc, no stamp, the same
    row."""

    FIELDS = ("symbol", "side", "qty", "entry_price", "stop_loss",
              "take_profit", "status", "paper", "rule_name")

    def _fields(self, row, client=None):
        """The row's columns, its metadata VALUES (ids and moments masked:
        they differ between two runs by construction) and every call the
        client received, in order."""
        row.refresh_from_db()
        meta = json.loads(json.dumps(_masked(row.metadata), sort_keys=True,
                                     default=str))
        calls = ([_masked_call(c) for c in client.mock_calls]
                 if client is not None else None)
        return ({f: str(getattr(row, f)) for f in self.FIELDS}, meta, calls)

    def test_entry_take_trade_and_working_fill_are_identical_with_the_switch_off(self):
        from bot_program.asset_engine import StockBot
        from bot_program.asset_engine.base import make_bot
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc
        from tests.test_desk_seam import _client as _desk_client
        from tests.test_desk_seam import _config as _desk_config
        from tests.test_desk_seam import _signal as _desk_signal
        from tests.test_take_trade import _quote, _signal
        _on(False)
        # execute_entry
        runs = []
        for hooked in (False, True):
            cfg = _desk_config(_user(f"orc_entry_{hooked}"),
                               symbols=["ORCE1"])
            _desk_signal("ORCE1", "bullish", 0.85, rule="orc_rule")
            client = _desk_client()
            with ExitStack() as stack:
                stack.enter_context(patch(ROUTER, return_value=client))
                if not hooked:
                    stack.enter_context(patch(ENSURE))
                stack.enter_context(self.captureOnCommitCallbacks(
                    execute=True))
                res = StockBot(cfg).scan_symbol("ORCE1")
            row = AssetBotTrade.objects.get(pk=res["trade_id"])
            runs.append(self._fields(row, client))
            row.delete()
        self.assertTrue(runs[0][2], "the client was called")
        self.assertEqual(runs[0], runs[1])
        self.assertNotIn("orc", runs[1][1])
        # TAKE TRADE, paper
        inst = _quote("BTCUSD", 60000)
        runs = []
        for hooked in (False, True):
            user = _user(f"orc_take_{hooked}")
            client = _desk_client(price="60000")
            with ExitStack() as stack:
                stack.enter_context(patch(ROUTER, return_value=client))
                if not hooked:
                    stack.enter_context(patch(ENSURE))
                stack.enter_context(self.captureOnCommitCallbacks(
                    execute=True))
                out = execute_take_trade(user, _signal(inst))
            self.assertTrue(out.get("ok"), out)
            runs.append(self._fields(AssetBotTrade.objects.get(
                pk=out["trade_id"]), client))
        self.assertEqual(runs[0], runs[1])
        self.assertNotIn("orc", runs[1][1])
        # the working fill
        runs = []
        for hooked in (False, True):
            cfg = _config(_user(f"orc_fill_{hooked}"))
            row = _row(cfg, meta={"entry_working": True,
                                  "qty_requested": 1.0,
                                  "protective_order_ids": [],
                                  "protected": False})
            client = MagicMock()
            with ExitStack() as stack:
                stack.enter_context(patch(ROUTER, return_value=client))
                if not hooked:
                    stack.enter_context(patch(ENSURE))
                stack.enter_context(patch(
                    "bot_program.notifications.notify_bot_fill_open"))
                stack.enter_context(self.captureOnCommitCallbacks(
                    execute=True))
                make_bot(cfg)._finish_working_entry(
                    row, client, qty=1.0, price=100.5, source="broker")
            runs.append(self._fields(row, client))
        self.assertEqual(runs[0], runs[1])
        self.assertNotIn("orc", runs[1][1])
        self.assertEqual(Orc.objects.count(), 0)

    def test_kill_switch_is_identical_with_no_orc(self):
        from bot_program.engine.kill_switch import execute_kill_switch
        from tests.test_risk_limits_bind import _quote
        _quote("BTCUSD", "101")
        runs = []
        for hooked in (False, True):
            user = _user(f"orc_kill_{hooked}")
            row = _row(_config(user))
            with ExitStack() as stack:
                if not hooked:
                    stack.enter_context(patch(
                        "bot_program.orcs.lifecycle.kill_all"))
                stack.enter_context(self.captureOnCommitCallbacks(
                    execute=True))
                out = execute_kill_switch(user=user, reason="test")
            snap = _snap(row)
            snap["metadata"].pop("kill_switch", None)
            runs.append((out, snap["status"], snap["outcome"]))
        self.assertEqual(runs[0], runs[1])

    def test_a_close_save_of_an_unstamped_row_adds_no_query(self):
        _on()
        row = _row(_config(_user("orc_save")))
        row.status = "CLOSED"
        row.outcome = "manual_close"
        with self.captureOnCommitCallbacks(execute=True) as cbs, \
                CaptureQueriesContext(connection) as q:
            row.save(update_fields=["status", "outcome"])
        self.assertEqual(len(q.captured_queries), 1, "the UPDATE alone")
        self.assertEqual(cbs, [])

    def test_the_census_does_nothing_while_off(self):
        from bot_program.orcs.models import Orc
        from bot_program.orcs.tasks import orc_census
        from core.platform_control import PlatformComponent
        _on(False)
        _row(_config(_user("orc_census_off")))
        self.assertEqual(orc_census(), {"status": "skipped",
                                        "reason": "orcs_disabled"})
        self.assertEqual(Orc.objects.count(), 0)
        comp = PlatformComponent.objects.get(key="orcs")
        self.assertEqual((comp.run_count, comp.last_run_at), (0, None))

    def test_a_birth_makes_no_broker_call(self):
        import requests
        _on()
        row = _row(_config(_user("orc_offline")), paper=False)
        with patch(ROUTER, side_effect=AssertionError("a broker call")), \
                patch.object(requests.Session, "request",
                             side_effect=AssertionError("a network call")), \
                patch("requests.get", side_effect=AssertionError("get")), \
                patch("requests.post", side_effect=AssertionError("post")):
            self.assertIsNotNone(born(self, row))


class TheSourcePinTests(SimpleTestCase):

    FORBIDDEN = {"_close_trade", "execute_entry", "client_for_symbol",
                 "market_order", "close_position", "_move_broker_stop",
                 "modify_protective", "ai_agents", "anthropic"}

    def _files(self):
        import bot_program.orcs as pkg
        root = os.path.dirname(pkg.__file__)
        out = [os.path.join(root, f) for f in sorted(os.listdir(root))
               if f.endswith(".py")]
        out.append(os.path.join(os.path.dirname(root), "management",
                                "commands", "orcs.py"))
        return out

    def test_the_orcs_package_imports_no_order_path_and_no_model(self):
        for path in self._files():
            tree = ast.parse(open(path, encoding="utf-8").read())
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.alias):
                    names.update(node.name.split("."))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.update(node.module.split("."))
            with self.subTest(os.path.basename(path)):
                self.assertFalse(names & self.FORBIDDEN, names & self.FORBIDDEN)

    def test_nothing_outside_the_orcs_reads_the_stamp(self):
        """The stamp is the one write outside the Orc tables; nothing else
        reads it, so it changes no behaviour."""
        import re

        from django.conf import settings
        base = settings.BASE_DIR
        # a row's metadata read for the "orc" key (the Horde's own seat
        # dict carries an "orc" slot of its own: not a metadata read)
        pattern = re.compile(
            r"""(meta|metadata)\b[^\n]*(\.get\(\s*["']orc["']"""
            r"""|\[\s*["']orc["']\s*\])""")
        hits, scanned = [], 0
        for app in ("bot_program", "brain", "core", "dashboard", "portfolio",
                    "signals", "market_data", "ai_agents", "backtester"):
            for dirpath, _dirs, files in os.walk(os.path.join(base, app)):
                # by the path's own parts under the project, never by a
                # substring of the absolute path: a checkout whose folder
                # name holds "orcs" (a worktree) would skip every file
                parts = os.path.relpath(dirpath, base).split(os.sep)
                if "orcs" in parts or "migrations" in parts:
                    continue
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, f)
                    if path.endswith(os.path.join("commands", "orcs.py")):
                        continue
                    scanned += 1
                    if pattern.search(open(path, encoding="utf-8").read()):
                        hits.append(os.path.relpath(path, base))
        self.assertGreater(scanned, 400, "the guard must read the tree")
        self.assertEqual(hits, [])

    def test_the_hooks_sit_where_they_must(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.engine import kill_switch
        mp = inspect.getsource(AssetBot.manage_positions)
        self.assertLess(mp.index("_care(self, trade, price, client)"),
                        mp.index("_orc_after_care(self, trade, price, _cared)"))
        self.assertLess(mp.index("_orc_after_care(self, trade, price, _cared)"),
                        mp.index("if _cared:"))
        ee = inspect.getsource(AssetBot.execute_entry)
        self.assertLess(ee.index("ensure_on_commit(trade"),
                        ee.index("skips.clear(self.cfg, symbol)"))
        fw = inspect.getsource(AssetBot._finish_working_entry)
        self.assertIn("ensure_on_commit(trade", fw)
        ks = inspect.getsource(kill_switch.execute_kill_switch)
        self.assertLess(ks.index("disarm.disable_config"), ks.index("kill_all("))
        self.assertLess(ks.index("kill_all("), ks.index("open_legacy = "))
        for src in (mp, ee, fw, ks):
            self.assertIn("except Exception", src)
