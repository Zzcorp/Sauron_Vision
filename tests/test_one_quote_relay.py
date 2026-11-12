"""ONE PRICE EVERYWHERE: the held relay (2026-11-12).

A held instrument's eToro price is read every 30 s by the quote beat (or
every 5-10 min for a stand-in, by the manage tick and the candle pass), and
before this reached no browser by push: the headband caught up on its 60 s
sweep, the Horde on its 20/60 s poll, the hero on its 15 s poll (measured:
up to a minute between two cells of one print). One display-only task now,
market_data.tasks.relay_held_quotes, every 10 s:

  * reads every open eToro row's symbols and the rule's answer for each
    (market_data.one_quote: the database only);
  * pushes, through the EXISTING quote_update handler, only the symbols
    whose value changed since its last push (dashboard.consumers
    .push_shown: the legacy fields plus the rule's payload under `q`);
  * sends no request to eToro or anyone else, and never raises.

Run with:  python manage.py test tests.test_one_quote_relay
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tests.one_quote_fixture import T, seed_measured, stamp


class _Layer:
    def __init__(self):
        self.sent = []

    async def group_send(self, group, message):
        self.sent.append((group, message))


def _no_network(*a, **k):
    raise AssertionError("the relay opened a connection")


class TheRelayTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("oq_relay", password="x")
        self.rows = seed_measured(self.user)
        self.layer = _Layer()
        for patch in (
                mock.patch("market_data.one_quote.now", return_value=T),
                mock.patch("channels.layers.get_channel_layer",
                           return_value=self.layer),
                mock.patch("requests.Session.request", _no_network),
                mock.patch("urllib.request.urlopen", _no_network),
                mock.patch("socket.create_connection", _no_network)):
            patch.start()
            self.addCleanup(patch.stop)

    def run_relay(self):
        from market_data.tasks import relay_held_quotes
        fn = relay_held_quotes
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        return fn()

    def test_it_pushes_each_held_symbol_once_then_only_changes(self):
        from market_data.one_quote import ALL, shown_many
        out = self.run_relay()
        self.assertEqual(out["held"], 3)
        self.assertEqual(out["sent"], 3)
        sent = {m["data"]["symbol"]: (g, m) for g, m in self.layer.sent}
        self.assertEqual(sorted(sent), ["AAPL", "EURUSD", "XAUUSD"])
        want = shown_many(["EURUSD"], user=ALL, now=T)["EURUSD"]
        group, msg = sent["EURUSD"]
        self.assertEqual(group, "dashboard_live")
        self.assertEqual(msg["type"], "quote_update", "the existing handler")
        self.assertEqual(msg["data"]["q"], want.payload())
        self.assertEqual(msg["data"]["price"], "1.08447")
        self.assertEqual(msg["data"]["source"], "etoro")
        self.assertEqual(msg["data"]["t"], int(T.timestamp() * 1000))

        self.layer.sent.clear()
        self.assertEqual(self.run_relay()["sent"], 0, "nothing changed")
        self.assertEqual(self.layer.sent, [])

        t = self.rows["EURUSD"]
        meta = dict(t.metadata)
        meta["venue_mark"] = stamp("1.08470", "1.08465", "1.08475", 2)
        t.metadata = meta
        t.save(update_fields=["metadata"])
        out = self.run_relay()
        self.assertEqual(out["sent"], 1)
        self.assertEqual(self.layer.sent[0][1]["data"]["q"]["p"], "1.08465")

    def test_nothing_held_nothing_sent(self):
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.update(status="CLOSED")
        self.assertEqual(self.run_relay(), {"held": 0, "sent": 0})
        self.assertEqual(self.layer.sent, [])

    def test_it_is_on_the_beat_every_ten_seconds(self):
        from config.celery import app
        beat = app.conf.beat_schedule["relay-held-quotes"]
        self.assertEqual(beat["task"], "market_data.tasks.relay_held_quotes")
        self.assertEqual(beat["schedule"], 10.0)
        self.assertLessEqual(beat["options"]["expires"], 10)

    def test_a_broken_layer_never_raises(self):
        class _Down:
            async def group_send(self, group, message):
                raise RuntimeError("down")
        with mock.patch("channels.layers.get_channel_layer",
                        return_value=_Down()):
            out = self.run_relay()
        self.assertEqual(out["held"], 3)
