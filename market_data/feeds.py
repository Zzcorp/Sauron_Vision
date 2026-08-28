"""The feeds this platform knows about — declared, not inferred.

`/api/live/health/` used to build its list by grouping the `source` column
of the rows that happened to exist. That reads well until you notice what it
cannot say. `LiveQuote` is ONE row per instrument (a OneToOneField) with a
single `source` column that the winning writer overwrites, so "which feeds
exist" was really "which feed last won the write for some instrument" — and
three different failures all rendered as the same thing, silence:

  * A feed with no credentials never starts, never writes, and therefore
    never appears. OANDA has been absent from the panel this whole time,
    which reads as "nothing to worry about" rather than "off".
  * A feed that is streaming perfectly but ranks below another on every
    instrument it covers holds no rows and vanishes the moment the better
    one connects — `binance_public` disappears when `binance_ws` comes up,
    even though it is doing exactly its job.
  * A feed that only speaks during its market's hours goes red every night.
    `finnhub_ws` writes on US stock trade prints and nothing else, so a
    perfectly healthy Finnhub is red from 20:00 UTC to 13:30 UTC, all
    weekend, and every holiday.

The third one is why the operator asked. A panel that cries wolf nightly is
a panel nobody reads on the morning it means it.

So the list is declared here and the freshness is judged against it. The
states below carry the distinction the old three could not:

    green / yellow / red   fresh, slowing, stale — inside the feed's own
                           window and against its own tolerance
    idle                   configured and quiet because its market is shut.
                           Not a fault. Grey-blue, never red.
    yielding               configured, running, but outranked on every
                           instrument it covers. Doing its job invisibly.
    never                  configured and has NEVER delivered a quote.
                           The loudest state here, because it is the one
                           that means a thing the operator switched on has
                           never once worked.
    off                    no credentials. Grey. Not switched on is not
                           broken, and a panel that shouts about a feed
                           nobody wants trains its reader to ignore it.
    unregistered           a source string in the database that this file
                           does not know. Shown rather than dropped: it
                           means this file has fallen behind the writers.
"""
from __future__ import annotations

import os

# Freshness tolerances, per feed, replacing one global 60s/600s pair that
# was calibrated for a websocket and applied to a ten-minute poller.
_WS = (60, 300)             # a stream is late at a minute, dead at five
_FAST_POLL = (400, 1200)    # a five-minute poller
_SLOW_POLL = (900, 3600)    # a ten-minute-or-worse poller
_FALLBACK = (3600, 21600)   # only speaks when nothing better is available


class Window:
    """When a feed is EXPECTED to be speaking."""

    ALWAYS = "always"        # crypto: 24/7
    FOREX = "forex"          # Sunday 17:00 ET -> Friday 17:00 ET
    US_EQUITY = "us_equity"  # US regular session


