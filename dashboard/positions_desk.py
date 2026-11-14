"""The desk on /positions/ (UI batch B7, 2026-11-13).

The operator approved the desk v2 board ("amazing work, bravo, I need it
fast!!"): Bloomberg's discipline and TradingView's calm in Sauron's
identity. This module reads the figures that board draws around the open
book, off what the page already holds; it values nothing a second time.

  * OPEN P&L BY WORLD: REAL, DEMO and PAPER apart, never summed (the
    operator's rule since 2026-09-30). Each world's figure is the sum of
    the P&L its rows PRINT (eToro's own on an eToro row its holdings list,
    dashboard.views._live_row), with its count and, for REAL, how old
    eToro's figures are. A world whose rows print an estimate says so (≈).
  * THE BOOK AT eTORO, the real book only: the account's equity, the
    notional of the REAL rows at their marks, what every REAL stop costs
    if all fill against the open-risk limit (the gates' limit and book
    size, each world-live row priced as the gate prices it: the reading
    bot_program.orcs.sources makes of the live book, made here), and the
    margin eToro says it holds.
  * CLOSED · 24 H, the REAL EXPOSURE by class and by side, and CLOSED · 30 D
    by world: the lower row of the board.

DISPLAY ONLY. Nothing here writes, orders, sizes or gates; no broker and no
model is called, and nothing of the Orcs is imported (their importers are
frozen: tests/orcs/test_orc_o2a_shadow_pins.py). A figure the platform does
not have is None, and the page prints the em dash for it, never a zero.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

WORLDS = ("live", "demo", "paper")
DASH = "—"
#: A world's 30-day record prints its rates from this many graded closes
#: (the board: "Demo is judged from 10 closes"); fewer print the count and
#: a dash, never a rate read off three trades.
MIN_GRADED = 10
#: How a close ended, in the board's one word ("By").
BY_WORDS = {"hit_target": "target", "stopped_out": "stop",
            "manual_close": "you", "time_stop": "time",
            "expired": "expiry"}


def _f(value):
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def signed(value, places=2):
    """'+76.26' / '-4.16'; the em dash for None."""
    v = _f(value)
    if v is None:
        return DASH
    return ("{:+,.%df}" % places).format(v)


def tone(value):
    v = _f(value)
    if v is None or v == 0:
        return ""
    return "up" if v > 0 else "down"


def arrow(value):
    """▲ for a gain, ▼ for a loss, nothing for zero or unknown: colour never
    works alone (UI plan rule 4)."""
    t = tone(value)
    return "▲" if t == "up" else "▼" if t == "down" else ""


def money(value, ccy="USD"):
    """'$10,453.61', or '10,453.61 EUR' in another account currency."""
    v = _f(value)
    if v is None:
        return DASH
    ccy = (ccy or "USD").upper()
    if ccy == "USD":
        return ("-$" if v < 0 else "$") + "{:,.2f}".format(abs(v))
    return "{:,.2f} {}".format(v, ccy)


def pct(value, places=1):
    v = _f(value)
    return DASH if v is None else ("{:.%df}%%" % places).format(v)


def _figure(value, *, est=False):
    """One P&L figure as the desk prints it: text, tone, arrow, estimate."""
    return {"value": _f(value), "text": signed(value), "tone": tone(value),
            "arrow": arrow(value), "est": bool(est and _f(value) is not None)}


def _age_words(seconds):
    from bot_program.venue_mark import age_words
    return age_words(seconds)


# ── 1. Open P&L by world, never summed ─────────────────────────────────────

def open_worlds(rows, now=None):
    """[{world, n, pnl (a _figure), sub}] for REAL, DEMO and PAPER, in that
    order, over the open rows dashboard.views._live_row built. A world with
    no open row reads "none open"; one whose rows carry no P&L at all is
    unmeasured (the em dash), never 0."""
    now = now or timezone.now()
    out = []
    for world in WORLDS:
        mine = [r for r in rows if (r.get("world") or "") == world]
        vals = [_f(r.get("unrealized_pnl")) for r in mine]
        vals = [v for v in vals if v is not None]
        total = round(sum(vals), 2) if vals else None
        est = any((r.get("pnl_source") or "") == "estimate"
                  and _f(r.get("unrealized_pnl")) is not None for r in mine)
        n = len(mine)
        sub = ("none open" if not n else
               "%d position%s" % (n, "" if n == 1 else "s"))
        if n and est:
            sub = "estimate · " + sub
        # eToro's own figures carry the time eToro's list was read: the
        # oldest of them is how old the REAL figure is.
        ats = [r.get("pnl_at") for r in mine
               if (r.get("pnl_source") or "") == "etoro" and r.get("pnl_at")]
        if ats:
            age = max(0.0, (now - min(ats)).total_seconds())
            sub += " · read %s ago" % _age_words(age)
        out.append({"world": world, "n": n, "pnl": _figure(total, est=est),
                    "sub": sub})
    return out


# ── 2. The book at eToro (REAL only) ───────────────────────────────────────

def _exposure(obj):
    """|qty x price x USD per point per unit| at the row's mark, its entry
    where no mark arrived (the asset breakdown's rule); None unpriceable."""
    qty = _f(getattr(obj, "quantity", None))
    price = _f(getattr(obj, "current_price", None))
    if price is None:
        price = _f(getattr(obj, "entry_price", None))
    if qty is None or price is None:
        return None
    vpu = _f(getattr(obj, "value_per_unit", None)) or 1.0
    return abs(qty * price * vpu)


def _real_risk_at_stops(user, pf):
    """What every REAL stop costs if all fill: each open world-live row
    (OPEN or CLOSE_PENDING, never paper, never the DEMO world) priced as
    the open-risk gate prices it (risk_gate._row_risk: a row with no stop
    risks its whole notional), plus the legacy portfolio.Position rows the
    gate counts on the limits book, never one a REAL row above mirrors.

    The reading bot_program.orcs.sources._live_book makes of the live
    book, row for row, made here: this page imports nothing of the Orcs,
    whose importers are frozen (CI round 1, 2026-11-14:
    tests/orcs/test_orc_o2a_shadow_pins.py). Reads only."""
    from bot_program.models import AssetBotTrade
    from portfolio import risk_gate
    from portfolio.models import Position
    from portfolio.services import value_per_unit
    from .position_summary import WORLD_LIVE, world_of
    total, symbols = 0.0, set()
    for t in AssetBotTrade.objects.filter(
            config__user=user, status__in=("OPEN", "CLOSE_PENDING"),
            paper=False):
        if world_of(t) != WORLD_LIVE:
            continue
        risk, _stopped = risk_gate._row_risk(
            t.qty, t.entry_price, t.stop_loss, t.side, value_per_unit(t))
        total += risk
        symbols.add(str(t.symbol).upper())
    for p in (Position.objects.filter(portfolio=pf, closed_at__isnull=True)
              .select_related("instrument")):
        if str(getattr(p.instrument, "symbol", "")).upper() in symbols:
            continue
        risk, _stopped = risk_gate._row_risk(
            p.quantity, p.entry_price, getattr(p, "stop_loss", None),
            "BUY" if str(p.direction).lower() == "long" else "SELL")
        total += risk
    return total


def _at_the_stops(user):
    """(risk money, its % of the live book, the limit %) of the REAL rows:
    what every REAL stop costs if all fill (_real_risk_at_stops), against
    the live gates' limit and book size. (None, None, None) when nothing
    can be measured; the risk is unknown, as the Orcs read it, while the
    limit or the book size is. Read only: the limits book is never created
    here."""
    try:
        from portfolio import risk_gate
        from portfolio.models import Portfolio
        pf = Portfolio.objects.filter(name="Main").first()
        if pf is None:
            return None, None, None
        limit_pct = risk_gate._limit_pct(pf, "max_open_risk_pct")
        book_v, _src = risk_gate.venue_book_value(user, pf, "live")
        book_v = _f(book_v)
        if limit_pct is None or not book_v or book_v <= 0:
            return None, None, limit_pct
        risk = _real_risk_at_stops(user, pf)
        return risk, risk / book_v * 100.0, limit_pct
    except Exception:  # noqa: BLE001 — the page never fails on a reading
        logger.warning("[desk] the open risk could not be read",
                       exc_info=True)
        return None, None, None


def etoro_book(user, objects, rows, etoro):
    """The REAL book at eToro: equity, exposure, at the stops, margin used.
    `objects` and `rows` are the open book as the page holds it (the same
    order); `etoro` is capital_summary's eToro reading (None without an
    eToro account)."""
    e = etoro or {}
    ccy = (e.get("currency") or "USD")
    live = [(o, r) for o, r in zip(objects, rows)
            if (r.get("world") or "") == "live"]
    exposures = [_exposure(o) for o, _r in live]
    known = [x for x in exposures if x is not None]
    exposure = round(sum(known), 2) if known else None
    risk, share, limit_pct = _at_the_stops(user)
    used, total = _f(e.get("used")), _f(e.get("total"))
    margin = (used / total * 100.0 if used is not None and total and total > 0
              else None)
    read = e.get("total_age_t") or e.get("age_t") or ""
    return {
        "has_account": bool(etoro),
        "equity": money(e.get("total"), ccy) if etoro else DASH,
        "equity_read": read,
        "exposure": money(exposure, ccy),
        "exposure_n": len(live),
        "stops": pct(share, 2),
        "stops_limit": pct(limit_pct, 2) if limit_pct is not None else "",
        "stops_money": signed(-risk if risk is not None else None),
        "stops_over": bool(share is not None and limit_pct is not None
                           and share > limit_pct),
        "margin": pct(margin, 1),
        "margin_used": money(used, ccy),
        "margin_free": money(e.get("available"), ccy),
        "title": e.get("title") or "",
    }


# ── 3. The REAL exposure by class and by side ──────────────────────────────

def real_exposure(objects, rows):
    """{classes: [{name, text, share, share_text}], long, short, total,
    top}: the REAL rows' notional by asset class (largest first) and by
    side, with the largest single position's share. None without a REAL
    row that can be priced."""
    by_class, by_side, by_sym = {}, {"long": 0.0, "short": 0.0}, {}
    for o, r in zip(objects, rows):
        if (r.get("world") or "") != "live":
            continue
        x = _exposure(o)
        if x is None:
            continue
        cls = (r.get("asset_class") or "other").lower()
        by_class[cls] = by_class.get(cls, 0.0) + x
        side = "short" if str(r.get("direction") or "").lower() in (
            "short", "sell") else "long"
        by_side[side] += x
        sym = r.get("symbol") or DASH
        by_sym[sym] = by_sym.get(sym, 0.0) + x
    total = sum(by_class.values())
    if total <= 0:
        return None
    classes = [{"name": k, "text": money(v), "share": round(v / total * 100, 1),
                "share_text": pct(v / total * 100)}
               for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])]
    top_sym, top_v = max(by_sym.items(), key=lambda kv: kv[1])
    return {"classes": classes,
            "long": round(by_side["long"] / total * 100, 1),
            "short": round(by_side["short"] / total * 100, 1),
            "long_text": pct(by_side["long"] / total * 100),
            "short_text": pct(by_side["short"] / total * 100),
            "total": money(total),
            "top": {"symbol": top_sym, "text": pct(top_v / total * 100)}
            if len(by_sym) > 1 else None}


