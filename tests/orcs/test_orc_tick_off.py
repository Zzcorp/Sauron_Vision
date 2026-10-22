"""HARD RULE 1 FOR O1b (spec §11): with the `orcs` switch OFF the tick is
byte-identical to before, its outbound calls included, and no Orc table is
read; ON, a row with no Orc is managed exactly as before, and a row WITH
an Orc writes only the Orc tables. The care's plan() and its outputs are
unchanged by the in-memory stash the ghost reads, the crowd is read once
per tick for the care and its ghost together, a ghost that raises never
breaks the tick, and a quiet tick costs a bounded number of queries.

Run with:  python manage.py test tests.orcs.test_orc_tick_off
"""
import json
from contextlib import ExitStack
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from tests.orcs.helpers import ROUTER, _config, _on, _row, _switch, _user, born

FIXED = datetime(2026, 10, 14, 15, 0, tzinfo=dt_tz.utc)
HOOK = "bot_program.orcs.observe.after_care"
ORC_TABLE = "bot_program_orc"


def _snap(row):
    row.refresh_from_db()
    return {"status": row.status, "qty": str(row.qty),
            "stop_loss": str(row.stop_loss), "exit_price": str(row.exit_price),
            "pnl": str(row.pnl), "reason": row.reason, "outcome": row.outcome,
            "realized_r": row.realized_r,
            "metadata": json.loads(json.dumps(row.metadata, sort_keys=True,
                                              default=str))}


class _Tick(TestCase):

    def setUp(self):
        _switch("aragorn")
        self.user = _user("orc_tick_off")
        from tests.test_risk_limits_bind import _quote
        _quote("BTCUSD", "102.2")

    def _pair(self):
        from bot_program.models import AssetBotTrade
        a, b = _config(self.user, name="a"), _config(self.user, name="b")
        ra, rb = _row(a), _row(b)
        AssetBotTrade.objects.filter(pk__in=[ra.pk, rb.pk]).update(
            opened_at=FIXED - timedelta(hours=1))
        ra.refresh_from_db()
        rb.refresh_from_db()
        return (a, ra), (b, rb)

    def _run(self, cfg, row, *, hooked=True, hook=None, price="102.2"):
        from bot_program.aragorn_models import AragornAction
        from bot_program.asset_engine.base import make_bot
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": price}
        client.get_positions.return_value = []
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
        return {"closed": closed, "row": _snap(row),
                "actions": list(AragornAction.objects.values_list(
                    "kind", "detail")),
                "calls": [repr(c) for c in client.mock_calls],
                "orc_sql": [x["sql"] for x in q.captured_queries
                            if ORC_TABLE in x["sql"]],
                "queries": len(q.captured_queries),
                "sql": [x["sql"][:150] for x in q.captured_queries]}


class TheOffTests(_Tick):

    def test_off_manage_positions_is_byte_identical(self):
        """An Orc already born, the switch then OFF: the tick with the hook
        is the tick without it, and no Orc table is touched."""
        _on()
        (a, ra), (b, rb) = self._pair()
        born(self, ra)
        born(self, rb)
        ra.refresh_from_db()
        rb.refresh_from_db()
        _on(False)
        out = self._run(a, ra, hooked=False)
        real = self._run(b, rb, hooked=True)
        for run in (out, real):
            run["row"]["metadata"].pop("orc")
        self.assertEqual(real["orc_sql"], [], "no Orc table read")
        # the switch itself is read once a pass for a stamped row (O1a's
        # hook): a platform-control read, never an Orc table
        self.assertLessEqual(real.pop("queries") - out.pop("queries"), 1)
        out.pop("sql")
        real.pop("sql")
        self.assertEqual(out, real)
        self.assertEqual(real["row"]["metadata"]["care"]["soft_why"],
                         "breakeven", "the care acted")

    def test_on_rows_without_an_orc_are_byte_identical(self):
        _on()
        (a, ra), (b, rb) = self._pair()
        out = self._run(a, ra, hooked=False)
        real = self._run(b, rb, hooked=True)
        self.assertEqual(real["orc_sql"], [])
        out.pop("sql")
        real.pop("sql")
        self.assertEqual(out, real)

    def test_on_an_orc_row_writes_only_orc_tables(self):
        """Every write the hook makes, captured inside the hook itself, is
        to an Orc table, and the arms' own update is among them."""
        from bot_program.orcs import observe
        from tests.orcs.test_orc_grading import _orc_tables, _written_tables
        _on()
        (a, ra), (b, rb) = self._pair()
        born(self, ra)
        born(self, rb)
        ra.refresh_from_db()
        rb.refresh_from_db()
        real_hook = observe.after_care
        writes = []

        def spy(*args, **kwargs):
            with CaptureQueriesContext(connection) as q:
                real_hook(*args, **kwargs)
            writes.extend(_written_tables(q.captured_queries))
        out = self._run(a, ra, hooked=False)
        real = self._run(b, rb, hook=spy)
        self.assertEqual([w for w in writes if w[1] not in _orc_tables()],
                         [], "the hook writes the Orc tables only")
        self.assertIn(("UPDATE", "bot_program_orctrack"), writes,
                      "the arms stepped")
        for run in (out, real):
            run["row"]["metadata"].pop("orc")
            run.pop("orc_sql")
            run.pop("queries")
            run.pop("sql")
        self.assertEqual(out, real, "the row, the actions, the calls")

    def test_a_ghost_that_raises_never_breaks_the_tick(self):
        _on()
        (a, ra), (b, rb) = self._pair()
        born(self, ra)
        born(self, rb)
        ra.refresh_from_db()
        rb.refresh_from_db()
        with patch("bot_program.orcs.ghost.step_tick",
                   side_effect=RuntimeError("the ghost broke")), \
                patch("bot_program.orcs.predicates.check",
                      side_effect=RuntimeError("a predicate broke")):
            real = self._run(b, rb, hooked=True)
        out = self._run(a, ra, hooked=False)
        for run in (out, real):
            run["row"]["metadata"].pop("orc")
        self.assertEqual(out["row"], real["row"])
        self.assertEqual(out["calls"], real["calls"])

    def test_tick_query_budget_per_orc_row(self):
        _on()
        (a, ra), (_b, _rb) = self._pair()
        born(self, ra)
        ra.refresh_from_db()
        self._run(a, ra)                    # the first tick: facts written
        quiet = self._run(a, ra)            # a quiet tick
        plain_cfg = _config(self.user, name="plain")
        plain = _row(plain_cfg)
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=plain.pk).update(
            opened_at=FIXED - timedelta(hours=1))
        plain.refresh_from_db()
        self._run(plain_cfg, plain)
        base = self._run(plain_cfg, plain)
        extra = quiet["queries"] - base["queries"]
        self.assertLessEqual(extra, 12, (quiet["queries"], base["queries"],
                                         quiet.get("sql")))


