"""The file:line -> batch map (the critic's hole 5): the batch of
batches.md that empties each counted marker."""
import collections

from tests.old_design.rules import ROOT, census

# ══════════════════════════════════════════════════════════════════════════
# Who empties what: the file:line -> batch map (the critic's hole 5)
# ══════════════════════════════════════════════════════════════════════════
#
# The batch of batches.md that removes a file's old markers. A shared file
# is cut into stretches (first line, last line, batch[, marker]): a marker
# named on a stretch is that batch's on those lines (the shell's glyph
# icons are B2's wherever they sit, the rest of a stretch its own batch's).
# Lines are main's at 1b94a50. A batch that moves lines moves its stretch
# with them, in the same change. "exception" is a recorded exception of the
# final guard (the intro, kept exactly; the Django admin); "B24a" is light
# mode, its §10 meanings whatever he decides about its palette.

BATCHES = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11", "B12", "B13", "B14",
           "B15", "B16", "B17", "B18", "B19", "B20", "B21", "B22", "B23", "B24", "B24a", "exception")

#: One owner per template or script: the page batch that redoes it.
FILE_OWNER = {
    # The frame (B1) and the shell's own pieces.
    "templates/_partials/activity_drawer.html": "B4", "templates/_partials/council_band.html": "B4",
    "templates/_partials/the_horde.html": "B4", "templates/_tour.html": "B4",
    "templates/_partials/dh_item.html": "B3", "templates/_partials/ticker_item.html": "B3",
    "templates/_partials/ticker_items.html": "B3", "templates/_partials/signal_rail_items.html": "B3",
    "templates/_partials/signal_rows_compact.html": "B3", "templates/_partials/notif_items.html": "B3",
    "templates/_partials/rail_sig_chips.html": "B3", "templates/_partials/rail_watch_chips.html": "B3",
    "templates/_partials/rail_host_attrs.html": "B3", "templates/_partials/passation_card.html": "B3",
    "templates/_partials/live_region.html": "B3", "templates/_partials/deep_link_note.html": "B3",
    "templates/_partials/sv_venue.html": "B3",
    # The shared pieces (B5) and the kit's own page.
    "templates/dashboard/design_kit.html": "B5",
    # B6: the ticket and the instrument page.
    "templates/_partials/deal_ticket.html": "B6", "templates/dashboard/instrument_detail.html": "B6",
    # B7: positions.
    "templates/dashboard/positions_list.html": "B7", "templates/dashboard/_positions_metrics.html": "B7",
    "templates/dashboard/_position_summary.html": "B7", "templates/_partials/capital_card.html": "B7",
    "templates/_partials/position_filter.html": "B7", "templates/_partials/close_selection_bar.html": "B7",
    "templates/_partials/position_group_row.html": "B7", "templates/_partials/position_view_note.html": "B7",
    "templates/dashboard/forensics_detail.html": "B7", "templates/dashboard/_council_card.html": "B7",
    "templates/dashboard/_live_shell.html": "B7",
    # B8: home, /command/ (OC1).
    "templates/dashboard/command.html": "B8", "templates/dashboard/_command_bots.html": "B8",
    "templates/dashboard/_command_history.html": "B8", "templates/dashboard/_command_live.html": "B8",
    "templates/dashboard/_command_portfolio.html": "B8",
    # B9: signals, portfolio, the small charts, the broker's own reading.
    "templates/dashboard/signals_list.html": "B9", "templates/dashboard/_signals_metrics.html": "B9",
    "templates/dashboard/portfolio_overview.html": "B9", "templates/dashboard/_portfolio_metrics.html": "B9",
    "templates/_chart_assets.html": "B9", "templates/_partials/chart_line.html": "B9",
    "templates/_partials/chart_bars.html": "B9", "templates/_partials/chart_donut.html": "B9",
    "templates/_partials/broker_account.html": "B9", "dashboard/views_bot_charts.py": "B9",
    # B10: the instrument chart.
    "templates/_partials/chart_widget.html": "B10",
    # B11: the cockpits.
    "templates/dashboard/ops.html": "B11", "templates/dashboard/orcs_list.html": "B11",
    "templates/dashboard/orcs_seats.html": "B11", "templates/dashboard/orc_detail.html": "B11",
    "templates/dashboard/ai_models.html": "B11",
    # B12: /oculus/.
    "templates/dashboard/oculus.html": "B12",
    # B13: money settings.
    "templates/dashboard/setup.html": "B13", "templates/dashboard/brokers.html": "B13",
    "templates/dashboard/withdrawals.html": "B13", "templates/dashboard/treasury.html": "B13",
    # B14: bots and pools.
    "templates/dashboard/asset_bots.html": "B14", "templates/dashboard/shares.html": "B14",
    "templates/dashboard/desk.html": "B14", "templates/dashboard/allocator.html": "B14",
    "templates/dashboard/risk_depth.html": "B14", "bot_program/templates/bot_program/home.html": "B14",
    "templates/dashboard/bot_console.html": "B14",
    # B15: login, PIN, lock, pop-out (and the Wall's sign-in, below).
    "templates/registration/login.html": "B15", "templates/registration/login_pin.html": "B15",
    "templates/registration/_key_eye.html": "B15", "templates/dashboard/locked.html": "B15",
    "templates/dashboard/_popout.html": "B15", "static/js/idle-lock.js": "B15",
    # B16: the markets.
    "templates/dashboard/instruments_list.html": "B16", "templates/dashboard/economic_calendar.html": "B16",
    "templates/dashboard/news_feed.html": "B16", "templates/dashboard/news_detail.html": "B16",
    "templates/dashboard/_news_metrics.html": "B16", "templates/bigmoney/board.html": "B16",
    "templates/dashboard/liquidations.html": "B16",
    # B17: what can act.
    "templates/dashboard/strategies_list.html": "B17", "templates/dashboard/strategy_detail.html": "B17",
    "templates/dashboard/_strategy_wizard.html": "B17", "templates/dashboard/_strategies_metrics.html": "B17",
    "templates/dashboard/setups.html": "B17", "templates/dashboard/opportunities.html": "B17",
    "templates/dashboard/rule_control.html": "B17", "templates/dashboard/promotions.html": "B17",
    "templates/dashboard/personas.html": "B17", "templates/dashboard/events.html": "B17",
    # B18: what is measured.
    "templates/dashboard/evidence.html": "B18", "templates/dashboard/performance.html": "B18",
    "templates/dashboard/bot_performance.html": "B18", "templates/dashboard/forensics_list.html": "B18",
    "templates/dashboard/backtest_list.html": "B18", "templates/dashboard/_backtest_metrics.html": "B18",
    "templates/dashboard/bot_backtest.html": "B18", "templates/dashboard/bot_backtest_detail.html": "B18",
    "templates/dashboard/calibration.html": "B18", "templates/dashboard/council.html": "B18",
    # B19: what is invented.
    "templates/dashboard/evolution.html": "B19", "templates/dashboard/discoveries.html": "B19",
    "templates/dashboard/generated.html": "B19", "templates/dashboard/hypotheses.html": "B19",
    "templates/dashboard/brain.html": "B19", "templates/dashboard/_brain_rule_lever.html": "B19",
    "templates/dashboard/knowledge.html": "B19", "templates/dashboard/knowledge_history.html": "B19",
    "templates/lore/index.html": "B19", "templates/lore/entry.html": "B19",
    "templates/dashboard/consolidation.html": "B19", "templates/dashboard/horizon.html": "B19",
    "templates/dashboard/intelligence.html": "B19", "templates/dashboard/briefing.html": "B19",
    "templates/dashboard/_monday_plan.html": "B19", "templates/dashboard/_next_steps.html": "B19",
    "templates/dashboard/earnings_reviews.html": "B19", "templates/dashboard/research.html": "B19",
    "templates/dashboard/ai_journal.html": "B19", "templates/dashboard/ai_insights.html": "B19",
    # B20: the machine.
    "templates/dashboard/admin_dashboard.html": "B20", "templates/dashboard/_admin_bots.html": "B20",
    "templates/dashboard/system_map.html": "B20", "templates/dashboard/admin_eye.html": "B20",
    "templates/dashboard/hq_books.html": "B20", "templates/dashboard/_hq_divisions.html": "B20",
    "templates/dashboard/admin_newsletters.html": "B20", "templates/dashboard/eye.html": "B20",
    "templates/dashboard/_eye_body.html": "B20", "templates/dashboard/eye_gate_events.html": "B20",
    "templates/dashboard/eye_fills.html": "B20", "templates/dashboard/eye_exposure.html": "B20",
    "templates/dashboard/system_health.html": "B20", "templates/dashboard/ai_tasks_list.html": "B20",
    "templates/dashboard/audit_log.html": "B20",
    # B21: you, off-nav, the book's tail.
    "templates/dashboard/profile.html": "B21", "templates/dashboard/_profile_credentials.html": "B21",
    "templates/dashboard/_profile_password_modal.html": "B21",
    "templates/dashboard/_profile_pin_modal.html": "B21", "templates/dashboard/notifications_inbox.html": "B21",
    "templates/dashboard/user_notifications.html": "B21", "templates/dashboard/newsletter_archive.html": "B21",
    "templates/dashboard/newsletter_detail.html": "B21", "templates/dashboard/getting_started.html": "B21",
    "templates/dashboard/passation.html": "B21", "templates/dashboard/short_proofs.html": "B21",
    "bot_program/templates/bot_program/link.html": "B21", "bot_program/templates/bot_program/configure.html": "B21",
    "bot_program/templates/bot_program/scenarios.html": "B21",
    "bot_program/templates/bot_program/scenario_new.html": "B21",
    "bot_program/templates/bot_program/scenario_detail.html": "B21",
    "templates/dashboard/tax_lots.html": "B21", "templates/dashboard/bot_charts.html": "B21",
    # B23: the public pages, the report and the emails (the Wall's sign-in is B15's, below).
    "templates/landing/the_wall.html": "B23", "templates/landing/the_book.html": "B23",
    "templates/landing/withheld.html": "B23", "templates/investor/panel.html": "B23",
    "templates/investor/_panel_body.html": "B23", "templates/email/newsletter.html": "B23",
    "templates/email/briefing.html": "B23", "templates/newsletter/unsubscribe.html": "B23",
    "dashboard/reports.py": "B23",
    # B24: dead, deleted rather than restyled.
    "templates/dashboard/dashboard.html": "B24", "templates/dashboard/market_quotes.html": "B24",
    "templates/dashboard/_signal_cards.html": "B24", "templates/dashboard/_signal_performance.html": "B24",
    "templates/_modal.html": "B24", "templates/dashboard/report.html": "B24",
    # Recorded exceptions of the final guard.
    "templates/dashboard/intro.html": "exception", "templates/admin/base_site.html": "exception",
    # The sheets and the scripts.
    "static/css/sv-rail.css": "B3", "static/css/sv-venue.css": "B3", "static/css/sv-overlay.css": "B3",
    "static/css/sv-horde.css": "B4", "static/css/sv-council-band.css": "B4", "static/css/sv-activity.css": "B4",
    "static/css/sv-tour.css": "B4", "static/css/sv-motion.css": "B5", "static/css/sv-kit.css": "B5",
    "static/css/sv-close-advice.css": "B7", "static/css/sv-day-scheme.css": "B8",
    "static/css/sv-responsive.css": "B22",
    "static/js/sv-overlay.js": "B3", "static/js/sv-flash.js": "B3", "static/js/sv-notif-card.js": "B3",
    "static/js/sv-news-dwell.js": "B3", "static/js/sv-rail-filters.js": "B3", "static/js/sv-position-card.js": "B3",
    "static/js/sv-venue.js": "B3", "static/js/sv-market-status.js": "B3",
    "static/js/sv-horde.js": "B4", "static/js/sv-council-band.js": "B4", "static/js/sv-activity.js": "B4",
    "static/js/sv-tour.js": "B4", "static/js/sv-gollum.js": "B4", "static/js/sv-motion.js": "B5",
    "static/js/sv-council.js": "B6", "static/js/sv-instrument-live.js": "B6", "static/js/sv-level-edit.js": "B7",
    "static/js/sv-close-advice.js": "B7", "static/js/sv-day-scheme.js": "B8", "static/js/sv-day-live.js": "B8",
    "static/js/sv-nav-activity.js": "B2", "static/js/sv-gate.js": "B15", "static/js/sv-run.js": "B5",
    "static/js/sv-embers.js": "B1", "static/js/sv-moments.js": "B1", "static/js/sv-ambience.js": "B1",
    "core/templatetags/sauron_tags.py": "B5", "core/templatetags/quote_tags.py": "B3",
}

