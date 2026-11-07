"""THE ONE VENUE-SOURCE RULE (the eToro feed spec, F1, §3.2 item 3, harm
27; 2026-11-07): did the venue's own reader write a quote whose source is
this?

Three tests answered it before F1 and they disagree on names no code
writes; the readings keep each caller's answer to the letter
(tests/feed/test_venue_source_one_rule.py runs the old and the new side
by side over every source the code base writes):

  CHANNEL  the spec's rule: the venue's own name or one of its channels —
           "etoro", "etoro_ws", "etoro_rest", "etoro-..." — trimmed, in
           any case (portfolio.services' P&L tier before F1);
  EXACT    the venue's own name only, any case, untrimmed: the carrier's
           own write (venue_mark.quote_stand_in, generic over carriers: an
           OANDA row's "oanda_stream" quote is not "oanda"'s own write);
  PREFIX   anything that begins with the venue's name, any case, untrimmed
           (mark_sanity.second_opinion, VENUE_SOURCES, 2026-10-05).

STANDARD LIBRARY ONLY, AND IMPORTED AT MODULE LEVEL BY ITS CALLERS (the
review of F1, 2026-11-07). The three callers sit inside code that fails
open — an exception there waives a stand-in check or a second opinion — so
the rule must never be able to fail at the moment of a decision: it loads
with them, or they do not load at all. market_data.venue_quotes re-exports
it; a pin (tests/feed/test_feed_pins.py) keeps this module free of every
import but the standard library's.
"""
from __future__ import annotations

#: The venue whose prices the feed carries, and the LiveQuote source its
#: readers write today (the legacy Sync button, the interim quotes beat).
VENUE = "etoro"

CHANNEL = "channel"
EXACT = "exact"
PREFIX = "prefix"
READINGS = (CHANNEL, EXACT, PREFIX)


def is_venue_source(source, venue=VENUE, *, reading=CHANNEL) -> bool:
    """Did `venue`'s own reader write a quote whose source is `source`?

    ONE FUNCTION FOR THE THREE TESTS THAT ANSWERED IT BEFORE F1. They
    agree on every source the code base writes ("etoro" from the legacy
    Sync and the interim quotes beat; every outside feed's name; any
    case). They differ only on names no code writes — "etoro_ws", a padded
    " etoro", "etorox" — and each caller keeps its own answer there by its
    `reading`, so no decision moves."""
    if reading not in READINGS:
        raise ValueError(f"not a reading: {reading!r}")
    if not venue:
        return False
    if reading == EXACT:
        # venue_mark.quote_stand_in before F1, to the letter
        return str(source or "").lower() == str(venue).lower()
    if reading == PREFIX:
        # mark_sanity.second_opinion before F1, to the letter
        return str(source or "").lower().startswith(str(venue))
    # portfolio.services._is_etoro_source before F1, to the letter
    s = str(source or "").strip().lower()
    v = str(venue).strip().lower()
    return bool(v) and (s == v or s.startswith((v + "_", v + "-")))
