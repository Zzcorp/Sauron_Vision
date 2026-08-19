"""The market anomaly alert leads to the asset it is about.

"Market Anomaly Alert (7 severe)" named seven symbols in its body and then
linked to /quotes/ — the table of every quote on the platform, where the
operator had to hunt for the symbols the scan had already identified. The
producer knew them all along.

Two halves to the fix, both pinned here. `data["items"]` carries one row
per severe anomaly with its own asset link, so the detail card can offer
every underlying asset; and the notification's single url deep-links when
there is exactly ONE asset to lead to, keeping the list page when there
are several or when the symbol is not one we track — a deep link that
404s is worse than the list it replaced, which is why every url produced
here is asserted to resolve.

Run with:  python manage.py test tests.test_anomaly_deeplink
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import Resolver404, resolve


def _enable(*keys):
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    PlatformComponent.objects.filter(
        key__in=("platform_master",) + keys).update(is_enabled=True)


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(inst):
    from market_data.models import LiveQuote
    return LiveQuote.objects.create(
        instrument=inst, last=Decimal("100"), change_pct=Decimal("1.5"),
        volume=1000, source="test")


def _severe(symbol, description="volume 40x the 30d average", severity=9):
    return {"symbol": symbol, "type": "volume_spike",
            "description": description, "severity": severity}


class _StubAgent:
    """Stands in for the LLM. What the task does with an answer is the
    behaviour under test; how it obtained one is not."""

    anomalies: list = []

    def __init__(self, *args, **kwargs):
        pass

    def run(self, **kwargs):
        return {"anomalies": list(type(self).anomalies),
                "market_stress_level": 6}


def _scan(anomalies):
    """Run the real task against a scripted agent answer."""
    from ai_agents import tasks

    _StubAgent.anomalies = anomalies
    with mock.patch(
            "ai_agents.agents.anomaly_detector.AnomalyDetectorAgent",
            _StubAgent):
        return tasks.run_anomaly_detection()


def _assert_resolves(case, url, why):
    if not url:
        return
    try:
        resolve(url.split("?")[0])
    except Resolver404:  # pragma: no cover - the assertion message is the point
        case.fail(f"{why}: {url!r} does not resolve to any view")


class AnomalyAlertDestinationTests(TestCase):
    def setUp(self):
        _enable("agent_anomaly")
        self.user = User.objects.create_user("anomaly_op")
        _quote(_instrument("AAPL"))
        _quote(_instrument("TSLA"))

    def _notification(self):
        from alerts.models import Notification
        return Notification.objects.get(user=self.user)

    def test_one_severe_anomaly_lands_on_that_asset(self):
        """The whole complaint: the scan named the symbol, so the click
        must not start with a search for it."""
        _scan([_severe("AAPL")])
        self.assertEqual(self._notification().url, "/instruments/AAPL/")

    def test_several_severe_keep_the_list_destination(self):
        """Several assets share no single page, and /quotes/ is the table
        the scan itself read — an arbitrary one of the seven would be a
        worse answer than all of them."""
        _scan([_severe("AAPL"), _severe("TSLA")])
        self.assertEqual(self._notification().url, "/quotes/")

    def test_a_symbol_we_do_not_track_degrades_to_the_list(self):
        """/instruments/GME/ for an instrument that does not exist is a
        confident-looking 404. The alert is still worth sending."""
        _scan([_severe("GME")])
        n = self._notification()
        self.assertEqual(n.url, "/quotes/")
        self.assertEqual(n.data["items"][0]["label"], "GME",
                         "the asset is still named even when unlinkable")
        self.assertEqual(n.data["items"][0]["url"], "",
                         "no url beats a broken one")

    def test_every_severe_anomaly_becomes_its_own_linked_row(self):
        """This is what the one-line body had to throw away: which asset,
        what was seen, and where to look at it."""
        _scan([_severe("AAPL", "gap on no news", 8),
               _severe("TSLA", "spread blew out", 10)])
        items = self._notification().data["items"]
        self.assertEqual([i["label"] for i in items], ["AAPL", "TSLA"])
        self.assertEqual([i["url"] for i in items],
                         ["/instruments/AAPL/", "/instruments/TSLA/"])
        self.assertIn("gap on no news", items[0]["detail"])
        self.assertIn("8", items[0]["detail"],
                      "severity is the reason the row is in the alert at all")

    def test_a_symbol_the_scan_echoed_in_lower_case_still_links(self):
        """The symbols come back through an LLM, so their case is not
        ours to trust — and the link must carry the row's own spelling
        because that is what the route matches."""
        _scan([_severe("aapl")])
        self.assertEqual(self._notification().url, "/instruments/AAPL/")

    def test_the_data_reaches_every_users_row(self):
        """create_for_all fans one row out per user with bulk_create. A
        detail card that only worked for whoever came first in the query
        would be the same defect one layer down."""
        User.objects.create_user("anomaly_op2")
        inactive = User.objects.create_user("anomaly_op3")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        _scan([_severe("AAPL"), _severe("TSLA")])

        from alerts.models import Notification
        rows = list(Notification.objects.all())
        self.assertEqual(len(rows), 2, "active users only")
        for row in rows:
            self.assertEqual([i["label"] for i in row.data["items"]],
                             ["AAPL", "TSLA"])

    def test_the_fan_out_still_pushes_one_live_banner_per_user(self):
        """bulk_create fires no post_save, so the explicit push loop is the
        only thing raising the banner and moving the bell badge."""
        User.objects.create_user("anomaly_op4")
        with mock.patch("dashboard.consumers.push_eye_event") as push:
            _scan([_severe("AAPL")])
        pushed = [c.args[0].username for c in push.call_args_list]
        self.assertCountEqual(pushed, ["anomaly_op", "anomaly_op4"])

    def test_every_url_the_alert_produces_resolves(self):
        """A stored link that 404s is exactly the failure this alert
        already shipped once ("/market-data/"), and it survived a code fix
        because nothing asserted the destinations were real."""
        _scan([_severe("AAPL"), _severe("GME"), _severe("TSLA")])
        n = self._notification()
        _assert_resolves(self, n.url, "the notification's own url")
        for item in n.data["items"]:
            _assert_resolves(self, item["url"], f"item {item['label']}")

    def test_a_quiet_scan_writes_nothing(self):
        """Nothing severe means no notification — the deep-link work must
        not have turned the alert into a heartbeat."""
        from alerts.models import Notification
        out = _scan([_severe("AAPL", severity=3)])
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(out["notifications_sent"])


class AuditedProducerLinkTests(TestCase):
    """The same defect in the producers audited alongside the anomaly
    alert: each knew its object and linked to a list of every object."""

    def setUp(self):
        self.user = User.objects.create_user("producer_op")
        self.inst = _instrument("AAPL")

    def test_a_new_signal_leads_to_its_instrument(self):
        """A signal has no page of its own; its instrument's page carries
        the chart and lists this signal. /signals/ made the reader find
        the row the title had already named."""
        from signals.models import Signal
        sig = Signal.objects.create(
            instrument=self.inst, signal_type="technical", direction="bullish",
            urgency="high", title="Golden cross", description="d",
            rule_name="golden_cross", score=0.8,
            price_at_signal=Decimal("100"))

        from alerts.models import Notification
        from alerts.notify import notify_new_signal
        notify_new_signal(sig)
        n = Notification.objects.get(user=self.user)
        self.assertEqual(n.url, "/instruments/AAPL/")
        _assert_resolves(self, n.url, "new-signal notification")

    def test_breaking_news_leads_to_the_article(self):
        """The feed reorders on every scrape, so "top of /news/" stops
        being this article within the hour."""
        from django.utils import timezone
        from scraping.models import NewsArticle
        article = NewsArticle.objects.create(
            title="Fed cuts", source="Reuters",
            url="https://example.com/fed-cuts", published_at=timezone.now(),
            ai_urgency="critical")

        from alerts.models import Notification
        from alerts.notify import notify_critical_news
        notify_critical_news(article)
        n = Notification.objects.get(user=self.user)
        self.assertEqual(n.url, f"/news/{article.pk}/")
        _assert_resolves(self, n.url, "breaking-news notification")

    def test_a_bot_fill_leads_to_that_trades_forensics(self):
        """"Why did it just buy that?" is answered by the trade's own
        forensics page — the rule, the signals that voted, the gate
        decision. /asset-bots/ is the config list and answers none of it."""
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="ADL", mode="paper",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="OPEN", paper=True, rule_name="rule_a",
            composite_score=0.8, reason="r")

        from alerts.models import Notification
        from bot_program.notifications import notify_bot_fill_open
        notify_bot_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=trade.qty, entry_price=trade.entry_price,
            rule_name="rule_a", trade_id=trade.id)
        n = Notification.objects.get(user=self.user)
        self.assertEqual(n.url, f"/forensics/{trade.id}/")
        _assert_resolves(self, n.url, "bot-fill notification")

    def test_a_fill_with_no_trade_keeps_its_list_page(self):
        """Callers that cannot name the trade must not lose their link —
        the deep link is an upgrade, never a precondition."""
        from alerts.models import Notification
        from bot_program.notifications import notify_bot_fill_open
        notify_bot_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"))
        self.assertEqual(Notification.objects.get(user=self.user).url,
                         "/asset-bots/")

    def test_an_unknown_symbol_never_produces_a_plausible_404(self):
        """The link helper is what every producer leans on to decide
        whether an asset page exists."""
        from alerts.links import instrument_url
        self.assertEqual(instrument_url("AAPL"), "/instruments/AAPL/")
        self.assertEqual(instrument_url("NOT_A_SYMBOL"), "")
        self.assertEqual(instrument_url(""), "")
        # A slash ends the path segment, so the route cannot express this
        # pair at all — "" rather than a url that silently resolves to a
        # different view.
        _instrument("BTC/USD", asset_class="crypto")
        self.assertEqual(instrument_url("BTC/USD"), "")