#: The two big shared files, cut where their own sections begin. A stretch
#: starts on the first line, after the previous stretch's start, that holds
#: its anchor, and runs to the next one (the first from line 1, the last to
#: the end of the file). Anchored on the files' own section notes, so lines
#: added above move nothing; a batch that rewrites a section re-anchors its
#: stretch in the same change (a lost anchor fails a test below).
ANCHORED = {
    "templates/base.html": [
        (None, "B1"),                                                   # the head: the faces, the sheets
        ("<!-- Animated grid background -->", "B24"),                   # the hidden ambient layers (#103)
        ('<div id="navMiniTip"', "B2"),                                 # the brand, the nav, its 62 marks
        ("<!-- Mobile sidebar overlay -->", "B1"),                      # the topbar row (#7)
        ('class="theme-toggle-btn"', "B2"),                             # the theme toggle's ☀ ☾
        ('<span id="clock"', "B1"),
        ('<div class="exchange-indicator">', "B3"),                     # the sessions menu (#40)
        # B1 (the desk v2 board) put the feed pill before REAL ARMED, so the
        # bell, which followed the pill, has an anchor of its own.
        ("<!-- UPGRADE-8: Live status pill -->", "B3"),                 # the live-status list (#39, #40)
        ('class="sv-armed-pill"', "B1"),                                # REAL ARMED (#41)
        ('class="notif-bell" id="notifBell"', "B3"),                    # the bell (#40)
        ("{# Lock now, rather than waiting out the idle window", "B2"),  # lock now (#113)
        ('<div class="user-menu" id="userMenu">', "B3"),                # the user menu (#40)
        ("<!-- Ticker Bar (fixed, always visible) -->", "B1"),          # the strips, restore tabs, the bottom strip (#1, #10, #11)
        ('<div class="ip-dropdown">', "B3"),                            # the bottom strip's dropdowns (#38)
        ("{# A Telegram button's page (2026-10-24): what the link opens. #}", "B3"),  # (#112)
        ("<!-- UPGRADE-6: Top-level rail toggle", "B1"),
        ("{# THE PHONE'S BOTTOM NAV", "B2"),
        ("<!-- Signals Rail (right sidebar)", "B1"),                    # the rail's frame (#6)
        ('id="railWatchPanel"', "B3"),                                  # the watchlist, its quote card (#35, #37)
        ("{# The activity drawer (2026-09-29)", "B1"),
        ("/* Phase 62 — render sparkline paths", "B3"),                 # sparks, the rail card, pass and star (#36)
        ("/* ── TAKE TRADE — a signal proposes", "B6"),                  # TAKE TRADE and its outcome (#25, #109)
        ("/* ── CLOSE POSITION — the way out", "B7"),                    # the close (#30)
        ("/* ── A TELEGRAM BUTTON'S PAGE (2026-10-24)", "B3"),           # (#112)
        ("<!-- UPGRADE-9: Sidebar edge toggle", "B1"),                  # the edge toggle, the embers, the clock
        ("// Instrument preview on hover", "B3"),                       # the instrument preview (#39)
        ("function toggleSidebar()", "B2"),                             # the sidebar's collapse
        ("// Ticker mouse wheel scroll", "B1"),                         # the strips' wheel (the marquee's)
        ("/* UPGRADE-3: WebSocket live ticks.", "B3"),                  # live ticks, the flash's fallback, the popups (#13, #39)
        ("<!-- ── Keyboard Shortcuts Modal", "B4"),                     # the "?" sheet, the toast (#88)
        ("<!-- ── Mobile Sidebar Toggle", "B22"),
        ("<!-- ── Pop-Out Panel System", "B15"),                        # the pop-out (#96)
        ("<!-- ── PWA: Service Worker Registration", "B1"),             # Gollum's button (#2)
        ('<div class="gollum-dialog" id="gollumDialog"', "B4"),         # Gollum's dialog (#74)
        ('<button type="button" class="se-eye-fab" id="seEyeFab"', "B1"),  # Ask Sauron's Eye (#3)
        ('<div class="se-chat-panel" id="seChatPanel"', "B4"),          # Ask Sauron's panel (#73)
        ("/* ── Resume scroll position across navigation", "B1"),
        ("{# Idle PIN lock gate.", "B15"),                              # the idle lock (#69)
        ("/* Live event banners.", "B3"),                               # the trading-event banners (#75)
    ],
    "static/css/sauron.css": [
        (None, "B24"),                                   # the old token names, re-pointed (dropped once unread)
        ("/* The browser's own parts follow the theme", "B5"),   # form controls, body, links
        ("/* ── Globe-Eye: static eye, rotating globe", "B24"),  # the ambient keyframes (#103)
        ("/* The embers (the magic kept, 2026-11-12)", "B1"),
        ("/* ── Sidebar ──", "B2"),                       # the sidebar, the brand, the logout
        ("/* ── Main ──", "B1"),                          # the main frame
        ("/* ── Cards (base — overridden", "B5"),          # the cards' base (#14)
        ("Smart 2-row reflow when BOTH rails are open", "B22"),  # reflow, phone 29, the hamburger
        ("/* stat-box — handled by unified card system", "B5"),  # stat-box, signal-item (#14, #45)
        ("/* ── Account cards ──", "B13"),                # the account cards
        ("/* The line under an empty state that says WHY", "B5"),  # notes, the entry motion (#15, #83)
        ("::-webkit-scrollbar{width:6px}", "B1"),        # the page's scrollbar (#113)
        (".detail-header { display: flex;", "B5"),       # details, section dividers (#45)
        ("/* ── Light Mode ──", "B24a"),                  # light mode (#100, #116)
        ("/* ── Theme Toggle ──", "B1"),
        ("/* ── Keyboard Shortcuts Modal ──", "B4"),      # (#88)
        ("/* ── Sidebar Collapse ──", "B2"),              # the collapsed sidebar, its tooltip (#8)
        ("/* ── Exchange Dropdown (fixed) ──", "B3"),     # the sessions menu (#40)
        ("/* ── Buttons ──", "B24"),                      # the old buttons, folded into the kit (#16)
        ("/* ── Instrument Preview Popup ──", "B3"),      # (#39)
        ("/* ── Admin User Popup ──", "B20"),
        ("/* ── Mobile Responsive ──", "B22"),
        ("/* ── Form Styles (global) ──", "B5"),          # form labels (#45)
        ("/* ── Headband collapse system: dynamic offsets ── */", "B1"),  # strips, bottom strip, cells (#1, #11)
        ("/* ── Notification Bell ──", "B3"),             # the bell (#40, #113)
        ("/* ── Sidebar expand arrow (when mini) ──", "B2"),
        ("/* ── Signals Sidebar (right) ──", "B1"),        # the rail's frame (#6)
        ("/* Rich row layout */", "B3"),                  # the rail's rows
        ("/* ── Hover popup for each signal ──", "B3"),   # the rail card (#36)
        ("/* Adjust main content when signals rail is visible */", "B1"),  # toggles, hide/restore tabs (#5, #10)
        ("UPGRADE-2: Design system — buttons, inputs, metrics", "B24"),    # the second .btn (#16)
        (".input-label { font-family: var(--font-mono); font-size: 10px;", "B5"),  # labels (#45)
        ("UPGRADE-2: Signals rail split (Signals + Watchlist)", "B3"),     # the watchlist (#37)
        ("UPGRADE-9: Data headband (escape-clip popups + RTL scroll)", "B1"),  # the price band (#1)
        ("/* Popup — fixed position, anchored by JS to escape the scroll container */", "B3"),  # cards (#35, #39)
        ("/* ── THE VENUE CONVENTION, NAMED ONCE", "B5"),  # the world chips' convention (#21)
        ("/* THE ARMED PILL: on every page", "B1"),       # (#41)
        ("/* Gold, and therefore --accent-gold-ink", "B3"),  # the position card's insides (#39)
        ("/* Fresh headline in the marquee", "B1"),
        ("/* Push page content down for headbands", "B3"),   # the news popup, the live-status pill
        ("UNIFIED PREMIUM CARD SYSTEM", "B5"),             # the card recipe (#14)
        ("/* ── Top-right user menu (clickable username dropdown) ── */", "B3"),  # (#40)
        ("/* ── Enhanced Form Styles ──", "B5"),           # forms, checkbox, radio, range, file (#77)
        ("/* ── Switch (toggle) — for any element with class .sv-switch", "B24"),  # (#104)
        ("/* Django form.as_p styling */", "B5"),          # form.as_p, search, the KPI strip (#44)
        ("/* ── Layout-aware anchoring ──", "B1"),         # Ask Sauron's floating Eye (#3)
        ("/* ── In-panel SEND button — circular palantír-mini", "B4"),  # the send orb (hole 5)
        ("/* Background circuits overlay", "B24"),         # the circuits (#103)
        ("/* (FAB no longer uses the old SVG pupil-look", "B4"),  # Ask Sauron's panel (#73)
        ("REFINEMENT LAYER", "B5"),                       # numbers, the strip, cards (#14, #44)
        ("/* ── 3c. Strategy ladder cards", "B17"),        # (#90)
        ("/* ── 4. Tables ──", "B5"),                     # tables, empty states (#83, #114)
        ("TOKEN ALIASES", "B24"),
        ("/* ── The lead metric ──", "B5"),               # (#44)
        ("TICKER POPUPS", "B3"),                         # (#39)
        ("EVENT BANNERS", "B3"),                         # (#75)
        ("LIGHT MODE — remove the dark inset shadows", "B24a"),
        ("OVERFLOW HONESTY (2026-08-19)", "B22"),
        ("IDLE PIN LOCK (il-)", "B15"),                  # (#69)
        ("CARD CONTAINMENT (2026-08-19)", "B5"),         # identifiers (#82)
        ("STACKED TABLES (.sv-stack)", "B22"),
        ("/* ── Positions: the closed-trade cards", "B7"),
        ("SIGNAL ALREADY ACTED ON (sr-acted / sr-taken)", "B3"),
        ("TAKE TRADE — the pre-trade control panel (sz-)", "B6"),  # (#25, #109)
        ("CHART SURFACES", "B9"),                        # (#49)
        ("ASK SAURON — THE ANSWER", "B4"),               # (#73)
        ("INTERACTIVE BROKERS CONNECTION CARD", "B13"),
        ("/* ── Signal symbol cell ──", "B9"),            # (#47)
        ("/* ── Lock-now button ──", "B2"),               # (#113)
        ("/* ── Capital truth (pools/used/free card", "B7"),
        ("/* The oversubscribed note inside a dropdown body", "B3"),
        ("/* Sidebar unseen-activity dot", "B2"),        # (#113)
        ("/* ── Lock engage/release choreography", "B15"),
        ("/* ── Briefing depth — the strategist's report", "B19"),
        ("/* ── Gollum — the guide at the bottom-left", "B1"),   # his button and bubble (#2)
        ("/* The dialog — above the stone, in the card idiom. */", "B4"),  # his dialog (#74)
        ("/* ── The second gate — shared by /locked/ and the idle overlay", "B15"),
        ("/* ── News cell: a day of sentiment above the headlines", "B16"),
        ("/* -- Editing a stop where it is read", "B7"),   # the level editor (#32)
        ("/* ── DEAL TICKET ──", "B6"),                   # (#26)
        ("/* ── BROKER TRUTH ──", "B9"),                  # (#110)
        ("/* ── A Telegram button's page (2026-10-24)", "B3"),  # (#112)
    ],
}

