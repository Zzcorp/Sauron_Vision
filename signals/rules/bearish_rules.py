"""Bearish-by-definition signal rules (2026-10-31) — born at research.

The operator asked, 2026-10-31, for strategies that are bearish by
definition. The book had been long by construction: the three
long rules had no short side and every starter setup was bullish. These
eight rules are SHORT only, each a pattern that is bearish by its own
definition:

  bull_trap_swing_high         a close above a swing high and back under it
  po3_london_sweep_short       London runs the Asian high, New York closes
                               back under it (1h bars)
  range_breakdown_short        a tight range's low broken, with follow-through
  trend_continuation_short     a rally to the EMA20 rejected under the last
                               swing high, in a downtrend
  risk_off_exhaustion_short    a rejection wick on a relief rally under the
                               SMA200, while the Mind reads risk-off or the
                               market is stressed (risk assets only)
  vix_inversion_index_short    the index under its 10-bar low with VIX/VIX3M
                               at 1 or more (indices and US index ETFs)
  crowded_long_reversal_short  the speculators at the top of their COT range
                               and the top's swing low broken (markets a
                               COT report maps)
  positioning_crowd_reversal_short
                               the same break under a crowd leaning long,
                               read from funding or sentiment (markets no
                               COT report maps; no family replays it)

THE MONEY RULE. Every name is in signals/rule_birth.BORN_AT_RESEARCH: with
no RuleControl row it reads research (stage_policy), decide() leaves it out
of the vote, and its first stored signal writes the row at research. It is
stored, graded (entry, stop and target are always emitted) and judged by
the proving ground nightly per class under its own name — all but
positioning_crowd_reversal_short, whose crowd score no history replays,
so size by proof reads it as unjudged; it trades only once the existing
ladder has promoted it on proof.

ONE DETECTOR. Each pattern lives once, in backtester/proving/families.py;
the rule calls it on its own CLOSED bars (closed_frame: PriceData stamps a
bar's open, and a family fires on the close of bar t) after the bar sanity
(technical_rules._sane, the judge's own data.sanitize), and reads the last
bar. So the rule fires where the family fires, and the verdict and the
graded record measure the same fires.

THE LEVELS are the bot's own (risk_levels): stop 1.5 ATR(14) above the
entry, the fraction clamped to the class's stop band, target 3 ATR below —
2R, the trade the proving ground simulates. The score is 0.60 + 0.15 q, q
in [0, 1] per rule: 0.60 is entry_score_min, so a promoted rule votes,
and 0.75 stays under the high urgencies.
"""
import logging
import math
import time

from signals.rules.technical_rules import (BaseRule, _load_df, _sane,
                                           closed_frame)

logger = logging.getLogger(__name__)

#: The US index ETFs the VIX inversion rule shorts beside the indices.
INDEX_ETFS = frozenset({"SPY", "QQQ", "IWM", "DIA", "VOO", "IVV", "VTI"})
#: The score at q = 0 and its span to q = 1.
SCORE_FLOOR = 0.60
SCORE_SPAN = 0.15
#: The Mind's risk_off counts from this confidence (market_stress reads
#: the Mind's label from the same bar).
REGIME_MIN_CONFIDENCE = 0.65
#: The regime gate is read once per scan pass (a SignalEngine rebuilds its
#: rules each pass) and for this long at most.
GATE_TTL_SECONDS = 60.0


def _symbol(instrument):
    return getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)


