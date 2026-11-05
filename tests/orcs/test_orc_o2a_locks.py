"""T17, NO ORC LOCK CAN DELAY THE CARE, A CLOSE OR THE KILL SWITCH (the O2
spec N8 items 1-3; 2026-11-05).

Every Orc-row lock of the package is taken by journal.orc_lock, which sets
SET LOCAL lock_timeout and statement_timeout first, and the real-money
paths wait for one within a lock budget of ORC_LOCK_MONEY_MS in all
(journal.lock_budget): the tick's Orc steps, a close's journal, the kill
switch and the entry's provenance.

On PostgreSQL (TheMoneyPathsNeverWaitTests, `skipUnless`): thread A holds
one Orc's row lock for 10 s; thread B then runs (a) the tick on a config
holding that Orc's row and a second row whose price crosses its stop, (b)
the kill switch, (c) the close of the Orc's row and (d) the runner's
provenance step, each in under 1 s, with the same broker calls and rows as
the same run with no Orc; and B's connection keeps no Orc timeout after.
CI runs SQLite, where none of this exists: the builder runs this module on
a throwaway PostgreSQL 16 cluster before each commit that touches a lock,
and the commit message names that run.

On any engine: the source pins (every Orc lock through orc_lock, the
budget entered where the money is, the census's sweep left at the default,
the hooks called outside any transaction of theirs, and no lock holder
that renders, validates, prices or calls the gateway) and the budget's
arithmetic.

Run with:  python manage.py test tests.orcs.test_orc_o2a_locks
(PostgreSQL: DB_ENGINE=postgresql and the DB_* variables of a scratch
cluster.)
"""
import ast
import inspect
import json
import textwrap
import threading
import time
from contextlib import ExitStack
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.db import connection, transaction

from tests.orcs import test_orc_o2a_shadow_pins as t1
from tests.orcs.helpers import ROUTER, _config, _on, _row, _switch, _user
from tests.orcs.helpers_o2 import MindTestCase, MindTransactionTestCase

FIXED = datetime(2026, 10, 14, 15, 0, tzinfo=dt_tz.utc)
#: Thread A's hold, and what thread B may take with it held.
HOLD_S = 10.0
UNDER_S = 1.0
PG = connection.vendor == "postgresql"
NOT_PG = "N8's lock proof needs PostgreSQL's row locks (SQLite has none)"

#: The functions that take an Orc's row lock, each through orc_lock.
LOCKERS = (("journal", "append"), ("journal", "remember"),
           ("journal", "merge_seen"), ("lifecycle", "_close_leg"),
           ("lifecycle", "kill_all"), ("thesis", "complete_provenance"))
#: The real-money paths and what each one runs inside the budget.
MONEY_PATHS = (("observe", "after_care", "TICK_STEPS"),
               ("lifecycle", "_closed_quietly", "on_leg_closed"),
               ("lifecycle", "kill_all", "orc_lock"),
               ("thesis", "complete_provenance", "orc_lock"))
#: The hooks of the order path that call those paths, and the call.
HOOK_CALLS = (("bot_program.asset_engine.base", "AssetBot.manage_positions",
               "_orc_after_care"),
              ("bot_program.engine.kill_switch", "execute_kill_switch",
               "kill_all"),
              ("bot_program.asset_engine.runner", "_stamp_desk_keys",
               "complete_provenance"))
#: What a lock holder never names (N8 item 1): the render, the validator,
#: the officer, the pricing and the gateway.
HOLDER_FORBIDDEN = {"dossier", "render", "render_wake", "validator",
                    "validate", "mandate", "officer", "allowed_actions",
                    "pricing", "mind_gateway", "gateway"}


def _source_fn(mod, qual):
    import importlib
    obj = importlib.import_module(f"bot_program.orcs.{mod}"
                                  if "." not in mod else mod)
    for part in qual.split("."):
        obj = getattr(obj, part)
    return ast.parse(textwrap.dedent(inspect.getsource(obj))).body[0]


