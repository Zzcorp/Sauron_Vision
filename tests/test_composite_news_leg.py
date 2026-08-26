"""The composite bot score's news leg had never scored anything.

`_score_news` opened with `from scraping.models import NewsItem`. No such
model has ever existed — the news table is `NewsArticle` — so the ImportError
went into the function's bare except and the leg returned a flat 0 for every
symbol on every bar. A config that authored 0.3 of its weight to news was
therefore damping its own composite by that whole 0.3 toward zero and taking
fewer entries than it was configured for, with no log line at any level. The
v2 backtester calls the same function, so a backtest could not reveal it
either.

Run with:  python manage.py test tests.test_composite_news_leg
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone


def _article(title, sentiment, *, hours_ago=1, summary=""):
    from scraping.models import NewsArticle
    return NewsArticle.objects.create(
        title=title, source="test",
        url=f"https://example.test/{abs(hash((title, sentiment)))}",
        published_at=timezone.now() - timedelta(hours=hours_ago),
        content_summary=summary, ai_sentiment_score=sentiment,
    )


def _bars(n=80, start=100.0):
    """n rising [open, high, low, close, volume] bars."""
    out = []
    px = start
    for _ in range(n):
        out.append([px, px + 1, px - 1, px + 0.5, 1000.0])
        px += 0.5
    return out


class NewsLegTests(TestCase):
    def test_bullish_news_scores_the_symbol_bullish(self):
        from bot_program.engine.strategy import _score_news
        _article("AAPL beats on earnings", 0.8)
        _article("Analysts raise AAPL targets", 0.6)

        score, reasons = _score_news("AAPL")

        self.assertGreater(score, 0)
        self.assertTrue(reasons)

    def test_bearish_news_scores_the_symbol_bearish(self):
        from bot_program.engine.strategy import _score_news
        _article("AAPL supply chain halted", -0.7)

        score, _ = _score_news("AAPL")

        self.assertLess(score, 0)

    def test_news_about_another_symbol_is_not_this_symbols_news(self):
        from bot_program.engine.strategy import _score_news
        _article("TSLA recalls a million cars", -0.9)

        self.assertEqual(_score_news("AAPL"), (0, []))

    def test_an_ungraded_article_is_unmeasured_not_neutral(self):
        """A story the analyst has not scored yet must not drag the leg
        toward zero — it simply is not evidence."""
        from bot_program.engine.strategy import _score_news
        _article("AAPL something happened", None)

        self.assertEqual(_score_news("AAPL"), (0, []))

    def test_stale_news_is_out_of_the_window(self):
        from bot_program.engine.strategy import _score_news
        _article("AAPL beats on earnings", 0.9, hours_ago=48)

        self.assertEqual(_score_news("AAPL"), (0, []))

    def test_the_summary_counts_as_naming_the_symbol(self):
        from bot_program.engine.strategy import _score_news
        _article("Chipmaker cuts guidance", -0.6,
                 summary="The warning hit AAPL suppliers hardest")

        score, _ = _score_news("AAPL")
        self.assertLess(score, 0)


class CompositeTests(TestCase):
    def test_authored_news_weight_actually_moves_the_decision(self):
        """The whole point of the leg: a config that puts weight on news
        gets a different answer when the news changes. With the import
        broken this returned HOLD no matter what was in the table."""
        from bot_program.engine.strategy import decide
        _article("AAPL beats on earnings", 0.9)

        d = decide("AAPL", _bars(), {}, {"news": 1.0},
                   entry_min=0.6, exit_max=0.2)

        self.assertEqual(d.direction, "BUY")
        self.assertGreater(d.score, 0.6)

    def test_no_news_leaves_the_leg_at_zero(self):
        from bot_program.engine.strategy import decide
        d = decide("AAPL", _bars(), {}, {"news": 1.0},
                   entry_min=0.6, exit_max=0.2)
        self.assertEqual(d.direction, "HOLD")
