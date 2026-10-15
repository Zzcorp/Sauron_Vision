"""One function per footprint (spec §2.5).

A cell is {state: read|unread|out_of_season, score, grade, role, weight,
prior, words, why, from, data_as_of, public_at, age_days, claim,
horizon_days, proxy, ...}. A footprint that cannot be read is `unread` with
its reason (a dash, never a zero); an exception inside a cell is "unreadable:
{ExceptionName}". The season is judged before any data is touched, so an
out-of-season footprint is never a dash.

THE SEASON is judged on the day the claim covers: the next business day
after `as_of`. The read is made after the as-of close and claims the next
close, so the Friday read before a window that opens on Monday is in season,
and the read made after the month's last close (the pressure is spent) is
not: it belongs to the reversal.
"""
from __future__ import annotations

import bisect
import math
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_tz

from bigmoney import calendar as bmcal
from bigmoney import words as W
from bigmoney.calendar import COT_FRESH_DAYS, COT_FRESH_DAYS_DELAYED  # noqa: F401
from bigmoney.inputs import FRED_BOUNDS, UNITS_TO_MILLIONS, fred_key_set
from bigmoney.rows import (CRYPTO_SYMBOLS, FIX_CCY, FIX_INDEX_NAMES,
                           FX_FIX_PAIRS, ROWS, BOND_LEG)
# The smart money's own COT window and floor (bot_program/smart_money.py),
# reused so the board and cot_read never disagree on what "thin" is. The
# import runs one way: nothing under bot_program imports bigmoney.
from bot_program.smart_money import COT_MIN_WEEKS, COT_WINDOW_WEEKS

UTC = dt_tz.utc

GRADE = ("ROBUST", "CONDITIONAL", "FRAGILE")
LEAN_AT = 0.33
COVERAGE_MIN = 0.5
ACTIVE_AT = 0.2
SIGMA_MONTHS, MIN_MONTHS = 36, 24
REBALANCE_DAYS, REVERSAL_DAYS, FX_FIX_DAYS = 5, 5, 2
REBALANCE_DEAD_ZONE = 0.66
COT_CHANGE_DEAD_ZONE = 1.0
CROWD_FLAGS = (90, 80, 20, 10)
LOSING_AT = 1.5
CTA_LOOKBACKS = (21, 63, 252)
CTA_NEAR = 1.0
VRP_DAYS, VRP_HISTORY_DAYS, VRP_MIN_DAYS = 21, 756, 252
FLOW_DAYS, FLOW_BASE_DAYS = 5, 60
TIDE_WEEKS, TIDE_SIGMA_WEEKS, TIDE_MIN_WEEKS = 4, 156, 52
SIGMA_D_DAYS = 20
CLOSE_BOUND_DAYS, CLOSE_BOUND_CRYPTO = 4, 2

#: footprint -> (role, grade, claim, horizon_days); the prior weight is per
#: market (PRIORS). Weights are fixed priors in code: the record can only
#: lower a lean weight to zero (score.effective_weights), never raise it.
FOOTPRINTS = {
    "rebalance": ("lean", "ROBUST", "direction", 1),
    "rebalance_reversal": ("lean", "CONDITIONAL", "direction", 5),
    "fx_fix": ("lean", "ROBUST", "direction", 1),
    "cot_change": ("lean", "CONDITIONAL", "direction", 10),
    "crowding": ("risk", "ROBUST", "tail", 20),
    "crowd_losing": ("risk", "CONDITIONAL", "direction", 5),
    "cta": ("current", "CONDITIONAL", "direction", 20),
    "vrp": ("current", "ROBUST", "direction", 60),
    "flows": ("context", "FRAGILE", "direction", 5),
    "opex": ("context", "CONDITIONAL", "direction", 5),
    "tide": ("current", "FRAGILE", "direction", 20),
    "stress": ("risk", "ROBUST", None, None),
    "calendar": ("risk", "ROBUST", None, None),
}
LEAN_FOOTPRINTS = ("rebalance", "rebalance_reversal", "fx_fix", "cot_change")
#: Where the speculators' weekly change counts in the lean (commodities,
#: Kang, Rouwenhorst & Tang 2020); everywhere else it is context, FRAGILE.
COT_LEAN_ROWS = ("gold", "crude_oil")


def prior(footprint: str, market: str, *, commodity=False) -> float:
    if footprint == "rebalance":
        return 1.0 if market == "us_equities" else 0.5
    if footprint == "rebalance_reversal":
        return 0.5 if market == "us_equities" else 0.25
    if footprint == "fx_fix":
        return 0.5
    if footprint == "cot_change":
        return 0.5 if (market in COT_LEAN_ROWS or commodity) else 0.0
    return 0.0


class Unread(Exception):
    """A footprint that cannot be read, with the reason (and its remedy)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ── maths ────────────────────────────────────────────────────────────────

def clip(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


def sign(x: float) -> int:
    return (x > 0) - (x < 0)


def sd(xs) -> float | None:
    xs = [float(x) for x in xs]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(v) if v > 0 else None


def log_returns(closes) -> list:
    return [math.log(b / a) for a, b in zip(closes, closes[1:])
            if a > 0 and b > 0]


def sigma_d(closes) -> float | None:
    """The standard deviation of the last 20 daily log returns."""
    return sd(log_returns(closes[-(SIGMA_D_DAYS + 1):]))


def month_ends(days, closes) -> dict:
    """{(year, month): last close of that month}."""
    out = {}
    for d, c in zip(days, closes):
        out[(d.year, d.month)] = c
    return out


def prev_month(ym):
    y, m = ym
    return (y - 1, 12) if m == 1 else (y, m - 1)


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def cot_index(values_newest_first):
    """The smart money's COT index (bot_program/smart_money.py cot_index)."""
    from bot_program.smart_money import cot_index as _ci
    return _ci(values_newest_first)


