"""The chart's second storey: panes, MACD, volume, and a ruler in R.

RSI used to be the only thing under the price — its height, creation,
sync, teardown and legend written out in five separate places. A second
pane written the same way would be a sixth copy of the plumbing, and
copies drift. These tests hold the registry shape, not the indicators:
the point is that adding the next pane is a table entry.
"""
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase


def widget(**ctx):
    base = {"chart_id": "t", "symbol": "EURUSD", "height": "420",
            "timeframe": "1d"}
    base.update(ctx)
    return render_to_string("_partials/chart_widget.html", base)


def source():
    return (Path(settings.BASE_DIR) / "templates" / "_partials"
            / "chart_widget.html").read_text(encoding="utf-8")


class ThePaneRegistryTests(TestCase):

    def test_the_panes_share_one_host_and_one_creation_path(self):
        html = widget()
        self.assertIn('id="t-panes"', html)
        self.assertIn("PANE_SPECS", html)
        self.assertIn("function ensurePane(", html)
        self.assertIn("function destroyPane(", html)

    def test_the_old_hand_wired_rsi_pane_is_gone(self):
        """Not merely unused — REMOVED. A dead second implementation of a
        pane is the one a later edit would pick up."""
        src = source()
        for ghost in ("ensureRsiPane", "rsiChart", "rsiSeries", "RSI_H"):
            self.assertNotIn(ghost, src, f"{ghost} survived the registry")

    def test_both_panes_are_declared_and_offered(self):
        html = widget()
        self.assertIn('data-ind="rsi"', html)
        self.assertIn('data-ind="macd"', html)
        # ...and each one is a spec, not a branch.
        self.assertIn("rsi: {", html)
        self.assertIn("macd: {", html)

    def test_one_zoom_moves_every_pane(self):
        """Panes that scroll independently are two charts of different
        windows stacked to look like one."""
        html = widget()
        self.assertIn("function propagateRange(", html)
        self.assertIn("propagateRange('main'", html)

    def test_the_panes_keep_a_stable_order(self):
        """A pane that jumps position when an unrelated one opens is a
        pane the operator has to re-find."""
        self.assertIn("function orderPanes(", widget())

    def test_the_time_axes_are_aligned_across_panes(self):
        """Each pane is its own canvas, so its price scale is only as
        wide as its own labels — and two axes ten pixels apart put the
        same bar at two different x positions."""
        self.assertIn("function alignPriceScales(", widget())


class TheMacdIsComputedNotGuessedTests(TestCase):

    def test_macd_is_declared_with_the_standard_periods(self):
        html = widget()
        self.assertIn("macd(bars, 12, 26, 9)", html)

    def test_the_signal_line_is_an_ema_of_the_macd_not_of_price(self):
        """The one thing that is easy to get wrong here. `emaPoints`
        exists precisely because `ema(bars, n)` reads closes."""
        html = widget()
        self.assertIn("function emaPoints(", html)
        self.assertIn("emaPoints(line, signalN)", html)

    def test_the_two_emas_are_joined_on_time_not_index(self):
        """They warm up at different bars. Aligning by index shifts the
        whole histogram by (slow - fast) bars and every cross with it."""
        html = widget()
        self.assertIn("byTime[barEpoch(p.time)]", html)


class VolumeIsAChoiceTests(TestCase):

    def test_volume_has_a_button(self):
        self.assertIn('data-ind="volume"', widget())

    def test_it_defaults_on_for_anyone_who_never_touches_it(self):
        """`undefined` means "never had the choice", not "chose no" —
        a stored preference blob written before the button existed must
        not silently turn the histogram off."""
        html = widget()
        self.assertIn("if (activeInds.volume === undefined) "
                      "activeInds.volume = true;", html)

    def test_the_legend_stops_reporting_a_hidden_histogram(self):
        html = widget()
        self.assertIn("(volumeSeries && activeInds.volume)", html)


class TheMeasureToolAnswersInRTests(TestCase):

    def test_the_tool_exists_beside_the_other_drawings(self):
        self.assertIn('data-tool="measure"', widget())

    def test_r_comes_from_a_real_stop_not_an_invented_denominator(self):
        """R on this desk is entry-to-stop distance. The tool asks the
        open position for it."""
        html = widget()
        self.assertIn("function riskPerUnit(", html)
        self.assertIn("Math.abs(p.entry - p.stop)", html)

    def test_with_no_stop_it_prints_a_dash_rather_than_a_number(self):
        html = widget()
        self.assertIn("&middot; —R", html)

    def test_leaving_the_tool_abandons_a_half_taken_measurement(self):
        """An anchor left armed would pair with an unrelated click made
        minutes later and report a move nobody measured."""
        html = widget()
        self.assertIn("if (tool !== 'measure') measureFrom = null;", html)

    def test_the_measurement_reports_the_move_the_span_and_the_size(self):
        html = widget()
        self.assertIn("function barsBetween(", html)
        self.assertIn("function showMeasure(", html)