def _num(x, nd=6):
    """A finite float rounded, or None (sub_scores are JSON: no NaN)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def short_levels(entry, atr, asset_class):
    """(stop, target) of a short entered at `entry`: the bot's own ATR
    levels (risk_levels.DEFAULT_ATR_STOP_MULT, DEFAULT_ATR_TARGET_MULT),
    the stop fraction clamped to stop_band(asset_class), the target at the
    same reward:risk. None without a finite positive entry and ATR."""
    from bot_program.asset_engine.risk_levels import (
        DEFAULT_ATR_STOP_MULT, DEFAULT_ATR_TARGET_MULT, stop_band)
    try:
        entry, atr = float(entry), float(atr)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(entry) and math.isfinite(atr) and entry > 0
            and atr > 0):
        return None
    lo, hi = stop_band(asset_class or "")
    frac = min(max(DEFAULT_ATR_STOP_MULT * atr / entry, lo), hi)
    risk = frac * entry
    ratio = DEFAULT_ATR_TARGET_MULT / DEFAULT_ATR_STOP_MULT
    return entry + risk, entry - ratio * risk


def _px(x) -> str:
    return f"{float(x):.5g}"


class _BearishRule(BaseRule):
    """The shared spine: the closed, sane frame; the family's detector at
    its defaults on it; the levels and the score."""
    #: the family in backtester.proving.families that IS this rule
    family = ""
    timeframe = "4h"
    bars = 300
    min_bars = 60

    def _fam(self):
        from backtester.proving.families import FAMILIES
        return FAMILIES[self.family]

    def eligible(self, instrument) -> bool:
        return self._fam().is_eligible(_symbol(instrument),
                                       getattr(instrument, "asset_class", ""))

    def frame(self, instrument, now=None):
        """(symbol, the closed, sane frame) or (symbol, None)."""
        symbol, df = _load_df(instrument, self.timeframe, self.bars)
        if df is None or len(df) == 0:
            return symbol, None
        df = closed_frame(df, self.timeframe, now)
        df = _sane(df, instrument)
        if df is None or len(df) < self.min_bars:
            return symbol, None
        return symbol, df

    def detect(self, df):
        """(fires on the last bar, {detail key: value at the last bar})."""
        from backtester.proving.families import SHORT
        fam = self._fam()
        fires, info = fam.fn(df, SHORT, **fam.defaults, detail=True)
        if not len(fires) or not bool(fires[-1]):
            return False, {}
        return True, {k: v[-1] for k, v in info.items()}

    def card(self, symbol, instrument, df, *, quality, headline, thesis,
             sub_scores):
        from backtester.proving.families import atr
        entry = float(df["close"].iloc[-1])
        levels = short_levels(entry, atr(df, 14).iloc[-1],
                              getattr(instrument, "asset_class", ""))
        if levels is None:
            return None
        stop, target = levels
        q = min(1.0, max(0.0, float(quality))) if quality == quality else 0.0
        subs = {k: v for k, v in sub_scores.items() if v is not None}
        subs["quality"] = round(q, 3)
        return {
            "symbol": symbol,
            "rule": self.name,
            "direction": "SHORT",
            "score": round(SCORE_FLOOR + SCORE_SPAN * q, 3),
            "sub_scores": subs,
            "headline": headline,
            "thesis": thesis,
            "entry": entry,
            "stop": stop,
            "target": target,
        }


class BullTrapSwingHighRule(_BearishRule):
    """The failed breakout at a swing high (families.bull_trap): a close
    above the most recent swing high and, within three bars, the first
    close back under it. Not the generated `fakeout_pattern` setups (the
    max of 20 bars as the level, a wick as the break): the clean version,
    on a fractal swing and an accepted close."""
    name = "bull_trap_swing_high"
    family = "bull_trap"

    def evaluate(self, instrument):
        symbol, df = self.frame(instrument)
        if df is None:
            return None
        fired, d = self.detect(df)
        if not fired:
            return None
        from backtester.proving.families import atr
        a = float(atr(df, 14).iloc[-1])
        level, x = float(d["level"]), float(d["invalidation"])
        n = int(d["bars_above"])
        close = float(df["close"].iloc[-1])
        return self.card(
            symbol, instrument, df, quality=d["quality"],
            headline=f"{symbol} SHORT · Bull trap at the swing high",
            thesis=(f"Closed above the swing high {_px(level)} ({n} bar"
                    f"{'s' if n != 1 else ''} ago) and back under it: a "
                    f"failed breakout, the buyers above are trapped. "
                    f"Invalid above {_px(x)}."),
            sub_scores={"level": _num(level), "extreme": _num(x),
                        "bars_above": n,
                        "depth_atr": _num((level - close) / a, 3)
                        if a > 0 else None})


class PO3LondonSweepShortRule(_BearishRule):
    """London sweeps the Asian high, New York distributes lower
    (families.po3_london), on 1h bars: the run in London, the close back
    under the Asian high by 10:00 New York. The levels are the 1h ATR's —
    the trade the 1h proving run simulates — and so, once promoted, are
    the bot's: its entry reads the ATR of the bars the family pins
    (risk_levels.rule_atr_timeframe: 1h), whatever the config's
    atr_timeframe, so the verdict that sizes the trade simulated it."""
    name = "po3_london_sweep_short"
    family = "po3_london"
    timeframe = "1h"
    bars = 360
    min_bars = 48

    def evaluate(self, instrument):
        if not self.eligible(instrument):
            return None
        symbol, df = self.frame(instrument)
        if df is None:
            return None
        fired, d = self.detect(df)
        if not fired:
            return None
        ah, al, x = (float(d[k]) for k in ("asian_high", "asian_low",
                                            "invalidation"))
        return self.card(
            symbol, instrument, df, quality=d["quality"],
            headline=f"{symbol} SHORT · London swept the Asian high",
            thesis=(f"London ran the Asian high ({_px(ah)}) to {_px(x)} and "
                    f"New York is back under it: the manipulation is done, "
                    f"the distribution points down."),
            sub_scores={"asian_high": _num(ah), "asian_low": _num(al),
                        "extreme": _num(x)})


class RangeBreakdownShortRule(_BearishRule):
    """The low of a tight range broken, with follow-through
    (families.range_breakdown). Unlike the Donchian short: a tight range,
    a first break of 0.25 ATR or more, a lower close and low after it, one
    fire per range."""
    name = "range_breakdown_short"
    family = "range_breakdown"

    def evaluate(self, instrument):
        symbol, df = self.frame(instrument)
        if df is None:
            return None
        fired, d = self.detect(df)
        if not fired:
            return None
        n = int(self._fam().defaults["n"])
        rl, rh, x = (float(d[k]) for k in ("range_low", "range_high",
                                            "invalidation"))
        return self.card(
            symbol, instrument, df, quality=d["quality"],
            headline=f"{symbol} SHORT · Range breakdown",
            thesis=(f"Broke the low of a {n}-bar range ({_px(rl)}) and "
                    f"followed through lower: sellers in control. Invalid "
                    f"above {_px(x)}."),
            sub_scores={"range_low": _num(rl), "range_high": _num(rh),
                        "extreme": _num(x)})


class TrendContinuationShortRule(_BearishRule):
    """The downtrend's continuation (families.trend_rally): EMA20 < EMA50 <
    SMA200, a red bar that reached the EMA20 and closed under it, the
    rally's high under the last swing high — a lower high. 600 bars: the
    EMAs' seed weighs nothing there, and the slow line is a simple mean."""
    name = "trend_continuation_short"
    family = "trend_rally"
    bars = 600
    min_bars = 201

    def evaluate(self, instrument):
        symbol, df = self.frame(instrument)
        if df is None:
            return None
        fired, d = self.detect(df)
        if not fired:
            return None
        p1, x = float(d["swing_high"]), float(d["invalidation"])
        return self.card(
            symbol, instrument, df, quality=d["quality"],
            headline=f"{symbol} SHORT · Trend continuation",
            thesis=(f"Downtrend (EMA20 < EMA50 < SMA200): the rally to the "
                    f"EMA20 was rejected under the last swing high "
                    f"{_px(p1)}, a lower high. Invalid above {_px(x)}."),
            sub_scores={"swing_high": _num(p1), "extreme": _num(x)})


