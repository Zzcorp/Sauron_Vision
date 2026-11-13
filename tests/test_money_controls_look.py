"""The money controls' look contract (UI plan §10, S1a, 2026-11-06).

The words, forms, PIN steps, confirm steps and focus order of every control
that moves money stay exactly as they are; a display stage changes only how
they look, and the look must never mislead. Each row of the plan's §10
table is pinned here as far as S1a takes it: the selector exists, it paints
with the stated tokens, and no rule paints it in a forbidden way. What a
later stage restyles (the ticket and its dialog in S2.1, the close dialog
and CLOSE ALL's stop variant in S2.2, /ops/' OFF chips in S2.6) is pinned
here for what must already hold: no green on a SELL, no red slab on a
protective action, REAL the only solid red.

  * THE DEAL TICKET: SELL in coral, BUY in jade, never a fill; the price in
    the number face; a fixed width, so a ticking price never moves a button;
    a stale ticket dashed and its price muted; the REAL chip in the middle.
  * TAKE TRADE: the confirm is never green on a SELL (S1a makes it neutral:
    the side's colours arrive with the dialog's markup in S2.1), and a
    "danger" confirm is the same neutral outline, never the loss coral; a
    dialog that takes the trading PIN (real money) carries the REAL red top
    edge, and no other dialog does (2026-11-07).
  * THE SIGNAL CARD: TAKE TRADE / ADD in the signal's side (a bearish
    signal is a SELL), PASS a neutral ghost (it dismisses; it loses nothing).
    Its RULE value breaks between words or after an underscore when it
    must, never inside a word, and stays in its cell (2026-11-07).
  * THE QUOTE CARD: LONG jade, SHORT coral, outlines, no gradient slabs.
  * CLOSE, RETRY CLOSE, CLOSE ALL, turn off, all off, Cancel a withdrawal:
    neutral outlines (.btn-danger), never a red fill — turning off and
    closing are the safe directions, and a red fill is REAL's alone.
  * TURN ON: never a cheerful green slab (.btn-primary is the light primary).
  * PIN FIELDS: every PIN input keeps its type, its inputmode and its
    autocomplete; /brokers/' world boxes stay plain checkboxes; /setup/
    keeps "blank = no cap" in words; CLOSE ALL keeps "whole book".
  * EVERY PRICE AND P&L CELL: a flash is a background wash, never the
    text's colour; count-ups run on counts only; the bottom band's lists
    keep their state colours (a loss, an alarm, a gold count).
  * WHOSE MONEY, everywhere it is said: every LIVE / REAL label is the
    REAL chip, never the loss coral (2026-11-07).
  * ON A PHONE: every button keeps the 44 px tap floor, CLOSE and Close
    all 48 px.

Display only: nothing here posts, trades or calls a broker. The measured
class renders synthetic pages through the test client and computes the
colours in a headless Chromium with every network URL blocked (skipped,
not failed, where the machine has none).

THE MAGIC KEPT (2026-11-12). Sauron's light came back on the frame, and
this module holds its line on the money controls: at rest every one of them
is as S1a left it (no shadow at all); the Eye's green never reaches one,
with hover and focus forced; a BUY or a SELL lights in its own side's
colour, inside its own box only (inset), so nothing beside it changes;
TURN ON, CLOSE, CLOSE ALL, the dialog's confirm and PASS take no light.

MARKET SHUT (2026-11-12, at the merge of main's #99, #100 and #101). A
signal whose market is shut says so on its card, its headband row and
/signals/, and with the optional hold on it waits in a MARKET SHUT section.
On the kit: the badge is the warning amber, an outline, never a fill (REAL
is the only solid red) and never the Eye's green; the hour is a figure, on
an opaque ground, unlit in every Ambience, never cut; nothing is under
11 px; the section's ▶ TICKET wears its signal's side like LEFT THE RAIL's.
Main's words, hooks and calls are as main wrote them.

Run with:  python manage.py test tests.test_money_controls_look
"""
import json
import pathlib
import re
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests.test_close_advice import CHROME, _legacy, _quote, _trade
from tests.test_design_tokens import PALETTE, block, decls, read, rules
from tests.test_ui_s0_fixes import _get, _measure

ROOT = pathlib.Path(settings.BASE_DIR)
KIT = "static/css/sv-kit.css"
SAURON = "static/css/sauron.css"
OVERLAY = "static/css/sv-overlay.css"


def kit_rule(selector):
    return block(read(KIT), selector)


def kit_value(selector, prop, rel=KIT):
    """What the last top-level rule naming `selector` (alone or in a list)
    gives `prop` in a sheet: the cascade's answer for rules of one weight."""
    got = None
    for prelude, body, ctx in rules(read(rel)):
        if ctx or selector not in [s.strip() for s in prelude.split(",")]:
            continue
        for p, v in decls(body):
            if p == prop:
                got = v
    return got


#: The dialogs that take the trading PIN, which only real money asks for
#: (2026-11-07): the LIVE ticket's PIN step (base.html renders .sz-pin only
#: when the ticket is live) and an SV.overlay confirm given a secretLabel
#: (a live close, CLOSE ALL over live rows, arming or resuming a live bot).
#: These, and only these, carry the REAL red edge.
REAL_DIALOGS = (':where(body:not(.light-mode)) .sv-dialog:has(.sz-pin)',
                ':where(body:not(.light-mode)) .sv-dialog:has([data-role="secret-wrap"])')


# ══════════════════════════════════════════════════════════════════════════
# The sheets and the templates
# ══════════════════════════════════════════════════════════════════════════

class DealTicketLookTests(SimpleTestCase):

    def test_the_sides_wear_jade_and_coral_never_a_fill(self):
        css = read(SAURON)
        long_ = block(css, ".tk-long  .tk-lbl, .tk-long  .tk-px")
        short = block(css, ".tk-short .tk-lbl, .tk-short .tk-px")
        self.assertTrue(long_["color"].startswith("var(--sv-up,"), long_)
        self.assertTrue(short["color"].startswith("var(--sv-down,"), short)
        side = block(css, ".tk-side")
        self.assertEqual(side["background"], "transparent")
        self.assertIn("--sv-up-wash", block(css, ".tk-long:hover")["background"])
        self.assertIn("--sv-down-wash", block(css, ".tk-short:hover")["background"])

    def test_a_ticking_price_never_moves_a_button(self):
        side = block(read(SAURON), ".tk-side")
        self.assertEqual(side["min-width"], "104px")
        self.assertEqual(block(read(SAURON), ".sv-ticket")["font-family"], "var(--font-mono)")

    def test_a_stale_ticket_is_dashed_and_prints_no_live_price(self):
        css = read(SAURON)
        self.assertEqual(block(css, ".sv-ticket.tk-stale")["border-style"], "dashed")
        self.assertEqual(block(css, ".sv-ticket.tk-stale .tk-px,\n.sv-ticket.tk-stale .tk-v")["color"],
                         "var(--text-muted)")

    def test_the_ticket_keeps_its_two_sides_and_their_words(self):
        html = read("templates/_partials/deal_ticket.html")
        self.assertIn('class="tk-side tk-short"', html)
        self.assertIn('class="tk-side tk-long"', html)
        self.assertIn("▼ SHORT", html)
        self.assertIn("▲ LONG", html)
        self.assertIn("svTakeTradeAsset('{{ symbol|escapejs }}', 'SELL')", html)
        self.assertIn("svTakeTradeAsset('{{ symbol|escapejs }}', 'BUY')", html)


class TakeTradeDialogLookTests(SimpleTestCase):

    def test_the_confirm_is_neutral_so_never_green_on_a_sell(self):
        go = kit_rule(".sv-dialog-btn.sv-dialog-btn--go")
        self.assertEqual(go["background"], "transparent")
        self.assertEqual(go["color"], "var(--sv-ink-1)")
        self.assertIn("var(--sv-ink-1)", go["border"])
        for value in go.values():
            self.assertNotIn("--sv-eye", value)
            self.assertNotIn("--accent", value)

    def test_a_danger_confirm_is_the_same_neutral_strong_outline(self):
        """is-danger rides every SV.overlay.confirm({danger: true}) (CLOSE,
        RETRY CLOSE, CLOSE n POSITIONS, Pause, Disarm, a delete), every
        LIVE ticket on either side and the funding ticket (base.html), and
        the close-advice dialog's confirm. Painted coral, it said loss and
        SELL on a close and on a LIVE BUY (review, 2026-11-07). It is the
        neutral-strong outline every confirm wears; the side's colours
        arrive with the dialog's own markup (S2.1)."""
        rule = kit_rule(".sv-dialog-btn.sv-dialog-btn--go.is-danger")
        self.assertEqual(rule["background"], "transparent")
        self.assertEqual(rule["color"], "var(--sv-ink-1)")
        self.assertEqual(rule["border-color"], "var(--sv-ink-1)")
        for value in rule.values():
            for hue in ("--sv-down", "--accent-red", "--sv-real", "--sv-up", "--sv-eye",
                        "--accent"):
                self.assertNotIn(hue, value)

    def test_a_real_money_dialog_carries_the_real_edge(self):
        """A dialog that moves real money carries the REAL red as a 3 px top
        edge. Updated deliberately on 2026-11-07 (review of S1a): the edge
        sat on .sv-dialog.sv-dialog--danger, which plan §7 read as "the
        ticket is live or funding", but every SV.overlay.confirm({danger:
        true}) sets that class too (Delete preset, Pause, a paper close),
        the lost-answer dialog always sets it, and a funding ticket is
        paper (base.html: funding requires !live). Solid red there meant
        danger, which plan §3.9 forbids. The edge now marks the dialogs that
        take the trading PIN, which only real money asks for. What the test
        guards is unchanged: a REAL dialog carries the REAL edge."""
        for sel in REAL_DIALOGS:
            with self.subTest(selector=sel):
                self.assertEqual(kit_value(sel, "border-top"), "3px solid var(--sv-real)")

    def test_no_rule_puts_the_real_edge_on_a_danger_dialog_alone(self):
        """Solid red is REAL money, never danger or delete (plan §3.9): no
        rule paints --sv-real on a dialog but the PIN-taking ones, and a
        danger dialog's own border is the dialog's line in the dark theme
        (the coral wash it took from sv-overlay.css read as a loss)."""
        for rel in (KIT, SAURON, OVERLAY):
            for prelude, body, ctx in rules(read(rel)):
                if "--sv-real" not in body:
                    continue
                for sel in prelude.split(","):
                    if ".sv-dialog" in sel:
                        with self.subTest(file=rel, selector=sel.strip()):
                            self.assertIn(sel.strip(), REAL_DIALOGS)
        self.assertEqual(kit_value(":where(body:not(.light-mode)) .sv-dialog--danger",
                                   "border-color"), "var(--sv-line-2)")

    def test_the_real_edge_reads_the_trading_pin_s_own_markup(self):
        """The two markers mean real money: the ticket renders its PIN step
        only when live, a funding ticket is never live, and the overlay
        draws its secret field only for a secretLabel (the trading PIN)."""
        base = read("templates/base.html")
        self.assertIn("var funding = !p.sufficient && closable.length > 0 && !live;", base)
        self.assertIn("var pinHtml = live\n        ? '<fieldset class=\"sz-block sz-pin\">", base)
        overlay = read("static/js/sv-overlay.js")
        self.assertIn("var secretHtml = opts.secretLabel", overlay)
        self.assertIn('\'<label class="sv-dialog-confirm-text" data-role="secret-wrap">\'', overlay)

    def test_the_dialog_keeps_its_words_and_steps(self):
        base = read("templates/base.html")
        self.assertIn("'sv-dialog sz-dialog' + ((funding || live) ? ' sv-dialog--danger' : '')", base)
        self.assertIn('class="sv-dialog-btn" data-role="cancel">Cancel</button>', base)
        self.assertIn("'<button type=\"button\" class=\"sv-dialog-btn sv-dialog-btn--go' +", base)


