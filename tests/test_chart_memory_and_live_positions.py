"""Each instrument's chart as the operator left it, and a position that
appears on the tape it was opened from.

Two operator reports.

"make sure each instrument graphs is remembered no?" — chart type, log scale
and the indicator toggles were already kept per symbol. The TIMEFRAME was
not: `currentTf` was initialised unconditionally from the include's
parameter, `paintToolbarState()` never touched the timeframe buttons, and the
click handler never saved — so an operator working a 5-minute tape re-picked
it on every single navigation. Neither were DRAWINGS, which cost a deliberate
act to place and did not survive a reload.

"when we open a position we on instrument we have to refresh to see on chart"
— the position list was baked into the page as a json_script block and read
once at boot. Even the sixty-second chart refresh only re-fetched BARS, so a
position opened from the page was invisible above the button that opened it,
and a position a bot opened was invisible indefinitely.

Run with:  python manage.py test tests.test_chart_memory_and_live_positions
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone


def widget(**ctx):
    base = {"chart_id": "t", "symbol": "EURUSD", "height": "420",
            "timeframe": "1d"}
    base.update(ctx)
    return render_to_string("_partials/chart_widget.html", base)


def widget_source():
    return (Path(settings.BASE_DIR) / "templates" / "_partials"
            / "chart_widget.html").read_text(encoding="utf-8")


# ═══ A. The chart is remembered, per instrument ═══════════════════════

class TheKeyNamesTheInstrumentTests(TestCase):

    def test_the_key_carries_both_the_surface_and_the_symbol(self):
        """It was the prefix plus the symbol alone, which collided twice:
        every symbol-less include shared the literal key 'sv-chart:', and
        two charts of the same symbol on one page shared one record."""
        html = widget()
        self.assertIn("'sv-chart:' + CHART_ID + ':' + SYMBOL", html)

    def test_a_widget_with_no_symbol_neither_reads_nor_writes(self):
        """It can never load data; a record it wrote would belong to no
        instrument."""
        html = widget(symbol="")
        self.assertIn("if (!SYMBOL) return {};", html)
        self.assertIn("if (!SYMBOL) return;", html)


class TheTimeframeIsRememberedTests(TestCase):

    def test_it_is_saved(self):
        self.assertIn("tf: currentTf,", widget())

    def test_it_is_restored_over_the_includes_default(self):
        html = widget()
        self.assertIn("currentTf = prefs.tf;", html)

    def test_only_a_frame_the_toolbar_still_offers_is_restored(self):
        """A value stored by an older build must not leave the chart on a
        frame nobody can switch back from."""
        html = widget()
        self.assertIn("function offeredTimeframes(", html)
        self.assertIn("offeredTimeframes().indexOf(prefs.tf) !== -1", html)

    def test_the_frames_are_read_off_the_buttons_not_listed_twice(self):
        """A hardcoded copy is how a frame gets removed from the UI and
        stays reachable through a stale preference."""
        self.assertIn("container.querySelectorAll('.sv-tf-btn')", widget())

    def test_the_toolbar_paints_the_frame_the_chart_is_showing(self):
        """The template marks the include's default active in the HTML, so
        a restored preference would leave the chart on 5min with the 1d
        button lit — the toolbar lying about the tape beside it."""
        html = widget()
        self.assertIn("b.dataset.tf === currentTf", html)

    def test_the_click_handler_saves(self):
        src = widget_source()
        i = src.find(".sv-tf-btn').forEach(function(btn)")
        self.assertGreater(i, 0)
        self.assertIn("savePrefs();", src[i:i + 1800])


class TheDrawingsSurviveAReloadTests(TestCase):

    def test_they_are_serialised(self):
        html = widget()
        self.assertIn("function serialiseDrawings(", html)
        self.assertIn("drawings: savedDrawings,", html)

    def test_they_are_redrawn_after_every_load(self):
        """setData wipes markers and a removed series takes its price lines
        with it — the same reason applyOverlays exists at all."""
        html = widget()
        self.assertIn("function restoreDrawings(", html)
        self.assertIn("restoreDrawings();", html)

    def test_a_drawing_carries_its_own_numbers(self):
        """A lightweight-charts price line cannot be asked what price it was
        made from, so a drawing that did not carry its own numbers could
        never be written down."""
        html = widget()
        self.assertIn("type: 'hline', priceLine: pl, price: price", html)
        self.assertIn("tf: currentTf, points:", html)

    def test_price_lines_are_kept_once_for_the_instrument(self):
        """1.0850 is 1.0850 whether the chart shows minutes or months."""
        self.assertIn("out.hlines.push(d.price)", widget())

    def test_trendlines_are_bucketed_by_the_frame_they_were_drawn_on(self):
        """The daily series carries date strings and the intraday series
        epoch seconds. A daily trendline restored onto a 5-minute chart
        draws a line through two points the series does not contain."""
        html = widget()
        self.assertIn("out.trendlines[d.tf]", html)
        self.assertIn("(savedDrawings.trendlines || {})[currentTf]", html)

    def test_switching_frames_does_not_erase_the_other_frames_lines(self):
        html = widget()
        self.assertIn("if (tf !== currentTf)", html)

    def test_a_trendline_whose_anchors_scrolled_away_is_dropped_not_clamped(self):
        """A line redrawn onto whatever sits at the edge of the window is
        not the line the operator drew, and nothing on screen would
        distinguish the two."""
        html = widget()
        self.assertIn("return isFinite(e) && e >= first && e <= last;", html)

    def test_the_record_is_bounded(self):
        """A chart somebody has been drawing on for a year must not grow a
        blob big enough to trip the storage quota and take the rest of the
        settings down with it."""
        self.assertIn("slice(-40)", widget())

    def test_clear_means_gone_not_gone_until_the_next_reload(self):
        src = widget_source()
        i = src.find("clearMeasure();\n                /* CLEAR means gone")
        self.assertGreater(i, 0, "the clear handler lost its save")
        self.assertIn("savePrefs();", src[i:i + 700])


class WhatIsDeliberatelyForgottenTests(TestCase):
    """Some state SHOULD reset, and saying so is as load-bearing as saying
    what to keep."""

    def test_the_viewport_is_not_persisted(self):
        """A zoom saved on Friday frames a window the market has left."""
        html = widget()
        self.assertNotIn("range: chart.timeScale().getVisibleLogicalRange()",
                         html)

    def test_the_view_state_is_not_persisted(self):
        """Restoring a page into fullscreen nobody asked for."""
        src = widget_source()
        i = src.find("window.localStorage.setItem(PREF_KEY")
        # Guarded: find() returns -1 when the anchor moves, and src[-1:2599]
        # is the EMPTY STRING — so an unguarded assertNotIn passes vacuously
        # against a rename, even if the very thing it forbids were added.
        self.assertGreater(i, 0, "the save anchor moved")
        blob = src[i:i + 2600]
        self.assertNotIn("view:", blob)
        self.assertNotIn("viewState:", blob)

    def test_a_half_taken_measurement_is_not_persisted(self):
        src = widget_source()
        i = src.find("window.localStorage.setItem(PREF_KEY")
        self.assertGreater(i, 0, "the save anchor moved")
        self.assertNotIn("measureFrom", src[i:i + 2600])


# ═══ B. A new position appears without a reload ═══════════════════════

class TheOverlayRidesTheResponseTheChartAlreadyAsksForTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("ovl_u", password="x")
        self.client.force_login(self.user)
        from instruments.models import Instrument
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="OVLTEST", defaults={"name": "O", "asset_class": "stock"})

    def test_the_widget_asks_for_overlays(self):
        """No second endpoint and no second poller: the chart already
        re-polls this URL every sixty seconds and already rebuilds every
        line from scratch on each paint."""
        self.assertIn("&overlays=1", widget())

    def test_the_endpoint_carries_positions_when_asked(self):
        res = self.client.get("/api/chart-data/",
                              {"symbol": "OVLTEST", "timeframe": "1d",
                               "overlays": "1"})
        self.assertIn("positions", res.json())
        self.assertIn("signals", res.json())

    def test_it_does_not_when_not_asked(self):
        """This endpoint also serves charts with no operator context; a
        user-scoped payload must not become the default response shape."""
        res = self.client.get("/api/chart-data/",
                              {"symbol": "OVLTEST", "timeframe": "1d"})
        self.assertNotIn("positions", res.json())

    def test_an_open_position_reaches_the_response(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="O", mode="paper",
            symbols=["OVLTEST"], capital=Decimal("10000"), enabled=True)
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="OVLTEST", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("95"), status="OPEN", paper=True,
            opened_at=timezone.now())
        res = self.client.get("/api/chart-data/",
                              {"symbol": "OVLTEST", "timeframe": "1d",
                               "overlays": "1"})
        rows = res.json()["positions"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry"], 100.0)
        self.assertEqual(rows[0]["stop"], 95.0)

    def test_another_operators_position_never_reaches_it(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        other = User.objects.create_user("ovl_other", password="x")
        cfg = AssetBotConfig.objects.create(
            user=other, asset_class="stock", name="X", mode="paper",
            symbols=["OVLTEST"], capital=Decimal("10000"), enabled=True)
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="OVLTEST", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
            paper=True, opened_at=timezone.now())
        res = self.client.get("/api/chart-data/",
                              {"symbol": "OVLTEST", "timeframe": "1d",
                               "overlays": "1"})
        self.assertEqual(res.json()["positions"], [])

    def test_an_overlay_failure_does_not_cost_the_operator_their_chart(self):
        """The bars are the payload."""
        from unittest.mock import patch
        with patch("dashboard.views._chart_positions",
                   side_effect=RuntimeError("boom")):
            res = self.client.get("/api/chart-data/",
                                  {"symbol": "OVLTEST", "timeframe": "1d",
                                   "overlays": "1"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("bars", res.json())


class TheWidgetAdoptsItSafelyTests(TestCase):

    def test_it_is_adopted_after_the_sequence_guard(self):
        """The sixty-second poll and a fill-triggered refresh overlap: a
        slow in-flight response from before the fill has its bars correctly
        discarded, and would otherwise still overwrite the fresh positions
        on its way past."""
        src = widget_source()
        guard = src.find("if (seq !== loadSeq) return;")
        adopt = src.find("POSITIONS = json.positions;")
        self.assertGreater(guard, 0)
        self.assertGreater(adopt, guard)

    def test_it_is_adopted_before_the_early_returns(self):
        """A position is real whether or not this venue could serve bars
        this second; a minute-bar outage must not erase the stop line the
        operator is watching."""
        src = widget_source()
        adopt = src.find("POSITIONS = json.positions;")
        bail = src.find("if (json.error) {", adopt - 2000)
        self.assertGreater(bail, adopt)

    def test_an_empty_array_clears_the_lines(self):
        """Array.isArray, never truthiness: an EMPTY array is the correct
        answer when the last position closed."""
        html = widget()
        self.assertIn("Array.isArray(json.positions)", html)
        self.assertIn("Array.isArray(json.signals)", html)

    def test_a_missing_key_leaves_the_screen_alone(self):
        """It means this response was not asked for overlays."""
        src = widget_source()
        i = src.find("var overlayFresh = false;")
        self.assertGreater(i, 0)
        self.assertIn("Array.isArray(json.positions)", src[i:i + 900])


class SomethingSaysWhenToLookTests(TestCase):

    def _base(self):
        return (Path(settings.BASE_DIR) / "templates" / "base.html"
                ).read_text(encoding="utf-8")

    def _poller(self):
        return (Path(settings.BASE_DIR) / "static" / "js"
                / "sv-instrument-live.js").read_text(encoding="utf-8")

    def test_the_event_is_dispatched_from_tradeflow(self):
        """One line covers the signal path and the asset path, where a
        third entry point cannot forget to add it."""
        src = self._base()
        i = src.find("function tradeFlow(")
        j = src.find("window.svTakeTrade = function", i)
        self.assertIn("sv:position-changed", src[i:j])

    def test_it_fires_on_the_execute_response_not_the_preview(self):
        """execute_asset_trade closes its atomic block before it builds the
        response. Hanging the refresh off the PREVIEW would refetch before
        the write and draw nothing — which looks exactly like the bug never
        being fixed."""
        src = self._base()
        dispatch = src.find("sv:position-changed")
        exec_call = src.find("fetch(executeUrl, {")
        self.assertGreater(dispatch, exec_call)

    def test_the_page_listens_for_its_own_entry_and_for_everyone_elses(self):
        poller = self._poller()
        self.assertIn("sv:position-changed", poller)
        self.assertIn("sv:eye-event", poller)

    def test_another_instruments_fill_is_ignored(self):
        self.assertIn("!== String(symbol).toUpperCase()", self._poller())

    def test_the_two_triggers_are_debounced_into_one_fetch(self):
        """The response and the WebSocket push arrive milliseconds apart."""
        self.assertIn("if (syncTimer) return;", self._poller())

    def test_the_one_shot_ignores_the_hidden_tab_guard(self):
        """An operator returning to the tab must not find a chart that
        skipped the fill they just made."""
        poller = self._poller()
        i = poller.find("function syncPositions()")
        j = poller.find("document.addEventListener('sv:position-changed'")
        self.assertNotIn("document.hidden", poller[i:j])


class TheLevelEditorRepaintsInsteadOfReloadingTests(TestCase):

    def test_the_hook_it_calls_now_exists(self):
        """sv-level-edit.js asked for window.svLiveRefresh, which was
        defined nowhere — so every accepted stop or target fell through to
        location.reload() and threw the operator's scroll, chart and zoom
        away to repaint two cells."""
        region = (Path(settings.BASE_DIR) / "templates" / "_partials"
                  / "live_region.html").read_text(encoding="utf-8")
        self.assertIn("window.svLiveRefresh = function", region)
        # Not a bare `schedule`: refresh() returns without fetching while
        # one is already in flight, and the sweep runs every 20 seconds — so
        # a sweep issued a second before the save could swallow the repaint
        # and leave the operator reading the pre-edit stop with no retry,
        # which is the one thing the location.reload() it replaced always
        # got right.
        self.assertIn("if (inFlight && ++tries", region)
        editor = (Path(settings.BASE_DIR) / "static" / "js"
                  / "sv-level-edit.js").read_text(encoding="utf-8")
        self.assertIn("w.svLiveRefresh", editor)
