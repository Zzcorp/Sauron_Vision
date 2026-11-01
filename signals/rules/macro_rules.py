"""Macro signal rules: yield curve, DXY, FRED surprises."""
from django.utils import timezone


#: The commodities a curve un-inversion argues against (2026-10-31): the
#: energy complex and the industrial metals, the growth trades a recession
#: sells. Not the grains and softs (a recession is not their argument), and
#: never gold, silver or their crosses, which posture.classify reads as
#: risk_on_short when quoted in EUR or GBP.
YIELD_CURVE_COMMODITIES = frozenset({
    "WTIUSD", "BRNUSD", "OILFUTURES", "NGUSD", "HEATOILUSD", "GASOLINEUSD",
    "HGUSD", "ALUMUSD", "ZINCUSD", "NICKELUSD", "LEADUSD", "TINUSD"})
#: The currencies a forex SELL may buy on the flip: the yen and the franc.
#: The dollar is not one here — an un-inversion arrives with Fed easing,
#: which weakened it against the euro in 2007-08 and 2019-20 — unless the
#: currency sold is unranked (posture.CCY_RANK 0: AUD, NZD, ...), a risk
#: currency sold for a haven.
YIELD_CURVE_HAVEN_CCYS = frozenset({"JPY", "CHF"})
#: A previous observation no further than this before the newest common
#: date: an older one is a hole in the feed, not yesterday's curve.
YIELD_CURVE_GAP_DAYS = 7


