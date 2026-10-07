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
from bot_program.engine import etoro_client as _etoro_client
from bot_program.engine import paper_trader as _paper_trader

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
# SIZE BY PROOF (2026-10-07, backtester/proving/proof.py): the proving
# ground's verdict would cut or refuse every live entry this suite sizes —
# hundreds of them, on rules no proving run here ever judged, each sized
# and asserted to the unit at full stage size. So the suite runs with the
# proof off; tests/test_size_by_proof.py turns it back on.
_proof.GATE = False
