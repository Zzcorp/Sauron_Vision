"""The rail's pinned card keeps its money in view (the desk v2 polish, D3,
2026-11-15).

Scene 05 of the desk v2 deploy note (/instruments/AUDUSD/ at 1440 x 900,
the signal rail open, the rail's AUDUSD card pinned by a click) showed the
card docked in the rail with its TAKE TRADE and PASS below the rail's
visible part: no money button on screen after the pin. B10 docks a pinned
card in its card's place (static/css/sv-chart.css), but the card kept the
height the floating card is given, the screen between its bands (800 px at
900), so the sticky foot that holds TAKE TRADE and PASS in view while a
long card scrolls (static/css/sv-rail.css) stuck to the bottom of that
800 px box, under the rail's fold.

Measured here on the scene itself: the pictures' invented book, the held
instant, the page served with every script (tests/desk_scenes.py), the
card pinned the way the pictures pinned it. After the pin, TAKE TRADE and
PASS are on screen inside the rail and inside the card, nothing over them,
and the card's head with them; their words, their order, their place in
the keyboard's order and what they call are the card's own (plan §10).
A card lower in the rail, pinned, shows its money too.

Display only: nothing here posts, trades, or calls a broker or a model.
"""
import json
import unittest

from django.test import Client, TestCase

from tests import desk_scenes as S
from tests.old_design.measure import ACT_MS
from tests.test_close_advice import CHROME

#: Pin the rail's card naming `sym`, as scene 05 did: its words found in
#: the rail, scrolled into view if need be, clicked.
PIN = r"""(function (sym) {
  var rail = document.getElementById('signalsRail');
  if (!rail || !rail.classList.contains('open')) return 'no open rail';
  var re = new RegExp('(^|[^A-Z])' + sym + '([^A-Z]|$)');
  var cards = Array.prototype.filter.call(rail.querySelectorAll('.sr-signal'), function (e) {
    var r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && re.test((e.innerText || '').toUpperCase());
  });
  if (!cards.length) return 'no card naming ' + sym;
  cards[0].scrollIntoView({block: 'nearest'});
  cards[0].click();
  return 'pinned';
})(%s)"""

