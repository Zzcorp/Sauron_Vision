"""THE SENTIMENT AGGREGATION READS THE RAW ROWS ONLY (2026-10-24).

scraping.tasks.aggregate_sentiment wrote a row with source "aggregated"
every hour and, the next hour, summed it with the raw StockTwits, Reddit
and TradingView rows of the last 24 hours: its own earlier sums came back
in, so the message volume and the bull and bear counts roughly doubled
every hour (the score stayed an average), until the integer column
refused the insert on Postgres.

Pinned here:
  * two runs over the same window give the same counts, and the counts
    are the raw rows' sums (neutral included);
  * an inflated aggregate already stored is never fed back;
  * a second run in the same clock hour rewrites that hour's row instead
    of adding a twin;
  * the readers read on purpose: the positioning map's crowd score and
    the news page take the fresh aggregate, else the newest raw read; the
    crowd_extreme and sentiment_snapshot conditions and the sentiment
    index read the raw rows unless a source is named;
  * the system map says so: the switch feeds no scanner condition, and
    its readers are people and agents (dashboard/views_topology.py);
  * `manage.py rebuild_sentiment_aggregates` is a dry run by default,
    rebuilds each stored aggregate from the raw rows of its own window
    with --apply, deletes one that has no raw row behind it, and drops
    them all with --drop --apply. It never touches a raw row.

Run with:  python manage.py test tests.test_sentiment_aggregation
"""
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

#: Larger than any sum the raw rows below can make: a stored aggregate
#: that the old code had inflated.
INFLATED = 2_000_000_000


def _inst(symbol):
    from instruments.models import Instrument
    return Instrument.objects.create(symbol=symbol, name=symbol,
                                     asset_class="stock", is_active=True,
                                     is_watchlist=True)


def _row(inst, at, *, source="stocktwits", score=0.4, volume=30, bull=20,
         bear=6, neutral=4):
    from scraping.models import SentimentSnapshot
    return SentimentSnapshot.objects.create(
        instrument=inst, source=source, timestamp=at, composite_score=score,
        volume=volume, bullish_count=bull, bearish_count=bear,
        neutral_count=neutral)


def _run(now):
    """One aggregation at `now`, past the component gate."""
    from scraping import tasks
    with mock.patch("django.utils.timezone.now", return_value=now):
        return tasks.aggregate_sentiment.__wrapped__.__wrapped__()


def _aggregates(inst):
    from scraping.models import SentimentSnapshot
    return list(SentimentSnapshot.objects
                .filter(instrument=inst, source="aggregated")
                .order_by("timestamp"))


def _counts(row):
    return (row.volume, row.bullish_count, row.bearish_count,
            row.neutral_count, round(row.composite_score, 6))


class TheAggregationIsIdempotentTests(TestCase):

    def setUp(self):
        # On the hour plus one minute, so +10 minutes stays in the hour.
        self.now = (timezone.now().replace(minute=1, second=0, microsecond=0)
                    - timedelta(days=1))
        self.inst = _inst("SAGG1")
        _row(self.inst, self.now - timedelta(minutes=30), score=0.6,
             volume=30, bull=20, bear=5, neutral=5)
        _row(self.inst, self.now - timedelta(hours=3), score=-0.2,
             volume=30, bull=5, bear=15, neutral=10)
        _row(self.inst, self.now - timedelta(hours=5), source="tradingview",
             score=0.5, volume=0, bull=0, bear=0, neutral=0)
        # Outside the 24-hour window: never counted.
        _row(self.inst, self.now - timedelta(hours=30), volume=999,
             bull=999, bear=999, neutral=999)
        self.raw = (60, 25, 20, 15, round((0.6 - 0.2 + 0.5) / 3, 6))

    def test_two_hourly_runs_over_the_same_rows_give_the_same_counts(self):
        _run(self.now)
        _run(self.now + timedelta(hours=1))
        first, second = _aggregates(self.inst)
        # The old code summed the first aggregate back in: 120, 50, 40.
        self.assertEqual(_counts(second), _counts(first))
        self.assertEqual(_counts(first), self.raw)

    def test_an_inflated_aggregate_already_stored_is_not_fed_back(self):
        _row(self.inst, self.now - timedelta(minutes=50), source="aggregated",
             score=0.9, volume=INFLATED, bull=INFLATED, bear=INFLATED,
             neutral=0)
        _run(self.now)
        newest = _aggregates(self.inst)[-1]
        self.assertEqual(_counts(newest), self.raw)

    def test_a_second_run_in_the_same_hour_rewrites_the_hours_row(self):
        _run(self.now)
        _run(self.now + timedelta(minutes=10))
        rows = _aggregates(self.inst)
        self.assertEqual(len(rows), 1)
        self.assertEqual(_counts(rows[0]), self.raw)
        self.assertEqual(rows[0].timestamp, self.now + timedelta(minutes=10))

    def test_the_run_says_how_many_it_aggregated(self):
        out = _run(self.now)
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["instruments_aggregated"], 1)