_ANCHOR_CACHE = {}


def anchored_stretches(rel):
    """[(first, last, batch)] of an anchored file, end to end, and the
    anchors not found (in order)."""
    st = (ROOT / rel).stat()
    key = (rel, st.st_mtime_ns, st.st_size)
    if key not in _ANCHOR_CACHE:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        starts, lost, at = [], [], 0
        for anchor, batch in ANCHORED[rel]:
            if anchor is None:
                starts.append((1, batch))
                continue
            for i in range(at, len(lines)):
                if anchor in lines[i]:
                    starts.append((i + 1, batch))
                    at = i + 1
                    break
            else:
                lost.append(anchor)
        out = [(first, (starts[k + 1][0] - 1) if k + 1 < len(starts) else max(len(lines), first), batch)
               for k, (first, batch) in enumerate(starts)]
        _ANCHOR_CACHE[key] = (out, lost)
    return _ANCHOR_CACHE[key]


#: The other shared files, cut by line (first, last, batch[, marker]): a
#: marker named on a stretch is that batch's on those lines.
STRETCHES = {
    "templates/base.html": [(1, 10 ** 6, "B2", "glyph_icon")],   # every glyph icon of the shell: the sprite
    "static/css/sv-overlay.css": [
        (448, 476, "B3"),          # the bottom strip's dropdowns (#38)
        (854, 977, "B1"),          # Ask Sauron's floating Eye (#3)
        (1022, 1048, "B4"),        # Ask Sauron's panel (#73)
    ],
    "static/css/sv-horde.css": [(150, 230, "B1")],          # the Horde's strip (#4)
    "static/css/sv-council-band.css": [(117, 144, "B1")],   # COUNCIL's edge tab (#5)
    "static/css/sv-activity.css": [(46, 72, "B1")],         # ACTIVITY's edge tab (#5)
    "static/js/sv-venue.js": [(725, 735, "B9")],            # the eToro "now" line's colour (#49)
    "static/js/sv-motion.js": [(198, 282, "B8")],           # count-ups on /command/ (#42)
    "templates/landing/the_wall.html": [
        (630, 790, "B15"), (4586, 4670, "B15"), (5040, 5260, "B15"),   # his sign-in (#105)
    ],
    "core/templatetags/sauron_tags.py": [(300, 470, "B23")],   # the emails' palette (#99)
    "templates/_partials/council_band.html": [(1, 9999, "B2", "glyph_icon")],
    "templates/_partials/the_horde.html": [(1, 9999, "B2", "glyph_icon")],
}