def fmt_level(x: float) -> str:
    x = float(x)
    if abs(x) >= 100:
        return f"{x:,.1f}"
    if abs(x) >= 10:
        return f"{x:,.2f}"
    return f"{x:.4f}"


# ── the read's context ───────────────────────────────────────────────────

class Ctx:
    """What every cell reads through: the store, the calendar, the as-of
    day, the run, live or replayed, and the sources log for the page."""

    def __init__(self, store, cal, as_of: date, *, run="morning",
                 replayed=False, read_time: datetime | None = None,
                 now: datetime | None = None, weights=None):
        self.store = store
        self.cal = cal
        self.as_of = as_of
        self.run = run
        self.replayed = replayed
        self.read_time = read_time or datetime.combine(
            as_of + timedelta(days=1), time(5, 20), tzinfo=UTC)
        self.now = now or self.read_time
        self.weights = weights or {}
        self.sources = {}
        self._memo = {}

    # memo of shared computations (an Unread is remembered too)
    def memo(self, key, fn):
        if key not in self._memo:
            try:
                self._memo[key] = (True, fn())
            except Unread as u:
                self._memo[key] = (False, u)
        ok, val = self._memo[key]
        if not ok:
            raise Unread(val.reason)
        return val

    def weight(self, footprint, market, prior_w):
        got = self.weights.get((footprint, market))
        if got is None:
            return prior_w, False
        w, zeroed = got
        return min(prior_w, w), zeroed

    def is_crypto(self, symbol) -> bool:
        return symbol in CRYPTO_SYMBOLS or self.store.asset_class(symbol) == "crypto"

    def _source(self, name, newest, bound, state):
        """One row of the Sources panel. Every record of an input is made
        against the read's own as-of day (`_tape` for closes; COT is
        memoized; a FRED series reads the same rows every time), so the
        last record is the input's state and replaces any earlier one: a
        dead series is never shown as fresh."""
        age = (self.as_of - newest).days if newest else None
        self.sources[name] = {"input": name,
                              "newest": newest.isoformat() if newest else "",
                              "age": age, "bound": bound, "state": state}

    def _tape(self, symbol) -> dict:
        """The symbol's closes as of the read day, judged once and recorded
        in the Sources panel: {days, closes, vols, bound, crypto, reason}.
        `reason` is None for a fresh tape, else the Unread reason. A read at
        a past date (the reversal reads last month's last close) says
        nothing about today's tape, so it is judged here, never by that
        read."""
        key = ("tape", symbol)
        if key in self._memo:
            return self._memo[key][1]
        days, closes, vols = self.store.closes_upto(symbol, self.as_of)
        crypto = self.is_crypto(symbol)
        if crypto and self.run == "evening" and days and days[-1] >= self.as_of:
            # The as-of crypto bar closes at 00:00 UTC, after this read:
            # the evening reads the last complete one; the morning fills it.
            days, closes, vols = days[:-1], closes[:-1], vols[:-1]
        bound = CLOSE_BOUND_CRYPTO if crypto else CLOSE_BOUND_DAYS
        reason = None
        if not days:
            self._source(symbol, None, bound, "missing")
            reason = ""                      # worded by the caller (its need)
        else:
            last = days[-1]
            age = (self.as_of - last).days
            if self.run == "evening" and not crypto and last < self.as_of:
                # Every market but crypto has closed by 23:20 UTC: a close
                # not stored for the as-of day is said, never yesterday's
                # read as today's (gold, oil, the pairs and the foreign
                # indices as much as the US session).
                reason = W.R_NO_CLOSE_YET.format(symbol=symbol,
                                                 date=self.as_of.isoformat())
            elif age > bound:
                reason = (W.R_CLOSE_STALE_CRYPTO if crypto
                          else W.R_CLOSE_STALE).format(symbol=symbol, n=age,
                                                       b=bound)
            self._source(symbol, last, bound,
                         "fresh" if reason is None else "stale")
        out = {"days": days, "closes": closes, "vols": vols, "bound": bound,
               "crypto": crypto, "reason": reason}
        self._memo[key] = (True, out)
        return out

    def prices(self, symbol, need=0, *, at: date | None = None):
        """(days, closes, volumes) ascending through `at` (as_of by
        default), or Unread with the reason and its remedy."""
        at = at or self.as_of
        tape = self._tape(symbol)
        if at == self.as_of:
            days, closes, vols = tape["days"], tape["closes"], tape["vols"]
            if tape["reason"] == "":
                raise Unread(W.R_CLOSES_THIN.format(symbol=symbol, n=0,
                                                    m=max(need, 1)))
            if tape["reason"]:
                raise Unread(tape["reason"])
        else:
            # A read at a past date: its own close must be fresh at `at`.
            days, closes, vols = self.store.closes_upto(symbol, at)
            if not days:
                raise Unread(W.R_CLOSES_THIN.format(symbol=symbol, n=0,
                                                    m=max(need, 1)))
            age = (at - days[-1]).days
            if age > tape["bound"]:
                raise Unread((W.R_CLOSE_STALE_CRYPTO if tape["crypto"]
                              else W.R_CLOSE_STALE).format(
                    symbol=symbol, n=age, b=tape["bound"]))
        if len(days) < need:
            raise Unread(W.R_CLOSES_THIN.format(symbol=symbol, n=len(days),
                                                m=need))
        return days, closes, vols

    def cot(self, symbol) -> dict:
        """The COT reports a read may see, in the symbol's own frame."""
        def _read():
            rows = self.store.cot_visible(symbol, self.as_of, self.replayed,
                                          self.read_time)
            name = f"COT {symbol}"
            if not rows:
                self._source(name, None, COT_FRESH_DAYS, "missing")
                raise Unread(W.R_COT_NONE.format(symbol=symbol))
            rdate = rows[-1][0]
            bound = bmcal.cot_bound(rdate)
            age = (self.as_of - rdate).days
            if age > bound:
                self._source(name, rdate, bound, "stale")
                raise Unread(W.R_COT_STALE.format(n=age, b=bound))
            self._source(name, rdate, bound, "fresh")
            if len(rows) < COT_MIN_WEEKS:
                raise Unread(W.R_COT_THIN.format(n=len(rows)))
            if not rows[-1][3]:
                raise Unread(W.R_COT_NO_OI.format(day=W.day(rdate),
                                                  symbol=symbol))
            from signals.opportunity_scanner import cot_sign
            inst = self.store.instrument(symbol)
            sgn = cot_sign(inst) if inst is not None else 1
            window = rows[-(COT_WINDOW_WEEKS + 1):]
            x = [(r[0], sgn * (r[1] - r[2]) / r[3]) for r in window if r[3]]
            return {"report_date": rdate, "x": x, "bound": bound, "age": age,
                    "public_at": datetime.combine(
                        bmcal.cot_release(rdate), time(20, 30), tzinfo=UTC)}
        return self.memo(("cot", symbol), _read)

    def fred(self, series, need=0) -> tuple:
        """(ascending [(date, value)], units), or Unread."""
        rows, units = self.store.fred_visible(series, self.as_of,
                                              self.replayed, self.read_time,
                                              self.cal)
        bound = FRED_BOUNDS.get(series, 5)
        no_key = (not self.replayed) and not fred_key_set()
        if not rows:
            self._source(series, None, bound, "no key" if no_key else "missing")
            raise Unread(W.R_NO_KEY.format(series=series) if no_key
                         else W.R_FRED_NONE.format(series=series))
        newest = rows[-1][0]
        age = (self.as_of - newest).days
        if age > bound:
            self._source(series, newest, bound, "no key" if no_key else "stale")
            raise Unread(W.R_NO_KEY.format(series=series) if no_key
                         else W.R_FRED_STALE.format(series=series, n=age,
                                                    b=bound))
        self._source(series, newest, bound, "fresh")
        if len(rows) < need:
            raise Unread(W.R_FRED_THIN.format(series=series, n=len(rows),
                                              m=need))
        return rows, units

    def target_day(self, symbol=None) -> date:
        """The day the claim covers: the next business day (the next
        calendar day for crypto)."""
        if symbol and self.is_crypto(symbol):
            return self.as_of + timedelta(days=1)
        return self.cal.next_business_day(self.as_of)