# ── 4. Closed in the last 24 hours ─────────────────────────────────────────

def _by_words(pairs):
    """{trade id: the board's word for how it ended} from the trades'
    own outcome."""
    ids = [getattr(p, "trade_id", None) for p, _d in pairs]
    ids = [i for i in ids if i]
    if not ids:
        return {}
    from bot_program.models import AssetBotTrade
    return {pk: BY_WORDS.get(outcome or "", DASH)
            for pk, outcome in AssetBotTrade.objects.filter(pk__in=ids)
            .values_list("pk", "outcome")}


def closed_recent(pairs, now=None, hours=24):
    """{rows, worlds}: the closes of the last `hours`, newest first, each
    with its world, prices, P&L and R; and the P&L of each world apart
    (never summed), None for a world with no close in the window."""
    from core.price_format import format_price
    now = now or timezone.now()
    since = now - timedelta(hours=hours)
    recent = [(p, d) for p, d in pairs
              if getattr(p, "closed_at", None) and p.closed_at >= since]
    recent.sort(key=lambda pd: pd[0].closed_at, reverse=True)
    by = _by_words(recent)
    rows, sums = [], {w: None for w in WORLDS}
    for p, d in recent:
        d = d or {}
        world = d.get("world") or ""
        inst = getattr(p, "instrument", None)
        sym = getattr(inst, "symbol", "") or ""
        cls = getattr(inst, "asset_class", "") or ""
        pnl = _f(getattr(p, "unrealized_pnl", None))
        if world in sums and pnl is not None:
            sums[world] = (sums[world] or 0.0) + pnl
        short = str(getattr(p, "direction", "") or "").lower() in ("short",
                                                                   "sell")
        r = d.get("realized_r") or ""
        rows.append({
            "symbol": sym, "short": short, "world": world,
            "entry": format_price(getattr(p, "entry_price", None), cls, sym),
            "exit": format_price(getattr(p, "current_price", None), cls, sym),
            "pnl": _figure(pnl),
            "r": (r + "R") if r else DASH,
            "r_tone": tone(r),
            "by": by.get(getattr(p, "trade_id", None), DASH),
            "href": d.get("href") or "",
        })
    worlds = [{"world": w, "pnl": _figure(None if sums[w] is None
                                          else round(sums[w], 2))}
              for w in WORLDS]
    return {"rows": rows, "worlds": worlds}