def _withs_of_budget(fn):
    """The `with` statements of `fn` that enter lock_budget, and the
    argument each passes."""
    out = []
    for sub in ast.walk(fn):
        if isinstance(sub, ast.With):
            for item in sub.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and \
                        t1.chain_of(call.func)[-1] == "lock_budget":
                    out.append((sub, ast.unparse(call.args[0])
                                if call.args else ""))
    return out


def _named_inside(node, name) -> bool:
    return any((isinstance(s, ast.Name) and s.id == name)
               or (isinstance(s, ast.Attribute) and s.attr == name)
               for s in ast.walk(node))


def holder_problems(fn) -> list:
    """N8 item 1: a function that takes an Orc lock or the line lock
    (orc_lock, line_lock, a select_for_update on an Orc or an OrcSetting)
    and names the render, the validator, the officer, pricing or the
    gateway."""
    takes = False
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call):
            chain = t1.chain_of(sub.func)
            if chain[-1] in ("orc_lock", "line_lock") or (
                    "select_for_update" in chain
                    and {"Orc", "OrcSetting"} & set(chain)):
                takes = True
    if not takes:
        return []
    return sorted({name for name, _n in t1.identifiers(fn)
                   if name in HOLDER_FORBIDDEN})


class TheLocksAreTakenOneWayTests(MindTestCase):
    """The source: every Orc-row lock through orc_lock; the budget where
    the money is; the hooks outside any transaction of theirs."""

    def test_every_orc_row_lock_goes_through_orc_lock(self):
        for mod, path in t1.package_files():
            tree = t1.tree_of(path)
            for node, scope in t1.scoped(tree):
                if not isinstance(node, ast.Call):
                    continue
                chain = t1.chain_of(node.func)
                if "select_for_update" in chain and "Orc" in chain:
                    with self.subTest(f"{mod}.{scope}"):
                        self.assertEqual((mod, scope), ("journal", "orc_lock"))
        for mod, name in LOCKERS:
            with self.subTest(f"{mod}.{name}"):
                self.assertIn("orc_lock(", inspect.getsource(
                    getattr(__import__(f"bot_program.orcs.{mod}",
                                       fromlist=[name]), name)))

    def test_the_money_paths_wait_within_their_budget(self):
        for mod, name, inside in MONEY_PATHS:
            fn = _source_fn(mod, name)
            withs = _withs_of_budget(fn)
            with self.subTest(f"{mod}.{name}"):
                self.assertEqual([arg for _w, arg in withs],
                                 ["ORC_LOCK_MONEY_MS"])
                self.assertTrue(_named_inside(withs[0][0], inside),
                                f"{inside} runs inside the budget")
        sweep = _source_fn("lifecycle", "sweep")
        self.assertEqual(_withs_of_budget(sweep), [],
                         "the census's sweep keeps the default")
        from bot_program.orcs.constants import (ORC_LOCK_MONEY_MS,
                                                ORC_LOCK_TIMEOUT_MS,
                                                ORC_STATEMENT_TIMEOUT_MS)
        self.assertEqual((ORC_LOCK_MONEY_MS, ORC_LOCK_TIMEOUT_MS,
                          ORC_STATEMENT_TIMEOUT_MS), (200, 2000, 5000))

    def test_the_hooks_call_the_orcs_outside_any_transaction_of_theirs(self):
        """SET LOCAL ends with the Orc's own transaction: the order path
        never calls a money path from inside an atomic block, and a close
        reaches the Orcs after its commit."""
        for mod, qual, call in HOOK_CALLS:
            fn = _source_fn(mod, qual)
            with self.subTest(qual):
                self.assertFalse([d for d in fn.decorator_list
                                  if "atomic" in ast.unparse(d)])
                found = 0
                for sub in ast.walk(fn):
                    if isinstance(sub, ast.With) and any(
                            "atomic" in ast.unparse(i.context_expr)
                            for i in sub.items):
                        self.assertFalse(_named_inside(sub, call),
                                         f"{call} inside an atomic block")
                    if isinstance(sub, ast.Call) and \
                            t1.chain_of(sub.func)[-1] == call:
                        found += 1
                self.assertEqual(found, 1)
        from bot_program.orcs import lifecycle
        self.assertIn("transaction.on_commit(partial(_closed_quietly",
                      inspect.getsource(lifecycle._leg_saved))

    def test_no_lock_holder_renders_validates_prices_or_calls_a_model(self):
        units = t1.o2_units()
        self.assertTrue(units)
        for mod, qual, node in units:
            with self.subTest(f"{mod}.{qual}"):
                self.assertEqual(holder_problems(node), [])
        bad = ast.parse(inspect.cleandoc("""
            def settle(orc, wake):
                with transaction.atomic():
                    locked = journal.orc_lock(orc.pk)
                    text = dossier.render(wake)
                    ok = validator.check(text)
            """)).body[0]
        self.assertEqual(holder_problems(bad), ["dossier", "render",
                                                "validator"])
        ok = ast.parse(inspect.cleandoc("""
            def settle(orc, verdict):
                with transaction.atomic():
                    locked = journal.orc_lock(orc.pk)
                    journal.append(locked, "decision", verdict)
            """)).body[0]
        self.assertEqual(holder_problems(ok), [])