def regime_gate() -> dict:
    """{open, why, regime, regime_confidence, stress}: open when the Mind
    reads risk_off at REGIME_MIN_CONFIDENCE or more, or the market stress
    reading is fresh at stressed or crisis; closed otherwise, an unreadable
    read included."""
    out = {"open": False, "why": "", "regime": "", "regime_confidence": None,
           "stress": ""}
    try:
        from brain.context import get_brain_context
        ctx = get_brain_context() or {}
        label = str(ctx.get("regime_label") or "")
        conf = float(ctx.get("regime_confidence") or 0.0)
        out["regime"], out["regime_confidence"] = label, round(conf, 2)
        if label == "risk_off" and conf >= REGIME_MIN_CONFIDENCE:
            out["open"] = True
            out["why"] = f"the Mind: risk_off at {conf * 100:.0f}%"
    except Exception as e:  # noqa: BLE001
        logger.debug("[bearish] the Mind unread: %s", e)
    try:
        from bot_program import market_stress
        cur = market_stress.current() or {}
        level = str(cur.get("level") or "")
        out["stress"] = level
        if not out["open"] and cur.get("fresh") and level in (
                market_stress.STRESSED, market_stress.CRISIS):
            out["open"] = True
            sc = cur.get("score")
            out["why"] = (f"the stress level: {level}"
                          + (f", score {float(sc):.0f}" if sc is not None
                             else ""))
    except Exception as e:  # noqa: BLE001
        logger.debug("[bearish] stress unread: %s", e)
    return out


