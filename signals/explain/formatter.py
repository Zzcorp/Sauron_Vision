"""Build the 5-second signal card from a detector output."""
from .templates import HEADLINE_TEMPLATES, THESIS_TEMPLATES


# Conviction floor before any evidence is counted. Every card starts here, so
# the number a trader reads is "30 plus what this setup actually brought".
CONVICTION_BASE = 30

# One agreeing confluence family (structure / momentum / flow / macro /
# sentiment) is worth this much. Five families, so a card with everything
# agreeing tops out at +50 — the same order as the base, which keeps
# confluence from being the only thing that matters.
CONFLUENCE_POINTS_PER_CHIP = 10

# (minimum R, points). Geometry the trader can verify on the chart, so it
# outranks a single chip: 3R is worth two chips, and below 1R the trade's
# shape adds nothing worth scoring.
R_MULTIPLE_BONUS = ((3, 20), (2, 12), (1, 5))

# Hit-rate bonus = (hit_rate - 0.5) * HIT_RATE_GAIN, clamped. A coin flip
# earns nothing; each point of edge above 50% is worth 0.6 conviction points.
# The clamps are asymmetric on purpose — a measured edge can lift a card by
# 20, but a bad run is capped at -15 so a thin sample cannot bury a setup
# the platform would then stop collecting evidence on.
HIT_RATE_GAIN = 60
HIT_RATE_BONUS_MIN = -15
HIT_RATE_BONUS_MAX = 20


# `signals.explain.templates` is shared with the terminal renderer and the
# other setups; SFP was advertised in SmcSignal.SETUP_CHOICES long before any
# detector could emit one, so it never got a line there. This keeps the new
# card from falling back to "SFP setup at 1.2345", which says nothing about
# why the setup exists.
EXTRA_THESIS_TEMPLATES = {
    "SFP": (
        "Price pushed through the {sweep_level:.4f} swing and failed to hold "
        "it, closing back inside. The move trapped breakout traders; entry "
        "{entry:.4f} fades the failure with the wick as invalidation."
    ),
}


def build_card(setup_dict, symbol, timeframe, hit_rate=None, hit_rate_n=None,
               ict=None):
    """Convert a raw detector setup into a trader-facing card dict.

    hit_rate  — MEASURED 30d hit rate for this setup, or None when the sample
                is too small to be anything but noise. None renders as an
                em-dash and contributes nothing to conviction; it is never
                replaced by a prior, a default, or a zero.
    hit_rate_n — how many closed cards that rate was measured on. None means
                the performance record could not be read at all, which is a
                different fact from "no cards have closed yet" (0).
    ict       — output of `smc_rules.evaluate_ict_context`, or None when the
                ICT filters are off for this scan.
    """
    setup = setup_dict["setup"]
    direction = setup_dict["direction"]

    headline = HEADLINE_TEMPLATES.get(
        setup,
        "{symbol} {direction} · {setup} · {timeframe}",
    ).format(symbol=symbol, direction=direction, timeframe=timeframe, setup=setup)

    thesis_args = {
        "entry": setup_dict["entry"],
        "stop": setup_dict["stop"],
        "target": setup_dict["target"],
    }
    if "sweep" in setup_dict and setup_dict["sweep"]:
        thesis_args["sweep_level"] = setup_dict["sweep"].get("swept_price", 0)
    if "range" in setup_dict and setup_dict["range"]:
        thesis_args["range_high"] = setup_dict["range"]["high"]
        thesis_args["range_low"] = setup_dict["range"]["low"]
    try:
        thesis = _thesis_template(setup).format(setup=setup, **thesis_args)
    except (KeyError, ValueError):
        thesis = f"{setup} setup at {setup_dict['entry']:.4f}"

    why_now = build_why_now(setup_dict)
    chips = build_chips(setup_dict)
    conviction, reasons = score_conviction(
        chips, setup_dict, hit_rate=hit_rate, hit_rate_n=hit_rate_n, ict=ict,
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "setup": setup,
        "direction": direction,
        "headline": headline,
        "thesis": thesis,
        "why_now": why_now,
        "entry": setup_dict["entry"],
        "stop": setup_dict["stop"],
        "target": setup_dict["target"],
        "r_multiple": setup_dict.get("r_multiple", 0),
        "invalidation": setup_dict.get("invalidation", ""),
        "components": setup_dict.get("components", []),
        "chips": chips,
        "conviction": conviction,
        "reasons": reasons,
        "ict": ict,
        "hit_rate_30d": hit_rate,
        "hit_rate_n": hit_rate_n,
        "trigger_ts": setup_dict.get("trigger_ts"),
    }


def _thesis_template(setup):
    """Thesis line for a setup: the shared table first, then the local one."""
    return THESIS_TEMPLATES.get(
        setup,
        EXTRA_THESIS_TEMPLATES.get(setup, "{setup} setup at {entry:.4f}"),
    )


