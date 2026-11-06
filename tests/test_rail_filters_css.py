"""The rail's filters, as the stylesheet applies them (2026-11-06, the review).

The filters run in the browser: the state sits as data-f-* attributes on the
hosts, the facts as data-* attributes on the rows, and static/css/sv-rail.css
(with the generated <style id="svRuleOff"> after it) decides what is hidden
and in which order the rest is drawn. The tests of the first build read the
stylesheet as text: a typo in one rule would have passed them all.

These tests render the page and the rail exactly as Django does, set each
filter state on the hosts, and evaluate the stylesheet on them — selectors
by soupsieve (bs4's own engine), the cascade by this module: !important,
then specificity, then source order; an inline declaration beats a normal
rule; an element under a hidden ancestor is hidden; `order` resolves the
row's own custom properties. What is visible, and in which order, is then
compared with what the operator chose.

DISPLAY ONLY: the filters hide and order what is drawn, nothing else.

Run with:  python manage.py test tests.test_rail_filters_css
"""
import re
from decimal import Decimal
from pathlib import Path

import soupsieve
from bs4 import BeautifulSoup
from django.conf import settings
from django.test import TestCase

from tests.test_rail_every_signal import (
    _inst, _page, _quote, _sig, _user)

CSS = (Path(settings.BASE_DIR) / "static" / "css" / "sv-rail.css")


# ── a small cascade, for the two properties the filters set ───────────────

def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _split_top(text, sep=","):
    out, depth, quote, cur = [], 0, None, ""
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def specificity(sel):
    """(ids, classes+attributes+pseudo-classes, types) — :is() and :not()
    count as their most specific argument."""
    a = b = c = 0
    i, n = 0, len(sel)
    while i < n:
        ch = sel[i]
        if ch == "#":
            a += 1
            i += 1
            while i < n and re.match(r"[\w-]", sel[i]):
                i += 1
        elif ch == ".":
            b += 1
            i += 1
            while i < n and re.match(r"[\w-]", sel[i]):
                i += 1
        elif ch == "[":
            b += 1
            depth, quote = 0, None
            while i < n:
                if quote:
                    if sel[i] == quote:
                        quote = None
                elif sel[i] in "\"'":
                    quote = sel[i]
                elif sel[i] == "[":
                    depth += 1
                elif sel[i] == "]":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
        elif sel.startswith("::", i):
            c += 1
            i += 2
            while i < n and re.match(r"[\w-]", sel[i]):
                i += 1
        elif ch == ":":
            m = re.match(r":([\w-]+)(\()?", sel[i:])
            name = m.group(1)
            i += len(m.group(0))
            if m.group(2):
                depth, start = 1, i
                while i < n and depth:
                    if sel[i] == "(":
                        depth += 1
                    elif sel[i] == ")":
                        depth -= 1
                    i += 1
                inner = sel[start:i - 1]
                if name in ("is", "not", "has"):
                    best = max((specificity(s) for s in _split_top(inner)),
                               default=(0, 0, 0))
                    a, b, c = a + best[0], b + best[1], c + best[2]
                elif name != "where":
                    b += 1
            else:
                b += 1
        elif re.match(r"[a-zA-Z]", ch):
            c += 1
            while i < n and re.match(r"[\w-]", sel[i]):
                i += 1
        else:
            i += 1
    return (a, b, c)


def parse_rules(css):
    """[(index, [(compiled selector, specificity)], [(prop, value, important)])]
    for the rules outside @-blocks (the media blocks are for touch and small
    screens, which these tests do not draw)."""
    css = _strip_comments(css)
    rules, pos, n = [], 0, len(css)
    while pos < n:
        brace = css.find("{", pos)
        if brace < 0:
            break
        head = css[pos:brace].strip()
        depth, j = 1, brace + 1
        while depth and j < n:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[brace + 1:j - 1]
        pos = j
        if head.startswith("@") or not head:
            continue
        decls = []
        for part in body.split(";"):
            if ":" not in part:
                continue
            prop, value = part.split(":", 1)
            value = value.strip()
            important = value.endswith("!important")
            if important:
                value = value[:-len("!important")].strip()
            decls.append((prop.strip(), value, important))
        if not any(p in ("display", "order") for p, _v, _i in decls):
            continue
        sels = [(soupsieve.compile(s), specificity(s))
                for s in _split_top(head)]
        rules.append((len(rules), sels, decls))
    return rules


def _inline(el):
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def computed(el, prop, rules):
    best = None
    for idx, sels, decls in rules:
        for p, value, important in decls:
            if p != prop:
                continue
            for compiled, spec in sels:
                if compiled.match(el):
                    key = (important, spec, idx)
                    if best is None or key > best[0]:
                        best = (key, value)
    inline = _inline(el)
    if prop in inline and (best is None or not best[0][0]):
        return inline[prop]
    return best[1] if best else None


