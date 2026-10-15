"""Point-in-time readers over tables Sauron already stores (spec §2.4, R0-R1).

One `Store` per read (or one per replay): it loads each series once and
slices it by date, so a 3-year replay is not 750 copies of the same query.

  closes  PriceData 1d, a bar's market day being its stamp read at noon UTC
          (midnight in New York, London, Tokyo or Sydney, and Binance's
          00:00 UTC, all land on their own day). Never the live quote: a
          replay equals a live read.
  cot     COTReport, live by report_date, replayed by publication time.
  fred    MacroObservation, live by observation date, replayed by release.

Nothing here raises past a reader: a missing series is an empty one, and
the caller words the dash.
"""
from __future__ import annotations

import bisect
import os
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_tz

UTC = dt_tz.utc

#: COT reports dated in the 2025 shutdown backlog became public only as the
#: CFTC caught up, through 2025-12-29
#: (https://www.cftc.gov/PressRoom/PressReleases/9147-25, seen 2026-10-08).
COT_BACKLOG = (date(2025, 9, 30), date(2025, 12, 23))
COT_BACKLOG_PUBLIC = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

#: FRED series published weekly with the H.4.1 (Thursday 16:30 ET for the
#: Wednesday): readable two days after the observation in a replay.
WEEKLY_SERIES = frozenset({"WALCL", "WTREGEN", "WRESBAL", "WMTSECL1"})
FRED_BOUNDS = {"WALCL": 9, "WTREGEN": 9, "WRESBAL": 9, "WMTSECL1": 9,
               "RRPONTSYD": 5, "VIXCLS": 5, "VXVCLS": 5, "BAMLH0A0HYM2": 5}
#: The eight series the board reads (fred-history pulls these).
BOARD_FRED_SERIES = ("WALCL", "WTREGEN", "RRPONTSYD", "WRESBAL", "WMTSECL1",
                     "VIXCLS", "VXVCLS", "BAMLH0A0HYM2")
UNITS_TO_MILLIONS = {"Millions of U.S. Dollars": 1,
                     "Billions of U.S. Dollars": 1000}


