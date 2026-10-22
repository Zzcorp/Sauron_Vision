"""Shared fixtures for the Orcs' suites. No network anywhere: every broker
is a MagicMock and every switch a PlatformComponent row."""
from decimal import Decimal

from django.contrib.auth import get_user_model

from tests.test_aragorn import _switch  # noqa: F401  (re-exported)
from tests.test_risk_limits_bind import _config  # noqa: F401  (re-exported)

ROUTER = "bot_program.engine.broker_router.client_for_symbol"


def _user(name="orc_u"):
    return get_user_model().objects.create_user(name, password="x")


def _on(on=True):
    """The orcs switch, and the platform master the census's gate reads."""
    _switch("platform_master", True)
    _switch("orcs", on)


def _manual_config(user, asset_class="crypto", **kw):
    from bot_program.manual_trade import MANUAL_CONFIG_NAME
    return _config(user, asset_class, name=MANUAL_CONFIG_NAME, symbols=[],
                   **kw)


def _row(cfg, *, qty="1", entry="100", stop="98", side="BUY", paper=True,
         cls=None, symbol="BTCUSD", meta=None, rule="golden_cross",
         status="OPEN", target="110"):
    """An open trade row: entry 100, stop 98, so 102 is +1R."""
    from bot_program.models import AssetBotTrade
    base = {} if stop is None else {"initial_stop_loss": float(stop)}
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cls or cfg.asset_class, symbol=symbol,
        side=side, qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=None if stop is None else Decimal(stop),
        take_profit=None if target is None else Decimal(target),
        status=status, paper=paper, rule_name=rule,
        metadata={**base, **(meta or {})})


def _manual_row(cfg, **kw):
    from bot_program.manual_trade import MANUAL_RULE
    kw.setdefault("rule", MANUAL_RULE)
    return _row(cfg, **kw)


def born(test, trade, *, at=None, **kw):
    """ensure() with the after-commit work run, as the hooks run it. `at`
    pins the birth instant (the clock and `now`): the arms are seeded and
    Orc.born_at stamped there, as a birth at that moment would."""
    from bot_program.orcs.birth import ensure
    if at is None:
        with test.captureOnCommitCallbacks(execute=True):
            return ensure(trade, **kw)
    from unittest.mock import patch
    kw.setdefault("now", at)
    with patch("django.utils.timezone.now", return_value=at), \
            test.captureOnCommitCallbacks(execute=True):
        return ensure(trade, **kw)


def journal(orc, **filters):
    from bot_program.orcs.models import OrcJournal
    return list(OrcJournal.objects.filter(orc=orc, **filters)
                .order_by("at", "id"))


def headlines(orc, **filters):
    return [e.headline for e in journal(orc, **filters)]


# ── O1b: bars ─────────────────────────────────────────────────────────────

SPAN_H = {"1h": 1, "4h": 4, "1d": 24}


def _inst(symbol="BTCUSD", asset_class="crypto"):
    from tests.test_risk_limits_bind import _instrument
    return _instrument(symbol, asset_class)


def _bars(symbol, tf, ohlc, *, start, source="etoro", asset_class="crypto",
          step=None):
    """Write bars of `symbol` on `tf` from `start` (each bar's OPEN time),
    one per (open, high, low, close) in `ohlc` (a bare number is a flat
    bar at that price). Returns the bars' open times."""
    from datetime import timedelta

    from market_data.models import PriceData
    inst = _inst(symbol, asset_class)
    step = step or timedelta(hours=SPAN_H[tf])
    out = []
    for i, bar in enumerate(ohlc):
        if not isinstance(bar, (list, tuple)):
            bar = (bar, bar, bar, bar)
        o, h, lo, c = (Decimal(str(x)) for x in bar)
        ts = start + i * step
        PriceData.objects.update_or_create(
            instrument=inst, timeframe=tf, timestamp=ts,
            defaults={"open": o, "high": h, "low": lo, "close": c,
                      "volume": 0, "source": source})
        out.append(ts)
    return out


def _wave(n, *, base=100.0, amp=2.0, period=12, drift=0.0):
    """n bars of a sine wave with swings every half period: real highs and
    lows for the swing reader. (open, high, low, close)."""
    import math
    out = []
    prev = base
    for i in range(n):
        c = base + drift * i + amp * math.sin(2 * math.pi * i / period)
        o = prev
        h = max(o, c) + amp * 0.1
        lo = min(o, c) - amp * 0.1
        out.append((round(o, 5), round(h, 5), round(lo, 5), round(c, 5)))
        prev = c
    return out


# ── O1b: driving the real tick ───────────────────────────────────────────

def _ticker(price, bid=None, ask=None):
    out = {"lastPrice": str(price)}
    if bid is not None:
        out["bid"] = str(bid)
    if ask is not None:
        out["ask"] = str(ask)
    return out


def drive(test, cfg, row, marks, *, client=None, until_closed=True):
    """The real manage_positions on `cfg`, one pass per (at, price[, bid,
    ask]) in `marks`, the clock pinned at `at`. Returns (bot, client)."""
    from contextlib import ExitStack
    from unittest.mock import MagicMock, patch

    from bot_program.asset_engine.base import make_bot
    bot = make_bot(cfg)
    if client is None:
        client = MagicMock()
        client.get_positions.return_value = []
    for mark in marks:
        at, price = mark[0], mark[1]
        bid = mark[2] if len(mark) > 2 else None
        ask = mark[3] if len(mark) > 3 else None
        client.ticker.return_value = _ticker(price, bid, ask)
        with ExitStack() as stack:
            stack.enter_context(patch(ROUTER, return_value=client))
            stack.enter_context(patch("django.utils.timezone.now",
                                      return_value=at))
            stack.enter_context(test.captureOnCommitCallbacks(execute=True))
            bot.manage_positions()
        row.refresh_from_db()
        if until_closed and row.status != "OPEN":
            break
    return bot, client


def care_tick(test, bot, row, price, client, at, *, bid=None, ask=None):
    """The real care() then the Orcs' hook, as manage_positions runs them,
    for a row the full pass would not reach in a test (a live protected
    row): the clock pinned at `at`. Returns what care() returned."""
    from decimal import Decimal
    from unittest.mock import patch

    from bot_program.orcs.observe import after_care
    from bot_program.position_care import care
    bot._tick_broker_cache = {}
    bot._last_ticks = {row.symbol: _ticker(price, bid, ask)}
    with patch("django.utils.timezone.now", return_value=at), \
            test.captureOnCommitCallbacks(execute=True):
        cared = care(bot, row, Decimal(str(price)), client)
        after_care(bot, row, Decimal(str(price)), cared)
    row.refresh_from_db()
    return cared


def tracks_of(orc):
    from bot_program.orcs.models import OrcTrack
    return {t.arm: t for t in OrcTrack.objects.filter(orc=orc)}
