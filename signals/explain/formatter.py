"""Build the 5-second signal card from a detector output."""
from .templates import HEADLINE_TEMPLATES, THESIS_TEMPLATES


def build_card(setup_dict, symbol, timeframe, hit_rate=None):
    """Convert a raw detector setup into a trader-facing card dict."""
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
        thesis = THESIS_TEMPLATES.get(
            setup, "{setup} setup at {entry:.4f}"
        ).format(setup=setup, **thesis_args)
    except (KeyError, ValueError):
        thesis = f"{setup} setup at {setup_dict['entry']:.4f}"

    why_now = build_why_now(setup_dict)
    chips = build_chips(setup_dict)
    conviction = compute_conviction(chips, setup_dict, hit_rate)

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
        "hit_rate_30d": hit_rate,
        "trigger_ts": setup_dict.get("trigger_ts"),
    }


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


def compute_conviction(chips, setup_dict, hit_rate):
    """Conviction 0-100. Combines confluence count, R-multiple, and hit rate."""
    base = 30
    confluence = sum(1 for v in chips.values() if v > 0) * 10
    r = setup_dict.get("r_multiple", 0)
    r_bonus = 0
    if r >= 3:
        r_bonus = 20
    elif r >= 2:
        r_bonus = 12
    elif r >= 1:
        r_bonus = 5
    hr_bonus = 0
    if hit_rate is not None:
        hr_bonus = int((hit_rate - 0.5) * 60)
        hr_bonus = max(-15, min(20, hr_bonus))
    score = base + confluence + r_bonus + hr_bonus
    return max(0, min(100, score))


def render_terminal_card(card):
    """Pretty-print a card for the CLI / management command."""
    bar = "=" * 68
    sep = "-" * 68
    chip_glyph = {-1: "x", 0: ".", 1: "#"}
    chip_str = " ".join(
        f"{name.upper()[:5]}{chip_glyph.get(val, '.')}"
        for name, val in card["chips"].items()
    )
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
        f"  Conviction:   {card['conviction']}/100"
        + (f"   (rule 30d hit-rate: {card['hit_rate_30d']:.0%})"
           if card.get("hit_rate_30d") is not None else ""),
        bar,
    ]
    return "\n".join(lines)