class SignalCardLookTests(SimpleTestCase):

    def test_take_trade_takes_the_signal_s_side(self):
        css = read(KIT)
        buy = block(css, ".sr-pop-btn.sr-pop-btn-act")
        self.assertIn("var(--sv-up)", buy["color"])
        sell = block(css, ".sr-popup:has(.sr-pop-dir-bearish) .sr-pop-btn.sr-pop-btn-act")
        self.assertIn("var(--sv-down)", sell["color"])
        self.assertIn("var(--sv-down)", sell["border-color"])

    def test_pass_is_a_neutral_ghost(self):
        rule = kit_rule(".sr-pop-btn.sr-pop-btn-pass")
        self.assertEqual(rule["background"], "transparent")
        self.assertEqual(rule["color"], "var(--sv-ink-2)")

    def test_the_rail_keeps_its_buttons_and_words(self):
        html = read("templates/_partials/signal_rail_items.html")
        self.assertIn("sr-pop-btn sr-pop-btn-act{% if s.acted %} sr-pop-btn-add{% endif %}", html)
        self.assertIn('class="sr-pop-btn sr-pop-btn-pass"', html)
        self.assertIn("▶ TAKE TRADE", html)
        self.assertIn("▶ ADD TO POSITION", html)
        self.assertIn("✕ PASS", html)
        self.assertIn('sr-pop-dir sr-pop-dir-{{ s.direction }}', html)


class LeftTheRailLookTests(SimpleTestCase):
    """LEFT THE RAIL (railfilters, #90; on the kit at the merge of
    origin/main, 2026-11-07): ▶ TICKET opens the ticket TAKE TRADE opens,
    so it wears its signal's side like TAKE TRADE (a short signal is a
    SELL), an outline, never the Eye's wash; ↺ BRING BACK is a plain card
    button. A row with no side keeps the plain look."""

    def test_the_ticket_wears_the_signal_s_side(self):
        css = read(KIT)
        for side, token in (("long", "var(--sv-up)"), ("short", "var(--sv-down)")):
            rule = block(css, '.sr-gone-row[data-side="%s"] .sr-gone-btn.sr-gone-btn-ticket' % side)
            with self.subTest(side=side):
                self.assertEqual(rule["background"], "transparent")
                self.assertEqual(rule["color"], token)
                self.assertIn(token, rule["border"])
                for value in rule.values():
                    self.assertNotIn("--sv-eye", value)
                    self.assertNotIn("--accent", value)

    def test_bring_back_is_a_plain_card_button(self):
        rule = kit_rule(":where(body:not(.light-mode)) .sr-gone-btn")
        self.assertEqual(rule["background"], "var(--sv-bg-3)")
        self.assertEqual(rule["border-color"], "var(--sv-line-2)")
        self.assertEqual(rule["color"], "var(--sv-ink-1)")

    def test_the_departures_keep_their_buttons_words_and_side(self):
        html = read("templates/_partials/signal_rail_items.html")
        self.assertIn('data-side="{{ g.facts.side }}"', html)
        self.assertIn('class="sr-gone-btn sr-gone-btn-ticket"', html)
        self.assertIn("window.svTakeTrade && window.svTakeTrade({{ g.signal_id }});\">▶ TICKET</button>",
                      html)
        self.assertIn('class="sr-gone-btn" data-sv-unpass="{{ g.signal_id }}"', html)
        self.assertIn("↺ BRING BACK", html)


class MarketShutLookTests(SimpleTestCase):
    """MARKET SHUT (main's #99, #100 and #101, on the kit at their merge,
    2026-11-12). The section's ▶ TICKET is LEFT THE RAIL's: it opens the
    ticket TAKE TRADE opens, so it wears its signal's side, an outline,
    never the Eye's wash main's sheet gives every .sr-gone-btn. And nothing
    main wrote is touched: its words, its hooks, its calls."""

    def test_the_section_s_ticket_wears_the_signal_s_side(self):
        css = read(KIT)
        for side, token, wash in (("long", "var(--sv-up)", "var(--sv-up-wash)"),
                                  ("short", "var(--sv-down)", "var(--sv-down-wash)")):
            sel = '.sr-wait-row[data-side="%s"] .sr-gone-btn.sr-gone-btn-ticket' % side
            left = sel.replace(".sr-wait-row", ".sr-gone-row")
            with self.subTest(side=side):
                rule, hover = block(css, sel), block(css, sel + ":hover")
                self.assertEqual(rule, block(css, left))                # LEFT THE RAIL's, to the letter
                self.assertEqual(hover, block(css, left + ":hover"))
                self.assertEqual(rule["background"], "transparent")
                self.assertEqual(rule["color"], token)
                self.assertIn(token, rule["border"])
                self.assertEqual(hover["background"], wash)
                for value in list(rule.values()) + list(hover.values()):
                    self.assertNotIn("--sv-eye", value)
                    self.assertNotIn("--accent", value)

    def test_main_s_words_hooks_and_calls_are_as_main_wrote_them(self):
        rail = read("templates/_partials/signal_rail_items.html")
        chips = read("templates/_partials/rail_sig_chips.html")
        rows = read("templates/_partials/signal_rows_compact.html")
        base = read("templates/base.html")
        signals = read("templates/dashboard/signals_list.html")
        for html, marker in (
                (rail, '<section class="sr-shut-sec" data-sv-shut aria-label="Signals whose market cannot trade now">'),
                (rail, '<span class="sr-gone-title">MARKET SHUT</span>'),
                (rail, '<span class="sr-gone-count" data-sv-rail-n="waiting">'),
                (rail, '<div class="sr-wait-row" data-sv-row data-waiting data-reason="{{ g.reason }}"'),
                (rail, '<span class="sr-shut-tag">MARKET SHUT</span>{% if s.rail.opens %} '
                       '<span class="sr-shut-opens">{{ s.rail.opens }}</span>{% endif %}</div>'),
                (rail, "{% if s.rail.market == 'shut' %} data-market=\"shut\"{% endif %}"),
                (rail, '<div class="sr-pop-fact sr-pop-fact-shut"><span class="sr-pop-k">market</span> shut'),
                (rail, "No signal is waiting for its market."),
                (rows, "{% if sig.rail.market == 'shut' %} data-market=\"shut\"{% endif %}"),
                (rows, 'MARKET SHUT{% if sig.rail.opens %} · {{ sig.rail.opens }}{% endif %}</span>'),
                (chips, 'class="rf-chip rf-shut" data-f-key="shut" data-f-val="1" data-f-toggle'),
                (chips, 'class="rf-chip rf-shut" data-f-key="shut_off" data-f-val="0" data-f-toggle'),
                (chips, '>SHUT <b data-sv-rail-n="waiting">'),
                (chips, '>SHUT <b data-sv-rail-n="shut">'),
                (base, '<span class="dk">MARKET SHUT</span><span class="dv" data-sv-rail-n="waiting">'),
                (base, '<span class="rf-k">MARKET SHUT</span><button type="button" class="rf-opt" '
                       'data-f-key="shut" data-f-val="0"'),
                (base, '(d.market ? " · " + d.market : "")'),
                (signals, '<span class="badge badge-high sig-shut" title="{{ r.market.title }}">MARKET SHUT</span>'),
                (signals, '<span class="sig-shut-opens">{{ r.market.opens }}</span>'),
                (signals, '<div class="sig-hold" title="{{ r.hold.title }}">{{ r.hold.text }}</div>')):
            with self.subTest(marker=marker[:56]):
                self.assertIn(marker, html)
        # Both ▶ TICKET buttons, LEFT THE RAIL's and MARKET SHUT's, open the
        # ticket TAKE TRADE opens, and neither is given a word more.
        self.assertEqual(rail.count("window.svTakeTrade && window.svTakeTrade({{ g.signal_id }});\">"
                                    "▶ TICKET</button>"), 2)


class ProtectiveButtonsLookTests(SimpleTestCase):
    """.btn-danger carries CLOSE, RETRY CLOSE, CLOSE ALL, turn off, all off and
    a withdrawal's Cancel: a neutral outline now, never a red slab."""

    def test_btn_danger_is_a_neutral_outline(self):
        rule = block(read(SAURON), ".btn.btn-danger")
        self.assertEqual(rule["background"], "transparent")
        self.assertTrue(rule["color"].startswith("var(--sv-ink-1"), rule)
        self.assertTrue(rule["border-color"].startswith("var(--sv-line-3"), rule)
        for value in rule.values():
            self.assertNotIn("--accent-red", value)
            self.assertNotIn("#3a0e0e", value)

    def test_btn_primary_is_the_light_primary_not_a_green_slab(self):
        rule = block(read(SAURON), ".btn.btn-primary")
        self.assertTrue(rule["background"].startswith("var(--sv-ink-1"), rule)
        self.assertTrue(rule["color"].startswith("var(--sv-bg-0"), rule)
        for value in rule.values():
            self.assertNotIn("--accent", value)
            self.assertNotIn("rgba(0,232,104", value)
        # Hovered and focused too (the magic kept, 2026-11-12): the primary
        # button is also the PIN-guarded TURN ON that arms real money, so no
        # rule of the shell gives it, in any state, a glow or the Eye's green.
        states = 0
        for rel in (SAURON, KIT):
            for prelude, body, ctx in rules(read(rel)):
                if ".btn-primary" not in prelude or "light-mode" in prelude:
                    continue
                states += ":hover" in prelude or ":focus" in prelude
                for prop, value in decls(body):
                    with self.subTest(file=rel, rule=prelude, prop=prop):
                        self.assertNotIn("--sv-glow", value)
                        self.assertNotIn("--sv-eye", value)
                        self.assertNotIn("0,232,104", value.replace(" ", ""))
                        if prop in ("box-shadow", "text-shadow", "filter"):
                            self.assertNotRegex(value, r"--accent\b(?!-)")
        self.assertGreater(states, 0)

    def test_the_buttons_keep_their_words_and_hooks(self):
        positions = read("templates/dashboard/positions_list.html")
        self.assertIn('class="btn btn-sm btn-danger" data-sv-close-trade="{{ p.trade_id }}">'
                      "{% if p.status == 'CLOSE_PENDING' %}RETRY CLOSE{% else %}CLOSE{% endif %}",
                      positions)
        self.assertIn('class="btn btn-sm btn-danger" id="svCloseAll"', positions)
        self.assertIn("whole book", positions)
        ops = read("templates/dashboard/ops.html")
        self.assertIn('{% if r.comp.is_enabled %}btn-danger{% else %}btn-primary{% endif %}">'
                      '{% if r.comp.is_enabled %}turn off{% else %}turn on{% endif %}', ops)
        self.assertIn('class="btn btn-sm btn-danger">all off</button>', ops)
        self.assertIn('class="btn btn-sm">all on</button>', ops)
        self.assertIn('class="btn btn-sm btn-danger">Cancel</button>',
                      read("templates/dashboard/withdrawals.html"))


