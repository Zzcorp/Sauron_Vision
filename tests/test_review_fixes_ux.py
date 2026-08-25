"""What the adversarial review caught in the seven-feature wave.

Each test here is a defect that shipped green once: a baseline close
taken from the session the news itself moved, an entity regex that
backtracked a scraped slug into a minute-long request, a "disable"
button that was a toggle, a proposal the database let through twice, a
guide who counted the page under your nose as unseen, and a fullscreen
chart that outranked the lock screen.

Run with:  python manage.py test tests.test_review_fixes_ux
"""
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


def _src(*parts):
    return Path(settings.BASE_DIR).joinpath(*parts).read_text(
        encoding="utf-8")


def _article(**kw):
    from scraping.models import NewsArticle
    defaults = dict(title="Copper holds", source="Reuters",
                    url="https://example.com/rf1",
                    published_at=timezone.now() - timedelta(hours=6),
                    content_summary="")
    defaults.update(kw)
    return NewsArticle.objects.create(**defaults)


def _instrument(symbol="RFX"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
    return inst


class NewsBaselineTests(TestCase):
    def test_the_baseline_is_a_session_that_had_already_closed(self):
        """1d bars are stamped at their OPEN, so the bar preceding
        publication is the SAME session — its close lands hours after
        the news and would price the reaction into the baseline."""
        from dashboard.news_detail import _instrument_rows
        from market_data.models import PriceData

        art = _article()
        inst = _instrument("RFB")
        art.ai_affected_instruments.add(inst)
        # Same-session bar: opened before the article, closed after it.
        PriceData.objects.create(instrument=inst, timeframe="1d",
                                 timestamp=art.published_at - timedelta(hours=8),
                                 open=Decimal("100"), high=Decimal("101"),
                                 low=Decimal("99"), close=Decimal("104"))
        # The session that had genuinely closed.
        PriceData.objects.create(instrument=inst, timeframe="1d",
                                 timestamp=art.published_at - timedelta(days=1),
                                 open=Decimal("100"), high=Decimal("101"),
                                 low=Decimal("99"), close=Decimal("100"))
        rows = _instrument_rows(art, [inst])
        self.assertEqual(float(rows[0]["base_close"]), 100.0)

    def test_a_month_old_bar_is_not_a_baseline(self):
        from dashboard.news_detail import _instrument_rows
        from market_data.models import PriceData

        art = _article(url="https://example.com/rf2")
        inst = _instrument("RFC")
        art.ai_affected_instruments.add(inst)
        PriceData.objects.create(instrument=inst, timeframe="1d",
                                 timestamp=art.published_at - timedelta(days=30),
                                 open=Decimal("100"), high=Decimal("101"),
                                 low=Decimal("99"), close=Decimal("100"))
        rows = _instrument_rows(art, [inst])
        self.assertIsNone(rows[0]["base_close"])
        self.assertIsNone(rows[0]["since_pct"])


class NewsExtractionTests(TestCase):
    def test_a_hyphen_slug_cannot_stall_the_request(self):
        """`'` and `-` are inside the word class but non-word to \\b, so
        every capital after a hyphen was a fresh match start and the
        engine backtracked character by character."""
        from dashboard.news_detail import _extract_keywords
        art = _article(url="https://example.com/rf3",
                       raw_content="Ab-" * 20000)
        started = time.monotonic()
        _extract_keywords(art)
        self.assertLess(time.monotonic() - started, 3.0)

    def test_a_title_case_headline_is_not_one_giant_name(self):
        from dashboard.news_detail import _extract_keywords
        art = _article(
            url="https://example.com/rf4",
            title="Fed Holds Rates Steady As Powell Signals Patience Ahead",
            ai_summary="The decision came from the Federal Reserve today.")
        chips = _extract_keywords(art)
        for c in chips:
            self.assertLessEqual(len(c["text"].split()), 4, c["text"])

    def test_the_macro_vocabulary_survives_the_length_floor(self):
        from dashboard.news_detail import _extract_keywords
        art = _article(url="https://example.com/rf5",
                       ai_summary="Oil and gas slid as war risk eased; "
                                  "the tax bill stalled and oil fell again.")
        words = {c["text"] for c in _extract_keywords(art)}
        self.assertIn("oil", words)

    def test_common_acronyms_do_not_take_the_ticker_slots(self):
        from dashboard.news_detail import _extract_keywords
        art = _article(url="https://example.com/rf6",
                       ai_summary="US CEO says AI boom lifts NVDA and NVDA "
                                  "again as the US CEO adds AI capacity.")
        tickers = {c["text"] for c in _extract_keywords(art)
                   if c["kind"] == "ticker"}
        self.assertIn("NVDA", tickers)
        self.assertNotIn("CEO", tickers)

    def test_a_wordless_body_is_unmeasured_not_zero_words(self):
        from dashboard.news_detail import _reading_facts
        art = _article(url="https://example.com/rf7", raw_content="   ")
        self.assertIsNone(_reading_facts(art)["words"])


class BrainLeverTests(TestCase):
    def setUp(self):
        self.op = get_user_model().objects.create_superuser(
            "rf_op", "op@x.x", "x")
        self.client.force_login(self.op)

    def _manual(self, asset_class="stock", enabled=True):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.create(
            user=self.op, asset_class=asset_class, name=MANUAL_CONFIG_NAME,
            enabled=enabled, mode="paper", symbols=[],
            capital=Decimal("1000"))

    def test_disabling_twice_leaves_it_disabled(self):
        """hq_toggle_asset_bot flips whatever it finds — a stale page or
        a double submit would RE-ARM the config the brain asked to
        quiet."""
        cfg = self._manual()
        for _ in range(2):
            self.client.post("/brain/disable-manual/",
                             {"config_id": cfg.id})
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)

    def test_a_config_that_is_not_yours_is_refused(self):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        from bot_program.models import AssetBotConfig
        other = get_user_model().objects.create_user("rf_other",
                                                     password="x")
        cfg = AssetBotConfig.objects.create(
            user=other, asset_class="stock", name=MANUAL_CONFIG_NAME,
            enabled=True, mode="paper", symbols=[], capital=Decimal("1000"))
        self.client.post("/brain/disable-manual/", {"config_id": cfg.id})
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)

    def test_a_plain_staff_user_cannot_pull_the_lever(self):
        staff = get_user_model().objects.create_user("rf_staff",
                                                     password="x")
        staff.is_staff = True
        staff.save()
        cfg = self._manual(asset_class="forex")
        self.client.force_login(staff)
        resp = self.client.post("/brain/disable-manual/",
                                {"config_id": cfg.id})
        self.assertEqual(resp.status_code, 403)
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)


