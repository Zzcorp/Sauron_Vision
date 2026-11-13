"""/design/kit/: the kit on one page, for staff (UI plan §7, S1a, 2026-11-06).

Every component of static/css/sv-kit.css on synthetic content, so a
designer, a reviewer or the screenshot harness can see the whole vocabulary
at every width without hunting through the platform for a page that
happens to show a demo row, a stale price or a danger dialog.

Nothing on it is real: no account, no position, no quote, no model, no
broker is read, and no control does anything (every button is type
"button" with no handler, the inputs sit in no form). Staff only; anyone
else, signed in or not, gets the 404 an unknown URL gets.
"""
from django.http import Http404
from django.shortcuts import render

from core.views_book import is_staff

#: §3: the palette, by role, as the tokens name it.
PALETTE = (
    ("Surfaces", (
        ("--sv-bg-0", "#040B07", "the void: page, chart, input wells"),
        ("--sv-bg-1", "#07130C", "cards, panels, sidebar, rail"),
        ("--sv-bg-2", "#0D1B14", "raised: popovers, dialogs, heads"),
        ("--sv-bg-3", "#14231B", "controls, row hover"),
        ("--sv-bg-4", "#1B2C23", "selected row, pressed control"),
    )),
    ("Lines", (
        ("--sv-line-1", "#14261D", "hairlines between rows"),
        ("--sv-line-2", "#1D3528", "card and input borders"),
        ("--sv-line-3", "#2C4739", "strong and hover borders"),
    )),
    ("Ink", (
        ("--sv-ink-1", "#E6F1EA", "values, primary text"),
        ("--sv-ink-2", "#ACC4B6", "secondary text, zero"),
        ("--sv-ink-3", "#839B8D", "labels, captions, axes, unknown"),
        ("--sv-ink-4", "#55665D", "disabled and placeholder only"),
    )),
    ("Meaning", (
        ("--sv-eye", "#00E868", "the Eye: live, selected, focus"),
        ("--sv-up", "#24B582", "up, gain, long, buy"),
        ("--sv-down", "#FF6B6E", "down, loss, short, sell; errors"),
        ("--sv-up-fill", "#1FA374", "up candles, bars, volume"),
        ("--sv-down-fill", "#E5484D", "down candles, bars, volume"),
        ("--sv-real", "#CC3A40", "REAL money: the only solid red"),
        ("--sv-demo", "#D6BC5E", "DEMO money: a gold outline"),
        ("--sv-warn", "#F29B38", "warning, stale"),
        ("--sv-ai", "#A48BFF", "a model wrote or spends it"),
    )),
    ("Chart series", (
        ("--sv-cat-1", "#3987E5", "slot 1"),
        ("--sv-cat-2", "#D95926", "slot 2"),
        ("--sv-cat-3", "#9085E9", "slot 3"),
        ("--sv-cat-4", "#C98500", "slot 4"),
        ("--sv-cat-5", "#D55181", "slot 5"),
    )),
)

#: §4.3: the type scale (at the 1280-1679 px tier; the page shows the
#: tier the browser is in).
SCALE = (
    ("--sv-fs-hero", "Hero figure", "mono"),
    ("--sv-fs-figure", "KPI figure", "mono"),
    ("--sv-fs-title", "Page and section title", "sans"),
    ("--sv-fs-lead", "Card value, dialog text", "sans"),
    ("--sv-fs-base", "Body, cells, controls", "sans"),
    ("--sv-fs-small", "Secondary, chips, table heads", "sans"),
    ("--sv-fs-micro", "Labels, axes, ages", "sans"),
)

#: A positions table on synthetic rows: one per world, gains, a loss, an
#: estimate, a stale price, a closed market.
ROWS = (
    {"sym": "EURUSD", "sub": "forex · bot 3 · 2 h", "side": "up", "side_word": "Long",
     "world": "live", "qty": "20000.00000000", "entry": "1.08420", "mark": "1.08745",
     "fresh": "live", "src": "etoro", "age": "", "pnl": "+65.00", "pnl_cls": "up",
     "pnl_src": "eToro's own · 8 s", "r": "+1.25R"},
    {"sym": "XAUUSD", "sub": "commodity · manual · 1 d", "side": "down", "side_word": "Short",
     "world": "live", "qty": "1.50000000", "entry": "2,658.40", "mark": "2,648.12",
     "fresh": "recent", "src": "etoro", "age": "12 s", "pnl": "+15.42", "pnl_cls": "up",
     "pnl_src": "eToro's own · 8 s", "r": "+0.62R"},
    {"sym": "BTCUSD", "sub": "crypto · bot 22 · 5 h", "side": "up", "side_word": "Long",
     "world": "demo", "qty": "0.05000000", "entry": "92,410.0", "mark": "91,230.5",
     "fresh": "live", "src": "binance_ws", "age": "", "pnl": "-58.98", "pnl_cls": "down",
     "pnl_src": "eToro's own · 8 s", "r": "-0.71R"},
    {"sym": "AAPL", "sub": "stock · bot 14 · 3 d", "side": "up", "side_word": "Long",
     "world": "live", "qty": "4.00000000", "entry": "228.10", "mark": "227.06",
     "fresh": "closed", "src": "etoro", "age": "", "pnl": "-4.16", "pnl_cls": "down",
     "pnl_src": "eToro's own · market closed", "r": "-0.21R"},
    {"sym": "GBPUSD", "sub": "forex · paper lane · 1 h", "side": "down", "side_word": "Short",
     "world": "paper", "qty": "10000.00000000", "entry": "1.29110", "mark": "1.29044",
     "fresh": "stale", "src": "yfinance_public", "age": "3 min", "pnl": "≈ +6.60", "pnl_cls": "",
     "pnl_src": "estimate · Yahoo quote, 3 min", "r": "+0.18R"},
)

#: The number rules (§4.4) through the two filters, on synthetic values.
QTY_SAMPLES = ("20000.00000000", "0.05000000", "1.50000000", "12.00000000",
               "0.123456789", None)
SRC_SAMPLES = ("yfinance_public", "binance_ws", "etoro", "oanda_stream",
               "finnhub_ws", "paper")


def design_kit(request):
    if not is_staff(request.user):
        raise Http404()
    return render(request, "dashboard/design_kit.html", {
        "palette": PALETTE,
        "scale": SCALE,
        "rows": ROWS,
        "qty_samples": QTY_SAMPLES,
        "src_samples": SRC_SAMPLES,
        "page_id": "design_kit",
    })
