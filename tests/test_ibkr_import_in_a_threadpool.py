"""ib_insync imports from a thread that has no event loop.

THE BUG, as an operator met it. Daphne runs a sync Django view in a
ThreadPoolExecutor worker, and such a thread starts with no asyncio loop.
ib_insync calls `asyncio.get_event_loop()` AT IMPORT TIME, so the import
itself raised

    There is no current event loop in thread 'ThreadPoolExecutor-33_0'

— a RuntimeError, not an ImportError. This module's import guard caught it and
recorded "ib_insync not installed", which was false. And the verdict was a
module global set once, so the first unlucky thread condemned the WHOLE
PROCESS: from then on every IBKR call out of the web container degraded to a
paper stub, on every thread, until a restart.

What the operator saw, for an afternoon, pressing a button in the UI:

    LIVE route unavailable — stock orders would fall back to the paper
    simulator (credentials missing, broker library absent, or the account
    disconnected). Nothing was armed

against a funded account on a logged-in Gateway that `docker ps` called
healthy, with ib_insync installed and working — and `manage.py shell` in the
SAME container routed the same symbol to a live socket seconds later, because
a management command runs on the main thread, which has a loop.

Three defects in one line of code, and the first two are why it took so long
to find: an environment fault reported as a missing package, a per-thread
condition cached as a per-process fact, and a routing failure reported to the
operator as a credentials problem.

Run with:  python manage.py test tests.test_ibkr_import_in_a_threadpool
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from django.test import SimpleTestCase


def _no_loop_here() -> bool:
    """True when the calling thread has no asyncio loop — the ThreadPool state
    ib_insync's import cannot survive."""
    try:
        asyncio.get_event_loop()
        return False
    except RuntimeError:
        return True


class TheLoopIsInPlaceBeforeTheImportTests(SimpleTestCase):

    def test_ensure_event_loop_is_defined_before_the_import_runs(self):
        """Ordering IS the fix. The helper existed all along, 40 lines BELOW
        the import that needed it."""
        import inspect

        from bot_program.engine import ibkr_client
        src = inspect.getsource(ibkr_client)
        self.assertLess(src.index("def _ensure_event_loop"),
                        src.index("_ib = _try_import_ib()"))

    def test_the_import_helper_installs_a_loop_first(self):
        import inspect

        from bot_program.engine.ibkr_client import _try_import_ib
        body = inspect.getsource(_try_import_ib)
        self.assertLess(body.index("_ensure_event_loop()"),
                        body.index("import ib_insync"))

    def test_importing_from_a_loopless_thread_succeeds(self):
        """The reproduction. Before the fix this returned False from the pool
        and True from the main thread — the exact split the operator hit."""
        from bot_program.engine.ibkr_client import _try_import_ib

        with ThreadPoolExecutor(max_workers=1) as pool:
            confirmed_no_loop = pool.submit(_no_loop_here).result()
            self.assertTrue(confirmed_no_loop,
                            "the fixture must start without a loop or it "
                            "proves nothing")
            # A fresh worker: the loop the previous call installed belongs to
            # that thread, so ask a new one.
            got = pool.submit(_try_import_ib).result()

        try:
            import ib_insync  # noqa: F401
        except Exception:
            self.skipTest("ib_insync is genuinely not installed here")
        self.assertIsNotNone(
            got, "the import failed in a thread with no event loop")


class AFailedImportIsRetriedNotRememberedTests(SimpleTestCase):
    """The second defect, and the one that made it permanent. What fails the
    import is a property of the CALLING THREAD, so caching the verdict for the
    process is caching the wrong thing."""

    def test_is_ibkr_available_retries_rather_than_trusting_the_flag(self):
        import inspect

        from bot_program.engine.ibkr_client import is_ibkr_available
        src = inspect.getsource(is_ibkr_available)
        self.assertIn("global", src)
        self.assertIn("_try_import_ib()", src)

    def test_a_poisoned_flag_recovers_on_the_next_call(self):
        from bot_program.engine import ibkr_client

        try:
            import ib_insync  # noqa: F401
        except Exception:
            self.skipTest("ib_insync is genuinely not installed here")

        prior_mod, prior_flag = ibkr_client._ib, ibkr_client._IB_AVAILABLE
        try:
            # Exactly the state the first loopless thread left behind.
            ibkr_client._ib, ibkr_client._IB_AVAILABLE = None, False
            self.assertTrue(ibkr_client.is_ibkr_available(),
                            "a stale False must not survive one call")
            self.assertIsNotNone(ibkr_client._ib)
        finally:
            ibkr_client._ib, ibkr_client._IB_AVAILABLE = prior_mod, prior_flag

    def test_no_guard_reads_the_raw_flag_behind_the_retry(self):
        """A single stale read anywhere else defeats the whole fix: the guard
        returns early, the router substitutes PaperTrader, and the retry never
        runs. Only `is_ibkr_available` itself may touch the global."""
        import inspect

        from bot_program.engine import ibkr_client
        src = inspect.getsource(ibkr_client)
        inside = inspect.getsource(ibkr_client.is_ibkr_available)
        outside = src.replace(inside, "")
        # The module-level assignment is the one legitimate remaining use.
        leaks = [ln.strip() for ln in outside.splitlines()
                 if "_IB_AVAILABLE" in ln
                 and not ln.startswith("_IB_AVAILABLE =")
                 and not ln.strip().startswith("#")]
        self.assertEqual(leaks, [], f"these read the flag directly: {leaks}")


class TheOperatorIsToldWhichThingIsWrongTests(SimpleTestCase):
    """"not installed" sent the operator to pip, to the Dockerfile, and to
    moving a brokerage account row between two users. The message must not
    name a cause it has not established."""

    def test_the_log_line_does_not_claim_the_package_is_missing(self):
        """Scoped to the log CALL, not the whole function: the docstring
        quotes the old wording on purpose, to record what it cost."""
        import inspect

        from bot_program.engine.ibkr_client import _try_import_ib
        src = inspect.getsource(_try_import_ib)
        logged = src.split("log.info(", 1)[1]
        self.assertIn("unavailable", logged)
        self.assertNotIn("not installed", logged)

    def test_it_says_the_verdict_will_be_retried(self):
        import inspect

        from bot_program.engine.ibkr_client import _try_import_ib
        self.assertIn("RETRIED", inspect.getsource(_try_import_ib))
