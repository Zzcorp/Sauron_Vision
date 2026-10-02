"""THE SMART MONEY'S FOOTPRINTS (2026-10-02) — where the crowd keeps its
stops, who just took them, and who is crowded.

The operator: study the smart money and the big flows of funds, avoid the
spoofing and the moves made on purpose to break the other side's
positions before entering. What can be seen from here, and what each
bot entry does with it:

1. THE CROWD'S STOPS (stop_beyond_the_crowd). Stops cluster just past
   the last swing high or low, the latest pullback's extreme and the
   round numbers. A stop hunt drives the price through them and turns.
   An entry's stop that sits in that zone is moved beyond it, by
   HUNT_DEPTH_ATR, within MAX_WIDEN_ATR. The size is computed from the
   moved stop (risk-based sizing), so the money at risk is unchanged: the
   position is smaller, not riskier. A zone that cannot be cleared within
   the cap leaves the stop where it was and takes CROWDED_STOP_SCALE.
   The trailing locks get the same treatment (lock_beyond_the_crowd):
   Aragorn's break-even and trail (position_care.py), and the engine's
   own (extras breakeven_at_r / trail_pct), held by the bot or resting at
   the broker (lock_adjuster) — never closer to the entry than the round
   trip, never looser than the stop already in place.
2. THE SWEEP (sweep_read). A bar that wicked through a swing level and
   closed back inside is a liquidity grab; whoever took the stops trades
   the other way. A real-money entry against a fresh sweep takes
   AGAINST_SWEEP_SCALE; a breakout barely past a level taken by the
   latest bar only (where the next sweep happens) takes
   UNCONFIRMED_BREAKOUT_SCALE.
3. THE CROWDED TRADE (cot_read). CFTC Commitments of Traders, weekly:
   the large speculators' and the commercials' net position against
   their own 3-year range (the COT index, 0-100). An entry on the side of
   a speculative extreme, or against a commercial (hedger) extreme,
   takes COT_EXTREME_SCALE, or COT_HIGH_SCALE short of the extreme.
4. THE ICT READ (ict_read, on signals/smc's detectors). The bias (the
   last displaced break of structure, else the swing sequence), the
   dealing range's premium and discount, the unfilled fair value gaps
   and unbroken order blocks on the way to the target, and the draw on
   liquidity (the nearest unswept pool the trade runs to). Against a
   confident bias: AGAINST_STRONG_BIAS_SCALE; against a weaker one,
   buying a premium or selling a discount, an opposing FVG or order
   block within OPPOSING_ZONE_ATR, or a draw closer than
   DRAW_MIN_ROOM_ATR: ICT_SCALE. The ICT session at entry is recorded.
5. THE VOLUME (volume_read). Over VOLUME_WINDOW bars, the volume of
   the bars that closed against the trade over the volume of those that
   closed with it: PRESSURE_AGAINST or more takes PRESSURE_SCALE (the
   tape is being sold into a buy). A sweep on thin volume is a weaker
   grab (THIN_SWEEP_SCALE instead of AGAINST_SWEEP_SCALE). A feed with
   no volume (forex and CFDs often carry none) reads nothing, said.
6. THE LIQUIDITY POOLS: equal highs and lows (two touches or more) are
   crowd levels for the stop, and the draw above.
7. THE VIX CURVE (the VIX over its 3-month twin, FRED VIXCLS / VXVCLS)
   is read by market_stress.py: a curve upside down is panic.

SPOOFING is not visible from here. It lives in the order book (level 2),
and eToro's API does not give it. Said, not pretended.

The switch is "smart_money" (LIVE_MONEY_SWITCHES), OFF by default: OFF,
nothing changes anywhere. ON: the stop moves on every bot entry, paper
and real (the paper record must measure the plan real money gets), and
the size scales bind real-money entries only. The strongest warning
wins (the scales are not multiplied). The manual lane is never touched.
Nothing here raises: a read that fails changes nothing and says why.
"""
import logging
import math

logger = logging.getLogger(__name__)

SWITCH = "smart_money"

TIMEFRAME = "4h"
BARS = 200
SWING_LEFT = SWING_RIGHT = 3
#: swing levels older than this many bars are not where today's stops are
LEVEL_LOOKBACK = 120
#: the latest pullback's extreme: the obvious stop place before it is a
#: confirmed swing
RECENT_EXTREME_BARS = 5
#: how far a hunt runs past a level, and so how far beyond it a stop goes
HUNT_DEPTH_ATR = 0.5
#: a stop this close on the near side of a level is taken on the way to it
NEAR_ATR = 0.25
#: the most a stop is ever moved, beyond the stop it replaces
MAX_WIDEN_ATR = 1.0
#: the round-number step is the power of ten at or above this many ATRs;
#: whole and half steps both count
ROUND_SPACING_ATR = 3.0

SWEEP_FRESH_BARS = 3
SWEEP_LOOKBACK = 80
SWEEP_WICK_RATIO = 0.5

AGAINST_SWEEP_SCALE = 0.5
UNCONFIRMED_BREAKOUT_SCALE = 0.75
CROWDED_STOP_SCALE = 0.75

THIN_SWEEP_SCALE = 0.75
#: a sweeping bar under this multiple of the median volume is thin
THIN_SWEEP_RVOL = 1.0