def build_why_now(s):
    """One-paragraph 'what just happened that triggered this'."""
    parts = []
    if s.get("sweep"):
        sw = s["sweep"]
        if sw.get("type") == "SWEEP_HIGH":
            parts.append(
                f"Sweep above {sw['swept_price']:.4f} "
                f"(wick {sw['wick_high']:.4f}, close {sw['close']:.4f})."
            )
        else:
            parts.append(
                f"Sweep below {sw['swept_price']:.4f} "
                f"(wick {sw['wick_low']:.4f}, close {sw['close']:.4f})."
            )
    if s.get("bos"):
        b = s["bos"]
        direction_word = "up" if b["type"] == "BOS_UP" else "down"
        parts.append(
            f"Structure broken {direction_word} at {b['broken_swing_price']:.4f}."
        )
    if s.get("breaker"):
        br = s["breaker"]
        kind = "bearish" if br["type"] == "BREAKER_BEAR" else "bullish"
        parts.append(
            f"Failed zone {br['low']:.4f}-{br['high']:.4f} flipped to {kind} breaker."
        )
    if s.get("range"):
        r = s["range"]
        parts.append(f"Range {r['low']:.4f}-{r['high']:.4f} in play.")
    if s.get("fvg"):
        f = s["fvg"]
        parts.append(f"Unfilled FVG {f['low']:.4f}-{f['high']:.4f} tagged.")
    if s.get("order_block"):
        ob = s["order_block"]
        parts.append(f"Order block {ob['low']:.4f}-{ob['high']:.4f} retested.")
    parts.append("Current bar tagging the trigger zone.")
    return " ".join(parts)


def build_chips(setup_dict):
    """Confluence chips: -1 disagreeing / 0 neutral / 1 supporting per family."""
    components = setup_dict.get("components", [])
    chips = {
        "structure": 0,
        "momentum": 0,
        "flow": 0,
        "macro": 0,
        "sentiment": 0,
    }
    structure_kw = ("sweep", "msb", "bos", "breaker", "range",
                    "supply", "demand", "fvg", "order_block",
                    "accumulation", "manipulation", "distribution",
                    "retest", "trend_aligned")
    if any(any(k in c for k in structure_kw) for c in components):
        chips["structure"] = 1
    return chips


def score_conviction(chips, setup_dict, hit_rate=None, hit_rate_n=None, ict=None):
    """Conviction 0-100 and the line-by-line reasons that produced it.

    The reasons are not decoration: conviction is the feed's primary sort key,
    so every term that moved it is written to `SmcSignal.reasons` and shown on
    the card. A number nobody can trace is a number nobody should trade.
    """
    reasons = ["base %d" % CONVICTION_BASE]
    score = CONVICTION_BASE

    agreeing = sum(1 for v in chips.values() if v > 0)
    confluence = agreeing * CONFLUENCE_POINTS_PER_CHIP
    score += confluence
    reasons.append("%d confluence chip(s) +%d" % (agreeing, confluence))

    r = setup_dict.get("r_multiple", 0) or 0
    r_bonus = next((pts for threshold, pts in R_MULTIPLE_BONUS if r >= threshold), 0)
    score += r_bonus
    reasons.append("%.2fR geometry +%d" % (r, r_bonus))

    if hit_rate is not None:
        hr_bonus = int((hit_rate - 0.5) * HIT_RATE_GAIN)
        hr_bonus = max(HIT_RATE_BONUS_MIN, min(HIT_RATE_BONUS_MAX, hr_bonus))
        score += hr_bonus
        reasons.append("30d hit rate %.0f%% measured on %s closed %+d"
                       % (hit_rate * 100, hit_rate_n, hr_bonus))
    elif hit_rate_n is None:
        # Not "0% of 0" — the record could not be read, and a card that
        # claimed a measurement here would be inventing one.
        reasons.append("30d hit rate not measured — performance record "
                       "unavailable +0")
    else:
        reasons.append("30d hit rate not empirical yet (%d closed) +0"
                       % hit_rate_n)

    if ict:
        score += ict.get("adjust", 0)
        reasons.extend(ict.get("reasons", []))

    return max(0, min(100, score)), reasons


def compute_conviction(chips, setup_dict, hit_rate, ict=None):
    """Conviction 0-100 only. `score_conviction` also returns the reasons."""
    return score_conviction(chips, setup_dict, hit_rate=hit_rate, ict=ict)[0]


def render_terminal_card(card):
    """Pretty-print a card for the CLI / management command."""
    bar = "=" * 68
    sep = "-" * 68
    chip_glyph = {-1: "x", 0: ".", 1: "#"}
    chip_str = " ".join(
        f"{name.upper()[:5]}{chip_glyph.get(val, '.')}"
        for name, val in card["chips"].items()
    )
    hit = card.get("hit_rate_30d")
    n = card.get("hit_rate_n")
    # An em-dash, never a 0% — nothing has closed, which is not a losing record.
    hit_str = f"{hit:.0%} on {n} closed" if hit is not None else "—"
    lines = [
        bar,
        card["headline"],
        sep,
        card["thesis"],
        "",
        f"  Entry:   {card['entry']:.4f}",
        f"  Stop:    {card['stop']:.4f}",
        f"  Target:  {card['target']:.4f}",
        f"  R:       {card['r_multiple']}",
        "",
        f"  Why now:      {card['why_now']}",
        f"  Invalidation: {card['invalidation']}",
        f"  Components:   {' + '.join(card['components'])}",
        f"  Confluence:   {chip_str}",
        f"  30d hit:      {hit_str}",
        f"  Conviction:   {card['conviction']}/100",
    ]
    lines += [f"    - {r}" for r in card.get("reasons", [])]
    lines.append(bar)
    return "\n".join(lines)
