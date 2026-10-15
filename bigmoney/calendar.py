"""Business days and the forced-flow calendar (spec §2.4, R2). No network.

BUSINESS DAYS. On or before the newest stored SPX500 daily bar, the tape is
the calendar: a date is a business day when SPX500 printed a close on it,
so a past holiday is known without a table (the NYSE table in
core/exchange_status.py covers 2026 and 2027 only, and the replay and the
36-month sigmas reach back to 2023). After the tape, weekdays minus
US_EQUITY_HOLIDAYS through 2027-12-31; past it, weekdays, said.

THE CALENDAR. Rows computed from rules (month-ends, the rebalancing, reversal
and fix windows, expiries, the COT release, the 13F deadline, the tax date)
plus a table of announced dates, each with its URL and the day it was
checked. Never written to EconomicEvent: real-money gates read that table
(bot_program/position_care.py, bot_program/news_risk.py).
"""
from __future__ import annotations

import bisect
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bigmoney import words as W
from bigmoney.rows import ROW_ORDER

NEW_YORK = ZoneInfo("America/New_York")
HOLIDAY_TABLE_END = date(2027, 12, 31)
TAPE_SYMBOL = "SPX500"
TAPE_GAP_DAYS = 4
REBALANCE_DAYS, REVERSAL_DAYS, FX_FIX_DAYS = 5, 5, 2
RUNWAY_DAYS = 30
#: A COT report is fresh 10 days from its Tuesday; 14 when the next release
#: is one the CFTC moved to a Monday (spec §2.4, R0).
COT_FRESH_DAYS, COT_FRESH_DAYS_DELAYED = 10, 14

#: Calendar-year corporations pay estimated income tax on the 15th of
#: April, June, September and December, the next business day when it is
#: not one (26 U.S.C. 6655(c)(2); IRS Form 1120-W instructions,
#: https://www.irs.gov/pub/irs-prior/i1120w--2022.pdf, seen 2026-10-15).
#: Mid-March is the S-corporation and partnership return date and moves
#: little cash; mid-April (corporate estimates and individual returns) is
#: the year's largest inflow to the Treasury's account, so the bank-reserve
#: drain is dated then.
CORPORATE_TAX_MONTHS = (4, 6, 9, 12)

ALL_ROWS = ROW_ORDER
COT_ROWS = ("us_equities", "us_dollar", "gold", "crude_oil", "crypto")

#: COT releases the CFTC moved to a Monday (https://www.cftc.gov/es/node/207246,
#: seen 2026-10-08): Veterans Day, Thanksgiving and Christmas weeks.
COT_DELAYED_RELEASES = frozenset({date(2026, 11, 16), date(2026, 11, 30),
                                  date(2026, 12, 28)})
COT_DELAYED_SOURCE = "https://www.cftc.gov/es/node/207246"

_RUSSELL = ("https://www.lseg.com/en/media-centre/press-releases/ftse-russell/"
            "2026/ftse-russell-announces-december-2026-russell-us-indexes-"
            "reconstitution-schedule")
_MSCI = "https://www.msci.com/eqb/pressreleases/archive/ir_dates.pdf"
_FOMC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_BLACKOUT = ("https://www.chicagofed.org/utilities/about-us/"
             "federal-reserve-calendars")

