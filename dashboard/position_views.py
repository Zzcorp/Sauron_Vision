"""Order, filter and group the position tables (2026-09-26).

The operator's ask, 2026-09-26: the book in PURCHASE ORDER, with filters
(same asset, same type) and groups. Pure functions over the rows the views
already build — the open book's (live row dict, card detail) pairs, the
history's (UnifiedPosition | Position, card detail) pairs, /portfolio/'s
(live row dict, None) — so the order a row lands in is pinned without a
page (tests/test_position_views.py).

Server-side through GET params, on purpose: /positions/live/ and
/portfolio/live/ fetch LIVE_URL + window.location.search
(templates/_partials/live_region.html), so a filter kept in the query
string rides every refresh through this same code; one kept in the browser
alone would be wiped by the next swap.

Four rules the callers keep:
  - PAIRS move together. A row and its card detail are filtered, sorted and
    grouped as one tuple, so the zip can never misalign.
  - A filter narrows the TABLE, never the book. The strip, the class
    breakdown, the donut and Close all read the unfiltered rows, and the
    table says "showing N of M" whenever it holds less than the book.
  - Unmeasured stays unmeasured: a row with no P&L sorts after every
    measured one in both directions, and a group nothing in it could price
    sums to None — an em dash on the page, never 0.
  - A group sums EVERY matched row of its own, even the ones /portfolio/'s
    eight-row cap keeps off the table, and says how many it lists: a
    subtotal over the listed rows alone would read as the type's total and
    contradict the donut above it.

Unknown values fall back to the defaults; build_view never raises on a
query string (it logs and renders the defaults if anything does). A type or
an asset the book does not hold is dropped AND said so ("dropped"): the last
BTCUSD closing under ?symbol=BTCUSD turns the filter off on the next sweep,
and a table that went back to the whole book without a word would be read
as the filtered one. The value is echoed only when it looks like a ticker:
a crafted link must not put a sentence in the platform's voice on the page
that holds Close all.
"""
import logging
import re
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

#: The orders a table can take, (value, label). Purchase order leads: it is
#: the ask, and the default on the open book and on /portfolio/.
SORTS = (
    ("opened", "Purchase order (oldest first)"),
    ("-opened", "Newest first"),
    ("symbol", "Asset A-Z"),
    ("pnl", "P&L, worst first"),
    ("-pnl", "P&L, best first"),
    ("class", "Type A-Z"),
)
#: History adds the close. Newest close first stays its default: the order
#: the tab had before this module (unified_closed_positions).
HISTORY_SORTS = SORTS + (
    ("-closed", "Closed, newest first"),
    ("closed", "Closed, oldest first"),
)
OPEN_DEFAULT_SORT = "opened"
HISTORY_DEFAULT_SORT = "-closed"
GROUPS = (("", "No grouping"), ("class", "Group by type"),
          ("symbol", "Group by asset"))
SIDES = ("long", "short")
VENUES = ("live", "paper")
#: A value longer than this is junk, not a symbol.
MAX_PARAM = 64
#: What a dropped type or asset must look like to be echoed back: a ticker
#: or a class token, no space. Anything else is dropped under a neutral
#: sentence that repeats nothing of it.
ECHO_TOKEN = re.compile(r"[A-Za-z0-9._:/^=-]{1,24}")
#: The filters: (view key, query param, what the page calls it).
FILTERS = (("asset_class", "class", "type"), ("symbol", "symbol", "asset"),
           ("side", "side", "side"), ("venue", "venue", "venue"))


# ── Reading a row: a live dict, a UnifiedPosition or a legacy Position ────