#: The rail and its pinned card, as the operator sees them once the pin
#: has settled: the rail's visible part (its scroll box), the card's, the
#: head's words, and each money button's box, words, keyboard place and
#: call, and what the screen shows at its centre.
READ = r"""(function () {
  function box(e) { var r = e.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom}; }
  var body = document.getElementById('railSignalsBody');
  var pop = body ? body.querySelector('.sr-popup.sv-pinned') : null;
  var bb = body.getBoundingClientRect();
  var out = {pinned: !!pop,
             view: {l: bb.left + body.clientLeft, t: bb.top + body.clientTop,
                    r: bb.left + body.clientLeft + body.clientWidth, b: bb.top + body.clientTop + body.clientHeight}};
  if (!pop) return JSON.stringify(out);
  out.sym = pop.querySelector('.sr-pop-sym').textContent.trim();
  var pb = pop.getBoundingClientRect();
  out.card = {l: pb.left + pop.clientLeft, t: pb.top + pop.clientTop,
              r: pb.left + pop.clientLeft + pop.clientWidth, b: pb.top + pop.clientTop + pop.clientHeight};
  var head = pop.querySelector('.sr-pop-head');
  out.head = box(head);
  out.headWords = head.innerText.replace(/\s+/g, ' ').trim();
  function at(b) { return document.elementFromPoint((b.l + b.r) / 2, (b.t + b.b) / 2); }
  var symEl = pop.querySelector('.sr-pop-sym');
  var sh = at(box(symEl));
  out.symSeen = !!(sh && (sh === symEl || symEl.contains(sh)));
  var btns = Array.prototype.slice.call(pop.querySelectorAll('.sr-pop-btn-act, .sr-pop-btn-pass'));
  var tabbable = Array.prototype.filter.call(document.querySelectorAll('button, a[href], input, select, textarea, [tabindex]'),
    function (e) { return e.tabIndex >= 0 && !e.disabled; });
  out.money = btns.map(function (b) {
    var r = box(b), hit = at(r);
    return {kind: b.classList.contains('sr-pop-btn-pass') ? 'pass' : 'act', words: b.textContent.replace(/\s+/g, ' ').trim(),
            box: r, hit: !!(hit && (hit === b || b.contains(hit))), seen: hit ? String(hit.className || hit.tagName) : null,
            tab: b.tabIndex, disabled: b.disabled, at: tabbable.indexOf(b), onclick: b.getAttribute('onclick')};
  });
  return JSON.stringify(out);
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class ThePinnedCardKeepsItsMoneyInViewTests(TestCase):
    """Scene 05: /instruments/AUDUSD/ at 1440 x 900, the rail open, its
    AUDUSD card pinned; then its last card, AAPL, pinned as well."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        S.hold_the_clock(cls)
        book = S.scene_book()
        cls.signal = book["ids"]["signal"]
        client = Client()
        client.force_login(book["user"])
        desk = S.SceneBrowser(client)
        cls.got = {}
        try:
            for sym in ("AUDUSD", "AAPL"):
                tid, sid = desk.open("/instruments/%s/" % S.SYMBOL, 1440, 900, rail="open", prefs=S.chart_pref())
                cls.chart = desk.chart(sid)
                cls.got[sym + ":act"] = desk.js(sid, PIN % json.dumps(sym))
                desk.settle(sid, ACT_MS)
                desk.chart(sid)
                cls.got[sym] = json.loads(desk.js(sid, READ))
                desk.close_tab(tid)
        finally:
            desk.close()

    def _in(self, inner, outer):
        return (inner["l"] >= outer["l"] - 0.5 and inner["r"] <= outer["r"] + 0.5
                and inner["t"] >= outer["t"] - 0.5 and inner["b"] <= outer["b"] + 0.5)

    def test_the_scene_was_reached(self):
        self.assertTrue(self.chart, "the chart drew")
        for sym in ("AUDUSD", "AAPL"):
            with self.subTest(card=sym):
                self.assertEqual(self.got[sym + ":act"], "pinned")
                self.assertTrue(self.got[sym]["pinned"], "the card pinned in the rail")
                self.assertEqual(self.got[sym]["sym"], sym)

    def test_take_trade_and_pass_are_on_screen_after_the_pin(self):
        """Inside the rail's visible part, inside the card's, and what the
        screen shows at their centre is the button itself."""
        for sym in ("AUDUSD", "AAPL"):
            got = self.got[sym]
            with self.subTest(card=sym):
                self.assertEqual([m["kind"] for m in got["money"]], ["act", "pass"])
                for m in got["money"]:
                    self.assertTrue(self._in(m["box"], got["view"]), (m["words"], m["box"], got["view"]))
                    self.assertTrue(self._in(m["box"], got["card"]), (m["words"], m["box"], got["card"]))
                    self.assertTrue(m["hit"], "%s is covered by %s" % (m["words"], m["seen"]))

    def test_the_card_s_head_stays_with_its_money(self):
        """What is pinned (the symbol, the side, the score) reads with the
        buttons that trade it."""
        for sym in ("AUDUSD", "AAPL"):
            got = self.got[sym]
            with self.subTest(card=sym):
                self.assertTrue(self._in(got["head"], got["view"]), (got["head"], got["view"]))
                self.assertTrue(got["symSeen"], got["headWords"])
        self.assertIn("▲ LONG", self.got["AUDUSD"]["headWords"])

    def test_the_money_keeps_its_words_its_order_and_its_calls(self):
        """Plan §10: TAKE TRADE then PASS in the page's order, so the
        keyboard's (the side's button first); PASS on the left of the row;
        the words and the calls the card has always had."""
        got = self.got["AUDUSD"]
        act, pas = got["money"]
        self.assertEqual((act["words"], pas["words"]), ("▶ TAKE TRADE", "✕ PASS"))
        self.assertLess(pas["box"]["r"], act["box"]["l"], "PASS on the left, the side's button on the right")
        self.assertTrue(act["at"] >= 0 and pas["at"] == act["at"] + 1, (act["at"], pas["at"]))
        self.assertEqual((act["tab"], pas["tab"]), (0, 0))
        self.assertFalse(act["disabled"] or pas["disabled"])
        self.assertEqual(act["onclick"], "event.preventDefault(); event.stopPropagation(); "
                                         "window.svTakeTrade && window.svTakeTrade(%d);" % self.signal)
        self.assertEqual(pas["onclick"], "event.preventDefault(); event.stopPropagation(); "
                                         "window.dismissSignal && window.dismissSignal(%d);" % self.signal)