# ── 5. Closed in 30 days, by world ─────────────────────────────────────────

def closed_by_world(pairs, now=None, days=30):
    """[{world, n, graded, won, r, pf}] per world over the closes of the
    last `days`: n counts every close, the rates read only the graded ones
    (a close nothing could price is held out, not counted as a loss), and
    a world with fewer than MIN_GRADED graded closes prints dashes."""
    now = now or timezone.now()
    since = now - timedelta(days=days)
    out = []
    for world in WORLDS:
        mine = [(p, d or {}) for p, d in pairs
                if (d or {}).get("world") == world
                and getattr(p, "closed_at", None) and p.closed_at >= since]
        pnls = [_f(getattr(p, "unrealized_pnl", None)) for p, _d in mine]
        graded = [v for v in pnls if v is not None]
        rs = [_f(d.get("realized_r")) for _p, d in mine]
        rs = [v for v in rs if v is not None]
        wins = sum(v for v in graded if v > 0)
        losses = -sum(v for v in graded if v < 0)
        enough = len(graded) >= MIN_GRADED
        won = (sum(1 for v in graded if v > 0) / len(graded) * 100.0
               if enough else None)
        r_mean = (sum(rs) / len(rs)) if enough and rs else None
        pf = (wins / losses) if enough and losses > 0 and wins > 0 else None
        out.append({"world": world, "n": len(mine), "graded": len(graded),
                    "enough": enough,
                    "won": pct(won, 0) if won is not None else DASH,
                    "r": (signed(r_mean) + "R") if r_mean is not None else DASH,
                    "r_tone": tone(r_mean),
                    "pf": "{:.2f}".format(pf) if pf is not None else DASH})
    return out