class TheBudgetArithmeticTests(MindTestCase):
    """journal.lock_budget on any engine: what a block has, what a block
    inside it may have, and that leaving restores the outer one."""

    def test_a_block_holds_its_budget_and_leaves_none_behind(self):
        from bot_program.orcs import journal
        self.assertIsNone(journal._BUDGET.get())
        with journal.lock_budget(200) as b:
            self.assertEqual(b, {"left_ms": 200.0, "spent_ms": 0.0})
            self.assertIs(journal._BUDGET.get(), b)
            with journal.lock_budget(2000) as inner:
                self.assertEqual(inner["left_ms"], 200.0,
                                 "an inner block never widens it")
                inner["left_ms"] -= 150.0
                inner["spent_ms"] += 150.0
            self.assertEqual(b, {"left_ms": 50.0, "spent_ms": 150.0},
                             "what the inner block spent is spent")
            with journal.lock_budget(10) as small:
                self.assertEqual(small["left_ms"], 10.0)
        self.assertIsNone(journal._BUDGET.get())

    def test_an_exception_leaves_no_budget_behind(self):
        from bot_program.orcs import journal
        with self.assertRaises(RuntimeError):
            with journal.lock_budget(200):
                raise RuntimeError("a step failed")
        self.assertIsNone(journal._BUDGET.get())

    def test_each_thread_has_its_own_budget(self):
        from bot_program.orcs import journal
        seen = []
        with journal.lock_budget(200):
            t = threading.Thread(target=lambda: seen.append(
                journal._BUDGET.get()))
            t.start()
            t.join()
        self.assertEqual(seen, [None])

    def test_the_lock_reads_the_row_it_names(self):
        from bot_program.orcs import journal
        from bot_program.orcs.models import Orc, OrcSeat
        user = _user("o2lock_sqlite")
        cfg = _config(user)
        row, other = _row(cfg), _row(cfg, symbol="ETHUSD")
        orc = Orc.objects.create(
            seat=OrcSeat.objects.create(venue="paper", asset_class="crypto"),
            user=user, config=cfg, root_trade=row, symbol=row.symbol,
            side=row.side, asset_class=row.asset_class)
        with transaction.atomic():
            self.assertEqual(journal.orc_lock(orc.pk).pk, orc.pk)
            self.assertEqual(journal.orc_lock(orc.pk,
                                              root_trade_id=row.pk).pk, orc.pk)
            with self.assertRaises(Orc.DoesNotExist):
                journal.orc_lock(orc.pk, root_trade_id=other.pk)


def _snap(row):
    row.refresh_from_db()
    meta = json.loads(json.dumps(row.metadata, sort_keys=True, default=str))
    meta.pop("orc", None)
    return {"status": row.status, "qty": str(row.qty),
            "stop_loss": str(row.stop_loss),
            "take_profit": str(row.take_profit),
            "exit_price": str(row.exit_price), "pnl": str(row.pnl),
            "reason": row.reason, "outcome": row.outcome,
            "realized_r": row.realized_r, "metadata": meta}


