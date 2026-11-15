"""A cold cache for the tests that count queries (2026-11-13).

LocMem lives as long as the test process (one per CI worker), while the
rows a test writes are rolled back, and SQLite rolls its sequence back
too: the next test's user has the same pk. So a request can read entries
an earlier test in the same worker left behind:

  presence:<pk>               the presence throttle, 60 s (core.presence)
  hb:sparks3                  the headband's sparks, 300 s (core.context_ui)
  chart:levels:<symbol>       the instrument chart's overlays, 60 s each
  chart:positioning:<symbol>  (dashboard.views, LEVELS_TTL)

They run out on the wall clock, which a test's patch of timezone.now does
not move. One that runs out between the two requests a query count
compares, or between a warm-up and the request a ceiling bounds, makes
that request alone pay the stamp or the refill: CI run 43384272086 failed
69 != 75 that way (tests.test_rail_market_shut, test_9). From a cold
cache, the test's own warm-up pays them, and the requests it measures
read the same cache.

Call it first in setUp. tests/test_rail_every_signal.py imports it too,
and tests/test_rail_market_shut.py takes it from there.
"""
from django.core.cache import cache


def _cold_cache():
    """Start the test from a cold cache (see the module docstring)."""
    cache.clear()