class RiskOffExhaustionShortRule(_BearishRule):
    """The exhaustion short in a risk-off regime (families.exhaustion_short
    plus a regime gate): risk assets only (posture.classify SELL is
    risk_on_short — never gold, silver, treasuries, the dollar index nor
    forex). The proving ground judges the bar pattern on those markets; the
    gate is live only, so every live fire is a subset of the judged
    fires."""
    name = "risk_off_exhaustion_short"
    family = "exhaustion_short"

    def __init__(self):
        self._gate = None
        self._gate_at = 0.0

    def gate(self) -> dict:
        now = time.monotonic()
        if self._gate is None or now - self._gate_at > GATE_TTL_SECONDS:
            self._gate = regime_gate()
            self._gate_at = now
        return self._gate

    def evaluate(self, instrument):
        if not self.eligible(instrument):
            return None
        gate = self.gate()
        if not gate.get("open"):
            return None
        symbol, df = self.frame(instrument)
        if df is None:
            return None
        fired, d = self.detect(df)
        if not fired:
            return None
        rally = float(d["rally_atr"])
        return self.card(
            symbol, instrument, df, quality=d["quality"],
            headline=f"{symbol} SHORT · Risk-off exhaustion",
            thesis=(f"Risk-off ({gate['why']}): a {rally:.1f}-ATR relief "
                    f"rally under the SMA200 printed a rejection wick. "
                    f"Rallies are sold here. The regime gate is not in the "
                    f"proving ground's replay."),
            sub_scores={"regime": gate.get("regime") or None,
                        "regime_confidence": gate.get("regime_confidence"),
                        "stress": gate.get("stress") or None,
                        "wick_share": _num(d["wick_share"], 3),
                        "rally_atr": _num(rally, 2)})


class VixInversionIndexShortRule(_BearishRule):
    """The index risk-off short when the VIX term structure inverts
    (families.vix_term_breakdown): VIX/VIX3M at 1.00 or more as published
    the day before the bar, and the first close under the 10-bar low.
    Indices and the US index ETFs (INDEX_ETFS) only. The published
    evidence on VIX/VIX3M at 1 or more reads contrarian (index returns
    after it are often positive): watched at research, a FAILED verdict
    would be no surprise."""
    name = "vix_inversion_index_short"
    family = "vix_term_breakdown"
    min_bars = 30

    def evaluate(self, instrument):
        if not self.eligible(instrument):
            return None
        symbol, df = self.frame(instrument)
        if df is None:
            return None
        from backtester.proving import context
        df = context.attach(df, symbol, getattr(instrument, "asset_class", ""))
        fired, d = self.detect(df)
        if not fired:
            return None
        ratio = float(d["vix_term"])
        on = context.vix_date_words(df["vix_term_date"].iloc[-1]) \
            if "vix_term_date" in df.columns else ""
        return self.card(
            symbol, instrument, df, quality=d["quality"],
            headline=f"{symbol} SHORT · VIX curve inverted, index breakdown",
            thesis=(f"VIX/VIX3M at {ratio:.2f} (the term structure "
                    f"inverted{', as of ' + on if on else ''}) and the index "
                    f"closed under its 10-bar low."),
            sub_scores={"vix_term": _num(ratio, 3),
                        "vix_term_date": on or None})