# ── 6. The figure columns, as wide as their figures ────────────────────────

#: The least a figure column holds, in characters of the number face: a
#: forex quantity, a price at five digits, a P&L with its arrow's slot, an R,
#: a level. A column grows past it only when a figure on the book needs it.
COL_FLOOR = {"sym": 6, "qty": 6, "px": 8, "pnl": 9, "r": 6, "lvl": 8}
#: The sheet sizes columns from 4 to this many characters.
COL_CEIL = 20


def _chars(text):
    return len(str(text or ""))


def figure_columns(rows):
    """{sym, qty, px, pnl, r, lvl}: each figure column's width in characters
    of the number face (static/css/sv-positions.css turns them into widths,
    `ch` of JetBrains Mono at the row's size tier), from the widest figure
    the book prints in it. The P&L counts its arrow's two-character slot and
    an estimate's ≈ with its half space. Fixed pixel widths were the review's
    blocker (2026-11-13): the size tiers raise the cells to 14 and 15 px and
    the figures were cut mid-number."""
    from core.price_format import format_price
    from core.templatetags.sauron_tags import qty as qty_text
    w = dict(COL_FLOOR)
    for r in rows:
        cls, sym = r.get("asset_class") or "", r.get("symbol") or ""

        def px(value):
            return format_price(value, cls, sym) if value is not None else ""
        w["sym"] = max(w["sym"], _chars(sym))
        w["qty"] = max(w["qty"], _chars(qty_text(r.get("quantity"))))
        w["px"] = max(w["px"], _chars(px(r.get("entry_price"))),
                      _chars(r.get("last_text")))
        if r.get("unrealized_pnl") is not None:
            est = (r.get("pnl_source") or "") == "estimate"
            w["pnl"] = max(w["pnl"], _chars(r.get("pnl_text")) + 2 + (2 if est else 0))
        if r.get("r_multiple") is not None:
            w["r"] = max(w["r"], _chars(r.get("r_text")))
        w["lvl"] = max(w["lvl"], _chars(px(r.get("stop_loss"))),
                       _chars(px(r.get("take_profit"))))
    return {k: min(v, COL_CEIL) for k, v in w.items()}


# ── 7. The closed book by world (the history tab) ──────────────────────────

#: The history strip's keys (the refresh's): REAL keeps the names the strip
#: always had, DEMO and PAPER take theirs with the world's suffix.
CLOSED_KEYS = ("closed", "closed.sub", "win_rate", "realized", "profit_factor",
               "avg_wl")