# ── cells ────────────────────────────────────────────────────────────────

def make(footprint, market, ctx, state, *, score=None, words="", why="",
         from_words="", data_as_of=None, public_at=None, proxy=None,
         horizon_days=None, commodity=False, **extra) -> dict:
    role, grade, claim, h = FOOTPRINTS[footprint]
    p = prior(footprint, market, commodity=commodity)
    w, zeroed = ctx.weight(footprint, market, p)
    if role == "lean" and footprint == "cot_change" and p == 0.0:
        role, grade = "context", "FRAGILE"
    cell = {"footprint": footprint, "state": state,
            "score": None if score is None else round(float(score), 4),
            "grade": grade, "role": role, "weight": w, "prior": p,
            "zeroed": bool(zeroed) and p > 0,
            "words": words, "why": why, "from": from_words,
            "data_as_of": data_as_of.isoformat() if data_as_of else None,
            "public_at": public_at.isoformat() if public_at else None,
            "age_days": (ctx.as_of - data_as_of).days if data_as_of else None,
            "claim": claim, "horizon_days": horizon_days or h,
            "proxy": proxy}
    if cell["zeroed"]:
        cell["why"] = (cell["why"] + " " + W.ZEROED).strip()
    cell.update(extra)
    return cell


def guarded(footprint, market, ctx, fn, *, proxy=None, commodity=False):
    """Run one cell: Unread -> a dash with its reason; any other exception ->
    "unreadable: {ExceptionName}". Never raises."""
    try:
        return fn()
    except Unread as u:
        return make(footprint, market, ctx, "unread", why=u.reason,
                    proxy=proxy, commodity=commodity)
    except Exception as e:  # noqa: BLE001
        return make(footprint, market, ctx, "unread",
                    why=W.R_UNREADABLE.format(name=type(e).__name__),
                    proxy=proxy, commodity=commodity)


def _close_public(d: date) -> datetime:
    return datetime.combine(d, time(21, 0), tzinfo=UTC)


def _next_window_start(ctx, target, kind):
    days = ctx.cal.window(target.year, target.month, kind)
    if days and days[0] >= target:
        return days[0]
    y, m = target.year + (target.month == 12), target.month % 12 + 1
    days = ctx.cal.window(y, m, kind)
    return days[0] if days else None


