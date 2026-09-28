"""saxo_smoke: three states per read, no order ever, no web lane.

  * It refuses to run without a registered application or a live session
    — and says which, without touching Saxo.
  * Each read is reported ok / refused / unknown: a SaxoApiError is
    Saxo's own no; anything else is 'unknown' and says so, because an
    adapter bug read as "your keys are refused" is the misdiagnosis this
    command exists to prevent.
  * Nothing in it can place an order, and the ops page cannot run it.
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from bot_program.engine.saxo_client import SaxoApiError, SaxoAuthError
# Imported BEFORE any patch replaces the module attribute, so the stub below
# can borrow the real arithmetic instead of inventing a second copy of it.
from bot_program.engine.saxo_client import SaxoTrader as _RealSaxoTrader
from bot_program.models import SaxoAccount


def _registered(user, session=True):
    acct = SaxoAccount.objects.create(user=user, redirect_uri="https://h/brokers/saxo/callback/")
    acct.set_credentials("app", "secret")
    if session:
        acct.set_tokens("acc", "ref", timezone.now() + timedelta(seconds=1200),
                        refresh_expires_at=timezone.now() + timedelta(seconds=2400))
        acct.connected = True
    acct.save()
    return acct


class _Stub:
    """A SaxoTrader that answers from a script."""

    # The command asks the adapter for the venue's own size floor. The
    # ARITHMETIC stays the real one — only the transport is stubbed — so the
    # smoke line exercises what ships, against the payload `resolve` below
    # returns. That payload carries neither LotSize nor MinimumTradeSize, so
    # the honest answer is UNMEASURED and the line reports ok.
    _size_floor = staticmethod(_RealSaxoTrader._size_floor)

    def __init__(self, acct):
        self.acct = acct

    def ping(self):
        return True

    def identity(self):
        return {"client_key": "CK", "account_id": "1INET", "currency": "EUR",
                "netting_profile": "FifoEndOfDay", "netting_mode": "EndOfDay",
                "account_key": "AK"}

    def net_liquidation(self):
        return (100000.0, "EUR")

    def resolve(self, symbol):
        return (21, "FxSpot", {"SupportedOrderTypes": ["Market", "Limit", "Stop"]})

    def ticker(self, symbol):
        raise SaxoApiError(400, "InvalidUic", "Uic must be greater than 0", "c#1")

    def klines(self, symbol, interval, limit):
        raise RuntimeError("boom — the adapter's own bug")

    def order_book(self, symbol, limit):
        return {"bids": [["1.1", "1000000"]], "asks": [["1.2", "1000000"]]}

    def get_positions(self):
        raise SaxoAuthError(401, "Unauthorized", "bearer refused", "")

    def broker_portfolio(self):
        return None

    def _get(self, path, params=None):
        return {"Data": []}


class SmokeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("smoke_u", password="x")

    def _run(self, **kw):
        out = StringIO()
        call_command("saxo_smoke", user="smoke_u", stdout=out, **kw)
        return out.getvalue()

    def test_no_application_means_no_call_to_saxo(self):
        with mock.patch("bot_program.engine.saxo_client.SaxoTrader") as trader:
            with self.assertRaises(CommandError) as cm:
                self._run()
        self.assertIn("Register Saxo Application", str(cm.exception))
        trader.assert_not_called()

    def test_no_session_means_sign_in_first(self):
        _registered(self.user, session=False)
        with mock.patch("bot_program.engine.saxo_client.SaxoTrader") as trader:
            with self.assertRaises(CommandError) as cm:
                self._run()
        self.assertIn("Connect Saxo", str(cm.exception))
        trader.assert_not_called()

    def test_three_states_are_told_apart_and_tallied(self):
        _registered(self.user)
        with mock.patch("bot_program.engine.saxo_client.SaxoTrader", _Stub):
            body = self._run()
        self.assertIn("ok       ping", body)
        self.assertIn("FifoEndOfDay/EndOfDay", body)
        self.assertIn("100,000.00 EUR", body)
        self.assertIn("refused  ticker EURUSD", body)
        self.assertIn("InvalidUic", body)
        self.assertIn("unknown  klines EURUSD", body)
        self.assertIn("RuntimeError: boom", body)
        self.assertIn("unknown  get_positions", body)
        self.assertIn("sign in again", body)
        self.assertIn("synthetic", body)
        self.assertIn("unreadable", body)
        self.assertIn("ok · 1 refused by Saxo · 2 unknown", body)
        self.assertIn("NOT Saxo saying no", body)
        self.assertIn("No order was placed", body)

    def test_it_is_registered_but_never_web_runnable(self):
        from core import ops_commands
        entry = ops_commands.get("saxo_smoke")
        self.assertIsNotNone(entry)
        self.assertTrue(entry["read_only"])
        self.assertFalse(ops_commands.is_runnable(entry))
        self.assertNotIn("saxo_smoke", ops_commands.runnable_names())

    def test_nothing_in_the_command_can_place_an_order(self):
        from pathlib import Path

        from bot_program.management.commands import saxo_smoke
        src = Path(saxo_smoke.__file__).read_text(encoding="utf-8")
        for word in ("market_order", "close_position", "trade/v2/orders",
                     "modify_protective", "modify_target", "cancel_order"):
            self.assertNotIn(word, src, word)