FEEDS = (
    # ── streams ──────────────────────────────────────────────────────
    {"key": "binance_ws", "label": "Binance (stream)", "kind": "stream",
     "requires": (), "window": Window.ALWAYS, "ages": _WS,
     "note": "Crypto trade prints over websocket"},

    {"key": "oanda_stream", "label": "OANDA (stream)", "kind": "stream",
     "requires": ("OANDA_API_KEY", "OANDA_ACCOUNT_ID"),
     "window": Window.FOREX, "ages": _WS,
     "note": "Forex mid prices over websocket"},

    {"key": "finnhub_ws", "label": "Finnhub (stream)", "kind": "stream",
     "requires": ("FINNHUB_API_KEY",),
     "window": Window.US_EQUITY, "ages": _WS,
     "note": "US equity trade prints — silent outside the session"},

    {"key": "ibkr", "label": "IBKR", "kind": "stream",
     "requires": (), "window": Window.ALWAYS, "ages": _WS,
     "note": "Broker feed, when a gateway is connected"},

    # ── pollers ──────────────────────────────────────────────────────
    {"key": "yfinance", "label": "Yahoo Finance", "kind": "poller",
     "requires": (), "window": Window.ALWAYS, "ages": _SLOW_POLL,
     "note": "Keyless marks for stocks, indices, commodities and forex"},

    {"key": "binance_public", "label": "Binance (REST)", "kind": "poller",
     "requires": (), "window": Window.ALWAYS, "ages": _FAST_POLL,
     "superseded_by": "binance_ws",
     "note": "Keyless crypto marks — yields to the websocket stream"},

    # Capped at twenty calls a day and it SKIPS any symbol a streamer
    # already owns — "spending one of the 20 daily calls on a print that
    # precedence will refuse is the budget subsidising a worse feed"
    # (market_data/tasks.py). So on a healthy install with the OANDA
    # stream up, this feed writing nothing is the budget being spent
    # correctly, not a fault. `superseded_by` is what lets it report
    # `yielding` instead of the alarming `never`.
    {"key": "alpha_vantage", "label": "Alpha Vantage", "kind": "poller",
     "requires": ("ALPHA_VANTAGE_API_KEY",),
     "window": Window.FOREX, "ages": _FALLBACK,
     "superseded_by": "oanda_stream",
     "note": "Forex marks on a 20/day budget — quiet while OANDA streams"},

    # ── brokers ──────────────────────────────────────────────────────
    {"key": "etoro", "label": "eToro", "kind": "broker",
     "requires": ("ETORO_API_KEY",), "window": Window.ALWAYS,
     "ages": _SLOW_POLL, "note": "Synced holdings and their marks"},

    # ── last resorts ─────────────────────────────────────────────────
    {"key": "coingecko", "label": "CoinGecko", "kind": "fallback",
     "requires": (), "window": Window.ALWAYS, "ages": _FALLBACK,
     "superseded_by": "binance_ws",
     "note": "Crypto fallback — expected quiet while a stream is up"},
)

# Only feeds that a writer in this repo actually stamps onto
# LiveQuote.source belong above. `binance`, `oanda`, `alpaca`, `twelve_data`
# and `fmp` appear in market_data/quotes.py's SOURCE_PRIORITY table but no
# code path ever writes them, and declaring them here was a real defect, not
# a cosmetic one: `binance` needs no credentials, so it read as CONFIGURED
# on every deployment, sat permanently in `never`, and — `never` not being
# benign — made `len(live) == len(watched)` unsatisfiable. The top-bar dot
# could never be green on ANY install, which is worse than the derived list
# it replaced: an operator whose feeds all died would see the same amber
# they had been looking at all along.
#
# If one of them gains a writer, declare it here in the same change.

BY_KEY = {f["key"]: f for f in FEEDS}


def is_configured(feed: dict) -> bool:
    """True when every credential this feed needs is present AND non-empty.

    Non-empty matters: an `.env` carrying `FINNHUB_API_KEY=` with nothing
    after it sets the variable, so a bare presence check would call the feed
    configured and then report it red forever for failing to deliver on a
    key it never had.
    """
    return all(os.environ.get(name, "").strip() for name in feed["requires"])


def missing_credentials(feed: dict) -> list:
    return [n for n in feed["requires"] if not os.environ.get(n, "").strip()]


def window_is_open(window: str, now=None) -> bool:
    """Is this feed's market trading right now?

    Answering "no" is what turns a nightly red Finnhub into an honest grey
    idle. Any doubt resolves to True — claiming a market is shut when it is
    not would hide a genuinely dead feed, which is the failure this whole
    module exists to stop.
    """
    from django.utils import timezone

    now = now or timezone.now()
    if window == Window.ALWAYS:
        return True
    try:
        if window == Window.FOREX:
            from bot_program.asset_engine.forex_bot import forex_market_open
            return forex_market_open(now)
        if window == Window.US_EQUITY:
            from zoneinfo import ZoneInfo
            local = now.astimezone(ZoneInfo("America/New_York"))
            if local.weekday() >= 5:
                return False
            minutes = local.hour * 60 + local.minute
            # 09:30 -> 16:00 ET. Holidays are not modelled: a feed idle on
            # Thanksgiving reports stale for a day, which is a smaller lie
            # than a calendar this file would have to keep current.
            return 570 <= minutes < 960
    except Exception:  # noqa: BLE001 — a health panel must never 500
        return True
    return True