class BrainProposalTests(TestCase):
    def _report(self, overlay=None):
        from brain.models import BrainReport
        return BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.8,
            rule_status_overlay=overlay or {})

    def test_a_rule_nothing_governs_gets_no_ticket(self):
        """The overlay's keys are LLM-typed; a pause on a rule no
        control, signal or trade has heard of enforces nothing."""
        from signals.rule_actuator import ActuatorError, propose_from_brain
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name="real_rule")
        report = self._report({"made_up_rule": "pause_recommended"})
        with self.assertRaises(ActuatorError):
            propose_from_brain(report, "made_up_rule", "pause_rule", None)

    def test_a_rejected_proposal_can_be_raised_again(self):
        """A rejection is a decision about YESTERDAY's concern; the
        brain raising it again deserves a fresh ticket, not the corpse
        of the old one."""
        from signals.models import RuleAction, RuleControl
        from signals.rule_actuator import propose_from_brain
        RuleControl.objects.create(rule_name="gov_rule")
        report = self._report({"gov_rule": "pause_recommended"})
        first = propose_from_brain(report, "gov_rule", "pause_rule", None)
        again = propose_from_brain(report, "gov_rule", "pause_rule", None)
        self.assertEqual(first.id, again.id)
        first.state = RuleAction.STATE_REJECTED
        first.save(update_fields=["state"])
        third = propose_from_brain(report, "gov_rule", "pause_rule", None)
        self.assertNotEqual(third.id, first.id)
        self.assertEqual(third.state, RuleAction.STATE_PROPOSED)

    def test_a_wild_severity_is_clamped_where_every_number_is(self):
        from brain.synthesizer import _persist_report
        rep = _persist_report(
            {"regime_label": "trending", "regime_confidence": 0.8,
             "top_concerns": [{"kind": "x", "text": "y", "severity": 8.5},
                              {"kind": "z", "text": "w", "severity": "high"}]},
            {}, model="t", tokens_in=0, tokens_out=0, cost_usd=0,
            n_consumed=0)
        self.assertEqual(rep.top_concerns[0]["severity"], 1.0)
        self.assertIsNone(rep.top_concerns[1]["severity"])

    def test_the_brain_page_reports_its_own_result_only(self):
        """The page rendered the whole messages queue, so a flash left
        by any view whose target never shows one surfaced here dressed
        as a brain-action result."""
        self.assertNotIn("{% for msg in messages %}",
                         _src("templates", "dashboard", "brain.html"))
        self.assertIn("brain_propose_result",
                      _src("templates", "dashboard", "brain.html"))


class LockOutranksEverythingTests(TestCase):
    def test_the_lock_leaves_fullscreen_before_it_paints(self):
        """A fullscreen element lives in the browser's TOP LAYER, above
        every z-index there is — including the veil."""
        js = _src("static", "js", "idle-lock.js")
        engage = js.split("function engage(")[1][:1400]
        self.assertIn("exitFullscreen", engage)
        widget = _src("templates", "_partials", "chart_widget.html")
        self.assertIn("svIdleLock.isLocked()", widget)

    def test_the_guide_sits_under_the_veil_on_the_ladder(self):
        css = _src("static", "css", "sauron.css")
        block = css.split(".gollum-fab {")[1].split("}")[0]
        self.assertIn("var(--z-fab", block)
        self.assertNotIn("8500", block)


class ChartTruthTests(TestCase):
    def test_a_marker_lands_on_the_bar_that_contains_it(self):
        """A daily bar opens at midnight, so an entry at 15:30 is nearer
        to tomorrow's open than to today's — nearest-neighbour drew it a
        session late."""
        widget = _src("templates", "_partials", "chart_widget.html")
        fn = widget.split("function nearestBarTime")[1].split("function ")[0]
        self.assertIn("bars[Math.max(0, lo - 1)].time", fn)
        self.assertNotIn("Math.abs(barEpoch(a.time)", fn)

    def test_modifier_chords_belong_to_the_browser(self):
        widget = _src("templates", "_partials", "chart_widget.html")
        self.assertIn("if (ev.ctrlKey || ev.metaKey || ev.altKey) return;",
                      widget)