BIAS_STRONG = 0.6
AGAINST_STRONG_BIAS_SCALE = 0.5
ICT_SCALE = 0.75
OPPOSING_ZONE_ATR = 1.0
DRAW_MIN_ROOM_ATR = 1.0
POOL_MIN_TOUCHES = 2

VOLUME_WINDOW = 20
PRESSURE_AGAINST = 1.5
PRESSURE_SCALE = 0.75

COT_WINDOW_WEEKS = 156
COT_MIN_WEEKS = 52
COT_EXTREME = 90.0
COT_HIGH = 80.0
COT_EXTREME_SCALE = 0.5
COT_HIGH_SCALE = 0.75


def is_on() -> bool:
    """The switch (LIVE_MONEY_SWITCHES): OFF, nothing here runs."""
    from core.platform_control import is_component_enabled
    try:
        return bool(is_component_enabled(SWITCH))
    except Exception:  # noqa: BLE001
        return False


def _buy(direction) -> bool:
    return str(direction or "BUY").upper() == "BUY"


# ── 1. THE CROWD'S STOPS ──────────────────────────────────────────────────

def round_step(atr):
    """The round-number step for an instrument moving `atr` per bar, or
    None without an ATR."""
    if not atr or atr <= 0:
        return None
    return 10.0 ** math.ceil(math.log10(ROUND_SPACING_ATR * float(atr)))


def round_levels(lo, hi, step):
    """The whole and half steps in [lo, hi], at most 50."""
    if not step or step <= 0 or hi < lo:
        return []
    half = step / 2.0
    k0, k1 = math.ceil(lo / half), math.floor(hi / half)
    if k1 - k0 > 50:
        return []
    return [round(k * half, 10) for k in range(k0, k1 + 1)]


def _untaken(df, s, upto) -> bool:
    """Whether swing `s` still holds its stops at bar `upto` (exclusive):
    no bar since it traded through it (signals/smc/bias.unswept_pools)."""
    if df is None:
        return True
    a, b = s["idx"] + 1, upto
    if b <= a:
        return True
    if s["type"] == "H":
        return float(df["high"].values[a:b].max()) <= float(s["price"])
    return float(df["low"].values[a:b].min()) >= float(s["price"])


def crowd_levels(direction, entry, stop, atr, df=None, swings=None, *,
                 span=None) -> list:
    """[(price, kind)] where the crowd keeps its stops for a position on
    `direction`: swing lows (a BUY) or highs (a SELL) on the stop's side of
    the entry that no bar has traded through since (a taken swing's stops
    are gone), equal lows/highs among them, the latest pullback's extreme,
    and the round numbers that could touch the stop — within `span`
    (lo, hi) when given (the position care's whole range)."""
    buy = _buy(direction)
    out = []
    atr = float(atr or 0)
    reach = (HUNT_DEPTH_ATR + MAX_WIDEN_ATR) * atr
    n = len(df) if df is not None else 0
    held = [s for s in (swings or [])
            if (not n or s["idx"] >= n - LEVEL_LOOKBACK)
            and _untaken(df, s, n)]
    for s in held:
        if buy and s["type"] == "L" and s["price"] < entry:
            out.append((float(s["price"]), "swing low"))
        elif not buy and s["type"] == "H" and s["price"] > entry:
            out.append((float(s["price"]), "swing high"))
    if held:
        from signals.smc.liquidity import find_equal_levels
        for c in find_equal_levels(held):
            if c["count"] < POOL_MIN_TOUCHES:
                continue
            if buy and c["type"] == "EQL" and c["price"] < entry:
                out.append((float(c["price"]), f"equal lows ({c['count']} touches)"))
            elif not buy and c["type"] == "EQH" and c["price"] > entry:
                out.append((float(c["price"]), f"equal highs ({c['count']} touches)"))
    if df is not None and len(df) >= RECENT_EXTREME_BARS:
        tail = df.iloc[-RECENT_EXTREME_BARS:]
        if buy:
            low = float(tail["low"].min())
            if 0 < low < entry:
                out.append((low, "recent low"))
        else:
            high = float(tail["high"].max())
            if high > entry:
                out.append((high, "recent high"))
    step = round_step(atr)
    if step:
        if span is not None:
            lo, hi = span
        else:
            near = NEAR_ATR * atr
            lo, hi = ((stop - reach, stop + near) if buy
                      else (stop - near, stop + reach))
        for lvl in round_levels(lo, hi, step):
            if (buy and lvl < entry) or (not buy and lvl > entry):
                out.append((lvl, "round number"))
    return out


