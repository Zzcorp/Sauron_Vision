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
from bot_program.engine import paper_trader as _paper_trader

_paper_trader.MARKET_HOURS_GATE = False
