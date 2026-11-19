"""The invented gold desk on a Saturday afternoon (2026-11-19), for the
measured tests and the pictures of eToro's all-week words.

The bureau v2 note's invented book (tests/audusd_scene_fixture.py: the
REAL XAUUSD short among its rows, the rail's XAUUSD signal, the eToro
account's cells), moved to an instant of the weekend and seen from the
gold page:

    SAT      Saturday 21 November 2026, 15:00 UTC: CME, the FX week and
             NYSE shut; eToro trades GOLD (its all-week list).
    PAUSE    Friday 20 November 2026, 22:10 UTC: inside eToro's Friday
             break, 22:00-22:30 UTC.
    XAUUSD   eToro's quote 2649.50 / 2650.00 read 4 minutes before the
             instant (the REAL short's venue stamp and the 30-second
             read), and 120 one-hour eToro candles of one seeded walk up
             to it, the weekend's included (eToro trades it).

Round, obviously invented levels, sizes and ages; no account id, no host,
no name, nothing real. Display only: nothing here reaches a broker, an
order or a model.
"""
import random
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from tests import audusd_scene_fixture as S

UTC = dt_tz.utc
SAT = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
PAUSE = datetime(2026, 11, 20, 22, 10, tzinfo=UTC)
SYMBOL = "XAUUSD"
PAGE_URL = "/instruments/XAUUSD/"
CHART_ID = S.CHART_ID
#: How old eToro's reading is at the instant.
READ_AGO = timedelta(minutes=4)


def gold_bars(end, n=120, seed=20261121):
    """`n` one-hour gold candles of one seeded walk, the last the forming
    hour of `end`, every hour of the week (eToro trades it all week)."""
    rnd = random.Random(seed)
    start = end.replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=n - 1)
    px, rows = 2655.0, []
    for i in range(n):
        ts = start + timedelta(hours=i)
        o = px
        c = o + rnd.gauss(0, 2.2) - 0.04
        if i == n - 1:
            c = 2649.50
        hi = max(o, c) + abs(rnd.gauss(0, 1.1)) + 0.2
        lo = min(o, c) - abs(rnd.gauss(0, 1.1)) - 0.2
        rows.append((ts, round(o, 2), round(hi, 2), round(lo, 2), round(c, 2),
                     int(300 + rnd.uniform(0, 900))))
        px = c
    return rows


def seed(user, at):
    """The bureau v2 book for `user`, moved to `at`: gold read by eToro
    READ_AGO before it, and gold's candles up to it. Returns
    S.seed_scene's answer."""
    from bot_program.models import AssetBotConfig, AssetBotTrade
    from instruments.models import Instrument
    from market_data.models import LiveQuote, PriceData
    from signals.models import Signal

    book = S.seed_scene(user)
    read = at - READ_AGO
    gold = Instrument.objects.get(symbol=SYMBOL)
    LiveQuote.objects.filter(instrument=gold).update(updated_at=read)
    for t in AssetBotTrade.objects.filter(symbol=SYMBOL):
        meta = dict(t.metadata or {})
        if isinstance(meta.get("venue_mark"), dict):
            meta["venue_mark"] = dict(meta["venue_mark"], at=read.isoformat())
            AssetBotTrade.objects.filter(pk=t.pk).update(metadata=meta)
    for cfg in AssetBotConfig.objects.filter(user=user):
        extras = dict(cfg.extras or {})
        if "last_tick_at" in extras:
            extras["last_tick_at"] = (at - timedelta(seconds=90)).isoformat()
            AssetBotConfig.objects.filter(pk=cfg.pk).update(extras=extras)
    Signal.objects.filter(instrument=gold).update(
        created_at=at - timedelta(hours=2))
    q2 = lambda v: Decimal(str(round(v, 2)))  # noqa: E731
    PriceData.objects.bulk_create([
        PriceData(instrument=gold, timeframe="1h", source="etoro",
                  timestamp=ts, open=q2(o), high=q2(h), low=q2(lo),
                  close=q2(c), volume=v)
        for ts, o, h, lo, c, v in gold_bars(at)])
    return book