# 1. month-end rebalancing (Harvey, Mazzoleni & Melone, NBER w33554)

def _months_needed() -> int:
    return 21 * (MIN_MONTHS + 2)


def rebalance_z(ctx, at: date) -> dict:
    """The 60/40 drift at `at` and its z against the last 36 complete
    month-ends: {z, drift, w, sigma, n, leg, leg_reason, data_as_of}."""
    def _compute():
        eq_days, eq_c, _ = ctx.prices("SPX500", at=at)
        legs, leg_reason = [], ""
        for sym in BOND_LEG:
            try:
                bd_days, bd_c, _ = ctx.prices(sym, at=at)
                legs.append((sym, bd_days, bd_c))
            except Unread as u:
                leg_reason = leg_reason or u.reason
        me_eq = month_ends(eq_days, eq_c)
        cur = (at.year, at.month)
        pm = prev_month(cur)

        def drifts(me_bd):
            out = []
            keys = sorted(k for k in me_eq if k < cur)
            for k in keys:
                p = prev_month(k)
                if p not in me_eq:
                    continue
                r_eq = me_eq[k] / me_eq[p] - 1.0
                if me_bd is None:
                    r_bd = 0.0
                elif k in me_bd and p in me_bd:
                    r_bd = me_bd[k] / me_bd[p] - 1.0
                else:
                    continue
                out.append(_drift(r_eq, r_bd))
            return out[-SIGMA_MONTHS:]

        chosen = None
        for sym, bd_days, bd_c in legs:
            me_bd = month_ends(bd_days, bd_c)
            hist = drifts(me_bd)
            if pm in me_bd and len(hist) >= MIN_MONTHS:
                chosen = (sym, me_bd, hist, bd_c[-1])
                break
            leg_reason = leg_reason or W.R_CLOSES_THIN.format(
                symbol=sym, n=len(bd_days), m=_months_needed())
        if pm not in me_eq:
            raise Unread(W.R_CLOSES_THIN.format(symbol="SPX500", n=len(eq_days),
                                                m=_months_needed()))
        r_eq = eq_c[-1] / me_eq[pm] - 1.0
        if chosen is not None:
            sym, me_bd, hist, last_bd = chosen
            r_bd = last_bd / me_bd[pm] - 1.0
        else:
            sym, hist, r_bd = None, drifts(None), 0.0
        if len(hist) < MIN_MONTHS:
            raise Unread(W.R_CLOSES_THIN.format(symbol="SPX500", n=len(eq_days),
                                                m=_months_needed()))
        sigma = sd(hist)
        if not sigma:
            raise Unread(W.R_CLOSES_THIN.format(symbol="SPX500", n=len(eq_days),
                                                m=_months_needed()))
        drift = _drift(r_eq, r_bd)
        w = 0.6 * (1 + r_eq) / (0.6 * (1 + r_eq) + 0.4 * (1 + r_bd))
        return {"z": drift / sigma, "drift": drift, "w": w, "sigma": sigma,
                "n": len(hist), "leg": sym, "leg_reason": leg_reason,
                "data_as_of": eq_days[-1]}
    return ctx.memo(("rebalance_z", at), _compute)


def _drift(r_eq, r_bd) -> float:
    a, b = 0.6 * (1 + r_eq), 0.4 * (1 + r_bd)
    return a / (a + b) - 0.6


def _leg_suffix(r) -> str:
    if r["leg"] == "TLT":
        return W.REBALANCE_TLT
    if r["leg"] is None:
        return W.REBALANCE_ONE_LEG
    return ""


def rebalance_cell(ctx, market) -> dict:
    proxy = ROWS[market]["graded_on"]

    def _cell():
        target = ctx.target_day()
        if not ctx.cal.in_window(target, "rebalance"):
            opens = _next_window_start(ctx, target, "rebalance")
            return make("rebalance", market, ctx, "out_of_season",
                        words=W.REBALANCE_SEASON.format(
                            day=W.day(opens) if opens else "?"), proxy=proxy)
        r = rebalance_z(ctx, ctx.as_of)
        if market == "treasuries" and r["leg"] is None:
            raise Unread(r["leg_reason"] or W.REBALANCE_ONE_LEG.strip())
        z = r["z"]
        s = 0.0 if abs(z) < REBALANCE_DEAD_ZONE else clip(z / 2)
        s = -s if market == "us_equities" else s
        zw, ww = W.z(z), f"{r['w'] * 100:.1f}"
        if abs(z) < REBALANCE_DEAD_ZONE:
            text = W.REBALANCE_SMALL.format(z=zw)
        elif z > 0:
            text = W.REBALANCE_UP.format(z=zw, w=ww)
        else:
            text = W.REBALANCE_DOWN.format(z=zw, w=ww)
        return make("rebalance", market, ctx, "read", score=s,
                    words=text + _leg_suffix(r), from_words=W.REBALANCE_FROM,
                    data_as_of=r["data_as_of"],
                    public_at=_close_public(r["data_as_of"]), proxy=proxy,
                    z=round(z, 3), leg=r["leg"])
    return guarded("rebalance", market, ctx, _cell, proxy=proxy)


