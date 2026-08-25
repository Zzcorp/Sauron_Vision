"""News detail depth — the article page carries more than the summary:
keyword chips (entities first, tickers kept, stopwords out), a per-
instrument market reaction (live last vs the 1d close at or before
publication), the latest sentiment snapshot per instrument, 7-day
coverage by source with this article's rank in the timeline, and reading
facts (words, read time, scrape-to-analysis latency, source domain).

Every one of those is computed server-side, and every value the data
cannot support renders the muted em-dash — never a zero. The last test
here is the one that matters most: an article with nothing (no
instruments, no summary, no score) must render clean, with no "0.00%"
reaction, no "NEUTRAL 0.00" verdict, and no 500.

Run with:  python manage.py test tests.test_news_depth
"""
import itertools
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

_SEQ = itertools.count()


def _article(**kw):
    from scraping.models import NewsArticle
    defaults = dict(
        title="Copper squeezes shorts",
        source="Reuters",
        # Monotonic counter: Windows clock granularity let two same-tick
        # creates collide on the unique url column.
        url=f"https://www.example.com/a/{next(_SEQ)}",
        published_at=timezone.now() - timedelta(hours=2),
    )
    defaults.update(kw)
    return NewsArticle.objects.create(**defaults)


def _page(resp) -> str:
    """The article page proper. The base chrome (headband, panels) prints
    its own numbers, so "no zeros" is asserted against the nd-grid only."""
    body = resp.content.decode("utf-8")
    start = body.index('<div class="nd-grid">')
    return body[start:body.index("</aside>", start)]


def _instrument(symbol):
    from instruments.models import Instrument
    return Instrument.objects.create(symbol=symbol, name=symbol, asset_class="stock")


class NewsDepthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("nd_u")

    def setUp(self):
        self.client.force_login(self.user)

    # ---------------------------------------------------------- keywords
    def test_keywords_drop_stopwords_keep_entities_and_tickers(self):
        from dashboard.news_detail import _extract_keywords
        a = _article(
            title="The Federal Reserve holds rates as AAPL rallies",
            ai_summary=("Jerome Powell said the Federal Reserve would hold. "
                        "Tariffs on copper and the tariffs debate weighed on AAPL."),
        )
        chips = _extract_keywords(a)
        texts = [c["text"] for c in chips]
        kinds = {c["text"]: c["kind"] for c in chips}
        self.assertIn("Federal Reserve", texts)
        self.assertIn("Jerome Powell", texts)
        self.assertEqual(kinds["Federal Reserve"], "entity")
        self.assertIn("AAPL", texts)
        self.assertEqual(kinds["AAPL"], "ticker")
        self.assertIn("tariffs", texts)
        for stop in ("the", "said", "would", "and"):
            self.assertNotIn(stop, texts)
        # Entities lead the row, and the leading "The" was stripped.
        self.assertEqual(chips[0]["kind"], "entity")
        self.assertNotIn("The Federal Reserve", texts)
        # Frequency is counted: "tariffs" appeared twice.
        self.assertEqual(next(c for c in chips if c["text"] == "tariffs")["count"], 2)

    # ---------------------------------------------------------- reaction
    def test_reaction_measures_last_against_the_close_before_publication(self):
        from dashboard.news_detail import _instrument_rows
        from market_data.models import LiveQuote, PriceData
        inst = _instrument("NDR1")
        a = _article()
        a.ai_affected_instruments.add(inst)
        # A close after publication must NOT be the baseline.
        PriceData.objects.create(instrument=inst, timeframe="1d",
                                 timestamp=a.published_at - timedelta(days=1),
                                 open=100, high=101, low=99, close=Decimal("100"),
                                 source="t")
        PriceData.objects.create(instrument=inst, timeframe="1d",
                                 timestamp=a.published_at + timedelta(hours=1),
                                 open=100, high=101, low=99, close=Decimal("50"),
                                 source="t")
        LiveQuote.objects.create(instrument=inst, last=Decimal("110"),
                                 change_pct=Decimal("1.5"), source="t")
        row = _instrument_rows(a, [inst])[0]
        self.assertAlmostEqual(row["since_pct"], 10.0)
        self.assertEqual(row["since_tone"], "up")
        self.assertAlmostEqual(row["day_pct"], 1.5)
        self.assertIsNotNone(row["quote_age"])

    def test_reaction_is_unmeasured_without_a_baseline_bar(self):
        from dashboard.news_detail import _instrument_rows
        from market_data.models import LiveQuote
        inst = _instrument("NDR2")
        a = _article()
        a.ai_affected_instruments.add(inst)
        LiveQuote.objects.create(instrument=inst, last=Decimal("110"), source="t")
        row = _instrument_rows(a, [inst])[0]
        self.assertIsNone(row["since_pct"])
        self.assertEqual(row["since_tone"], "unknown")
        self.assertIsNone(row["sent_score"])
        resp = self.client.get(f"/news/{a.id}/")
        page = _page(resp)
        self.assertIn('id="nd-reaction"', page)
        self.assertNotIn("0.00%", page)
        self.assertIn('class="sv-unknown"', page)

    # ---------------------------------------------------------- sentiment
    def test_sentiment_context_shows_the_latest_snapshot(self):
        from scraping.models import SentimentSnapshot
        inst = _instrument("NDS1")
        a = _article()
        a.ai_affected_instruments.add(inst)
        now = timezone.now()
        SentimentSnapshot.objects.create(instrument=inst, source="reddit",
                                         timestamp=now - timedelta(days=1),
                                         bullish_count=1, bearish_count=9,
                                         composite_score=-0.8)
        SentimentSnapshot.objects.create(instrument=inst, source="reddit",
                                         timestamp=now, bullish_count=42,
                                         bearish_count=7, composite_score=0.63,
                                         trending=True)
        resp = self.client.get(f"/news/{a.id}/")
        self.assertContains(resp, 'id="nd-sentiment-ctx"')
        self.assertContains(resp, "0.63")
        self.assertContains(resp, "<td class=\"r\">42</td>", html=False)
        self.assertContains(resp, "▲ HOT")
        self.assertNotContains(resp, "-0.80")

    # ---------------------------------------------------------- coverage
    def test_coverage_counts_seven_days_by_source_and_ranks_this_report(self):
        from dashboard.news_detail import _coverage
        inst = _instrument("NDC1")
        now = timezone.now()
        first = _article(source="Reuters", published_at=now - timedelta(days=2))
        second = _article(source="Bloomberg", published_at=now - timedelta(days=1))
        third = _article(source="Reuters", published_at=now - timedelta(hours=1))
        stale = _article(source="FT", published_at=now - timedelta(days=9))
        for x in (first, second, third, stale):
            x.ai_affected_instruments.add(inst)
        cov = _coverage(third, [inst])
        self.assertEqual(cov["total"], 3)
        self.assertEqual(cov["by_source"][0], {"source": "Reuters", "n": 2})
        # Rank is against every report on the instrument, including the
        # one that aged out of the 7-day window.
        self.assertEqual(cov["rank_label"], "4th")
        self.assertFalse(cov["first"])
        self.assertEqual(_coverage(stale, [inst])["rank_label"], "1st")
        resp = self.client.get(f"/news/{third.id}/")
        self.assertContains(resp, 'id="nd-coverage"')
        self.assertContains(resp, "4th to file")

    # ---------------------------------------------------------- facts
    def test_reading_facts_count_words_read_time_latency_and_domain(self):
        from dashboard.news_detail import _reading_facts
        a = _article(raw_content=" ".join(["word"] * 450))
        a.ai_processed_at = a.scraped_at + timedelta(minutes=4, seconds=10)
        a.save()
        f = _reading_facts(a)
        self.assertEqual(f["words"], 450)
        self.assertEqual(f["read_min"], 3)
        self.assertEqual(f["latency"], "4m")
        self.assertEqual(f["domain"], "example.com")
        self.assertEqual(f["text_kind"], "full text")
        bare = _reading_facts(_article(url="https://x.io/b"))
        self.assertIsNone(bare["words"])
        self.assertIsNone(bare["read_min"])
        self.assertIsNone(bare["latency"])

    # ---------------------------------------------------------- page
    def test_the_full_page_renders_every_section(self):
        inst = _instrument("NDP1")
        a = _article(ai_summary="The Federal Reserve held rates steady.",
                     ai_sentiment_score=0.4, ai_urgency="high")
        a.ai_affected_instruments.add(inst)
        sib = _article(title="Sibling report", ai_sentiment_score=-0.5,
                       ai_urgency="critical")
        sib.ai_affected_instruments.add(inst)
        resp = self.client.get(f"/news/{a.id}/")
        self.assertEqual(resp.status_code, 200)
        for marker in ('id="nd-keywords"', "Federal Reserve", 'id="nd-reaction"',
                       'id="nd-sentiment-ctx"', 'id="nd-coverage"',
                       "Sibling report", "nd-dot-down", "nd-rel-urg badge-critical",
                       "example.com", "BULLISH"):
            self.assertContains(resp, marker)

    def test_an_empty_article_renders_with_dashes_and_no_zeros(self):
        a = _article(title="Untitled wire", url="https://x.io/e")
        resp = self.client.get(f"/news/{a.id}/")
        self.assertEqual(resp.status_code, 200)
        page = _page(resp)
        self.assertIn('class="sv-unknown"', page)
        # No instruments: no reaction table, coverage says so, and the
        # unscored sentiment card does not invent NEUTRAL 0.00.
        self.assertNotIn('id="nd-reaction"', page)
        self.assertIn("nothing to count coverage of", page)
        self.assertIn("not yet scored", page)
        self.assertNotIn("NEUTRAL", page)
        self.assertNotIn("0.00", page)
        self.assertNotIn("0 min", page)
        self.assertNotIn("0 words", page)