#: Announced dates: {date, event, rows, source_url, checked}. Adding next
#: year's is a code edit with its URLs (spec §2.4, the runway warning).
ANNOUNCED = (
    {"date": date(2026, 10, 16), "event": W.EV_TIC,
     "rows": ("treasuries", "us_dollar"),
     "source_url": "https://home.treasury.gov/system/files/136/"
                   "Press-notice-TIC-for-Jul-2026.pdf",
     "checked": "2026-10-08"},
    {"date": date(2026, 10, 17), "event": W.EV_FOMC_BLACKOUT, "rows": ALL_ROWS,
     "source_url": _BLACKOUT, "checked": "2026-10-09"},
    {"date": date(2026, 10, 28), "event": W.EV_FOMC, "rows": ALL_ROWS,
     "source_url": _FOMC, "checked": "2026-10-09"},
    {"date": date(2026, 10, 30), "event": W.EV_RUSSELL_RANK,
     "rows": ("us_equities",), "source_url": _RUSSELL, "checked": "2026-10-08"},
    {"date": date(2026, 11, 4), "event": W.EV_REFUNDING,
     "rows": ("treasuries",),
     "source_url": "https://home.treasury.gov/news/press-releases/sb0590",
     "checked": "2026-10-08"},
    {"date": date(2026, 11, 11), "event": W.EV_MSCI_ANNOUNCED,
     "rows": ("us_equities",), "source_url": _MSCI, "checked": "2026-10-08"},
    {"date": date(2026, 11, 13), "event": W.EV_RUSSELL_PRELIM,
     "rows": ("us_equities",), "source_url": _RUSSELL, "checked": "2026-10-08"},
    {"date": date(2026, 11, 28), "event": W.EV_FOMC_BLACKOUT, "rows": ALL_ROWS,
     "source_url": _BLACKOUT, "checked": "2026-10-09"},
    {"date": date(2026, 11, 30), "event": W.EV_RUSSELL_LOCKDOWN,
     "rows": ("us_equities",), "source_url": _RUSSELL, "checked": "2026-10-08"},
    {"date": date(2026, 11, 30), "event": W.EV_MSCI_EFFECTIVE,
     "rows": ("us_equities",), "source_url": _MSCI, "checked": "2026-10-08"},
    {"date": date(2026, 12, 9), "event": W.EV_FOMC, "rows": ALL_ROWS,
     "source_url": _FOMC, "checked": "2026-10-09"},
    {"date": date(2026, 12, 11), "event": W.EV_RUSSELL_RECON,
     "rows": ("us_equities",), "source_url": _RUSSELL, "checked": "2026-10-08"},
    {"date": date(2026, 12, 11), "event": W.EV_FUNDING_DEADLINE,
     "rows": ALL_ROWS,
     "source_url": "https://ffis.org/budget-brief/"
                   "house-approves-senate-cr-averts-shutdown/",
     "checked": "2026-10-08"},
) + tuple(
    {"date": d, "event": W.EV_COT_DELAYED, "rows": COT_ROWS,
     "source_url": COT_DELAYED_SOURCE, "checked": "2026-10-08"}
    for d in sorted(COT_DELAYED_RELEASES))

ANNOUNCED_END = max(a["date"] for a in ANNOUNCED)

#: Which events carry a direction (spec §2.4: the rebalance, its reversal,
#: the fix and the trend followers' trigger), which are forced flows (the
#: "forced flows within 2 business days" risk flag), and each one's play.
_INDEX_EVENTS = (W.EV_QUARTERLY_OPEX, W.EV_SP500_REBALANCE, W.EV_NDX_RECON,
                 W.EV_RUSSELL_RANK, W.EV_RUSSELL_PRELIM, W.EV_RUSSELL_LOCKDOWN,
                 W.EV_RUSSELL_RECON, W.EV_MSCI_ANNOUNCED, W.EV_MSCI_EFFECTIVE)
PLAYS = {W.EV_REBALANCE_OPENS: W.PLAY_REBALANCE,
         W.EV_REVERSAL_OPENS: W.PLAY_REBALANCE,
         W.EV_FX_FIX_OPENS: W.PLAY_FX_FIX,
         W.EV_FOMC: W.PLAY_EVENT_RISK, W.EV_REFUNDING: W.PLAY_EVENT_RISK,
         W.EV_FINANCING: W.PLAY_EVENT_RISK,
         W.EV_FUNDING_DEADLINE: W.PLAY_EVENT_RISK,
         **{e: W.PLAY_INDEX for e in _INDEX_EVENTS}}
DIRECTIONAL = frozenset({W.EV_REBALANCE_OPENS, W.EV_REVERSAL_OPENS,
                         W.EV_FX_FIX_OPENS})
FORCED = frozenset({W.EV_MONTH_END, W.EV_QUARTER_END, W.EV_REBALANCE_OPENS,
                    W.EV_REVERSAL_OPENS, W.EV_FX_FIX_OPENS, W.EV_OPEX,
                    W.EV_VIX_EXPIRY, W.EV_TAX_DATE, *_INDEX_EVENTS})