def closed_book(pairs):
    """[{world, keys, closed, won, realized (a _figure), pf, avg_wl, title}]
    for REAL, DEMO and PAPER apart: every close of the world, its booked
    P&L, and its rates from MIN_GRADED graded closes (fewer print the count
    and a dash, as the open tab's 30 days do). Never two worlds added: the
    review of 2026-11-13 found the history strip summing the three into one
    "realized P&L" that read as real money."""
    out = []
    for world in WORLDS:
        mine = [p for p, d in pairs if (d or {}).get("world") == world]
        graded = [_f(getattr(p, "unrealized_pnl", None)) for p in mine]
        graded = [v for v in graded if v is not None]
        wins = [v for v in graded if v > 0]
        losses = [v for v in graded if v < 0]
        enough = len(graded) >= MIN_GRADED
        gross_w, gross_l = sum(wins), -sum(losses)
        won = (len(wins) / len(graded) * 100.0) if enough else None
        pf = (gross_w / gross_l) if enough and wins and gross_l > 0 else None
        realized = round(sum(graded), 2) if graded else None
        avg_w = signed(gross_w / len(wins)) if wins else DASH
        avg_l = signed(-gross_l / len(losses)) if losses else DASH
        suffix = "" if world == "live" else "." + world
        out.append({
            "world": world,
            "keys": {k.replace(".", "_"): "pos.%s%s" % (k, suffix)
                     for k in CLOSED_KEYS},
            "closed": str(len(mine)),
            "wl": "%dW / %dL" % (len(wins), len(losses)),
            "min_graded": MIN_GRADED,
            "won": pct(won, 0) if won is not None else DASH,
            "realized": _figure(realized),
            "pf": "{:.2f}".format(pf) if pf is not None else DASH,
            "avg_wl": "%s / %s" % (avg_w, avg_l),
            "title": ("%d closed, %d of them graded; a close nothing could "
                      "price is held out, never booked as a loss. Rates from "
                      "%d graded closes." % (len(mine), len(graded), MIN_GRADED)),
        })
    return out


# ── The whole desk ─────────────────────────────────────────────────────────

def desk(user, objects, rows, closed_pairs, etoro, now=None):
    """Everything the board draws around the open table, for the template."""
    now = now or timezone.now()
    counts = {w: sum(1 for r in rows if (r.get("world") or "") == w)
              for w in WORLDS}
    return {
        "worlds": open_worlds(rows, now=now),
        "book": etoro_book(user, objects, rows, etoro),
        "exposure": real_exposure(objects, rows),
        "closed_24h": closed_recent(closed_pairs, now=now),
        "closed_30d": closed_by_world(closed_pairs, now=now),
        "counts": counts,
        "n_open": len(rows),
        "min_graded": MIN_GRADED,
        # A RETRY CLOSE on the book: the CLOSE column takes its longer word.
        "retry": any((r.get("status") or "") == "CLOSE_PENDING" for r in rows),
        "words": _shown_words(),
        "cols": figure_columns(rows),
    }


def empty_desk(rows=()):
    """The desk when its figures cannot be read (contract review F4,
    2026-11-13): every figure the em dash, the table's columns at their
    floor, so the page the operator closes from still renders, CLOSE
    included. Display only, like the rest."""
    blank = _figure(None)
    return {
        "worlds": [{"world": w, "n": 0, "pnl": blank, "sub": DASH} for w in WORLDS],
        "book": {"has_account": False, "equity": DASH, "equity_read": "",
                 "exposure": DASH, "exposure_n": 0, "stops": DASH,
                 "stops_limit": "", "stops_money": DASH, "stops_over": False,
                 "margin": DASH, "margin_used": DASH, "margin_free": DASH,
                 "title": ""},
        "exposure": None,
        "closed_24h": {"rows": [], "worlds": [{"world": w, "pnl": blank} for w in WORLDS]},
        "closed_30d": [{"world": w, "n": DASH, "graded": 0, "enough": False,
                        "won": DASH, "r": DASH, "r_tone": "", "pf": DASH}
                       for w in WORLDS],
        "counts": {w: 0 for w in WORLDS},
        "n_open": len(rows),
        "min_graded": MIN_GRADED,
        "retry": any((r.get("status") or "") == "CLOSE_PENDING" for r in rows),
        "words": "",
        "cols": dict(COL_FLOOR),
    }


def _shown_words():
    from .views import SHOWN_PNL_WORDS
    return SHOWN_PNL_WORDS