def hidden(el, rules, stop=None):
    node = el
    while node is not None and getattr(node, "name", None):
        if computed(node, "display", rules) == "none":
            return True
        if node is stop:
            break
        node = node.parent
    return False


def order_of(el, rules):
    value = computed(el, "order", rules) or "0"
    m = re.match(r"var\((--[\w-]+)\s*(?:,\s*([^)]*))?\)", value)
    if m:
        value = _inline(el).get(m.group(1), m.group(2) or "0")
    try:
        return int(float(value))
    except ValueError:
        return 0


def drawn(lst, rules, stop):
    """The children of a list the stylesheet draws, in its visual order."""
    kids = [k for k in lst.find_all(recursive=False)]
    shown = [(order_of(k, rules), i, k) for i, k in enumerate(kids)
             if not hidden(k, rules, stop)]
    return [k for _o, _i, k in sorted(shown, key=lambda t: (t[0], t[1]))]


def label(el):
    if el.has_attr("data-sv-grp"):
        return "grp:" + el.get("data-asset-class", "")
    return el.get("data-signal-id") or el.get("data-symbol") or el.name


def _set_state(host, **attrs):
    for k in list(host.attrs):
        if k.startswith("data-f-"):
            del host[k]
    host["data-f-class"] = ""
    for k, v in attrs.items():
        host["data-f-" + k] = v


# ── the fixtures ──────────────────────────────────────────────────────────

class _Page(TestCase):
    @classmethod
    def setUpTestData(cls):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from signals.models import RuleControl
        cls.user = _user("rf_css")
        RuleControl.objects.create(rule_name="rf_css_b",
                                   promotion_stage="live_full",
                                   status="active")
        RuleControl.objects.create(rule_name="rf_css_c",
                                   promotion_stage="research",
                                   status="active")
        fx, cr, st, fx2 = (_inst("RFCSA", "forex"), _inst("RFCSB", "crypto"),
                           _inst("RFCSC", "stock"), _inst("RFCSD", "forex"))
        cls.a = _sig(fx, rule="rf_css_a", score=0.55, minutes_ago=4)
        cls.b = _sig(cr, rule="rf_css_b", score=0.91, direction="bearish",
                     entry="100", stop="105", target="90", minutes_ago=3)
        cls.c = _sig(st, rule="rf_css_c", score=0.72, entry="100", stop="95",
                     target="110", minutes_ago=2)
        cls.d = _sig(fx2, rule="", score=0.65, minutes_ago=1)
        gone_inst = _inst("RFCSE", "crypto")
        cls.e = _sig(gone_inst, rule="rf_css_e", score=0.6, entry="100",
                     stop="95", target="110", minutes_ago=5)
        _quote(gone_inst, "90")                       # through its stop
        cfg = AssetBotConfig.objects.create(
            user=cls.user, asset_class="forex", name="RF css", enabled=True,
            mode="paper", symbols=[], capital=Decimal("10000"))
        AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol="RFCSA", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("1.08"),
            stop_loss=Decimal("1.075"), take_profit=Decimal("1.09"),
            status="OPEN", paper=True, rule_name="rf_css_other")
        # The watchlist: listed by class, then symbol (Instrument.Meta).
        for sym, cls_ in (("RFCWA", "forex"), ("RFCWB", "crypto"),
                          ("RFCWC", "forex"), ("RFCWD", "stock")):
            inst = _inst(sym, cls_)
            inst.is_watchlist = True
            inst.save(update_fields=["is_watchlist"])
        for sym in ("RFCWB", "RFCWC"):                 # held
            AssetBotTrade.objects.create(
                config=cfg, asset_class="forex", symbol=sym, side="BUY",
                qty=Decimal("1"), entry_price=Decimal("1"),
                stop_loss=Decimal("0.9"), take_profit=Decimal("1.2"),
                status="OPEN", paper=True, rule_name="rf_css_other")

    def setUp(self):
        self.client.force_login(self.user)
        self.soup = BeautifulSoup(_page(self.client), "html.parser")
        rail = self.soup.find(id="signalsRail")
        rail["class"] = rail.get("class", []) + ["open"]
        self.base = CSS.read_text(encoding="utf-8")

    def rules(self, muted=()):
        from dashboard import rail_prefs
        css = rail_prefs.rule_off_css({"sig": {"rules_off": list(muted)}})
        return parse_rules(self.base + "\n" + css)