#: Every numeric PIN field (§10 "PIN entries"), as it is today: per file,
#: the autocomplete each password input with inputmode="numeric" keeps.
PIN_FIELDS = {
    "templates/dashboard/locked.html": ["one-time-code"] * 4,         # the lock
    "templates/registration/login_pin.html": ["one-time-code"] * 4,   # the second gate
    "templates/base.html": ["off"] + ["one-time-code"] * 4,           # the ticket's PIN, the idle lock
    "templates/dashboard/ops.html": ["off"],                          # PIN ____ TURN ON
}


class PinFieldTests(SimpleTestCase):

    def test_every_pin_field_keeps_its_type_inputmode_and_autocomplete(self):
        for rel, autos in PIN_FIELDS.items():
            html = read(rel)
            fields = [t for t in re.findall(r"<input\b[^>]*>", html)
                      if 'type="password"' in t and 'inputmode="numeric"' in t]
            with self.subTest(file=rel):
                got = [re.search(r'autocomplete="([^"]*)"', t).group(1) for t in fields]
                self.assertEqual(sorted(got), sorted(autos), fields)

    def test_the_ticket_pin_and_the_brokers_pin_keep_theirs(self):
        base = read("templates/base.html")
        self.assertIn("'<input type=\"password\" inputmode=\"numeric\" autocomplete=\"off\" ' +", base)
        brokers = read("templates/dashboard/brokers.html")
        pin = re.search(r'<input type="password" name="pin"[^>]*>', brokers).group(0)
        self.assertIn('autocomplete="off"', pin)

    def test_the_world_choices_stay_plain_checkboxes_with_their_words(self):
        brokers = read("templates/dashboard/brokers.html")
        for name, words in (("confirm_key_change", "Replace keys"),
                            ("demo", None),
                            ("confirm_world_change", "Switch world")):
            with self.subTest(box=name):
                self.assertRegex(brokers, r'<input type="checkbox" name="%s"' % name)
                if words:
                    self.assertIn(words, brokers)
        self.assertNotIn("sv-switch", brokers)

    def test_blank_still_means_no_cap_in_words(self):
        self.assertIn("blank = no cap", read("templates/dashboard/setup.html"))


class PriceCellLookTests(SimpleTestCase):

    def test_a_flash_is_a_background_wash_never_the_text_colour(self):
        for rel in (OVERLAY, KIT):
            for prelude, body, ctx in rules(read(rel)):
                if not prelude.startswith("@keyframes sv-flash"):
                    continue
                with self.subTest(file=rel, keyframes=prelude):
                    props = set(re.findall(r"([a-z-]+)\s*:", body))
                    self.assertEqual(props, {"background-color"})

    def test_the_flash_fades_in_600ms_on_the_washes(self):
        rule = kit_rule(".sv-flash")
        self.assertEqual(rule["animation-duration"], "600ms")
        frames = [b for p, b, c in rules(read(KIT)) if p == "@keyframes sv-flash-up"]
        self.assertIn("var(--sv-up-wash)", frames[0])
        frames = [b for p, b, c in rules(read(KIT)) if p == "@keyframes sv-flash-down"]
        self.assertIn("var(--sv-down-wash)", frames[0])

    def test_count_ups_run_on_counts_only(self):
        """sv-motion's count-up reads data-sv-count; it rides two tabs of the
        command centre (bots and history), never a price or a P&L."""
        found = sorted(p.relative_to(ROOT).as_posix()
                       for p in (ROOT / "templates").rglob("*.html")
                       if "data-sv-count" in p.read_text(encoding="utf-8"))
        self.assertEqual(found, ["templates/dashboard/_command_bots.html",
                                 "templates/dashboard/_command_history.html"])


# ══════════════════════════════════════════════════════════════════════════
# Measured: the colours the browser computes
# ══════════════════════════════════════════════════════════════════════════

PROBE = r"""(function () {
    function paint(el) {
        if (!el) return null;
        var c = getComputedStyle(el);
        return { bg: c.backgroundColor, img: c.backgroundImage, color: c.color,
                 border: c.borderTopColor, bw: c.borderTopWidth, text: (el.textContent || '').trim().slice(0, 30),
                 shadow: c.boxShadow };
    }
    function all(sel) { return Array.prototype.map.call(document.querySelectorAll(sel), paint); }
    // The card's RULE value as the browser breaks it, the card opened as a
    // click opens it (pinned, shown: a hover card is display: none where
    // the browser reports no hover, as a headless one does): each
    // character's box, grouped by the line it sits on; the ink's edges
    // against its cell's.
    function rule(pop) {
        var cell = Array.prototype.filter.call(pop.querySelectorAll('.sr-pop-grid > div'), function (d) {
            var k = d.querySelector('.sr-pop-k');
            return k && k.textContent.trim().toLowerCase() === 'rule';
        })[0];
        var v = cell && cell.querySelector('.sr-pop-v');
        if (!v) return null;
        var was = pop.className;
        pop.classList.add('sv-pinned', 'show');
        try {
            var range = document.createRange(), lines = [], top = null, n;
            var walk = document.createTreeWalker(v, NodeFilter.SHOW_TEXT);
            while ((n = walk.nextNode())) {
                for (var i = 0; i < n.data.length; i++) {
                    range.setStart(n, i); range.setEnd(n, i + 1);
                    var r = range.getClientRects()[0];
                    if (!r) continue;
                    if (top === null || r.top > top + r.height / 2) { lines.push(''); top = r.top; }
                    lines[lines.length - 1] += n.data.charAt(i);
                }
            }
            range.selectNodeContents(v);
            var ink = range.getBoundingClientRect(), box = cell.getBoundingClientRect();
            return { text: v.textContent, lines: lines, size: getComputedStyle(v).fontSize,
                     ink: [ink.left, ink.right], cell: [box.left, box.right],
                     width: pop.getBoundingClientRect().width };
        } finally {
            pop.className = was;
        }
    }
    var out = { rail: [] };
    Array.prototype.forEach.call(document.querySelectorAll('.sr-popup'), function (pop) {
        var dir = pop.querySelector('.sr-pop-dir');
        out.rail.push({ dir: dir ? dir.className : '', act: paint(pop.querySelector('.sr-pop-btn-act')),
                        pass: paint(pop.querySelector('.sr-pop-btn-pass')), rule: rule(pop) });
    });
    out.quoteLong = all('.dh-pop .sr-pop-btn-act, .wl-pop .sr-pop-btn-act');
    out.quoteShort = all('.dh-pop .sr-pop-btn-short, .wl-pop .sr-pop-btn-short');
    out.close = all('[data-sv-close-trade]');
    out.closeAll = all('#svCloseAll');
    out.danger = all('button.btn-danger');
    out.primary = all('button.btn-primary');
    out.tkLong = all('.tk-long'); out.tkShort = all('.tk-short');
    out.tkLongPx = all('.tk-long .tk-px'); out.tkShortPx = all('.tk-short .tk-px');
    out.tkVenue = all('.tk-venue--live');
    return JSON.stringify(out);
})()"""


def parse(c):
    m = re.match(r"rgba?\(([^)]+)\)", c or "")
    if not m:
        return None
    p = [float(x) for x in re.split(r"[ ,/]+", m.group(1).strip()) if x]
    return (p[0], p[1], p[2], p[3] if len(p) > 3 else 1.0)


def is_red(c, min_alpha=0.5):
    p = parse(c)
    return bool(p) and p[3] >= min_alpha and p[0] >= 150 and p[1] < 130 and p[2] < 140


def is_green(c, min_alpha=0.5):
    p = parse(c)
    return bool(p) and p[3] >= min_alpha and p[1] >= 150 and p[0] < 130


def is_neutral(c):
    p = parse(c)
    return bool(p) and max(p[:3]) - min(p[:3]) < 48


def rgb_of(hexv):
    h = hexv.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


UP, DOWN, EYE = rgb_of("#24B582"), rgb_of("#FF6B6E"), rgb_of("#00E868")


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class MoneyControlsMeasuredTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from tests.test_signal_acted_and_sizing import _signal
        from tests.test_ops_cockpit import _component
        User = get_user_model()
        user = User.objects.create_user("s1a_money", password="x", is_staff=True,
                                        is_superuser=True)
        inst = _quote("BTCUSD", 60600).instrument
        _signal(inst, direction="bullish", rule="s1a_up")
        eth = _quote("ETHUSD", 2600).instrument
        _signal(eth, direction="bearish", entry=2600, stop=2700, target=2400,
                rule="s1a_down")
        # A rule name longer than the card's RULE column (synthetic).
        _signal(inst, direction="bullish", rule="trend_breakout_crossover")
        _trade(user)
        _legacy(user)
        _component("s1a_on_switch", is_enabled=True)
        _component("s1a_off_switch", is_enabled=False)
        client = Client()
        client.force_login(user)
        pages = {url: _get(client, url) for url in
                 ("/command/", "/positions/", "/ops/", "/instruments/BTCUSD/")}
        cls.got = {url: got for (url, _w), got in
                   _measure(pages, ((1440, 900),), PROBE, "sv-s1a-money-").items()}

    def test_the_fixture_reaches_every_control(self):
        cmd, pos, ops = self.got["/command/"], self.got["/positions/"], self.got["/ops/"]
        dirs = {r["dir"].split()[-1] for r in cmd["rail"]}
        self.assertTrue({"sr-pop-dir-bullish", "sr-pop-dir-bearish"} <= dirs, dirs)
        self.assertTrue(pos["close"] and pos["closeAll"])
        self.assertTrue(ops["primary"] and ops["danger"])
        tk = self.got["/instruments/BTCUSD/"]
        self.assertTrue(tk["tkLong"] and tk["tkShort"])

    def test_take_trade_wears_the_signal_s_side_and_pass_is_neutral(self):
        for card in self.got["/command/"]["rail"]:
            act, pas = card["act"], card["pass"]
            with self.subTest(direction=card["dir"]):
                if act:
                    want = DOWN if card["dir"].endswith("bearish") else UP
                    self.assertEqual(act["color"], want, act)
                    self.assertEqual(act["border"], want, act)
                    self.assertFalse(is_red(act["bg"]) or is_green(act["bg"]), act)
                    self.assertEqual(act["img"], "none")
                self.assertTrue(is_neutral(pas["color"]), pas)
                self.assertFalse(is_red(pas["bg"], 0.05), pas)

    def test_a_long_rule_name_never_splits_inside_a_word(self):
        """S1a's 11 px labels narrowed the card's RULE value, and
        overflow-wrap: anywhere then split a long name mid-word
        ("trend_breakou" over "t_cr…", 2026-11-07). At 1440 it breaks only
        between words or after an underscore when it must, keeps every
        character and its 11 px, and stays in its cell."""
        got = [c["rule"] for c in self.got["/command/"]["rail"]
               if c["rule"] and c["rule"]["text"].startswith("trend_breakout_")]
        self.assertEqual(len(got), 1, self.got["/command/"]["rail"])
        rule = got[0]
        self.assertEqual("".join(rule["lines"]), rule["text"], rule)
        for line, after in zip(rule["lines"], rule["lines"][1:]):
            self.assertTrue(line.endswith(("_", " ", "-")) or after.startswith(" "),
                            "the rule name splits inside a word: %r" % rule["lines"])
        self.assertGreaterEqual(float(rule["size"][:-2]), 11, rule)
        self.assertGreaterEqual(rule["ink"][0], rule["cell"][0] - 0.5, rule)
        self.assertLessEqual(rule["ink"][1], rule["cell"][1] + 0.5, rule)

    def test_the_quote_card_long_is_jade_and_short_is_coral_outlines(self):
        cmd = self.got["/command/"]
        for got, want in ((cmd["quoteLong"], UP), (cmd["quoteShort"], DOWN)):
            for b in got:
                with self.subTest(button=b["text"]):
                    self.assertEqual(b["color"], want)
                    self.assertEqual(b["img"], "none")
                    self.assertFalse(is_red(b["bg"]) or is_green(b["bg"]), b)

    def test_close_close_all_and_turn_off_are_neutral_outlines(self):
        buttons = (self.got["/positions/"]["close"] + self.got["/positions/"]["closeAll"]
                   + self.got["/ops/"]["danger"])
        self.assertTrue(buttons)
        for b in buttons:
            with self.subTest(button=b["text"]):
                self.assertEqual(b["img"], "none")
                self.assertFalse(is_red(b["bg"], 0.05) or is_red(b["color"]), b)
                self.assertTrue(is_neutral(b["color"]), b)

    def test_turn_on_is_no_green_slab(self):
        for b in self.got["/ops/"]["primary"]:
            with self.subTest(button=b["text"]):
                self.assertEqual(b["img"], "none")
                self.assertFalse(is_green(b["bg"]), b)
                self.assertTrue(is_neutral(b["bg"]), b)

    def test_the_ticket_sides_in_jade_and_coral_on_no_fill(self):
        tk = self.got["/instruments/BTCUSD/"]
        for px in tk["tkLongPx"]:
            self.assertEqual(px["color"], UP)
        for px in tk["tkShortPx"]:
            self.assertEqual(px["color"], DOWN)
        for side in tk["tkLong"] + tk["tkShort"]:
            self.assertFalse(is_red(side["bg"], 0.05) or is_green(side["bg"], 0.05), side)
        for chip in tk["tkVenue"]:
            self.assertEqual(chip["bg"], rgb_of("#CC3A40"))