class TheReadersReadOnPurposeTests(TestCase):

    def setUp(self):
        self.now = timezone.now()
        self.inst = _inst("SAGG2")

    def test_the_crowd_score_takes_the_fresh_aggregate(self):
        from bot_program import positioning as P
        _row(self.inst, self.now - timedelta(minutes=5), score=0.9)
        _row(self.inst, self.now - timedelta(minutes=40),
             source="aggregated", score=0.2, volume=60)
        s = P.crowd_read("SAGG2", "stock")["components"]["sentiment"]
        self.assertEqual((s["source"], s["score"]), ("aggregated", 0.2))

    def test_a_stale_aggregate_gives_way_to_the_newest_raw_read(self):
        from bot_program import positioning as P
        _row(self.inst, self.now - timedelta(hours=1), score=-0.3)
        _row(self.inst, self.now - timedelta(hours=6),
             source="aggregated", score=0.8)
        s = P.crowd_read("SAGG2", "stock")["components"]["sentiment"]
        self.assertEqual((s["source"], s["score"]), ("stocktwits", -0.3))

    def test_the_news_page_takes_the_same_read(self):
        from dashboard.news_detail import _instrument_rows
        _row(self.inst, self.now - timedelta(minutes=5), score=0.9,
             bull=3, bear=1, neutral=0)
        _row(self.inst, self.now - timedelta(minutes=40),
             source="aggregated", score=0.2, volume=60, bull=25, bear=20,
             neutral=15)
        article = SimpleNamespace(published_at=self.now - timedelta(hours=2))
        row = _instrument_rows(article, [self.inst], now=self.now)[0]
        self.assertEqual((row["sent_source"], row["bull"], row["bear"],
                          row["neutral"]), ("aggregated", 25, 20, 15))

    def test_crowd_extreme_reads_the_raw_rows_unless_a_source_is_named(self):
        from signals.evaluators_advanced import _eval_crowd_extreme
        for i in range(5):
            _row(self.inst, self.now - timedelta(hours=i + 1), score=0.1 * i)
        for i in range(40):
            _row(self.inst, self.now - timedelta(hours=i + 1, minutes=30),
                 source="aggregated", score=0.2)
        out = _eval_crowd_extreme({"window": 30}, self.inst, self.now)
        self.assertFalse(out["matched"])
        self.assertEqual(out["details"]["reason"], "need 31 snapshots, got 5")
        named = _eval_crowd_extreme({"window": 30, "source": "aggregated"},
                                    self.inst, self.now)
        self.assertEqual(named["details"]["n_snapshots"], 40)

    def test_the_sentiment_snapshot_condition_reads_the_raw_rows(self):
        from signals.opportunity_scanner import _eval_sentiment_snapshot
        _row(self.inst, self.now - timedelta(hours=1), score=0.5)
        _row(self.inst, self.now - timedelta(hours=2), score=0.5)
        _row(self.inst, self.now - timedelta(minutes=30),
             source="aggregated", score=-1.0)
        out = _eval_sentiment_snapshot({"threshold": 0.3}, self.inst,
                                       self.now)
        self.assertTrue(out["matched"])
        self.assertEqual((out["details"]["n"], out["details"]["avg_score"]),
                         (2, 0.5))

    def test_the_sentiment_index_weighs_the_raw_rows_only(self):
        from signals.sentiment_index import SentimentIndex
        _row(self.inst, self.now - timedelta(hours=1), score=0.5, volume=10)
        _row(self.inst, self.now - timedelta(hours=2), score=-0.5, volume=30)
        _row(self.inst, self.now - timedelta(minutes=30),
             source="aggregated", score=1.0, volume=INFLATED)
        got = SentimentIndex()._social_sentiment(
            self.inst, self.now - timedelta(days=1))
        self.assertAlmostEqual(got, (0.5 * 10 - 0.5 * 30) / 40)