class _Holder:
    """Thread A: takes one Orc's row lock the only way the package takes
    it (journal.orc_lock) and holds it until released, HOLD_S at most."""

    def __init__(self, orc_pk):
        self.orc_pk = orc_pk
        self.ready, self.release = threading.Event(), threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from django.db import connection as conn

        from bot_program.orcs import journal
        try:
            with transaction.atomic():
                journal.orc_lock(self.orc_pk)
                self.ready.set()
                self.release.wait(HOLD_S)
        except Exception as e:  # noqa: BLE001 — told to the test thread
            self.error = e
            self.ready.set()
        finally:
            conn.close()

    def __enter__(self):
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            raise RuntimeError(f"thread A never held the lock: {self.error}")
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.thread.join(HOLD_S + 5)
        return False


def _timeouts():
    with connection.cursor() as cur:
        cur.execute("SELECT current_setting('lock_timeout'), "
                    "current_setting('statement_timeout')")
        return cur.fetchone()


@skipUnless(PG, NOT_PG)
class TheLockItselfTests(MindTransactionTestCase):
    """orc_lock on PostgreSQL: its timeouts live in its own transaction,
    a held lock is waited for within the budget only, and a row that only
    names the Orc is written at once (FOR NO KEY UPDATE)."""

    def setUp(self):
        from bot_program.orcs.models import Orc, OrcSeat
        user = _user("o2lock_pg")
        cfg = _config(user)
        self.row = _row(cfg)
        self.orc = Orc.objects.create(
            seat=OrcSeat.objects.create(venue="paper", asset_class="crypto"),
            user=user, config=cfg, root_trade=self.row,
            symbol=self.row.symbol, side=self.row.side,
            asset_class=self.row.asset_class)

    def test_the_timeouts_end_with_the_transaction(self):
        from bot_program.orcs import journal
        session = _timeouts()
        with transaction.atomic():
            journal.orc_lock(self.orc.pk)
            self.assertEqual(_timeouts(), ("2s", "5s"))
        self.assertEqual(_timeouts(), session)
        with journal.lock_budget(200), transaction.atomic():
            journal.orc_lock(self.orc.pk)
            self.assertEqual(_timeouts()[0], "200ms")
        self.assertEqual(_timeouts(), session)

    def test_a_held_lock_is_waited_for_within_the_budget_only(self):
        from django.db import OperationalError

        from bot_program.orcs import journal
        from bot_program.orcs.models import OrcWake
        with _Holder(self.orc.pk):
            t0 = time.monotonic()
            OrcWake.objects.create(orc_id=self.orc.pk, dedupe_key="o2:k",
                                   status="recorded")
            self.assertLess(time.monotonic() - t0, 0.5,
                            "a row naming the Orc is written at once")
            with journal.lock_budget(200) as budget:
                t0 = time.monotonic()
                with self.assertRaises(OperationalError), \
                        transaction.atomic():
                    journal.orc_lock(self.orc.pk)
                first = time.monotonic() - t0
                t0 = time.monotonic()
                with self.assertRaises(OperationalError), \
                        transaction.atomic():
                    journal.orc_lock(self.orc.pk)
                second = time.monotonic() - t0
            self.assertGreaterEqual(first, 0.15)
            self.assertLess(first, 0.6)
            self.assertLess(second, 0.1, "a spent budget waits no more")
            self.assertEqual(budget["left_ms"], 0.0)
        with transaction.atomic():
            self.assertEqual(journal.orc_lock(self.orc.pk).pk, self.orc.pk)


