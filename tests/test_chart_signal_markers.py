"""The signal dots on the instrument chart (2026-09-27).

The operator: "the assets details pages graphs need a lifting too, for the
signals appearance, maybe add a dot with some hover details on it,
different colors depending on strenght... you feel me?"

The instrument page's chart used to draw each signal as a faint 0.6 circle
with the rule's raw name and a price written beside it. Now:

  C1 THE PAYLOAD. Each signal the chart receives (the page's json_script
     and every /api/chart-data/ refresh) carries what its card says: the
     rule in words, type, urgency, score, the time, the price at the
     signal, entry / stop / target as numbers and as text at the
     instrument's ONE decimal count, reward to risk, active, and its
     outcome in the platform's words — built from the rows already
     fetched, so no query per signal.
  C2 THE DOTS. One circle per signal on the bar that contains its time:
     green buy under the bar, red sell over it, a neutral tone on it; size
     and intensity in four steps of the score; a small arrow for the side;
     a key under the chart.
  C3 THE CARD. Hover (or a tap) shows a card beside the dot, inside the
     chart's box, every server string escaped; its percent floored, so
     one printed percent carries one strength word. It never takes the
     pointer (only its close button does): the dots under it stay
     clickable.
  C4 THE LEVELS. A click pins the card and draws the signal's entry, stop
     and target as dashed lines titled Entry / Stop / Target, until the
     card closes or another dot is clicked; a drawing tool keeps its
     click. Two signals on one bar: the library's marker id picks the dot
     under the mouse; without one, each click on the bar pins the next.
  C5 Nothing else moves: the positions' arrows and lines stay as they
     were. The legend reads a daily bar's 'YYYY-MM-DD' time as the date
     instead of throwing on it (the throw cost the dots their marker id).

The pure half (steps, colours, the hit test, the card, the placement) runs
under node exactly as the page ships it; the wiring runs under node too,
the widget's real script against a stub page and a fake chart.

Run with:  python manage.py test tests.test_chart_signal_markers
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

NODE = shutil.which("node")
SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.S)
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
EM = "—"


def widget(**ctx):
    base = {"chart_id": "t", "symbol": "EURUSD", "height": "420",
            "timeframe": "1d", "decimals": 5}
    base.update(ctx)
    return render_to_string("_partials/chart_widget.html", base)


def widget_source():
    return (Path(settings.BASE_DIR) / "templates" / "_partials"
            / "chart_widget.html").read_text(encoding="utf-8")


def _blocks(html):
    """(the pure block, the widget's own script) out of a rendered widget."""
    blocks = SCRIPT_RE.findall(html)
    pure = [b for b in blocks if "window.svSignalDots = {" in b]
    main = [b for b in blocks if "var CHART_ID" in b]
    assert len(pure) == 1 and len(main) == 1, (len(pure), len(main))
    return pure[0], main[0]


def _node(program, manifest=None):
    tmp = Path(tempfile.mkdtemp(prefix="sv-sigdots-"))
    try:
        (tmp / "run.js").write_text(program, encoding="utf-8")
        args = [NODE, str(tmp / "run.js")]
        if manifest is not None:
            (tmp / "m.json").write_text(json.dumps(manifest), encoding="utf-8")
            args.append(str(tmp / "m.json"))
        out = subprocess.run(args, capture_output=True, text=True,
                             encoding="utf-8", timeout=120)
        if out.returncode != 0:
            raise AssertionError("node failed: %s" % out.stderr[-2000:])
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _visible(markup):
    text = re.sub(r"<[^>]+>", " ", markup)
    return " ".join(text.split())


def _strip_vars(css):
    """Drop every var(...) — fallbacks included, nested parentheses too —
    so a hex left over is a colour that does not follow the theme."""
    out, i = [], 0
    while True:
        j = css.find("var(", i)
        if j < 0:
            out.append(css[i:])
            return "".join(out)
        out.append(css[i:j])
        depth, k = 0, j + 3
        while k < len(css):
            if css[k] == "(":
                depth += 1
            elif css[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append("var()")
        i = k + 1


# ═══ C1. The payload ══════════════════════════════════════════════════

def _instrument(symbol, asset_class, last=None):
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst = Instrument.objects.create(symbol=symbol, name=symbol,
                                     asset_class=asset_class, is_active=True)
    if last is not None:
        LiveQuote.objects.create(instrument=inst, last=Decimal(last),
                                 source="oanda")
    return inst


def _signal(inst, **kw):
    from signals.models import Signal
    base = dict(
        instrument=inst, signal_type="technical", direction="bullish",
        urgency="high", title="Golden cross on %s" % inst.symbol,
        description="d", rule_name="golden_cross", score=0.82,
        price_at_signal=Decimal("1.08412345"),
        suggested_entry=Decimal("1.0842"), suggested_stop=Decimal("1.0812"),
        suggested_target=Decimal("1.0902"), is_active=True)
    base.update(kw)
    return Signal.objects.create(**base)


class ThePayloadCarriesTheCardTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sigdot_u", password="x")
        self.client.force_login(self.user)
        self.inst = _instrument("EURUSD", "forex", last="1.08425")
        self.bull = _signal(self.inst)
        self.bear = _signal(
            self.inst, direction="bearish", rule_name="rsi_reversal_4h",
            urgency="low", score=0.95, is_active=False,
            outcome="stopped_out", realized_r=-1.0, risk_reward_ratio=1.5,
            suggested_entry=Decimal("1.09"), suggested_stop=Decimal("1.095"),
            suggested_target=Decimal("1.0825"))
        self.unpriced = _signal(self.inst, suggested_entry=None,
                                rule_name="rule_unpriced")

    def _page(self):
        resp = self.client.get("/instruments/EURUSD/")
        self.assertEqual(resp.status_code, 200)
        return resp

    def _mark(self, marks, sig):
        found = [m for m in marks if m["id"] == sig.pk]
        self.assertEqual(len(found), 1, marks)
        return found[0]

    def test_the_instrument_page_with_signals_answers_200(self):
        resp = self._page()
        self.assertContains(resp, 'id="instrument-main-chart-sig-legend"')
        self.assertContains(resp, 'id="instrument-main-chart-sig-card"')

    def test_a_live_signal_carries_every_field_of_its_card(self):
        m = self._mark(self._page().context["chart_signals"], self.bull)
        self.assertEqual(m["rule"], "Golden cross")
        self.assertEqual(m["type"], "Technical")
        self.assertEqual(m["urgency"], "High " + EM + " Act Today")
        self.assertEqual(m["score"], 0.82)
        self.assertRegex(m["at_text"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")
        self.assertEqual(m["price_at_text"], "1.08412")
        self.assertEqual(m["price_at"], 1.08412)
        self.assertEqual((m["entry"], m["stop"], m["target"]),
                         (1.0842, 1.0812, 1.0902))
        self.assertEqual((m["entry_text"], m["stop_text"], m["target_text"]),
                         ("1.08420", "1.08120", "1.09020"))
        # No stored ratio: derived from the three levels, 0.0060 / 0.0030.
        self.assertEqual(m["rr"], 2.0)
        self.assertEqual(m["rr_text"], "2.00 : 1")
        self.assertIs(m["active"], True)
        self.assertEqual((m["outcome"], m["outcome_text"]), ("", ""))
        self.assertIsNone(m["realized_r"])

    def test_the_five_fields_every_caller_reads_keep_their_shape(self):
        m = self._mark(self._page().context["chart_signals"], self.bull)
        self.assertEqual(m["label"], "golden_cross")
        self.assertEqual(m["price"], 1.0842)
        self.assertEqual(m["direction"], "bullish")
        self.assertIsInstance(m["at"], int)

    def test_a_graded_signal_says_how_it_ended_in_the_platforms_words(self):
        m = self._mark(self._page().context["chart_signals"], self.bear)
        self.assertEqual(m["rule"], "RSI reversal 4h")
        self.assertIs(m["active"], False)
        self.assertEqual(m["outcome"], "stopped_out")
        self.assertEqual(m["outcome_text"], "Stop loss hit · -1.00R")
        self.assertEqual(m["realized_r"], -1.0)
        self.assertEqual((m["rr"], m["rr_text"]), (1.5, "1.50 : 1"))

    def test_every_outcome_code_reads_as_the_position_page_reads_it(self):
        from dashboard.position_summary import ENDINGS
        from dashboard.views import _chart_signal_marks
        for code in ("hit_target", "stopped_out", "expired", "manual_close"):
            sig = _signal(self.inst, outcome=code, is_active=False)
            m = _chart_signal_marks([sig], 5)[0]
            self.assertEqual(m["outcome_text"], ENDINGS[code], code)

    def test_a_signal_without_a_price_is_still_left_off_the_tape(self):
        marks = self._page().context["chart_signals"]
        self.assertNotIn(self.unpriced.pk, [m["id"] for m in marks])

    def test_the_page_ships_the_same_list_it_hands_the_template(self):
        resp = self._page()
        block = re.search(
            r'<script id="instrument-main-chart-signals" '
            r'type="application/json">(.*?)</script>',
            resp.content.decode(), re.S)
        self.assertIsNotNone(block)
        self.assertEqual(json.loads(block.group(1)),
                         json.loads(json.dumps(resp.context["chart_signals"])))

    def test_the_card_and_the_axis_print_one_number_one_way(self):
        """The page's quote_decimals and the card's text come from one
        helper; forex is five."""
        resp = self._page()
        self.assertEqual(resp.context["quote_decimals"], 5)
        body = resp.content.decode()
        self.assertIn("parseInt('5'", body.split("var DECIMALS")[1][:200])

    def test_the_refresh_carries_the_same_card(self):
        res = self.client.get("/api/chart-data/", {
            "symbol": "EURUSD", "timeframe": "1d", "overlays": "1"})
        self.assertEqual(res.status_code, 200)
        page = self._page().context["chart_signals"]
        self.assertEqual(res.json()["signals"],
                         json.loads(json.dumps(page)))

    def test_one_query_whatever_the_number_of_signals(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from dashboard.views import _chart_signal_marks
        from signals.models import Signal

        def count():
            with CaptureQueriesContext(connection) as ctx:
                res = self.client.get("/api/chart-data/", {
                    "symbol": "EURUSD", "timeframe": "1d", "overlays": "1"})
            self.assertEqual(res.status_code, 200)
            return len(ctx.captured_queries), len(res.json()["signals"])

        count()                                   # warm any cache first
        before, n_before = count()
        for i in range(5):
            _signal(self.inst, rule_name="rule_%d" % i)
        after, n_after = count()
        self.assertEqual(n_after, n_before + 5)
        self.assertEqual(after, before, "a query per signal crept in")

        sigs = list(Signal.objects.filter(instrument=self.inst))
        with self.assertNumQueries(0):
            _chart_signal_marks(sigs, 5)

    def test_the_refresh_reads_the_live_quote_once(self):
        """_chart_decimals reads instrument.live_quote on the refresh too;
        _chart_positions has already read it on the same instance, and
        Django keeps a reverse one-to-one on the instance, found or not.
        So the decimals cost no second query, with a quote and without."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from market_data.models import LiveQuote

        table = LiveQuote._meta.db_table
        bare = _instrument("GBPUSD", "forex")
        _signal(bare)
        for symbol in ("EURUSD", "GBPUSD"):
            with CaptureQueriesContext(connection) as ctx:
                res = self.client.get("/api/chart-data/", {
                    "symbol": symbol, "timeframe": "1d", "overlays": "1"})
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.json()["signals"], symbol)
            reads = [q["sql"] for q in ctx.captured_queries
                     if 'FROM "%s"' % table in q["sql"]]
            self.assertLessEqual(len(reads), 1, (symbol, reads))


class ThePriceIsOneNumberTests(TestCase):
    """The number a click draws a line at and the text the card prints
    come from ONE rounding: the text is core.price_format's own
    (Decimal, half to even) and the number is parsed back from it."""

    def test_a_tie_in_the_last_decimal_is_one_value_on_the_line_and_the_card(self):
        from dashboard.views import _chart_signal_marks
        inst = _instrument("EURUSD", "forex", last="1.08425")
        sig = _signal(inst, suggested_entry=Decimal("1.087345"),
                      price_at_signal=Decimal("1.087345"),
                      suggested_stop=Decimal("1.084355"),
                      suggested_target=Decimal("1.093365"))
        sig.refresh_from_db()
        m = _chart_signal_marks([sig], 5)[0]
        for key in ("entry", "price_at", "stop", "target"):
            self.assertEqual(m[key], float(m[key + "_text"]), key)
            self.assertEqual("%.5f" % m[key], m[key + "_text"], key)
        self.assertEqual(m["entry_text"], "1.08734")
        self.assertEqual(m["entry"], 1.08734)


class TheInstrumentsDecimalsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sigdot_dec", password="x")
        self.client.force_login(self.user)

    def test_a_share_without_a_quote_prints_two(self):
        inst = _instrument("AAPL", "stock")
        sig = _signal(inst, price_at_signal=Decimal("100.5"),
                      suggested_entry=Decimal("101"),
                      suggested_stop=Decimal("99"),
                      suggested_target=Decimal("105.123"))
        resp = self.client.get("/instruments/AAPL/")
        self.assertEqual(resp.status_code, 200)
        m = [x for x in resp.context["chart_signals"] if x["id"] == sig.pk][0]
        self.assertEqual((m["entry_text"], m["stop_text"], m["target_text"],
                          m["price_at_text"]),
                         ("101.00", "99.00", "105.12", "100.50"))
        self.assertEqual(m["target"], 105.12)

    def test_a_jpy_cross_prints_three(self):
        inst = _instrument("USDJPY", "forex", last="150.25")
        sig = _signal(inst, price_at_signal=Decimal("150.2"),
                      suggested_entry=Decimal("150.25"),
                      suggested_stop=Decimal("149.9"),
                      suggested_target=Decimal("151"))
        resp = self.client.get("/instruments/USDJPY/")
        self.assertEqual(resp.status_code, 200)
        m = [x for x in resp.context["chart_signals"] if x["id"] == sig.pk][0]
        self.assertEqual((m["entry_text"], m["stop_text"], m["target_text"]),
                         ("150.250", "149.900", "151.000"))

    def test_a_missing_level_is_the_dash_not_zero(self):
        inst = _instrument("MSFT", "stock")
        sig = _signal(inst, suggested_stop=None, suggested_target=None,
                      suggested_entry=Decimal("300"))
        from dashboard.views import _chart_signal_marks
        m = _chart_signal_marks([sig], 2)[0]
        self.assertEqual((m["stop"], m["stop_text"]), (None, EM))
        self.assertEqual((m["target"], m["target_text"]), (None, EM))
        self.assertEqual((m["rr"], m["rr_text"]), (None, EM))


# ═══ C2 / C3. The markup the page renders ═════════════════════════════

class TheKeyAndTheCardAreOnThePageTests(SimpleTestCase):

    def test_the_key_is_rendered_under_the_chart_in_words_and_colours(self):
        html = widget()
        i = html.index('id="t-sig-legend"')
        block = html[i:html.index("</div>", i)]
        self.assertIn(
            "Signal strength: weak · medium · strong · very strong",
            _visible(block))
        self.assertIn("green buy", _visible(block))
        self.assertIn("red sell", _visible(block))
        for n in range(4):
            self.assertIn('class="sv-sig-sw sv-sig-s%d"' % n, block)
            self.assertIn('class="sv-sig-sw sv-sig-sw--bear sv-sig-s%d"' % n,
                          block)

    def test_the_key_waits_for_a_dot(self):
        """Hidden until the widget draws a dot: a chart with no signals
        carries no key for nothing."""
        html = widget()
        tag = re.search(r'<div class="sv-sig-legend"[^>]*>', html).group(0)
        self.assertIn(" hidden", tag)
        self.assertIn("sigLegendEl.hidden = !sigDots.length;", html)

    def test_the_key_sits_under_the_chart_and_the_card_inside_it(self):
        """The key outside the container (inside, it would take a row
        from the canvas layout() sizes); the card inside (its box is the
        chart's, and the expand portal takes it along)."""
        html = widget()
        box = html.index('class="sv-candle-container')
        card = html.index('id="t-sig-card"')
        loading = html.index('id="t-loading"')
        error = html.index('id="t-error"')
        key = html.index('id="t-sig-legend"')
        first_script = html.index("<script>")
        self.assertLess(box, card)
        self.assertLess(card, loading)
        self.assertLess(error, key)
        self.assertLess(key, first_script)

    def test_the_card_is_the_sites_card_in_both_themes(self):
        src = widget_source()
        rule = re.search(r"\n\.sv-sig-card \{([^}]*)\}", src).group(1)
        for token in ("var(--bg-card", "var(--border", "var(--radius-md",
                      "var(--shadow-card", "var(--text-primary",
                      "var(--font-mono"):
            self.assertIn(token, rule)
        # It can never outgrow the chart's box.
        self.assertIn("max-width: calc(100% - 12px);", rule)
        self.assertIn("max-height: calc(100% - var(--sv-toolbar-h, 36px) - 12px);",
                      rule)
        self.assertIn(".sv-sig-card--bull { --sv-sig-tone: var(--accent", src)
        self.assertIn(".sv-sig-card--bear { --sv-sig-tone: var(--accent-red",
                      src)

    def test_no_signal_rule_paints_a_colour_the_theme_cannot_move(self):
        css = widget_source().split("<style>")[1].split("</style>")[0]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        offenders = []
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if ".sv-sig" not in selector:
                continue
            for hit in HEX.findall(_strip_vars(body)):
                offenders.append((selector.strip()[:50], hit))
        self.assertEqual(offenders, [])

    def test_the_card_stills_for_reduced_motion(self):
        src = widget_source()
        self.assertRegex(
            src, r"@media \(prefers-reduced-motion: reduce\) \{\s*"
                 r"\.sv-sig-card \{ transition: none; transform: none; \}")

    def test_the_pure_half_carries_no_template_tags(self):
        """So the inline-JS parse guard reaches it and node runs it as
        the page ships it."""
        raw = widget_source()
        blocks = [b for b in SCRIPT_RE.findall(raw)
                  if "window.svSignalDots = {" in b]
        self.assertEqual(len(blocks), 1)
        for tag in ("{{", "{%", "{#"):
            self.assertNotIn(tag, blocks[0])


class TheWiringTests(SimpleTestCase):
    """Pins on the widget's own script: the parts a fake chart cannot
    prove were wired the way the page needs them."""

    def setUp(self):
        self.src = widget_source()

    def _fn(self, name):
        seg = self.src.split("function %s(" % name)[1]
        end = seg.find("\n    function ")
        return seg[:end] if end > 0 else seg

    def test_the_dots_have_their_own_subscriptions(self):
        self.assertIn("chart.subscribeCrosshairMove(onSignalHover);", self.src)
        self.assertIn("chart.subscribeClick(onSignalClick);", self.src)
        # FIRST: a throw ends the library's listener loop, and the legend's
        # handler threw on every daily bar until 2026-09-27.
        self.assertLess(
            self.src.index("chart.subscribeCrosshairMove(onSignalHover);"),
            self.src.index("chart.subscribeCrosshairMove(onCrosshair);"))
        self.assertIn(
            "chart.timeScale().subscribeVisibleLogicalRangeChange(onSignalRange);",
            self.src)
        # ...and the legend's and the drawing tools' are untouched.
        self.assertIn("chart.subscribeCrosshairMove(onCrosshair);", self.src)
        self.assertIn("chart.subscribeClick(onChartClick);", self.src)

    def test_the_legend_reads_a_daily_bars_date_string_as_the_date(self):
        """lightweight-charts 4 hands a daily bar's time back as its
        'YYYY-MM-DD' string; read as epoch seconds it threw on every move
        (and in a setData under a resting crosshair). The string branch
        comes before the epoch arithmetic."""
        body = self._fn("onCrosshair")
        self.assertIn("var d = (typeof param.time === 'string')\n"
                      "            ? param.time\n",
                      body.replace("\r\n", "\n"))
        self.assertLess(body.index("typeof param.time === 'string'"),
                        body.index("new Date(param.time * 1000)"))

    def test_a_drawing_tool_keeps_its_click(self):
        self.assertIn("if (activeTool !== 'crosshair') return;",
                      self._fn("onSignalClick"))

    def test_a_click_without_a_marker_id_steps_through_its_bar(self):
        body = self._fn("onSignalClick")
        self.assertIn("if (!hit.byObject) {", body)
        self.assertIn("sigApi().cycle(sigDots, hit.dot, sigPin ? sigPin.id : null)", body)
        self.assertIn("api.prefer(sigDots, hit, sigPin ? sigPin.id : null)",
                      self._fn("onSignalHover"))

    def test_the_cards_handlers_never_throw_into_the_librarys_loop(self):
        for name in ("onSignalHover", "onSignalClick"):
            self.assertIn("} catch (e) {", self._fn(name), name)

    def test_the_levels_are_dashed_and_titled_in_words(self):
        body = self._fn("drawSignalLevels")
        self.assertIn("LightweightCharts.LineStyle.Dashed", body)
        for title in ("'Entry'", "'Stop'", "'Target'"):
            self.assertIn(title, body)
        self.assertIn("clearSignalLevels();", body)

    def test_the_dots_are_redrawn_with_every_paint(self):
        body = self._fn("applyPositions")
        marks = body.index("mainSeries.setMarkers(markers)")
        self.assertIn("sigDots = signalDots(bars, c);", body)
        self.assertGreater(body.index("syncSignalFocus();"), marks)
        self.assertIn("function applyOverlays(bars) {", self.src)
        self.assertIn("applyPositions(bars);",
                      self.src.split("function applyOverlays(bars) {")[1][:200])

    def test_the_last_bar_holds_an_instant_only_while_it_forms(self):
        """A bar contains an instant from its open to its close: a day
        for a daily-family bar (a 'YYYY-MM-DD' string — every daily range
        draws daily candles), the frame's seconds for an intraday one."""
        body = self._fn("nearestBarTime")
        self.assertIn("if (epoch >= last + barSpan(bars)) return null;", body)
        self.assertLess(body.index("barSpan(bars)"),
                        body.index("if (epoch >= last) return"))
        span = self._fn("barSpan")
        self.assertIn("86400", span)
        self.assertIn("TF_SECONDS[currentTf]", span)

    def test_the_old_faint_circle_is_gone_and_the_positions_are_not(self):
        self.assertNotIn("color: bull ? c.accentWash : c.redDim,", self.src)
        self.assertIn("shape: isLong ? 'arrowUp' : 'arrowDown', color: tone,",
                      self.src)
        self.assertIn("lineStyle: LightweightCharts.LineStyle.Dashed,\n"
                      "                        axisLabelVisible: true, title: 'SL',",
                      self.src.replace("\r\n", "\n"))


# ═══ C2 / C3. The pure half, under node ═══════════════════════════════

MODULE_RUN = r"""
var api = window.svSignalDots;
var out = {};
var colors = { bull: 'G', bear: 'R', neutral: 'N' };
var alpha = function (c, a) { return c + '@' + a; };
var place = function (bars, at) {
    return (at === null || at === undefined) ? null : 't' + at;
};
var sigs = [
    { id: 1,  at: 1,    direction: 'bullish', score: 0.5 },
    { id: 2,  at: 2,    direction: 'bullish', score: 0.6 },
    { id: 3,  at: 3,    direction: 'bullish', score: 0.7499 },
    { id: 4,  at: 4,    direction: 'bearish', score: 0.75 },
    { id: 5,  at: 5,    direction: 'bearish', score: 0.8999 },
    { id: 6,  at: 6,    direction: 'bearish', score: 0.9 },
    { id: 7,  at: 7,    direction: 'neutral', score: 1.0 },
    { id: 8,  at: 8,    direction: 'bullish', score: null },
    { id: 9,  at: 9,    direction: 'bullish', score: 4.2 },
    { id: 10, at: null, direction: 'bullish', score: 0.9 },
    { id: 11, at: 11,   direction: 'bullish', score: -0.3 },
    { id: 12, at: 12,   direction: 'bullish', score: 0.599 }
];
out.dots = api.build(sigs, [], { colors: colors, alpha: alpha, place: place })
    .map(function (d) {
        return { id: d.id, time: d.time, step: d.step.key, marker: d.marker };
    });

var ts = {
    spacing: 6,
    timeToCoordinate: function (t) {
        return ({ tA: 100, tB: 160, tOff: null })[t];
    },
    options: function () { return { barSpacing: this.spacing }; }
};
/* b and c share one bar; off has none on screen. */
var dots = [
    { id: 'a',   time: 'tA',   sig: { score: 0.7 },  marker: { id: 'sv-sig-a' } },
    { id: 'b',   time: 'tB',   sig: { score: 0.65 }, marker: { id: 'sv-sig-b' } },
    { id: 'c',   time: 'tB',   sig: { score: 0.95 }, marker: { id: 'sv-sig-c' } },
    { id: 'off', time: 'tOff', sig: { score: 1 },    marker: { id: 'sv-sig-off' } }
];
function h(x, obj) {
    var r = api.hitTest(dots, x, ts, obj);
    return r ? { id: r.dot.id, x: r.x, others: r.others, byObject: r.byObject } : null;
}
/* Two on one bar (b 0.65, c 0.95): each click without a marker id pins
   the next of them, strongest first, and round again. */
var cById = function (id) { return dots.filter(function (d) { return d.id === id; })[0]; };
var raw = api.hitTest(dots, 161, ts);
out.cycle = {
    fresh: api.cycle(dots, raw.dot, null).id,
    fromC: api.cycle(dots, raw.dot, 'c').id,
    fromB: api.cycle(dots, raw.dot, 'b').id,
    otherBar: api.cycle(dots, raw.dot, 'a').id,
    alone: api.cycle(dots, cById('a'), 'a').id
};
/* The pointer on the pinned signal's bar, no marker id: the pinned one. */
var pb = api.prefer(dots, raw, 'b');
var named = api.hitTest(dots, 165, ts, 'sv-sig-c');
out.prefer = {
    pinnedB: { id: pb.dot.id, x: pb.x, others: pb.others },
    pinnedElsewhere: api.prefer(dots, raw, 'a').dot.id,
    nothingPinned: api.prefer(dots, raw, null).dot.id,
    named: api.prefer(dots, named, 'b').dot.id,
    miss: api.prefer(dots, null, 'b')
};
/* The printed percent and the strength word, for scores on and beside
   each threshold: one number, one word. */
out.pct = [0.599, 0.6, 0.7499, 0.75, 0.8999, 0.9, 0.29, 0.57, 0.82, 1, 0]
    .map(function (s) {
        var html = api.card({ direction: 'bullish', score: s }, {});
        return [s, api.percent(s), html.match(/sv-sig-pct">([^<]*)</)[1],
                html.match(/sv-sig-strength">([^<]*)</)[1], api.step(s).key];
    });
out.hits = {
    on: h(100), near: h(109), edge: h(110), past: h(111), sameBar: h(161),
    between: h(130), object: h(165, 'sv-sig-b'),
    objectOffscreen: h(500, 'sv-sig-off'), objectStale: h(400, 'sv-sig-a'),
    objectStaleNear: h(158, 'sv-sig-a'), objectNoX: h(NaN, 'sv-sig-b'),
    nan: h(NaN),
    empty: api.hitTest([], 100, ts)
};
ts.spacing = 40;
out.hits.wide = h(121);
out.hits.wideMiss = h(123);

var evil = {
    id: 5, direction: 'bearish', score: 0.83,
    rule: '<img src=x onerror=alert(1)>', type: 'Tech"nical',
    urgency: 'High <b>now</b>', at_text: '<script>x</script>',
    price_at_text: '1&2', rr_text: '2.00 : 1', entry_text: '<i>1</i>',
    stop_text: '"s"', target_text: "'t'", active: true,
    entry: 1, stop: 0.9, target: 1.2
};
out.cardPinned = api.card(evil, { pinned: true, others: 2 });
out.cardHover = api.card(evil, {});
out.classes = [api.cardClass(evil, true), api.cardClass({ direction: 'bullish' }, false),
               api.cardClass({}, false)];
out.won = api.card({ direction: 'bullish', score: 0.91, rule: 'Golden cross',
                     active: false, outcome: 'hit_target',
                     outcome_text: 'Target reached · +2.00R', realized_r: 2 }, {});
out.lost = api.card({ direction: 'bearish', score: 0.61, rule: 'RSI reversal',
                      active: false, outcome: 'stopped_out',
                      outcome_text: 'Stop loss hit · -1.00R', realized_r: -1 }, {});
out.lapsed = api.card({ direction: 'neutral', score: 0.3, active: false }, {});
out.noScore = api.card({ direction: 'bullish', score: null, active: true,
                         urgency: 'High' }, { others: 1 });

var box = { width: 400, height: 300, top: 40 };
var size = { w: 200, h: 120 };
out.places = [[10, 50], [390, 50], [200, 150], [0, 0], [399, 299],
              [-50, 1000], [200, -80]].map(function (p) {
    return api.place(box, { x: p[0], y: p[1] }, size);
});
out.placeFull = api.place(box, { x: 100, y: 100 }, { w: 388, h: 248 });
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is not installed")
class ThePureHalfUnderNodeTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pure, _main = _blocks(widget())
        cls.out = _node("var window = {};\n" + pure + "\n" + MODULE_RUN)

    def test_colour_and_size_climb_the_four_steps(self):
        by_id = {d["id"]: d for d in self.out["dots"]}
        expect = {
            1: ("weak", "G@0.4", 0.6),
            2: ("medium", "G@0.65", 0.9),
            3: ("medium", "G@0.65", 0.9),
            4: ("strong", "R@0.85", 1.25),
            5: ("strong", "R@0.85", 1.25),
            6: ("very_strong", "R@1", 1.7),
            7: ("very_strong", "N@1", 1.7),
            8: ("weak", "G@0.4", 0.6),        # no score is the weakest step
            9: ("very_strong", "G@1", 1.7),   # clamped, never bigger
            11: ("weak", "G@0.4", 0.6),
            12: ("weak", "G@0.4", 0.6),       # 0.599 is 59%, still weak
        }
        for sid, (key, colour, size) in expect.items():
            d = by_id[sid]
            self.assertEqual(d["step"], key, sid)
            self.assertEqual(d["marker"]["color"], colour, sid)
            self.assertEqual(d["marker"]["size"], size, sid)
            self.assertEqual(d["marker"]["shape"], "circle", sid)
            self.assertEqual(d["marker"]["id"], "sv-sig-%d" % sid)
            self.assertEqual(d["marker"]["time"], "t%d" % sid)

    def test_the_side_is_the_colour_the_place_and_the_arrow(self):
        by_id = {d["id"]: d["marker"] for d in self.out["dots"]}
        self.assertEqual((by_id[1]["position"], by_id[1]["text"]),
                         ("belowBar", "▲"))
        self.assertEqual((by_id[4]["position"], by_id[4]["text"]),
                         ("aboveBar", "▼"))
        self.assertEqual((by_id[7]["position"], by_id[7]["text"]),
                         ("inBar", ""))

    def test_a_signal_with_no_bar_is_not_drawn(self):
        self.assertNotIn(10, [d["id"] for d in self.out["dots"]])
        self.assertEqual(len(self.out["dots"]), 11)

    def test_one_printed_percent_carries_one_word(self):
        """Floored, and the step read from the same whole percent: 0.599
        prints 59% beside "weak", 0.60 prints 60% beside "medium"."""
        expect = {
            0.599: (59, "59%", "weak"), 0.6: (60, "60%", "medium"),
            0.7499: (74, "74%", "medium"), 0.75: (75, "75%", "strong"),
            0.8999: (89, "89%", "strong"), 0.9: (90, "90%", "very strong"),
            0.29: (29, "29%", "weak"), 0.57: (57, "57%", "weak"),
            0.82: (82, "82%", "strong"), 1: (100, "100%", "very strong"),
            0: (0, "0%", "weak"),
        }
        steps = {"weak": "weak", "medium": "medium", "strong": "strong",
                 "very strong": "very_strong"}
        self.assertEqual(len(self.out["pct"]), len(expect))
        for score, pct, printed, word, key in self.out["pct"]:
            self.assertEqual((pct, printed, word), expect[score], score)
            self.assertEqual(key, steps[word], score)
        # The same percent never carries two words.
        seen = {}
        for _s, pct, _p, word, _k in self.out["pct"]:
            self.assertEqual(seen.setdefault(pct, word), word, pct)

    def test_the_hit_test_answers_on_and_next_to_the_bar(self):
        hits = self.out["hits"]
        self.assertEqual(hits["on"], {"id": "a", "x": 100, "others": 0,
                                      "byObject": False})
        self.assertEqual(hits["near"]["id"], "a")
        self.assertEqual(hits["edge"]["id"], "a")      # a fingertip: 10px
        self.assertIsNone(hits["past"])
        self.assertIsNone(hits["between"])
        self.assertIsNone(hits["nan"])
        self.assertIsNone(hits["empty"])

    def test_on_one_bar_the_strongest_answers_and_counts_the_rest(self):
        self.assertEqual(self.out["hits"]["sameBar"],
                         {"id": "c", "x": 160, "others": 1, "byObject": False})

    def test_the_librarys_own_hit_wins_but_never_off_screen(self):
        # On the shared bar the library's marker beats the strongest (c).
        self.assertEqual(self.out["hits"]["object"]["id"], "b")
        self.assertIs(self.out["hits"]["object"]["byObject"], True)
        self.assertIsNone(self.out["hits"]["objectOffscreen"])
        self.assertEqual(self.out["hits"]["objectNoX"]["id"], "b")

    def test_a_stale_marker_name_far_from_the_pointer_is_not_believed(self):
        """The library names the marker of the PREVIOUS move: a pointer
        that jumped off dot a to x 400 still carries 'sv-sig-a' once. Far
        from a (300px), the bar test answers: nothing there."""
        self.assertIsNone(self.out["hits"]["objectStale"])
        near = self.out["hits"]["objectStaleNear"]
        self.assertEqual((near["id"], near["byObject"]), ("c", False))

    def test_every_signal_of_a_shared_bar_is_reachable_without_a_marker_id(self):
        """A phone's tap rarely lands on a 0.9 dot, and the library names
        no marker then: each click on the bar pins the next signal of it,
        strongest first, and round again."""
        self.assertEqual(self.out["cycle"], {
            "fresh": "c", "fromC": "b", "fromB": "c", "otherBar": "c",
            "alone": "a"})

    def test_the_hover_shows_the_pinned_signal_of_its_bar(self):
        prefer = self.out["prefer"]
        self.assertEqual(prefer["pinnedB"], {"id": "b", "x": 160, "others": 1})
        self.assertEqual(prefer["pinnedElsewhere"], "c")
        self.assertEqual(prefer["nothingPinned"], "c")
        # A marker the library named under the mouse stays what it is.
        self.assertEqual(prefer["named"], "c")
        self.assertIsNone(prefer["miss"])

    def test_a_wide_bar_widens_the_reach(self):
        self.assertEqual(self.out["hits"]["wide"]["id"], "a")   # 21 <= 22
        self.assertIsNone(self.out["hits"]["wideMiss"])         # 23 > 22

    def test_the_card_escapes_every_server_string(self):
        card = self.out["cardPinned"]
        self.assertNotIn("<img", card)
        self.assertNotIn("<script", card)
        self.assertNotIn("<i>1", card)
        self.assertNotIn("<b>now", card)
        for escaped in ("&lt;img src=x onerror=alert(1)&gt;",
                        "&lt;script&gt;x&lt;/script&gt;", "1&amp;2",
                        "&lt;i&gt;1&lt;/i&gt;", "&quot;s&quot;",
                        "&#39;t&#39;", "High &lt;b&gt;now&lt;/b&gt;",
                        "Tech&quot;nical signal"):
            self.assertIn(escaped, card)

    def test_the_card_says_side_score_strength_and_state(self):
        card = self.out["cardPinned"]
        self.assertIn('<span class="sv-sig-side">SELL</span>', card)
        self.assertIn('class="sv-sig-score sv-sig-s2"', card)
        self.assertIn('style="width:83%"', card)
        self.assertIn('<b class="sv-sig-pct">83%</b>', card)
        self.assertIn('<span class="sv-sig-strength">strong</span>', card)
        for label in ("Signalled", "Price then", "Reward to risk",
                      "Entry", "Stop", "Target"):
            self.assertIn(label, card)
        self.assertIn("sv-sig-chip--live", card)
        self.assertIn("+2 more signals on this bar", card)

    def test_only_a_pinned_card_can_be_closed_and_says_its_levels_are_drawn(self):
        self.assertIn("data-sv-sig-close", self.out["cardPinned"])
        self.assertIn("Entry, stop and target drawn on the chart",
                      self.out["cardPinned"])
        self.assertNotIn("data-sv-sig-close", self.out["cardHover"])
        self.assertIn("Click or tap the dot to draw its levels",
                      self.out["cardHover"])

    def test_the_card_wears_its_side(self):
        self.assertEqual(self.out["classes"], [
            "sv-sig-card sv-sig-card--bear is-pinned",
            "sv-sig-card sv-sig-card--bull",
            "sv-sig-card sv-sig-card--neutral"])

    def test_a_graded_signal_shows_its_outcome(self):
        self.assertIn("sv-sig-chip--win", self.out["won"])
        self.assertIn("Target reached · +2.00R", self.out["won"])
        self.assertIn(">BUY<", self.out["won"])
        self.assertIn("very strong", self.out["won"])
        self.assertIn("sv-sig-chip--loss", self.out["lost"])
        self.assertIn("Stop loss hit · -1.00R", self.out["lost"])
        self.assertNotIn("sv-sig-chip--live", self.out["lost"])

    def test_an_unknown_is_a_dash_never_blank_or_zero(self):
        lapsed = self.out["lapsed"]
        self.assertIn("No longer active", lapsed)
        self.assertIn(">NEUTRAL<", lapsed)
        self.assertIn('<span class="sv-sig-rule">' + EM + "</span>", lapsed)
        self.assertIn("<dd>" + EM + "</dd>", lapsed)
        no_score = self.out["noScore"]
        self.assertIn('style="width:0%"', no_score)
        self.assertIn('<b class="sv-sig-pct">' + EM + "</b>", no_score)
        self.assertIn('<span class="sv-sig-strength">weak</span>', no_score)
        self.assertIn("+1 more signal on this bar", no_score)
        self.assertNotIn("draw its levels", no_score)   # nothing to draw

    def test_the_card_never_leaves_the_box(self):
        box_w, box_h, top, w, h = 400, 300, 40, 200, 120
        for pos in self.out["places"]:
            self.assertGreaterEqual(pos["left"], 0, pos)
            self.assertLessEqual(pos["left"] + w, box_w, pos)
            self.assertGreaterEqual(pos["top"], top, pos)
            self.assertLessEqual(pos["top"] + h, box_h, pos)
        right_of, flipped = self.out["places"][0], self.out["places"][1]
        self.assertEqual(right_of, {"left": 24, "top": 46})
        self.assertEqual(flipped["left"], 390 - 14 - 200)
        # A card as big as the box allows still fits exactly.
        self.assertEqual(self.out["placeFull"], {"left": 6, "top": 46})


# ═══ C2-C5. The widget's own script, against a fake chart ═════════════

WIDGET_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const M = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

function ClassList() { this.s = new Set(); }
ClassList.prototype.add = function () { for (const c of arguments) this.s.add(c); };
ClassList.prototype.remove = function () { for (const c of arguments) this.s.delete(c); };
ClassList.prototype.toggle = function (c, on) {
    if (on === undefined) on = !this.s.has(c);
    if (on) this.s.add(c); else this.s.delete(c);
    return on;
};
ClassList.prototype.contains = function (c) { return this.s.has(c); };

function El(id) {
    this.id = id; this.style = { setProperty() {}, removeProperty() {} };
    this.dataset = {}; this.classList = new ClassList(); this.hidden = false;
    this.innerHTML = ''; this.textContent = ''; this.className = ''; this.l = {};
    this.offsetWidth = 800; this.offsetHeight = 420;
    this.clientWidth = 800; this.clientHeight = 420;
    this.offsetTop = 0; this.offsetLeft = 0; this.parentNode = null;
}
El.prototype.addEventListener = function (t, fn) { (this.l[t] = this.l[t] || []).push(fn); };
El.prototype.removeEventListener = function () {};
El.prototype.querySelector = function () { return null; };
El.prototype.querySelectorAll = function () { return []; };
El.prototype.appendChild = function (c) { return c; };
El.prototype.insertBefore = function (c) { return c; };
El.prototype.removeChild = function (c) { return c; };
El.prototype.remove = function () {};
El.prototype.setAttribute = function () {};
El.prototype.getAttribute = function () { return null; };
El.prototype.focus = function () {};
El.prototype.blur = function () {};
El.prototype.contains = function () { return false; };
El.prototype.getBoundingClientRect = function () {
    return { top: 0, left: 0, right: this.offsetWidth, bottom: this.offsetHeight,
             width: this.offsetWidth, height: this.offsetHeight };
};

const ID = 't';
const els = {};
['-container', '', '-panes', '-measure', '-legend', '-countdown', '-loading',
 '-error', '-sig-card', '-sig-legend'].forEach(function (s) { els[ID + s] = new El(ID + s); });
els[ID].offsetTop = 36;
const card = els[ID + '-sig-card'], legend = els[ID + '-sig-legend'];
card.offsetWidth = 252; card.offsetHeight = 190; card.hidden = true; legend.hidden = true;
const toolButtons = ['crosshair', 'hline', 'trendline', 'measure', 'clear'].map(function (t) {
    const b = new El(''); b.dataset.tool = t; return b;
});
const typeButtons = ['candlestick', 'heikin', 'line', 'area'].map(function (t) {
    const b = new El(''); b.dataset.type = t; return b;
});
els[ID + '-container'].querySelectorAll = function (sel) {
    return sel === '.sv-chart-btn' ? toolButtons
         : sel === '.sv-type-btn' ? typeButtons : [];
};

const TOKENS = { '--accent': '#00e868', '--accent-red': '#e83030',
                 '--text-secondary': '#7aaa8a', '--text-muted': '#3a6850',
                 '--accent-gold-ink': '#d8b020', '--border': '#133020',
                 '--bg-void': '#030806' };
function getComputedStyle() {
    return { getPropertyValue: function (n) { return TOKENS[n] || ''; },
             display: 'block', visibility: 'visible', opacity: '1' };
}
const document = {
    body: new El('body'), head: new El('head'), documentElement: new El('html'),
    fullscreenElement: null, activeElement: null,
    getElementById: function (id) { return els[id] || null; },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    createElement: function () { return new El(''); },
    addEventListener: function () {}, removeEventListener: function () {},
    dispatchEvent: function () {}
};

const log = { markers: [], setData: 0, fetches: 0 };
let BARS = [];
function Series(kind) { this.kind = kind; this.lines = []; this.markers = []; this.rows = []; }
Series.prototype.setData = function (d) {
    this.rows = d; this.markers = [];            /* setData wipes markers */
    if (this.kind === 'candle') log.setData++;
};
Series.prototype.setMarkers = function (m) {       /* only the main series has any */
    this.markers = m.slice();
    log.markers.push(JSON.parse(JSON.stringify(m)));
};
Series.prototype.createPriceLine = function (o) { const pl = { o: o }; this.lines.push(pl); return pl; };
Series.prototype.removePriceLine = function (pl) {
    const i = this.lines.indexOf(pl);
    if (i < 0) throw new Error('not a line of this series');
    this.lines.splice(i, 1);
};
Series.prototype.applyOptions = function () {};
Series.prototype.data = function () { return this.rows; };
Series.prototype.update = function () {};
Series.prototype.coordinateToPrice = function () { return 1.1; };
Series.prototype.priceToCoordinate = function () { return 100; };

const handlers = { move: [], click: [], range: [] };
const ts = {
    timeToCoordinate: function (t) {
        const i = BARS.findIndex(function (b) { return b.time === t; });
        return i < 0 ? null : 20 + i * 10;
    },
    options: function () { return { barSpacing: 10 }; },
    subscribeVisibleLogicalRangeChange: function (fn) { handlers.range.push(fn); },
    getVisibleLogicalRange: function () { return { from: 0, to: BARS.length }; },
    setVisibleLogicalRange: function () { handlers.range.forEach(function (f) { f({}); }); },
    fitContent: function () { handlers.range.forEach(function (f) { f({}); }); }
};
const chart = {
    series: [],
    add: function (kind) { const s = new Series(kind); this.series.push(s); return s; },
    addCandlestickSeries: function () { return this.add('candle'); },
    addHistogramSeries: function () { return this.add('hist'); },
    addLineSeries: function () { return this.add('line'); },
    addAreaSeries: function () { return this.add('area'); },
    removeSeries: function (s) { const i = this.series.indexOf(s); if (i >= 0) this.series.splice(i, 1); },
    priceScale: function () { return { applyOptions: function () {}, width: function () { return 60; } }; },
    timeScale: function () { return ts; },
    subscribeCrosshairMove: function (fn) { handlers.move.push(fn); },
    subscribeClick: function (fn) { handlers.click.push(fn); },
    applyOptions: function () {}, setCrosshairPosition: function () {}, remove: function () {}
};
const LightweightCharts = {
    createChart: function () { return chart; },
    CrosshairMode: { Normal: 0 },
    LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3, SparseDotted: 4 },
    PriceScaleMode: { Normal: 0, Logarithmic: 1 }
};
let PAYLOAD = M.payload;
function fetchStub() {
    log.fetches++;
    const body = JSON.parse(JSON.stringify(PAYLOAD));
    BARS = body.bars;
    return Promise.resolve({ status: 200, json: function () { return Promise.resolve(body); } });
}
const sandbox = {
    document: document, LightweightCharts: LightweightCharts, fetch: fetchStub,
    getComputedStyle: getComputedStyle, console: console,
    setTimeout: function () { return 0; }, clearTimeout: function () {},
    setInterval: function () { return 0; }, clearInterval: function () {},
    innerWidth: 1200, innerHeight: 800,
    addEventListener: function () {}, removeEventListener: function () {}
};
sandbox.window = sandbox;
vm.createContext(sandbox);

const flush = function () { return new Promise(function (r) { setImmediate(r); }); };
const SIG_TITLES = ['Entry', 'Stop', 'Target'];
/* The main series: the candles, or whatever a type switch put in their
   place (the volume histogram is the only other series on this chart). */
const candle = function () { return chart.series.find(function (s) { return s.kind !== 'hist'; }); };
const sigLines = function () {
    return candle().lines.filter(function (l) { return SIG_TITLES.indexOf(l.o.title) >= 0; })
        .map(function (l) { return { title: l.o.title, price: l.o.price, style: l.o.lineStyle }; });
};
const otherLines = function () {
    return candle().lines.filter(function (l) { return SIG_TITLES.indexOf(l.o.title) < 0; })
        .map(function (l) { return l.o.title; });
};
const lastMarkers = function () { return log.markers[log.markers.length - 1] || []; };
const cardState = function () {
    return { hidden: card.hidden, cls: card.className, html: card.innerHTML,
             left: card.style.left, top: card.style.top };
};
const param = function (x, y, time, objectId) {
    return { point: (x === null ? undefined : { x: x, y: y }), time: time,
             seriesData: new Map(), hoveredObjectId: objectId };
};
/* As lightweight-charts 4.1 does on a mouse move: the crosshair listeners
   run in order, carrying the marker the library found under the pointer
   on the PREVIOUS move, and only once they have all returned does the
   library record the marker under the pointer now. A throw ends the loop
   (and reaches the page as an uncaught error) before that record: one
   throwing listener, and no listener ever learns which marker it is on.
   The bar is in seriesData, so the legend formats its date. */
let hovered;
const move = function (x, y, time, objectId) {
    const p = param(x, y, time, hovered);
    if (p.point && time !== undefined) {
        p.seriesData.set(candle(), { time: time, open: 1.08, high: 1.09, low: 1.07, close: 1.085 });
    }
    try { handlers.move.forEach(function (f) { f(p); }); }
    catch (e) { log.moveErrors = (log.moveErrors || 0) + 1; return; }
    hovered = objectId;
};
const click = function (x, y, time, objectId) {
    handlers.click.forEach(function (f) { f(param(x, y, time, objectId)); });
};
const legendEl = els[ID + '-legend'];
const chartType = function (name) {
    typeButtons.find(function (b) { return b.dataset.type === name; })
        .l.click.forEach(function (f) { f({}); });
};
const tool = function (name) {
    toolButtons.find(function (b) { return b.dataset.tool === name; })
        .l.click.forEach(function (f) { f({}); });
};
const refresh = async function (payload) {
    PAYLOAD = payload;
    sandbox.svCharts[ID].refresh();
    for (let i = 0; i < 6; i++) await flush();
};

(async function () {
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const R = {};
    R.first = { setData: log.setData, markers: lastMarkers(), legendHidden: legend.hidden,
                card: cardState(), others: otherLines() };
    move(113, 150, M.barS1);
    R.hover = cardState();
    R.legend = legendEl.innerHTML;
    move(400, 150, M.barFar);
    R.away = cardState();
    click(111, 200, M.barS1);
    R.pinned = { card: cardState(), lines: sigLines(), others: otherLines() };
    move(null, null, undefined);
    R.pinnedAfterLeave = cardState();
    await refresh(M.payload);
    R.refreshed = { setData: log.setData, fetches: log.fetches, markers: lastMarkers(),
                    lines: sigLines(), card: cardState() };
    click(262, 120, M.barS2);
    R.other = { card: cardState(), lines: sigLines() };
    click(600, 120, M.barFar);
    R.cleared = { card: cardState(), lines: sigLines(), others: otherLines() };
    /* On the card: pointerdown (which says what pointed) then click; a
       target whose closest() finds the close button, or not. */
    const onCard = function (pointerType, onClose) {
        (card.l.pointerdown || []).forEach(function (f) { f({ pointerType: pointerType }); });
        card.l.click.forEach(function (f) {
            f({ target: { closest: function () { return onClose ? {} : null; } },
                preventDefault: function () {}, stopPropagation: function () {} });
        });
    };
    click(111, 200, M.barS1);
    onCard('mouse', true);
    R.closed = { card: cardState(), lines: sigLines() };
    click(111, 200, M.barS1);
    /* The card's body never takes the pointer (its CSS); should a click
       reach its listener anyway, only the close button closes it. */
    onCard('mouse', false);
    R.bodyMouse = { card: cardState(), lines: sigLines() };
    onCard('touch', false);
    R.bodyTouch = { card: cardState(), lines: sigLines() };
    /* ...because the tap goes through to the chart: where no dot is, it
       is the tap elsewhere and closes the card. */
    click(600, 120, M.barFar);
    R.tapThrough = { card: cardState(), lines: sigLines() };

    /* Two signals on ONE daily bar (11 BUY 0.82, 14 SELL 0.62), and no
       marker id from the library (a phone's tap, a click beside the
       dots): each click on the bar pins the next of them. */
    click(111, 200, M.barS1);
    R.cycle1 = { card: cardState(), lines: sigLines() };
    click(111, 200, M.barS1);
    R.cycle2 = { card: cardState(), lines: sigLines() };
    move(113, 150, M.barS1);           /* hover on that bar: the pinned one, not the strongest */
    R.cycleHover = cardState();
    click(111, 200, M.barS1);
    R.cycle3 = { card: cardState(), lines: sigLines() };
    click(600, 120, M.barFar);
    move(400, 150, M.barFar);

    /* The mouse on the SELL dot of that shared DAILY bar: the library
       names the marker on the next move, because no listener throws on
       the bar's date string any more. */
    move(113, 185, M.barS1, 'sv-sig-14');
    move(113, 186, M.barS1, 'sv-sig-14');
    R.named = { card: cardState(), moveErrors: log.moveErrors || 0,
                legend: legendEl.innerHTML };
    click(113, 186, M.barS1, 'sv-sig-14');
    R.namedPin = { card: cardState(), lines: sigLines() };
    click(113, 186, M.barS1, 'sv-sig-14');   /* named again: that one again, no stepping */
    R.namedAgain = { lines: sigLines() };
    click(113, 140, M.barS1, 'sv-sig-11');   /* the BUY dot of the same bar, named */
    R.namedOther = { card: cardState(), lines: sigLines() };
    click(600, 120, M.barFar);
    move(400, 150, M.barFar);
    tool('hline');
    click(111, 200, M.barS1);
    R.drawing = { card: cardState(), lines: sigLines(), others: otherLines() };
    tool('crosshair');
    click(111, 200, M.barS1);
    R.repinned = { lines: sigLines() };
    chartType('line');                 /* the candles go, and their price lines with them */
    for (let i = 0; i < 6; i++) await flush();
    R.swapped = { kind: candle().kind, lines: sigLines(), card: cardState(),
                  series: chart.series.map(function (s) { return s.kind; }) };
    /* A signal fired after the last loaded bar CLOSED, one fired inside
       that bar while it forms, and a position opened after the close. */
    const edge = JSON.parse(JSON.stringify(M.payload));
    edge.signals = M.edge.signals; edge.positions = M.edge.positions;
    await refresh(edge);
    R.edge = { markers: lastMarkers(), legendHidden: legend.hidden };
    const none = JSON.parse(JSON.stringify(M.payload));
    none.signals = [];
    await refresh(none);
    R.gone = { markers: lastMarkers(), legendHidden: legend.hidden, card: cardState(),
               lines: sigLines() };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""


def _epoch(y, m, d, hh=0, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=dt_timezone.utc).timestamp())


def _payload():
    start = date(2026, 8, 1)
    bars = []
    for i in range(40):
        c = 1.08 + 0.001 * (i % 7)
        bars.append({"time": (start + timedelta(days=i)).isoformat(),
                     "open": c - 0.0005, "high": c + 0.002,
                     "low": c - 0.002, "close": c, "volume": 0})
    s1 = {"id": 11, "price": 1.0842, "at": _epoch(2026, 8, 10, 15, 30),
          "direction": "bullish", "label": "golden_cross",
          "rule": "Golden cross", "type": "Technical",
          "urgency": "High " + EM + " Act Today", "score": 0.82,
          "at_text": "2026-08-10 15:30 UTC",
          "price_at": 1.08412, "price_at_text": "1.08412",
          "entry": 1.0842, "entry_text": "1.08420",
          "stop": 1.0812, "stop_text": "1.08120",
          "target": 1.0902, "target_text": "1.09020",
          "rr": 2.0, "rr_text": "2.00 : 1", "active": True,
          "outcome": "", "outcome_text": "", "realized_r": None}
    s2 = dict(s1, id=12, at=_epoch(2026, 8, 25, 9, 0), direction="bearish",
              label="rsi_reversal", rule="RSI <b>reversal</b>", score=0.95,
              entry=1.09, entry_text="1.09000", stop=1.095,
              stop_text="1.09500", target=1.08, target_text="1.08000",
              active=False, outcome="stopped_out",
              outcome_text="Stop loss hit · -1.00R", realized_r=-1.0)
    early = dict(s1, id=13, at=_epoch(2026, 7, 1))   # before the loaded range
    # On s1's own daily bar, weaker and the other side.
    shared = dict(s1, id=14, at=_epoch(2026, 8, 10, 18, 0),
                  direction="bearish", label="rsi_reversal_4h",
                  rule="RSI reversal 4h", score=0.62,
                  entry=1.0855, entry_text="1.08550", stop=1.0885,
                  stop_text="1.08850", target=1.0795, target_text="1.07950")
    position = {"id": "bot-1", "source": "bot", "side": "long",
                "entry": 1.08, "stop": 1.075, "tp": 1.09, "qty": 1000.0,
                "opened_at": _epoch(2026, 8, 5, 12), "label": "LONG x",
                "via": "x", "paper": True, "protected": False,
                "pnl": None, "pnl_pct": None, "mark": None}
    return {"symbol": "EURUSD", "timeframe": "1d", "bars": bars,
            "positions": [position], "signals": [s1, s2, early, shared]}


def _edge():
    """The last loaded bar is 2026-09-09, which closes at 2026-09-10
    00:00 UTC: a signal fired after that close, one fired inside the bar
    while it forms, and a position opened after the close."""
    base = _payload()
    s1, position = base["signals"][0], base["positions"][0]
    late = dict(s1, id=15, at=_epoch(2026, 9, 10, 14, 0))
    forming = dict(s1, id=16, at=_epoch(2026, 9, 9, 15, 30))
    late_pos = dict(position, id="bot-2", opened_at=_epoch(2026, 9, 10, 12),
                    label="LONG late")
    return {"signals": [s1, late, forming], "positions": [position, late_pos]}


@unittest.skipUnless(NODE, "node is not installed")
class TheWidgetAgainstAFakeChartTests(SimpleTestCase):
    """The widget's real script, a stub page and a fake lightweight-charts
    whose setData wipes markers the way the library does."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pure, main = _blocks(widget())
        cls.r = _node(WIDGET_HARNESS, {
            "pure": pure, "main": main, "payload": _payload(),
            "barS1": "2026-08-10", "barS2": "2026-08-25",
            "barFar": "2026-09-08", "edge": _edge()})

    def _sig_markers(self, markers):
        return {m["id"]: m for m in markers
                if str(m.get("id", "")).startswith("sv-sig-")}

    def test_each_signal_is_a_dot_on_the_bar_that_contains_it(self):
        first = self.r["first"]
        dots = self._sig_markers(first["markers"])
        self.assertEqual(sorted(dots), ["sv-sig-11", "sv-sig-12", "sv-sig-14"])
        s1, s2 = dots["sv-sig-11"], dots["sv-sig-12"]
        shared = dots["sv-sig-14"]
        self.assertEqual((shared["time"], shared["position"], shared["size"],
                          shared["color"], shared["text"]),
                         ("2026-08-10", "aboveBar", 0.9,
                          "rgba(232,48,48,0.65)", "▼"))
        self.assertEqual((s1["time"], s1["position"], s1["shape"], s1["size"],
                          s1["color"], s1["text"]),
                         ("2026-08-10", "belowBar", "circle", 1.25,
                          "rgba(0,232,104,0.85)", "▲"))
        self.assertEqual((s2["time"], s2["position"], s2["size"],
                          s2["color"], s2["text"]),
                         ("2026-08-25", "aboveBar", 1.7,
                          "rgba(232,48,48,1)", "▼"))
        self.assertFalse(first["legendHidden"])
        self.assertTrue(first["card"]["hidden"])

    def test_the_positions_arrow_and_lines_are_untouched(self):
        first = self.r["first"]
        arrows = [m for m in first["markers"] if "id" not in m]
        self.assertEqual(len(arrows), 1)
        self.assertEqual((arrows[0]["shape"], arrows[0]["text"]),
                         ("arrowUp", "LONG @ 1.08000"))
        self.assertEqual(first["others"], ["LONG 1000", "SL", "TP"])
        self.assertEqual(self.r["cleared"]["others"], ["LONG 1000", "SL", "TP"])

    def test_a_signal_after_the_last_bars_close_is_not_drawn_on_that_bar(self):
        """On the daily default the newest bar is the previous session's
        until the EOD fetch at 22:30 UTC, and a signal fired today sat on
        yesterday's candle — one session before it fired, under a card
        that printed today. Past the last bar's CLOSE there is nowhere
        honest to put it, exactly as before the first bar; inside the
        last bar it is the forming candle, and stays (2026-09-28)."""
        edge = self.r["edge"]
        dots = self._sig_markers(edge["markers"])
        self.assertNotIn("sv-sig-15", dots, "drawn on a bar that closed "
                                            "before it fired")
        self.assertIn("sv-sig-16", dots)
        self.assertEqual(dots["sv-sig-16"]["time"], "2026-09-09")
        self.assertEqual(dots["sv-sig-11"]["time"], "2026-08-10")
        self.assertFalse(edge["legendHidden"])

    def test_the_positions_arrow_follows_the_same_rule(self):
        """One placement for the arrows and the dots: a position opened
        after the last bar's close has no arrow, and keeps its lines."""
        arrows = [m for m in self.r["edge"]["markers"] if "id" not in m]
        self.assertEqual([a["time"] for a in arrows], ["2026-08-05"])

    def test_hover_shows_the_card_beside_the_dot(self):
        """On a DAILY bar, whose string date the legend's handler cannot
        format: the harness runs the listeners the way the library does."""
        hover = self.r["hover"]
        self.assertFalse(hover["hidden"])
        self.assertEqual(hover["cls"], "sv-sig-card sv-sig-card--bull")
        for text in ("Golden cross", ">BUY<", "82%", "1.08420", "1.08120",
                     "1.09020", "2.00 : 1", "2026-08-10 15:30 UTC",
                     "Active", "+1 more signal on this bar"):
            self.assertIn(text, hover["html"])
        # x 110 + 14px gap; the pointer's 150 + the 36px toolbar - half 190.
        self.assertEqual((hover["left"], hover["top"]), ("124px", "91px"))
        self.assertTrue(self.r["away"]["hidden"])

    def test_a_click_pins_the_card_and_draws_dashed_levels(self):
        pinned = self.r["pinned"]
        self.assertIn("is-pinned", pinned["card"]["cls"])
        self.assertIn("data-sv-sig-close", pinned["card"]["html"])
        self.assertEqual(pinned["lines"], [
            {"title": "Entry", "price": 1.0842, "style": 2},
            {"title": "Stop", "price": 1.0812, "style": 2},
            {"title": "Target", "price": 1.0902, "style": 2}])
        # The pointer leaves: the pinned card stays, at its own dot.
        after = self.r["pinnedAfterLeave"]
        self.assertFalse(after["hidden"])
        self.assertEqual((after["left"], after["top"]), ("124px", "141px"))

    def test_the_dots_and_the_levels_survive_every_set_data(self):
        ref = self.r["refreshed"]
        self.assertEqual(ref["fetches"], 2)
        self.assertEqual(ref["setData"], self.r["first"]["setData"] + 1)
        self.assertEqual(sorted(self._sig_markers(ref["markers"])),
                         ["sv-sig-11", "sv-sig-12", "sv-sig-14"])
        # Redrawn once, not stacked on the first copy.
        self.assertEqual([l["title"] for l in ref["lines"]],
                         ["Entry", "Stop", "Target"])
        self.assertFalse(ref["card"]["hidden"])
        self.assertIn("is-pinned", ref["card"]["cls"])

    def test_another_dot_moves_the_levels_and_the_card(self):
        other = self.r["other"]
        self.assertEqual([(l["title"], l["price"]) for l in other["lines"]],
                         [("Entry", 1.09), ("Stop", 1.095), ("Target", 1.08)])
        self.assertIn("sv-sig-card--bear", other["card"]["cls"])
        self.assertIn(">SELL<", other["card"]["html"])
        self.assertIn("Stop loss hit", other["card"]["html"])
        self.assertIn("RSI &lt;b&gt;reversal&lt;/b&gt;", other["card"]["html"])
        self.assertNotIn("<b>reversal", other["card"]["html"])

    def test_a_click_elsewhere_or_the_close_button_takes_it_all_away(self):
        for step in ("cleared", "closed"):
            self.assertTrue(self.r[step]["card"]["hidden"], step)
            self.assertEqual(self.r[step]["lines"], [], step)

    def test_the_card_lets_clicks_through_and_only_its_button_closes_it(self):
        """The pinned card sits beside the newest bars, where recent
        signals cluster. Its body never takes the pointer, so the dots
        under it stay clickable and, on a phone, a tap on it is the tap
        elsewhere that closes it."""
        for step in ("bodyMouse", "bodyTouch"):
            self.assertFalse(self.r[step]["card"]["hidden"], step)
            self.assertEqual(len(self.r[step]["lines"]), 3, step)
        self.assertTrue(self.r["tapThrough"]["card"]["hidden"])
        self.assertEqual(self.r["tapThrough"]["lines"], [])
        src = widget_source()
        pinned = re.search(r"\n\.sv-sig-card\.is-pinned \{([^}]*)\}", src).group(1)
        self.assertNotIn("pointer-events", pinned)
        self.assertIn("\n.sv-sig-card.is-pinned .sv-sig-close { pointer-events: auto; }",
                      src.replace("\r\n", "\n"))
        card = re.search(r"\n\.sv-sig-card \{([^}]*)\}", src).group(1)
        self.assertIn("pointer-events: none;", card)
        self.assertNotIn("pointerdown", src.split("function syncSignalFocus(")[1]
                         .split("function applyOverlays(")[0])

    def test_each_click_on_a_shared_bar_pins_the_next_signal(self):
        """No marker id (a phone's tap): BUY 0.82 first, then SELL 0.62,
        then round again; the hover on that bar shows the pinned one."""
        buy = [("Entry", 1.0842), ("Stop", 1.0812), ("Target", 1.0902)]
        sell = [("Entry", 1.0855), ("Stop", 1.0885), ("Target", 1.0795)]
        levels = lambda k: [(l["title"], l["price"]) for l in self.r[k]["lines"]]
        self.assertEqual(levels("cycle1"), buy)
        self.assertIn(">BUY<", self.r["cycle1"]["card"]["html"])
        self.assertIn("+1 more signal on this bar: click or tap the bar again "
                      "for the next", self.r["cycle1"]["card"]["html"])
        self.assertEqual(levels("cycle2"), sell)
        self.assertIn("sv-sig-card--bear is-pinned", self.r["cycle2"]["card"]["cls"])
        self.assertIn("RSI reversal 4h", self.r["cycle2"]["card"]["html"])
        hover = self.r["cycleHover"]
        self.assertFalse(hover["hidden"])
        self.assertIn("sv-sig-card--bear is-pinned", hover["cls"])
        self.assertIn("RSI reversal 4h", hover["html"])
        self.assertEqual(levels("cycle3"), buy)

    def test_on_a_daily_bar_the_library_names_the_dot_under_the_mouse(self):
        """The legend's handler used to throw on a daily bar's date
        string, and the throw ended the library's crosshair update before
        it recorded the marker under the pointer: the SELL dot sharing a
        bar with a stronger BUY could never be opened, and a click on it
        drew the BUY's levels. Now nothing throws, the legend reads the
        date, and the named dot is the one opened and pinned."""
        named = self.r["named"]
        self.assertEqual(named["moveErrors"], 0)
        self.assertIn("2026-08-10", named["legend"])
        self.assertIn("2026-08-10", self.r["legend"])
        self.assertFalse(named["card"]["hidden"])
        self.assertIn(">SELL<", named["card"]["html"])
        self.assertIn("RSI reversal 4h", named["card"]["html"])
        sell = [("Entry", 1.0855), ("Stop", 1.0885), ("Target", 1.0795)]
        levels = lambda k: [(l["title"], l["price"]) for l in self.r[k]["lines"]]
        self.assertEqual(levels("namedPin"), sell)
        self.assertIn("sv-sig-card--bear is-pinned", self.r["namedPin"]["card"]["cls"])
        # Named again: that dot again, never the next one of the bar.
        self.assertEqual(levels("namedAgain"), sell)
        self.assertEqual(levels("namedOther"),
                         [("Entry", 1.0842), ("Stop", 1.0812), ("Target", 1.0902)])
        self.assertIn(">BUY<", self.r["namedOther"]["card"]["html"])

    def test_a_drawing_tool_keeps_its_click(self):
        drawing = self.r["drawing"]
        self.assertEqual(drawing["lines"], [])
        self.assertTrue(drawing["card"]["hidden"])
        self.assertIn("H", drawing["others"])
        # Back on the crosshair, a click on the dot pins it again.
        self.assertEqual(len(self.r["repinned"]["lines"]), 3)

    def test_a_chart_type_switch_redraws_the_levels_on_the_new_series(self):
        """removeSeries takes a series' price lines with it: the pinned
        levels are drawn again on the series that replaced it, once."""
        swapped = self.r["swapped"]
        self.assertEqual(swapped["kind"], "line")
        self.assertNotIn("candle", swapped["series"])
        self.assertEqual([(l["title"], l["price"], l["style"]) for l in swapped["lines"]],
                         [("Entry", 1.0842, 2), ("Stop", 1.0812, 2),
                          ("Target", 1.0902, 2)])
        self.assertIn("is-pinned", swapped["card"]["cls"])
        self.assertFalse(swapped["card"]["hidden"])

    def test_a_signal_that_leaves_the_tape_takes_its_pin_and_key_along(self):
        gone = self.r["gone"]
        self.assertEqual(self._sig_markers(gone["markers"]), {})
        self.assertTrue(gone["legendHidden"])
        self.assertTrue(gone["card"]["hidden"])
        self.assertEqual(gone["lines"], [])
        self.assertEqual(len([m for m in gone["markers"] if "id" not in m]), 1)
