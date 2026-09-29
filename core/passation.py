"""THE HANDOVER (2026-09-28): a letter that opens when the operator has left.

The operator, the night before leaving for three weeks at least: "write a
letter of passation, token of respect to Gandalf and the help he has
already provided and the one he's gonna provide for 3 weeks minimum,
something pretty fancy that will only show after 4PM tomorrow afternoon
French time, when I'll have left and my dad will have taken my PC and
duty". Gandalf is his father, who keeps the house on the same account.

One clock, read here and nowhere else: OPENS_AT, 2026-09-29 16:00 Paris
(CEST, UTC+2 until 25 October), as an aware UTC datetime so no server
timezone can move it. Before it the page sends the reader to the
dashboard (never a 404: probe_routes would count the page as missing)
and no card is rendered; after it the page serves the letter for ever,
and the card that points to it stands on every page for CARD_DAYS, the
length of the watch.

Tests patch `_now`, nothing else (tests/test_passation.py).
"""
from datetime import datetime, timedelta, timezone as dt_tz

from django.utils import timezone

#: 16:00 Paris on 2026-09-29, written in UTC on purpose.
OPENS_AT = datetime(2026, 9, 29, 14, 0, tzinfo=dt_tz.utc)
#: The watch: three weeks at least. The card stands that long; the page stays.
CARD_DAYS = 21
CARD_UNTIL = OPENS_AT + timedelta(days=CARD_DAYS)


def _now():
    return timezone.now()


def is_open(now=None) -> bool:
    """The letter may be read."""
    return (now or _now()) >= OPENS_AT


def card_due(now=None) -> bool:
    """The card that leads to the letter stands on every page."""
    now = now or _now()
    return OPENS_AT <= now < CARD_UNTIL
