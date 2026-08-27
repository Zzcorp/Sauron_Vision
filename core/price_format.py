"""How many decimals a price actually needs.

Every surface on this platform used to hardcode its own answer —
`floatformat:4` in the headband and the watchlist rail, `toFixed(4)` in
the live painter, `toFixed(2)` in the ticker — so AAPL rendered as
`227.5300` and a JPY cross rendered as `148.3250`, one digit past what
the venue quotes. Neither is wrong by much; both read as a machine that
does not know what it is showing.

The convention this follows is the venue's, not a rounding rule:

  * Forex is quoted in pips. A JPY cross carries three decimals, every
    other major five. That is what the broker's own ticket shows, and a
    forex price with two decimals is missing the part that moves.
  * Everything else scales with magnitude, because the question is how
    many digits are MEANINGFUL, not what the asset class is called. A
    227 dollar share and a 67,000 dollar bitcoin both want two. A
    0.85 token wants four. A 0.00002 token wants eight, and would read
    as zero at anything less.

One helper, used by the template tags and mirrored in the live painter,
so a value cannot be formatted one way on load and another on a tick.
"""
from decimal import Decimal, InvalidOperation

# Quote currencies conventionally shown to three decimals rather than
# five. JPY is the one that matters; the others follow the same logic.
_THREE_DECIMAL_QUOTES = ("JPY", "HUF", "KRW")


def price_decimals(value, asset_class="", symbol="") -> int:
    """Decimals for one price. Never raises — a bad value gets 2."""
    ac = (asset_class or "").strip().lower()
    sym = (symbol or "").strip().upper()

    if ac == "forex":
        # The QUOTE currency decides, so look at the tail of the pair:
        # USDJPY is three, JPYUSD (were it quoted) would not be.
        tail = sym[-3:] if len(sym) >= 6 else sym
        return 3 if tail in _THREE_DECIMAL_QUOTES else 5

    try:
        v = abs(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return 2
    if v >= 1:
        return 2
    if v >= Decimal("0.01"):
        return 4
    if v >= Decimal("0.0001"):
        return 6
    return 8


def format_price(value, asset_class="", symbol="", dash="—") -> str:
    """A price rendered at its own precision, or `dash` when absent.

    Grouping separators are deliberately absent: these land in
    monospaced cells beside each other, and a comma that appears at
    1,000 and vanishes at 999 makes a column jump.
    """
    if value is None or value == "":
        return dash
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return dash
    places = price_decimals(d, asset_class, symbol)
    return f"{d:.{places}f}"