class BusinessCalendar:
    """US business days: the tape first, the NYSE table after it, weekdays
    past the table (each fallback said in `reasons`)."""

    def __init__(self, tape_dates=()):
        self.tape = sorted(set(tape_dates))
        self._tape_set = frozenset(self.tape)
        self.tape_first = self.tape[0] if self.tape else None
        self.tape_last = self.tape[-1] if self.tape else None
        self.reasons = set()

    @classmethod
    def from_db(cls, upto=None):
        """The calendar over SPX500's stored daily bars (one query)."""
        from bigmoney.inputs import market_day
        try:
            from market_data.models import PriceData
            qs = PriceData.objects.filter(instrument__symbol=TAPE_SYMBOL,
                                          timeframe="1d")
            stamps = qs.values_list("timestamp", flat=True)
            days = {market_day(t) for t in stamps}
            if upto is not None:
                days = {d for d in days if d <= upto}
            return cls(days)
        except Exception:  # noqa: BLE001
            return cls(())

    def is_business_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        if self.tape_last is not None and self.tape_first <= d <= self.tape_last:
            return d in self._tape_set
        if d > HOLIDAY_TABLE_END:
            self.reasons.add(W.R_HOLIDAYS_END)
            return True
        from core.exchange_status import US_EQUITY_HOLIDAYS
        return d not in US_EQUITY_HOLIDAYS

    def next_business_day(self, d: date) -> date:
        d = d + timedelta(days=1)
        if self.tape_last is not None and self.tape_first <= d <= self.tape_last:
            i = bisect.bisect_left(self.tape, d)
            if i < len(self.tape):
                return self.tape[i]
            d = self.tape_last + timedelta(days=1)
        while not self.is_business_day(d):
            d += timedelta(days=1)
        return d

    def prev_business_day(self, d: date) -> date:
        d = d - timedelta(days=1)
        if self.tape_last is not None and self.tape_first <= d <= self.tape_last:
            i = bisect.bisect_right(self.tape, d) - 1
            if i >= 0:
                return self.tape[i]
        for _ in range(4000):
            if self.is_business_day(d):
                return d
            d -= timedelta(days=1)
        return d

    def add_business_days(self, d: date, n: int) -> date:
        for _ in range(max(0, int(n))):
            d = self.next_business_day(d)
        return d

    def business_days_between(self, a: date, b: date) -> int:
        """Business days in (a, b]."""
        if b <= a:
            return 0
        n, d = 0, a
        while True:
            d = self.next_business_day(d)
            if d > b:
                return n
            n += 1

    def month_days(self, year: int, month: int) -> list:
        first = date(year, month, 1)
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        out, d = [], first
        while d < nxt:
            if self.is_business_day(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def last_business_day(self, year: int, month: int):
        days = self.month_days(year, month)
        return days[-1] if days else None

    def window(self, year: int, month: int, kind: str) -> list:
        """The business days of a window in this month: "rebalance" (the
        last 5), "reversal" (the first 5) or "fx_fix" (the last 2)."""
        days = self.month_days(year, month)
        if kind == "rebalance":
            return days[-REBALANCE_DAYS:]
        if kind == "reversal":
            return days[:REVERSAL_DAYS]
        if kind == "fx_fix":
            return days[-FX_FIX_DAYS:]
        raise ValueError(kind)

    def in_window(self, d: date, kind: str) -> bool:
        return d in self.window(d.year, d.month, kind)

    def gaps(self, since: date | None = None) -> list:
        """[(last close before the gap, first close after it, days)] where
        the stored tape skips more than TAPE_GAP_DAYS calendar days."""
        out = []
        tape = [d for d in self.tape if since is None or d >= since]
        for a, b in zip(tape, tape[1:]):
            if (b - a).days > TAPE_GAP_DAYS:
                out.append((a, b, (b - a).days))
        return out


def as_of_for(now_utc: datetime, cal: BusinessCalendar) -> date:
    """The last US business day whose 16:00 New York close has passed."""
    ny = now_utc.astimezone(NEW_YORK)
    d = ny.date()
    if cal.is_business_day(d) and ny.time() >= time(16, 0):
        return d
    return cal.prev_business_day(d)


def third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def _on_or_before(d: date, cal: BusinessCalendar) -> date:
    return d if cal.is_business_day(d) else cal.prev_business_day(d)


def _on_or_after(d: date, cal: BusinessCalendar) -> date:
    return d if cal.is_business_day(d) else cal.next_business_day(d)


def monthly_expiry(year: int, month: int, cal: BusinessCalendar) -> date:
    """The third Friday, or the business day before it on a holiday."""
    return _on_or_before(third_friday(year, month), cal)


def vix_expiry(year: int, month: int, cal: BusinessCalendar) -> date:
    """The Wednesday 30 days before the next month's third Friday."""
    ny, nm = year + (month == 12), month % 12 + 1
    return _on_or_before(third_friday(ny, nm) - timedelta(days=30), cal)


def thirteen_f_deadline(quarter_end: date, cal: BusinessCalendar) -> date:
    return _on_or_after(quarter_end + timedelta(days=45), cal)


def financing_estimates(refunding: date) -> date:
    """The Monday before the refunding statement."""
    back = refunding.weekday() or 7
    return refunding - timedelta(days=back)


def cot_release(tuesday: date) -> date:
    """The release of a report dated `tuesday`: the Friday after, or the
    Monday the CFTC moved it to."""
    friday = tuesday + timedelta(days=3)
    monday = friday + timedelta(days=3)
    return monday if monday in COT_DELAYED_RELEASES else friday


def cot_bound(report_date: date) -> int:
    """10 days from report_date; 14 when the next release is one the CFTC
    moved to a Monday (spec §2.4, R0)."""
    nxt = report_date + timedelta(days=7)
    return (COT_FRESH_DAYS_DELAYED if cot_release(nxt) in COT_DELAYED_RELEASES
            else COT_FRESH_DAYS)


def _months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = y + (m == 12), m % 12 + 1


def _ev(d, event, rows, kind, *, source_url="", checked="", market=None):
    return {"date": d.isoformat(), "event": event, "rows": list(rows),
            "kind": kind, "source_url": source_url, "checked": checked,
            "play": PLAYS.get(event, W.PLAY_TREND if market else ""),
            "directional": event in DIRECTIONAL or bool(market),
            "forced": event in FORCED or bool(market)}


def events(start: date, days: int, cal: BusinessCalendar, *,
           triggers=()) -> tuple:
    """([event dicts] dated start..start+days, [reasons]). `triggers` are
    the trend followers' estimates: [(date, row key, market title)]."""
    end = start + timedelta(days=days)
    out = []
    # From two and a half months back: a quarter's 13F deadline lands 45
    # days after it; everything is filtered to the window below.
    for y, m in _months(start - timedelta(days=75), end + timedelta(days=31)):
        mdays = cal.month_days(y, m)
        if not mdays:
            continue
        last = mdays[-1]
        out.append(_ev(last, W.EV_MONTH_END, ALL_ROWS, "computed"))
        if m in (3, 6, 9, 12):
            out.append(_ev(last, W.EV_QUARTER_END, ALL_ROWS, "computed"))
        out.append(_ev(mdays[-REBALANCE_DAYS], W.EV_REBALANCE_OPENS,
                       ("us_equities", "treasuries"), "computed"))
        out.append(_ev(mdays[0], W.EV_REVERSAL_OPENS,
                       ("us_equities", "treasuries"), "computed"))
        out.append(_ev(mdays[-FX_FIX_DAYS], W.EV_FX_FIX_OPENS,
                       ("us_dollar",), "computed"))
        exp = monthly_expiry(y, m, cal)
        if m in (3, 6, 9, 12):
            out.append(_ev(exp, W.EV_QUARTERLY_OPEX, ("us_equities",),
                           "computed"))
            out.append(_ev(exp, W.EV_SP500_REBALANCE, ("us_equities",),
                           "computed"))
            if m == 12:
                out.append(_ev(exp, W.EV_NDX_RECON, ("us_equities",),
                               "computed"))
        else:
            out.append(_ev(exp, W.EV_OPEX, ("us_equities",), "computed"))
        out.append(_ev(vix_expiry(y, m, cal), W.EV_VIX_EXPIRY,
                       ("us_equities",), "computed"))
        if m in (3, 6, 9, 12):
            qe = date(y, m, 1) + timedelta(days=31)
            qe = qe.replace(day=1) - timedelta(days=1)
            out.append(_ev(thirteen_f_deadline(qe, cal), W.EV_13F,
                           ("us_equities",), "computed"))
        if m in CORPORATE_TAX_MONTHS:
            out.append(_ev(_on_or_after(date(y, m, 15), cal), W.EV_TAX_DATE,
                           ("treasuries", "us_dollar"), "computed"))
        # Every COT Friday; a delayed one is the announced Monday below.
        d = date(y, m, 1)
        while d.month == m:
            if d.weekday() == 4 and cot_release(d - timedelta(days=3)) == d:
                out.append(_ev(d, W.EV_COT, COT_ROWS, "computed"))
            d += timedelta(days=1)
    for a in ANNOUNCED:
        out.append(_ev(a["date"], a["event"], a["rows"], "announced",
                       source_url=a["source_url"], checked=a["checked"]))
        if a["event"] == W.EV_REFUNDING:
            out.append(_ev(financing_estimates(a["date"]), W.EV_FINANCING,
                           ("treasuries",), "computed"))
    for d, row, title in triggers:
        out.append(_ev(d, W.EV_TREND_TRIGGER.format(market=title), (row,),
                       "estimate", market=title))
    out = [e for e in out if start.isoformat() <= e["date"] <= end.isoformat()]
    seen, uniq = set(), []
    for e in sorted(out, key=lambda e: (e["date"], e["event"])):
        key = (e["date"], e["event"])
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    reasons = []
    if (ANNOUNCED_END - start).days <= RUNWAY_DAYS:
        reasons.append(W.R_CALENDAR_RUNWAY.format(date=ANNOUNCED_END.isoformat()))
    return uniq, reasons