# ══════════════════════════════════════════════════════════════════════════
# Measured: the review of 2026-11-07
# ══════════════════════════════════════════════════════════════════════════

# The neutrals are the Eye-lit ones since 2026-11-12 (a look, updated:
# tests/test_design_tokens.PALETTE holds them, at S1a's lightness).
REAL, INK1 = rgb_of("#CC3A40"), rgb_of(PALETTE["--sv-ink-1"])
LINE2, LINE3 = rgb_of(PALETTE["--sv-line-2"]), rgb_of(PALETTE["--sv-line-3"])
WARN, GOLD = rgb_of("#F29B38"), rgb_of("#D6BC5E")
CLEAR = "rgba(0, 0, 0, 0)"

#: The overlay's own dialogs come from sv-overlay.js, loaded into the page
#: (SV.overlay.confirm as the pages call it). The ticket, the funding ticket
#: and the lost answer are built as base.html builds them, with the classes
#: TakeTradeDialogLookTests pins.
DIALOG_PROBE = r"""(async function () {
    await new Promise(function (ok, bad) {
        var s = document.createElement('script');
        s.src = %(overlay)s;
        s.onload = ok;
        s.onerror = function () { bad(new Error('sv-overlay.js did not load')); };
        document.head.appendChild(s);
    });
    function paint(dlg) {
        var c = getComputedStyle(dlg), go = getComputedStyle(dlg.querySelector('.sv-dialog-btn--go'));
        return { top: c.borderTopWidth, topColor: c.borderTopColor, side: c.borderLeftColor,
                 title: getComputedStyle(dlg.querySelector('.sv-dialog-title')).color,
                 goColor: go.color, goBorder: go.borderTopColor, goBg: go.backgroundColor,
                 goImg: go.backgroundImage };
    }
    var out = {};
    var asks = {
        danger: { danger: true, title: 'Close this position?', confirmLabel: 'CLOSE POSITION' },
        liveClose: { danger: true, title: 'Close this position?', secretLabel: 'Trading PIN',
                     confirmLabel: 'CLOSE LIVE POSITION' },
        armLive: { title: 'Arm the bot LIVE', secretLabel: 'Your trading PIN', confirmLabel: 'Arm LIVE' },
        plain: { title: 'Save the preset?', confirmLabel: 'Save' }
    };
    Object.keys(asks).forEach(function (k) {
        var before = document.querySelectorAll('.sv-dialog').length;
        SV.overlay.confirm(asks[k]);
        var all = document.querySelectorAll('.sv-dialog');
        if (all.length !== before + 1) throw new Error('no dialog for ' + k);
        out[k] = paint(all[all.length - 1]);
        all[all.length - 1].remove();
    });
    var foot = function (go) {
        return '<div class="sv-dialog-foot"><button type="button" class="sv-dialog-btn" data-role="cancel">Cancel</button>'
             + '<button type="button" class="sv-dialog-btn sv-dialog-btn--go' + go + '" data-role="ok">OK</button></div>';
    };
    var head = '<div class="sv-dialog-head"><span class="sv-dialog-title">BUY BTCUSD</span></div>';
    var built = {
        liveTicket: '<div class="sv-dialog sz-dialog sv-dialog--danger">' + head
            + '<div class="sv-dialog-body"><fieldset class="sz-block sz-pin"><legend>Trading PIN</legend>'
            + '<input type="password" inputmode="numeric" autocomplete="off"></fieldset></div>' + foot(' is-danger') + '</div>',
        fundingTicket: '<div class="sv-dialog sz-dialog sv-dialog--danger">' + head
            + '<div class="sv-dialog-body"></div>' + foot(' is-danger') + '</div>',
        paperTicket: '<div class="sv-dialog sz-dialog">' + head + '<div class="sv-dialog-body"></div>' + foot('') + '</div>',
        lostAnswer: '<div class="sv-dialog sv-dialog--danger" data-sv-persist="">'
            + '<div class="sv-dialog-head"><span class="sv-dialog-title">The order may have gone</span></div>'
            + '<div class="sv-dialog-body"></div><div class="sv-dialog-foot">'
            + '<button type="button" class="sv-dialog-btn sv-dialog-btn--go">Close</button></div></div>'
    };
    Object.keys(built).forEach(function (k) {
        var wrap = document.createElement('div');
        wrap.innerHTML = built[k];
        var dlg = wrap.firstChild;
        document.body.appendChild(dlg);
        out[k] = paint(dlg);
        dlg.remove();
    });
    return JSON.stringify(out);
})()""" % {"overlay": json.dumps((ROOT / "static/js/sv-overlay.js").as_uri())}


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class DialogsMeasuredTests(TestCase):
    """The confirm dialogs as the browser paints them (2026-11-07): every
    confirm, "danger" or not, is the neutral-strong outline; the REAL red
    top edge sits on the dialogs that take the trading PIN (the LIVE
    ticket, a live close, arming a live bot) and on no other: not a paper
    close, not the funding ticket (paper), not the lost answer."""

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("s1a_dialogs", password="x", is_staff=True)
        client = Client()
        client.force_login(user)
        pages = {"/command/": _get(client, "/command/")}
        cls.got = _measure(pages, ((1440, 900),), DIALOG_PROBE,
                           "sv-s1a-dialogs-")[("/command/", 1440)]

    def test_every_confirm_is_the_neutral_strong_outline(self):
        for name, d in sorted(self.got.items()):
            with self.subTest(dialog=name):
                self.assertEqual(d["goColor"], INK1, d)
                self.assertEqual(d["goBorder"], INK1, d)
                self.assertEqual(d["goBg"], CLEAR, d)
                self.assertEqual(d["goImg"], "none", d)
                self.assertEqual(d["title"], INK1, d)

    def test_the_real_edge_is_on_the_dialogs_that_take_the_trading_pin(self):
        for name in ("liveTicket", "liveClose", "armLive"):
            with self.subTest(dialog=name):
                d = self.got[name]
                self.assertEqual((d["top"], d["topColor"]), ("3px", REAL), d)

    def test_no_other_dialog_wears_red(self):
        for name in ("danger", "fundingTicket", "paperTicket", "lostAnswer", "plain"):
            with self.subTest(dialog=name):
                d = self.got[name]
                self.assertEqual(d["top"], "1px", d)
                self.assertEqual(d["topColor"], LINE2, d)
                self.assertEqual(d["side"], LINE2, d)


