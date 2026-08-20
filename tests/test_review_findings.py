"""Regressions for the four defects the adversarial review confirmed.

Each of these was found by reading the change set, not by a failing test —
which is the point of writing them down here. All four are the same species:
code that is correct in the case it was written for and silently wrong in
the case nobody enumerated.

Run with:  python manage.py test tests.test_review_findings
"""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _read(*parts):
    return (Path(settings.BASE_DIR).joinpath(*parts)
            .read_text(encoding="utf-8", errors="replace"))


# ══════════════════════════════════════════════════════════════════════════
# 1. A refusal is not an answer
# ══════════════════════════════════════════════════════════════════════════

class SameFactsDedupeTests(TestCase):
    """`_same_facts_recently` gated on the hash alone.

    The row is written BEFORE the per-pass cap, the daily cap and the budget
    check run, so a position that was measured and then refused a model pass
    left a row carrying that hash — and the next pass could not tell it from
    a row that had actually been reasoned about. The refusal muted the
    position for the full six-hour TTL while its own `skipped_reason` read
    "re-queued next pass". The fingerprint is bucketed by design, so the
    positions it hit hardest were the ones flagged for structural reasons
    that do not move: a decayed rule, a regime flip, a self-hedge.
    """

    def setUp(self):
        self.user = User.objects.create_user("dedupe_u")

    def _row(self, **kw):
        from brain.position_review_models import PositionReview
        return PositionReview.objects.create(
            user=self.user, book="bot", position_id=kw.pop("position_id", 1),
            symbol="AAPL", side="BUY", facts_hash=kw.pop("facts_hash", "abc"),
            **kw)

    def test_a_capped_row_does_not_mute_the_next_pass(self):
        from brain.position_review_agent import _same_facts_recently
        from brain.position_review_models import PositionReview
        self._row(verdict=PositionReview.VERDICT_NONE,
                  skipped_reason="per-pass cap reached (3) — re-queued next pass")
        self.assertFalse(_same_facts_recently("abc"),
                         "a position refused for the cap must be asked again")

    def test_a_budget_refusal_does_not_mute_the_next_pass(self):
        from brain.position_review_agent import _same_facts_recently
        from brain.position_review_models import PositionReview
        self._row(verdict=PositionReview.VERDICT_NONE,
                  skipped_reason="AI budget: daily cap reached")
        self.assertFalse(_same_facts_recently("abc"))

    def test_an_answered_row_does_mute_the_next_pass(self):
        """The dedupe still has to work — that is what bounds the cost."""
        from brain.position_review_agent import _same_facts_recently
        from brain.position_review_models import PositionReview
        self._row(verdict=PositionReview.VERDICT_HOLD, reasoning_md="fine",
                  model_used="claude-x")
        self.assertTrue(_same_facts_recently("abc"))

    def test_a_stale_mark_row_mutes_the_next_pass(self):
        """It already says the only thing there is to say, and if the mark
        comes back the facts change and the hash with them."""
        from brain.position_review_agent import _same_facts_recently
        from brain.position_review_models import PositionReview
        self._row(verdict=PositionReview.VERDICT_NO_QUOTE, stale_quote=True)
        self.assertTrue(_same_facts_recently("abc"))

    def test_an_errored_row_is_retried(self):
        """A failed API call is not a verdict."""
        from brain.position_review_agent import _same_facts_recently
        from brain.position_review_models import PositionReview
        self._row(verdict=PositionReview.VERDICT_NONE, error="api down")
        self.assertFalse(_same_facts_recently("abc"))

    def test_an_old_answered_row_stops_muting(self):
        from brain.position_review_agent import (SAME_FACTS_TTL_HOURS,
                                                 _same_facts_recently)
        from brain.position_review_models import PositionReview
        row = self._row(verdict=PositionReview.VERDICT_HOLD,
                        model_used="claude-x")
        PositionReview.objects.filter(pk=row.pk).update(
            created_at=timezone.now()
            - timedelta(hours=SAME_FACTS_TTL_HOURS + 1))
        self.assertFalse(_same_facts_recently("abc"))

    def test_an_empty_hash_never_mutes(self):
        from brain.position_review_agent import _same_facts_recently
        self.assertFalse(_same_facts_recently(""))


# ══════════════════════════════════════════════════════════════════════════
# 2. "Since entry" has to mean since entry
# ══════════════════════════════════════════════════════════════════════════