@skipUnless(PG, NOT_PG)
class TheMoneyPathsNeverWaitTests(MindTransactionTestCase):
    """(a)-(d): each real-money path finishes in under a second while
    thread A holds the Orc's row lock for ten, with the same broker calls
    and rows as the same run with no Orc."""

    def setUp(self):
        _switch("aragorn")
        _on()
        from tests.test_risk_limits_bind import _quote
        _quote("BTCUSD", "102.2")

    def _world(self, tag):
        """A config with the Orc's row (entry 100, stop 98) and a second
        row whose stop (103) the price (102.2) has crossed."""
        from bot_program.models import AssetBotTrade
        user = _user(f"o2lock_{tag}")
        cfg = _config(user, name="o2lock")
        held = _row(cfg)
        crossing = _row(cfg, entry="106", stop="103", target="120")
        AssetBotTrade.objects.filter(pk__in=[held.pk, crossing.pk]).update(
            opened_at=FIXED - timedelta(hours=1))
        held.refresh_from_db()
        crossing.refresh_from_db()
        return SimpleNamespace(user=user, cfg=cfg, held=held,
                               crossing=crossing)

    def _born(self, w):
        from bot_program.orcs.birth import ensure
        with patch("django.utils.timezone.now", return_value=FIXED):
            orc = ensure(w.held, now=FIXED)
        self.assertIsNotNone(orc)
        w.held.refresh_from_db()
        return orc

    def _client(self):
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "102.2"}
        client.get_positions.return_value = []
        return client

    def _timed(self, w, run, orc=None):
        """Run `run(w, client)`, with thread A holding `orc`'s lock when
        given; (seconds, outcome, broker calls)."""
        from bot_program.aragorn_models import AragornAction
        client = self._client()
        AragornAction.objects.all().delete()
        with ExitStack() as stack:
            stack.enter_context(patch(ROUTER, return_value=client))
            stack.enter_context(patch("django.utils.timezone.now",
                                      return_value=FIXED))
            if orc is not None:
                stack.enter_context(_Holder(orc.pk))
            t0 = time.monotonic()
            out = run(w, client)
            took = time.monotonic() - t0
        self.assertEqual(_timeouts(), ("0", "0"),
                         "no Orc timeout stays on B's connection")
        actions = list(AragornAction.objects.values_list("kind", "detail"))
        return took, (out, _snap(w.held), _snap(w.crossing), actions), \
            [repr(c) for c in client.mock_calls]

    def _same_without_and_with(self, run):
        bare = self._world("bare")
        base_s, base, base_calls = self._timed(bare, run)
        orcd = self._world("orc")
        orc = self._born(orcd)
        took, got, calls = self._timed(orcd, run, orc)
        self.assertLess(took, UNDER_S, f"{took:.3f}s with the Orc's lock "
                        f"held ({base_s:.3f}s with no Orc)")
        self.assertEqual(got, base)
        self.assertEqual(calls, base_calls)
        return got

    def test_a_the_tick(self):
        from bot_program.asset_engine.base import make_bot

        def run(w, client):
            return make_bot(w.cfg).manage_positions()
        got = self._same_without_and_with(run)
        self.assertEqual(got[0], 1, "the crossed row closed")
        self.assertEqual(got[2]["status"], "CLOSED")

    def test_b_the_kill_switch(self):
        from bot_program.engine.kill_switch import execute_kill_switch

        def run(w, client):
            out = execute_kill_switch(user=w.user, reason="test")
            return {k: v for k, v in out.items()
                    if not isinstance(v, (list, dict))}
        got = self._same_without_and_with(run)
        self.assertEqual(got[1]["status"], "CLOSED", "the flatten ran")

    def test_c_the_close_of_the_orcs_row(self):
        from bot_program.asset_engine.base import make_bot

        def run(w, client):
            return make_bot(w.cfg)._close_trade(w.held, Decimal("99"), client,
                                                reason="SL")
        got = self._same_without_and_with(run)
        self.assertEqual(got[1]["status"], "CLOSED")

    def test_d_the_runners_provenance_step(self):
        from bot_program.asset_engine.runner import _stamp_desk_keys

        def run(w, client):
            _stamp_desk_keys(
                w.held.pk, plan=SimpleNamespace(pk=7, mode="advise"),
                decision=SimpleNamespace(pk=8, size_mult=1.0, e_r=0.4,
                                         lane="trend"),
                cand=SimpleNamespace(qty_default=1.0,
                                     risk_dollars_default=2.0))
            return None
        got = self._same_without_and_with(run)
        self.assertEqual(got[1]["metadata"]["desk_plan_id"], 7)