SHELL_MARKS_PROBE = r"""(function () {
    var out = {};
    function paint(e) {
        var c = getComputedStyle(e);
        return { color: c.color, bg: c.backgroundColor, border: c.borderTopColor,
                 edge: c.borderLeftColor, edgeW: c.borderLeftWidth };
    }
    // The bottom band's lists: a value, a gain, a loss, an alarm, a gold count.
    var dd = document.createElement('div');
    dd.className = 'ip-dropdown';
    dd.innerHTML = '<div class="ip-dd-grid">' + ['', 'up', 'down', 'red', 'gold'].map(function (k) {
        return '<div class="ip-dd-cell"><span class="dk">K</span><span class="dv ' + k + '">1.00</span></div>';
    }).join('') + '</div>';
    document.body.appendChild(dd);
    out.dv = {};
    Array.prototype.forEach.call(dd.querySelectorAll('.dv'), function (e) {
        out.dv[e.className.replace('dv', '').trim() || 'plain'] = getComputedStyle(e).color;
    });
    dd.remove();
    out.pageRed = Array.prototype.map.call(document.querySelectorAll('.ip-dd-cell .dv.red'),
                                           function (e) { return getComputedStyle(e).color; });
    // Whose money, wherever it is said.
    var host = document.querySelector('.page-content') || document.body;
    var t = document.createElement('div');
    t.innerHTML = '<span class="sv-adv-world is-live">REAL MONEY</span><span class="pos-pop-venue is-live">LIVE</span>'
        + '<span class="hq-tag hq-tag--live">LIVE MONEY</span><span class="hq-brk hq-brk--live">eToro<small>LIVE</small></span>'
        + '<span class="ib-env ib-env--live">LIVE</span><span class="bk-env bk-env--live">eToro · LIVE</span>'
        + '<div class="hq-acct hq-acct--live">acct</div>'
        + '<span class="sr-stage sr-stage-bearish">TRADEABLE</span><span class="sr-stage sr-stage-high">PAUSED</span>';
    host.appendChild(t);
    out.marks = {};
    Array.prototype.forEach.call(t.children, function (e) { out.marks[e.className] = paint(e); });
    out.brkSmall = getComputedStyle(t.querySelector('.hq-brk--live small')).color;
    t.remove();
    return JSON.stringify(out);
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class ShellMoneyMarksMeasuredTests(TestCase):
    """What the review of 2026-11-07 found, as the browser computes it: the
    bottom band's lists keep their state colours; every LIVE / REAL label
    is the REAL chip, not the loss coral; the rail's stage chips mean what
    they say. /positions/ loads the close advice's own sheet, after the
    kit, so its world chip is measured where that sheet applies."""

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("s1a_marks", password="x", is_staff=True)
        _quote("BTCUSD", 60600)
        _trade(user)
        client = Client()
        client.force_login(user)
        pages = {"/positions/": _get(client, "/positions/")}
        cls.got = {url: got for (url, _w), got in
                   _measure(pages, ((1440, 900),), SHELL_MARKS_PROBE, "sv-s1a-marks-").items()}

    def test_the_band_s_lists_keep_their_state_colours(self):
        """A value is ink-1 (never the Eye); a gain jade, a loss coral; an
        alarm (OFF, overdue, HALTED, a negative free pool, the drawdown)
        keeps the red class's colour; a gold count its gold. The kit's
        value colour outweighed all of them (review, 2026-11-07)."""
        got = self.got["/positions/"]
        self.assertEqual(got["dv"], {"plain": INK1, "up": UP, "down": DOWN, "red": DOWN,
                                     "gold": GOLD})
        self.assertTrue(got["pageRed"])
        for c in got["pageRed"]:
            self.assertEqual(c, DOWN)

    def test_every_live_label_is_the_real_chip(self):
        """--accent-red is the loss coral since S1a: a REAL label that read
        it printed real money in the colour of a loss (plan §3.10: the REAL
        family moves to --sv-real)."""
        marks = self.got["/positions/"]["marks"]
        for cls in ("sv-adv-world is-live", "pos-pop-venue is-live", "hq-tag hq-tag--live",
                    "hq-brk hq-brk--live", "ib-env ib-env--live", "bk-env bk-env--live"):
            with self.subTest(label=cls):
                self.assertEqual(marks[cls]["bg"], REAL, marks[cls])
                self.assertEqual(marks[cls]["color"], "rgb(255, 255, 255)", marks[cls])
        self.assertEqual(self.got["/positions/"]["brkSmall"], "rgb(255, 255, 255)")
        acct = marks["hq-acct hq-acct--live"]
        self.assertEqual((acct["edgeW"], acct["edge"]), ("2px", REAL))

    def test_the_rail_s_stage_chips_say_what_they_mean(self):
        """TRADEABLE (a live stage: real money can move) is the strong
        neutral outline, never the loss coral; PAUSED and REDUCED wear the
        warning amber, never DEMO's gold outline (plan §3.9)."""
        marks = self.got["/positions/"]["marks"]
        trade = marks["sr-stage sr-stage-bearish"]
        self.assertEqual((trade["color"], trade["border"]), (INK1, LINE3))
        self.assertEqual(marks["sr-stage sr-stage-high"]["color"], WARN)


# ══════════════════════════════════════════════════════════════════════════
# Measured: MARKET SHUT on the kit (the merge of 2026-11-12)
# ══════════════════════════════════════════════════════════════════════════