class TheSignalFiltersTests(_Page):
    def _visible(self, muted=(), **state):
        host = self.soup.find(id="railSignals")
        _set_state(host, **state)
        rules = self.rules(muted)
        cards = [label(k) for k in drawn(host.find(class_="sr-list"), rules,
                                          host) if not k.has_attr("data-sv-grp")]
        left = [r["data-signal-id"]
                for r in host.find_all(class_="sr-gone-row")
                if not hidden(r, rules, host)]
        return cards, left

    def test_every_filter_hides_what_it_names(self):
        a, b, c, d, e = (str(s.pk) for s in (self.a, self.b, self.c, self.d,
                                             self.e))
        cases = [
            ({}, (), {a, b, c, d}, set()),
            ({"gone": "1"}, (), {a, b, c, d}, {e}),
            ({"class": "forex"}, (), {a, d}, set()),
            ({"class": "forex stock"}, (), {a, c, d}, set()),
            ({"class": "crypto", "gone": "1"}, (), {b}, {e}),
            ({"side": "long"}, (), {a, c, d}, set()),
            ({"side": "short"}, (), {b}, set()),
            ({"score": "7"}, (), {b, c}, set()),
            ({"score": "9"}, (), {b}, set()),
            ({"stage": "votes"}, (), {a, b, d}, set()),
            ({"stage": "live"}, (), {b}, set()),
            ({"held": "held"}, (), {a}, set()),
            ({"held": "not"}, (), {b, c, d}, set()),
            ({"class": "crypto", "peek": "1"}, (), {a, b, c, d}, set()),
            ({}, ("rf_css_a",), {b, c, d}, set()),
            ({}, ("",), {a, b, c}, set()),
            ({"peek": "1"}, ("rf_css_a",), {a, b, c, d}, set()),
        ]
        for state, muted, cards, left in cases:
            with self.subTest(state=state, muted=muted):
                got_cards, got_left = self._visible(muted, **state)
                self.assertEqual(set(got_cards), cards)
                self.assertEqual(set(got_left), left)

    def test_every_sort_draws_its_order(self):
        a, b, c, d = (str(s.pk) for s in (self.a, self.b, self.c, self.d))
        host = self.soup.find(id="railSignals")
        lst = host.find(class_="sr-list")
        for state, want in [
            ({}, [d, c, b, a]),                                  # newest
            ({"sort": "score"}, [b, c, d, a]),
            ({"sort": "class"}, [c, d, a, b]),                   # stock, FX, crypto
            ({"group": "1"}, ["grp:stock", c, "grp:forex", d, a,
                              "grp:crypto", b]),
            ({"group": "1", "sort": "score"}, ["grp:stock", c, "grp:forex",
                                               d, a, "grp:crypto", b]),
        ]:
            with self.subTest(state=state):
                _set_state(host, **state)
                self.assertEqual([label(k) for k in drawn(lst, self.rules(),
                                                          host)], want)


class TheWatchFiltersTests(_Page):
    def _drawn(self, host_id, **state):
        host = self.soup.find(id=host_id)
        _set_state(host, **state)
        lst = host if host.has_attr("data-sv-list") else host.find(
            attrs={"data-sv-list": "watch"})
        return [label(k) for k in drawn(lst, self.rules(), host)
                if k.has_attr("data-sv-row") or k.has_attr("data-sv-grp")]

    def test_every_watch_sort_and_filter(self):
        for host_id in ("railWatchBody", "hbWatchDD"):
            for state, want in [
                ({"sort": "class"}, ["RFCWD", "RFCWA", "RFCWC", "RFCWB"]),
                ({"sort": "symbol"}, ["RFCWA", "RFCWB", "RFCWC", "RFCWD"]),
                ({"sort": "held"}, ["RFCWB", "RFCWC", "RFCWA", "RFCWD"]),
                ({"sort": "class", "held": "held"}, ["RFCWC", "RFCWB"]),
                ({"sort": "class", "held": "not"}, ["RFCWD", "RFCWA"]),
                ({"sort": "class", "class": "forex"}, ["RFCWA", "RFCWC"]),
                ({"sort": "class", "group": "1"},
                 ["grp:stock", "RFCWD", "grp:forex", "RFCWA", "RFCWC",
                  "grp:crypto", "RFCWB"]),
                # Grouped, the held-first sort holds inside each class.
                ({"sort": "held", "group": "1"},
                 ["grp:stock", "RFCWD", "grp:forex", "RFCWC", "RFCWA",
                  "grp:crypto", "RFCWB"]),
                ({"sort": "symbol", "group": "1"},
                 ["grp:stock", "RFCWD", "grp:forex", "RFCWA", "RFCWC",
                  "grp:crypto", "RFCWB"]),
            ]:
                with self.subTest(host=host_id, state=state):
                    self.assertEqual(self._drawn(host_id, **state), want)
