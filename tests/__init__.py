"""The test package.

THE WALL CLOCK IS NOT AN INPUT TO THIS SUITE (2026-09-26). The paper venue
refuses every fill and every exit while the instrument's market is shut
(bot_program/engine/paper_trader.py MARKET_HOURS_GATE), and hundreds of
tests here open and close paper positions at whatever instant they run: a
stock close run at 03:00 UTC, or a forex close run on a Saturday, would
fail for the hour and not for the code. So the suite runs with the gate
off, and tests/test_paper_market_hours.py turns it back on at a fixed
clock for every path it pins.
"""
from backtester.proving import proof as _proof
from bot_program import entry_timing as _entry_timing
from bot_program.engine import etoro_budget as _etoro_budget
from bot_program.engine import etoro_client as _etoro_client
from bot_program.engine import etoro_rates as _etoro_rates
from bot_program.engine import paper_trader as _paper_trader
from bot_program.management.commands import etoro_smoke as _etoro_smoke

_paper_trader.MARKET_HOURS_GATE = False
# The same reason, one layer up (2026-10-06): the entry timing refuses a
# new entry in the rollover window, a market's first quarter hour, its
# last minutes and the hour before a print, and hundreds of entries here
# run at whatever instant they run. tests/test_entry_timing.py turns it
# back on at a fixed clock.
_entry_timing.GATE = False
# THE /search MEMO (2026-10-06, etoro_client.SEARCH_MEMO) keeps an id for
# the UTC day across EtoroTrader instances, and the suite's fake wires
# answer /search with ids per test and count the calls: kept on, a test
# would read another test's id. tests/test_etoro_search_memo.py turns it
# back on.
_etoro_client.SEARCH_MEMO = False
_etoro_client.SEARCH_SHARED_MEMO = False  # its Redis copy (2026-10-07)
# THE 429 PAUSE and THE /search "NO" (2026-10-07): per-process memories a
# fake wire's 429 or empty answer would leak into the next test.
# tests/test_etoro_rate_pause.py turns both back on.
_etoro_client.RATE_PAUSE = False
_etoro_client.SEARCH_NO_MEMO = False
# THE eTORO REQUEST BUDGET (2026-11-01, etoro_budget.BUDGET): one budget
# per user key per minute, kept in the cache. The suite's fake wires ask
# eToro hundreds of times inside one process minute with the same few
# keys, and LocMem is kept across tests, so with it on a mark or a
# proposal would be refused for another test's reads. Off, every request
# goes as it did before the budget. tests/test_etoro_budget.py turns it
# back on.
_etoro_budget.BUDGET = False
# THE SHARED RATES CACHE AND THE BATCHED MARKS (2026-11-01,
# etoro_rates.CACHE): every eToro rates answer is kept 30 s in the cache,
# keyed (world, instrument id), and the marks and the proposals read one
# batched snapshot. The suite's fake wires hand every test the same few
# ids and count each read, and LocMem is kept across tests, so with it on
# a mark would be read off another test's answer. Off, every reader asks
# ticker() as it did before the batch. And THE SHUT-MARKET CADENCE
# (etoro_rates.SHUT_CADENCE) reads the wall clock: a live row managed on a
# Saturday would not be asked. tests/test_etoro_rates_batch.py turns both
# back on.
_etoro_rates.CACHE = False
_etoro_rates.SHUT_CADENCE = False
# THE BATCH WAITS FOR ITS MEASUREMENT (2026-11-02, etoro_rates.
# MEASURED_FIRST): in production nothing is sent in batch before the
# operator's measurement wrote its proof. The suite's batch tests read the
# batch as E2 sent it; tests/test_etoro_rates_batch.py's
# TheBatchWaitsForItsMeasurementTests turns the wait back on.
_etoro_rates.MEASURED_FIRST = False
# THE READ POOL (2026-11-01, etoro_client.READ_POOL): a GET at P2 to P5
# rides one pooled requests.Session per process and user key, kept at
# module level. The suite's fake wires are handed to each client (a
# supplied session carries every request anyway), and a pool kept across
# tests would hand one test's connection to the next. Off, every read rides
# its client's own session as before the pool. tests/test_etoro_cheaper_
# reads.py turns it back on.
_etoro_client.READ_POOL = False
# THE SMOKE'S PACE (2026-11-01, etoro_smoke.SMOKE_GAP_S): one request a
# second, on the wall clock; the suite's smoke runs would sleep through
# every read. tests/test_etoro_cheaper_reads.py turns it back on, on a
# moved clock.
_etoro_smoke.SMOKE_GAP_S = 0.0
# SIZE BY PROOF (2026-10-07, backtester/proving/proof.py): the proving
# ground's verdict would cut or refuse every live entry this suite sizes —
# hundreds of them, on rules no proving run here ever judged, each sized
# and asserted to the unit at full stage size. So the suite runs with the
# proof off; tests/test_size_by_proof.py turns it back on.
_proof.GATE = False