def reversal_cell(ctx, market) -> dict:
    proxy = ROWS[market]["graded_on"]

    def _cell():
        target = ctx.target_day()
        if not ctx.cal.in_window(target, "reversal"):
            return make("rebalance_reversal", market, ctx, "out_of_season",
                        words=W.REVERSAL_SEASON, proxy=proxy)
        prev_last = ctx.cal.prev_business_day(date(target.year, target.month, 1))
        r = rebalance_z(ctx, prev_last)
        if market == "treasuries" and r["leg"] is None:
            raise Unread(r["leg_reason"] or W.REBALANCE_ONE_LEG.strip())
        z = r["z"]
        s = 0.5 * clip(z / 2)
        s = s if market == "us_equities" else -s
        return make("rebalance_reversal", market, ctx, "read", score=s,
                    words=W.REVERSAL_WORDS.format(z=W.z(z)) + _leg_suffix(r),
                    from_words=W.REVERSAL_FROM, data_as_of=r["data_as_of"],
                    public_at=_close_public(r["data_as_of"]), proxy=proxy,
                    z=round(z, 3), leg=r["leg"])
    return guarded("rebalance_reversal", market, ctx, _cell, proxy=proxy)


# 2. month-end hedging at the London 4 pm fix (Melvin & Prins 2015)

def fix_pair(ctx, pair) -> dict:
    """{z, foreign, usd, pair_score, data_as_of} for one fix pair."""
    def _compute():
        index = FX_FIX_PAIRS[pair]
        sp_days, sp_c, _ = ctx.prices("SPX500")
        ix_days, ix_c, _ = ctx.prices(index)
        cur = (ctx.as_of.year, ctx.as_of.month)
        pm = prev_month(cur)
        me_sp, me_ix = month_ends(sp_days, sp_c), month_ends(ix_days, ix_c)
        hist = []
        for k in sorted(k for k in me_sp if k < cur):
            p = prev_month(k)
            if all(x in me for x in (k, p) for me in (me_sp, me_ix)):
                hist.append(math.log(me_ix[k] / me_ix[p])
                            - math.log(me_sp[k] / me_sp[p]))
        hist = hist[-SIGMA_MONTHS:]
        if pm not in me_sp or pm not in me_ix or len(hist) < MIN_MONTHS:
            thin = index if len(ix_days) <= len(sp_days) else "SPX500"
            raise Unread(W.R_CLOSES_THIN.format(
                symbol=thin, n=min(len(ix_days), len(sp_days)),
                m=_months_needed()))
        sigma = sd(hist)
        if not sigma:
            raise Unread(W.R_CLOSES_THIN.format(symbol=index, n=len(ix_days),
                                                m=_months_needed()))
        e = math.log(ix_c[-1] / me_ix[pm]) - math.log(sp_c[-1] / me_sp[pm])
        z = e / sigma
        foreign, usd = -clip(z / 2), clip(z / 2)
        pair_score = foreign if pair.endswith("USD") else usd
        return {"z": z, "foreign": foreign, "usd": usd,
                "pair_score": pair_score,
                "data_as_of": min(sp_days[-1], ix_days[-1])}
    return ctx.memo(("fix_pair", pair), _compute)


def _fix_in_season(ctx):
    target = ctx.target_day()
    if ctx.cal.in_window(target, "fx_fix"):
        return True, None
    return False, _next_window_start(ctx, target, "fx_fix")


def fx_fix_pair_cell(ctx, pair) -> dict:
    def _cell():
        ok, opens = _fix_in_season(ctx)
        if not ok:
            return make("fx_fix", pair, ctx, "out_of_season", proxy=pair,
                        words=W.FX_FIX_SEASON.format(
                            day=W.day(opens) if opens else "?"))
        r = fix_pair(ctx, pair)
        index = FX_FIX_PAIRS[pair]
        tmpl = W.FX_FIX_PAIR_UP if r["z"] > 0 else W.FX_FIX_PAIR_DOWN
        return make("fx_fix", pair, ctx, "read", score=r["pair_score"],
                    words=tmpl.format(index=FIX_INDEX_NAMES[index],
                                      z=W.z(r["z"]), ccy=FIX_CCY[pair]),
                    from_words=W.FX_FIX_FROM, data_as_of=r["data_as_of"],
                    public_at=_close_public(r["data_as_of"]), proxy=pair,
                    z=round(r["z"], 3), foreign=round(r["foreign"], 4),
                    ccy=FIX_CCY[pair])
    return guarded("fx_fix", pair, ctx, _cell, proxy=pair)


def fx_fix_row_cell(ctx) -> dict:
    market, proxy = "us_dollar", ROWS["us_dollar"]["graded_on"]

    def _cell():
        ok, opens = _fix_in_season(ctx)
        if not ok:
            return make("fx_fix", market, ctx, "out_of_season", proxy=proxy,
                        words=W.FX_FIX_SEASON.format(
                            day=W.day(opens) if opens else "?"))
        sides, reasons, newest = [], [], None
        for pair in FX_FIX_PAIRS:
            try:
                r = fix_pair(ctx, pair)
                sides.append(r["usd"])
                newest = max(newest, r["data_as_of"]) if newest else r["data_as_of"]
            except Unread as u:
                reasons.append(u.reason)
        if len(sides) < 2:
            raise Unread(W.R_FIX_PAIRS.format(reasons="; ".join(reasons)))
        s = sum(sides) / len(sides)
        verb = "up" if s >= ACTIVE_AT else "down" if s <= -ACTIVE_AT else "flat"
        return make("fx_fix", market, ctx, "read", score=s,
                    words=W.FX_FIX_ROW.format(n=len(sides),
                                              verb=W.FX_FIX_VERBS[verb]),
                    from_words=W.FX_FIX_FROM, data_as_of=newest,
                    public_at=_close_public(newest), proxy=proxy,
                    pairs=len(sides))
    return guarded("fx_fix", market, ctx, _cell, proxy=proxy)


