"""The eToro feed's tests (the feed spec, F1 onwards, 2026-11-07).

F1 builds the pure core (market_data.venue_quotes, venue_store and
venue_session), the one venue-source rule, the harm counters
(bot_program.feed_harms), the pins and the decision replay harness
(tests/feed/harness.py). Nothing here calls eToro, a broker or a model:
every eToro answer is a fake, every clock is a fixed instant, and every
symbol and value is synthetic.
"""
