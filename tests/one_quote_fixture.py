"""The synthetic fixture of the one-price tests (2026-11-12).

Round, invented instruments, levels, sizes and ages: the measurement
fixture of scratchpad/onequote/measure_before.md, held at one instant `T`
(a Thursday evening, every market open). Nothing here is anybody's data.

    held, real, eToro (venue stamps with bid/ask):
      EURUSD  forex      stamp 1.08452 (bid 1.08447 / ask 1.08457), 25 s
              LiveQuote  an OLDER eToro row 1.08390 (1.08385 / 1.08395), 7 min
      XAUUSD  commodity  stamp 2648.55 (bid 2648.30 / ask 2648.80), 40 s
              LiveQuote  Yahoo's future GC=F 2671.30, 90 s, sideless
      AAPL    stock      stamp 228.31 (bid 228.27 / ask 228.35), 15 s
              LiveQuote  finnhub_ws 227.94, 3 min, sideless (change Yahoo's)
    nobody holds:
      GBPUSD  forex      LiveQuote yfinance 1.29410, 4 min, sideless

The reference every surface must print: EURUSD 1.08447, XAUUSD 2648.30,
AAPL 228.27 (eToro's bid: every row is a long), GBPUSD 1.29410.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

#: The fixture's instant: Thursday 12 November 2026, 19:13:56 UTC.
T = datetime(2026, 11, 12, 19, 13, 56, tzinfo=dt_tz.utc)

INSTRUMENTS = {
    "EURUSD": ("Euro / US Dollar", "forex", "FX"),
    "XAUUSD": ("Gold", "commodity", "COMEX"),
    "AAPL": ("Apple", "stock", "NASDAQ"),
    "GBPUSD": ("British Pound / US Dollar", "forex", "FX"),
    "EURGBP": ("Euro / British Pound", "forex", "FX"),
    "SPX500": ("S&P 500", "index", "NYSE"),
    "USDJPY": ("US Dollar / Japanese Yen", "forex", "FX"),
}

REFERENCE = {"EURUSD": "1.08447", "XAUUSD": "2648.30", "AAPL": "228.27",
             "GBPUSD": "1.29410"}


def instrument(symbol, *, watch=True):
    from instruments.models import Instrument
    name, cls, exch = INSTRUMENTS.get(symbol, (symbol, "stock", "NYSE"))
    inst, _ = Instrument.objects.update_or_create(
        symbol=symbol, defaults={"name": name, "asset_class": cls,
                                 "exchange": exch, "currency": "USD",
                                 "is_active": True, "is_watchlist": watch})
    return inst


def quote(symbol, last, source, age_s, *, bid=None, ask=None, chg="0",
          chg_src=None, at=None):
    """A LiveQuote row written `age_s` before T (or before `at`)."""
    from market_data.models import LiveQuote
    inst = instrument(symbol)
    LiveQuote.objects.update_or_create(
        instrument=inst,
        defaults={"last": Decimal(str(last)), "source": source,
                  "bid": None if bid is None else Decimal(str(bid)),
                  "ask": None if ask is None else Decimal(str(ask)),
                  "change_pct": Decimal(str(chg)), "volume": 0,
                  "change_source": source if chg_src is None else chg_src})
    LiveQuote.objects.filter(instrument=inst).update(
        updated_at=(at or T) - timedelta(seconds=age_s))
    return inst


def stamp(price, bid=None, ask=None, age_s=0, via="tick", at=None):
    vm = {"price": float(price), "source": "etoro", "via": via,
          "at": ((at or T) - timedelta(seconds=age_s)).isoformat()}
    if bid is not None:
        vm["bid"] = float(bid)
        vm["ask"] = float(ask)
    return vm


def lane(user, asset_class, *, name=None, mode="live"):
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=asset_class, name=name or f"oq {asset_class}",
        defaults={"enabled": True, "mode": mode, "symbols": [],
                  "capital": Decimal("10000"), "base_currency": "USD"})
    return cfg


def held(user, symbol, *, side="BUY", vm=None, qty="1", entry="100",
         stop=None, target=None, world="live", paper=False, broker="etoro",
         status="OPEN"):
    """An open row at eToro (real money, or eToro's demo world)."""
    from bot_program.models import AssetBotTrade
    inst = instrument(symbol)
    meta = {"broker": broker,
            "broker_env": "paper" if world == "demo" else "live"}
    if stop is not None:
        meta["initial_stop_loss"] = float(stop)
    if vm is not None:
        meta["venue_mark"] = vm
    t = AssetBotTrade.objects.create(
        config=lane(user, inst.asset_class), asset_class=inst.asset_class,
        symbol=symbol, side=side, qty=Decimal(str(qty)),
        entry_price=Decimal(str(entry)),
        stop_loss=None if stop is None else Decimal(str(stop)),
        take_profit=None if target is None else Decimal(str(target)),
        status=status, paper=paper, rule_name="ema_cross", metadata=meta)
    from bot_program.models import AssetBotTrade as M
    M.objects.filter(pk=t.pk).update(opened_at=T - timedelta(hours=5))
    return t


def previous_close_event(symbol, at):
    from bot_program.feed_harm_models import FeedHarmEvent
    return FeedHarmEvent.objects.create(kind="poller_previous_close",
                                        symbol=symbol, source="yfinance",
                                        at=at)


def daily_bar(symbol, day, close, source="yfinance"):
    from market_data.models import PriceData
    c = Decimal(str(close))
    return PriceData.objects.create(
        instrument=instrument(symbol), timeframe="1d", timestamp=day,
        open=c, high=c, low=c, close=c, volume=1, source=source)


def seed_measured(user):
    """The measurement fixture: three held eToro longs and one unheld pair
    (the module docstring). Returns {symbol: trade} for the held rows."""
    quote("EURUSD", "1.08390", "etoro", 420, bid="1.08385", ask="1.08395",
          chg="0.12", chg_src="yfinance")
    quote("XAUUSD", "2671.30", "yfinance", 90)
    quote("AAPL", "227.94", "finnhub_ws", 180, chg="0.85",
          chg_src="yfinance")
    quote("GBPUSD", "1.29410", "yfinance", 240, chg="-0.21")
    return {
        "EURUSD": held(user, "EURUSD", qty="10000", entry="1.08210",
                       stop="1.07900", target="1.08900",
                       vm=stamp("1.08452", "1.08447", "1.08457", 25)),
        "XAUUSD": held(user, "XAUUSD", qty="0.5", entry="2640.00",
                       stop="2620.00", target="2690.00",
                       vm=stamp("2648.55", "2648.30", "2648.80", 40)),
        "AAPL": held(user, "AAPL", qty="4", entry="225.00", stop="219.00",
                     target="240.00",
                     vm=stamp("228.31", "228.27", "228.35", 15)),
    }