# 3. the speculators' weekly change, faded (Kang, Rouwenhorst & Tang 2020)

def cot_change_cell(ctx, market, symbol, *, proxy, title,
                    commodity=False) -> dict:
    lean = market in COT_LEAN_ROWS or commodity

    def _cell():
        c = ctx.cot(symbol)
        xs = [v for _d, v in c["x"]]
        deltas = [b - a for a, b in zip(xs, xs[1:])]
        sigma = sd(deltas[-COT_WINDOW_WEEKS:])
        if not sigma:
            raise Unread(W.R_COT_THIN.format(n=len(xs)))
        z = deltas[-1] / sigma
        s = -clip(z / 2) if abs(z) >= COT_CHANGE_DEAD_ZONE else 0.0
        zw, dw = W.z(z), W.day(c["report_date"])
        if z >= COT_CHANGE_DEAD_ZONE:
            text = W.COT_BOUGHT.format(z=zw, day=dw)
        elif z <= -COT_CHANGE_DEAD_ZONE:
            text = W.COT_SOLD.format(z=zw, day=dw)
        else:
            text = W.COT_ORDINARY.format(z=zw)
        if not lean:
            text += W.COT_CONTEXT.format(market=title)
        return make("cot_change", market, ctx, "read", score=s, words=text,
                    from_words=W.COT_FROM if lean else "",
                    data_as_of=c["report_date"], public_at=c["public_at"],
                    proxy=proxy, commodity=commodity, z=round(z, 3))
    return guarded("cot_change", market, ctx, _cell, proxy=proxy,
                   commodity=commodity)


# 4. crowding, a fatter left tail (Brunnermeier, Nagel & Pedersen)

def crowd(ctx, symbol) -> dict:
    def _compute():
        c = ctx.cot(symbol)
        newest_first = [v for _d, v in reversed(c["x"][-COT_WINDOW_WEEKS:])]
        idx = cot_index(newest_first)
        if idx is None:
            raise Unread(W.R_COT_THIN.format(n=len(newest_first)))
        hi_x, hi_h, lo_h, lo_x = CROWD_FLAGS
        side = degree = None
        if idx >= hi_x:
            side, degree = "long", "crowded"
        elif idx >= hi_h:
            side, degree = "long", "heavy"
        elif idx <= lo_x:
            side, degree = "short", "crowded"
        elif idx <= lo_h:
            side, degree = "short", "heavy"
        return {"idx": idx, "side": side, "degree": degree,
                "report_date": c["report_date"], "public_at": c["public_at"]}
    return ctx.memo(("crowd", symbol), _compute)


def crowding_cell(ctx, market, symbol, *, proxy) -> dict:
    def _cell():
        k = crowd(ctx, symbol)
        idx, dw = k["idx"], W.day(k["report_date"])
        if k["degree"] == "crowded":
            text = W.CROWDING_CROWDED.format(side=k["side"], idx=f"{idx:g}",
                                             day=dw)
        elif k["degree"] == "heavy":
            text = W.CROWDING_HEAVY.format(side=k["side"], idx=f"{idx:g}",
                                           day=dw)
        else:
            text = W.CROWDING_NORMAL.format(idx=f"{idx:g}")
        flag = (f"{k['degree']} {k['side']}" if k["degree"] else "")
        return make("crowding", market, ctx, "read", score=(idx - 50) / 50.0,
                    words=text, data_as_of=k["report_date"],
                    public_at=k["public_at"], proxy=proxy, idx=idx,
                    flag=flag, side=k["side"], degree=k["degree"])
    return guarded("crowding", market, ctx, _cell, proxy=proxy)


def crowd_losing_cell(ctx, market, symbol, *, proxy) -> dict:
    def _cell():
        k = crowd(ctx, symbol)
        if not k["degree"]:
            return make("crowd_losing", market, ctx, "out_of_season",
                        words=W.CROWD_NONE, proxy=proxy)
        days, closes, _ = ctx.prices(proxy, need=SIGMA_D_DAYS + 2)
        rd, c_report = ctx.store.close_on_or_before(proxy, k["report_date"])
        if c_report is None:
            raise Unread(W.R_CLOSES_THIN.format(symbol=proxy, n=len(days),
                                                m=SIGMA_D_DAYS + 2))
        sig = sigma_d(closes)
        n = ((days[-1] - k["report_date"]).days if ctx.is_crypto(proxy)
             else ctx.cal.business_days_between(k["report_date"], days[-1]))
        if not sig or n < 1:
            return make("crowd_losing", market, ctx, "out_of_season",
                        words=W.CROWD_NOT_LOSING, proxy=proxy)
        S = 1 if k["side"] == "long" else -1
        m = math.log(closes[-1] / c_report) / (sig * math.sqrt(n))
        against = -S * m
        if against < LOSING_AT:
            return make("crowd_losing", market, ctx, "out_of_season",
                        words=W.CROWD_NOT_LOSING, proxy=proxy,
                        against=round(against, 3))
        return make("crowd_losing", market, ctx, "read", score=float(-S),
                    words=W.CROWD_LOSING.format(degree=k["degree"],
                                                side=k["side"],
                                                z=W.z(against),
                                                day=W.day(k["report_date"])),
                    data_as_of=days[-1], public_at=_close_public(days[-1]),
                    proxy=proxy, against=round(against, 3))
    return guarded("crowd_losing", market, ctx, _cell, proxy=proxy)