class TheMapSaysWhoReadsTheAggregateTests(TestCase):
    """The system map drew pipeline_sentiment_agg -> the opportunity
    scanner, true while the scanner's conditions read every row. They read
    the raw rows now, so switching the aggregation off changes no scanner
    condition and does change the crowd score: the map says that."""

    def test_the_wiring_has_no_scanner_edge_and_names_its_readers(self):
        from dashboard.views_topology import WIRING
        agg = WIRING["pipeline_sentiment_agg"]
        self.assertEqual(agg["feeds"], [])
        self.assertEqual(agg["pages"], ["/instruments/", "/news/"])
        for words in ("crowd score", "the council", "the position review",
                      "the news page", "read the raw rows"):
            self.assertIn(words, agg["note"])
        # The raw reads still reach the scanner, from their own scrapers.
        self.assertIn("pipeline_opportunity_scanner",
                      WIRING["scraper_sentiment"]["feeds"])

    def test_the_map_lists_it_as_read_by_people_not_an_orphan(self):
        from django.contrib.auth.models import User

        from dashboard.views_topology import build_topology
        call_command("seed_components", verbosity=0)
        topo = build_topology(User.objects.create_user(
            "agg_map", password="x", is_staff=True))
        self.assertFalse([e for e in topo["edges"]
                          if e["from"] == "pipeline_sentiment_agg"])
        self.assertNotIn("pipeline_sentiment_agg", topo["orphans"])
        readers = {h["key"]: h["pages"] for h in topo["human_read"]}
        self.assertEqual(readers["pipeline_sentiment_agg"],
                         ["/instruments/", "/news/"])


class TheRebuildCommandTests(TestCase):

    def setUp(self):
        self.now = timezone.now()
        self.inst = _inst("SAGG3")
        _row(self.inst, self.now - timedelta(hours=2), score=0.6, volume=30,
             bull=20, bear=5, neutral=5)
        _row(self.inst, self.now - timedelta(hours=4), score=-0.2,
             volume=30, bull=5, bear=15, neutral=10)
        # Inflated, with raw rows in its window.
        self.kept = _row(self.inst, self.now - timedelta(hours=1),
                         source="aggregated", score=0.7, volume=INFLATED,
                         bull=INFLATED, bear=INFLATED, neutral=0)
        # Inflated, two days on: no raw row in its own window, so the fixed
        # aggregation would never have written it.
        self.orphan = _row(self.inst, self.now + timedelta(days=2),
                           source="aggregated", score=0.1, volume=INFLATED,
                           bull=INFLATED, bear=INFLATED, neutral=0)

    def call(self, *args):
        out = StringIO()
        call_command("rebuild_sentiment_aggregates", *args, stdout=out)
        return out.getvalue()

    def test_the_default_is_a_dry_run_that_changes_nothing(self):
        from scraping.models import SentimentSnapshot
        before = list(SentimentSnapshot.objects.order_by("pk").values())
        text = self.call()
        self.assertEqual(list(SentimentSnapshot.objects.order_by("pk")
                              .values()), before)
        self.assertIn("Dry run", text)
        self.assertIn("2 aggregated rows", text)
        self.assertIn("1 would be rebuilt", text)
        self.assertIn("1 would be deleted", text)
        self.assertIn("--apply", text)

    def test_apply_rebuilds_from_the_raw_rows_of_its_own_window(self):
        from scraping.models import SentimentSnapshot
        self.call("--apply")
        self.kept.refresh_from_db()
        self.assertEqual(_counts(self.kept), (60, 25, 20, 15, 0.2))
        self.assertFalse(SentimentSnapshot.objects.filter(
            pk=self.orphan.pk).exists())
        self.assertEqual(SentimentSnapshot.objects.exclude(
            source="aggregated").count(), 2)

    def test_drop_apply_deletes_every_aggregate_and_no_raw_row(self):
        from scraping.models import SentimentSnapshot
        text = self.call("--drop")
        self.assertIn("2 would be deleted", text)
        self.assertEqual(SentimentSnapshot.objects.count(), 4)
        self.call("--drop", "--apply")
        self.assertFalse(SentimentSnapshot.objects.filter(
            source="aggregated").exists())
        self.assertEqual(SentimentSnapshot.objects.count(), 2)