MARKET_SHUT_PROBE = r"""(async function () {
  function frame() { return new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); }); }
  function each(sel, fn, root) { Array.prototype.forEach.call((root || document).querySelectorAll(sel), fn); }
  function rgba(c) {
    var m = /rgba?\(([^)]+)\)/.exec(c || '');
    if (m) { var p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    m = /color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)/.exec(c || '');
    if (m) return { r: Math.round(m[1] * 255), g: Math.round(m[2] * 255), b: Math.round(m[3] * 255), a: m[4] === undefined ? 1 : Number(m[4]) };
    return null;
  }
  function name(n) {
    return n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className.trim()
      ? '.' + n.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  }
  function over(t, u) { return { r: t.r * t.a + u.r * (1 - t.a), g: t.g * t.a + u.g * (1 - t.a), b: t.b * t.a + u.b * (1 - t.a), a: 1 }; }
  function lum(c) {
    function f(v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  function own(el) {
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3 && n.nodeValue.trim()) return true;
    }
    return false;
  }
  // A shadow that is a light: any layer with a blur. A ring (no blur) is a line.
  function lights(shadow) {
    if (!shadow || shadow === 'none') return false;
    return shadow.split(/,(?![^(]*\))/).some(function (layer) {
      var px = (layer.replace(/rgba?\([^)]+\)|color\([^)]+\)/, '').match(/-?[\d.]+px/g) || []).map(parseFloat);
      return !!px[2];
    });
  }
  // The ground an element sits on: the first opaque colour behind it, what
  // lies see-through in between (glass), and how strongly the element itself
  // is drawn (its own opacity and its ancestors', up to that ground).
  function ground(el) {
    var layers = [], glass = null, alpha = 1, solid = null;
    for (var n = el; n && n.nodeType === 1 && n !== document.documentElement; n = n.parentElement) {
      var cs = getComputedStyle(n), c = rgba(cs.backgroundColor), img = cs.backgroundImage;
      if (img && img !== 'none' && /gradient/.test(img)) {
        var stops = (img.match(/rgba?\([^)]+\)|color\(srgb [^)]+\)/g) || []).map(rgba);
        var clear = /transparent/.test(img) || stops.some(function (k) { return k && k.a < 0.999; });
        if (!clear) { solid = stops[0] || c; break; }
        if (!glass) glass = 'a gradient on ' + name(n);
      }
      if (c && c.a >= 0.999) { solid = c; break; }
      if (c && c.a > 0) { layers.push(c); if (!glass) glass = cs.backgroundColor + ' on ' + name(n); }
      alpha *= parseFloat(cs.opacity);
    }
    var g = solid || { r: 0, g: 0, b: 0, a: 1 };
    while (layers.length) g = over(layers.pop(), g);
    return { colour: g, glass: glass, onVoid: !solid || n === document.body, alpha: alpha };
  }
  // Everything open, as the operator opens it: the rail, MARKET SHUT's
  // section, the ⚙ panel, the headband's SIGNALS list, a shut card's own
  // card (pinned, shown: a hover card is not displayed where the browser
  // reports no hover).
  var still = document.createElement('style');
  still.textContent = '*, *::before, *::after { transition: none !important; }';
  document.head.appendChild(still);
  document.getElementById('signalsRail').classList.add('open');
  each('[data-sv-fhost="signals"][data-f-shut]', function (h) { h.setAttribute('data-f-shut', '1'); });
  document.getElementById('railSigPanel').hidden = false;
  document.getElementById('hbSignalsDD').style.display = 'block';
  each('.sr-signal-wrap[data-market="shut"] .sr-popup', function (p) { p.classList.add('sv-pinned', 'show'); });
  // And landed: what plays once (the rail's body fades in as it opens) is
  // at its end before a colour is read; what loops is left to be counted.
  async function settle() {
    for (var round = 0; round < 6; round++) {
      var moving = 0;
      document.getAnimations().forEach(function (a) {
        var t = a.effect && a.effect.getComputedTiming();
        if (t && t.iterations === Infinity) return;
        if (a.playState !== 'finished') { moving++; try { a.finish(); } catch (e) {} }
      });
      await frame();
      if (!moving) return;
    }
  }
  await frame();
  await settle();

  function byText(sel, text) {
    return Array.prototype.filter.call(document.querySelectorAll(sel), function (e) { return e.textContent.trim() === text; });
  }
  var cellKey = byText('#hbSignalsDD .ip-dd-cell .dk', 'MARKET SHUT'), rowKey = byText('#railSigPanel .rf-k', 'MARKET SHUT');
  var groups = {
    line: '.sr-signal .sr-shut', tag: '.sr-signal .sr-shut-tag', opens: '.sr-signal .sr-shut-opens',
    fact: '.sr-pop-fact-shut', hbLine: '#hbSignalRows .ipr-shut',
    chip: '.rf-chip.rf-shut', chipCount: '.rf-chip.rf-shut b',
    section: '.sr-shut-sec', head: '.sr-shut-sec .sr-gone-head', count: '.sr-shut-sec .sr-gone-count',
    row: '.sr-wait-row', rowTag: '.sr-wait-row .sr-gone-tag', rule: '.sr-wait-rule', words: '.sr-wait-row .sr-gone-words',
    ticket: '.sr-wait-row .sr-gone-btn-ticket', empty: '.sr-shut-sec .sr-gone-empty',
    opt: '.rf-opt[data-f-key="shut"]', cellValue: '#hbSignalsDD [data-sv-rail-n="waiting"]',
    badge: '.sig-shut', hour: '.sig-shut-opens', hold: '.sig-hold'
  };
  function look(e) {
    var c = getComputedStyle(e), r = e.getBoundingClientRect();
    return { text: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 48), side: (e.closest('[data-side]') || e).getAttribute('data-side'),
             pressed: e.getAttribute('aria-pressed'), size: parseFloat(c.fontSize), family: c.fontFamily.split(',')[0].replace(/["']/g, '').trim(),
             weight: c.fontWeight, tracking: c.letterSpacing, nums: c.fontVariantNumeric, color: c.color, bg: c.backgroundColor, img: c.backgroundImage,
             border: c.borderTopColor, borderWidth: c.borderTopWidth, borderStyle: c.borderTopStyle, shadow: c.boxShadow,
             opacity: c.opacity, box: [r.left, r.top, r.right, r.bottom] };
  }
  var out = { els: {}, refs: {}, small: [], low: [], figures: [], onVoid: [], glass: [], lit: [], spins: [], cut: [] };
  Object.keys(groups).forEach(function (k) { out.els[k] = Array.prototype.map.call(document.querySelectorAll(groups[k]), look); });
  out.els.cellKey = cellKey.map(look); out.els.rowKey = rowKey.map(look);
  // The neighbours a new control must be drawn like: the ALL chip (pressed)
  // and the LEFT chip (not pressed), LEFT THE RAIL's row in the ⚙ panel,
  // the headband's NEW 24H cell.
  var refs = {
    chipPressed: '#railSigFacets .rf-chip.rf-all[aria-pressed="true"]', chipRest: '#railSigFacets .rf-chip.rf-gone[aria-pressed="false"]',
    chipCount: '#railSigFacets .rf-chip.rf-gone b', optPressed: '.rf-opt[data-f-key="gone"][aria-pressed="true"]',
    optRest: '.rf-opt[data-f-key="gone"][aria-pressed="false"]', cellValue: '#hbSignalsDD [data-sv-rail-n="new24"]'
  };
  Object.keys(refs).forEach(function (k) { var e = document.querySelector(refs[k]); out.refs[k] = e ? look(e) : null; });
  out.refs.cellKey = byText('#hbSignalsDD .ip-dd-cell .dk', 'NEW 24H').map(look)[0] || null;
  out.refs.rowKey = byText('#railSigPanel .rf-k', 'LEFT THE RAIL').map(look)[0] || null;

  // Every element that is MARKET SHUT's, with its own text.
  var mine = [];
  each('.sr-shut, .sr-shut *, .sr-pop-fact-shut, .sr-pop-fact-shut *, .ipr-shut, .rf-shut, .rf-shut *, .sr-shut-sec, .sr-shut-sec *,'
       + ' .sig-shut, .sig-shut-opens, .sig-hold', function (e) { mine.push(e); });
  cellKey.forEach(function (k) { mine.push(k); each('*', function (e) { mine.push(e); }, k.parentElement); });
  rowKey.forEach(function (k) { mine.push(k); each('*', function (e) { mine.push(e); }, k.parentElement); });
  mine = mine.filter(function (e, i) { return mine.indexOf(e) === i; });
  out.mine = mine.length;
  mine.forEach(function (el) {
    if (!own(el)) return;
    var c = getComputedStyle(el), label = name(el) + ' "' + el.textContent.trim().slice(0, 24) + '"';
    if (parseFloat(c.fontSize) < 11) out.small.push(label + ' ' + c.fontSize);
    if (!el.getClientRects().length) return;           // not rendered on this page
    var g = ground(el), fg = rgba(c.color);
    fg = over({ r: fg.r, g: fg.g, b: fg.b, a: fg.a * g.alpha }, g.colour);
    var x = lum(fg), y = lum(g.colour), ratio = (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
    if (ratio < 4.5) out.low.push(label + ' ' + ratio.toFixed(2));
    if (/\d/.test(Array.prototype.filter.call(el.childNodes, function (n) { return n.nodeType === 3; })
                  .map(function (n) { return n.nodeValue; }).join(''))) {
      out.figures.push(label);
      if (g.onVoid) out.onVoid.push(label);
      if (g.glass) out.glass.push(label + ': ' + g.glass);
    }
  });
  // The hour on a card: inside its line, the line inside the card, at the
  // rail's own width and again with the line squeezed to 150 px.
  each('.sr-signal .sr-shut', function (line) {
    var opens = line.querySelector('.sr-shut-opens'), tag = line.querySelector('.sr-shut-tag');
    function fit(label) {
      var range = document.createRange(); range.selectNodeContents(opens);
      var ink = range.getBoundingClientRect(), box = line.getBoundingClientRect(),
          card = line.closest('.sr-signal').getBoundingClientRect();
      if (ink.left < box.left - 0.5 || ink.right > box.right + 0.5 || box.right > card.right + 0.5
          || line.scrollWidth > line.clientWidth + 1 || opens.scrollWidth > opens.clientWidth + 1) {
        out.cut.push(label + ': ' + [ink.left, ink.right, box.left, box.right, card.right].map(Math.round).join(' '));
      }
      return { under: ink.top >= tag.getBoundingClientRect().bottom - 0.5, lines: opens.getClientRects().length };
    }
    var wide = fit('at the rail width');
    line.style.width = '150px';
    var narrow = fit('squeezed to 150 px');
    line.style.width = '';
    out.fit = { wide: wide, narrow: narrow };
  });
  // Nothing lights it, in any Ambience: no text-shadow, no filter, no
  // shadow with a blur, no animation that never ends, on it or inside it.
  var modes = ['magic', 'calm', 'off'];
  for (var i = 0; i < modes.length; i++) {
    document.body.setAttribute('data-sv-ambience', modes[i]);
    await frame();
    mine.forEach(function (el) {
      ['', '::before', '::after'].forEach(function (pseudo) {
        var c = getComputedStyle(el, pseudo || null);
        if (c.textShadow !== 'none' || c.filter !== 'none' || lights(c.boxShadow)) {
          out.lit.push(modes[i] + ' ' + name(el) + pseudo + ' ' + c.textShadow + ' | ' + c.filter + ' | ' + c.boxShadow);
        }
      });
    });
    document.getAnimations().forEach(function (a) {
      var t = a.effect && a.effect.getComputedTiming(), target = a.effect && a.effect.target;
      if (t && t.iterations === Infinity && target && mine.indexOf(target) >= 0) out.spins.push(modes[i] + ' ' + name(target));
    });
  }
  // Light mode, read last: what main drew there.
  document.body.classList.add('light-mode');
  await frame();
  out.light = {};
  ['line', 'tag', 'opens', 'fact', 'hbLine', 'section', 'row', 'rowTag', 'badge', 'hour'].forEach(function (k) {
    out.light[k] = Array.prototype.map.call(document.querySelectorAll(groups[k]), look);
  });
  document.body.classList.remove('light-mode');
  return JSON.stringify(out);
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class MarketShutMeasuredTests(TestCase):
    """MARKET SHUT as the browser computes it, at 1440, on synthetic
    signals at one fixed Saturday noon (forex is shut, crypto never is):
    the rail with the optional hold off (the badge on a card, its line in
    the card's facts, the headband row, the SHUT chip), the rail with it on
    (the section, its rows and ▶ TICKET, the chip, the ⚙ row, the
    headband's count) and /signals/ (the badge, the hour, the hold's line).
    The clock is the market clock's own gate, which the suite keeps off."""

    @classmethod
    def setUpTestData(cls):
        from signals.models import SignalHold
        from tests.test_signal_market_hold import SAT_NOON, SUN_OPEN, _at, _db_inst, _sig, _switch, _t
        born = _t(2026, 11, 7, 11, 0)
        user = get_user_model().objects.create_user("s1a_shut", password="x", is_staff=True)
        down = _sig(_db_inst("SYNFXA"), born, rule="s1a_shut_down")
        _sig(_db_inst("SYNFXB"), born, rule="trend_breakout_crossover", direction="bullish",
             entry="1.08500", stop="1.08000", target="1.09500")
        _sig(_db_inst("SYNCOIN", "crypto"), born, rule="s1a_always_open", direction="bullish",
             entry="100", stop="95", target="110")
        SignalHold.objects.create(signal=down, state=SignalHold.HELD, reason=SignalHold.MARKET_SHUT,
                                  words="The forex market is shut: it opens Sunday 22:00 UTC",
                                  reopens_at=SUN_OPEN, held_at=born)
        client = Client()
        client.force_login(user)
        pages = {}
        with _at(SAT_NOON):
            pages["cards"] = _get(client, "/positions/")
            pages["signals"] = _get(client, "/signals/")
        _switch(True)
        with _at(SAT_NOON):
            pages["section"] = _get(client, "/positions/")
        cls.got = {key: got for (key, _w), got in
                   _measure(pages, ((1440, 900),), MARKET_SHUT_PROBE, "sv-s1a-shut-").items()}

    def test_the_fixture_reaches_every_one_of_them(self):
        cards, section, signals = (self.got[k]["els"] for k in ("cards", "section", "signals"))
        self.assertEqual([len(cards[k]) for k in ("line", "tag", "opens", "fact", "hbLine", "chip", "chipCount")],
                         [2, 2, 2, 2, 2, 1, 1])
        self.assertEqual([e["text"] for e in cards["opens"]], ["opens Sun 22:00 UTC"] * 2)
        self.assertEqual(cards["chip"][0]["pressed"], "true")            # the badged cards show by default
        self.assertEqual((len(cards["section"]), len(cards["opt"]), len(cards["cellKey"])), (0, 0, 0))
        # With the hold on they wait in the section, off the cards.
        self.assertEqual([len(section[k]) for k in ("section", "head", "count", "row", "rowTag", "rule",
                                                    "words", "ticket", "opt", "cellKey", "cellValue", "rowKey")],
                         [1, 1, 1, 2, 2, 2, 2, 2, 2, 1, 1, 1])
        self.assertEqual((len(section["line"]), section["chip"][0]["pressed"]), (0, "false"))
        self.assertEqual(sorted(e["side"] for e in section["ticket"]), ["long", "short"])
        self.assertEqual({e["text"] for e in section["rowTag"]}, {"SHUT"})
        self.assertEqual([len(signals[k]) for k in ("badge", "hour", "hold")], [2, 2, 1])
        for key in ("cards", "section", "signals"):
            self.assertGreater(len(self.got[key]["figures"]), 2, key)

    def test_nothing_of_it_is_under_11px(self):
        for key, got in sorted(self.got.items()):
            with self.subTest(page=key):
                self.assertGreater(got["mine"], 4)
                self.assertEqual(got["small"], [])

    def test_the_badge_is_the_warning_amber_outline_never_a_fill(self):
        cards, section, signals = (self.got[k]["els"] for k in ("cards", "section", "signals"))
        half = (242, 155, 56, 0.5)
        for tag in cards["tag"] + section["rowTag"]:
            with self.subTest(tag=tag["text"]):
                self.assertEqual(tag["color"], WARN)
                self.assertEqual((tag["bg"], tag["img"], tag["shadow"]), (CLEAR, "none", "none"))
                self.assertEqual((tag["borderWidth"], tag["borderStyle"]), ("1px", "solid"))
                self.assertEqual(_rgba(tag["border"]), half)
                self.assertEqual(tag["family"], "Inter")
        for said in cards["line"] + cards["fact"] + cards["hbLine"]:
            with self.subTest(said=said["text"]):
                self.assertEqual(said["color"], WARN)
                self.assertEqual((said["bg"], said["img"]), (CLEAR, "none"))
        # /signals/: main's .badge-high was DEMO's gold on a gold wash.
        for badge in signals["badge"]:
            self.assertEqual((badge["color"], badge["bg"], badge["img"]), (WARN, CLEAR, "none"))
            self.assertRegex(badge["shadow"], r"0px 0px 0px 1px inset$")
            self.assertEqual(_rgba(re.sub(r" 0px 0px 0px 1px inset$", "", badge["shadow"])), half)
        for key in ("cards", "section", "signals"):
            for group, els in self.got[key]["els"].items():
                for e in els:
                    with self.subTest(page=key, group=group, text=e["text"]):
                        self.assertFalse(is_red(e["bg"], 0.05), e)       # REAL is the only solid red
                        self.assertNotEqual(e["color"], GOLD, e)         # gold is DEMO's
                        if group not in ("chip", "opt"):                 # a pressed filter is selected: the Eye's edge
                            self.assertFalse(is_green(e["bg"], 0.05) or e["color"] == EYE or e["border"] == EYE, e)

    def test_the_hour_is_a_figure_on_an_opaque_ground(self):
        cards, signals = self.got["cards"]["els"], self.got["signals"]["els"]
        for hour in cards["opens"] + signals["hour"]:
            with self.subTest(hour=hour["text"]):
                self.assertEqual(hour["family"], "JetBrains Mono")
                self.assertIn("tabular-nums", hour["nums"])
                self.assertIn(hour["tracking"], ("normal", "0px"))
        self.assertEqual({h["color"] for h in cards["opens"]}, {rgb_of(PALETTE["--sv-ink-2"])})
        self.assertEqual({h["color"] for h in signals["hour"]}, {rgb_of(PALETTE["--sv-ink-3"])})
        for key, got in sorted(self.got.items()):
            with self.subTest(page=key):
                self.assertEqual(got["onVoid"], [])
                self.assertEqual(got["glass"], [])

    def test_the_hour_on_a_card_is_never_cut(self):
        got = self.got["cards"]
        self.assertEqual(got["cut"], [])
        self.assertEqual(got["fit"]["wide"]["lines"], 1)
        # Too narrow to sit beside the badge, it takes the line under it, whole.
        self.assertEqual(got["fit"]["narrow"], {"under": True, "lines": 1})

    def test_nothing_lights_it_in_any_ambience(self):
        for key, got in sorted(self.got.items()):
            with self.subTest(page=key):
                self.assertEqual(got["lit"], [])
                self.assertEqual(got["spins"], [])

    def test_every_word_of_it_keeps_4_5_to_1(self):
        for key, got in sorted(self.got.items()):
            with self.subTest(page=key):
                self.assertEqual(got["low"], [])

    def test_the_section_is_the_kit_s(self):
        """An opaque recessed ground, hairlines between its rows, its head a
        label, its count and its rule in the number face; ▶ TICKET in its
        signal's side, an outline; the ⚙ row and the headband's cell as the
        kit draws every other one."""
        els = self.got["section"]["els"]
        self.assertEqual(els["section"][0]["bg"], rgb_of(PALETTE["--sv-bg-0"]))
        for row in els["row"]:
            self.assertEqual(row["border"], rgb_of(PALETTE["--sv-line-1"]))
        self.assertEqual((els["head"][0]["family"], els["head"][0]["color"]),
                         ("Inter", rgb_of(PALETTE["--sv-ink-3"])))
        self.assertEqual(els["count"][0]["family"], "JetBrains Mono")
        for rule in els["rule"]:
            self.assertEqual((rule["family"], rule["color"]), ("JetBrains Mono", rgb_of(PALETTE["--sv-ink-3"])))
        for ticket in els["ticket"]:
            want = UP if ticket["side"] == "long" else DOWN
            with self.subTest(side=ticket["side"]):
                self.assertEqual((ticket["color"], ticket["border"], ticket["bg"], ticket["img"], ticket["shadow"]),
                                 (want, want, CLEAR, "none", "none"))

    #: What two controls drawn alike share: everything but their own words.
    SAME = ("size", "family", "weight", "tracking", "nums", "color", "bg", "img", "border", "borderWidth",
            "borderStyle", "shadow", "opacity")

    def assertDrawnLike(self, got, ref):
        self.assertTrue(got and ref, (got, ref))
        self.assertEqual({k: got[k] for k in self.SAME}, {k: ref[k] for k in self.SAME})

    def test_light_mode_keeps_main_s_colours(self):
        """Frozen (plan §15): in light mode the badge, its lines and the
        tags print in main's gold ink on main's line, the section sits on
        main's own ground and /signals/' badge is main's .badge-high. The
        sizes are the kit's in both themes: nothing under 11 px."""
        ink, line = "rgb(138, 106, 0)", "rgba(232, 163, 61, 0.45)"       # --accent-gold-ink in light mode; main's border
        cards, section, signals = (self.got[k]["light"] for k in ("cards", "section", "signals"))
        self.assertEqual([len(cards[k]) for k in ("line", "tag", "fact", "hbLine")], [2, 2, 2, 2])
        for said in cards["line"] + cards["tag"] + cards["fact"] + cards["hbLine"] + section["rowTag"]:
            with self.subTest(said=said["text"]):
                self.assertEqual(said["color"], ink)
                self.assertGreaterEqual(said["size"], 11)
        for tag in cards["tag"] + section["rowTag"]:
            self.assertEqual(tag["border"], line)
        self.assertEqual(section["section"][0]["bg"], "rgba(0, 0, 0, 0.18)")
        self.assertEqual({row["border"] for row in section["row"]}, {"rgba(19, 48, 32, 0.6)"})
        self.assertEqual(len(signals["badge"]), 2)
        for badge in signals["badge"]:
            self.assertEqual((badge["color"], badge["bg"], badge["shadow"]),
                             ("rgb(216, 176, 32)", "rgba(216, 176, 32, 0.15)", "none"))

    def test_the_shut_chip_is_a_filter_chip_like_the_others(self):
        """Pressed, it is selected like ALL (bg-3, ink-1, the Eye's edge);
        not pressed, it is LEFT's neutral outline; its count a figure."""
        cards, section = self.got["cards"], self.got["section"]
        pressed, rest = cards["els"]["chip"][0], section["els"]["chip"][0]
        self.assertDrawnLike(pressed, cards["refs"]["chipPressed"])
        self.assertDrawnLike(rest, section["refs"]["chipRest"])
        self.assertEqual((pressed["bg"], pressed["border"], pressed["color"]),
                         (rgb_of(PALETTE["--sv-bg-3"]), EYE, INK1))
        self.assertEqual((rest["bg"], rest["border"], rest["color"]),
                         (CLEAR, LINE3, rgb_of(PALETTE["--sv-ink-2"])))
        self.assertDrawnLike(section["els"]["chipCount"][0], section["refs"]["chipCount"])
        for key in ("cards", "section"):
            count = self.got[key]["els"]["chipCount"][0]
            self.assertEqual(count["family"], "JetBrains Mono")
            self.assertIn("tabular-nums", count["nums"])

    def test_the_panel_s_row_and_the_headband_s_cell_are_their_neighbours(self):
        """MARKET SHUT's row in the ⚙ panel is LEFT THE RAIL's row, and its
        cell in the headband list is NEW 24H's: the kit's, with nothing of
        their own."""
        got = self.got["section"]
        els, refs = got["els"], got["refs"]
        self.assertDrawnLike(els["rowKey"][0], refs["rowKey"])
        self.assertDrawnLike(els["cellKey"][0], refs["cellKey"])
        self.assertDrawnLike(els["cellValue"][0], refs["cellValue"])
        by_state = {o["pressed"]: o for o in els["opt"]}
        self.assertDrawnLike(by_state["true"], refs["optPressed"])
        self.assertDrawnLike(by_state["false"], refs["optRest"])
        self.assertEqual((els["cellValue"][0]["color"], els["cellValue"][0]["family"]), (INK1, "JetBrains Mono"))


def _rgba(css_colour):
    """(r, g, b, a) of a computed colour in either spelling: rgba(), or the
    color(srgb …) a color-mix() computes to."""
    p = parse(css_colour)
    if p:
        return (round(p[0]), round(p[1]), round(p[2]), round(p[3], 3))
    m = re.fullmatch(r"color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: / ([\d.]+))?\)", css_colour.strip())
    if not m:
        raise AssertionError("not a colour: %r" % css_colour)
    return tuple(round(float(x) * 255) for x in m.group(1, 2, 3)) + (round(float(m.group(4) or 1), 3),)


PHONE_PROBE = r"""(function () {
    function shown(e) {
        var r = e.getBoundingClientRect();
        if (!r.width || !r.height) return false;
        for (var a = e; a; a = a.parentElement) {
            var c = getComputedStyle(a);
            if (c.display === 'none' || c.visibility === 'hidden') return false;
        }
        return true;
    }
    function h(e) { return Math.round(e.getBoundingClientRect().height); }
    return JSON.stringify({
        buttons: Array.prototype.filter.call(document.querySelectorAll('.btn'), shown).map(function (e) {
            return { h: h(e), text: e.textContent.trim().slice(0, 24), cls: e.className };
        }),
        close: Array.prototype.filter.call(document.querySelectorAll('[data-sv-close-trade], #svCloseAll'), shown)
            .map(function (e) { return { h: h(e), text: e.textContent.trim().slice(0, 24) }; })
    });
})()"""


def _measure_phone(pages, probe, tmp_prefix, width=390, height=844):
    """_measure at a phone's viewport, with the viewport meta counting."""
    import shutil
    import tempfile
    from tests.test_close_advice import _Chrome
    from tests.test_ui_s0_fixes import _offline
    tmp = tempfile.mkdtemp(prefix=tmp_prefix)
    try:
        chrome = _Chrome(CHROME)
        try:
            sid = chrome.page(width, height, True)
            got = {}
            for i, (url, markup) in enumerate(sorted(pages.items())):
                path = pathlib.Path(tmp) / ("page%d.html" % i)
                path.write_text(_offline(markup), encoding="utf-8")
                chrome.open(sid, path.as_uri())
                got[url] = json.loads(chrome.eval(sid, probe))
            return got
        finally:
            chrome.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class PhoneTapFloorMeasuredTests(TestCase):
    """At 390 px every button keeps the phone tier's 44 px tap floor, and
    CLOSE and Close all their 48 px, where a miss costs most
    (sv-responsive.css). The kit's small button height (28 px), at a
    button's weight, had pulled every .btn-sm under it: the per-row CLOSE
    and every /ops/ switch (review, 2026-11-07)."""

    @classmethod
    def setUpTestData(cls):
        from tests.test_ops_cockpit import _component
        user = get_user_model().objects.create_user("s1a_phone", password="x", is_staff=True,
                                                    is_superuser=True)
        _quote("BTCUSD", 60600)
        _trade(user)
        _component("s1a_phone_on", is_enabled=True)
        _component("s1a_phone_off", is_enabled=False)
        client = Client()
        client.force_login(user)
        pages = {url: _get(client, url) for url in ("/positions/", "/ops/")}
        cls.got = _measure_phone(pages, PHONE_PROBE, "sv-s1a-phone-")

    def test_every_button_keeps_the_44px_tap_floor(self):
        for url, got in sorted(self.got.items()):
            self.assertTrue(got["buttons"], url)
            for b in got["buttons"]:
                with self.subTest(url=url, button=b["text"]):
                    self.assertGreaterEqual(b["h"], 44, b)

    def test_close_and_close_all_keep_48px(self):
        close = self.got["/positions/"]["close"]
        self.assertGreaterEqual(len(close), 2, close)
        for b in close:
            with self.subTest(button=b["text"]):
                self.assertGreaterEqual(b["h"], 48, b)


# ══════════════════════════════════════════════════════════════════════════
# Measured: the light and the money controls (the magic kept, 2026-11-12)
# ══════════════════════════════════════════════════════════════════════════

#: The controls that open or add to a position, and the side each wears.
SIDE_CONTROLS = (
    (".sr-popup:has(.sr-pop-dir-bullish) .sr-pop-btn-act", "up"),
    (".sr-popup:has(.sr-pop-dir-bearish) .sr-pop-btn-act", "down"),
    (".dh-pop .sr-pop-btn-act, .wl-pop .sr-pop-btn-act", "up"),
    (".dh-pop .sr-pop-btn-short, .wl-pop .sr-pop-btn-short", "down"),
    (".tk-long", "up"), (".tk-short", "down"),
    (".dk-page .btn.btn-buy:not([disabled])", "up"), (".dk-page .btn.btn-sell:not([disabled])", "down"),
    ('.sr-gone-row[data-side="long"] .sr-gone-btn-ticket', "up"),
    ('.sr-gone-row[data-side="short"] .sr-gone-btn-ticket', "down"),
    # MARKET SHUT's ▶ TICKET (2026-11-12): the same control in the section
    # beside it, so the same side and the same light.
    ('.sr-wait-row[data-side="long"] .sr-gone-btn-ticket', "up"),
    ('.sr-wait-row[data-side="short"] .sr-gone-btn-ticket', "down"),
)
#: The controls that take no light at all: the protective ones, TURN ON,
#: the dialog's confirm, PASS, and a BUY or a SELL that is disabled.
DARK_CONTROLS = ("[data-sv-close-trade]", "#svCloseAll", "button.btn-danger", "button.btn-primary",
                 ".sv-dialog-btn--go", ".sr-pop-btn-pass", ".btn.btn-stop",
                 "[data-probe-off]")
LIGHT_RGB = {"up": "36, 181, 130", "down": "255, 107, 110", "eye": "0, 232, 104"}

CONTROLS_PROBE = r"""(function (sides, dark) {
  function read(sel, side) {
    return Array.prototype.map.call(document.querySelectorAll(sel), function (el) {
      var c = getComputedStyle(el);
      return { sel: sel, side: side, text: (el.textContent || '').trim().slice(0, 24), shadow: c.boxShadow,
               textShadow: c.textShadow, filter: c.filter, bg: c.backgroundColor, img: c.backgroundImage,
               outline: c.outlineStyle + ' ' + c.outlineColor };
    });
  }
  var out = [];
  sides.forEach(function (s) { out = out.concat(read(s[0], s[1])); });
  dark.forEach(function (s) { out = out.concat(read(s, null)); });
  return out;
})"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class MoneyControlsLightMeasuredTests(TestCase):
    """Every §10 control with :hover and :focus-visible forced (the
    DevTools' own switch), per Ambience, on /command/, /positions/, /ops/,
    an instrument page and the kit, at 1440."""

    URLS = ("/command/", "/positions/", "/ops/", "/instruments/BTCUSD/", "/design/kit/")
    MODES = ("magic", "calm", "off")

    @classmethod
    def setUpTestData(cls):
        from tests.test_magic_layer import PROBES, _Browser, _book, _file_page, _pages
        client = _book("magic_money")
        pages = {u: _file_page(m) for u, m in _pages(client, cls.URLS).items()}
        everything = ", ".join([s for s, _side in SIDE_CONTROLS] + list(DARK_CONTROLS))
        probe = CONTROLS_PROBE + "(%s, %s)" % (json.dumps(SIDE_CONTROLS), json.dumps(DARK_CONTROLS))
        b = _Browser(pages, "sv-magic-money-")
        try:
            sid = b.tab()
            cls.rest, cls.forced, cls.ring = {}, {}, []
            for url in cls.URLS:
                b.open(sid, url, PROBES)
                # A disabled BUY and SELL, in both spellings, as pages print them.
                b.js(sid, "(function () { var d = document.createElement('div');"
                          " d.innerHTML = '<button type=\"button\" class=\"btn btn-buy\" disabled data-probe-off>Buy</button>'"
                          " + '<button type=\"button\" class=\"btn btn-sell disabled\" data-probe-off>Sell</button>';"
                          " (document.querySelector('.page-content') || document.body).appendChild(d); return 0; })()")
                for mode in cls.MODES:
                    b.js(sid, "__sv.mode('%s'); __sv.frame().then(function () { return 0; })" % mode)
                    cls.rest[(url, mode)] = b.js(sid, probe)
                b.force(sid, everything, ["hover", "focus-visible", "focus"])
                for mode in cls.MODES:
                    b.js(sid, "__sv.mode('%s'); __sv.frame().then(function () { return 0; })" % mode)
                    cls.forced[(url, mode)] = b.js(sid, probe)
            # The neighbours: one control at a time, forced, in a picture of
            # its box and the 24 px around it, under Magic and under Off.
            for url, selectors in (("/design/kit/", (".dk-page .btn.btn-buy:not([disabled])",
                                                     ".dk-page .btn.btn-sell:not([disabled])",
                                                     '.sr-gone-row[data-side="long"] .sr-gone-btn-ticket',
                                                     '.sr-gone-row[data-side="short"] .sr-gone-btn-ticket')),
                                   ("/instruments/BTCUSD/", (".tk-long", ".tk-short")),
                                   ("/command/", (".sr-popup:has(.sr-pop-dir-bullish) .sr-pop-btn-act",
                                                  ".sr-popup:has(.sr-pop-dir-bearish) .sr-pop-btn-act"))):
                b.open(sid, url, PROBES)
                b.js(sid, "__sv.settle()")      # the page has landed before a box is read
                for sel in selectors:
                    # A rail card is opened as a click opens it (a hover card
                    # is not displayed where the browser reports no hover),
                    # one at a time, and set where the page's script would
                    # set it: inside the viewport.
                    box = b.js(sid, "(function () { var e = document.querySelector(%s); if (!e) return null;"
                                    " Array.prototype.forEach.call(document.querySelectorAll('.sr-popup'), function (p) {"
                                    "   p.classList.remove('sv-pinned', 'show'); });"
                                    " var pop = e.closest('.sr-popup');"
                                    " if (pop) { pop.classList.add('sv-pinned', 'show'); pop.style.top = '90px'; pop.style.left = '420px';"
                                    "   pop.style.right = 'auto'; pop.style.bottom = 'auto'; pop.style.transform = 'none'; }"
                                    " else e.scrollIntoView({ block: 'center' });"
                                    " var r = e.getBoundingClientRect();"
                                    " return r.width && r.top >= 24 && r.bottom <= innerHeight - 24 ? [r.left, r.top, r.width, r.height] : null; })()"
                               % json.dumps(sel))
                    if not box:
                        continue
                    clip = (max(0, int(box[0]) - 24), max(0, int(box[1]) - 24), int(box[2]) + 49, int(box[3]) + 49)
                    node = b.nodes(sid, sel)[:1]
                    shots = {}
                    for state in ("rest", "forced"):
                        b.chrome.call("CSS.forcePseudoState", {"nodeId": node[0], "forcedPseudoClasses":
                                      ["hover", "focus-visible", "focus"] if state == "forced" else []}, session=sid)
                        for mode in ("magic", "off"):
                            # settled: the page's entrance and the hover's own
                            # transition are at their end in every picture
                            b.js(sid, "__sv.mode('%s'); __sv.frame().then(__sv.settle)" % mode)
                            shots[(state, mode)] = b.shot(sid, clip)
                    b.chrome.call("CSS.forcePseudoState", {"nodeId": node[0], "forcedPseudoClasses": []}, session=sid)
                    cls.ring.append((url, sel, (int(box[0]) - clip[0], int(box[1]) - clip[1],
                                               int(box[0] + box[2] + 0.999) - clip[0],
                                               int(box[1] + box[3] + 0.999) - clip[1]), shots))
        finally:
            b.close()

    def by_side(self, state, mode):
        got = {"up": [], "down": [], None: []}
        for (url, m), controls in state.items():
            if m == mode:
                for c in controls:
                    got[c["side"]].append(dict(c, url=url))
        return got

    def test_the_fixture_reaches_every_control(self):
        seen = {c["sel"] for controls in self.rest.values() for c in controls}
        for sel, _side in SIDE_CONTROLS:
            self.assertIn(sel, seen)
        for sel in DARK_CONTROLS:
            self.assertIn(sel, seen)

    def test_at_rest_every_money_button_has_no_shadow(self):
        for (url, mode), controls in sorted(self.rest.items()):
            for c in controls:
                with self.subTest(url=url, mode=mode, control=c["sel"], text=c["text"]):
                    self.assertEqual((c["shadow"], c["textShadow"], c["filter"]), ("none", "none", "none"))

    def test_the_eye_s_green_never_reaches_a_money_control(self):
        """Hover and focus forced, in every Ambience: no shadow, text-shadow
        or filter of a §10 control carries the Eye's green. (S1a's focus
        outline is the one Eye ring a focused control keeps.)"""
        for (url, mode), controls in sorted(self.forced.items()):
            self.assertGreater(len(controls), 3, (url, mode))
            for c in controls:
                with self.subTest(url=url, mode=mode, control=c["sel"], text=c["text"]):
                    for prop in ("shadow", "textShadow", "filter"):
                        self.assertNotIn(LIGHT_RGB["eye"], c[prop])
                        self.assertNotIn("120, 255, 180", c[prop])

    def test_a_side_lights_in_its_own_colour_inside_its_own_box(self):
        """Under Magic and Calm a BUY lights jade and a SELL coral, every
        layer inset; a bearish card's TAKE TRADE lights coral, never jade."""
        for mode in ("magic", "calm"):
            got = self.by_side(self.forced, mode)
            for side, other in (("up", "down"), ("down", "up")):
                self.assertGreater(len(got[side]), 3)
                for c in got[side]:
                    with self.subTest(mode=mode, url=c["url"], control=c["sel"]):
                        self.assertIn(LIGHT_RGB[side], c["shadow"])
                        self.assertNotIn(LIGHT_RGB[other], c["shadow"])
                        for layer in re.split(r",\s*(?=rgb)", c["shadow"]):
                            self.assertTrue(layer.endswith("inset"), layer)
                        self.assertEqual((c["textShadow"], c["filter"]), ("none", "none"))
        bearish = [c for c in self.by_side(self.forced, "magic")["down"] if "bearish" in c["sel"]]
        self.assertTrue(bearish)

    def test_off_keeps_s1a_s_hover_with_no_light(self):
        got = self.by_side(self.forced, "off")
        for side in ("up", "down"):
            for c in got[side]:
                with self.subTest(url=c["url"], control=c["sel"]):
                    self.assertEqual((c["shadow"], c["textShadow"], c["filter"]), ("none", "none", "none"))

    def test_the_protective_buttons_turn_on_the_confirm_and_a_disabled_side_take_no_light(self):
        for mode in self.MODES:
            got = self.by_side(self.forced, mode)[None]
            self.assertGreater(len(got), 8)
            for c in got:
                with self.subTest(mode=mode, url=c["url"], control=c["sel"], text=c["text"]):
                    for rgb in LIGHT_RGB.values():
                        self.assertNotIn(rgb, c["shadow"])
                    self.assertEqual((c["textShadow"], c["filter"]), ("none", "none"))

    def test_turn_on_is_no_green_slab_hovered_or_focused(self):
        seen = 0
        for mode in self.MODES:
            for c in self.forced[("/ops/", mode)]:
                if c["sel"] != "button.btn-primary":
                    continue
                seen += 1
                with self.subTest(mode=mode, button=c["text"]):
                    self.assertEqual(c["img"], "none")
                    self.assertFalse(is_green(c["bg"]), c)
                    self.assertTrue(is_neutral(c["bg"]), c)
        self.assertGreater(seen, 0)

    def test_a_lit_control_changes_nothing_beside_it(self):
        """With one control forced into hover and focus, the picture of the
        24 px around it is, under Magic, what it is under Off: the side's
        light adds nothing outside the control's own box (S1a's own hover
        wash and focus ring are in both pictures). The control's own focus
        ring, 2 px at 2 px, is the control's: what is compared is what lies
        beyond it, where every other element's box is."""
        self.assertGreaterEqual(len(self.ring), 6)
        for url, sel, box, shots in self.ring:
            a, b = shots[("rest", "magic")].load(), shots[("rest", "off")].load()
            c, d = shots[("forced", "magic")].load(), shots[("forced", "off")].load()
            w, h = shots[("rest", "magic")].size
            ring = same = spilt = inside = 0

            def differ(p, q):       # by more than 2 levels, this layer's standard for a pixel
                return max(abs(p[0] - q[0]), abs(p[1] - q[1]), abs(p[2] - q[2])) > 2

            for y in range(h):
                for x in range(w):
                    if box[0] <= x < box[2] and box[1] <= y < box[3]:
                        inside += differ(c[x, y], d[x, y])
                        continue
                    if box[0] - 4 <= x < box[2] + 4 and box[1] - 4 <= y < box[3] + 4:
                        continue            # its own focus ring
                    ring += 1
                    if differ(a[x, y], b[x, y]):
                        continue            # lit by something else at rest (the void's grain)
                    same += 1
                    spilt += differ(c[x, y], d[x, y])
            with self.subTest(url=url, control=sel):
                self.assertGreater(same, ring * 0.5)
                self.assertEqual(spilt, 0)
                self.assertGreater(inside, 0)       # the light is there, inside