# 5. the trend followers' own rule, replicated from prices

def cta_cell(ctx, market, symbol, *, title) -> dict:
    def _cell():
        need = max(CTA_LOOKBACKS) + 1
        days, c, _ = ctx.prices(symbol, need=need)
        t = len(c) - 1
        signs = {L: sign(math.log(c[t] / c[t - L])) for L in CTA_LOOKBACKS}
        s = sum(signs.values()) / len(CTA_LOOKBACKS)
        sig = sigma_d(c)
        nearest = None
        for L in CTA_LOOKBACKS:
            level = c[t + 1 - L]
            k = abs(c[t] - level) / (sig * c[t]) if sig else None
            if k is None:
                continue
            if nearest is None or k < nearest["k"]:
                above = c[t] > level
                nearest = {"L": L, "level": level, "k": k,
                           "beyond": "below" if above else "above",
                           "turn": "short" if above else "long"}
        n_long = sum(1 for v in signs.values() if v > 0)
        n_short = sum(1 for v in signs.values() if v < 0)
        side = "long" if s > 0 else "short" if s < 0 else "split"
        n = n_long if side in ("long", "split") else n_short
        text = W.CTA_WORDS.format(side=side, n=n)
        short = W.CTA_SHORT.format(side=side, n=n)
        trigger = None
        if nearest is not None:
            trig = W.CTA_TRIGGER.format(beyond=nearest["beyond"],
                                        level=fmt_level(nearest["level"]),
                                        horizon=W.CTA_HORIZONS[nearest["L"]],
                                        turn=nearest["turn"],
                                        k=f"{nearest['k']:.1f}")
            text += trig
            if nearest["k"] <= CTA_NEAR:
                trigger = {"date": ctx.target_day(symbol).isoformat(),
                           "level": nearest["level"], "k": round(nearest["k"], 3),
                           "horizon": W.CTA_HORIZONS[nearest["L"]],
                           "market": title}
        return make("cta", market, ctx, "read", score=s, words=text,
                    data_as_of=days[-1], public_at=_close_public(days[-1]),
                    proxy=symbol, short=short, trigger=trigger,
                    signs={str(L): v for L, v in signs.items()})
    return guarded("cta", market, ctx, _cell, proxy=symbol)


# 6. the variance risk premium (Bollerslev, Tauchen & Zhou; FEDS 2007-11)

def vrp_cell(ctx) -> dict:
    market, proxy = "us_equities", "SPX500"

    def _cell():
        days, c, _ = ctx.prices(proxy, need=VRP_MIN_DAYS + VRP_DAYS + 1)
        vix_rows, _units = ctx.fred("VIXCLS")
        vix = dict(vix_rows)
        rets = [None] + [math.log(b / a) for a, b in zip(c, c[1:])]
        series = []
        for i in range(VRP_DAYS, len(c)):
            v = vix.get(days[i])
            if v is None:
                continue
            rv = sum((100.0 * r) ** 2 for r in rets[i - VRP_DAYS + 1:i + 1])
            series.append((days[i], v * v / 12.0 - rv))
        series = series[-VRP_HISTORY_DAYS:]
        if len(series) < VRP_MIN_DAYS:
            raise Unread(W.R_FRED_THIN.format(series="VIXCLS", n=len(series),
                                              m=VRP_MIN_DAYS))
        vals = [v for _d, v in series]
        sigma = sd(vals)
        if not sigma:
            raise Unread(W.R_FRED_THIN.format(series="VIXCLS", n=len(series),
                                              m=VRP_MIN_DAYS))
        mean = sum(vals) / len(vals)
        z = (vals[-1] - mean) / sigma
        s = clip(z / 2)
        tmpl = (W.VRP_HIGH if s >= LEAN_AT else W.VRP_LOW if s <= -LEAN_AT
                else W.VRP_MID)
        d = series[-1][0]
        return make("vrp", market, ctx, "read", score=s,
                    words=tmpl.format(z=W.z(z)), data_as_of=d,
                    public_at=_close_public(d), proxy=proxy,
                    vrp=round(vals[-1], 3), z=round(z, 3))
    return guarded("vrp", market, ctx, _cell, proxy=proxy)


# 7. fund flows: the crowd's "follow the flow" claim, scored in public

def flows_cell(ctx, market, etf) -> dict:
    def _cell():
        days, c, v = ctx.prices(etf, need=FLOW_DAYS + FLOW_BASE_DAYS + 1)
        dv = [a * b for a, b in zip(c, v)]
        base = [x for x in dv[-(FLOW_DAYS + FLOW_BASE_DAYS):-FLOW_DAYS] if x > 0]
        med = median(base)
        if not med or sum(dv[-FLOW_DAYS:]) <= 0:
            raise Unread(W.R_NO_VOLUME.format(symbol=etf))
        ratio = sum(dv[-FLOW_DAYS:]) / (FLOW_DAYS * med)
        r5 = math.log(c[-1] / c[-1 - FLOW_DAYS])
        s = clip(sign(r5) * (ratio - 1.0))
        return make("flows", market, ctx, "read", score=s,
                    words=W.FLOWS.format(etf=etf, ratio=ratio,
                                         way="up" if r5 >= 0 else "down"),
                    data_as_of=days[-1], public_at=_close_public(days[-1]),
                    proxy=etf, ratio=round(ratio, 3))
    return guarded("flows", market, ctx, _cell, proxy=etf)


# 8. monthly options expiry week (Stivers & Sun, J. Banking & Finance 2013)

