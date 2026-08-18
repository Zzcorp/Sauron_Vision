"""News-feed hover preview — a 2s dwell on a feed row opens an article
preview card, placed below the row or above it depending on the viewport
space the scroll position leaves, never under the fixed chrome.

The popup content is carried as data attributes on each row (the page
needs no extra endpoint and the card opens instantly once the dwell
elapses), and the script builds the card with textContent only — scraped
headlines never reach innerHTML. The up/down sentiment verdict is
computed SERVER-side from the raw score with the same predicate the
row's cell uses — the review caught the client re-deriving it from the
rounded display string, which disagreed with the cell at the 0.2
boundary.

Run with:  python manage.py test tests.test_news_hover_preview
"""
import itertools
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

_SEQ = itertools.count()


def _article(**kw):
    from scraping.models import NewsArticle
    defaults = dict(
        title="Copper squeezes shorts",
        source="Reuters",
        # Monotonic counter, not a timestamp: Windows clock granularity
        # let two same-tick creates collide on the unique url column.
        url=f"https://example.com/a/{next(_SEQ)}",
        published_at=timezone.now() - timedelta(hours=1),
    )
    defaults.update(kw)
    return NewsArticle.objects.create(**defaults)


class NewsHoverPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("nf_u")

    def setUp(self):
        self.client.force_login(self.user)

    def test_rows_carry_the_preview_payload(self):
        _article(content_summary="Prices ripped through resistance.",
                 ai_sentiment_score=0.55, ai_urgency="high")
        resp = self.client.get("/news/")
        self.assertContains(resp, 'class="nf-row"')
        self.assertContains(resp, 'data-nf-title="Copper squeezes shorts"')
        self.assertContains(
            resp, 'data-nf-summary="Prices ripped through resistance."')
        self.assertContains(resp, 'data-nf-sent="0.55"')
        self.assertContains(resp, 'data-nf-sent-cls="up"')
        self.assertContains(resp, 'data-nf-urgency="high"')

    def test_the_ai_summary_wins_over_the_scraped_one(self):
        _article(title="Gold steadies",
                 content_summary="raw scrape text",
                 ai_summary="The analyst's distilled read.")
        resp = self.client.get("/news/")
        self.assertContains(
            resp, "data-nf-summary=\"The analyst&#x27;s distilled read.\"")
        self.assertNotContains(resp, 'data-nf-summary="raw scrape text"')

    def test_long_payloads_are_truncated_for_the_attributes(self):
        _article(title="T" * 500, content_summary="x" * 600)
        resp = self.client.get("/news/")
        body = resp.content.decode("utf-8")
        self.assertIn("x" * 419 + "…", body,
                      "the 600-char summary must be cut at 420 with an ellipsis")
        self.assertNotIn("x" * 600, body)
        # Titles are CharField(max_length=500); untruncated they made the
        # card taller than short viewports. Assert on the attribute — the
        # base chrome's news ticker renders the full title legitimately.
        self.assertIn('data-nf-title="' + "T" * 219 + "…", body)
        self.assertNotIn('data-nf-title="' + "T" * 220, body)

    def test_scraped_quotes_cannot_break_out_of_the_attribute(self):
        _article(title='He said "buy" and left')
        resp = self.client.get("/news/")
        self.assertContains(
            resp, 'data-nf-title="He said &quot;buy&quot; and left"')

    def test_unscored_articles_render_empty_not_none(self):
        """ai_sentiment_score=None and blank urgency must yield empty
        attributes — the string "None" would render as a fact chip."""
        _article(title="Unscored yet")
        resp = self.client.get("/news/")
        self.assertContains(resp, 'data-nf-sent=""')
        self.assertContains(resp, 'data-nf-sent-cls=""')
        self.assertContains(resp, 'data-nf-urgency=""')
        self.assertNotContains(resp, 'data-nf-sent="None"')

    def test_a_zero_score_is_a_score_not_an_absence(self):
        """0.0 is a legitimately neutral verdict. A truthiness check in
        the template (`{% if a.ai_sentiment_score %}`) would silently drop
        it — the guard must be `!= None`."""
        _article(title="Perfectly neutral", ai_sentiment_score=0.0)
        resp = self.client.get("/news/")
        self.assertContains(resp, 'data-nf-sent="0.00"')
        self.assertContains(resp, 'data-nf-sent-cls=""')

    def test_the_boundary_verdict_matches_the_cell(self):
        """0.204 displays as 0.20 but IS bullish (raw 0.204 > 0.2, the
        cell's own predicate). Re-deriving the verdict client-side from
        the rounded string called this neutral while the cell showed
        green — the class must come from the server."""
        _article(title="Boundary case", ai_sentiment_score=0.204)
        resp = self.client.get("/news/")
        self.assertContains(resp, 'data-nf-sent="0.20"')
        self.assertContains(resp, 'data-nf-sent-cls="up"')

    def test_tagged_instruments_reach_the_payload(self):
        from instruments.models import Instrument
        art = _article(title="Tagged article")
        for sym in ("AAPL", "MSFT"):
            inst, _ = Instrument.objects.get_or_create(
                symbol=sym, defaults={"name": sym, "asset_class": "stock"})
            art.ai_affected_instruments.add(inst)
        resp = self.client.get("/news/")
        self.assertContains(resp, 'data-nf-instruments="AAPL, MSFT"')

    def test_the_dwell_script_is_armed(self):
        """The contract the user asked for, pinned: a TWO-second dwell on
        the feed rows opens the portal card."""
        _article()
        resp = self.client.get("/news/")
        self.assertContains(resp, 'id="newsFeedBody"')
        self.assertContains(resp, "HOVER_DELAY_MS = 2000")
        self.assertContains(resp, "nf-pop")
