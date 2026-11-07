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
    the side's colours arrive with the dialog's markup in S2.1); a REAL or
    funding dialog carries the REAL red top edge.
  * THE SIGNAL CARD: TAKE TRADE / ADD in the signal's side (a bearish
    signal is a SELL), PASS a neutral ghost (it dismisses; it loses nothing).
  * THE QUOTE CARD: LONG jade, SHORT coral, outlines, no gradient slabs.
  * CLOSE, RETRY CLOSE, CLOSE ALL, turn off, all off, Cancel a withdrawal:
    neutral outlines (.btn-danger), never a red fill — turning off and
    closing are the safe directions, and a red fill is REAL's alone.
  * TURN ON: never a cheerful green slab (.btn-primary is the light primary).
  * PIN FIELDS: every PIN input keeps its type, its inputmode and its
    autocomplete; /brokers/' world boxes stay plain checkboxes; /setup/
    keeps "blank = no cap" in words; CLOSE ALL keeps "whole book".
  * EVERY PRICE AND P&L CELL: a flash is a background wash, never the
    text's colour; count-ups run on counts only.

Display only: nothing here posts, trades or calls a broker. The measured
class renders synthetic pages through the test client and computes the
colours in a headless Chromium with every network URL blocked (skipped,
not failed, where the machine has none).

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
from tests.test_design_tokens import block, decls, read, rules
from tests.test_ui_s0_fixes import _get, _measure

ROOT = pathlib.Path(settings.BASE_DIR)
KIT = "static/css/sv-kit.css"
SAURON = "static/css/sauron.css"
OVERLAY = "static/css/sv-overlay.css"


def kit_rule(selector):
    return block(read(KIT), selector)


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

    def test_a_real_or_funding_dialog_carries_the_real_edge(self):
        danger = kit_rule(".sv-dialog.sv-dialog--danger")
        self.assertEqual(danger["border-top"], "3px solid var(--sv-real)")

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
    var out = { rail: [] };
    Array.prototype.forEach.call(document.querySelectorAll('.sr-popup'), function (pop) {
        var dir = pop.querySelector('.sr-pop-dir');
        out.rail.push({ dir: dir ? dir.className : '', act: paint(pop.querySelector('.sr-pop-btn-act')),
                        pass: paint(pop.querySelector('.sr-pop-btn-pass')) });
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
