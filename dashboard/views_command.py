"""Operations Center — unified tabbed view (renamed from Command Center).

Replaces the old "Dashboard" + "Sauron's Eye" + "Command Center" layout
with a single richer page split into 4 tabs:

  LIVE       — current Eye content + brain regime + gate ratio + recent fills
  PORTFOLIO  — equity curve + allocation donut + Sharpe + winners/losers
  HISTORY    — cumulative R curve + rolling win-rate + DoW heatmap + per-rule
  BOTS       — per-bot today's stats + heartbeat + cooldown countdown

Every tab head also displays a LIVE metric so the tab bar itself is a
mini-dashboard (LIVE shows "1 REAL OPEN · +10.00 USD", BOTS "5/8 ON").

WebSocket: tabs subscribe to typed events on the existing /ws/eye/ feed
so live updates push (no polling).

TRUTH AND COST (2026-11-07, the Operations Center spec, OC0). The page
added REAL, DEMO and PAPER money together, printed an eToro DEMO row as
REAL MONEY, called the average win over the average loss a profit factor,
printed money with no currency and quantities with eight decimals, and
walked the open book three times per request while every tab paid for the
shell. Now:
  * one open-book walk per request (`_book_walk`): `shown_open_rows`,
    `live_book_value(book=…)` and `shown_book(venues=…)` are handed the walk
    the caller holds. `_open_book`, `_reprice_legacy` and `live_book_value`
    themselves are NOT edited: `live_book_value` feeds
    `Portfolio.current_value`, the paper limits' denominator;
  * the worlds are the rows' split (`position_summary.open_by_world` over
    the rows walked, each bot row's world from its trade's own stamps by
    `world_of`), never `_panel_detail`, and never added;
  * the closed history is read as database aggregates grouped by the rows'
    stamps, `world_of` applied to each group in Python (one world rule);
  * the fragments are rendered with `render_to_string` and no request, so
    the shell's context processors no longer run on them;
  * every dash carries its reason (core/templatetags/oc_dash.py).
Display only. No broker call and no model call is made to draw the page.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Max, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

# An em-dash means NOT MEASURED. A metric that cannot be computed must never
# fall back to 0 or to an empty span: a confident "+0.00" reads as "flat" and
# a blank reads as "broken page", and this tab bar has been doing both.
DASH = "—"

#: The money worlds, REAL first, never added (position_summary.world_of's
#: keys; "" is a row that states no venue: a hand-recorded Position).
WORLDS = ("live", "demo", "paper")
WORLD_NAME = {"live": "REAL", "demo": "DEMO", "paper": "PAPER",
              "": "NO VENUE"}

#: What a dash means, cell by cell (the spec's §5.7, in the page's words).
#: Each dash on the page carries one of these as its title, and the foot of
#: the page lists the ones drawn (core/templatetags/oc_dash.py).
WHY = {
    "no_live_open": "no REAL position open",
    "no_demo_open": "no DEMO position open",
    "no_paper_open": "no PAPER position open",
    "no_none_open": "no position recorded by hand is open",
    "unmarked": "not measured: open, but no price marks it",
    "nothing_live_24h": "nothing closed in the REAL world in 24 h",
    "nothing_demo_24h": "nothing closed in the DEMO world in 24 h",
    "nothing_paper_24h": "nothing closed in the PAPER world in 24 h",
    "nothing_24h": "nothing closed in 24 h",
    "nothing_90d": "nothing closed in 90 d",
    "nothing_closed": "nothing closed in this world yet",
    "no_win": "no winning close in this world yet",
    "no_loss": "no losing close in this world yet: a profit factor and a "
               "payoff need one",
    "snapshot_today": "not yet: today's snapshot is written at 23:30 UTC",
    "snapshot_none": "not yet: no daily snapshot to measure from",
    "snapshot_few": "not yet: Sharpe and Sortino need 5 or more daily "
                    "snapshots in 30 days",
    "ungraded": "closed with no R: no opening stop was recorded",
    "gate_not_asked": "the gate was not asked in 24 h",
    "no_stop": "no stop recorded: no R, not a zero",
    "no_target": "no target recorded",
    "no_weekday": "no close on this weekday in the window",
    "no_close_path": "no close path exists for a row recorded by hand",
    "no_close_path_bot": "no close path exists for the old crypto bot's rows",
    "no_price": "no live price for this row yet",
    "not_measured": "not measured: a source could not be read",
    "no_report": "not yet: the brain has written no report",
    "no_trust": "not measured: no graded brain call yet",
    "staff_only": "staff only",
    "no_rule": "no rule name: taken by hand or by the bots' consensus",
    "no_outcome": "no outcome recorded for this close",
    "no_cooldown": "none: no cooldown is running",
    "no_tick": "never ticked: no heartbeat recorded",
    "no_configs": "none: no bot is configured",
    "no_pct": "no percentage: the entry or the price is missing",
    "first_poll": "not yet: the first reading arrives within a minute",
    "rule_unread": "not measured: the rule-control table could not be read",
    "no_equity": "not yet: no snapshot to draw the curve from",
}

#: The platform book's words (2026-11-07): what PORTFOLIO VALUE always was.
BOOK_WORDS = ("cash typed on /setup/ ({ccy}) + the REAL and DEMO positions' "
              "notional (USD, hand-recorded rows too) + paper's open and "
              "realized P&L, not converted; not a balance")


# ── Helpers ──────────────────────────────────────────────────────────────

def _smart_default_tab(user, enabled=None) -> str:
    """If the user has any enabled bot configs → LIVE; else → PORTFOLIO.
    `enabled` is the count when the caller already read it."""
    if enabled is not None:
        return "live" if enabled else "portfolio"
    try:
        from bot_program.models import AssetBotConfig
        if AssetBotConfig.objects.filter(user=user, enabled=True).exists():
            return "live"
    except Exception as e:
        logger.warning("Op Center default-tab probe failed: %s", e)
    return "portfolio"


def _tone(value) -> str:
    """Colour class for a signed reading; blank for zero and for unknown."""
    if value is None:
        return ""
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return ""


def _money(value, ccy="USD", *, signed=True, estimate=False):
    """position_summary.money, with "≈ " in front of an estimate: two
    decimals and the currency on every money cell, never cut to units."""
    from dashboard.position_summary import money
    text = money(value, ccy, signed=signed)
    return ("≈ " + text) if (estimate and text != DASH) else text


def _ago(seconds) -> str:
    from dashboard.views_day import _ago as ago
    return ago(seconds)


def _fill_card(trade):
    """A closed trade, shaped the way the best/worst cards read it.

    Those cards ask for `.config.symbol` and `.config.rule_name`, and
    AssetBotConfig has neither — it holds a `symbols` LIST, and rule_name is
    a column on the trade. Both cards therefore rendered a real R multiple
    above a blank symbol and an em-dash rule, which reads as a data outage
    rather than a template mistake.
    """
    if trade is None:
        return None
    from dashboard.position_summary import world_of
    return {
        "config": {"symbol": trade.symbol, "rule_name": trade.rule_name},
        "realized_r": trade.realized_r,
        "outcome": (trade.outcome or "").replace("_", " "),
        "closed_at": trade.closed_at,
        # The world chip and the date (2026-11-07): an R from any world,
        # said so, and an "H:i" with no day read as today.
        "world": world_of(trade),
    }


def _open_book(user, portfolio):
    """The open position book — BOTH halves — priced from live marks.

    Exposure lives in two places on this platform: legacy portfolio.Position
    (Setup form, NL trader, eToro sync) and bot_program.AssetBotTrade (the
    bots, TAKE TRADE, the LONG/SHORT buttons). The LIVE tab head counted only
    the first, so an operator holding three bot trades read "0 OPEN" while
    the headband immediately above it counted all three. The union is the
    platform's own `unified_open_positions`, the same read the positions
    pages use.

    P&L comes from a live quote and never from Position.unrealized_pnl. That
    column defaults to 0 and its only writer is an hourly task that marks the
    SHARED "Main" portfolio, so on the per-user book this page reads it is a
    permanent, confident +0.00.

    Returns (rows, n_priced, unrealized, deployed). Legacy rows come back
    re-priced IN MEMORY — the tab head and the table underneath it must not
    be able to quote two different P&Ls for the same position. unrealized and
    deployed are None when nothing could be priced: an unpriced book is
    unknown, not flat.
    """
    from portfolio.services import notional_usd, unified_open_positions

    rows = unified_open_positions(user, portfolio)
    if not rows:
        return [], 0, None, None

    # Bot rows arrive already marked by portfolio.services (None where no
    # quote exists). Legacy Position rows carry the dead column, so they are
    # re-priced here against the same LiveQuote table the bot rows used.
    _reprice_legacy([r for r in rows if getattr(r, "source", "") != "bot"])

    n_priced = 0
    unrealized = 0.0
    deployed = 0.0
    for r in rows:
        if r.unrealized_pnl is None or r.current_price is None:
            continue
        # notional_usd: price x quantity x the row's USD-per-unit, so a
        # yen-quoted row is deployed dollars, not deployed yen.
        notional = notional_usd(r)
        if notional is None:
            continue
        unrealized += float(r.unrealized_pnl)
        deployed += notional
        n_priced += 1

    if n_priced == 0:
        return rows, 0, None, None
    return rows, n_priced, round(unrealized, 2), round(deployed, 2)


def _reprice_legacy(legacy) -> None:
    """Re-price legacy portfolio.Position rows IN MEMORY against LiveQuote —
    _open_book's own legacy loop, named so the Horde (dashboard/horde.py)
    marks a legacy seat exactly as this book does without reading the
    union a second time. One LiveQuote read by instrument_id; nothing is
    saved. A row with no quote, or a forex row whose quote currency has
    no readable USD rate, is unpriced (None), never its entry price."""
    from market_data.models import LiveQuote
    from portfolio.services import usd_per_unit

    if not legacy:
        return
    quotes = {}
    ids = {r.instrument_id for r in legacy
           if getattr(r, "instrument_id", None)}
    if ids:
        quotes = {q.instrument_id: q for q in
                  LiveQuote.objects.filter(instrument_id__in=ids)}

    # One rate read per quote CURRENCY for the whole pass: three yen rows
    # read the yen once (the Horde re-prices on every poll).
    rates = {}
    for r in legacy:
        quote = quotes.get(getattr(r, "instrument_id", None))
        mark = (float(quote.last)
                if quote is not None and quote.last is not None else None)
        r.mark_source = "quote" if mark is not None else None
        # NO FALLBACK to the row's stored `current_price`, tempting as it is.
        # It has two writers with two different meanings: the eToro sync puts
        # the broker's real `currentRate` there, but the /setup/ form writes
        # entry_price into it verbatim. A blanket fallback would therefore
        # launder entry cost into a figure labelled "current value" for every
        # hand-entered row — the exact claim this book refuses to make.
        # The broker's marks are fixed where they are made instead: the eToro
        # adapter now writes a LiveQuote beside the Position, so a real mark
        # reaches this table the same way every other real mark does.
        if mark is None:
            # Never saved: this is a display re-price, and writing it back
            # would put an unmarked guess into the book the snapshot task
            # reads.
            r.current_price = None
            r.unrealized_pnl = None
            r.unrealized_pnl_pct = None
            continue
        # The quote currency's worth in USD (2026-10-04): a legacy USDJPY
        # row's (mark - entry) x qty is YEN. Without a readable rate the
        # row is unpriced — a number this book cannot measure is left out,
        # never counted at 1.
        mult = usd_per_unit(r, rates)
        if mult is None:
            r.mark_source = None
            r.current_price = None
            r.unrealized_pnl = None
            r.unrealized_pnl_pct = None
            continue
        r.value_per_unit = mult
        entry = float(r.entry_price or 0)
        qty = float(r.quantity or 0)
        sign = -1 if (r.direction or "").lower() in ("short", "sell") else 1
        r.current_price = mark
        r.unrealized_pnl = round((mark - entry) * qty * sign * mult, 2)
        r.unrealized_pnl_pct = (round((mark - entry) / entry * 100 * sign, 2)
                                if entry else None)


def _shown_book_or(user, book, venues=None):
    """portfolio.services.shown_book, fenced (2026-11-06): the book value
    as the pages print it, or live_book_value's own when it cannot be read
    — the cell renders either way."""
    try:
        from portfolio.services import shown_book
        return shown_book(user, book, venues)
    except Exception as e:  # noqa: BLE001 — the marks' value stands
        logger.warning("Op Center: the shown book value is unreadable, the "
                       "marks' stands: %s", e, exc_info=True)
        return book


# ── One walk of the open book per request (2026-11-07, OC0) ──────────────

#: The walk failed this request (logged once): every reader prints dashes
#: rather than walking a second time.
_FAILED = object()


def _open_stamps(user, rows):
    """{trade id: (world, the currency its marks are in)} for the open bot
    rows among `rows`, from one read of the trades' own stamps.

    The world is world_of on the TRADE (paper, the broker, its world) —
    the unified row carries no metadata, and read off the row an eToro
    DEMO fill was "live". The currency is position_summary's: a forex row
    opened before value_per_unit was stamped is marked in its quote
    currency, never in dollars."""
    from types import SimpleNamespace
    from bot_program.models import AssetBotTrade
    from dashboard.position_summary import _unconverted_ccy, world_of
    ids = [getattr(r, "trade_id", None) for r in rows
           if getattr(r, "source", "") == "bot"
           and getattr(r, "trade_id", None)]
    if not ids:
        return {}
    out = {}
    for tid, paper, meta, cls, sym in (
            AssetBotTrade.objects.filter(id__in=ids)
            .values_list("id", "paper", "metadata", "asset_class", "symbol")):
        meta = meta if isinstance(meta, dict) else {}
        world = world_of({"paper": paper, "metadata": meta})
        raw = _unconverted_ccy(SimpleNamespace(asset_class=cls, metadata=meta,
                                               symbol=sym), "USD")
        out[tid] = (world, raw or "USD")
    return out


def _book_walk(user):
    """The open book, walked ONCE for the request, and everything the page
    reads off it.

    `_open_book` (the union, marked) once; `live_book_value` handed that
    walk (`book=`), as PORTFOLIO always did; `shown_open_rows` the display
    copies (eToro's own P&L on an eToro row its holdings list) and
    `shown_book` handed their answers (`venues=`). None of the three is
    edited: they are what the gates and the stored book read.

    Each row's world is its trade's (world_of), and the worlds are the
    rows' split (position_summary.open_by_world) — the band's own rule, so
    the hero's three lines equal the band's (`_book_truth`). Never added."""
    from dashboard.position_summary import open_by_world, world_of
    from portfolio.services import (get_or_create_default_portfolio,
                                    live_book_value, notional_usd,
                                    shown_open_rows)
    portfolio = get_or_create_default_portfolio(user=user)
    union = _open_book(user, portfolio)
    rows = union[0]
    book = live_book_value(user, portfolio, book=union)
    shown, venues = shown_open_rows(user, rows)
    shown_value = _shown_book_or(user, book, venues)
    stamps = _open_stamps(user, rows)
    entries = []
    for row in shown:
        bot = getattr(row, "source", "") == "bot"
        tid = getattr(row, "trade_id", None)
        world, ccy = stamps.get(tid, ("", "USD")) if bot else ("", "USD")
        if bot and not world:
            world = world_of(row)
        venue = getattr(row, "venue_pnl", None)
        pnl = getattr(row, "unrealized_pnl", None)
        tier = ""
        if pnl is not None:
            tier = (venue or {}).get("source") or "estimate"
        if venue and venue.get("ccy") == "USD":
            ccy = "USD"
        notional = None
        if getattr(row, "current_price", None) is not None:
            try:
                notional = notional_usd(row)
            except Exception:  # noqa: BLE001 — unmeasured, never 0
                notional = None
        entries.append({
            "row": row, "world": world, "bot": bot, "trade_id": tid,
            "pnl": None if pnl is None else float(pnl), "tier": tier,
            "ccy": ccy, "notional": notional,
            # As the band hands them to open_by_world: a figure that is
            # eToro's own (or its quote's side) is no stale venue print.
            "mark_source": (venue["source"] if venue and venue.get("source")
                            not in (None, "estimate")
                            else getattr(row, "mark_source", None)),
            "mark_age_s": getattr(row, "mark_age_s", None),
        })
    split = open_by_world([{"world": e["world"], "pnl": e["pnl"], "r": None,
                            "mark_source": e["mark_source"],
                            "mark_age_s": e["mark_age_s"]} for e in entries])
    return {"portfolio": portfolio, "union": union, "rows": rows,
            "shown": shown, "venues": venues, "book": book,
            "shown_value": shown_value, "entries": entries, "split": split,
            "n_open": len(rows), "n_priced": union[1]}


def _safe_walk(user):
    """_book_walk, or _FAILED (logged) — the page renders either way."""
    try:
        return _book_walk(user)
    except Exception as e:  # noqa: BLE001 — every cell prints its dash
        logger.warning("Op Center open book unavailable: %s", e, exc_info=True)
        return _FAILED


def _world_lines(walk):
    """REAL, DEMO and PAPER apart, each the sum of its own rows: the open
    P&L in its tier's words (an estimate starts with ≈), the rows it
    covers, its title; never added. Jade and coral only for a figure that
    is eToro's own on every row (spec §5.3); an estimate is ink."""
    from dashboard.position_summary import live_book_words
    split, entries = walk["split"], walk["entries"]
    stale = live_book_words(split)["stale_words"]
    lines = {}
    for w in WORLDS:
        slot = split[w]
        n = slot["n"]
        marked = [e for e in entries if e["world"] == w
                  and e["pnl"] is not None]
        own = bool(marked) and all(e["tier"] == "etoro" for e in marked)
        others = sorted({e["ccy"] for e in marked} - {"USD"})
        why = ""
        if not n:
            text, why = DASH, WHY[f"no_{w}_open"]
        elif slot["pnl"] is None:
            text, why = DASH, WHY["unmarked"]
        else:
            text = _money(slot["pnl"], "USD", estimate=not own)
        words = [f"{n} open"] if n else []
        if marked and len(marked) < n:
            words.append(f"{len(marked)} of {n} marked")
        if marked:
            words.append("eToro's own" if own else "estimate")
        if others:
            words.append(f"includes {', '.join(others)} not converted")
        if w == "live" and stale:
            words.append(stale)
        title = why or (
            f"{WORLD_NAME[w]}'s open P&L, the sum of its own rows "
            f"({len(marked)} of {n} marked): "
            + ("eToro's own figure on every row." if own else
               "an estimate from the platform's marks, eToro's own figure "
               "on a row its holdings list.")
            + (f" {', '.join(others)} rows are in their quote currency, "
               f"not converted." if others else "")
            + " Never added to the other worlds.")
        lines[w] = {"n": n, "pnl": slot["pnl"], "text": text, "why": why,
                    "words": " · ".join(words), "title": title,
                    "tone": _tone(slot["pnl"]) if own else ""}
    lines[""] = {"n": split[""]["n"], "pnl": split[""]["pnl"]}
    return lines


def _head_facts(user, walk):
    """The counts the heads and the hero share, read once: the configs
    (all, enabled, enabled in live mode) and the snapshots of today and
    yesterday. Fenced: a failure is a dash, logged."""
    from bot_program.models import AssetBotConfig
    from portfolio.models import PortfolioSnapshot
    facts = {"cfg": None, "snaps": None, "today": timezone.localdate()}
    try:
        facts["cfg"] = AssetBotConfig.objects.filter(user=user).aggregate(
            n=Count("id"), on=Count("id", filter=Q(enabled=True)),
            live_on=Count("id", filter=Q(enabled=True, mode="live")))
    except Exception as e:  # noqa: BLE001
        logger.warning("Op Center configs unavailable: %s", e, exc_info=True)
    try:
        if walk is not _FAILED and walk is not None:
            portfolio = walk["portfolio"]
        else:
            from portfolio.services import get_or_create_default_portfolio
            portfolio = get_or_create_default_portfolio(user=user)
        today = facts["today"]
        facts["snaps"] = {
            d: pct for d, pct in PortfolioSnapshot.objects.filter(
                portfolio=portfolio,
                date__in=(today, today - timedelta(days=1)))
            .values_list("date", "daily_pnl_pct")}
    except Exception as e:  # noqa: BLE001
        logger.warning("Op Center snapshots unavailable: %s", e,
                       exc_info=True)
    return facts


def _world_stamps():
    """The two stamps world_of reads off a trade's metadata, as annotations
    for a grouped read (`w_broker`, `w_env`); the world is world_of's,
    applied to each group in Python, never a second rule in SQL. A paper
    row is paper whatever its stamps (world_of reads the flag first), so
    its JSON is not parsed: a fifth of the lifetime read at six months."""
    from django.db.models import Case, CharField, Value, When
    from django.db.models.fields.json import KeyTextTransform

    def stamp(key):
        return Case(When(paper=True, then=Value(None)),
                    default=KeyTextTransform(key, "metadata"),
                    output_field=CharField())
    return {"w_broker": stamp("broker"), "w_env": stamp("broker_env")}


def _realized_24h_by_world(user):
    """{world: {currency: (pnl or None, n)}} for the closes of the last 24
    hours: one read grouped by the rows' stamps and the config's currency,
    world_of applied to each group (never a second rule in SQL)."""
    from bot_program.models import AssetBotTrade
    from dashboard.position_summary import world_of
    since = timezone.now() - timedelta(hours=24)
    out = {}
    for r in (AssetBotTrade.objects
              .filter(config__user=user, status="CLOSED", closed_at__gte=since)
              .annotate(**_world_stamps())
              .values("paper", "w_broker", "w_env", "config__base_currency")
              .annotate(s=Sum("pnl"), n=Count("id"), m=Count("pnl"))
              .order_by()):
        world = world_of({"paper": r["paper"],
                          "metadata": {"broker": r["w_broker"],
                                       "broker_env": r["w_env"]}})
        ccy = (r["config__base_currency"] or "USD").strip().upper()
        pnl, n = out.setdefault(world, {}).get(ccy, (None, 0))
        if r["m"]:
            pnl = (pnl or 0.0) + float(r["s"] or 0)
        out[world][ccy] = (pnl, n + r["n"])
    return out


def _realized_text(by_ccy):
    """One world's realized money, each currency apart: "+10.00 USD"."""
    parts = [_money(round(pnl, 2), ccy) for ccy, (pnl, _n) in
             sorted(by_ccy.items()) if pnl is not None]
    return " · ".join(parts) if parts else DASH


def _tab_bar_metrics(user, walk=None, facts=None) -> dict:
    """The small metric under each tab head.

    Every value is a pre-formatted string, `tone` is the colour class, and
    `title` is the tooltip — a four-character number cannot say which book it
    counted or how many of its rows it could actually price, and the operator
    has to be able to ask.

    REAL FIRST, NEVER ADDED (2026-11-07, OC0): the LIVE head reads "N REAL
    OPEN" over REAL's own open P&L, with every world in its title and the
    count of all of them beside it (`n_open`); the BOTS head reads REAL's
    realized 24 h. The heads summed REAL, DEMO and PAPER ("11 OPEN
    +198.31") while the band beside them split the three.

    Previously each block ended in `except Exception: pass` over a dict whose
    secondaries defaulted to the EMPTY STRING, so a metric that failed left a
    blank span rather than an em-dash: three of the four tab heads rendered
    nothing at all on an install with no snapshots, which looks exactly like
    a broken page and was reported as one.
    """
    out = {
        key: {"primary": DASH, "secondary": DASH, "tone": "", "title": "",
              # The reason each dash gives, read by its cell's title and
              # carried on every poll (2026-11-07, OC0).
              "primary_title": WHY["not_measured"],
              "secondary_title": WHY["not_measured"]}
        for key in ("live", "portfolio", "history", "bots")
    }
    out["live"].update(n_open=None, worlds={})
    if walk is None:
        walk = _safe_walk(user)
    if facts is None:
        facts = _head_facts(user, walk)

    # ── LIVE: REAL first, a count of every world beside it ───────────
    if walk is not _FAILED:
        try:
            split, lines = walk["split"], _world_lines(walk)
            n_open = walk["n_open"]
            live = out["live"]
            live["n_open"] = n_open
            live["worlds"] = {w: {"n": split[w]["n"], "pnl": split[w]["pnl"]}
                              for w in WORLDS + ("",)}
            live["primary"] = f"{split['live']['n']} REAL OPEN"
            live["primary_title"] = (
                "Open positions on REAL money; every world is counted in "
                "this head's title.")
            live["secondary"] = lines["live"]["text"]
            live["secondary_title"] = (lines["live"]["why"]
                                       or lines["live"]["title"])
            live["tone"] = lines["live"]["tone"]
            counts = " · ".join(
                [f"{split[w]['n']} {WORLD_NAME[w].lower()}" for w in WORLDS]
                + ([f"{split['']['n']} no venue"] if split[""]["n"] else []))
            money = "; ".join(
                f"{WORLD_NAME[w]} {lines[w]['text']}"
                + (f" ({lines[w]['why']})" if lines[w]["why"] else "")
                for w in WORLDS)
            live["title"] = (
                f"{n_open} open, all worlds: {counts}. Open P&L, each world "
                f"apart and never added: {money}. {walk['n_priced']} of "
                f"{n_open} open positions priced." if n_open else
                "0 open, all worlds: no open position in either book.")
        except Exception as e:
            logger.warning("Op Center LIVE metric unavailable: %s", e,
                           exc_info=True)

    # ── PORTFOLIO: the platform book + TODAY's snapshot delta ─────────
    if walk is not _FAILED:
        try:
            from portfolio.services import SHOWN_VALUE_WORDS
            book, shown = walk["book"], walk["shown_value"]
            portfolio = walk["portfolio"]
            ccy = (portfolio.currency or "").upper()
            # The platform's book, NOT a balance, in mixed currencies and
            # never converted: two decimals and no currency sign (OC0).
            out["portfolio"]["primary"] = (
                DASH if shown.value is None else f"{shown.value:,.2f}")
            out["portfolio"]["primary_title"] = (
                WHY["not_measured"] if shown.value is None else
                "The platform's book, not a balance, in mixed currencies, "
                "never converted.")
            out["portfolio"]["secondary_title"] = WHY["snapshot_today"]
            today = facts["today"]
            pct = (facts["snaps"] or {}).get(today)
            mixed = f"{ccy} + USD, not converted" if ccy not in ("", "USD") \
                else "USD"
            head = (f"{portfolio.name}: the platform's book ({mixed}): "
                    f"{BOOK_WORDS.format(ccy=ccy or 'its currency')}. "
                    f"{SHOWN_VALUE_WORDS} {book.coverage}")
            if pct is not None:
                out["portfolio"]["secondary"] = f"{float(pct):+.2f}%"
                out["portfolio"]["secondary_title"] = (
                    f"Day change from the {today} snapshot.")
                out["portfolio"]["tone"] = _tone(float(pct))
                out["portfolio"]["title"] = (
                    f"{head} Day change from today's snapshot.")
            else:
                out["portfolio"]["title"] = (
                    f"{head} No snapshot for {today} yet, so the day change "
                    f"is not measured: {WHY['snapshot_today']}.")
        except Exception as e:
            logger.warning("Op Center PORTFOLIO metric unavailable: %s", e,
                           exc_info=True)

    # ── HISTORY: 90-day W/L count + avg R (R only, all worlds) ────────
    try:
        from bot_program.models import AssetBotTrade
        # 90 days, not 30: this is the head of a tab whose body is a 90-day
        # analysis, and a head that summarises a different window than the
        # body it labels sends the operator looking for the discrepancy.
        cutoff = timezone.now() - timedelta(days=90)
        agg = AssetBotTrade.objects.filter(
            config__user=user, status="CLOSED", closed_at__gte=cutoff
        ).aggregate(n=Count("id"), graded=Count("realized_r"),
                    wins=Count("id", filter=Q(realized_r__gt=0)),
                    losses=Count("id", filter=Q(realized_r__lt=0)),
                    avg_r=Avg("realized_r"))
        n_closed, n_graded = agg["n"] or 0, agg["graded"] or 0
        why = WHY["ungraded"] if n_closed else WHY["nothing_90d"]
        out["history"]["primary_title"] = out["history"]["secondary_title"] = why
        if n_graded:
            avg_r = agg["avg_r"] or 0
            out["history"]["primary_title"] = "Graded wins and losses, 90 d."
            out["history"]["secondary_title"] = "The average R, 90 d, all worlds."
            out["history"]["primary"] = f"{agg['wins']}W·{agg['losses']}L"
            out["history"]["secondary"] = f"{avg_r:+.2f}R"
            out["history"]["tone"] = _tone(avg_r)
            out["history"]["title"] = (
                f"90 d · all worlds · R only. Bot trades closed in 90 days: "
                f"{n_graded} of {n_closed} carry an R grade and are counted "
                f"here.")
        else:
            out["history"]["title"] = (
                f"90 d · all worlds · R only. {n_closed} bot trades closed in "
                f"90 days, none graded with an R multiple: nothing to "
                f"average.")
    except Exception as e:
        logger.warning("Op Center HISTORY metric unavailable: %s", e,
                       exc_info=True)

    # ── BOTS: enabled count + REAL's realized 24 h ───────────────────
    try:
        cfg = facts["cfg"]
        if cfg is None:
            raise RuntimeError("the configs could not be read")
        n_total, n_on = cfg["n"] or 0, cfg["on"] or 0
        realized = _realized_24h_by_world(user)
        out["bots"]["primary_title"] = (
            "Bots enabled, of all configured." if n_total
            else WHY["no_configs"])
        out["bots"]["secondary_title"] = WHY["nothing_live_24h"]
        if n_total:
            out["bots"]["primary"] = f"{n_on}/{n_total} ON"
        # Sum() over an empty set is None, which the old code coerced to
        # Decimal("0") and printed as "+$0.00 24h" — a claim that the day
        # closed flat, on a day nothing closed at all.
        real = realized.get("live") or {}
        real_text = _realized_text(real)
        if real_text != DASH:
            out["bots"]["secondary"] = f"REAL {real_text} · 24 h"
            out["bots"]["secondary_title"] = (
                "Realized on REAL money in 24 h, booked in each config's "
                "currency; DEMO and PAPER are in this head's title.")
        worlds = "; ".join(
            f"{WORLD_NAME[w]} {_realized_text(realized[w])} over "
            f"{sum(n for _p, n in realized[w].values())} close(s)"
            if realized.get(w) else
            f"{WORLD_NAME[w]} {DASH} ({WHY['nothing_' + w + '_24h']})"
            for w in WORLDS)
        if n_total:
            out["bots"]["title"] = (
                f"{n_on} of {n_total} bots enabled. Realized in 24 h, each "
                f"world apart and never added: {worlds}.")
        else:
            out["bots"]["title"] = "No bot configurations yet."
    except Exception as e:
        logger.warning("Op Center BOTS metric unavailable: %s", e, exc_info=True)

    return out


def _brain_reading():
    """The newest brain report (regime, confidence, concerns) and the trust
    band, each with its age (2026-11-07: the hero printed both with none)."""
    from brain.context import _brain_trust_score, brain_trust_band
    from brain.models import BrainReport
    now = timezone.now()
    out = {"report": None, "regime": DASH, "regime_label": "",
           "regime_class": "oc-regime-unknown", "regime_conf": DASH,
           "regime_age": "", "regime_title": WHY["no_report"],
           "trust": "UNKNOWN", "trust_band": "unknown",
           "trust_class": "oc-trust-unknown", "trust_score": None,
           "trust_age": "", "trust_title": WHY["no_trust"],
           "concerns": []}
    report = (BrainReport.objects.filter(error="")
              .order_by("-created_at").first())
    if report is not None:
        age = (now - report.created_at).total_seconds()
        out.update(
            report=report,
            regime=(report.regime_label or "unknown").upper(),
            regime_label=report.regime_label or "unknown",
            regime_class=f"oc-regime-{report.regime_label or 'unknown'}",
            regime_age=_ago(age),
            regime_title=(f"The brain's report of "
                          f"{report.created_at:%Y-%m-%d %H:%M} UTC, "
                          f"{_ago(age)}."),
            concerns=(report.top_concerns or [])[:3])
        if report.regime_confidence is not None:
            out["regime_conf"] = f"{float(report.regime_confidence):.2f}"
    score = _brain_trust_score()
    # brain_trust_band(None) reads the score a second time: "unknown" is
    # what it would answer.
    band = brain_trust_band(score) if score is not None else "unknown"
    out.update(trust=(band or "unknown").upper(), trust_band=band or "unknown",
               trust_class=f"oc-trust-{band or 'unknown'}", trust_score=score)
    if score is not None:
        try:
            from ai_agents.models import AgentPrediction
            last = AgentPrediction.objects.filter(
                agent="sauron_mind", was_correct__isnull=False
            ).aggregate(m=Max("evaluated_at"))["m"]
        except Exception:  # noqa: BLE001 — the band stands without its age
            last = None
        if last is not None:
            age = (now - last).total_seconds()
            out["trust_age"] = _ago(age)
            out["trust_title"] = (f"From the brain's last 50 graded calls; "
                                  f"the newest was graded {_ago(age)}.")
        else:
            out["trust_title"] = "From the brain's last 50 graded calls."
    return out


def _hero_metrics(user, walk=None, facts=None) -> dict:
    """The hero strip's readouts, already formatted for display.

    Split out of _hero_context so the initial render and the live refresh
    below run the same code — two formatters for one number is how a page
    ends up disagreeing with itself after the first push.

    THE PLATFORM BOOK, NAMED (2026-11-07, OC0): the figure is the platform's
    own book — the cash typed on /setup/ plus the REAL and DEMO notional
    plus paper's P&L, in mixed currencies, never converted — not a balance.
    It wears no currency sign; its words say what it holds. eToro's own
    equity sits beside it (the page's broker line). The three worlds' open
    P&L are three lines, never added; the regime and the trust carry their
    age; the "today" change names the snapshot it waits for.
    """
    # Every key the page's poll patches (data-oc-hero) has its `<key>_title`
    # here whenever it can be the dash: the poll writes the title with the
    # text, so a dash never keeps the title of the figure it replaced
    # (2026-11-12: `value` and `regime` defaulted to no reason, and
    # `prev_delta` and `regime_conf` sent none under the name the poll
    # reads).
    out = {
        "value": DASH, "value_title": WHY["not_measured"], "currency": "",
        "value_words": "",
        "delta": DASH, "delta_tone": "", "delta_title": WHY["snapshot_today"],
        "prev_delta": DASH, "prev_title": "", "prev_delta_title": "",
        "regime": DASH, "regime_class": "oc-regime-unknown",
        "regime_conf": DASH, "regime_age": "",
        "regime_title": WHY["not_measured"],
        "regime_conf_title": WHY["not_measured"],
        "trust": "UNKNOWN", "trust_class": "oc-trust-unknown",
        "trust_age": "", "trust_title": "",
        "mode": "paper", "mode_label": "bots: none enabled",
        "mode_class": "pill-mode",
        "worlds": {}, "world_none": 0, "world_none_words": "",
    }
    for w in WORLDS:
        out.update({f"world_{w}": DASH, f"world_{w}_title": WHY["not_measured"],
                    f"world_{w}_words": ""})
    if walk is None:
        walk = _safe_walk(user)
    if facts is None:
        facts = _head_facts(user, walk)

    if walk is not _FAILED:
        try:
            from portfolio.services import SHOWN_VALUE_WORDS
            book, shown = walk["book"], walk["shown_value"]
            portfolio = walk["portfolio"]
            ccy = (portfolio.currency or "").upper()
            out["value"] = DASH if shown.value is None else f"{shown.value:,.2f}"
            out["currency"] = (f"({ccy} + USD, not converted)"
                               if ccy not in ("", "USD") else "(USD)")
            out["value_words"] = BOOK_WORDS.format(ccy=ccy or "its currency")
            out["value_title"] = (f"{portfolio.name}. {SHOWN_VALUE_WORDS} "
                                  f"{book.coverage}")
            lines = _world_lines(walk)
            out["worlds"] = {w: {k: lines[w][k] for k in
                                 ("n", "pnl", "text", "why", "words", "title",
                                  "tone")} for w in WORLDS}
            for w in WORLDS:
                out[f"world_{w}"] = lines[w]["text"]
                out[f"world_{w}_title"] = lines[w]["title"]
                out[f"world_{w}_words"] = lines[w]["words"]
            n_none = lines[""]["n"]
            out["world_none"] = n_none
            out["world_none_words"] = (
                f"{n_none} recorded by hand: states no venue, in no world"
                if n_none else "")
        except Exception as e:
            logger.warning("Op Center hero portfolio unavailable: %s", e,
                           exc_info=True)

    # "+0.00" was the hardcoded default here, printed under a "· 24h" label
    # on every install that has never taken a snapshot. It is TODAY's
    # snapshot, written at 23:30 UTC: a dash until then, said so, with
    # yesterday's change and its date beside it (2026-11-07).
    today = facts["today"]
    snaps = facts["snaps"] or {}
    pct = snaps.get(today)
    if pct is not None:
        out["delta"] = f"{float(pct):+.2f}%"
        out["delta_tone"] = _tone(float(pct))
        out["delta_title"] = f"Day change from the {today} snapshot."
    yesterday = today - timedelta(days=1)
    prev = snaps.get(yesterday)
    if prev is not None:
        out["prev_delta"] = f"{float(prev):+.2f}%"
        out["prev_title"] = (f"Yesterday's change, from the "
                             f"{yesterday.isoformat()} snapshot.")
    else:
        out["prev_title"] = (f"not yet: no snapshot for "
                             f"{yesterday.isoformat()}")
    out["prev_delta_title"] = out["prev_title"]

    cfg = facts["cfg"]
    if cfg is not None:
        # Not the REAL marker: the topbar's red pill is the one (it counts
        # bots on a REAL account). This says only the configs' mode.
        if cfg["live_on"]:
            out.update(mode="live", mode_label="bots: live mode")
        elif cfg["on"]:
            out.update(mode="paper", mode_label="bots: paper mode")

    # Brain regime + trust band for the hero strip (Phase 47 actuation).
    try:
        brain = _brain_reading()
        for key in ("regime", "regime_class", "regime_conf", "regime_age",
                    "regime_title", "trust", "trust_class", "trust_age",
                    "trust_title"):
            out[key] = brain[key]
        # A report always states its confidence (the column is not
        # nullable): the dash is "no report".
        out["regime_conf_title"] = (WHY["no_report"]
                                    if out["regime_conf"] == DASH
                                    else "the report's confidence")
    except Exception as e:
        logger.warning("Op Center hero brain state unavailable: %s", e,
                       exc_info=True)

    return out


def _hero_context(user, walk=None, facts=None) -> dict:
    """Header strip data — visible above tabs at all times."""
    hero = _hero_metrics(user, walk=walk, facts=facts)
    return {
        "hero": hero,
        "currency": hero["currency"],
        "now_utc": timezone.now(),
    }


# ── Main entry point ─────────────────────────────────────────────────────

@login_required
def command_center(request):
    """Renders the wrapper with tabs. Initial tab from `?tab=` or smart default.

    Note: route stays at /command/ for backward compat — only the visible
    name changed to 'Operations Center'.
    """
    user = request.user
    walk = _safe_walk(user)
    facts = _head_facts(user, walk)
    on = (facts["cfg"] or {}).get("on") if facts["cfg"] is not None else None
    tab = (request.GET.get("tab") or _smart_default_tab(user, on)).lower()
    if tab not in ("live", "portfolio", "history", "bots"):
        tab = "live"

    from bot_program.capital_truth import broker_view

    context = {
        "page_id": "command",
        "active_tab": tab,
        "tab_metrics": _tab_bar_metrics(user, walk=walk, facts=facts),
        # The broker's own reading, rendered BESIDE the platform book —
        # cached columns only, so this adds no broker I/O to the render.
        "broker": broker_view(user),
        # A day of Sauron (2026-09-29): the same ring the Wall draws, read
        # off the beat schedule at render; its live layer arrives from
        # /api/day/live/ once the page is up (dashboard.views_day).
        "day": _day_context(),
        "day_us": _us_band(),
        # The kill switch's link is for the users its endpoint accepts
        # (superusers, views_admin_hq._admin_only).
        "can_operate": bool(getattr(user, "is_superuser", False)),
        "why": WHY,
        "oc_dashes": [],
        **_hero_context(user, walk=walk, facts=facts),
    }
    return render(request, "dashboard/command.html", context)


def _us_band() -> dict:
    """The 24-hour strip's US band, off core.constants.MARKET_SESSIONS
    through dashboard.views_day.us_session — never typed in the template
    (it read 13:30–21:00 against the table's 13:30–20:00)."""
    from dashboard.views_day import us_session
    open_m, close_m = us_session()
    return {"left": round(open_m / 1440 * 100, 3),
            "width": round((close_m - open_m) / 1440 * 100, 3),
            "words": f"{open_m // 60:02d}:{open_m % 60:02d}–{close_m // 60:02d}:{close_m % 60:02d}"}


def _day_context() -> dict:
    """The ring's data for json_script — the schedule read into seven
    stages with the Wall's cached counts. wall_facts() never raises; the
    schedule read is fenced here so a beat entry with an odd schedule
    cannot take the home page down with it."""
    from core.day_of_sauron import day_scheme, page_scheme
    from core.wall_facts import wall_facts
    try:
        # page_scheme: what the ring draws, not every task's import path.
        return page_scheme(day_scheme(wall_facts()))
    except Exception as e:  # noqa: BLE001 — the home page renders anyway
        logger.warning("Op Center day scheme unavailable: %s", e, exc_info=True)
        return {"stages": [], "total": 0, "queues": {}, "fastest": "",
                "slowest": "", "unplaced": 0, "adapters": 0}


@login_required
def command_tab_metrics(request):
    """The tab-head metrics and the hero strip, as JSON.

    These were computed once, at page render, and the per-tab fragment
    endpoints never recomputed them — so the four numbers the tab bar exists
    to show stayed frozen at whatever they were when the page was opened,
    however many fills landed afterwards. The page polls this on the same
    /ws/eye/ events the headband already reacts to, plus a slow fallback
    timer for the state changes the socket does not announce (a snapshot
    landing, a bot being toggled elsewhere).

    Deliberately JSON and not an HTML fragment: the payload is eight short
    strings, and re-rendering the tab bar would mean duplicating its markup
    in a partial that the live tab (owned elsewhere) could not carry.

    One book walk for both (2026-11-07, OC0): it walked the book three
    times per poll. The page asks with X-Requested-With, so the idle lock
    neither counts it as a human nor redirects it: a locked tab gets 423.
    """
    user = request.user
    walk = _safe_walk(user)
    facts = _head_facts(user, walk)
    return JsonResponse({
        "tabs": _tab_bar_metrics(user, walk=walk, facts=facts),
        "hero": _hero_metrics(user, walk=walk, facts=facts),
    })


# ── Per-tab fragment endpoints (HTMX-loaded) ─────────────────────────────

def _fragment(template, context):
    """A tab body, rendered with `render_to_string` and NO request
    (2026-11-07, OC0): the shell's context processors — some seventy
    queries the fragment never printed — do not run. No tab body holds a
    form (2026-11-12, P1: the bots' two forms left the home), so none
    needs a CSRF token; one that ever does must be handed it by its view."""
    context.setdefault("oc_dashes", [])
    context.setdefault("why", WHY)
    context.setdefault("read_at", timezone.now())
    return HttpResponse(render_to_string(template, context))


def _deployed_by_world(walk):
    """The notional at the marks, per world, in USD (notional_usd: price x
    quantity x the row's USD per unit). Never added across worlds."""
    split = walk["split"]
    out = []
    for w in WORLDS + ("",):
        es = [e for e in walk["entries"] if e["world"] == w]
        priced = [e["notional"] for e in es if e["notional"] is not None]
        n = split[w]["n"]
        if not n and w == "":
            continue
        if not n:
            text, why = DASH, WHY[f"no_{w}_open"]
        elif not priced:
            text, why = DASH, WHY["unmarked"]
        else:
            text, why = _money(round(sum(priced), 2), "USD", signed=False), ""
        out.append({"world": w, "name": WORLD_NAME[w], "n": n,
                    "n_priced": len(priced), "text": text, "why": why})
    return out


@login_required
def command_tab_live(request):
    """LIVE tab — current Eye content + Operations enrichment."""
    from .views_eye import _build_eye_context
    user = request.user
    context = _build_eye_context(user, for_command=True)

    # Both books, marked to live quotes — the same union the tab head
    # counts, walked once. Reading only portfolio.Position here reported 0%
    # deployed and 100% cash to an operator whose whole book was bot trades.
    # DEPLOYED is per world, in USD (2026-11-07): the cross-world sum and
    # its share of the typed cash are gone.
    walk = _safe_walk(user)
    if walk is not _FAILED:
        split = walk["split"]
        context["live_opens"] = walk["n_open"]
        context["live_open_split"] = [
            {"world": w, "name": WORLD_NAME[w], "n": split[w]["n"]}
            for w in WORLDS + ("",) if w or split[w]["n"]]
        context["live_deployed"] = _deployed_by_world(walk)
        context["eye_hand_rows"] = split[""]["n"]
    else:
        context["live_opens"] = DASH
        context["live_open_split"] = []
        context["live_deployed"] = []
        context["eye_hand_rows"] = None
    # The Eye's rows as its reader returned them; a reader that answered
    # without them counts none, and the page still renders.
    eye_rows = context.get("open_positions") or []
    context["eye_bot_rows"] = sum(1 for p in eye_rows
                                  if p.get("kind") == "asset")
    context["eye_legacy_rows"] = sum(1 for p in eye_rows
                                     if p.get("kind") == "legacy")
    # Configs from the Eye's own read (2026-11-07): "Active bots 8" counted
    # every config beside "5 enabled". Counted here, outside the closes'
    # fence below (2026-11-12): they are not the closes', and a failed read
    # of the closes printed "— configs · — enabled".
    asset_bots = [b for b in (context.get("bot_health") or [])
                  if b.get("kind") == "asset"]
    context["live_bots_enabled"] = sum(1 for b in asset_bots if b["enabled"])
    context["live_bots_total"] = len(asset_bots)

    # A READ THAT FAILS IS "NOT MEASURED", NEVER "NONE" (2026-11-12, spec
    # §5.7). Each block below is fenced and prints dashes when its read
    # raises; the template asks these flags which dash it is, so a failed
    # read never borrows an empty day's words ("the gate was not asked",
    # "a clean session", a brain with 0 concerns).
    context.update(gate_unread=False, pulse_unread=False, rules_unread=False,
                   brain_unread=False)

    # THE LIVE WORLD AS eToro STATES IT (2026-10-31). eToro's own used,
    # available and total, from the sync's cells with their age, stand
    # beside DEPLOYED (bot_program.etoro_used). View layer only:
    # services.live_book_value, which the gates divide by, is not touched.
    try:
        from bot_program.etoro_used import account_used
        context["live_etoro"] = account_used(user)
    except Exception as e:  # noqa: BLE001 — the strip renders without it
        logger.warning("Op Center eToro figures unavailable: %s", e,
                       exc_info=True)
        context["live_etoro"] = None

    # Today's gate activity (Phase 15 orchestrator).
    #
    # This cell used to lead with an accept rate, and the rate was not one.
    # OrchestratorEvent keeps every reject and only a ~1-in-10 sample of the
    # allows (bot_program.orchestrator._log_decision), so allow/(allow+reject)
    # divides a sampled numerator by a mixed denominator: a gate letting 40 of
    # 50 entries through logs ~4 allows and 10 rejects and the strip read
    # "GATE 24H 28.6%". The operator sees a gate refusing three quarters of
    # their entries and goes and loosens the exposure caps. The reject count
    # is exact and is the number worth leading with; the allow count rides
    # along labelled as the sample it is.
    try:
        from bot_program.orchestrator_models import OrchestratorEvent
        cutoff = timezone.now() - timedelta(hours=24)
        agg = OrchestratorEvent.objects.filter(
            user=user, created_at__gte=cutoff).aggregate(
            allow=Count("id", filter=Q(decision="allow")),
            reject=Count("id", filter=Q(decision="reject")))
        n_allow, n_reject = agg["allow"] or 0, agg["reject"] or 0
        context["gate_n_allow"] = n_allow
        context["gate_n_reject"] = n_reject
        # No decisions in 24h is "the gate was not asked", not "0 refused".
        context["gate_asked"] = (n_allow + n_reject) > 0
    except Exception as e:
        logger.warning("Op Center gate counts unavailable: %s", e, exc_info=True)
        context["gate_n_allow"] = DASH
        context["gate_n_reject"] = DASH
        context["gate_asked"] = False
        context["gate_unread"] = True

    # Recent fills (last 5 closed bot trades in the last 24h) + 24h session
    # metrics. R only, all worlds: each close carries its world chip.
    try:
        from bot_program.models import AssetBotTrade
        from dashboard.position_summary import world_of
        cutoff = timezone.now() - timedelta(hours=24)
        all_24h_closed = list(
            AssetBotTrade.objects
            .filter(config__user=user, status="CLOSED",
                    closed_at__gte=cutoff)
            .order_by("-closed_at")
        )
        for t in all_24h_closed:
            t.world = world_of(t)
        context["live_recent_fills"] = all_24h_closed[:5]

        # 24h session aggregates.
        n_closed_24h = len(all_24h_closed)
        graded = [t for t in all_24h_closed if t.realized_r is not None]
        rs = [float(t.realized_r) for t in graded]
        n_wins = sum(1 for r in rs if r > 0)
        n_losses = sum(1 for r in rs if r < 0)
        best_24h = max(graded, key=lambda t: float(t.realized_r), default=None)
        worst_24h = min(graded, key=lambda t: float(t.realized_r), default=None)

        # Last 12 closes, oldest → newest, matching the axis captions under
        # the bars. The slice used to run over the tail of a newest-first
        # list, so the card labelled "last 12 closes" plotted the twelve
        # OLDEST of the session and drew them right-to-left.
        last_12 = list(reversed(graded))[-12:]
        last_12_r = [float(t.realized_r) for t in last_12]

        context["live_24h_n"] = n_closed_24h
        context["live_24h_wins"] = n_wins
        context["live_24h_losses"] = n_losses
        # Nothing graded means nothing measured: a summed R of 0 over zero
        # trades reads as a flat session, which is a different claim.
        context["live_24h_sum_r"] = round(sum(rs), 2) if rs else DASH
        context["live_24h_win_rate"] = (
            round(n_wins / len(rs) * 100, 1) if rs else DASH)
        # The best/worst cards read `.config.symbol` and `.config.rule_name`,
        # and AssetBotConfig has NEITHER (it holds a `symbols` LIST, and
        # rule_name lives on the trade) — so both cards rendered a blank
        # symbol above a real R number. Handed over as plain mappings shaped
        # the way the card reads them, with the trade's own values.
        context["live_24h_best"] = _fill_card(best_24h)
        context["live_24h_worst"] = _fill_card(worst_24h)
        context["live_24h_spark"] = last_12_r
        context["live_24h_spark_min"] = (min(last_12_r) if last_12_r else 0)
        context["live_24h_spark_max"] = (max(last_12_r) if last_12_r else 0)
        # chart_bars contract. A diverging series scales against ONE peak —
        # the largest absolute R — or a −3R loss next to a +0.5R win draws
        # the two at the same length in opposite directions. Each bar names
        # its world (2026-11-07): an R from any world, said so.
        context["live_24h_bars"] = [
            {"label": "#{} {}".format(i + 1, WORLD_NAME.get(t.world, "")),
             "value": float(t.realized_r),
             "display": "{:+.2f}R".format(float(t.realized_r))}
            for i, t in enumerate(last_12)
        ]
        context["live_24h_spark_peak"] = max(
            [abs(r) for r in last_12_r], default=0)
    except Exception as e:
        logger.warning("Op Center LIVE session pulse unavailable: %s", e,
                       exc_info=True)
        context["pulse_unread"] = True
        context["live_recent_fills"] = []
        context["live_24h_n"] = DASH
        context["live_24h_wins"] = DASH
        context["live_24h_losses"] = DASH
        context["live_24h_sum_r"] = DASH
        context["live_24h_win_rate"] = DASH
        context["live_24h_best"] = None
        context["live_24h_worst"] = None
        context["live_24h_spark"] = []
        context["live_24h_spark_min"] = 0
        context["live_24h_spark_max"] = 0
        context["live_24h_bars"] = []
        context["live_24h_spark_peak"] = 0

    # Active rules counter (Phase 5 RuleControl) — operator awareness.
    try:
        # signals.models_control, not bot_program.rule_control_models: that
        # module does not exist, so this import raised ModuleNotFoundError on
        # every single render and the swallowing `except` printed a confident
        # "0 rules · 0 paused · 0 research" on an install running twelve.
        # The old field names were wrong too (`state`, `stage`), so even the
        # right module would not have answered.
        from signals.models_control import RuleControl
        now = timezone.now()
        running = RuleControl.running_q(now)
        context["live_rules_active"] = RuleControl.objects.filter(running).count()
        # Paused is the complement of running, not `status="paused"`: a pause
        # whose paused_until has elapsed is a rule trading again, and nothing
        # ever writes the column back — counting by column double-books it
        # against the line above.
        context["live_rules_paused"] = RuleControl.objects.exclude(running).count()
        context["live_rules_research"] = RuleControl.objects.filter(
            promotion_stage=RuleControl.STAGE_RESEARCH).count()
    except Exception as e:
        logger.warning("Op Center rule counters unavailable: %s", e,
                       exc_info=True)
        context["rules_unread"] = True
        context["live_rules_active"] = DASH
        context["live_rules_paused"] = DASH
        context["live_rules_research"] = DASH

    # The brain's regime, trust and concerns, each with its age: one read.
    try:
        brain = _brain_reading()
        context["brain"] = brain
        context["brain_regime"] = brain["regime_label"] or "unknown"
        context["brain_regime_conf"] = brain["regime_conf"]
        context["brain_age_str"] = brain["regime_age"] or DASH
        context["brain_top_concerns"] = brain["concerns"]
        context["brain_trust"] = brain["trust_score"]
        context["brain_trust_band"] = brain["trust_band"]
    except Exception as e:
        # Logged like every other block here (2026-11-12): it fell back in
        # silence, and the tab then said "no report" and "0 concerns".
        logger.warning("Op Center LIVE brain reading unavailable: %s", e,
                       exc_info=True)
        context["brain_unread"] = True
        context["brain"] = None
        context["brain_regime"] = "unknown"
        context["brain_regime_conf"] = DASH
        context["brain_age_str"] = DASH
        context["brain_top_concerns"] = []
        context["brain_trust"] = None
        context["brain_trust_band"] = "unknown"

    # The concerns' text is staff-only, as on /brain/ (2026-10-24).
    from core.views_book import is_staff
    context["show_text"] = is_staff(user)
    return _fragment("dashboard/_command_live.html", context)


def _closed_by_world(user, portfolio):
    """Lifetime closes per world, as database aggregates (2026-11-07, OC0).

    {world: {"n", "n_graded", "n_unknown", "wins", "losses", "zeros",
    "gross_win", "gross_loss", "avg_win", "avg_loss", "win_rate",
    "profit_factor", "payoff", "ccy"}} — the bot closes grouped by their
    stamps and currency in ONE read (world_of on each group), the
    hand-recorded closes (no venue) in one more. The tab read every close
    there ever was (20,181 rows, 783 ms at six months) to compute four
    numbers, and summed the worlds. The profit factor is the gross wins
    over the gross losses; the payoff — what the tab printed as its
    "profit factor" — the average win over the average loss, named."""
    from bot_program.models import AssetBotTrade
    from dashboard.position_summary import world_of
    groups = {}

    def add(world, ccy, n, graded, wins, losses, gw, gl):
        g = groups.setdefault(world, {"n": 0, "n_graded": 0, "wins": 0,
                                      "losses": 0, "gross_win": 0.0,
                                      "gross_loss": 0.0, "ccys": set()})
        g["n"] += n
        g["n_graded"] += graded
        g["wins"] += wins
        g["losses"] += losses
        g["gross_win"] += float(gw or 0)
        g["gross_loss"] += float(gl or 0)
        if n:
            g["ccys"].add(ccy)

    for r in (AssetBotTrade.objects
              .filter(config__user=user, status="CLOSED")
              .annotate(**_world_stamps())
              .values("paper", "w_broker", "w_env", "config__base_currency")
              .annotate(n=Count("id"), graded=Count("pnl"),
                        wins=Count("id", filter=Q(pnl__gt=0)),
                        losses=Count("id", filter=Q(pnl__lt=0)),
                        gw=Sum("pnl", filter=Q(pnl__gt=0)),
                        gl=Sum("pnl", filter=Q(pnl__lt=0)))
              .order_by()):
        world = world_of({"paper": r["paper"],
                          "metadata": {"broker": r["w_broker"],
                                       "broker_env": r["w_env"]}})
        add(world, (r["config__base_currency"] or "USD").strip().upper(),
            r["n"], r["graded"], r["wins"], r["losses"], r["gw"], r["gl"])

    # A hand-recorded Position's realized P&L is its unrealized_pnl column
    # (unified_closed_positions' convention); it states no venue.
    legacy = portfolio.positions.filter(closed_at__isnull=False).aggregate(
        n=Count("id"), graded=Count("unrealized_pnl"),
        wins=Count("id", filter=Q(unrealized_pnl__gt=0)),
        losses=Count("id", filter=Q(unrealized_pnl__lt=0)),
        gw=Sum("unrealized_pnl", filter=Q(unrealized_pnl__gt=0)),
        gl=Sum("unrealized_pnl", filter=Q(unrealized_pnl__lt=0)))
    if legacy["n"]:
        add("", (portfolio.currency or "").upper() or "USD", legacy["n"],
            legacy["graded"], legacy["wins"], legacy["losses"],
            legacy["gw"], legacy["gl"])

    out = {}
    for world in WORLDS + ("",):
        g = groups.get(world)
        if g is None:
            out[world] = {"world": world, "name": WORLD_NAME[world], "n": 0,
                          "n_graded": 0, "n_unknown": 0, "wins": 0,
                          "losses": 0, "zeros": 0, "gross_win": None,
                          "gross_loss": None, "avg_win": None,
                          "avg_loss": None, "win_rate": None,
                          "profit_factor": None, "payoff": None, "ccy": "USD",
                          "mixed": False}
            continue
        wins, losses = g["wins"], g["losses"]
        avg_win = round(g["gross_win"] / wins, 2) if wins else None
        avg_loss = round(g["gross_loss"] / losses, 2) if losses else None
        ccys = sorted(g["ccys"]) or ["USD"]
        out[world] = {
            "world": world, "name": WORLD_NAME[world], "n": g["n"],
            "n_graded": g["n_graded"], "n_unknown": g["n"] - g["n_graded"],
            "wins": wins, "losses": losses,
            "zeros": g["n_graded"] - wins - losses,
            "gross_win": round(g["gross_win"], 2) if wins else None,
            "gross_loss": round(g["gross_loss"], 2) if losses else None,
            "avg_win": avg_win, "avg_loss": avg_loss,
            "win_rate": (round(wins / g["n_graded"] * 100, 1)
                         if g["n_graded"] else None),
            "profit_factor": (round(g["gross_win"] / abs(g["gross_loss"]), 2)
                              if losses and g["gross_loss"] else None),
            "payoff": (round(avg_win / abs(avg_loss), 2)
                       if avg_win is not None and avg_loss else None),
            "ccy": ccys[0], "mixed": len(ccys) > 1,
        }
    for row in out.values():
        row["avg_win_text"] = _money(row["avg_win"], row["ccy"])
        row["avg_loss_text"] = _money(row["avg_loss"], row["ccy"])
    return out


def _top_closes(user, portfolio, *, limit=5):
    """The `limit` best and the `limit` worst closes of a lifetime, bot and
    hand-recorded, each in its own world and currency: {"best", "worst"}.

    One read per book, never every close: the database ranks each close
    within its sign by the size of its P&L (largest first, the newest
    first among equals), over the ids alone, and returns the rows of the
    first `limit` of each sign (ranking the whole rows cost 140 ms at six
    months, the ids 50)."""
    from django.db.models import F, Window
    from django.db.models.functions import Abs, RowNumber, Sign
    from bot_program.models import AssetBotTrade
    from dashboard.position_summary import world_of

    def ranked(qs, field):
        ids = (qs.filter(**{f"{field}__isnull": False})
               .exclude(**{field: 0})
               .annotate(oc_rank=Window(
                   RowNumber(), partition_by=[Sign(field)],
                   order_by=[Abs(field).desc(),
                             F("closed_at").desc(nulls_last=True)]))
               .filter(oc_rank__lte=limit).values("id"))
        return qs.model.objects.filter(id__in=ids)

    rows = []
    for t in ranked(AssetBotTrade.objects.filter(config__user=user,
                                                 status="CLOSED"), "pnl"
                    ).select_related("config"):
        rows.append({"symbol": t.symbol,
                     "direction": "long" if (t.side or "").upper()
                     in ("BUY", "LONG") else "short",
                     "pnl": float(t.pnl), "world": world_of(t),
                     "ccy": (t.config.base_currency or "USD").upper(),
                     "closed_at": t.closed_at})
    for p in ranked(portfolio.positions.filter(closed_at__isnull=False),
                    "unrealized_pnl").select_related("instrument"):
        rows.append({"symbol": p.instrument.symbol,
                     "direction": (p.direction or "").lower(),
                     "pnl": float(p.unrealized_pnl), "world": "",
                     "ccy": (portfolio.currency or "USD").upper(),
                     "closed_at": p.closed_at})
    for r in rows:
        r["text"] = _money(r["pnl"], r["ccy"])
    best = sorted((r for r in rows if r["pnl"] > 0),
                  key=lambda r: r["pnl"], reverse=True)[:limit]
    worst = sorted((r for r in rows if r["pnl"] < 0),
                   key=lambda r: r["pnl"])[:limit]
    return {"best": best, "worst": worst}


def _has_broker(user) -> bool:
    """Is a broker interfaced (capital_truth.broker_backed: keyed and
    carrying an asset class)? Its three account rows in ONE read; False
    when they cannot be read — the label then names the platform's book
    alone, as with no broker."""
    from django.contrib.auth import get_user_model
    from bot_program.capital_truth import broker_backed
    try:
        rows = (get_user_model().objects
                .select_related("saxo_account", "etoro_account",
                                "ibkr_account")
                .get(pk=user.pk))
        return broker_backed(rows) is not None
    except Exception as e:  # noqa: BLE001 — the label, not the page
        logger.warning("Op Center broker rows unreadable: %s", e,
                       exc_info=True)
        return False


@login_required
def command_tab_portfolio(request):
    """PORTFOLIO tab — strategic snapshot with sparkline + allocation."""
    from dashboard.position_summary import quantity
    from portfolio.models import PortfolioSnapshot
    from portfolio.services import SHOWN_VALUE_WORDS

    user = request.user
    walk = _book_walk(user)
    portfolio = walk["portfolio"]
    # BOTH books. This tab read portfolio.Position alone, so on a platform
    # where every interactive trade writes AssetBotTrade it showed an empty
    # portfolio, an empty allocation donut and "No closed trades yet" to an
    # operator with a full track record. The walk is `unified_open_positions`
    # re-priced by _open_book, once, the rows and the totals from one union.
    open_positions = walk["rows"]
    book = walk["book"]
    # THE TABLE SHOWS eToro's OWN P&L on an eToro row (2026-11-06, the
    # operator's report: an open eToro forex row read a gain on Sauron and a
    # small loss in the eToro app): display copies (portfolio.services
    # .ShownRow), never the union's objects, which live_book_value has read
    # as the marks priced them.
    shown_value = walk["shown_value"]
    # The rows' P&L, ALL worlds: kept for the readers that count both books
    # (tests/test_command_metrics.py); never printed — the strip prints each
    # world apart (unrealized_by_world).
    from portfolio.services import shown_unrealized
    total_unrealized = (shown_unrealized(walk["shown"]) if walk["venues"]
                        else walk["union"][2])
    lines = _world_lines(walk)

    stats = _closed_by_world(user, portfolio)
    real = stats["live"]

    # Against the LIVE book value, not the stored column: dividing cash by a
    # figure that never counted the open positions reported "100% cash" to an
    # operator whose whole book was deployed. DASH and not None where it
    # cannot be measured.
    cash_pct = (DASH if shown_value.cash_pct is None
                else round(shown_value.cash_pct))
    exposure_pct = (DASH if shown_value.exposure_pct is None
                    else round(shown_value.exposure_pct))

    # The snapshots in ONE read: the newest 31 (one per day, unique per
    # portfolio and date) hold the last 30 days — the curve, Sharpe and
    # Sortino — and the newest, whatever its age, gives the drawdown and
    # its date.
    cutoff_30d = timezone.now().date() - timedelta(days=30)
    newest = list(PortfolioSnapshot.objects.filter(portfolio=portfolio)
                  .order_by("-date")
                  .values_list("date", "total_value", "daily_pnl_pct",
                               "max_drawdown")[:31])
    latest = newest[0] if newest else None
    snaps = [s for s in reversed(newest) if s[0] >= cutoff_30d]
    equity_points = [float(v) for _d, v, _p, _m in snaps]

    # Allocation donut data — by asset class, from current open positions.
    # Marked value where a mark exists, entry cost otherwise: a slice sized
    # at zero because no quote arrived would silently shrink the book. It is
    # the marked notional of every world and the cash typed on /setup/,
    # and it says so.
    alloc_by_class = defaultdict(float)
    for p in open_positions:
        ac = getattr(p.instrument, "asset_class", "") or "other"
        price = p.current_price if p.current_price is not None else p.entry_price
        alloc_by_class[ac] += abs(float(p.quantity or 0) * float(price or 0))
    alloc_by_class["cash"] = float(portfolio.cash_available or 0)
    alloc_total = sum(alloc_by_class.values()) or 1.0
    allocation = sorted(
        # "key" is the donut partial's contract; asset_class stays for the
        # table that reads the same rows.
        ({"asset_class": k, "key": k, "value": v,
          "pct": round(v / alloc_total * 100, 1)}
         for k, v in alloc_by_class.items() if v > 0),
        key=lambda r: r["value"], reverse=True,
    )

    # 30d Sharpe / Sortino approximations from PortfolioSnapshot.daily_pnl_pct.
    sharpe = sortino = None
    try:
        rets = [float(p or 0) for _d, _v, p, _m in snaps]
        if len(rets) >= 5:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = var ** 0.5
            sharpe = round((mean / std) * (252 ** 0.5), 2) if std > 0 else None
            downside = [r for r in rets if r < 0]
            if downside:
                d_var = sum(r ** 2 for r in downside) / len(downside)
                d_std = d_var ** 0.5
                sortino = round((mean / d_std) * (252 ** 0.5), 2) if d_std > 0 else None
    except Exception as e:
        logger.warning("Op Center Sharpe/Sortino unavailable: %s", e,
                       exc_info=True)

    # The open rows as the table prints them: the platform's row key (the
    # one F4 and F7 patch through), the world from the trade's stamps, the
    # quantity as a person counts it, the price in its instrument's own
    # decimals, the mark with its source and age, the P&L with its currency.
    from bot_program.venue_mark import age_words
    table = []
    for e in walk["entries"][:20]:
        row = e["row"]
        ident = (row.trade_id if e["bot"] else getattr(row, "pk", None))
        cls = getattr(row.instrument, "asset_class", "") or ""
        src = getattr(row, "mark_source", None) or ""
        age = getattr(row, "mark_age_s", None)
        table.append({
            "row": row, "world": e["world"],
            "key": f"{'bot' if e['bot'] else 'pos'}-{ident}",
            "symbol": row.instrument.symbol, "asset_class": cls,
            "qty_text": quantity(row.quantity),
            "mark_source": src,
            "mark_at": getattr(row, "mark_at", None),
            "mark_words": (
                f"{'venue' if src.startswith('venue') else 'feed' if src == 'quote' else src} · {age_words(age)}"
                if src and age is not None else (src or "")),
            "pnl_text": (_money(e["pnl"], e["ccy"], estimate=e["tier"] != "etoro")
                         if e["pnl"] is not None else DASH),
        })

    has_broker = _has_broker(user)
    top = _top_closes(user, portfolio)
    ccy = (portfolio.currency or "").upper()
    context = {
        "portfolio": portfolio,
        "open_positions": walk["shown"][:20],
        "open_table": table,
        "open_positions_total": len(open_positions),
        "total_unrealized": total_unrealized,
        "unrealized_by_world": [lines[w] | {"world": w,
                                            "name": WORLD_NAME[w]}
                                for w in WORLDS],
        "cash_pct": cash_pct,
        "exposure_pct": exposure_pct,
        # The platform book, named for what it is (2026-11-07, OC0): no
        # currency sign, its words, eToro's line beside it on the page.
        "book_label": "PLATFORM BOOK" if has_broker else "PORTFOLIO VALUE",
        "book_value_text": (DASH if shown_value.value is None
                            else f"{shown_value.value:,.2f}"),
        "book_currency": (f"{ccy} + USD, not converted"
                          if ccy not in ("", "USD") else "USD"),
        "book_words": BOOK_WORDS.format(ccy=ccy or "its currency"),
        "book_coverage": book.coverage,
        "book_value_title": f"{SHOWN_VALUE_WORDS} {book.coverage}",
        "book_value_partial": book.partial and book.value is not None,
        "cash_text": _money(portfolio.cash_available, ccy or "USD",
                            signed=False),
        # Per world, lifetime (2026-11-07): REAL leads the strip, every
        # world has its row below it. None all the way down where there is
        # nothing to measure — a 0.0% win rate over zero trades is a claim
        # that every trade lost.
        "stats_by_world": stats,
        "stats_rows": [stats[w] for w in WORLDS + ("",)
                       if w or stats[w]["n"]],
        "win_rate": real["win_rate"],
        "n_closed": real["n_graded"],
        "n_ungraded": real["n_unknown"],
        "n_winning": real["wins"],
        "n_losing": real["losses"],
        "avg_win": real["avg_win"],
        "avg_loss": real["avg_loss"],
        "profit_factor": real["profit_factor"],
        "payoff": real["payoff"],
        "best_trades": top["best"],
        "worst_trades": top["worst"],
        # A book with no snapshot has no measured drawdown. "0.00%" under a
        # MAX DRAWDOWN label reads as "never lost money".
        "max_drawdown": (float(latest[3]) if latest is not None
                         and latest[3] is not None else None),
        "snapshot_date": latest[0] if latest is not None else None,
        "sharpe_30d": sharpe,
        "sortino_30d": sortino,
        "equity_points": equity_points,
        "equity_min": min(equity_points) if equity_points else 0,
        "equity_max": max(equity_points) if equity_points else 0,
        # The curve's low and high as the book itself is printed: grouped,
        # two decimals, no currency sign (2026-11-12; they read 25000.50).
        "equity_min_text": (f"{min(equity_points):,.2f}" if equity_points
                            else DASH),
        "equity_max_text": (f"{max(equity_points):,.2f}" if equity_points
                            else DASH),
        "allocation": allocation,
    }
    return _fragment("dashboard/_command_portfolio.html", context)


@login_required
def command_tab_history(request):
    """HISTORY tab — closed trade analytics + per-rule track record.

    In the database (2026-11-07, OC0): one point per DAY on the cumulative
    R line (it drew one per close: 10,139 points, 154 KiB at six months),
    the rules' mean and spread as aggregates, the per-rule P&L split by
    world and printed with its currency (it summed the worlds)."""
    from django.db.models.functions import TruncDate
    from bot_program.models import AssetBotTrade
    from dashboard.position_summary import world_of

    user = request.user
    cutoff = timezone.now() - timedelta(days=90)
    closed = (AssetBotTrade.objects
              .filter(config__user=user, status="CLOSED",
                      closed_at__gte=cutoff))
    # Graded trades only. A close with no realized_r (no stop recorded, so no
    # initial risk to normalise by) can never be a win, and putting it in the
    # denominator quietly drags the win rate down by however many of them
    # there are — the sub-label now names the graded population.
    agg = closed.aggregate(n=Count("id"), graded=Count("realized_r"),
                           total_r=Sum("realized_r"),
                           wins=Count("id", filter=Q(realized_r__gt=0)))
    n_closed, n_graded = agg["n"] or 0, agg["graded"] or 0
    total_r = agg["total_r"]
    n_wins = agg["wins"] or 0
    win_rate = (n_wins / n_graded * 100) if n_graded else None

    # Per rule × class, the P&L of each world apart, with its currency. The
    # GROUP BY is the rule, the class and the rows' stamps; the world is
    # world_of's, applied to each group here. .order_by() before .values():
    # an ordering in force when values() runs rides into the GROUP BY.
    rules = {}
    for r in (closed.exclude(rule_name="")
              .annotate(**_world_stamps())
              .order_by()
              .values("rule_name", "asset_class", "paper", "w_broker",
                      "w_env", "config__base_currency")
              .annotate(n=Count("id"), n_r=Count("realized_r"),
                        sum_r=Sum("realized_r"), pnl_sum=Sum("pnl"),
                        n_pnl=Count("pnl"))):
        world = world_of({"paper": r["paper"],
                          "metadata": {"broker": r["w_broker"],
                                       "broker_env": r["w_env"]}})
        ccy = (r["config__base_currency"] or "USD").strip().upper()
        row = rules.setdefault((r["rule_name"], r["asset_class"]), {
            "rule_name": r["rule_name"], "asset_class": r["asset_class"],
            "n": 0, "n_r": 0, "sum_r": 0.0, "money": {}})
        row["n"] += r["n"]
        row["n_r"] += r["n_r"]
        row["sum_r"] += float(r["sum_r"] or 0)
        if r["n_pnl"]:
            key = (world, ccy)
            row["money"][key] = (row["money"].get(key, 0.0)
                                 + float(r["pnl_sum"] or 0))
    by_rule = []
    for row in rules.values():
        row["avg_r"] = round(row["sum_r"] / row["n_r"], 2) if row["n_r"] else None
        row["worlds"] = []
        for w in WORLDS + ("",):
            cells = [_money(round(v, 2), ccy) for (world, ccy), v in
                     sorted(row["money"].items()) if world == w]
            row["worlds"].append({"world": w, "name": WORLD_NAME[w],
                                  "text": " · ".join(cells) if cells else DASH})
        by_rule.append(row)
    # The most active first: an order that adds no money across worlds.
    by_rule.sort(key=lambda r: (-r["n"], r["rule_name"], r["asset_class"]))
    by_rule = by_rule[:20]
    has_none = any(r["money"] and any(w == "" for w, _c in r["money"])
                   for r in by_rule)

    # The cumulative R and the rolling win rate, ONE POINT PER DAY: the R
    # summed by day in the database, then run in order.
    days = list(closed.filter(realized_r__isnull=False)
                .annotate(day=TruncDate("closed_at"))
                .order_by().values("day")
                .annotate(r=Sum("realized_r"), n=Count("id"),
                          wins=Count("id", filter=Q(realized_r__gt=0)))
                .order_by("day"))
    cum_r_points: list[float] = []
    running = 0.0
    for d in days:
        running += float(d["r"] or 0)
        cum_r_points.append(round(running, 4))

    # Rolling 30d win-rate per closed day.
    win_rate_points: list[float] = []
    window = 30
    for i, d in enumerate(days):
        start = d["day"] - timedelta(days=window)
        n = w = 0
        for e in days[:i + 1]:
            if start <= e["day"] <= d["day"]:
                n += e["n"]
                w += e["wins"]
        if n:
            win_rate_points.append(round(w / n * 100, 1))

    # Day-of-week map: count and avg R per Mon-Sun, from the days above.
    # The shade is |avg R| with a floor (2026-11-07, spec §5.6): under
    # 0.05R a weekday is neutral, whatever its count, and the count is text.
    dow_stats = [{"label": d, "n": 0, "avg_r": 0.0, "total_r": 0.0}
                 for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]
    for d in days:
        idx = d["day"].weekday()
        dow_stats[idx]["n"] += d["n"]
        dow_stats[idx]["total_r"] += float(d["r"] or 0)
    for d in dow_stats:
        # A weekday with no closes has no average, and "0.0R" in the same
        # slot a real average occupies reads as a break-even day.
        d["avg_r"] = round(d["total_r"] / d["n"], 3) if d["n"] > 0 else DASH
        mag = abs(d["avg_r"]) if d["n"] else 0.0
        d["shade"] = (0 if mag < 0.05 else
                      min(35, int(round(mag / 1.0 * 35))) or 1)
        d["tone"] = ("" if not d["n"] or mag < 0.05 else
                     "up" if d["avg_r"] > 0 else "down")

    # Top rules by a Sharpe-like metric (avg R / stdev), in the database:
    # the mean and the mean of the squares per rule.
    top_rules_sharpe = []
    for r in (closed.filter(realized_r__isnull=False).exclude(rule_name="")
              .order_by().values("rule_name")
              .annotate(n=Count("id"), m=Avg("realized_r"),
                        m2=Avg(F("realized_r") * F("realized_r")))):
        if r["n"] < 5:
            continue
        m = float(r["m"] or 0)
        v = max(0.0, float(r["m2"] or 0) - m * m)
        s = v ** 0.5
        if s > 1e-12:
            top_rules_sharpe.append({"rule_name": r["rule_name"], "n": r["n"],
                                     "avg_r": round(m, 3),
                                     "sharpe": round(m / s, 3)})
    top_rules_sharpe.sort(key=lambda r: r["sharpe"], reverse=True)
    n_rules_ranked = len(top_rules_sharpe)
    top_rules_sharpe = top_rules_sharpe[:5]

    decay_alerts = []
    try:
        from bot_program.models import RuleTrackRecordAlert
        decay_alerts = list(
            RuleTrackRecordAlert.objects
            .filter(user=user, resolved_at__isnull=True)
            .order_by("-detected_at")[:10]
        )
    except Exception as e:
        logger.warning("Op Center decay alerts unavailable: %s", e,
                       exc_info=True)

    recent = list(closed.select_related("config").order_by("-closed_at")[:30])
    for t in recent:
        t.world = world_of(t)
        t.pnl_text = (_money(t.pnl, (t.config.base_currency or "USD").upper())
                      if t.pnl is not None else DASH)

    context = {
        "n_closed": n_closed,
        "n_graded": n_graded,
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "total_r": round(float(total_r), 2) if total_r is not None else None,
        "n_wins": n_wins,
        "by_rule": by_rule,
        "by_rule_none": has_none,
        "decay_alerts": decay_alerts,
        "recent_closed": recent,
        "cum_r_points": cum_r_points,
        "cum_r_days": [d["day"].isoformat() for d in days],
        "cum_r_min": min(cum_r_points) if cum_r_points else 0,
        "cum_r_max": max(cum_r_points) if cum_r_points else 0,
        "win_rate_points": win_rate_points,
        "dow_stats": dow_stats,
        "dow_max_n": max((d["n"] for d in dow_stats), default=0),
        "top_rules_sharpe": top_rules_sharpe,
        "n_rules_ranked": n_rules_ranked,
    }
    return _fragment("dashboard/_command_history.html", context)


@login_required
def command_tab_bots(request):
    """BOTS tab — per-AssetBotConfig overview with heartbeat + cooldown.

    Three grouped reads instead of seven per config (2026-11-07, OC0); the
    world chip from the ACCOUNT the config's symbols route to (a live-mode
    bot on an eToro demo account read REAL MONEY off its mode); health
    from each bot's own heartbeat against the tick's cadence, not from
    "traded in 6 h".

    NO FORM (2026-11-12, proposal P1, the operator's OK of 2026-11-07):
    the Toggle and Tick forms left the home for everyone. "Toggle" did not
    say on or off, and "Tick" started a bot pass from the home with no PIN
    and no confirmation. Both stay on the bots page (/asset-bots/), and
    their endpoints, PIN and words are not edited. A superuser, the only
    user those endpoints accept, gets one plain link to that page."""
    from bot_program.asset_engine.safety import heartbeat_age_seconds
    from bot_program.models import AssetBotConfig, AssetBotTrade
    from core.context_processors import (BOT_TICK_OVERDUE_FACTOR,
                                         _bot_tick_cadence_seconds,
                                         _is_manual_config, config_worlds)
    from dashboard.position_summary import world_of

    user = request.user
    configs = list(AssetBotConfig.objects.filter(user=user)
                   .order_by("asset_class", "name"))
    now = timezone.now()
    since_24h = now - timedelta(hours=24)
    trades = AssetBotTrade.objects.filter(config__user=user)

    open_by = dict(trades.filter(status__in=("OPEN", "CLOSE_PENDING"))
                   .order_by().values("config_id").annotate(n=Count("id"))
                   .values_list("config_id", "n"))
    activity = {r["config_id"]: r for r in (
        trades.order_by().values("config_id").annotate(
            opens_24h=Count("id", filter=Q(opened_at__gte=since_24h)),
            last_open=Max("opened_at"),
            last_close=Max("closed_at", filter=Q(status="CLOSED"))))}
    closed = {}
    for r in (trades.filter(status="CLOSED", closed_at__gte=since_24h)
              .annotate(**_world_stamps())
              .order_by()
              .values("config_id", "paper", "w_broker", "w_env")
              .annotate(n=Count("id"), s=Sum("pnl"), m=Count("pnl"))):
        world = world_of({"paper": r["paper"],
                          "metadata": {"broker": r["w_broker"],
                                       "broker_env": r["w_env"]}})
        slot = closed.setdefault(r["config_id"], {})
        n, s, m = slot.get(world, (0, 0.0, 0))
        slot[world] = (n + r["n"], s + float(r["s"] or 0), m + r["m"])

    worlds = config_worlds(user, configs)
    cadence = _bot_tick_cadence_seconds()
    late_after = cadence * BOT_TICK_OVERDUE_FACTOR
    rows = []
    for cfg in configs:
        act = activity.get(cfg.id) or {}
        by_world = closed.get(cfg.id) or {}
        ccy = (cfg.base_currency or "USD").upper()
        # Sum() over no rows is None. Coercing it to Decimal("0") printed a
        # flat "0.00" in the P&L column for a bot that closed nothing at all,
        # which is indistinguishable from a bot that traded and broke even.
        measured = {w: v for w, v in by_world.items() if v[2]}
        pnl_24h = (round(next(iter(measured.values()))[1], 2)
                   if len(measured) == 1 else None)
        pnl_cells = [{"world": w, "name": WORLD_NAME[w],
                      "pnl": round(v[1], 2),
                      "text": _money(round(v[1], 2), ccy)}
                     for w, v in sorted(measured.items(),
                                        key=lambda kv: (WORLDS + ("",)).index(kv[0]))]
        last_close = act.get("last_close")
        cooldown_remaining_min = 0
        if last_close and (cfg.cool_down_minutes or 0) > 0:
            elapsed_min = (now - last_close).total_seconds() / 60
            cooldown_remaining_min = max(
                0, int(cfg.cool_down_minutes - elapsed_min))
        # HEALTH FROM THE HEARTBEAT (2026-11-07): each bot's own tick
        # (safety.write_heartbeat's extras["last_tick_at"]) against the
        # tick's cadence, as the band reads it — never "traded in 6 h".
        age = heartbeat_age_seconds(cfg)
        if not cfg.enabled:
            health, health_title = "OFF", "Disabled: it does not tick."
        elif age is None:
            health, health_title = "IDLE", WHY["no_tick"]
        elif age > late_after:
            health = "IDLE"
            health_title = (f"Enabled, its own tick is late: last tick "
                            f"{_ago(age)}, against a {cadence / 60:.0f} min "
                            f"schedule.")
        else:
            health = "ALIVE"
            health_title = (f"Its own tick is on time: last tick {_ago(age)}, "
                            f"every {cadence / 60:.0f} min.")
        candidates = [x for x in (act.get("last_open"), last_close) if x]
        rows.append({
            "config": cfg,
            "world": worlds.get(cfg.id, "live"),
            "open_count": open_by.get(cfg.id, 0),
            "opens_24h": act.get("opens_24h") or 0,
            "closed_24h": sum(v[0] for v in by_world.values()),
            "pnl_24h": pnl_24h,
            "pnl_cells": pnl_cells,
            "cooldown_remaining_min": cooldown_remaining_min,
            "last_activity": max(candidates) if candidates else None,
            "tick_age": age,
            "tick_text": _ago(age) if age is not None else "",
            "health": health,
            "health_title": health_title,
            "is_alive": health == "ALIVE",
        })

    enabled = [r for r in rows if r["config"].enabled]
    live_mode = [r for r in enabled if r["config"].mode == "live"]
    context = {
        "rows": rows,
        "n_configs": len(configs),
        # With no configs at all there is no population to count enabled,
        # live-mode or alive members of — an em-dash, not four confident
        # zeros under four labels.
        "n_enabled": (len(enabled) if configs else DASH),
        # REAL-MONEY BOTS: enabled live-mode configs on a REAL account (or
        # whose route cannot be read); DEMO: on a demo account.
        "n_live": (sum(1 for r in live_mode if r["world"] != "demo")
                   if configs else DASH),
        "n_live_demo": (sum(1 for r in live_mode if r["world"] == "demo")
                        if configs else DASH),
        "n_alive": (sum(1 for r in rows if r["health"] == "ALIVE")
                    if rows else DASH),
        "cadence_min": round(cadence / 60),
        # The link to the bots page, where Toggle and Tick are: for the
        # users their endpoints accept (views_admin_hq._admin_only refuses
        # everyone but a superuser). No form is drawn here, so no CSRF
        # token is handed in (2026-11-12, P1).
        "can_operate": bool(getattr(user, "is_superuser", False)),
        # This tab lists the TAKE TRADE lanes too; the bots page lists the
        # fleet without them (views_asset_bots), so the line says where a
        # lane's own switch is.
        "has_manual_lane": any(_is_manual_config(c) for c in configs),
    }
    return _fragment("dashboard/_command_bots.html", context)