def opex_cell(ctx) -> dict:
    market, proxy = "us_equities", "SPX500"

    def _cell():
        target = ctx.target_day()
        exp = bmcal.monthly_expiry(target.year, target.month, ctx.cal)
        monday = exp - timedelta(days=exp.weekday())
        if not (monday <= target <= exp):
            return make("opex", market, ctx, "out_of_season",
                        words=W.OPEX_SEASON, proxy=proxy)
        h = max(1, ctx.cal.business_days_between(ctx.as_of, exp))
        return make("opex", market, ctx, "read", score=1.0,
                    words=W.OPEX.format(day=W.day_short(exp)),
                    data_as_of=ctx.as_of, proxy=proxy, horizon_days=h,
                    expiry=exp.isoformat())
    return guarded("opex", market, ctx, _cell, proxy=proxy)


# 9. the tide: dollar liquidity (weak evidence, context)

def _to_millions(series, units):
    factor = UNITS_TO_MILLIONS.get(units or "")
    if factor is None:
        raise Unread(W.R_UNITS.format(series=series, units=units or "none"))
    return factor


def _last_on_or_before(rows, d, days=None):
    """The value of the newest row dated on or before `d` (rows ascending;
    `days` their dates, passed once so a replay is not quadratic)."""
    days = days if days is not None else [r[0] for r in rows]
    i = bisect.bisect_right(days, d) - 1
    return rows[i][1] if i >= 0 else None


def _four_week_sign(ctx, series):
    try:
        rows, _u = ctx.fred(series)
    except Unread:
        return "unread"
    if len(rows) < TIDE_WEEKS + 1:
        return "unread"
    a, b = rows[-1 - TIDE_WEEKS][1], rows[-1][1]
    if a and abs(b - a) / abs(a) < 0.001:
        return "held"
    return "rose" if b > a else "fell"


def tide_cell(ctx) -> dict:
    market = "global"

    def _cell():
        walcl, uw = ctx.fred("WALCL")
        tga, ut = ctx.fred("WTREGEN")
        rrp, ur = ctx.fred("RRPONTSYD")
        fw, ft, fr = (_to_millions("WALCL", uw), _to_millions("WTREGEN", ut),
                      _to_millions("RRPONTSYD", ur))
        levels = []
        tga_days, rrp_days = [r[0] for r in tga], [r[0] for r in rrp]
        for d, w in walcl:
            t = _last_on_or_before(tga, d, tga_days)
            r = _last_on_or_before(rrp, d, rrp_days)
            if t is None or r is None:
                continue
            levels.append((d, w * fw - t * ft - r * fr))
        deltas = [b[1] - a[1] for a, b in zip(levels, levels[TIDE_WEEKS:])]
        need = TIDE_MIN_WEEKS + TIDE_WEEKS
        if len(deltas) < TIDE_MIN_WEEKS:
            raise Unread(W.R_FRED_THIN.format(series="WALCL", n=len(levels),
                                              m=need))
        sigma = sd(deltas[-TIDE_SIGMA_WEEKS:])
        if not sigma:
            raise Unread(W.R_FRED_THIN.format(series="WALCL", n=len(levels),
                                              m=need))
        z = deltas[-1] / sigma
        s = clip(z / 2)
        state = ("adding" if s >= LEAN_AT else "draining" if s <= -LEAN_AT
                 else "flat")
        d = levels[-1][0]
        text = W.TIDE.format(state=state,
                             reserves=_four_week_sign(ctx, "WRESBAL"),
                             custody=_four_week_sign(ctx, "WMTSECL1"))
        return make("tide", market, ctx, "read", score=s, words=text,
                    data_as_of=d,
                    public_at=datetime.combine(d + timedelta(days=1),
                                               time(20, 30), tzinfo=UTC),
                    proxy="SPX500", proxies=["SPX500", "BTCUSD"],
                    tide_state=state, z=round(z, 3))
    return guarded("tide", market, ctx, _cell, proxy="SPX500")


# 10. market stress, read-only, live only

def stress_cell(ctx) -> dict:
    market = "global"

    def _cell():
        if ctx.replayed:
            raise Unread(W.R_NOT_REPLAYED)
        from bot_program import market_stress as ms
        comps, _reasons = ms.read_components(ctx.now)
        if "vix_term" not in comps:
            term = ms._vix_term(ctx.now)
            if term is not None:
                comps["vix_term"] = term
        sc, subs = ms.score(comps)
        if sc is None:
            raise Unread(W.R_STRESS_NONE)
        level = ms.raw_level(sc, comps) or "calm"
        top = sorted(subs.items(), key=lambda kv: -kv[1])[:3]
        parts = [f"{W.STRESS_COMPONENTS.get(k, k)} {v:.0f}" for k, v in top]
        text = W.STRESS.format(level=W.STRESS_LEVELS.get(level, "Calm"),
                               n=f"{sc:.0f}",
                               components=", ".join(parts) or "none")
        return make("stress", market, ctx, "read", score=sc, words=text,
                    data_as_of=ctx.as_of, level=level)
    return guarded("stress", market, ctx, _cell)


def calendar_cell(ctx, triggers=()) -> dict:
    def _cell():
        start = ctx.read_time.date()
        evs, reasons = bmcal.events(start, 30, ctx.cal, triggers=triggers)
        return make("calendar", "global", ctx, "read", events=evs,
                    notes=reasons, data_as_of=ctx.as_of)
    return guarded("calendar", "global", ctx, _cell)