class YieldCurveInversionRule:
    """THE 2s10s UN-INVERSION (fixed 2026-10-31): the spread crossing from
    under zero to zero or more, read on dates DGS10 and DGS2 have IN
    COMMON, only while the newest is fresh, and short only what the flip
    argues.

    What it was: the newest two DGS10 values against the newest two DGS2
    values, whatever their dates (one slope could mix two days); no
    freshness bound (a dead feed kept the last flip true, re-firing every
    instrument after each cooldown); a SHORT of every instrument scanned,
    gold, treasuries, the dollar index and the yen included; and no levels,
    so it was never graded.

    What it is:
      paired     slope_now on the newest common date d0, slope_prev on the
                 common date before it, d1 (at most YIELD_CURVE_GAP_DAYS
                 earlier); d0 within market_stress.MACRO_FRESH_DAYS of
                 today, else silence. Pairing can move a flip by one day.
      shorts     a SELL that posture.classify reads risk_on_short —
                 stocks, non-haven ETFs, indices, crypto, and of the
                 commodities only YIELD_CURVE_COMMODITIES — or a forex SELL
                 that buys the yen or the franc, or sells an unranked
                 currency (AUD, NZD, ...) for a ranked one. Never a haven
                 short (gold, silver, treasuries, the dollar index), nor
                 USDCAD, EURUSD or EURGBP. A RuleControl
                 `parameters["short_havens"] is True` lets haven shorts
                 through; nothing sets it.
      levels     the bot's own ATR levels on the instrument's closed 4h
                 bars after the bar sanity (technical_rules._sane, the
                 proving ground's own: an unadjusted split is no 1.5-ATR
                 stop), bearish_rules.short_levels; no bars, or a broken
                 series, no signal — an ungraded flip short is not stored.
      cooldown   720 h (rule_scope.DEFAULT_RULE_SCOPE): one flip, one short
                 per symbol. A RuleControl row whose scope names
                 cooldown_hours decides instead.
      record     graded now, and one flip shorts every instrument it argues
                 at once (some 127 of the catalogue): its record counts
                 FLIPS, not signals (promotion_pipeline.EVENT_KEYED_RULES,
                 by sub_scores.paired_on), so the ladder, the floor, the
                 proof's record and the rule weight never read one flip's
                 correlated shorts as LOSER_MIN_N observations.
    """
    name = "yield_curve_inversion_flip"
    signal_type = "macro"

    # The two legs of the 2s10s spread, as FRED spells them.
    TEN_YEAR = "DGS10"
    TWO_YEAR = "DGS2"

    def _last_values(self, series_id, n=5):
        """The n most recent observed values for a FRED series, newest first.

        Reads MacroObservation, NOT a `MacroSeries` model — there has never
        been one. The import of that name raised ImportError into a bare
        except that returned None, so this rule fired exactly zero times in
        the life of the codebase while looking perfectly healthy from the
        outside. There is no try/except here on purpose: if the query cannot
        run, SignalEngine.scan_instrument logs the rule by name at ERROR,
        which is how a broken macro rule is supposed to surface.
        """
        from market_data.models import MacroObservation
        return list(MacroObservation.objects
                    .filter(indicator__series_id=series_id)
                    .order_by("-date")
                    .values_list("value", flat=True)[:n])

    def _dated(self, series_id, n=30):
        from market_data.models import MacroObservation
        return dict(MacroObservation.objects
                    .filter(indicator__series_id=series_id)
                    .order_by("-date")
                    .values_list("date", "value")[:n])

    def _paired_slopes(self, today=None):
        """(d0, slope_now, d1, slope_prev) on the two newest dates both
        legs were published, or None: fewer than two common dates, d0 older
        than MACRO_FRESH_DAYS, or d1 more than YIELD_CURVE_GAP_DAYS before
        d0."""
        from bot_program.market_stress import MACRO_FRESH_DAYS
        today = today or timezone.now().date()
        ten = self._dated(self.TEN_YEAR)
        two = self._dated(self.TWO_YEAR)
        common = sorted(set(ten) & set(two), reverse=True)
        if len(common) < 2:
            return None
        d0, d1 = common[0], common[1]
        if (today - d0).days > MACRO_FRESH_DAYS:
            return None
        if (d0 - d1).days > YIELD_CURVE_GAP_DAYS:
            return None
        return (d0, float(ten[d0]) - float(two[d0]),
                d1, float(ten[d1]) - float(two[d1]))

    def argues(self, instrument, ctrl=None) -> bool:
        """Whether the flip argues for a SELL of this instrument."""
        from bot_program import posture
        symbol = str(getattr(instrument, "symbol", "") or "").upper()
        cls = str(getattr(instrument, "asset_class", "") or "")
        kind = posture.classify(symbol, cls, "SELL")
        params = getattr(ctrl, "parameters", None) or {}
        if kind == posture.HAVEN_SHORT:
            return params.get("short_havens") is True
        if kind == posture.RISK_ON_SHORT:
            if cls == "commodity":
                return symbol in YIELD_CURVE_COMMODITIES
            return not symbol.startswith(("XAU", "XAG"))
        if cls == "forex" and kind == posture.HAVEN and len(symbol) >= 6:
            base, quote = symbol[:3], symbol[3:6]      # a SELL buys the quote
            return (quote in YIELD_CURVE_HAVEN_CCYS
                    or posture.CCY_RANK.get(base, 0) == 0)
        return False

    def evaluate(self, instrument):
        """Detect 2s10s slope crossing zero, and short what it argues."""
        paired = self._paired_slopes()
        if paired is None:
            return None
        d0, slope_now, _d1, slope_prev = paired
        if not (slope_prev < 0 and slope_now >= 0):
            return None
        from signals.rule_actuator import _control_for
        if not self.argues(instrument, _control_for(self.name)):
            return None
        from backtester.proving.families import atr
        from signals.rules.bearish_rules import closed_frame, short_levels
        from signals.rules.technical_rules import _load_df, _sane
        symbol, df = _load_df(instrument, "4h", 60)
        df = _sane(closed_frame(df, "4h"), instrument)
        if df is None or len(df) < 15:
            return None
        entry = float(df["close"].iloc[-1])
        levels = short_levels(entry, atr(df, 14).iloc[-1],
                              getattr(instrument, "asset_class", ""))
        if levels is None:
            return None
        stop, target = levels
        return {
            "symbol": symbol,
            "rule": self.name,
            "direction": "SHORT",
            "score": 0.6,
            "headline": "MACRO · 2s10s yield curve un-inverted",
            "thesis": (
                f"2s10s flipped from {slope_prev:+.2f} to {slope_now:+.2f} "
                f"(paired on {d0:%Y-%m-%d}). Historically a recession-onset "
                f"signal: risk assets sold, havens bought."
            ),
            "sub_scores": {"slope_now": round(slope_now, 3),
                           "slope_prev": round(slope_prev, 3),
                           "paired_on": d0.isoformat()},
            "entry": entry,
            "stop": stop,
            "target": target,
        }


class DXYBreakoutRule:
    name = "dxy_breakout"
    signal_type = "macro"

    def evaluate(self, instrument):
        """DXY breaking 60-day high/low — signals USD strength regime change."""
        try:
            from signals.smc.dataframe import load_ohlcv
        except Exception:
            return None
        df = load_ohlcv("DXY", "1d", bars=80)
        if df is None or len(df) < 60:
            return None
        last = float(df["close"].iloc[-1])
        hi = float(df["high"].iloc[-60:-1].max())
        lo = float(df["low"].iloc[-60:-1].min())
        if last > hi:
            return {
                "symbol": "DXY",
                "rule": self.name,
                "direction": "LONG",
                "score": 0.55,
                "headline": "MACRO · DXY breaks 60d high",
                "thesis": "USD strength regime — historically bearish for risk assets.",
            }
        if last < lo:
            return {
                "symbol": "DXY",
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.55,
                "headline": "MACRO · DXY breaks 60d low",
                "thesis": "USD weakness regime — historically bullish for risk assets.",
            }
        return None


def get_rules():
    return [YieldCurveInversionRule(), DXYBreakoutRule()]