class TheCareStashTests(_Tick):

    def test_care_plan_unchanged_and_the_stash_is_memory_only(self):
        from bot_program import position_care
        _on()
        (a, ra), (b, rb) = self._pair()
        with patch.object(position_care, "plan",
                          wraps=position_care.plan) as spy:
            self._run(a, ra, hooked=False)
        unhooked = spy.call_args_list[0]
        with patch.object(position_care, "plan",
                          wraps=position_care.plan) as spy:
            self._run(b, rb, hooked=True)
        hooked = spy.call_args_list[0]
        self.assertEqual(unhooked.kwargs, hooked.kwargs)
        rb.refresh_from_db()
        blob = json.dumps(rb.metadata, default=str)
        self.assertNotIn("_care_tick", blob)
        self.assertNotIn("posture_level", blob)

    def test_off_care_is_byte_identical_without_the_stash_and_the_memo(self):
        """The two lines the Orcs add to the care itself, live on every
        row even OFF: the stash (`trade._care_tick`, memory only) and the
        crowd read memo (`_Once`). With both undone, the care's row, its
        actions and its calls to the broker are what they are with them."""
        from bot_program import position_care
        _on(False)
        _switch("smart_money")
        reads = []

        def levels(symbol, side, price, **kw):
            reads.append(symbol)
            return {"atr": 1.0, "levels": []}
        (a, ra), (b, rb) = self._pair()
        with patch("bot_program.smart_money.care_levels",
                   side_effect=levels), \
                patch.object(position_care, "_stash",
                             lambda trade, value: None), \
                patch.object(position_care, "_Once", lambda read: read):
            undone = self._run(a, ra)
        with patch("bot_program.smart_money.care_levels",
                   side_effect=levels):
            real = self._run(b, rb)
        for run in (undone, real):
            run.pop("sql")
            run.pop("queries")
        self.assertEqual(undone, real)
        self.assertTrue(reads, "the crowd was read")
        self.assertEqual(real["row"]["metadata"]["care"]["soft_why"],
                         undone["row"]["metadata"]["care"]["soft_why"])

    def test_the_crowd_is_read_once_per_tick_for_care_and_ghost(self):
        _on()
        _switch("smart_money")
        (a, ra), _ = self._pair()
        born(self, ra)
        ra.refresh_from_db()
        reads = []

        def levels(symbol, side, price, **kw):
            reads.append(symbol)
            return {"atr": 1.0, "levels": []}
        with patch("bot_program.smart_money.care_levels", side_effect=levels):
            self._run(a, ra)
        self.assertEqual(len(reads), 1, "one read, the care's and the ghost's")


class TheOnceTests(SimpleTestCase):

    def test_the_memo_returns_the_identical_object(self):
        from bot_program.position_care import _Once
        calls = []
        value = {"atr": 1.0}

        def read():
            calls.append(1)
            return value
        once = _Once(read)
        self.assertIs(once(), value)
        self.assertIs(once(), value)
        self.assertEqual(len(calls), 1)
        none = _Once(lambda: None)
        self.assertIsNone(none())
        self.assertTrue(once, "truthy, as the closure it wraps")
