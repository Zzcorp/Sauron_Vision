"""The live hooks contract: what display stages never rename or drop
(UI plan §11, S1a, 2026-11-06).

Live updates, the ticket, the close path and the tests reach the page
through a small set of hooks: data attributes, ids, the classes the
scripts read, and the window globals the scripts publish. A display stage
restyles the page around them; it must never rename or drop one, because
nothing would say so — the price would simply stop moving, the ticket stop
opening, a row stop closing.

This module records today's inventory, file by file, and fails when a
file holds fewer of a hook than it did. Where a hook moves on purpose, the
move is written here with its reason, and the inventory is updated with it.
Hooks a branch adds (railfilters: data-sv-fhost, data-sv-list,
data-sv-rail-n, data-sv-gone-toggle, #hbSignalRows, .sv-pinned) join the
inventory when that branch merges. They joined on 2026-11-07, when
origin/main (railfilters, #90, and the rest of #89-#95) merged into this
branch; data-sv-gone-toggle, named from an earlier draft, never landed
under that name. LEFT THE RAIL landed as three hooks, recorded instead
(review of the merge, 2026-11-07): the section of departures
(data-sv-gone), the chip that toggles it, a data-f-toggle like the other
toggling chips, and the host's own state (data-f-gone).

MARKET SHUT joined the same way on 2026-11-12, when origin/main (#99, #100
and #101: the badge on a card whose market is shut, the SHUT chip, the
optional MARKET SHUT section) merged into this branch: four hooks, named
with their readers in DATA_ATTRS, and four counts that rose with main's
markup, written above RECORDED.

ONE PRICE EVERYWHERE (#105, merged 2026-11-13, just before S1a's #106)
joined on 2026-11-13 (the old-design redo's B0, plan §11: "the inventory
takes them in when it merges"), counted on origin/main 1b94a50: the cells
the one painter finds by attribute (the data-q family; the cells of a
price apart from Ask Sauron's suggestion buttons, which share data-q), the
position row's attributes its card copies into them (data-pos-q...,
data-pos-spark-...), its quote blocks (data-sv-quotes, printed by
{% q_json %}) and its clock (data-sv-now, in _partials/sv_venue.html,
which base.html includes), the painter itself (window.SVVenue) and every
call a display file makes to it, and the chart handle's keys it reads and
calls (svCharts[id].symbol, .source, .setNow, .caption, .series, .bars),
with the handle's own refresh and tick that §11 already named. A shell or
page rewrite that dropped one would leave a price that simply stops
moving. Two of #105's lines raised counts recorded before (the review of
B0): .tk-stale in sv-instrument-live.js (1 -> 2), .up and .down in
sv-venue.js (0 -> 2 each).

How each kind is counted, per file (templates, scripts, the template tags):
  * a data attribute: every occurrence of the attribute's name, as a whole
    token (data-sv-live is not counted inside data-sv-live-key);
  * an id: as an id="…" attribute, a json_script:"…" block, a
    getElementById('…') call, or a '#…' selector inside a quoted string;
  * a class the scripts read: as a token of a class="…" attribute (the
    Django tags inside it read through), and in scripts as a '.…'
    selector inside a quoted string, or a quoted string that is the class
    alone (a classList argument is one). A class family (sv-flash--*,
    sv-world--*) counts its prefix;
  * a window global: its definition (window.X =, w.X =, root.X =, SV.x =,
    w.SV.x =);
  * a call to the painter (SVVenue.x(...)): per file, so a display file
    that stops calling it is seen (base.html's socket, the preview, the
    sparks; the widget, the live region, the Horde, the instrument page,
    the position card);
  * a template tag or an include the painter needs ({% q_json %}, the
    sv_venue.html include): per template;
  * a key of a chart's handle (svCharts[id].x): its key in the object the
    widget sets svCharts[id] to. Its readers are the feed's own scripts
    (sv-venue.js, sv-instrument-live.js): a display stage that restyles
    them (B3's sheet, B9's "now" line, B6's instrument page) keeps every
    call; the widget is S4's (B10).

Display only: nothing here reads or writes data. Run with:
    python manage.py test tests.test_live_hooks_inventory
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

ROOT = pathlib.Path(settings.BASE_DIR)

#: Where hooks live: the templates, the scripts, the template tags (which
#: print the money-world chip and the unknown dash from Python).
SCANNED = ("templates/**/*.html", "static/js/*.js", "core/templatetags/*.py")

DATA_ATTRS = (
    "data-sv-live", "data-sv-live-key", "data-sv-live-status",
    "data-dq", "data-ticket", "data-decimals",
    "data-flash", "data-sv-noflash", "data-sv-count",
    "data-mark-source", "data-sv-at", "data-sv-close-trade",
    "data-sv-overlay", "data-sv-open", "data-sv-close", "data-sv-persist",
    "data-sv-backdrop", "data-sv-focus", "data-sv-lock",
    "data-nav-page-id", "data-instrument-live",
    # railfilters' (2026-11-07, at its merge, as plan §11 says): the filter
    # hosts, the lists the filters order, the rail's counts.
    "data-sv-fhost", "data-sv-list", "data-sv-rail-n",
    # LEFT THE RAIL, the hook plan §11 called data-sv-gone-toggle, as it
    # landed (review of the merge, 2026-11-07): the section the departures
    # sit in (data-sv-gone), the chips that toggle a filter, LEFT among
    # them (data-f-toggle), and the host's own state that shows or hides
    # the section (data-f-gone). Counted on origin/main ede54d0.
    "data-sv-gone", "data-f-toggle", "data-f-gone",
    # ONE PRICE EVERYWHERE (#105), joined on 2026-11-13 (counted on
    # origin/main 1b94a50). static/js/sv-venue.js, the one painter, finds
    # every price cell by attribute, never by text:
    #   data-q          the symbol of a cell the painter writes;
    #   data-q-f        the field it prints (price, bid, ask, spread, chg,
    #                   words, age, since, away, rr…);
    #   data-q-side     a position's closing side;
    #   data-q-title    a cell whose hover is painted too (its own tail);
    #   data-q-spark    a sparkline keyed to a symbol (drawn, not written);
    #   data-q-fam, data-q-bars   whose bars a spark draws;
    #   data-q-dot      the spark's "now" dot, which the painter adds;
    #   data-q-state    the cell's state the painter writes (stale, shut,
    #                   none), which sv-venue.css reads;
    #   data-q-ref, data-q-below  the figures beside a price: the level a
    #                   "since" or "away" counts from, and on which side;
    #   data-q-o, data-q-stop, data-q-target, data-q-max  the rail card's
    #                   live R:R (the order, its levels, the bound);
    #   data-sv-quotes  the quote blocks a response carries ({% q_json %}),
    #                   ingested before the cells are painted;
    #   data-sv-now     the server's clock, so ages count from it.
    "data-q", "data-q-f", "data-q-side", "data-q-title", "data-q-spark",
    "data-q-fam", "data-q-bars", "data-q-dot", "data-q-state",
    "data-q-ref", "data-q-below", "data-q-o", "data-q-stop",
    "data-q-target", "data-q-max", "data-sv-quotes", "data-sv-now",
    # The position row's (positions_list.html), which sv-position-card.js
    # reads by key (val(row, "q-side")) and copies into the data-q cells of
    # the card it paints (the review of B0).
    "data-pos-q", "data-pos-q-side", "data-pos-q-entry", "data-pos-q-stop",
    "data-pos-q-target", "data-pos-spark-fam", "data-pos-spark-bars",

    # MARKET SHUT (main's #99, #100 and #101), joined at their merge into
    # this branch (2026-11-12, counted on origin/main 4c1ebcc). Each is
    # read by the rail's sheet, by its script or by main's own tests:
    #   data-market     "shut" on a rail card and on a headband row whose
    #                   market is shut now. The SHUT chip's rule hides
    #                   exactly those rows (sv-rail.css), and the badge is
    #                   found by it (tests/test_rail_market_shut.py);
    #   data-f-shutoff  the host's state for that chip (the badged cards
    #                   hidden): the server writes it on both hosts
    #                   (rail_host_attrs.html), sv-rail-filters.js rewrites
    #                   it on a press, the sheet reads it;
    #   data-f-shut     the host's state that shows the MARKET SHUT section
    #                   (the optional hold, the switch signal_market_hold):
    #                   written the same way, read by the sheet, and by the
    #                   script to count the section's filtered rows;
    #   data-sv-shut    that section: the sheet hides it until its host
    #                   says shown, the script counts the rows inside it.
    # Not held: data-waiting, main's marker on a row of that section. No
    # script, no rule and no test reads it today, so nothing breaks without
    # it; it joins when something does.
    "data-market", "data-f-shutoff", "data-f-shut", "data-sv-shut",
)

IDS = (
    "signalsRail", "railSignals", "railSignalsBody",
    # railfilters' headband SIGNALS rows (2026-11-07, at its merge).
    "hbSignalRows",
    "svCloseAll", "clock", "svBannerStack",
    # The chart's json_script blocks, named after the widget: the page
    # prints them, the widget reads '<chart_id>-positions' / '-signals'.
    "instrument-main-chart-positions", "instrument-main-chart-signals",
)

#: The widget's reader of those blocks (chart_widget.html, pageJson()).
CHART_JSON_SUFFIXES = ("-positions", "-signals")

#: The chart handle's methods (svCharts[id], set by chart_widget.html):
#: §11's refresh and tick, and #105's for the one painter (joined
#: 2026-11-13): series() and bars() it draws the "now" line on and reads,
#: caption() the line under the chart it writes, setNow(v) the value the
#: scale must hold.
CHART_HANDLE = ("refresh", "tick", "series", "bars", "caption", "setNow",
                # what the painter reads off the handle (the review of B0):
                # without its symbol chart() returns at once, its caption
                # names the source.
                "symbol", "source")

CLASSES = (
    "sv-unknown", "sv-age", "up", "down", "tk-stale", "sv-row--live",
    "sv-sel-bar",
    # railfilters' pinned card, bar dropdown and headband card (2026-11-07,
    # at its merge).
    "sv-pinned",
)
CLASS_FAMILIES = ("sv-flash--", "sv-world--")

GLOBALS = (
    "svTakeTrade", "svTakeTradeAsset", "svCloseTrade",
    "svCharts", "svLevels", "svSignalDots", "svHoverCards",
    "svRenderSparks", "svWheelMarquee", "svLiveRefresh", "svRenderDonuts",
    "svRenderLines", "SAURON_CHART_COLORS",
)
SV_NAMESPACE = ("overlay", "ages", "flash", "dwell", "popup", "tour", "council")

#: The one painter (#105): defined in sv-venue.js (root.SVVenue =), called
#: from the display files; each file's calls are counted.
PAINTERS = ("SVVenue",)
#: The template tags and includes the painter needs, per template.
TEMPLATE_TAGS = ("q_json",)
INCLUDES = ("_partials/sv_venue.html",)


def _files():
    seen = []
    for pattern in SCANNED:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                seen.append(path)
    return seen


def _rel(path):
    return path.relative_to(ROOT).as_posix()


def _token(name):
    return r"(?<![\w-])%s(?![\w-])" % re.escape(name)


_QUOTED = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")


def _class_attrs(text):
    """The values of every class="…" (or class='…') attribute, read through
    the Django tags inside them ({% if %}up{% endif %}, {{ x }})."""
    out = []
    for m in re.finditer(r"""class=(\\?["'])""", text):
        quote = m.group(1)[-1]
        i, buf = m.end(), []
        while i < len(text):
            if text.startswith("{%", i) or text.startswith("{{", i):
                close = "%}" if text.startswith("{%", i) else "}}"
                j = text.find(close, i + 2)
                if j < 0:
                    break
                buf.append(" " + text[i + 2:j] + " ")
                i = j + 2
                continue
            ch = text[i]
            if ch == "\\" and i + 1 < len(text) and text[i + 1] == quote:
                break
            if ch == quote or ch == "\n" and len(buf) > 400:
                break
            buf.append(ch)
            i += 1
        out.append("".join(buf))
    return out


def count_data_attr(text, name):
    return len(re.findall(_token(name), text))


def count_id(text, name):
    tok = re.escape(name)
    n = len(re.findall(r"""\bid=\\?["']%s\\?["']""" % tok, text))
    n += len(re.findall(r"""getElementById\(\s*["']%s["']\s*\)""" % tok, text))
    n += len(re.findall(r"""json_script:\s*["']%s["']""" % tok, text))
    for q in _QUOTED.findall(text):
        n += len(re.findall(r"#%s(?![\w-])" % tok, q))
    return n


def count_class(text, name, family=False):
    pat = (r"(?<![\w-])%s[\w{}-]*" % re.escape(name)) if family else _token(name)
    n = 0
    for value in _class_attrs(text):
        n += len(re.findall(pat, value))
    for m in _QUOTED.finditer(text):
        if re.search(r"class=\\?$", text[max(0, m.start() - 7):m.start()]):
            continue  # a class attribute: counted above
        body = m.group(0)[1:-1]
        if family:
            # '.sv-flash--up' in a selector, or a class list string such as
            # "sv-flash sv-flash--" + dir, or "sv-flash--up" alone.
            n += len(re.findall(pat, body))
            continue
        n += len(re.findall(r"\.%s(?![\w-])" % re.escape(name), body))
        if body == name:
            n += 1
    return n


def count_global(text, name):
    return len(re.findall(r"(?:\bwindow|\bw|\broot)\.%s\s*=(?!=)" % re.escape(name), text))


def count_price_cells(text):
    """data-q cells whose symbol is the data's ({{ x }} in a template,
    ${x} in a script's markup): a price the painter writes. Ask Sauron's
    suggestion buttons share data-q with a question for its value, and a
    lost price cell must not hide behind an added question."""
    return len(re.findall(r"""(?<![\w-])data-q=\\?["'](?:\{\{|\$\{)""", text))


def count_calls(text, name):
    """Calls to a global's methods: name.method( (the definition is not)."""
    return len(re.findall(r"(?<![\w$])%s\s*\.\s*[A-Za-z_$][\w$]*\s*\(" % re.escape(name), text))


def count_tag(text, name):
    return len(re.findall(r"{%%\s*%s\b" % re.escape(name), text))


def count_include(text, name):
    return len(re.findall(r"""{%%\s*include\s+["']%s["']""" % re.escape(name), text))


def count_sv(text, name):
    return len(re.findall(r"(?:\bwindow\.SV|\bw\.SV|(?<![\w.])SV)\.%s\s*=(?!=)"
                          % re.escape(name), text))


_HANDLE = re.compile(r"\bsvCharts\s*\[[^\]\n]+\]\s*=\s*\{")


def count_handle_method(text, name):
    """How many times `name` is a key of the object a chart's handle is
    set to (svCharts[id] = {...}): keys at the literal's own depth only,
    strings and comments read through."""
    n = 0
    key = re.compile(r"(?<![\w$.])%s\s*:" % re.escape(name))
    for m in _HANDLE.finditer(text):
        i, depth, own = m.end(), 1, []
        while i < len(text) and depth:
            ch = text[i]
            if ch in "'\"`":
                j = i + 1
                while j < len(text) and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                i = j + 1
                own.append(" ")
                continue
            if text.startswith("//", i):
                j = text.find("\n", i)
                i = len(text) if j < 0 else j
                own.append(" ")
                continue
            if text.startswith("/*", i):
                j = text.find("*/", i + 2)
                i = len(text) if j < 0 else j + 2
                own.append(" ")
                continue
            if ch in "{([":
                depth += 1
            elif ch in "})]":
                depth -= 1
            elif depth == 1:
                own.append(ch)
            i += 1
        n += len(key.findall("".join(own)))
    return n


def inventory():
    """{hook: {file: count}} for the tree as it stands."""
    inv = {}

    def put(hook, rel, n):
        if n:
            inv.setdefault(hook, {})[rel] = n

    for path in _files():
        text = path.read_text(encoding="utf-8")
        rel = _rel(path)
        for name in DATA_ATTRS:
            put(name, rel, count_data_attr(text, name))
        for name in IDS:
            put("#" + name, rel, count_id(text, name))
        for suffix in CHART_JSON_SUFFIXES:
            put("json:" + suffix, rel,
                len(re.findall(r"""pageJson\(\s*['"]%s['"]\s*\)""" % re.escape(suffix), text)))
        for name in CHART_HANDLE:
            put("svCharts[id]." + name, rel, count_handle_method(text, name))
        for name in CLASSES:
            put("." + name, rel, count_class(text, name))
        for name in CLASS_FAMILIES:
            put("." + name + "*", rel, count_class(text, name, family=True))
        for name in GLOBALS + PAINTERS:
            put("window." + name, rel, count_global(text, name))
        for name in SV_NAMESPACE:
            put("SV." + name, rel, count_sv(text, name))
        put("data-q (price cell)", rel, count_price_cells(text))
        for name in PAINTERS:
            put(name + ".*()", rel, count_calls(text, name))
        if rel.endswith(".html"):
            for name in TEMPLATE_TAGS:
                put("{% " + name + " %}", rel, count_tag(text, name))
            for name in INCLUDES:
                put("include " + name, rel, count_include(text, name))
    return inv


# ── The recorded inventory (2026-11-07, origin/main ede54d0) ────────────
# Generated by inventory() on that tree: the main this branch merged on
# 2026-11-07, so the S1a pull request is held to every hook main carries.
# It was first recorded on the S0 tip (328d924, 2026-11-06). In between,
# main moved one hook on purpose: the headband SIGNALS rows left
# base.html for templates/_partials/signal_rows_compact.html (railfilters,
# #90), taking one .sv-age and one data-sv-at with them (base.html 4 -> 3
# and 7 -> 6; the partial 1 and 1). Every other count is main's own, the
# same as the S0 tip's or higher, and railfilters' hooks joined above.
# LEFT THE RAIL's three hooks (data-sv-gone, data-f-toggle, data-f-gone)
# joined on 2026-11-07 from the same tree, at the review of the merge.
# MARKET SHUT (2026-11-12, origin/main 4c1ebcc: #99, #100 and #101 merged
# into this branch). Updated deliberately, from inventory() on that tree,
# so the pull request is held to main's own counts again. Four hooks
# joined, each explained where DATA_ATTRS names it: data-market,
# data-f-shutoff, data-f-shut, data-sv-shut. Four counts rose with main's
# markup and are recorded at main's number: data-f-toggle in the signals'
# chips, 5 -> 7 (the SHUT chip, in its two spellings: the badged cards'
# and, with the optional hold on, the section's); data-sv-rail-n in the
# same partial, 4 -> 6 (the chip's two counts, "shut" and "waiting"), in
# the rail partial, 0 -> 1 (the MARKET SHUT section's count) and in
# base.html, 6 -> 7 (the headband's MARKET SHUT cell). No count fell: on
# that day the merged tree held every hook of main's in every file, and
# more only where the magic's own files read one (sv-moments.js, the kit
# page).
# ONE PRICE EVERYWHERE (#105, merged after S1a) joined on 2026-11-13, at
# the old-design redo's B0: its twenty-three hooks (the data-q family,
# data-sv-quotes, data-sv-now, and the chart handle's six methods, §11's
# refresh and tick among them) from inventory() on origin/main 1b94a50,
# each at main's own count. Every count recorded before stands unchanged.
# A file may gain a hook; it may not lose one. Each hook below must also be
# found somewhere (no hook is recorded at zero), so a hook renamed
# everywhere at once fails too.
RECORDED = {
    # THE REVIEW OF B0 (2026-11-13): #105's hooks the first count missed,
    # counted by inventory() on origin/main 1b94a50 (see DATA_ATTRS,
    # CHART_HANDLE, PAINTERS, TEMPLATE_TAGS, INCLUDES, count_price_cells).
    'data-pos-q': {
        'templates/dashboard/positions_list.html': 1,
    },
    'data-pos-q-entry': {
        'templates/dashboard/positions_list.html': 1,
    },
    'data-pos-q-side': {
        'templates/dashboard/positions_list.html': 1,
    },
    'data-pos-q-stop': {
        'templates/dashboard/positions_list.html': 1,
    },
    'data-pos-q-target': {
        'templates/dashboard/positions_list.html': 1,
    },
    'data-pos-spark-bars': {
        'templates/dashboard/positions_list.html': 1,
    },
    'data-pos-spark-fam': {
        'templates/dashboard/positions_list.html': 1,
    },
    'svCharts[id].source': {
        'templates/_partials/chart_widget.html': 1,
    },
    'svCharts[id].symbol': {
        'templates/_partials/chart_widget.html': 1,
    },
    'window.SVVenue': {
        'static/js/sv-venue.js': 1,
    },
    'data-q (price cell)': {
        'core/templatetags/quote_tags.py': 2,
        'templates/_partials/deal_ticket.html': 3,
        'templates/_partials/dh_item.html': 8,
        'templates/_partials/signal_rail_items.html': 2,
        'templates/base.html': 9,
        'templates/dashboard/_command_portfolio.html': 1,
        'templates/dashboard/_position_summary.html': 2,
        'templates/dashboard/instrument_detail.html': 9,
        'templates/dashboard/instruments_list.html': 10,
        'templates/dashboard/news_detail.html': 2,
        'templates/dashboard/portfolio_overview.html': 2,
        'templates/dashboard/positions_list.html': 3,
    },
    'SVVenue.*()': {
        'static/js/sv-horde.js': 2,
        'static/js/sv-instrument-live.js': 2,
        'static/js/sv-position-card.js': 1,
        'templates/_partials/chart_widget.html': 1,
        'templates/_partials/live_region.html': 1,
        'templates/base.html': 8,
    },
    '{% q_json %}': {
        'templates/_partials/signal_rail_items.html': 1,
        'templates/_partials/sv_venue.html': 1,
        'templates/dashboard/_command_portfolio.html': 1,
        'templates/dashboard/_live_shell.html': 1,
    },
    'include _partials/sv_venue.html': {
        'templates/base.html': 1,
    },
    '#clock': {
        'static/js/sv-flash.js': 1,
        'templates/base.html': 2,
    },
    '#hbSignalRows': {
        'templates/base.html': 2,
    },
    '#instrument-main-chart-positions': {
        'templates/dashboard/instrument_detail.html': 1,
    },
    '#instrument-main-chart-signals': {
        'templates/dashboard/instrument_detail.html': 1,
    },
    '#railSignals': {
        'templates/base.html': 8,
    },
    '#railSignalsBody': {
        'static/js/sv-rail-filters.js': 2,
        'templates/base.html': 10,
    },
    '#signalsRail': {
        'templates/_tour.html': 1,
        'templates/base.html': 7,
    },
    '#svBannerStack': {
        'static/js/sv-flash.js': 1,
        'templates/base.html': 3,
    },
    '#svCloseAll': {
        'templates/dashboard/positions_list.html': 2,
    },
    '.down': {
        'core/templatetags/sauron_tags.py': 1,
        'static/js/sv-close-advice.js': 1,
        'static/js/sv-flash.js': 1,
        'static/js/sv-horde.js': 3,
        'static/js/sv-instrument-live.js': 2,
        'static/js/sv-news-dwell.js': 1,
        'static/js/sv-position-card.js': 5,
        'static/js/sv-venue.js': 2,
        'templates/_partials/capital_card.html': 3,
        'templates/_partials/chart_widget.html': 9,
        'templates/_partials/dh_item.html': 4,
        'templates/_partials/signal_rail_items.html': 2,
        'templates/_partials/ticker_item.html': 2,
        'templates/base.html': 28,
        'templates/dashboard/_backtest_metrics.html': 1,
        'templates/dashboard/_command_bots.html': 2,
        'templates/dashboard/_command_history.html': 8,
        'templates/dashboard/_command_live.html': 5,
        'templates/dashboard/_command_portfolio.html': 7,
        'templates/dashboard/_eye_body.html': 2,
        'templates/dashboard/_news_metrics.html': 1,
        'templates/dashboard/_signals_metrics.html': 1,
        'templates/dashboard/ai_insights.html': 3,
        'templates/dashboard/ai_journal.html': 2,
        'templates/dashboard/ai_tasks_list.html': 3,
        'templates/dashboard/allocator.html': 1,
        'templates/dashboard/asset_bots.html': 3,
        'templates/dashboard/audit_log.html': 2,
        'templates/dashboard/backtest_list.html': 9,
        'templates/dashboard/bot_backtest.html': 3,
        'templates/dashboard/bot_backtest_detail.html': 10,
        'templates/dashboard/bot_console.html': 4,
        'templates/dashboard/bot_performance.html': 7,
        'templates/dashboard/brain.html': 2,
        'templates/dashboard/briefing.html': 2,
        'templates/dashboard/calibration.html': 2,
        'templates/dashboard/command.html': 2,
        'templates/dashboard/consolidation.html': 1,
        'templates/dashboard/desk.html': 3,
        'templates/dashboard/earnings_reviews.html': 1,
        'templates/dashboard/economic_calendar.html': 3,
        'templates/dashboard/evidence.html': 12,
        'templates/dashboard/evolution.html': 1,
        'templates/dashboard/eye_exposure.html': 4,
        'templates/dashboard/eye_fills.html': 5,
        'templates/dashboard/eye_gate_events.html': 3,
        'templates/dashboard/generated.html': 2,
        'templates/dashboard/horizon.html': 4,
        'templates/dashboard/hypotheses.html': 1,
        'templates/dashboard/instrument_detail.html': 3,
        'templates/dashboard/instruments_list.html': 2,
        'templates/dashboard/intelligence.html': 2,
        'templates/dashboard/knowledge.html': 5,
        'templates/dashboard/news_feed.html': 3,
        'templates/dashboard/ops.html': 8,
        'templates/dashboard/performance.html': 6,
        'templates/dashboard/personas.html': 2,
        'templates/dashboard/portfolio_overview.html': 3,
        'templates/dashboard/positions_list.html': 3,
        'templates/dashboard/promotions.html': 1,
        'templates/dashboard/research.html': 1,
        'templates/dashboard/risk_depth.html': 4,
        'templates/dashboard/rule_control.html': 1,
        'templates/dashboard/setups.html': 3,
        'templates/dashboard/shares.html': 7,
        'templates/dashboard/short_proofs.html': 1,
        'templates/dashboard/signals_list.html': 3,
        'templates/dashboard/strategies_list.html': 4,
        'templates/dashboard/tax_lots.html': 4,
        'templates/dashboard/withdrawals.html': 1,
        'templates/investor/_panel_body.html': 5,
        'templates/landing/the_wall.html': 1,
    },
    '.sv-age': {
        'templates/_partials/broker_account.html': 1,
        'templates/_partials/notif_items.html': 1,
        'templates/_partials/signal_rows_compact.html': 1,
        'templates/_partials/ticker_item.html': 1,
        'templates/base.html': 3,
        'templates/dashboard/notifications_inbox.html': 1,
        'templates/dashboard/positions_list.html': 1,
        'templates/dashboard/research.html': 5,
        'templates/dashboard/strategies_list.html': 1,
        'templates/dashboard/system_map.html': 1,
    },
    '.sv-flash--*': {
        'static/js/sv-flash.js': 7,
    },
    '.sv-pinned': {
        'templates/base.html': 13,
    },
    '.sv-row--live': {
        'templates/base.html': 1,
        'templates/dashboard/asset_bots.html': 3,
        'templates/dashboard/positions_list.html': 2,
    },
    '.sv-sel-bar': {
        'static/js/sv-motion.js': 1,
        'templates/_partials/close_selection_bar.html': 1,
    },
    '.sv-unknown': {
        'static/js/sv-close-advice.js': 1,
        'static/js/sv-horde.js': 1,
        'static/js/sv-instrument-live.js': 1,
        'templates/_partials/broker_account.html': 2,
        'templates/_partials/capital_card.html': 6,
        'templates/_partials/deal_ticket.html': 3,
        'templates/_partials/position_group_row.html': 2,
        'templates/_partials/signal_rail_items.html': 2,
        'templates/base.html': 57,
        'templates/dashboard/_command_portfolio.html': 3,
        'templates/dashboard/_eye_body.html': 2,
        'templates/dashboard/brain.html': 2,
        'templates/dashboard/dashboard.html': 2,
        'templates/dashboard/hq_books.html': 2,
        'templates/dashboard/instrument_detail.html': 2,
        'templates/dashboard/news_detail.html': 15,
        'templates/dashboard/portfolio_overview.html': 9,
        'templates/dashboard/positions_list.html': 12,
        'templates/dashboard/research.html': 1,
        'templates/dashboard/strategies_list.html': 6,
        'templates/dashboard/system_map.html': 3,
        'templates/investor/_panel_body.html': 7,
    },
    '.sv-world--*': {
        'core/templatetags/sauron_tags.py': 2,
        'static/js/sv-activity.js': 1,
        'static/js/sv-horde.js': 2,
        'static/js/sv-position-card.js': 1,
        'templates/_partials/the_horde.html': 1,
    },
    '.tk-stale': {
        'static/js/sv-instrument-live.js': 2,
    },
    '.up': {
        'core/templatetags/sauron_tags.py': 1,
        'static/js/sv-close-advice.js': 1,
        'static/js/sv-flash.js': 1,
        'static/js/sv-horde.js': 3,
        'static/js/sv-instrument-live.js': 2,
        'static/js/sv-news-dwell.js': 1,
        'static/js/sv-position-card.js': 4,
        'static/js/sv-venue.js': 2,
        'templates/_partials/chart_widget.html': 15,
        'templates/_partials/dh_item.html': 4,
        'templates/_partials/signal_rail_items.html': 3,
        'templates/_partials/ticker_item.html': 2,
        'templates/base.html': 27,
        'templates/dashboard/_backtest_metrics.html': 1,
        'templates/dashboard/_command_bots.html': 4,
        'templates/dashboard/_command_history.html': 6,
        'templates/dashboard/_command_live.html': 4,
        'templates/dashboard/_command_portfolio.html': 6,
        'templates/dashboard/_eye_body.html': 2,
        'templates/dashboard/_news_metrics.html': 1,
        'templates/dashboard/_signals_metrics.html': 1,
        'templates/dashboard/_strategies_metrics.html': 1,
        'templates/dashboard/ai_insights.html': 3,
        'templates/dashboard/ai_journal.html': 1,
        'templates/dashboard/ai_tasks_list.html': 3,
        'templates/dashboard/allocator.html': 2,
        'templates/dashboard/asset_bots.html': 3,
        'templates/dashboard/audit_log.html': 1,
        'templates/dashboard/backtest_list.html': 6,
        'templates/dashboard/bot_backtest.html': 3,
        'templates/dashboard/bot_backtest_detail.html': 9,
        'templates/dashboard/bot_charts.html': 1,
        'templates/dashboard/bot_console.html': 3,
        'templates/dashboard/bot_performance.html': 7,
        'templates/dashboard/brain.html': 2,
        'templates/dashboard/briefing.html': 2,
        'templates/dashboard/brokers.html': 1,
        'templates/dashboard/calibration.html': 2,
        'templates/dashboard/command.html': 2,
        'templates/dashboard/consolidation.html': 3,
        'templates/dashboard/desk.html': 4,
        'templates/dashboard/discoveries.html': 2,
        'templates/dashboard/earnings_reviews.html': 1,
        'templates/dashboard/events.html': 1,
        'templates/dashboard/evidence.html': 12,
        'templates/dashboard/evolution.html': 1,
        'templates/dashboard/eye_exposure.html': 5,
        'templates/dashboard/eye_fills.html': 5,
        'templates/dashboard/eye_gate_events.html': 2,
        'templates/dashboard/generated.html': 2,
        'templates/dashboard/horizon.html': 3,
        'templates/dashboard/hypotheses.html': 1,
        'templates/dashboard/instrument_detail.html': 3,
        'templates/dashboard/instruments_list.html': 3,
        'templates/dashboard/intelligence.html': 2,
        'templates/dashboard/knowledge.html': 3,
        'templates/dashboard/news_feed.html': 2,
        'templates/dashboard/notifications_inbox.html': 1,
        'templates/dashboard/opportunities.html': 1,
        'templates/dashboard/ops.html': 3,
        'templates/dashboard/performance.html': 5,
        'templates/dashboard/personas.html': 2,
        'templates/dashboard/portfolio_overview.html': 2,
        'templates/dashboard/positions_list.html': 3,
        'templates/dashboard/promotions.html': 3,
        'templates/dashboard/research.html': 1,
        'templates/dashboard/risk_depth.html': 2,
        'templates/dashboard/rule_control.html': 2,
        'templates/dashboard/setups.html': 1,
        'templates/dashboard/shares.html': 6,
        'templates/dashboard/short_proofs.html': 2,
        'templates/dashboard/signals_list.html': 4,
        'templates/dashboard/strategies_list.html': 5,
        'templates/dashboard/tax_lots.html': 5,
        'templates/dashboard/withdrawals.html': 1,
        'templates/investor/_panel_body.html': 4,
        'templates/landing/the_wall.html': 1,
    },
    'SV.ages': {
        'static/js/sv-overlay.js': 1,
    },
    'SV.council': {
        'static/js/sv-council.js': 1,
    },
    'SV.dwell': {
        'static/js/sv-notif-card.js': 1,
    },
    'SV.flash': {
        'static/js/sv-flash.js': 1,
    },
    'SV.overlay': {
        'static/js/sv-overlay.js': 1,
    },
    'SV.popup': {
        'static/js/sv-notif-card.js': 1,
    },
    'SV.tour': {
        'static/js/sv-tour.js': 1,
    },
    'data-decimals': {
        'core/templatetags/sauron_tags.py': 1,
        'static/js/sv-instrument-live.js': 6,
        'templates/_partials/deal_ticket.html': 1,
        'templates/_partials/dh_item.html': 2,
        'templates/base.html': 9,
        'templates/dashboard/forensics_detail.html': 2,
        'templates/dashboard/instrument_detail.html': 3,
    },
    'data-dq': {
        'static/js/sv-instrument-live.js': 2,
        'templates/_partials/deal_ticket.html': 4,
    },
    'data-f-gone': {
        'static/js/sv-rail-filters.js': 2,
        'templates/_partials/rail_host_attrs.html': 1,
        'templates/base.html': 1,
    },
    'data-f-shut': {
        'static/js/sv-rail-filters.js': 2,
        'templates/_partials/rail_host_attrs.html': 2,
    },
    'data-f-shutoff': {
        'static/js/sv-rail-filters.js': 1,
        'templates/_partials/rail_host_attrs.html': 1,
    },
    'data-f-toggle': {
        'static/js/sv-rail-filters.js': 1,
        'templates/_partials/rail_sig_chips.html': 7,
        'templates/_partials/rail_watch_chips.html': 2,
    },
    'data-flash': {
        'static/js/sv-horde.js': 5,
    },
    'data-instrument-live': {
        'static/js/sv-instrument-live.js': 2,
        'templates/dashboard/instrument_detail.html': 3,
    },
    'data-mark-source': {
        'templates/dashboard/instrument_detail.html': 1,
        'templates/dashboard/portfolio_overview.html': 2,
        'templates/dashboard/positions_list.html': 2,
    },
    'data-market': {
        'static/js/sv-rail-filters.js': 2,
        'templates/_partials/signal_rail_items.html': 2,
        'templates/_partials/signal_rows_compact.html': 2,
    },
    'data-nav-page-id': {
        'static/js/sv-nav-activity.js': 2,
        'templates/base.html': 1,
    },
    # ONE PRICE EVERYWHERE (#105), joined on 2026-11-13: counted by
    # inventory() on origin/main 1b94a50, the main the old-design redo's B0
    # branches from, so every later display stage is held to them.
    'data-q': {
        'core/templatetags/quote_tags.py': 3,
        'static/js/sv-horde.js': 7,
        'static/js/sv-position-card.js': 2,
        'static/js/sv-venue.js': 11,
        'templates/_partials/deal_ticket.html': 3,
        'templates/_partials/dh_item.html': 9,
        'templates/_partials/signal_rail_items.html': 2,
        'templates/base.html': 16,
        'templates/dashboard/_command_portfolio.html': 1,
        'templates/dashboard/_position_summary.html': 2,
        'templates/dashboard/instrument_detail.html': 9,
        'templates/dashboard/instruments_list.html': 10,
        'templates/dashboard/news_detail.html': 2,
        'templates/dashboard/portfolio_overview.html': 2,
        'templates/dashboard/positions_list.html': 3,
    },
    'data-q-bars': {
        'static/js/sv-position-card.js': 1,
        'static/js/sv-venue.js': 2,
        'templates/_partials/dh_item.html': 1,
        'templates/base.html': 2,
    },
    'data-q-below': {
        'static/js/sv-position-card.js': 1,
        'static/js/sv-venue.js': 1,
    },
    'data-q-dot': {
        'static/js/sv-venue.js': 3,
    },
    'data-q-f': {
        'core/templatetags/quote_tags.py': 2,
        'static/js/sv-horde.js': 3,
        'static/js/sv-overlay.js': 1,
        'static/js/sv-position-card.js': 2,
        'static/js/sv-venue.js': 6,
        'templates/_partials/deal_ticket.html': 3,
        'templates/_partials/dh_item.html': 6,
        'templates/_partials/signal_rail_items.html': 1,
        'templates/base.html': 5,
        'templates/dashboard/_position_summary.html': 1,
        'templates/dashboard/instrument_detail.html': 7,
        'templates/dashboard/instruments_list.html': 8,
        'templates/dashboard/news_detail.html': 1,
        'templates/dashboard/portfolio_overview.html': 1,
        'templates/dashboard/positions_list.html': 2,
    },
    'data-q-fam': {
        'static/js/sv-position-card.js': 1,
        'static/js/sv-venue.js': 1,
        'templates/_partials/dh_item.html': 1,
        'templates/base.html': 2,
    },
    'data-q-max': {
        'static/js/sv-venue.js': 1,
        'templates/_partials/signal_rail_items.html': 1,
    },
    'data-q-o': {
        'static/js/sv-venue.js': 1,
        'templates/_partials/signal_rail_items.html': 1,
    },
    'data-q-ref': {
        'static/js/sv-position-card.js': 1,
        'static/js/sv-venue.js': 1,
        'templates/dashboard/positions_list.html': 1,
    },
    'data-q-side': {
        'core/templatetags/quote_tags.py': 2,
        'static/js/sv-horde.js': 7,
        'static/js/sv-position-card.js': 2,
        'static/js/sv-venue.js': 2,
        'templates/dashboard/_command_portfolio.html': 1,
        'templates/dashboard/_position_summary.html': 2,
        'templates/dashboard/portfolio_overview.html': 2,
        'templates/dashboard/positions_list.html': 3,
    },
    'data-q-spark': {
        'static/js/sv-position-card.js': 1,
        'static/js/sv-venue.js': 11,
        'templates/_partials/dh_item.html': 1,
        'templates/base.html': 2,
    },
    'data-q-state': {
        'static/js/sv-venue.js': 2,
    },
    'data-q-stop': {
        'static/js/sv-venue.js': 1,
        'templates/_partials/signal_rail_items.html': 1,
    },
    'data-q-target': {
        'static/js/sv-venue.js': 1,
        'templates/_partials/signal_rail_items.html': 1,
    },
    'data-q-title': {
        'core/templatetags/quote_tags.py': 1,
        'static/js/sv-horde.js': 1,
        'static/js/sv-venue.js': 7,
        'templates/_partials/dh_item.html': 2,
        'templates/_partials/signal_rail_items.html': 1,
        'templates/base.html': 4,
        'templates/dashboard/_command_portfolio.html': 1,
        'templates/dashboard/_position_summary.html': 1,
        'templates/dashboard/instrument_detail.html': 1,
        'templates/dashboard/instruments_list.html': 2,
        'templates/dashboard/portfolio_overview.html': 1,
        'templates/dashboard/positions_list.html': 1,
    },
    'data-sv-at': {
        'static/js/sv-overlay.js': 3,
        'templates/_partials/broker_account.html': 1,
        'templates/_partials/dh_item.html': 2,
        'templates/_partials/notif_items.html': 1,
        'templates/_partials/signal_rows_compact.html': 1,
        'templates/_partials/ticker_item.html': 1,
        'templates/base.html': 6,
        'templates/dashboard/notifications_inbox.html': 1,
        'templates/dashboard/positions_list.html': 1,
        'templates/dashboard/research.html': 4,
        'templates/dashboard/strategies_list.html': 1,
        'templates/dashboard/system_map.html': 1,
    },
    'data-sv-backdrop': {
        'static/js/sv-overlay.js': 2,
        'templates/base.html': 1,
        'templates/dashboard/_profile_credentials.html': 2,
        'templates/dashboard/admin_dashboard.html': 1,
        'templates/dashboard/backtest_list.html': 2,
    },
    'data-sv-close': {
        'static/js/sv-close-advice.js': 2,
        'static/js/sv-motion.js': 1,
        'static/js/sv-overlay.js': 4,
        'templates/base.html': 2,
        'templates/dashboard/_profile_credentials.html': 2,
        'templates/dashboard/admin_dashboard.html': 2,
        'templates/dashboard/system_map.html': 2,
    },
    'data-sv-close-trade': {
        'static/js/sv-horde.js': 1,
        'static/js/sv-position-card.js': 1,
        'templates/base.html': 5,
        'templates/dashboard/_command_portfolio.html': 1,
        'templates/dashboard/_eye_body.html': 1,
        'templates/dashboard/portfolio_overview.html': 1,
        'templates/dashboard/positions_list.html': 1,
    },
    'data-sv-count': {
        'static/js/sv-motion.js': 4,
        'templates/dashboard/_command_bots.html': 5,
        'templates/dashboard/_command_history.html': 3,
    },
    'data-sv-fhost': {
        'static/js/sv-rail-filters.js': 6,
        'templates/base.html': 4,
    },
    'data-sv-focus': {
        'static/js/sv-overlay.js': 3,
        'templates/base.html': 3,
        'templates/dashboard/admin_dashboard.html': 1,
        'templates/dashboard/backtest_list.html': 2,
    },
    'data-sv-gone': {
        'static/js/sv-rail-filters.js': 1,
        'templates/_partials/signal_rail_items.html': 1,
    },
    'data-sv-list': {
        'static/js/sv-rail-filters.js': 3,
        'templates/_partials/signal_rail_items.html': 1,
        'templates/base.html': 3,
    },
    'data-sv-live': {
        'static/js/sv-motion.js': 1,
        'static/js/sv-news-dwell.js': 1,
        'templates/_partials/capital_card.html': 1,
        'templates/_partials/live_region.html': 6,
        'templates/base.html': 38,
        'templates/dashboard/portfolio_overview.html': 4,
        'templates/dashboard/positions_list.html': 5,
        'templates/dashboard/risk_depth.html': 1,
        'templates/investor/panel.html': 2,
    },
    'data-sv-live-key': {
        'templates/_partials/capital_card.html': 10,
        'templates/_partials/live_region.html': 4,
        'templates/_partials/position_group_row.html': 1,
        'templates/base.html': 15,
        'templates/dashboard/portfolio_overview.html': 29,
        'templates/dashboard/positions_list.html': 19,
        'templates/investor/_panel_body.html': 5,
    },
    'data-sv-live-status': {
        'templates/_partials/capital_card.html': 1,
        'templates/_partials/live_region.html': 2,
        'templates/base.html': 4,
        'templates/dashboard/portfolio_overview.html': 1,
        'templates/dashboard/positions_list.html': 1,
        'templates/dashboard/risk_depth.html': 1,
        'templates/investor/_panel_body.html': 1,
    },
    'data-sv-lock': {
        'static/js/sv-overlay.js': 2,
    },
    'data-sv-noflash': {
        'static/js/sv-flash.js': 1,
    },
    'data-sv-now': {
        'core/templatetags/quote_tags.py': 1,
        'static/js/sv-venue.js': 3,
        'templates/_partials/sv_venue.html': 1,
    },
    'data-sv-open': {
        'static/js/sv-motion.js': 1,
        'static/js/sv-overlay.js': 3,
        'templates/base.html': 1,
        'templates/dashboard/admin_dashboard.html': 1,
    },
    'data-sv-overlay': {
        'static/js/sv-close-advice.js': 1,
        'static/js/sv-motion.js': 3,
        'static/js/sv-notif-card.js': 1,
        'static/js/sv-overlay.js': 4,
        'static/js/sv-tour.js': 2,
        'templates/base.html': 4,
        'templates/dashboard/_profile_credentials.html': 2,
        'templates/dashboard/admin_dashboard.html': 1,
        'templates/dashboard/backtest_list.html': 2,
        'templates/dashboard/system_map.html': 1,
    },
    'data-sv-persist': {
        'static/js/sv-overlay.js': 6,
        'templates/base.html': 3,
    },
    'data-sv-quotes': {
        'core/templatetags/quote_tags.py': 1,
        'static/js/sv-venue.js': 4,
    },
    'data-sv-rail-n': {
        'templates/_partials/rail_sig_chips.html': 6,
        'templates/_partials/signal_rail_items.html': 1,
        'templates/base.html': 7,
    },
    'data-sv-shut': {
        'static/js/sv-rail-filters.js': 1,
        'templates/_partials/signal_rail_items.html': 1,
    },
    'data-ticket': {
        'templates/_partials/deal_ticket.html': 1,
    },
    'json:-positions': {
        'templates/_partials/chart_widget.html': 1,
    },
    'json:-signals': {
        'templates/_partials/chart_widget.html': 1,
    },
    'svCharts[id].bars': {
        'templates/_partials/chart_widget.html': 1,
    },
    'svCharts[id].caption': {
        'templates/_partials/chart_widget.html': 1,
    },
    'svCharts[id].refresh': {
        'templates/_partials/chart_widget.html': 1,
    },
    'svCharts[id].series': {
        'templates/_partials/chart_widget.html': 1,
    },
    'svCharts[id].setNow': {
        'templates/_partials/chart_widget.html': 1,
    },
    'svCharts[id].tick': {
        'templates/_partials/chart_widget.html': 1,
    },
    'window.SAURON_CHART_COLORS': {
        'templates/_chart_assets.html': 1,
    },
    'window.svCharts': {
        'templates/_partials/chart_widget.html': 1,
    },
    'window.svCloseTrade': {
        'templates/base.html': 1,
    },
    'window.svHoverCards': {
        'templates/_partials/chart_widget.html': 1,
    },
    'window.svLevels': {
        'templates/_partials/chart_widget.html': 1,
    },
    'window.svLiveRefresh': {
        'templates/_partials/live_region.html': 1,
    },
    'window.svRenderDonuts': {
        'templates/_partials/chart_donut.html': 1,
    },
    'window.svRenderLines': {
        'templates/_partials/chart_line.html': 1,
    },
    'window.svRenderSparks': {
        'templates/base.html': 1,
    },
    'window.svSignalDots': {
        'templates/_partials/chart_widget.html': 1,
    },
    'window.svTakeTrade': {
        'templates/base.html': 1,
    },
    'window.svTakeTradeAsset': {
        'templates/base.html': 1,
    },
    'window.svWheelMarquee': {
        'templates/base.html': 1,
    },
}


class LiveHooksInventoryTests(SimpleTestCase):

    maxDiff = None

    def test_the_contract_names_every_hook_of_section_11(self):
        """Every hook the plan names is in the recorded inventory, found in
        at least one file: the scanner sees them all today."""
        expected = (set(DATA_ATTRS) | {"#" + i for i in IDS}
                    | {"json:" + s for s in CHART_JSON_SUFFIXES}
                    | {"svCharts[id]." + m for m in CHART_HANDLE}
                    | {"." + c for c in CLASSES}
                    | {"." + c + "*" for c in CLASS_FAMILIES}
                    | {"window." + g for g in GLOBALS + PAINTERS}
                    | {"SV." + s for s in SV_NAMESPACE}
                    | {"data-q (price cell)"}
                    | {p + ".*()" for p in PAINTERS}
                    | {"{% " + n + " %}" for n in TEMPLATE_TAGS}
                    | {"include " + n for n in INCLUDES})
        self.assertEqual(set(RECORDED), expected)
        for hook, files in RECORDED.items():
            self.assertTrue(files, "%s is recorded nowhere" % hook)
            self.assertTrue(all(n > 0 for n in files.values()), hook)

    def test_no_file_loses_a_hook(self):
        now = inventory()
        lost = []
        for hook, files in sorted(RECORDED.items()):
            for rel, n in sorted(files.items()):
                got = now.get(hook, {}).get(rel, 0)
                if got < n:
                    lost.append("%s in %s: %d, was %d" % (hook, rel, got, n))
        self.assertEqual(lost, [], "a display change dropped live hooks:\n  "
                         + "\n  ".join(lost))

    def test_the_scanner_catches_a_lost_hook(self):
        """The counting is not vacuous: a page that drops one data-sv-live,
        the close-all id, a .sv-unknown dash or the ticket's global is seen
        as fewer."""
        base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
        for hook, counter, name in (
                ("data-sv-live", count_data_attr, "data-sv-live"),
                ("sv-unknown", count_class, "sv-unknown"),
                ("svTakeTrade", count_global, "svTakeTrade")):
            before = counter(base, name)
            self.assertGreater(before, 0, hook)
            first = base.find(name if counter is not count_global
                              else "window.svTakeTrade =")
            cut = base[:first] + base[first:].replace(
                name, "x" + name[1:] if counter is not count_global
                else "svTakeTradeX", 1)
            self.assertLess(counter(cut, name), before, hook)
        positions = (ROOT / "templates/dashboard/positions_list.html").read_text(
            encoding="utf-8")
        self.assertGreater(count_id(positions, "svCloseAll"), 0)
        self.assertEqual(count_id(positions.replace('id="svCloseAll"', 'id="svCloseEverything"'),
                                  "svCloseAll") + 1, count_id(positions, "svCloseAll"))
        # LEFT THE RAIL's section (2026-11-07): its hook is counted alone,
        # never inside the count it sits next to (data-sv-gone-n).
        rail = (ROOT / "templates/_partials/signal_rail_items.html").read_text(encoding="utf-8")
        self.assertEqual(count_data_attr(rail, "data-sv-gone"), 1)
        self.assertEqual(count_data_attr(rail.replace("data-sv-gone ", "data-sv-left "),
                                         "data-sv-gone"), 0)
        self.assertEqual(count_data_attr('<b data-sv-gone-n>3</b>', "data-sv-gone"), 0)
        # MARKET SHUT's hooks (2026-11-12) are whole tokens too: the host's
        # data-f-shut is never counted inside data-f-shutoff, nor the rail's
        # data-market inside the instrument pages' data-market-session.
        host = (ROOT / "templates/_partials/rail_host_attrs.html").read_text(encoding="utf-8")
        self.assertEqual(count_data_attr(host, "data-f-shutoff"), 1)
        self.assertEqual(count_data_attr(host, "data-f-shut"), 2)
        self.assertEqual(count_data_attr(host.replace("data-f-shutoff", "data-f-hidden"), "data-f-shut"), 2)
        self.assertEqual(count_data_attr(host.replace("data-f-shut=", "data-f-held="), "data-f-shut"), 1)
        self.assertEqual(count_data_attr('<i data-market-session="x" data-market-compact="1">',
                                         "data-market"), 0)
        self.assertEqual(count_data_attr('<div data-sv-row data-market="shut">', "data-market"), 1)
        self.assertEqual(count_data_attr(rail, "data-sv-shut"), 1)
        self.assertEqual(count_data_attr(rail.replace("data-sv-shut ", "data-sv-held "), "data-sv-shut"), 0)

    def test_the_one_price_hooks_are_counted_alone(self):
        """#105's hooks (2026-11-13): data-q is a whole token, never counted
        inside data-q-f or data-q-side; a cell that loses its data-q is
        seen as fewer; the chart handle's methods are its own keys, never a
        key of a nested object nor a word in a comment or a string."""
        dh = (ROOT / "templates/_partials/dh_item.html").read_text(encoding="utf-8")
        before = count_data_attr(dh, "data-q")
        self.assertGreater(before, 0)
        self.assertEqual(count_data_attr(dh.replace('data-q="', 'data-x="', 1), "data-q"), before - 1)
        self.assertEqual(count_data_attr('<b data-q-f="price" data-q-side="bid">', "data-q"), 0)
        self.assertEqual(count_data_attr('<b data-q-f="price" data-q-side="bid">', "data-q-f"), 1)
        self.assertEqual(count_data_attr('<script type="application/json" data-sv-quotes>', "data-sv-quotes"), 1)
        widget = (ROOT / "templates/_partials/chart_widget.html").read_text(encoding="utf-8")
        for name in CHART_HANDLE:
            self.assertEqual(count_handle_method(widget, name), 1, name)
        renamed = widget.replace("setNow: function", "setNowValue: function", 1)
        self.assertEqual(count_handle_method(renamed, "setNow"), 0)
        js = ("window.svCharts[ID] = { /* setNow: no */ series: function () { return {bars: 1}; },"
              " caption: 'tick: no', tick: function () {} };")
        self.assertEqual(count_handle_method(js, "series"), 1)
        self.assertEqual(count_handle_method(js, "bars"), 0)
        self.assertEqual(count_handle_method(js, "setNow"), 0)
        self.assertEqual(count_handle_method(js, "tick"), 1)
        self.assertEqual(count_handle_method("other[ID] = { tick: function () {} };", "tick"), 0)

    def test_the_painter_s_other_hooks_are_counted(self):
        """The review of B0: a price cell is told from a suggestion button,
        the painter's definition and every call to it are seen, and so are
        the tag and the include that feed it, and the handle's symbol."""
        self.assertEqual(count_price_cells('<b data-q="{{ w.symbol }}"></b><i data-q="${d.symbol}"></i>'
                                           '<button class="se-suggest" data-q="Why is the gate shut?">'), 2)
        self.assertEqual(count_data_attr('<button data-q="Why?">', "data-q"), 1)
        self.assertEqual(count_global("root.SVVenue = api;", "SVVenue"), 1)
        self.assertEqual(count_calls("if (window.SVVenue) SVVenue.ingest(q, t); w.SVVenue.paint(el);"
                                     " var SVVenue = 1;", "SVVenue"), 2)
        self.assertEqual(count_tag('{% q_json quotes %}{%q_json x%}', "q_json"), 2)
        self.assertEqual(count_include('{% include "_partials/sv_venue.html" %}', "_partials/sv_venue.html"), 1)
        widget = (ROOT / "templates/_partials/chart_widget.html").read_text(encoding="utf-8")
        self.assertEqual(count_handle_method(widget, "symbol"), 1)
        self.assertEqual(count_handle_method(widget.replace("symbol:", "sym:", 1), "symbol"), 0)
        rows = (ROOT / "templates/dashboard/positions_list.html").read_text(encoding="utf-8")
        self.assertEqual(count_data_attr(rows, "data-pos-q"), 1)
        self.assertEqual(count_data_attr(rows.replace("data-pos-q-side", "data-pos-qside"), "data-pos-q-side"), 0)

    def test_counting_reads_through_django_tags_in_a_class(self):
        html = ('<span class="ip-x {% if a > 0 %}up{% elif a < 0 %}down{% endif %}">'
                '<b class="sv-world sv-world--{{ w }}">x</b>'
                '<i title="prices went up">up</i>')
        self.assertEqual(count_class(html, "up"), 1)
        self.assertEqual(count_class(html, "down"), 1)
        self.assertEqual(count_class(html, "sv-world--", family=True), 1)
        js = "el.classList.add('up'); q('.sv-age.up'); x = 'down';"
        self.assertEqual(count_class(js, "up"), 2)
        self.assertEqual(count_class(js, "down"), 1)