def _field(row, name, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _number(value):
    """Decimal | float | str | None -> float | None. None stays None."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None      # NaN is not a measurement


def _stamp(value):
    """A datetime as a sortable float, None when there is none. A float and
    not the datetime: a naive and an aware stamp cannot be compared, and a
    sort must not 500 the page over one legacy row."""
    if value is None:
        return None
    try:
        return float(value.timestamp())
    except (AttributeError, TypeError, ValueError, OverflowError, OSError):
        return None


def row_symbol(row) -> str:
    sym = _field(row, "symbol")
    if not sym:
        sym = getattr(_field(row, "instrument"), "symbol", "")
    return str(sym or "")


def row_class(row) -> str:
    """The asset class ("type" on the page); "other" when none is known —
    dashboard.views._live_row's own fallback, so both readings agree."""
    cls = _field(row, "asset_class")
    if not cls:
        cls = getattr(_field(row, "instrument"), "asset_class", "")
    return str(cls or "other")


def row_side(row) -> str:
    """long | short — the reading _live_row signs the R with."""
    raw = str(_field(row, "direction") or "").lower()
    return "short" if raw in ("short", "sell") else "long"


def row_venue(row, detail=None) -> str:
    """live | paper | "" (unknown). The card detail's venue when there is
    one (the positions page); otherwise the row's own paper flag, and only
    on a bot row — a legacy Position has no venue, and _live_row's default
    of paper=True for it is a template fallback, not a fact."""
    if isinstance(detail, dict) and "venue" in detail:
        return str(detail.get("venue") or "").lower()
    if str(_field(row, "source") or "") != "bot":
        return ""
    paper = _field(row, "paper")
    if paper is None:
        return ""
    return "paper" if paper else "live"


def row_pnl(row):
    return _number(_field(row, "unrealized_pnl"))


def row_exposure(row, *, history=False):
    """|qty x price|: the mark where one exists and entry cost otherwise on
    the open book (the asset breakdown's own rule), entry on a closed trade.
    None when there is no quantity or no price to multiply."""
    qty = _number(_field(row, "quantity"))
    entry = _number(_field(row, "entry_price"))
    mark = None if history else _number(_field(row, "current_price"))
    price = mark if mark is not None else entry
    if qty is None or price is None:
        return None
    return abs(qty * price)


# ── The query string ──────────────────────────────────────────────────────

def _param(params, name) -> str:
    """One GET value, stripped; "" for anything unreadable or overlong."""
    try:
        raw = params.get(name, "")
    except Exception:  # noqa: BLE001 — unreadable params are no params
        return ""
    if isinstance(raw, (list, tuple)):
        raw = raw[-1] if raw else ""     # the last one, as QueryDict.get
    if not isinstance(raw, str):
        return ""
    raw = raw.strip()
    return raw if len(raw) <= MAX_PARAM else ""


def _counts(values) -> dict:
    out = {}
    for value in values:
        if value:
            out[value] = out.get(value, 0) + 1
    return out


def _pick(wanted, present) -> str:
    """`wanted` when the book holds it (case-insensitive), else ""."""
    if not wanted:
        return ""
    if wanted in present:
        return wanted
    folded = {key.casefold(): key for key in present}
    return folded.get(wanted.casefold(), "")


def _options(counts, chosen, order=None):
    """The select's options: the values PRESENT in the unfiltered book with
    their counts ("forex (3)"), plus the chosen one even at 0 — a selected
    side the book no longer holds must still read as selected."""
    keys = list(order) if order else sorted(counts, key=str.casefold)
    out = []
    for key in keys:
        n = counts.get(key, 0)
        if not n and key != chosen:
            continue
        out.append({"value": key, "label": "%s (%d)" % (key, n),
                    "selected": key == chosen})
    return out


def parse_view(params, pairs, *, history=False) -> dict:
    """The chosen order, filters and grouping, read off `params` against
    the book in `pairs`. Closed vocabulary: anything else is the default
    (sort) or "" (the rest) — never an exception."""
    sorts = HISTORY_SORTS if history else SORTS
    default = HISTORY_DEFAULT_SORT if history else OPEN_DEFAULT_SORT
    sort = _param(params, "sort")
    if sort not in {key for key, _label in sorts}:
        sort = default
    classes = _counts(row_class(row) for row, _d in pairs)
    symbols = _counts(row_symbol(row) for row, _d in pairs)
    sides = _counts(row_side(row) for row, _d in pairs)
    venues = _counts(row_venue(row, detail) for row, detail in pairs)
    side = _param(params, "side").lower()
    venue = _param(params, "venue").lower()
    group = _param(params, "group").lower()
    asked_class = _param(params, "class")
    asked_symbol = _param(params, "symbol")
    view = {
        "history": history,
        "sort": sort,
        "default_sort": default,
        "asset_class": _pick(asked_class, classes),
        "symbol": _pick(asked_symbol, symbols),
        "side": side if side in SIDES else "",
        "venue": venue if venue in VENUES else "",
        "group": group if group in dict(GROUPS) else "",
    }
    # A type or an asset asked for and not in the book: off, and said so.
    # The value is echoed (escaped) only when it looks like a ticker; any
    # other printable value is "" and the page says the filter is off
    # without repeating it. A control character is junk, not a name, and
    # is dropped without a word.
    view["dropped"] = [
        (label, asked if ECHO_TOKEN.fullmatch(asked) else "")
        for label, asked, got in (
            ("type", asked_class, view["asset_class"]),
            ("asset", asked_symbol, view["symbol"]))
        if asked and not got and asked.isprintable()]
    view["sort_options"] = [{"value": key, "label": label,
                             "selected": key == sort}
                            for key, label in sorts]
    view["group_options"] = [{"value": key, "label": label,
                              "selected": key == view["group"]}
                             for key, label in GROUPS]
    view["class_options"] = _options(classes, view["asset_class"])
    view["symbol_options"] = _options(symbols, view["symbol"])
    view["side_options"] = _options(sides, view["side"], order=SIDES)
    view["venue_options"] = _options(venues, view["venue"], order=VENUES)
    return view


# ── Filter, sort, group ───────────────────────────────────────────────────

def matches(row, detail, view) -> bool:
    if view["asset_class"] and row_class(row) != view["asset_class"]:
        return False
    if view["symbol"] and row_symbol(row) != view["symbol"]:
        return False
    if view["side"] and row_side(row) != view["side"]:
        return False
    if view["venue"] and row_venue(row, detail) != view["venue"]:
        return False
    return True


def filter_pairs(pairs, view):
    return [pair for pair in pairs if matches(pair[0], pair[1], view)]


def _ordered(pairs, key, reverse=False):
    """Stable sort on `key`; a pair whose key is None goes LAST whichever
    way the sort runs — an unmeasured row is not the smallest one."""
    have = [pair for pair in pairs if key(pair) is not None]
    rest = [pair for pair in pairs if key(pair) is None]
    have.sort(key=key, reverse=reverse)
    return have + rest


def _opened(pair):
    return _stamp(_field(pair[0], "opened_at"))


def _closed(pair):
    return _stamp(_field(pair[0], "closed_at"))


_SORT_KEYS = {
    "opened": (_opened, False),
    "-opened": (_opened, True),
    "symbol": (lambda pair: row_symbol(pair[0]).casefold() or None, False),
    "class": (lambda pair: row_class(pair[0]).casefold() or None, False),
    "pnl": (lambda pair: row_pnl(pair[0]), False),
    "-pnl": (lambda pair: row_pnl(pair[0]), True),
    "closed": (_closed, False),
    "-closed": (_closed, True),
}


def sort_pairs(pairs, sort):
    """Purchase order first, then `sort` on top of it. The sorts are
    stable, so rows the chosen order cannot tell apart keep the order they
    were bought in."""
    out = _ordered(list(pairs), _opened)
    if sort in _SORT_KEYS and sort != "opened":
        key, reverse = _SORT_KEYS[sort]
        out = _ordered(out, key, reverse)
    return out


def summarise(pairs, *, history=False) -> dict:
    """Count, exposure and P&L over one group's rows.

    Exposure follows the asset breakdown on the open book, so an unfiltered
    type group reads the breakdown's own figure for that type. P&L sums the
    rows that HAVE one and is None when none does: a group nothing in it
    could price is unmeasured, and the page prints an em dash, never 0.
    Formatted by dashboard.views' own _live_num, so the em-dash rule stays
    in one place.
    """
    from .views import _live_num, _live_tone
    n = len(pairs)
    exposure, pnl, n_priced = None, None, 0
    for row, _detail in pairs:
        value = row_exposure(row, history=history)
        if value is not None:
            exposure = (exposure or 0.0) + value
        move = row_pnl(row)
        if move is not None:
            pnl = (pnl or 0.0) + move
            n_priced += 1
    if pnl is not None:
        pnl = round(pnl, 2)
    if history:
        pnl_title = (
            "None of these closes could be graded: realized P&L is "
            "unmeasured, not zero." if not n_priced else
            "%d of %d closes graded; the rest are held out of this sum, "
            "not counted as zero." % (n_priced, n) if n_priced < n else
            "Booked P&L across all %d closes." % n)
        exposure_title = "Quantity x entry price, summed."
    else:
        pnl_title = (
            "Nothing in this group carries a live quote: its P&L is "
            "unmeasured, not zero." if not n_priced else
            "%d of %d carry a live quote; the rest are held out of this "
            "sum, not counted as zero." % (n_priced, n) if n_priced < n else
            "Marked to live quotes across all %d." % n)
        exposure_title = ("Notional at the live mark, entry cost where no "
                          "quote arrived: the rule the breakdown by asset "
                          "class uses.")
    return {
        "n": n,
        "noun": "trade" if history else "position",
        "exposure": exposure,
        "exposure_text": _live_num(exposure, "{:,.2f}"),
        "exposure_label": "exposure at entry" if history else "exposure",
        "exposure_title": exposure_title,
        "pnl": pnl,
        "pnl_text": _live_num(pnl),
        "pnl_tone": _live_tone(pnl),
        "pnl_label": "realized" if history else "unreal P&L",
        "pnl_title": pnl_title,
        "n_priced": n_priced,
    }


def _group(kind, key, pairs, *, history, listed=None):
    """One group: its sums over ALL of `pairs`, its rows the ones in
    `listed` (ids of the pairs the table shows; None is all of them)."""
    out = summarise(pairs, history=history)
    shown = (pairs if listed is None
             else [pair for pair in pairs if id(pair) in listed])
    out.update({
        "kind": kind,
        "key": key or "",
        "label": key or "",
        # The template prints a header row only for a real group; the
        # ungrouped table is one headless group so the loop has one shape.
        "header": bool(kind),
        "pairs": shown,
        "rows": [row for row, _detail in shown],
        "n_shown": len(shown),
        # The cap kept some of this group off the table; the sums above
        # still cover every one of them, and the header says so.
        "cut": len(shown) < len(pairs),
        "cut_title": (
            "The count and the sums cover all %d; the table lists %d of "
            "them, the rest are past its row cap." % (len(pairs), len(shown))),
    })
    return out


def group_pairs(pairs, group, *, history=False, shown=None):
    """[group, ...] in the order of each group's first row under the sort,
    rows inside a group in the sort's order. No grouping is ONE group with
    no header, so the table keeps a single loop shape either way.

    `shown` is the part of `pairs` the table lists (/portfolio/'s cap cuts
    the sorted list). Each group still counts and sums ALL its rows in
    `pairs`, so a group the cap cut reads the total the donut reads for it;
    a group the cap cut entirely keeps its header, with no row under it."""
    pairs = list(pairs)
    listed = None if shown is None else {id(pair) for pair in shown}
    if group not in ("class", "symbol"):
        return [_group("", "", pairs, history=history, listed=listed)]
    keyfn = row_class if group == "class" else row_symbol
    order, buckets = [], {}
    for pair in pairs:
        key = keyfn(pair[0]) or "—"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(pair)
    return [_group(group, key, buckets[key], history=history, listed=listed)
            for key in order]


def _build(params, pairs, *, history, limit, keep, base_url):
    pairs = [(pair[0], pair[1]) for pair in pairs]
    view = parse_view(params, pairs, history=history)
    matched = sort_pairs(filter_pairs(pairs, view), view["sort"])
    n_matched = len(matched)
    shown = matched
    if limit is not None and limit >= 0:
        shown = matched[:limit]
    # Grouped over every MATCHED row, listing only the shown ones: the cap
    # thins the table, never a group's count or its sums.
    groups = group_pairs(matched, view["group"], history=history, shown=shown)
    filters = [(label, view[key]) for key, _param_name, label in FILTERS
               if view[key]]
    keep = sorted((str(k), str(v)) for k, v in (keep or {}).items())
    view.update({
        # The rendered order: grouped rows gathered under their group.
        "pairs": [pair for group in groups for pair in group["pairs"]],
        "groups": groups,
        "grouped": bool(view["group"]),
        "n_total": len(pairs),
        "n_matched": n_matched,
        "n_shown": len(shown),
        "filters": filters,
        "filtered": bool(filters),
        # Less than the book on screen — a filter or /portfolio/'s cap. The
        # note prints on this OR on `filtered`: a filter that happens to
        # match the whole book is still a filter, and Close all says so.
        "partial": len(shown) < len(pairs),
        "changed": (bool(filters) or bool(view["group"])
                    or bool(view["dropped"])
                    or view["sort"] != view["default_sort"]),
        "keep": keep,
        "clear_href": base_url + ("?" + urlencode(keep) if keep else ""),
    })
    return view


def build_view(params, pairs, *, history=False, limit=None, keep=None,
               base_url=""):
    """Everything a position table needs to render in the chosen order.

    params    request.GET (or any mapping) — read, never trusted
    pairs     [(row, detail), ...], the UNFILTERED book; detail may be None
    history   the history tab: the close joins the sorts, default -closed
    limit     cap AFTER filter and sort (/portfolio/'s eight rows)
    keep      params every link and form carries (the tab)
    base_url  the page's own path, for the clear link — not request.path,
              which is the /live/ endpoint on a refresh
    """
    try:
        return _build(params, pairs, history=history, limit=limit,
                      keep=keep, base_url=base_url)
    except Exception:  # noqa: BLE001 — a query string must never 500 a page
        logger.warning("position view params unreadable, defaults used",
                       exc_info=True)
        return _build({}, pairs, history=history, limit=limit, keep=keep,
                      base_url=base_url)