def market_day(ts) -> date:
    """A daily bar's market day: its stamp read at noon UTC."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (ts.astimezone(UTC) + timedelta(hours=12)).date()


def fred_key_set() -> bool:
    return bool(os.getenv("FRED_API_KEY", ""))


def cot_public_at(report_date: date) -> datetime:
    """When a replay may read a COT report: report_date + 6 days at 21:00
    UTC, never earlier than a Friday or a holiday-Monday release (one day
    later than the live Saturday read: conservative); the 2025 backlog
    from 2026-01-01."""
    if COT_BACKLOG[0] <= report_date <= COT_BACKLOG[1]:
        return COT_BACKLOG_PUBLIC
    return datetime.combine(report_date + timedelta(days=6), time(21, 0),
                            tzinfo=UTC)


class Store:
    """Each series loaded once, sliced by date. `upto` bounds the loads."""

    def __init__(self, upto: date | None = None):
        self.upto = upto
        self._series = {}
        self._cot = {}
        self._fred = {}
        self._inst = {}

    # ── instruments ──────────────────────────────────────────────────
    def instrument(self, symbol):
        if symbol not in self._inst:
            try:
                from instruments.models import Instrument
                self._inst[symbol] = Instrument.objects.filter(
                    symbol=symbol).first()
            except Exception:  # noqa: BLE001
                self._inst[symbol] = None
        return self._inst[symbol]

    def asset_class(self, symbol) -> str:
        inst = self.instrument(symbol)
        return (getattr(inst, "asset_class", "") or "").lower()

    # ── closes ───────────────────────────────────────────────────────
    def series(self, symbol):
        """(days, closes, volumes), ascending, one bar per market day."""
        if symbol not in self._series:
            days, closes, vols = [], [], []
            try:
                from market_data.models import PriceData
                qs = PriceData.objects.filter(instrument__symbol=symbol,
                                              timeframe="1d")
                if self.upto is not None:
                    qs = qs.filter(timestamp__lt=datetime.combine(
                        self.upto + timedelta(days=2), time(0), tzinfo=UTC))
                by_day = {}
                for ts, close, vol in qs.order_by("timestamp").values_list(
                        "timestamp", "close", "volume"):
                    if close is None or float(close) <= 0:
                        continue
                    by_day[market_day(ts)] = (float(close), int(vol or 0))
                for d in sorted(by_day):
                    if self.upto is not None and d > self.upto:
                        continue
                    days.append(d)
                    closes.append(by_day[d][0])
                    vols.append(by_day[d][1])
            except Exception:  # noqa: BLE001
                days, closes, vols = [], [], []
            self._series[symbol] = (days, closes, vols)
        return self._series[symbol]

    def closes_upto(self, symbol, as_of: date):
        """(days, closes, volumes) ascending, every day <= as_of."""
        days, closes, vols = self.series(symbol)
        i = bisect.bisect_right(days, as_of)
        return days[:i], closes[:i], vols[:i]

    def close_on_or_before(self, symbol, d: date):
        days, closes, _ = self.series(symbol)
        i = bisect.bisect_right(days, d) - 1
        return (days[i], closes[i]) if i >= 0 else (None, None)

    def first_close_on_or_after(self, symbol, d: date):
        days, closes, _ = self.series(symbol)
        i = bisect.bisect_left(days, d)
        return (days[i], closes[i]) if i < len(days) else (None, None)

    # ── COT ──────────────────────────────────────────────────────────
    def cot_rows(self, symbol):
        """Ascending [(report_date, nc_long, nc_short, oi)]."""
        if symbol not in self._cot:
            rows = []
            try:
                from scraping.models import COTReport
                qs = COTReport.objects.filter(instrument__symbol=symbol)
                if self.upto is not None:
                    qs = qs.filter(report_date__lte=self.upto)
                rows = list(qs.order_by("report_date").values_list(
                    "report_date", "non_commercial_long",
                    "non_commercial_short", "open_interest"))
            except Exception:  # noqa: BLE001
                rows = []
            self._cot[symbol] = rows
        return self._cot[symbol]

    def cot_visible(self, symbol, as_of: date, replayed: bool,
                    read_time: datetime):
        """Ascending rows a read at `as_of` may see: live by report_date,
        replayed by publication time."""
        rows = self.cot_rows(symbol)
        if replayed:
            return [r for r in rows if cot_public_at(r[0]) <= read_time]
        return [r for r in rows if r[0] <= as_of]

    # ── FRED ─────────────────────────────────────────────────────────
    def fred_rows(self, series):
        """(ascending [(date, value)], units)."""
        if series not in self._fred:
            rows, units = [], None
            try:
                from market_data.models import MacroIndicator, MacroObservation
                ind = MacroIndicator.objects.filter(series_id=series).first()
                if ind is not None:
                    units = (ind.metadata or {}).get("units")
                    qs = MacroObservation.objects.filter(indicator=ind)
                    if self.upto is not None:
                        qs = qs.filter(date__lte=self.upto + timedelta(days=7))
                    rows = [(d, float(v)) for d, v in qs.order_by("date")
                            .values_list("date", "value")]
            except Exception:  # noqa: BLE001
                rows, units = [], None
            self._fred[series] = (rows, units)
        return self._fred[series]

    def fred_visible(self, series, as_of: date, replayed: bool,
                     read_time: datetime, cal=None):
        """Ascending [(date, value)] a read may see, and the units."""
        rows, units = self.fred_rows(series)
        if not replayed:
            return [r for r in rows if r[0] <= as_of], units
        cut = read_time.date()
        out = []
        for d, v in rows:
            if series in WEEKLY_SERIES:
                public = d + timedelta(days=2)
            elif cal is not None:
                public = cal.next_business_day(d)
            else:
                public = d + timedelta(days=1)
            if public <= cut:
                out.append((d, v))
        return out, units