def owner(path, line, marker=None):
    """The batch that empties `path` at `line` (of `marker`), or None."""
    stretches = list(STRETCHES.get(path, ()))
    for first, last, batch, *only in stretches:
        if only and only[0] == marker and first <= line <= last:
            return batch
    if path in ANCHORED:
        stretches += anchored_stretches(path)[0]
    found = None
    for first, last, batch, *only in stretches:
        if not only and first <= line <= last:
            found = batch
    return found or FILE_OWNER.get(path)


def batch_map(hits=None):
    """{batch: {file: [(line, marker)]}} and the orphans (no owner)."""
    hits = census() if hits is None else hits
    out, orphans = {}, []
    for h in hits:
        b = owner(h.file, h.line, h.marker)
        if b is None:
            orphans.append(h)
            continue
        out.setdefault(b, {}).setdefault(h.file, []).append((h.line, h.marker))
    return out, orphans


def print_batch_map(stream=None, hits=None):
    """The file:line -> batch map, batch by batch, with the totals."""
    import sys
    stream = stream or sys.stdout
    by_batch, orphans = batch_map(hits)
    order = {b: i for i, b in enumerate(BATCHES)}
    for b in sorted(by_batch, key=lambda x: order.get(x, 99)):
        files = by_batch[b]
        total = sum(len(v) for v in files.values())
        stream.write("%s  %d markers in %d files\n" % (b, total, len(files)))
        for f, items in sorted(files.items()):
            marks = collections.Counter(m for _l, m in items)
            lines = sorted({l for l, _m in items})
            spans, start, prev = [], None, None
            for l in lines:
                if start is None:
                    start = prev = l
                elif l <= prev + 3:
                    prev = l
                else:
                    spans.append((start, prev))
                    start = prev = l
            if start is not None:
                spans.append((start, prev))
            stream.write("    %s:%s  %s\n" % (f, ",".join("%d" % a if a == z else "%d-%d" % (a, z) for a, z in spans[:12])
                                             + (",…" if len(spans) > 12 else ""),
                                             " ".join("%s=%d" % kv for kv in sorted(marks.items()))))
    for h in orphans:
        stream.write("ORPHAN %s:%d %s\n" % (h.file, h.line, h.marker))
    return by_batch, orphans

