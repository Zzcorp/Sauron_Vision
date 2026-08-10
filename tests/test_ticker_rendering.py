"""The global ticker renders a MIXED feed and must survive every item type.

Reported live as a 500 on /bot-backtest/:

    VariableDoesNotExist at /bot-backtest/
    Failed lookup for key [title] in {'type': 'quote', 'symbol': 'HGUSD', ...}

The cause is a Django subtlety worth remembering: the `default` filter
resolves its ARGUMENT eagerly, before deciding whether it is needed. So

    {{ item.symbol|default:item.title }}

looks up `item.title` even when `item.symbol` is present, and a quote dict
has no `title` key. Unlike a bare `{{ item.title }}` — which renders empty —
a failed lookup inside a filter argument propagates and 500s the page.

Every page extends base.html, so this took down the entire site the moment a
commodity quote reached the ticker. `fetch_commodity_quotes` writes six of
them, which is why it appeared now and not before.

`{% firstof %}` is the correct construct: it resolves with
ignore_failures=True and is built for exactly this.

Run with:  python manage.py test tests.test_ticker_rendering
"""
from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import TestCase


QUOTE = {"type": "quote", "symbol": "HGUSD", "price": "6.60800000",
         "change": 0.2579, "change_display": "+0.26%",
         "asset_class": "commodity", "url": "/instruments/HGUSD/"}
NEWS = {"type": "news", "title": "Copper rallies", "source": "Reuters",
        "summary": "s", "published_at": "now", "url": "/news/"}
SIGNAL = {"type": "signal", "symbol": "BTCUSD", "title": "BTC long",
          "direction": "bullish", "score": "0.90", "urgency": "high",
          "url": "/signals/"}


class TickerItemRenderingTests(TestCase):
    def test_a_quote_without_a_title_renders(self):
        """The exact crash. A quote dict has no `title` key."""
        out = Template(
            "{% firstof item.symbol item.title %}"
        ).render(Context({"item": QUOTE}))
        self.assertEqual(out.strip(), "HGUSD")

    def test_the_old_construct_is_what_raised(self):
        """Pins the reason, so nobody reintroduces `default:` here thinking
        it is equivalent."""
        from django.template.base import VariableDoesNotExist
        with self.assertRaises(VariableDoesNotExist):
            Template("{{ item.symbol|default:item.title }}").render(
                Context({"item": QUOTE}))

    def test_an_item_with_only_a_title_still_renders(self):
        out = Template(
            "{% firstof item.symbol item.title %}"
        ).render(Context({"item": NEWS}))
        self.assertEqual(out.strip(), "Copper rallies")

    def test_every_feed_item_type_survives_the_real_template(self):
        """Render base.html's ticker block against one of each item type."""
        from django.template.loader import get_template
        user = User.objects.create_user(username="tick_u", password="x")
        self.client.force_login(user)
        tpl = get_template("base.html")
        # A smoke render is enough: a failed lookup inside a filter argument
        # raises during rendering, so no assertion beyond "it completed".
        html = tpl.render({"ticker_items": [QUOTE, NEWS, SIGNAL],
                           "user": user, "request": None})
        self.assertIn("HGUSD", html)


class TickerPageTests(TestCase):
    """Every page extends base.html, so a ticker bug is a site-wide outage.
    A commodity quote is the item that triggered it in production."""

    def setUp(self):
        self.user = User.objects.create_user(username="tick_page", password="x")
        self.client.force_login(self.user)

    def _commodity_quote(self):
        from decimal import Decimal
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        inst, _ = Instrument.objects.get_or_create(
            symbol="HGUSD", defaults={"name": "Copper",
                                      "asset_class": "commodity"})
        LiveQuote.objects.update_or_create(
            instrument=inst,
            defaults={"last": Decimal("6.608"), "change_pct": Decimal("0.2579")})

    def test_the_reported_page_loads_with_a_commodity_quote_in_the_ticker(self):
        self._commodity_quote()
        r = self.client.get("/bot-backtest/")
        self.assertEqual(r.status_code, 200)

    def test_the_dashboard_loads_too(self):
        self._commodity_quote()
        r = self.client.get("/")
        self.assertIn(r.status_code, (200, 302))
