"""The price cells' tags (2026-11-12): every cell that prints an
instrument's price asks market_data.one_quote, once per symbol per
response, and the response carries the values its cells used.

    {% load quote_tags %}
    <span data-q="{{ sym }}" data-q-side="{{ p.direction|q_side }}">{% q sym side=p.direction %}</span>
    <span data-q="{{ sym }}" data-q-f="words">{% q sym "words" %}</span>
    ...
    {% q_json %}            at the end of a page or of a fragment fetched alone

`q` prints one field of the rule's answer (core: one_quote.Shown
.field_text): "price" (default; `side` a position's direction or a side
name), "bid", "ask", "spread", "sides", "chg", "who", "words", "age",
"asof", "slot", "title". The cell carries `data-q` (and `data-q-f`,
`data-q-side`) so the browser's one painter (static/js/sv-venue.js) finds
it by attribute and keeps it on the newest value.

`q_json` writes one `<script type="application/json" data-sv-quotes>` with
the payload of every symbol this response printed and has not written
yet, and the server's clock: the browser ingests it before it paints, so a
server render older than what the page already shows never steps a cell
back. A new library, apart from sauron_tags: the shell's rewrite on its
own branch adds to that one.
"""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_SIDE_NAMES = ("bid", "ask", "mid", "last")


def _registry(context):
    from market_data.one_quote import for_request
    request = context.get("request") if context is not None else None
    return for_request(request)


def _side(side) -> str:
    """A side name, or a position's direction turned into its closing
    side ("BUY"/"long" -> "bid", "SELL"/"short" -> "ask")."""
    s = str(side or "").strip().lower()
    if s in _SIDE_NAMES:
        return s
    from market_data.one_quote import closing_side
    return closing_side(side)


@register.simple_tag(takes_context=True)
def q(context, symbol, field="price", side=None):
    """One field of the rule's answer for `symbol`, as text."""
    if not symbol:
        return "—"
    reg = _registry(context)
    return reg.get(symbol).field_text(field, side=_side(side) or None,
                                      now_at=reg.now)


@register.simple_tag(takes_context=True)
def q_json(context, shell=False):
    """The quote block of every symbol this response printed and has not
    written yet ("" when there is none). `shell=1` (the shell's own block,
    _partials/sv_venue.html at the end of base.html): every symbol the
    response asked, the headband's and the watchlist's included, which the
    shell printed from its context."""
    return mark_safe(_registry(context).json_block(shell=bool(shell)))


@register.simple_tag(takes_context=True)
def q_now(context):
    """The response's instant in epoch milliseconds: the browser's ages are
    counted on the server's clock (data-sv-now)."""
    reg = _registry(context)
    return int(round(reg.now.timestamp() * 1000))


@register.simple_tag(takes_context=True)
def q_title(context, symbol, side=None, tail=""):
    """The hover of a price cell: its words, who read it, a carried
    spread, the outside quote beside it, and the cell's own `tail` (the
    cell carries the same tail in data-q-title, and the browser's one
    painter rewrites the hover with the price)."""
    if not symbol:
        return ""
    reg = _registry(context)
    return reg.get(symbol).title(reg.now, side=_side(side) or None,
                                 tail=tail or "")


@register.filter
def q_side(direction) -> str:
    """A position's direction as the side its cell prints: "bid" for a
    long, "ask" for a short."""
    return _side(direction)
