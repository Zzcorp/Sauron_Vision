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
(LEFT THE RAIL's chip is a data-f-toggle with data-f-key="gone"), so
there is nothing by that name to record.

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
  * a window global: its definition (window.X =, w.X =, SV.x =, w.SV.x =).

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
    return len(re.findall(r"(?:\bwindow|\bw)\.%s\s*=(?!=)" % re.escape(name), text))


def count_sv(text, name):
    return len(re.findall(r"(?:\bwindow\.SV|\bw\.SV|(?<![\w.])SV)\.%s\s*=(?!=)"
                          % re.escape(name), text))


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
        for name in CLASSES:
            put("." + name, rel, count_class(text, name))
        for name in CLASS_FAMILIES:
            put("." + name + "*", rel, count_class(text, name, family=True))
        for name in GLOBALS:
            put("window." + name, rel, count_global(text, name))
        for name in SV_NAMESPACE:
            put("SV." + name, rel, count_sv(text, name))
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
# A file may gain a hook; it may not lose one. Each hook below must also be
# found somewhere (no hook is recorded at zero), so a hook renamed
# everywhere at once fails too.
RECORDED = {
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
        'static/js/sv-instrument-live.js': 1,
    },
    '.up': {
        'core/templatetags/sauron_tags.py': 1,
        'static/js/sv-close-advice.js': 1,
        'static/js/sv-flash.js': 1,
        'static/js/sv-horde.js': 3,
        'static/js/sv-instrument-live.js': 2,
        'static/js/sv-news-dwell.js': 1,
        'static/js/sv-position-card.js': 4,
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
    'data-nav-page-id': {
        'static/js/sv-nav-activity.js': 2,
        'templates/base.html': 1,
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
    'data-sv-rail-n': {
        'templates/_partials/rail_sig_chips.html': 4,
        'templates/base.html': 6,
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
                    | {"." + c for c in CLASSES}
                    | {"." + c + "*" for c in CLASS_FAMILIES}
                    | {"window." + g for g in GLOBALS}
                    | {"SV." + s for s in SV_NAMESPACE})
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