class ExcursionWindowTests(TestCase):
    """MAE/MFE were the extremes of the newest 400 bars, labelled "since
    entry". On the 1h feed that is ~17 trading days, against time-stop
    ceilings in this same change set that run to 720 hours — so a month-old
    position had its opening weeks amputated from the number that decides
    whether `give_back` fires."""

    def setUp(self):
        from instruments.models import Instrument
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="EXCUR", defaults={"name": "Excursion",
                                      "asset_class": "stock",
                                      "is_active": True})
        self.opened = timezone.now() - timedelta(days=40)

    def _bar(self, when, high, low):
        from market_data.models import PriceData
        PriceData.objects.create(
            instrument=self.inst, timeframe="1h", timestamp=when,
            open=Decimal("100"), high=Decimal(str(high)),
            low=Decimal(str(low)), close=Decimal("100"), volume=1)

    def _pos(self, dir_sign=1):
        return {"opened_at": self.opened, "dir_sign": dir_sign,
                "symbol": "EXCUR"}

    def test_the_earliest_spike_is_not_dropped(self):
        from brain.position_review import _excursion
        # The peak is in the FIRST week and then 500 quiet bars follow it —
        # more than the 400-bar window that used to be read.
        self._bar(self.opened + timedelta(hours=2), 180, 95)
        for i in range(500):
            self._bar(self.opened + timedelta(days=8, hours=i), 101, 99)
        worst, best = _excursion(self.inst, self._pos(), 100.0)
        self.assertEqual(best, 180.0,
                         "the peak that give_back exists to catch was dropped")

    def test_the_earliest_drawdown_is_not_dropped(self):
        from brain.position_review import _excursion
        self._bar(self.opened + timedelta(hours=2), 101, 40)
        for i in range(500):
            self._bar(self.opened + timedelta(days=8, hours=i), 101, 99)
        worst, _best = _excursion(self.inst, self._pos(), 100.0)
        self.assertEqual(worst, 40.0)

    def test_a_short_mirrors_the_pair(self):
        from brain.position_review import _excursion
        self._bar(self.opened + timedelta(hours=2), 180, 40)
        worst, best = _excursion(self.inst, self._pos(dir_sign=-1), 100.0)
        # A short's worst excursion is the HIGHEST print.
        self.assertEqual(worst, 180.0)
        self.assertEqual(best, 40.0)

    def test_the_current_mark_is_still_included(self):
        """A position younger than one bar must still report an excursion."""
        from brain.position_review import _excursion
        worst, best = _excursion(self.inst, self._pos(), 100.0)
        self.assertEqual((worst, best), (100.0, 100.0))

    def test_bars_before_entry_are_excluded(self):
        from brain.position_review import _excursion
        self._bar(self.opened - timedelta(days=5), 999, 1)
        self._bar(self.opened + timedelta(hours=1), 110, 90)
        worst, best = _excursion(self.inst, self._pos(), 100.0)
        self.assertEqual(best, 110.0)
        self.assertEqual(worst, 90.0)

    def test_it_reads_the_window_without_pulling_every_bar(self):
        """Aggregated in the database: the correct answer is also the cheap
        one, so there is nothing left for a row cap to protect."""
        for i in range(300):
            self._bar(self.opened + timedelta(hours=i), 101, 99)
        from brain.position_review import _excursion
        with self.assertNumQueries(1):
            _excursion(self.inst, self._pos(), 100.0)

    def test_the_cap_constant_is_gone(self):
        source = _read("brain", "position_review.py")
        self.assertNotIn("[:EXCURSION_MAX_BARS]", source)


# ══════════════════════════════════════════════════════════════════════════
# 3. The alarm colour has to reach the element that carries it
# ══════════════════════════════════════════════════════════════════════════

class HeadbandToneTests(TestCase):
    """The VOLATILITY cell moved its tone class onto an inner span so the
    live refresh could repaint it — but the selector stayed on `.ip-count`
    itself, so the >=60% branch rendered in the default accent GREEN. The
    highest-alarm state was drawn in the platform's "good" colour."""

    def setUp(self):
        self.css = _read("static", "css", "sauron.css")

    def test_a_red_tone_on_an_inner_span_is_coloured(self):
        self.assertIn(".ip-cat .ip-count .red", self.css)

    def test_a_blue_tone_on_an_inner_span_is_coloured(self):
        self.assertIn(".ip-cat .ip-count .blue", self.css)

    def test_the_old_form_still_works_for_cells_that_never_moved(self):
        self.assertIn(".ip-cat .ip-count.red", self.css)

    def test_gold_is_left_to_the_ink_rule(self):
        """`.ip-cat .gold` already catches the child and resolves to
        --accent-gold-ink, the gold that survives on white. A more specific
        rule here would win and put the glow token back on the light theme,
        undoing that contrast fix."""
        self.assertNotIn(".ip-cat .ip-count .gold", self.css)
        self.assertIn(".ip-cat .gold", self.css)

    def test_the_volatility_cell_still_asks_for_red(self):
        base = _read("templates", "base.html")
        self.assertIn('{% if panel_vol_pct >= 60 %}red', base)


# ══════════════════════════════════════════════════════════════════════════
# 4. One card, one destination
# ══════════════════════════════════════════════════════════════════════════

class BannerDestinationTests(TestCase):
    """The whole-card click closed over the FIRST alert's href. When later
    alerts coalesced into that banner, the visible Open link was retargeted
    to the inbox and the card body was not — two controls on one card
    resolving two different ways."""

    def setUp(self):
        self.base = _read("templates", "base.html")

    def test_the_click_reads_the_destination_off_the_element(self):
        self.assertIn("var dest = el.dataset.href;", self.base)

    def test_the_coalesce_branch_retargets_the_card_too(self):
        self.assertIn('existing.dataset.href = "/notifications/";', self.base)

    def test_the_captured_value_is_no_longer_the_destination(self):
        """`m` is the first alert's descriptor and must not decide where a
        click lands."""
        self.assertNotIn("window.location.href = m.href", self.base)