class CrowdedLongReversalShortRule(_BearishRule):
    """The contrarian short at an extreme crowded long, with a price
    trigger (families.crowded_long): the speculators' COT index at 90 or
    more (each report read from its publication, context.cot_released_at)
    and the first close under the swing low after the top. Only on a
    market a COT report maps (the family's own eligibility, cot_market):
    the trade the proving ground replays and judges per class under this
    name. A market no COT report maps is positioning_crowd_reversal_short's.
    Gold is allowed: a crowded long in gold is this rule's argument."""
    name = "crowded_long_reversal_short"
    family = "crowded_long"
    min_bars = 70

    def evaluate(self, instrument):
        if not self.eligible(instrument):
            return None
        symbol, df = self.frame(instrument)
        if df is None:
            return None
        from backtester.proving import context
        from bot_program.smart_money import cot_spec_history
        history = cot_spec_history(symbol)
        if not history:
            return None
        df = df.copy()
        df["cot_spec_index"] = context.cot_column(df, history)
        fired, d = self.detect(df)
        if not fired:
            return None
        import numpy as np
        import pandas as pd

        spec = float(d["spec_index"])
        bar_open = pd.Timestamp(df.index[-1])
        bar_open = (bar_open.tz_localize("UTC") if bar_open.tz is None
                    else bar_open.tz_convert("UTC"))
        # the report the column read: the newest published by the bar's open
        released = [r for r, _v in history
                    if context.cot_released_at(r) <= bar_open.to_pydatetime()]
        report = released[-1].isoformat() if released else ""
        return self.card(
            symbol, instrument, df, quality=d["quality"],
            headline=f"{symbol} SHORT · Crowded long breaking",
            thesis=(f"Speculators crowded long (COT index {spec:.0f}"
                    f"{', report ' + report if report else ''}) and the price "
                    f"broke the swing low after the top: the crowd is the "
                    f"fuel."),
            sub_scores={"gate": "cot", "spec_index": _num(spec, 1),
                        "report_date": report or None,
                        "extreme": _num(d["invalidation"])
                        if np.isfinite(d["invalidation"]) else None})


class PositioningCrowdReversalShortRule(_BearishRule):
    """The crowded long's price trigger (families.crowded_long_trigger at
    the crowded_long family's defaults) on a market no COT report maps,
    gated by the positioning map's crowd score at CROWDED or more, read
    from funding, sentiment or COT (never from the bars' volume alone).

    ITS OWN NAME (2026-11-01). No history replays a crowd score, so no
    family judges this gate: under crowded_long_reversal_short its fires
    on ETHUSD, DAX40 or GBPJPY would have been sized by the class verdict
    the COT gate earned on BTCUSD, SPX500 and the COT currency pairs.
    Under its own name size by proof reads it as unjudged, and the ladder
    grades it on its own record. Born at research (signals/rule_birth)."""
    name = "positioning_crowd_reversal_short"
    min_bars = 70
    #: crowd_read components that read positioning (not the bars' volume)
    CROWD_COMPONENTS = ("cot_speculators", "funding", "sentiment")

    def evaluate(self, instrument):
        from backtester.proving.families import (FAMILIES, cot_market,
                                                 crowded_long_trigger)
        fam = FAMILIES["crowded_long"]
        try:
            mapped = cot_market(_symbol(instrument),
                                getattr(instrument, "asset_class", ""))
        except Exception:  # noqa: BLE001 — unread may be the COT gate's
            return None
        if mapped:
            return None
        symbol, df = self.frame(instrument)
        if df is None:
            return None
        p = {k: v for k, v in fam.defaults.items()
             if k in ("left", "right", "top", "near")}
        fires, trig = crowded_long_trigger(df, **p)
        if not len(fires) or not bool(fires[-1]):
            return None
        from bot_program.positioning import CROWDED, crowd_read
        read = crowd_read(symbol, getattr(instrument, "asset_class", ""))
        comps = read.get("components") or {}
        if not any((comps.get(k) or {}).get("score") is not None
                   for k in self.CROWD_COMPONENTS):
            return None
        score = read.get("score")
        if score is None or float(score) < CROWDED:
            return None
        score = float(score)
        words = "; ".join(str((comps.get(k) or {}).get("words") or "")
                          for k in self.CROWD_COMPONENTS
                          if (comps.get(k) or {}).get("score") is not None)
        return self.card(
            symbol, instrument, df, quality=(score - CROWDED) / (1 - CROWDED),
            headline=f"{symbol} SHORT · Crowded positioning breaking",
            thesis=(f"The crowd leans long (positioning {score:+.2f}: "
                    f"{words}) and the price broke the swing low after the "
                    f"top: the crowd is the fuel. No history replays the "
                    f"crowd score: the proving ground does not judge it."),
            sub_scores={"gate": "crowd", "crowd_score": _num(score, 2),
                        "extreme": _num(trig["invalidation"][-1])})


def get_rules():
    """The eight bearish-by-definition rules, each born at research
    (signals/rule_birth)."""
    return [
        BullTrapSwingHighRule(),
        PO3LondonSweepShortRule(),
        RangeBreakdownShortRule(),
        TrendContinuationShortRule(),
        RiskOffExhaustionShortRule(),
        VixInversionIndexShortRule(),
        CrowdedLongReversalShortRule(),
        PositioningCrowdReversalShortRule(),
    ]
