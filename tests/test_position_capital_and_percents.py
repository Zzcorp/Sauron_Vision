"""Every price carries its percentage, and every position carries its cost.

Two things the positions table could not answer, on a page whose whole job
is answering them.

A price with no percentage beside it asks the operator to divide in their
head on every glance — and the answer they actually want (how far is my
stop, how far is my target, what has this done since I opened it) is the
one the raw number withholds.

And the CAPITAL was nowhere. The card behind the row had it, but the table
an operator scans did not, so "how much of my book is this position" could
not be answered by looking. 4,800 does not answer it either: the number
that does is the share of the pool it came out of.

Run with:  python manage.py test tests.test_position_capital_and_percents
"""
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

HOST = "127.0.0.1"


def _setup(user, *, side="BUY", entry="2400", mark="2500", stop="2350",
           target="2600", qty="2", capital="10000"):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol="XAUUSD",
        defaults={"name": "Gold", "asset_class": "commodity"})
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(mark), "source": "test"})
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="commodity", name="cap-bot",
        defaults={"capital": Decimal(capital)})
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="commodity", symbol="XAUUSD", side=side,
        qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=Decimal(stop), take_profit=Decimal(target),
        status="OPEN", paper=True,
        metadata={"initial_stop_loss": float(stop), "value_per_unit": 1.0})


class TableTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("cap_u", password="x")
        self.client.force_login(self.user)

    def _body(self, **kw):
        _setup(self.user, **kw)
        resp = self.client.get("/positions/", HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", "replace")

    def _attrs(self, body):
        return dict(re.findall(r'data-pos-([a-z-]+)="([^"]*)"', body))

    def test_the_table_has_a_capital_column(self):
        self.assertIn("<th class=\"num\">Capital</th>", self._body())

    def test_the_position_shows_what_it_ties_up(self):
        body = self._body()
        self.assertIn("4,800.00", body)

    def test_and_what_share_of_the_pool_that_is(self):
        """The number that actually answers "is this position big"."""
        body = self._body()
        self.assertIn("48% of pool", body)

    def test_the_share_is_absent_rather_than_invented_without_a_pool(self):
        """A legacy Position row belongs to no bot config and has no pool.
        A confident percentage over a denominator nobody set is worse than
        no percentage."""
        from dashboard.views import _pos_committed_pct
        self.assertEqual(_pos_committed_pct(4800.0, None), "")

    def test_the_mark_carries_its_move_since_entry(self):
        self.assertIn("4.17% since entry", self._body())

    def test_the_stop_and_target_carry_their_distance(self):
        body = self._body()
        self.assertIn("6.00% away", body)
        self.assertIn("4.00% away", body)

    def test_the_entry_is_labelled_the_reference_not_given_a_zero(self):
        """0.00% would be a measurement; "entry" is the truth."""
        body = self._body()
        self.assertIn(">entry<", body)

    def test_a_level_that_has_been_crossed_says_so(self):
        body = self._body(mark="2650")
        self.assertIn("THROUGH by", body)


class TheShortSideSignTests(TestCase):
    """The one place a price percentage and a P&L percentage must DISAGREE.

    On a short, a mark below entry is a fall that made money. Signing the
    price move with the P&L would have the card claim the market went up
    when it went down.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user("cap_s", password="x")
        self.client.force_login(self.user)

    def test_a_profitable_short_shows_a_negative_price_move(self):
        _setup(self.user, side="SELL", entry="2400", mark="2300",
               stop="2450", target="2200")
        body = self.client.get("/positions/", HTTP_HOST=HOST).content.decode(
            "utf-8", "replace")
        attrs = dict(re.findall(r'data-pos-([a-z-]+)="([^"]*)"', body))
        self.assertEqual(attrs["mark-pct"], "-4.17", "the market fell")
        self.assertEqual(attrs["pnl-pct"], "4.17", "and that made money")


class TheCardTests(TestCase):
    """The dwell card behind the row reads the same two numbers."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("cap_c", password="x")
        self.client.force_login(self.user)
        _setup(self.user)

    def test_the_row_carries_both_new_values_to_the_card(self):
        body = self.client.get("/positions/", HTTP_HOST=HOST).content.decode(
            "utf-8", "replace")
        attrs = dict(re.findall(r'data-pos-([a-z-]+)="([^"]*)"', body))
        self.assertEqual(attrs["mark-pct"], "4.17")
        self.assertEqual(attrs["committed-pct"], "48")

    def test_the_card_reads_no_key_the_row_does_not_write(self):
        """The two halves are a contract, and a renamed attribute is a
        silently blank cell rather than an error."""
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-position-card.js").read_text(encoding="utf-8")
        reads = set(re.findall(r'(?:val|num|flag)\(row, "([a-z-]+)"\)', js))
        body = self.client.get("/positions/", HTTP_HOST=HOST).content.decode(
            "utf-8", "replace")
        writes = set(re.findall(r'data-pos-([a-z-]+)=', body))
        self.assertEqual(reads - writes, set())

    def test_the_ladder_names_the_entry_as_the_reference(self):
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-position-card.js").read_text(encoding="utf-8")
        self.assertIn('"the reference"', js)

    def test_the_ledger_prints_the_share_of_the_pool(self):
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-position-card.js").read_text(encoding="utf-8")
        self.assertIn("% of the pool", js)
