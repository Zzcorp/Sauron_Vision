"""Winners / losers on the quotes page.

The market-anomaly alert links the operator at /quotes/ with several
instruments implicated, and the page it landed on had a sort but no bucket:
"which of these are down?" meant reading the whole universe row by row. The
page now takes ?movers=, and these pin the parts that quietly go wrong —
what each bucket contains, the order it arrives in, that an instrument with
no LiveQuote row is in neither bucket rather than silently a loser, and that
a stale or hand-typed value shows the board instead of 500ing.

Run with:  python manage.py test tests.test_quotes_filter
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase


def _quoted(symbol, change_pct, asset_class="stock"):
    """An instrument with a live quote at the given change."""
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst = Instrument.objects.create(
        symbol=symbol, name=symbol, asset_class=asset_class)
    LiveQuote.objects.create(
        instrument=inst, last=Decimal("100"),
        change_pct=Decimal(str(change_pct)), volume=1000, source="test")
    return inst


def _unquoted(symbol, asset_class="stock"):
    """An instrument the adapters have never priced — no LiveQuote row, so
    change_pct reaches the view as None rather than as a zero."""
    from instruments.models import Instrument
    return Instrument.objects.create(
        symbol=symbol, name=symbol, asset_class=asset_class)


class MoverBucketTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("movers_u"))
        _quoted("BIGUP", 8.5)
        _quoted("SMALLUP", 0.4)
        _quoted("FLAT", 0)
        _quoted("SMALLDOWN", -0.6)
        _quoted("BIGDOWN", -7.2)
        _unquoted("NOQUOTE")

    def _symbols(self, query=""):
        resp = self.client.get("/instruments/" + query, HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        return resp, [i["symbol"] for i in resp.context["items"]]

    def test_winners_holds_only_gainers_biggest_first(self):
        """The operator arrives from an alert wanting the interesting end,
        not the alphabet — so the bucket carries its own ordering."""
        _, symbols = self._symbols("?movers=winners")
        self.assertEqual(symbols, ["BIGUP", "SMALLUP"])

    def test_losers_holds_only_decliners_worst_first(self):
        """Same rule mirrored: the worst decliner leads, because that is the
        row the anomaly alert was about."""
        _, symbols = self._symbols("?movers=losers")
        self.assertEqual(symbols, ["BIGDOWN", "SMALLDOWN"])

    def test_flat_and_unpriced_rows_are_in_neither_bucket(self):
        """A quote that has not reported is not a loser. FLAT reported 0.00%
        and belongs to neither end either; NOQUOTE has no LiveQuote row at
        all, so its change renders as an em-dash and it sits both buckets
        out. Counting it as a loser would invent a decline nobody saw."""
        _, winners = self._symbols("?movers=winners")
        _, losers = self._symbols("?movers=losers")
        for symbol in ("FLAT", "NOQUOTE"):
            self.assertNotIn(symbol, winners)
            self.assertNotIn(symbol, losers)
        # ...and it is still on the board when no bucket is selected.
        _, everything = self._symbols()
        self.assertIn("NOQUOTE", everything)

    def test_the_strip_counts_the_split_and_names_the_unknowns(self):
        """GAINERS/LOSERS/NO DATA are counted before the bucket narrows the
        list, so switching to LOSERS cannot make the page claim there are
        zero gainers."""
        resp, _ = self._symbols("?movers=losers")
        self.assertEqual(resp.context["gainers"], 2)
        self.assertEqual(resp.context["losers"], 2)
        self.assertEqual(resp.context["unpriced"], 1)
        self.assertEqual(resp.context["shown"], 2)

    def test_an_unknown_change_renders_as_an_em_dash_not_a_zero(self):
        resp = self.client.get("/instruments/", HTTP_HOST="127.0.0.1")
        # The grid view carries data-instrument too, so scope to the table
        # body; index 2 skips the row's watchlist form and its CSRF blob.
        body = resp.content.decode().split("<tbody>")[1]
        row = body.split('data-instrument="NOQUOTE"')[2].split("</tr>")[0]
        self.assertIn("&mdash;", row)
        self.assertNotIn("0.00%", row)


class BadParameterTests(TestCase):
    """A truncated link, a typo, or an old bookmark is not something the
    operator can act on. The page owes them the whole board, not a 500 and
    not an empty table they would read as "nothing moved"."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("movers_bad_u"))
        _quoted("UPX", 3.0)
        _quoted("DOWNX", -3.0)

    def test_a_junk_value_falls_back_to_the_whole_board(self):
        for bad in ("gainers", "winner", "1", "", "winners; drop table"):
            with self.subTest(movers=bad):
                resp = self.client.get(
                    "/instruments/", {"movers": bad}, HTTP_HOST="127.0.0.1")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.context["movers"], "all")
                self.assertEqual(
                    sorted(i["symbol"] for i in resp.context["items"]),
                    ["DOWNX", "UPX"])

    def test_the_vocabulary_is_the_one_the_view_publishes(self):
        from dashboard.views import MOVER_BUCKETS
        self.assertEqual(set(MOVER_BUCKETS), {"all", "winners", "losers"})


class MoverControlRenderTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("movers_ui_u"))
        _quoted("UPY", 2.0)
        _quoted("DOWNY", -2.0)

    def _html(self, query=""):
        return self.client.get(
            "/instruments/" + query, HTTP_HOST="127.0.0.1"
        ).content.decode()

    def test_the_control_marks_the_active_bucket(self):
        """Without an active mark the pills are three links that all look
        alike and the operator cannot tell which slice they are reading."""
        html = self._html("?movers=losers")
        losers_pill = html.split("mv-pill mv-down")[1].split("</a>")[0]
        self.assertIn("btn-primary", losers_pill)
        self.assertIn('aria-current="true"', losers_pill)
        winners_pill = html.split("mv-pill mv-up")[1].split("</a>")[0]
        self.assertNotIn("btn-primary", winners_pill)
        self.assertNotIn("aria-current", winners_pill)

    def test_all_is_the_marked_bucket_by_default(self):
        html = self._html()
        all_pill = html.split('class="btn btn-sm mv-pill ')[1].split("</a>")[0]
        self.assertIn("btn-primary", all_pill)
        self.assertIn('aria-current="true"', all_pill)

    def test_the_bucket_survives_the_search_form_and_the_class_pills(self):
        """A reload, a search or an asset-class click must not silently drop
        the bucket — that is how an operator ends up reading the whole
        universe while believing they are still looking at the decliners."""
        html = self._html("?movers=winners")
        self.assertIn('<input type="hidden" name="movers" value="winners">',
                      html)
        stocks_href = html.split(">Stocks</a>")[0].rsplit("href=", 1)[1]
        self.assertIn("filter=stock", stocks_href)
        self.assertIn("movers=winners", stocks_href)

    def test_a_bucket_pill_drops_an_explicit_sort(self):
        """The bucket's own ordering is the point of clicking it; carrying a
        stale ?sort=name across would bury the biggest mover."""
        html = self._html("?sort=name")
        winners_href = html.split('mv-pill mv-up')[0].rsplit("href=", 1)[1]
        self.assertIn("movers=winners", winners_href)
        self.assertNotIn("sort=", winners_href)

    def test_an_explicit_sort_still_overrules_the_bucket_order(self):
        """The Sort By select is the operator saying otherwise, and it wins
        over the bucket's default — otherwise the control is a trap."""
        resp = self.client.get(
            "/instruments/", {"movers": "winners", "sort": "name"},
            HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.context["sort_by"], "name")
        self.assertEqual(resp.status_code, 200)


class QuotesEntryPointTests(TestCase):
    """/quotes/ is the URL the market-anomaly notification carries, and it
    bounces to the unified page. The bounce used to drop the query string,
    which would make every deep link into a bucket land unfiltered."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("movers_q_u"))

    def test_the_bounce_keeps_the_bucket(self):
        resp = self.client.get("/quotes/?movers=losers", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/instruments/?movers=losers")

    def test_the_bare_bounce_is_unchanged(self):
        resp = self.client.get("/quotes/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/instruments/")