def stop_beyond_the_crowd(direction, entry, stop, atr, levels, *,
                          max_fraction=None, max_distance=None) -> dict:
    """{stop, moved, crowded, why, ...}: the stop moved beyond every
    crowd level it sits in the hunt zone of, or left with the reason.

    The zone of a level L for a BUY is [L - HUNT, L + NEAR] (just past the
    level, where the crowd's stops are, or just short of it, taken on the
    way); the stop then goes to L - HUNT. Levels are walked from the
    entry outwards, so one pass settles a chain. The stop never moves by
    more than MAX_WIDEN_ATR, nor past `max_fraction` of the entry, nor
    past `max_distance` from it (the widest stop the plan's reward:risk
    carries, risk_levels.max_stop_distance); a zone that cannot be
    cleared within that leaves the stop and says crowded."""
    buy = _buy(direction)
    base = {"stop": stop, "moved": False, "crowded": False}
    try:
        atr = float(atr or 0)
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError):
        return dict(base, why="levels unreadable")
    if atr <= 0 or entry <= 0:
        return dict(base, why="no ATR: the stop is left as computed")
    hunt, near = HUNT_DEPTH_ATR * atr, NEAR_ATR * atr
    limit = abs(entry - stop) + MAX_WIDEN_ATR * atr
    if max_fraction:
        limit = min(limit, float(max_fraction) * entry)
    if max_distance is not None:
        # no room at all still reads the zone: a stop left in it is crowded
        limit = min(limit, max(float(max_distance), abs(entry - stop)))
    new, crossed = stop, []
    walk = sorted(levels, key=lambda lv: -lv[0]) if buy else \
        sorted(levels, key=lambda lv: lv[0])
    for price, kind in walk:
        if buy:
            if price >= entry or not (price - hunt <= new <= price + near):
                continue
            target = price - hunt
        else:
            if price <= entry or not (price - near <= new <= price + hunt):
                continue
            target = price + hunt
        if abs(entry - target) > limit * (1.0 + 1e-9):
            # in ATRs of WIDENING, both sides: "1.90 ATR" read as the
            # widening when it was the whole stop distance (2026-10-02)
            widen = (abs(entry - target) - abs(entry - stop)) / atr
            room = max(0.0, (limit - abs(entry - stop)) / atr)
            allows = (f"the plan allows {room:.2f}" if room >= 0.005
                      else "the plan has no room to widen it")
            return dict(base, crowded=True, level=price, kind=kind,
                        why=(f"the stop sits in the crowd's zone at the "
                             f"{kind} {price:g}; clearing it means widening "
                             f"it {widen:.2f} ATR and {allows} — left where "
                             f"it was"))
        new = target
        crossed.append({"price": round(price, 10), "kind": kind})
    if not crossed:
        return dict(base, why="the stop is clear of the crowd's levels")
    last = crossed[-1]
    return {"stop": new, "moved": True, "crowded": False,
            "levels": crossed,
            "widened_atr": round(abs(new - stop) / atr, 3),
            "why": (f"stop moved {abs(new - stop) / atr:.2f} ATR, beyond the "
                    f"{last['kind']} {last['price']:g} where the crowd's "
                    f"stops sit")}


# ── 2. THE SWEEP ──────────────────────────────────────────────────────────

def sweep_read(df, swings, direction, atr, entry=None) -> dict:
    """{scale, against, with, breakout, why}: a liquidity grab in the last
    SWEEP_FRESH_BARS bars against or with `direction`, and a breakout
    barely past a level only the latest bar took. A swing counts only once
    confirmed (SWING_RIGHT bars after it) before the sweeping bar."""
    out = {"scale": 1.0, "against": None, "with": None, "breakout": None,
           "why": ""}
    if df is None or len(df) < SWING_LEFT + SWING_RIGHT + 2 or not swings:
        out["why"] = "too few bars to read a sweep"
        return out
    buy = _buy(direction)
    highs, lows = df["high"].values, df["low"].values
    opens, closes = df["open"].values, df["close"].values
    n = len(df)
    up, down = None, None   # the latest sweep of highs (bearish) / lows (bullish)
    for i in range(max(0, n - SWEEP_FRESH_BARS), n):
        h, lo, o, c = (float(highs[i]), float(lows[i]), float(opens[i]),
                       float(closes[i]))
        rng = h - lo
        if rng <= 0:
            continue
        for s in swings:
            if not (i - SWEEP_LOOKBACK <= s["idx"] and
                    s["idx"] + SWING_RIGHT < i) or not _untaken(df, s, i):
                continue
            p = float(s["price"])
            if s["type"] == "H" and h > p and c < p \
                    and (h - max(o, c)) / rng >= SWEEP_WICK_RATIO:
                up = {"bar": i - n, "level": p}
            elif s["type"] == "L" and lo < p and c > p \
                    and (min(o, c) - lo) / rng >= SWEEP_WICK_RATIO:
                down = {"bar": i - n, "level": p}
    against, aligned = (up, down) if buy else (down, up)
    out["against"], out["with"] = against, aligned
    if against and not aligned:
        # the last bar may still be forming: its volume is partial, so
        # only a finished sweeping bar can be called thin
        rvol = _rvol_at(df, n + against["bar"]) if against["bar"] < -1 \
            else None
        against["rvol"] = rvol
        thin = rvol is not None and rvol < THIN_SWEEP_RVOL
        out["scale"] = THIN_SWEEP_SCALE if thin else AGAINST_SWEEP_SCALE
        out["why"] = (f"a fresh sweep of the {'highs' if buy else 'lows'} at "
                      f"{against['level']:g}"
                      + (f" on thin volume ({rvol:g}x)" if thin else
                         f" on {rvol:g}x volume" if rvol is not None else "")
                      + ": whoever took those stops trades the other way")
    elif against and aligned:
        out["why"] = "both sides swept: no read"
    elif aligned:
        out["why"] = (f"with a fresh sweep of the {'lows' if buy else 'highs'}"
                      f" at {aligned['level']:g}")
    # A breakout only the latest bar took, the price barely past the level.
    try:
        atr = float(atr or 0)
        px = float(entry if entry is not None else closes[-1])
    except (TypeError, ValueError):
        atr, px = 0.0, 0.0
    if atr > 0 and out["scale"] == 1.0:
        for s in swings:
            if s["idx"] < n - LEVEL_LOOKBACK or s["idx"] + SWING_RIGHT >= n - 1:
                continue
            p = float(s["price"])
            before = closes[s["idx"] + 1:n - 1]
            if buy and s["type"] == "H" and p < px <= p + NEAR_ATR * atr \
                    and (len(before) == 0 or float(max(before)) <= p):
                out["breakout"] = {"level": p}
            elif not buy and s["type"] == "L" and p - NEAR_ATR * atr <= px < p \
                    and (len(before) == 0 or float(min(before)) >= p):
                out["breakout"] = {"level": p}
        if out["breakout"]:
            out["scale"] = UNCONFIRMED_BREAKOUT_SCALE
            out["why"] = (f"a breakout of {out['breakout']['level']:g} not "
                          f"yet held: the price is within {NEAR_ATR:g} ATR of "
                          f"a level only the latest bar took")
    return out


