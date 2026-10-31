"""Context columns for the bearish families (2026-10-31): what a bar may
know beyond its own prices, read only as it was PUBLISHED by that bar.

  vix_term        VIX / VIX3M (FRED VIXCLS / VXVCLS) on the newest date
                  common to both that is at or before the bar's New York
                  date minus VIX_LAG_DAYS, within market_stress's
                  MACRO_FRESH_DAYS of the bar's date; NaN otherwise. FRED
                  publishes a day's close the next morning, so a bar never
                  reads its own day. The bar's New York date is the date of
                  its OPEN timestamp (the index: PriceData stamps a bar's
                  open). No tz database, no column values.
  vix_term_date   the FRED date the ratio was read on, for the words.
  cot_spec_index  the speculators' COT index (smart_money.cot_index over
                  the newest COT_WINDOW_WEEKS reports, smart_money's own
                  computation through cot_spec_history), each report read
                  only by a bar that OPENS at or after its publication
                  (cot_released_at: bigmoney.inputs.cot_public_at, the
                  platform's one replay rule — report_date + 6 days at
                  21:00 UTC, after a Friday or a holiday-Monday release,
                  and the 2025 shutdown backlog from 2026-01-01). No
                  release date is stored, and the CFTC publishes late in
                  a holiday week and published the shutdown's reports
                  weeks late: a fixed four days read them before they
                  existed. COT_MIN_WEEKS needed and NaN past
                  COT_MAX_AGE_DAYS. Only a symbol with COT reports gets
                  the column.

`attach` is called by run.load_class after the bar sanity, and by the live
rules on their own frame, so the judge and the rule read the same value
at the same bar. A family that needs a column reads `df.get(col)` and
fires nothing without it. An unreadable context leaves its column out,
said at INFO: a missing context is no fire, never an invented one.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: A bar reads the ratio published the day before its New York date.
VIX_LAG_DAYS = 1


def cot_released_at(report_date):
    """When a bar may first read the COT report as of `report_date` (an
    aware UTC datetime): bigmoney.inputs.cot_public_at, the replay rule the
    Big Money board already reads by — report_date + 6 days at 21:00 UTC,
    never before a Friday or a holiday-Monday release (the CFTC moves a
    holiday week's release to the Monday), and the reports dated in the
    2025 shutdown backlog from 2026-01-01, once the CFTC had caught up.
    The live rule reads its reports by the same rule, so it fires where
    the replay fires."""
    from bigmoney.inputs import cot_public_at
    return cot_public_at(report_date)


def vix_table():
    """(dates, ratios): every date both VIXCLS and VXVCLS were published,
    ascending, as datetime64[D], and VIX / VIX3M on it. Empty arrays when
    either series is missing."""
    from bot_program.market_stress import VIX3M_SERIES, VIX_SERIES
    from market_data.models import MacroObservation
    vals = {}
    for series in (VIX_SERIES, VIX3M_SERIES):
        vals[series] = {d: float(v) for d, v in MacroObservation.objects
                        .filter(indicator__series_id=series)
                        .values_list("date", "value")}
    common = sorted(d for d in set(vals[VIX_SERIES]) & set(vals[VIX3M_SERIES])
                    if vals[VIX3M_SERIES][d] > 0)
    dates = np.array(common, dtype="datetime64[D]")
    ratios = np.array([vals[VIX_SERIES][d] / vals[VIX3M_SERIES][d]
                       for d in common], dtype=float)
    return dates, ratios


def _ny_dates(df):
    from signals.smc.sessions import new_york_index
    ny = new_york_index(df)
    if ny is None:
        return None
    return np.array(ny.date, dtype="datetime64[D]")


def vix_columns(df, table) -> tuple:
    """(ratio, date) arrays, one value per bar of `df`, from vix_table's
    `table`: NaN and NaT where nothing published is fresh."""
    from bot_program.market_stress import MACRO_FRESH_DAYS
    n = len(df)
    ratio = np.full(n, np.nan)
    when = np.full(n, np.datetime64("NaT"), dtype="datetime64[D]")
    dates, ratios = table
    bar_days = _ny_dates(df)
    if bar_days is None or not len(dates):
        return ratio, when
    ref = bar_days - np.timedelta64(VIX_LAG_DAYS, "D")
    i = np.searchsorted(dates, ref, side="right") - 1
    ok = i >= 0
    picked = dates[np.clip(i, 0, None)]
    age = (bar_days - picked).astype(int)
    ok &= age <= MACRO_FRESH_DAYS
    ratio[ok] = ratios[i[ok]]
    when[ok] = picked[ok]
    return ratio, when


def cot_column(df, history) -> np.ndarray:
    """The speculators' COT index at each bar of `df` from
    smart_money.cot_spec_history's `history` (oldest first), each report
    read only by a bar that opens at or after cot_released_at; NaN where
    cot_read would read none of the reports published by then."""
    from bot_program.smart_money import (COT_MIN_WEEKS, COT_WINDOW_WEEKS,
                                         cot_index)
    from signals.opportunity_scanner import COT_MAX_AGE_DAYS
    n = len(df)
    out = np.full(n, np.nan)
    if not history or not n:
        return out
    reports = np.array([d for d, _v in history], dtype="datetime64[D]")
    # ascending with the report dates (the backlog shares one instant), so
    # the reports a bar may read are the first k
    released = pd.DatetimeIndex([cot_released_at(d) for d, _v in history]
                                ).tz_convert("UTC").as_unit("ns")
    values = [v for _d, v in history]
    # the index once per count of released reports
    by_k = np.full(len(history) + 1, np.nan)
    for k in range(1, len(history) + 1):
        window = values[max(0, k - COT_WINDOW_WEEKS):k][::-1]
        if len(window) < COT_MIN_WEEKS or window[0] is None:
            continue
        idx = cot_index([v for v in window if v is not None])
        if idx is not None:
            by_k[k] = idx
    stamps = pd.DatetimeIndex(df.index)
    if stamps.tz is None:
        stamps = stamps.tz_localize("UTC")
    stamps = stamps.tz_convert("UTC").as_unit("ns")
    bar_days = np.array(stamps.date, dtype="datetime64[D]")
    k = np.searchsorted(released.asi8, stamps.asi8, side="right")
    newest = reports[np.clip(k - 1, 0, None)]
    age = (bar_days - newest).astype(int)
    ok = (k > 0) & (age <= COT_MAX_AGE_DAYS)
    out[ok] = by_k[k[ok]]
    return out


def attach(df, symbol, asset_class=None, *, cache=None):
    """`df` with the context columns its bars may read (module docstring),
    as a copy; `df` itself when it is empty. `cache` (a dict, one per run)
    holds the VIX table across symbols."""
    if df is None or len(df) == 0:
        return df
    df = df.copy()
    try:
        table = cache.get("vix") if isinstance(cache, dict) else None
        if table is None:
            table = vix_table()
            if isinstance(cache, dict):
                cache["vix"] = table
        if len(table[0]):
            df["vix_term"], df["vix_term_date"] = vix_columns(df, table)
    except Exception as e:  # noqa: BLE001 — no column is no fire
        logger.info("[context] %s: VIX term structure unread (%s)", symbol, e)
    try:
        from bot_program.smart_money import cot_spec_history
        history = cot_spec_history(symbol)
        if history:
            df["cot_spec_index"] = cot_column(df, history)
    except Exception as e:  # noqa: BLE001
        logger.info("[context] %s: COT history unread (%s)", symbol, e)
    return df


def vix_date_words(value) -> str:
    """A vix_term_date cell as YYYY-MM-DD, or ""."""
    try:
        if value is None or pd.isna(value):
            return ""
        return str(pd.Timestamp(value).date())
    except Exception:  # noqa: BLE001
        return ""

