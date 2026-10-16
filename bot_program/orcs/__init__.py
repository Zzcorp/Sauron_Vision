"""THE ORCS (spec §1-§10): one trader agent per open position, per IDEA.

O1 builds them with no model: each open position is born an Orc, with a
thesis, an army type and a journal of facts written by code (the care's
and the venue's stop moves, the reviews, the thesis checks, the close).
Nothing here sends an order, moves a stop or calls a model. Everything O1
writes lives in the Orc tables, plus one stamp on the trade row
(metadata["orc"], §10.1) that the death receiver reads without a join.

The switch `orcs` (System, OFF on arrival) gates every write; while it is
OFF the platform behaves exactly as before.

This module imports nothing: the package is loaded before the apps are
ready (bot_program/models.py imports orcs.models).
"""