def _rvol_at(df, i):
    """Bar i's volume over the median of the VOLUME_WINDOW bars before it;
    None when the feed carries no volume there."""
    try:
        vols = [float(v) for v in df["volume"].values[max(0, i - VOLUME_WINDOW):i]]
        positive = sorted(v for v in vols if v > 0)
        if len(positive) < max(3, len(vols) // 2):
            return None
        med = positive[len(positive) // 2]
        return round(float(df["volume"].values[i]) / med, 2) if med > 0 else None
    except Exception:  # noqa: BLE001
        return None


# ── 3. THE CROWDED TRADE ──────────────────────────────────────────────────

def cot_index(values):
    """The COT index of the newest value (values newest first): where it
    stands in the window's range, 0-100; None on a flat window."""
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    if hi - lo <= 0:
        return None
    return round(100.0 * (vals[0] - lo) / (hi - lo), 1)


def cot_scale(direction, spec_idx, comm_idx) -> tuple:
    """(scale, why) for an entry on `direction` given the speculators' and
    the commercials' COT index. The crowd at an extreme on our side, or
    the hedgers at an extreme against us, takes less; the strongest
    warning wins."""
    buy = _buy(direction)
    warnings = []
    if spec_idx is not None:
        crowd = spec_idx if buy else 100.0 - spec_idx
        if crowd >= COT_EXTREME:
            warnings.append((COT_EXTREME_SCALE,
                             f"speculators crowded {'long' if buy else 'short'}"
                             f" (COT index {spec_idx:g})"))
        elif crowd >= COT_HIGH:
            warnings.append((COT_HIGH_SCALE,
                             f"speculators heavy {'long' if buy else 'short'}"
                             f" (COT index {spec_idx:g})"))
    if comm_idx is not None:
        against = 100.0 - comm_idx if buy else comm_idx
        if against >= COT_EXTREME:
            warnings.append((COT_EXTREME_SCALE,
                             f"commercials at an extreme "
                             f"{'short' if buy else 'long'} (COT index "
                             f"{comm_idx:g})"))
        elif against >= COT_HIGH:
            warnings.append((COT_HIGH_SCALE,
                             f"commercials heavy {'short' if buy else 'long'}"
                             f" (COT index {comm_idx:g})"))
    if not warnings:
        return 1.0, "positioning not crowded against this side"
    scale, why = min(warnings, key=lambda w: w[0])
    return scale, why


def cot_read(symbol, direction, now=None) -> dict:
    """{scale, spec_index, comm_index, weeks, why} from the COT reports of
    `symbol`, in its own frame (cot_sign: a USD-base pair reads the
    foreign currency's future the other way). Neutral, said, without a
    fresh report or COT_MIN_WEEKS of history."""
    from django.utils import timezone
    out = {"scale": 1.0, "spec_index": None, "comm_index": None,
           "weeks": 0, "why": ""}
    try:
        from instruments.models import Instrument
        from scraping.models import COTReport
        from signals.opportunity_scanner import COT_MAX_AGE_DAYS, cot_sign
        now = now or timezone.now()
        as_of = now.date() if hasattr(now, "date") else now
        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            out["why"] = "no instrument row"
            return out
        rows = list(COTReport.objects.filter(
            instrument=inst, report_date__lte=as_of)
            .order_by("-report_date")[:COT_WINDOW_WEEKS])
        out["weeks"] = len(rows)
        if not rows:
            out["why"] = "no COT report (no futures market maps to it)"
            return out
        age = (as_of - rows[0].report_date).days
        if age > COT_MAX_AGE_DAYS:
            out["why"] = f"COT report stale ({age} days)"
            return out
        if len(rows) < COT_MIN_WEEKS:
            out["why"] = (f"COT history thin: {len(rows)} weeks, "
                          f"{COT_MIN_WEEKS} needed (manage.py smart_money "
                          f"cot-backfill)")
            return out
        if not rows[0].open_interest:
            out["why"] = (f"COT report of {rows[0].report_date} has no open "
                          f"interest: unread")
            return out
        sign = cot_sign(inst)
        spec = [sign * (r.non_commercial_long - r.non_commercial_short)
                / r.open_interest for r in rows if r.open_interest]
        comm = [sign * (r.commercial_long - r.commercial_short)
                / r.open_interest for r in rows if r.open_interest]
        out["spec_index"] = cot_index(spec)
        out["comm_index"] = cot_index(comm)
        out["scale"], out["why"] = cot_scale(direction, out["spec_index"],
                                             out["comm_index"])
        out["report_date"] = rows[0].report_date.isoformat()
    except Exception as e:  # noqa: BLE001
        out["why"] = f"COT unreadable: {type(e).__name__}"
    return out


# ── 4. THE ICT READ ───────────────────────────────────────────────────────

def ict_scale(direction, *, bias=None, confidence=None, zone=None,
              opposing=None, draw_room_atr=None) -> tuple:
    """(scale, why) from the ICT facts of one entry — pure. `opposing` is
    the words for an opposing FVG or order block within reach, or None;
    `draw_room_atr` the distance to the draw in ATRs, or None. The
    strongest warning wins; nothing here ever raises a size."""
    buy = _buy(direction)
    side = "long" if buy else "short"
    warnings = []
    if bias in ("long", "short") and bias != side:
        c = float(confidence or 0.0)
        warnings.append((AGAINST_STRONG_BIAS_SCALE if c >= BIAS_STRONG
                         else ICT_SCALE,
                         f"against the ICT bias ({bias}, confidence {c:g})"))
    elif zone == ("premium" if buy else "discount"):
        warnings.append((ICT_SCALE,
                         f"{'buying the premium' if buy else 'selling the discount'}"
                         f" of the dealing range: chasing"))
    if opposing:
        warnings.append((ICT_SCALE, opposing))
    if draw_room_atr is not None and draw_room_atr < DRAW_MIN_ROOM_ATR:
        warnings.append((ICT_SCALE,
                         f"the draw on liquidity is {draw_room_atr:.2f} ATR "
                         f"away: little left to be paid"))
    if not warnings:
        return 1.0, ""
    return min(warnings, key=lambda w: w[0])


def _ict_session(now):
    try:
        from signals.smc.sessions import ICT_SESSIONS_NY, in_ny_session
        for name in ICT_SESSIONS_NY:
            if not name.startswith("silver_bullet") and in_ny_session(now, name):
                return name
    except Exception:  # noqa: BLE001
        return None
    return None


def ict_read(df, swings, direction, atr, entry, *, now=None) -> dict:
    """{scale, why, bias, confidence, zone, opposing, draw, draw_room_atr,
    session} for one entry, on signals/smc's detectors. Too few bars reads
    nothing, said."""
    from django.utils import timezone
    out = {"scale": 1.0, "why": "", "bias": None, "confidence": None,
           "zone": None, "opposing": None, "draw": None,
           "draw_room_atr": None,
           "session": _ict_session(now or timezone.now())}
    if df is None or len(df) < 30 or not swings:
        out["why"] = "too few bars for the ICT read"
        return out
    from signals.smc.bias import daily_bias, draw_on_liquidity, unswept_pools
    from signals.smc.structure import detect_market_structure_breaks
    from signals.smc.zones import detect_fvgs, detect_order_blocks
    buy = _buy(direction)
    entry = float(entry)
    breaks = detect_market_structure_breaks(df, swings)
    b = daily_bias(df, swings, breaks=breaks) or {}
    out["bias"], out["confidence"] = b.get("bias"), b.get("confidence")
    loc = b.get("location")
    out["zone"] = loc[0] if loc else None
    try:
        atr = float(atr or 0)
    except (TypeError, ValueError):
        atr = 0.0
    if atr > 0:
        reach = OPPOSING_ZONE_ATR * atr
        for f in detect_fvgs(df):
            if f["filled"]:
                continue
            # beyond the entry within reach, or around it (buying into it)
            if buy and f["type"] == "FVG_BEAR" \
                    and f["high"] > entry and f["low"] <= entry + reach:
                out["opposing"] = (f"an unfilled bearish FVG {f['low']:g}-"
                                   f"{f['high']:g} on the way up")
            elif not buy and f["type"] == "FVG_BULL" \
                    and f["low"] < entry and f["high"] >= entry - reach:
                out["opposing"] = (f"an unfilled bullish FVG {f['low']:g}-"
                                   f"{f['high']:g} on the way down")
        if not out["opposing"]:
            for ob in detect_order_blocks(df, breaks):
                if ob["broken"]:
                    continue
                if buy and ob["type"] == "OB_BEAR" \
                        and entry < ob["high"] and ob["low"] <= entry + reach:
                    out["opposing"] = (f"an unbroken bearish order block "
                                       f"{ob['low']:g}-{ob['high']:g} overhead")
                elif not buy and ob["type"] == "OB_BULL" \
                        and entry > ob["low"] and ob["high"] >= entry - reach:
                    out["opposing"] = (f"an unbroken bullish order block "
                                       f"{ob['low']:g}-{ob['high']:g} underfoot")
        pools = unswept_pools(df, swings)
        draws = draw_on_liquidity(df, swings, pools=pools) or {}
        draw = draws.get("buy_side" if buy else "sell_side")
        if draw:
            room = (draw["price"] - entry) if buy else (entry - draw["price"])
            out["draw"] = {"price": draw["price"], "touches": draw["touches"]}
            # at or past the draw already (an adverse fill, an old last
            # bar): no room at all, not "no reading"
            out["draw_room_atr"] = round(max(0.0, room) / atr, 2)
    out["scale"], out["why"] = ict_scale(
        direction, bias=out["bias"], confidence=out["confidence"],
        zone=out["zone"], opposing=out["opposing"],
        draw_room_atr=out["draw_room_atr"])
    return out


# ── 5. THE VOLUME ─────────────────────────────────────────────────────────

def volume_read(df, direction) -> dict:
    """{scale, pressure, rvol, why}: the volume of the last VOLUME_WINDOW
    bars that closed against `direction` over the volume of those that
    closed with it (pressure), and the latest bar's relative volume."""
    out = {"scale": 1.0, "pressure": None, "rvol": None, "why": ""}
    if df is None or len(df) < VOLUME_WINDOW + 1:
        out["why"] = "too few bars to read the volume"
        return out
    win = df.iloc[-VOLUME_WINDOW:]
    vols = [float(v) for v in win["volume"].values]
    if sum(1 for v in vols if v > 0) < VOLUME_WINDOW // 2:
        out["why"] = "no volume in this feed (forex and CFDs often carry none)"
        return out
    out["rvol"] = _rvol_at(df, len(df) - 1)
    up = sum(v for o, c, v in zip(win["open"].values, win["close"].values, vols)
             if float(c) > float(o))
    down = sum(v for o, c, v in zip(win["open"].values, win["close"].values, vols)
               if float(c) < float(o))
    buy = _buy(direction)
    with_v, against_v = (up, down) if buy else (down, up)
    if with_v <= 0 and against_v <= 0:
        return out
    ratio = 99.0 if with_v <= 0 else round(against_v / with_v, 2)
    out["pressure"] = ratio
    if ratio >= PRESSURE_AGAINST:
        out["scale"] = PRESSURE_SCALE
        out["why"] = (f"the volume leans against: {'down' if buy else 'up'}-bar"
                      f" volume {ratio:g}x the {'up' if buy else 'down'}-bar "
                      f"volume over {VOLUME_WINDOW} bars")
    return out


# ── THE ENTRY ─────────────────────────────────────────────────────────────

def _bars(symbol, timeframe):
    from signals.smc.dataframe import load_ohlcv
    from signals.smc.pivots import classify_swings, get_swings
    df = load_ohlcv(symbol, timeframe, bars=BARS)
    if df is None or len(df) < SWING_LEFT + SWING_RIGHT + 2:
        return df, []
    # labelled (HH/HL/LH/LL), as every signals/smc caller hands them:
    # daily_bias reads the structure from the labels
    return df, classify_swings(get_swings(df, SWING_LEFT, SWING_RIGHT))


def entry_read(symbol, direction, entry, stop, *, atr=None, asset_class="",
               timeframe=TIMEFRAME, now=None, bars=None,
               max_distance=None) -> dict:
    """Everything the smart money says about one entry:
    {stop, moved, scale, why, stop_read, sweep, cot}. `stop` is the stop
    to place (moved or not); `scale` the size a REAL-MONEY entry takes
    (the strongest warning; 1.0 when none). `bars` = (df, swings) for a
    caller that already has them; `max_distance` the widest stop the
    plan carries. Never raises."""
    out = {"stop": stop, "moved": False, "scale": 1.0, "why": [],
           "stop_read": {}, "sweep": {}, "ict": {}, "volume": {}, "cot": {}}
    try:
        df, swings = bars if bars is not None else _bars(symbol, timeframe)
    except Exception as e:  # noqa: BLE001
        df, swings = None, []
        out["why"].append(f"bars unreadable: {type(e).__name__}")
    if not atr and df is not None and len(df) > 15:
        try:
            from signals.smc.pivots import atr as _atr
            atr = float(_atr(df)[-1]) or None
        except Exception:  # noqa: BLE001
            atr = None
    scales = []
    try:
        from bot_program.asset_engine.risk_levels import stop_band
        levels = crowd_levels(direction, entry, stop, atr, df, swings)
        sr = stop_beyond_the_crowd(direction, entry, stop, atr, levels,
                                   max_fraction=stop_band(asset_class)[1],
                                   max_distance=max_distance)
        out["stop_read"] = {k: v for k, v in sr.items() if k != "stop"}
        if sr["moved"]:
            out["stop"], out["moved"] = sr["stop"], True
        if sr["crowded"]:
            scales.append((CROWDED_STOP_SCALE, sr["why"]))
        out["why"].append(sr["why"])
    except Exception as e:  # noqa: BLE001
        out["why"].append(f"stop read failed: {type(e).__name__}")
    try:
        sw = sweep_read(df, swings, direction, atr, entry=entry)
        out["sweep"] = sw
        if sw["scale"] < 1.0:
            scales.append((sw["scale"], sw["why"]))
        if sw["why"]:
            out["why"].append(sw["why"])
    except Exception as e:  # noqa: BLE001
        out["why"].append(f"sweep read failed: {type(e).__name__}")
    for name, reader in (
            ("ict", lambda: ict_read(df, swings, direction, atr, entry, now=now)),
            ("volume", lambda: volume_read(df, direction))):
        try:
            r = reader()
            out[name] = r
            if r["scale"] < 1.0:
                scales.append((r["scale"], r["why"]))
            if r["why"]:
                out["why"].append(r["why"])
        except Exception as e:  # noqa: BLE001
            out[name] = {}
            out["why"].append(f"{name} read failed: {type(e).__name__}")
    cot = cot_read(symbol, direction, now=now)
    out["cot"] = cot
    if cot["scale"] < 1.0:
        scales.append((cot["scale"], cot["why"]))
    if cot["why"]:
        out["why"].append(cot["why"])
    if scales:
        out["scale"], strongest = min(scales, key=lambda s: s[0])
        # said once, at the top, with the size it set
        if strongest in out["why"]:
            out["why"].remove(strongest)
        out["why"].insert(0, f"size x{out['scale']:g}: {strongest}")
    return out


def care_levels(symbol, side, price, *, timeframe=TIMEFRAME) -> dict:
    """{"atr", "levels"} for the position care (position_care.plan): the
    crowd's levels within reach under a long's mark (over a short's), or
    None without bars."""
    df, swings = _bars(symbol, timeframe)
    if df is None or len(df) <= 15:
        return None
    from signals.smc.pivots import atr as _atr
    atr = float(_atr(df)[-1] or 0)
    if atr <= 0:
        return None
    price = float(price)
    buy = _buy(side)
    reach = (3.0 + HUNT_DEPTH_ATR + MAX_WIDEN_ATR) * atr
    span = (price - reach, price) if buy else (price, price + reach)
    far = price - 3.0 * atr if buy else price + 3.0 * atr
    return {"atr": atr,
            "levels": crowd_levels(side, price, far, atr, df, swings,
                                   span=span)}


#: the stop column's precision (AssetBotTrade.stop_loss: 8 places). A lock
#: is snapped onto it, AWAY from the mark, so the value stored is the value
#: asked: a 10-decimal lock stored at 8 read as a fresh "tighter" stop on
#: the next tick and went back to the venue every five minutes (review of
#: PR21, 2026-10-02).
LOCK_QUANTUM = "1e-8"


def _snap_away_from_mark(value, buy):
    from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
    return Decimal(repr(float(value))).quantize(
        Decimal(LOCK_QUANTUM), rounding=ROUND_FLOOR if buy else ROUND_CEILING)


def lock_beyond_the_crowd(side, price, entry, lock, crowd, *,
                          cost=0.0) -> tuple:
    """(lock, moved) — a profit lock (a break-even, a trail) moved out of
    the crowd's hunt zone at the mark `price`, never closer to the entry
    than its round-trip `cost` (a fraction): a lock stays a lock, net of
    what the trip cost. One copy for every lane that trails a stop:
    Aragorn's position care and the engine's break-even and trail, held
    by the bot or resting at the broker (2026-10-02).

    The crowd's levels are read around the MARK (care_levels); the round
    numbers are also listed around the LOCK itself, because a percentage
    trail can sit far past the mark's span on a quiet series and land on a
    figure nobody listed. A moved lock comes back snapped to the stop
    column's 8 places, away from the mark."""
    buy = _buy(side)
    d = 1.0 if buy else -1.0
    try:
        price, entry, lock = float(price), float(entry), float(lock)
    except (TypeError, ValueError):
        return lock, False
    if not crowd or price <= 0 or entry <= 0:
        return lock, False
    floor = entry * (1.0 + d * max(0.0, float(cost or 0.0)))
    if d * (price - floor) <= 0:
        return lock, False
    atr = float(crowd.get("atr") or 0.0)
    levels = list(crowd.get("levels") or [])
    step = round_step(atr)
    if step:
        reach = (HUNT_DEPTH_ATR + MAX_WIDEN_ATR) * atr
        lo, hi = ((lock - reach, lock + NEAR_ATR * atr) if buy
                  else (lock - NEAR_ATR * atr, lock + reach))
        listed = {round(p, 10) for p, _k in levels}
        levels += [(lvl, "round number") for lvl in round_levels(lo, hi, step)
                   if (lvl < price if buy else lvl > price)
                   and round(lvl, 10) not in listed]
    r = stop_beyond_the_crowd("BUY" if buy else "SELL", price, lock, atr,
                              levels, max_distance=abs(price - floor))
    if not r["moved"]:
        return lock, False
    snapped = float(_snap_away_from_mark(r["stop"], buy))
    if d * (snapped - floor) < 0:
        return lock, False
    return snapped, True


def lock_adjuster(bot, trade, price):
    """A callable (lock, why) -> (lock, why) for the engine's break-even
    and trail (bot_program/engine/trailing.py), or None when the smart
    money does not apply: the switch OFF, options (a premium has no crowd
    levels), the operator's manual lane. The crowd's levels are read once,
    on the first lock asked about, never on a tick that asks nothing — and
    a read that failed is not retried in the same tick.

    The floor is the round trip the row was charged; a row opened before
    `cost_fraction_charged` existed takes the config's own round-trip
    estimate (risk_levels.round_trip_cost_fraction), never the bare entry,
    where a "break-even" books a loss. Never raises: a failed read leaves
    the lock where the rule put it."""
    try:
        if "options" in (getattr(bot, "asset_class", ""),
                         getattr(trade, "asset_class", "")):
            return None
        if not is_on():
            return None
        from bot_program.share_allocator import _is_manual_lane
        if _is_manual_lane(bot.cfg):
            return None
    except Exception:  # noqa: BLE001 — unknown reads as "do not touch"
        return None
    seen = {}

    def _crowd():
        if "crowd" not in seen:
            seen["crowd"] = None          # a failure is remembered too
            seen["crowd"] = care_levels(trade.symbol, trade.side, price)
        return seen["crowd"]

    def _cost():
        charged = (trade.metadata or {}).get("cost_fraction_charged")
        if charged is not None:
            return float(charged)
        from bot_program.asset_engine.risk_levels import (
            round_trip_cost_fraction,
        )
        return float(round_trip_cost_fraction(bot.cfg, trade.symbol))

    def adjust(lock, why):
        if lock is None:
            return lock, why
        try:
            moved_to, moved = lock_beyond_the_crowd(
                trade.side, price, trade.entry_price, lock, _crowd(),
                cost=_cost())
        except Exception as e:  # noqa: BLE001
            logger.info("[smart money] %s: lock left (%s)",
                        getattr(trade, "symbol", "?"), e)
            return lock, why
        if not moved:
            return lock, why
        return (_snap_away_from_mark(moved_to, _buy(trade.side)),
                f"{why} (beyond the crowd)")

    return adjust


def meta_for(read: dict, original_stop) -> dict:
    """The compact record an entry's row carries (metadata["smart_money"]),
    so a later grading can say whether the moves paid."""
    sr = read.get("stop_read") or {}
    sw = read.get("sweep") or {}
    cot = read.get("cot") or {}
    ict = read.get("ict") or {}
    vol = read.get("volume") or {}
    return {
        "stop_moved": bool(read.get("moved")),
        "original_stop": round(float(original_stop), 10),
        "widened_atr": sr.get("widened_atr"),
        "crowded": bool(sr.get("crowded")),
        "scale": read.get("scale", 1.0),
        "sweep_against": bool(sw.get("against")) and not sw.get("with"),
        "breakout_unheld": bool(sw.get("breakout")),
        "cot_spec": cot.get("spec_index"),
        "cot_comm": cot.get("comm_index"),
        "ict_bias": ict.get("bias"),
        "ict_confidence": ict.get("confidence"),
        "ict_zone": ict.get("zone"),
        "ict_opposing": bool(ict.get("opposing")),
        "ict_draw_room_atr": ict.get("draw_room_atr"),
        "ict_session": ict.get("session"),
        "volume_pressure": vol.get("pressure"),
        "why": list(read.get("why") or [])[:6],
    }


# ── THE OPERATOR'S VIEW ───────────────────────────────────────────────────

def summary_lines(now=None, *, days=1) -> list:
    """The smart money in plain lines (manage.py smart_money, Aragorn's
    daily report): the switch, the VIX curve, what it did to the bot
    entries of the last `days`, and whether the moved stops paid over 60
    days of closes."""
    from datetime import timedelta
    from django.utils import timezone
    now = now or timezone.now()
    lines = [f"Smart money: {'ON' if is_on() else 'OFF'}"]
    try:
        from bot_program.market_stress import _vix_term
        term = _vix_term(now)
        if term is not None:
            lines.append(f"  VIX curve {term:g} (VIX / VIX3M; above 1 is "
                         f"upside down: panic)")
    except Exception:  # noqa: BLE001
        pass
    try:
        from bot_program.asset_models import AssetBotTrade
        fresh = list(AssetBotTrade.objects.filter(
            opened_at__gte=now - timedelta(days=days),
            metadata__has_key="smart_money")
            .values_list("paper", "metadata"))
        moved = sum(1 for _p, m in fresh
                    if (m.get("smart_money") or {}).get("stop_moved"))
        smaller = sum(1 for p, m in fresh if not p
                      and float((m.get("smart_money") or {}).get("scale")
                                or 1.0) < 1.0)
        lines.append(f"  last {days * 24}h: {len(fresh)} entries read, "
                     f"{moved} stops moved out of the crowd, {smaller} "
                     f"real-money entries taken smaller")
        closed = list(AssetBotTrade.objects.filter(
            closed_at__gte=now - timedelta(days=60), status="CLOSED",
            metadata__has_key="smart_money", realized_r__isnull=False)
            .values_list("metadata", "realized_r"))
        groups = {True: [], False: []}
        for m, r in closed:
            groups[bool((m.get("smart_money") or {}).get("stop_moved"))] \
                .append(float(r))
        for key, label in ((True, "moved stops"), (False, "stops left")):
            rs = groups[key]
            if rs:
                lines.append(f"  60d closes, {label}: n {len(rs)} · "
                             f"expectancy {sum(rs) / len(rs):+.2f}R · "
                             f"stopped out {sum(1 for r in rs if r <= -0.9)}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"  entries unread: {type(e).__name__}")
    return lines