def window_last_closed(window: str, now=None):
    """When this feed's market most recently shut, or None if it never does.

    What separates "quiet because the market is shut" from "died during the
    session and the shut market is covering for it". A duration bound cannot
    draw that line: an ordinary overnight gap is seventeen hours and a
    weekend is sixty-five, so any threshold either forgives a Friday-morning
    death or condemns a healthy Sunday.
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from django.utils import timezone

    now = now or timezone.now()
    if window == Window.ALWAYS:
        return None
    try:
        if window == Window.US_EQUITY:
            local = now.astimezone(ZoneInfo("America/New_York"))
            close = local.replace(hour=16, minute=0, second=0, microsecond=0)
            while close > local or close.weekday() >= 5:
                close -= timedelta(days=1)
                close = close.replace(hour=16, minute=0, second=0,
                                      microsecond=0)
            return close
        if window == Window.FOREX:
            local = now.astimezone(ZoneInfo("America/New_York"))
            # Friday 17:00 ET.
            close = local.replace(hour=17, minute=0, second=0, microsecond=0)
            while close > local or close.weekday() != 4:
                close -= timedelta(days=1)
                close = close.replace(hour=17, minute=0, second=0,
                                      microsecond=0)
            return close
    except Exception:  # noqa: BLE001 — a health panel must never raise
        return None
    return None


def state_for(feed: dict, *, latest, age_seconds, superseder_ok=False,
              now=None) -> tuple:
    """(state, note) for one declared feed.

    `latest` is the freshest updated_at bearing this feed's key, or None.
    `superseder_ok` says whether the feed named in `superseded_by` is itself
    delivering right now — the difference between "this feed is dead" and
    "a better feed is winning every instrument it covers, which is the
    system working".

    That last distinction cannot be drawn from LiveQuote alone. The table
    holds ONE row per instrument with a single `source` column, so a feed
    that is outranked everywhere leaves no trace at all — it is
    indistinguishable from one that has never run. The first version of
    this function tried to tell them apart with a `holds_rows` flag, but
    its only caller derived that flag and `latest` from the same GROUP BY,
    so the two were the same condition and the `yielding` branch was
    unreachable. Asking the SUPERSEDER instead is a question the data can
    actually answer.
    """
    if not is_configured(feed):
        missing = missing_credentials(feed)
        return "off", "not configured — " + ", ".join(missing)

    warn_age, dead_age = feed["ages"]
    fresh = age_seconds is not None and age_seconds < warn_age
    if fresh:
        return "green", feed.get("note", "")

    # Quiet because something better is answering. Checked BEFORE `never`:
    # on a healthy install with the websocket up, the REST poller's every
    # write is refused by SOURCE_PRIORITY, so it has genuinely never
    # written a row and would otherwise be reported as a dead feed.
    if superseder_ok:
        return "yielding", ("running, but " + feed["superseded_by"]
                            + " is winning every instrument it covers")

    if latest is None:
        # Configured, and has never once produced a quote. The loudest
        # state on the panel, because the operator switched this on.
        return "never", "configured, but has never delivered a quote"

    if not window_is_open(feed["window"], now):
        # `idle` forgives silence, so it must not become the second place a
        # dead feed can hide. The test is not "how long has it been quiet" —
        # an ordinary overnight gap is seventeen hours and a weekend is
        # sixty-five, so any duration bound either forgives a feed that died
        # on Friday morning or condemns a healthy one on Sunday.
        #
        # The test is WHETHER IT WAS ALIVE WHEN THE MARKET LAST SHUT. A feed
        # whose newest quote predates the last close stopped delivering
        # during a session, which is a fault the closed market is merely
        # hiding.
        closed_at = window_last_closed(feed["window"], now)
        if closed_at is not None and latest is not None and latest < closed_at:
            return "red", ("silent since before its market closed — it "
                           "stopped during the session, not because of it")
        return "idle", "quiet — its market is closed"

    if age_seconds is not None and age_seconds < dead_age:
        return "yellow", "slower than expected"
    return "red", "stale — nothing recent from this feed"


#: The states that should NOT colour the top-bar pill. A feed nobody
#: configured, one whose market is shut, and one a better feed is
#: outranking are all the system working, not faults to escalate.
BENIGN_STATES = ("off", "idle", "yielding")
