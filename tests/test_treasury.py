"""TREASURY — where the money is, and whether the broker agrees.

capital_truth answers every capital question for ONE broker: the book.
With three wired venues that stopped being the operator's question, and
the answer lived in four pages and a shell. This is the one computation
(bot_program/broker_vision.vision) with two renderers, and these tests
hold the part that matters when the money is real: the DIVERGENCE between
what a broker says it holds and what the platform believes is open.

WHAT THEY CONFRONT

  * Unmeasured against zero, everywhere. A broker never read cannot be
    compared, and the view says so — because "nothing only at the broker"
    is the same sentence a flat account produces and means the opposite.
  * Live against paper. A paper row has no broker position by
    construction: it is counted apart and never compared, so venue
    discipline holds in the one view built to compare venues.
  * Recorded against inferred. A live row records the broker that carried
    it; older rows are attributed by today's routing rule, which is a
    GUESS when a flag has moved. Each row says which it is, and a test
    holds that the two do not read alike.
  * The page against the command. Both render the same function, so they
    cannot tell different stories — held by asserting the same fact
    through both.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bot_program.broker_vision import (brokers, divergence,
                                       platform_positions, routing, vision)
from bot_program.models import EtoroAccount, IBKRAccount, SaxoAccount

DASH = "—"

HELD_AAPL = {"symbol": "AAPL", "side": "BUY", "qty": 10.0, "avg_cost": 200.0,
             "market_price": 210.0, "market_value": 2100.0,
             "unrealized_pnl": 100.0, "currency": "USD", "sec_type": "STK"}
HELD_MSFT = dict(HELD_AAPL, symbol="MSFT", qty=5.0)


def a_saxo(user, *, flags=("stock",), equity=(50000.0, "EUR"), held=None,
           session=True):
    acct = SaxoAccount.objects.create(
        user=user, sim=False, label="Main",
        redirect_uri="https://h.example.net/brokers/saxo/callback/")
    acct.set_credentials("app", "secret")
    for cls in flags:
        setattr(acct, {"stock": "is_primary_for_stocks",
                       "forex": "is_primary_for_forex",
                       "commodity": "is_primary_for_commodity",
                       "crypto": "is_primary_for_crypto"}[cls], True)
    now = timezone.now()
    if session:
        acct.set_tokens("a", "r", now + timedelta(seconds=1200),
                        refresh_expires_at=now + timedelta(seconds=2400))
        acct.connected = True
    if equity is not None:
        acct.last_equity = Decimal(str(equity[0]))
        acct.last_equity_currency = equity[1]
        acct.last_equity_at = now
    if held is not None:
        acct.broker_positions = held
        acct.broker_positions_at = now
    acct.last_sync = now
    acct.save()
    return acct


def an_etoro(user, *, flags=("crypto",), equity=(2000.0, "USD"), held=None):
    acct = EtoroAccount.objects.create(user=user, demo=True, label="Main")
    acct.set_credentials("k", "u")
    for cls in flags:
        setattr(acct, {"stock": "is_primary_for_stocks",
                       "forex": "is_primary_for_forex",
                       "commodity": "is_primary_for_commodity",
                       "crypto": "is_primary_for_crypto"}[cls], True)
    now = timezone.now()
    if equity is not None:
        acct.last_equity = Decimal(str(equity[0]))
        acct.last_equity_currency = equity[1]
        acct.last_equity_at = now
    if held is not None:
        acct.broker_positions = held
        acct.broker_positions_at = now
    acct.save()
    return acct


def an_ibkr(user):
    acct = IBKRAccount.objects.create(user=user, port=4003)
    acct.set_credentials("U1234567")
    acct.username_enc, acct.password_enc = "x", "y"
    acct.save()
    return acct


def a_trade(user, symbol, *, paper=False, broker=None, asset_class="stock",
            qty=10.0, side="BUY"):
    from bot_program.asset_models import AssetBotConfig, AssetBotTrade
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, name=f"pool_{asset_class}",
        defaults={"asset_class": asset_class,
                  "mode": "paper" if paper else "live",
                  "symbols": [symbol], "capital": Decimal("10000"),
                  "base_currency": "EUR", "enabled": True})
    meta = {"broker": broker} if broker else {}
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal("200"), status="OPEN",
        paper=paper, metadata=meta)


def _fresh(user):
    return User.objects.get(pk=user.pk)


class EveryBrokerSideBySideTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tr_rows", password="x")

    def test_only_rows_that_exist_are_listed_in_precedence_order(self):
        an_etoro(self.user)
        a_saxo(self.user)
        rows = brokers(_fresh(self.user))
        self.assertEqual([r["kind"] for r in rows], ["saxo", "etoro"])
        self.assertNotIn("ibkr", [r["kind"] for r in rows])

    def test_an_unmeasured_equity_is_none_not_zero(self):
        """The whole house rule in one assertion: a keyed broker that has
        never been read is an em dash, and a broker read as flat is a 0."""
        a_saxo(self.user, equity=None, held=None)
        an_etoro(self.user, equity=(0.0, "USD"), held=[])
        rows = {r["kind"]: r for r in brokers(_fresh(self.user))}
        self.assertIsNone(rows["saxo"]["equity"])
        self.assertIsNone(rows["saxo"]["held_n"])
        self.assertEqual(rows["etoro"]["equity"]["value"], 0.0)
        self.assertEqual(rows["etoro"]["held_n"], 0)

    def test_the_book_is_marked_once(self):
        a_saxo(self.user, flags=("stock",))
        an_etoro(self.user, flags=("crypto",))
        rows = brokers(_fresh(self.user))
        self.assertEqual([r["kind"] for r in rows if r["is_book"]], ["saxo"])

    def test_the_session_line_speaks_each_venues_own_failure(self):
        a_saxo(self.user, session=False)
        rows = {r["kind"]: r for r in brokers(_fresh(self.user))}
        self.assertIn("never signed in", rows["saxo"]["session"])
        acct = SaxoAccount.objects.get(user=self.user)
        acct.mark_session_lost("HTTP 401 invalid_grant")
        acct.save()
        rows = {r["kind"]: r for r in brokers(_fresh(self.user))}
        self.assertIn("LOST", rows["saxo"]["session"])
        self.assertIn("invalid_grant", rows["saxo"]["session"])

    def test_a_stale_reading_is_flagged_not_hidden(self):
        acct = a_saxo(self.user)
        acct.last_equity_at = timezone.now() - timedelta(hours=3)
        acct.save()
        row = brokers(_fresh(self.user))[0]
        self.assertTrue(row["equity_stale"])
        self.assertGreater(row["equity"]["age_seconds"], 1900)


class RoutingTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tr_route", password="x")

    def test_a_contested_class_names_both_and_says_who_wins(self):
        a_saxo(self.user, flags=("stock",))
        an_etoro(self.user, flags=("stock",))
        by_class = {r["asset_class"]: r for r in routing(_fresh(self.user))}
        self.assertEqual(by_class["stock"]["winner"], "saxo")
        self.assertEqual(by_class["stock"]["claimants"], ["saxo", "etoro"])
        self.assertTrue(by_class["stock"]["contested"])

    def test_an_unclaimed_class_falls_to_the_default(self):
        rows = {r["asset_class"]: r for r in routing(self.user)}
        self.assertTrue(rows["crypto"]["by_default"])
        self.assertFalse(rows["crypto"]["contested"])
        self.assertEqual(rows["crypto"]["claimants"], [])


class PlatformPositionsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tr_plat", password="x")

    def test_paper_rows_are_counted_apart_never_listed(self):
        a_trade(self.user, "AAPL", paper=False, broker="saxo")
        a_trade(self.user, "BTCUSD", paper=True, asset_class="crypto")
        plat = platform_positions(_fresh(self.user))
        self.assertEqual([p["symbol"] for p in plat["live"]], ["AAPL"])
        self.assertEqual(plat["paper_n"], 1)

    def test_a_recorded_broker_is_not_read_as_an_inference(self):
        a_saxo(self.user, flags=("stock",))
        a_trade(self.user, "AAPL", broker="saxo")
        p = platform_positions(_fresh(self.user))["live"][0]
        self.assertEqual((p["broker"], p["attribution"]), ("saxo", "recorded"))

    def test_a_row_with_no_recorded_broker_is_attributed_by_the_rule(self):
        a_saxo(self.user, flags=("stock",))
        a_trade(self.user, "AAPL")            # no metadata["broker"]
        p = platform_positions(_fresh(self.user))["live"][0]
        self.assertEqual((p["broker"], p["attribution"]), ("saxo", "routing"))

    def test_a_recorded_broker_survives_a_flag_moving(self):
        """The reason the recording exists: the row says saxo even after the
        operator hands stocks to eToro, so the divergence compares it
        against the broker that actually holds it."""
        a_saxo(self.user, flags=())
        an_etoro(self.user, flags=("stock",))
        a_trade(self.user, "AAPL", broker="saxo")
        p = platform_positions(_fresh(self.user))["live"][0]
        self.assertEqual(p["broker"], "saxo")


class DivergenceTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tr_div", password="x")

    def test_a_broker_never_read_cannot_be_compared(self):
        a_saxo(self.user, held=None)
        a_trade(self.user, "AAPL", broker="saxo")
        d = divergence(_fresh(self.user))[0]
        self.assertFalse(d["known"])
        self.assertIn("never read", d["reason"])
        self.assertEqual(d["platform_n"], 1)
        self.assertEqual(d["only_broker"], [])
        self.assertEqual(d["only_platform"], [])

    def test_a_row_the_broker_does_not_report_is_platform_only(self):
        a_saxo(self.user, held=[HELD_AAPL])
        a_trade(self.user, "AAPL", broker="saxo")
        a_trade(self.user, "TSLA", broker="saxo")
        d = divergence(_fresh(self.user))[0]
        self.assertTrue(d["known"])
        self.assertEqual([p["symbol"] for p in d["only_platform"]], ["TSLA"])
        self.assertEqual([a["symbol"] for a in d["agree"]], ["AAPL"])

    def test_a_holding_no_row_claims_is_broker_only(self):
        a_saxo(self.user, held=[HELD_AAPL, HELD_MSFT])
        a_trade(self.user, "AAPL", broker="saxo")
        d = divergence(_fresh(self.user))[0]
        self.assertEqual([h["symbol"] for h in d["only_broker"]], ["MSFT"])

    def test_a_flat_broker_read_is_measured_and_agrees_with_no_rows(self):
        a_saxo(self.user, held=[])
        d = divergence(_fresh(self.user))[0]
        self.assertTrue(d["known"])
        self.assertEqual((d["only_broker"], d["only_platform"], d["agree"]),
                         ([], [], []))

    def test_a_paper_row_is_never_compared(self):
        a_saxo(self.user, held=[])
        a_trade(self.user, "AAPL", paper=True)
        d = divergence(_fresh(self.user))[0]
        self.assertEqual(d["only_platform"], [])
        self.assertEqual(d["platform_n"], 0)

    def test_symbols_are_compared_case_insensitively(self):
        a_saxo(self.user, held=[dict(HELD_AAPL, symbol="aapl")])
        a_trade(self.user, "AAPL", broker="saxo")
        d = divergence(_fresh(self.user))[0]
        self.assertEqual(len(d["agree"]), 1)
        self.assertEqual(d["only_platform"], [])


class TheVerdictTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tr_verdict", password="x")

    def test_a_platform_only_row_is_a_blocker_in_words(self):
        a_saxo(self.user, held=[])
        a_trade(self.user, "TSLA", broker="saxo")
        v = vision(_fresh(self.user))
        self.assertTrue(any("does NOT report" in b and "TSLA" in b
                            for b in v["blockers"]), v["blockers"])

    def test_positions_attributed_to_an_unread_broker_are_a_blocker(self):
        a_saxo(self.user, held=None)
        a_trade(self.user, "AAPL", broker="saxo")
        v = vision(_fresh(self.user))
        self.assertTrue(any("never been read" in b for b in v["blockers"]),
                        v["blockers"])

    def test_a_broker_only_holding_is_worth_reading_not_a_blocker(self):
        a_saxo(self.user, held=[HELD_AAPL])
        v = vision(_fresh(self.user))
        self.assertEqual(v["blockers"], [])
        self.assertTrue(any("no open platform row claims" in n
                            for n in v["notes"]), v["notes"])

    def test_no_broker_row_at_all_is_the_first_blocker(self):
        v = vision(self.user)
        self.assertTrue(any("No broker row exists" in b for b in v["blockers"]))

    def test_a_keyed_row_that_claims_nothing_leaves_no_book(self):
        a_saxo(self.user, flags=())
        v = vision(_fresh(self.user))
        self.assertIsNone(v["book"])
        self.assertTrue(any("no broker row is the book" in b.lower()
                            for b in v["blockers"]), v["blockers"])

    def test_a_contested_class_is_worth_reading(self):
        a_saxo(self.user, flags=("stock",))
        an_etoro(self.user, flags=("stock",))
        v = vision(_fresh(self.user))
        self.assertTrue(any("configuration mistake" in n for n in v["notes"]))


class TheCommandTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tr_cmd", password="x")

    def _run(self, **kw):
        out = StringIO()
        call_command("treasury", stdout=out, **kw)
        return out.getvalue()

    def test_it_refuses_when_no_user_has_a_broker_row(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._run()

    def test_every_section_and_the_verdict_print(self):
        a_saxo(self.user, held=[HELD_AAPL, HELD_MSFT])
        a_trade(self.user, "AAPL", broker="saxo")
        a_trade(self.user, "TSLA", broker="saxo")
        body = self._run(user="tr_cmd")
        for head in ("TREASURY", "1. THE BOOK", "2. EVERY BROKER",
                     "3. WHERE A NEW TRADE WOULD GO",
                     "4. POSITIONS THE PLATFORM BELIEVES ARE OPEN",
                     "5. WHAT EACH BROKER SAYS IT HOLDS",
                     "6. DIVERGENCE"):
            self.assertIn(head, body)
        self.assertIn("PLATFORM ONLY", body)
        self.assertIn("TSLA", body)
        self.assertIn("BROKER ONLY", body)
        self.assertIn("MSFT", body)
        self.assertIn("BLOCKERS", body)
        self.assertIn("no broker call", body)

    def test_unmeasured_prints_an_em_dash_and_flat_prints_words(self):
        a_saxo(self.user, equity=None, held=None)
        body = self._run(user="tr_cmd")
        self.assertIn(DASH, body)
        self.assertIn("never read", body)
        acct = SaxoAccount.objects.get(user=self.user)
        acct.broker_positions, acct.broker_positions_at = [], timezone.now()
        acct.save()
        self.assertIn("flat — measured, and zero", self._run(user="tr_cmd"))

    def test_an_unknown_user_is_an_error(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._run(user="nobody")

    def test_it_is_registered_read_only_and_runnable(self):
        from core import ops_commands
        entry = ops_commands.get("treasury")
        self.assertIsNotNone(entry)
        self.assertTrue(entry["read_only"])
        self.assertEqual(entry["category"], "read")
        self.assertIn("treasury", ops_commands.runnable_names())


class ThePageTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tr_page", password="x")

    def test_it_needs_a_login(self):
        self.assertNotEqual(self.client.get(reverse("treasury_page")).status_code,
                            200)

    def test_the_page_and_the_command_tell_the_same_story(self):
        a_saxo(self.user, held=[HELD_AAPL])
        a_trade(self.user, "TSLA", broker="saxo")
        self.client.login(username="tr_page", password="x")
        page = self.client.get(reverse("treasury_page"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "TREASURY")
        self.assertContains(page, "PLATFORM ONLY")
        self.assertContains(page, "TSLA")
        out = StringIO()
        call_command("treasury", user="tr_page", stdout=out)
        self.assertIn("TSLA", out.getvalue())
        self.assertIn("PLATFORM ONLY", out.getvalue())

    def test_the_rail_carries_it_with_a_glyph_nobody_else_uses(self):
        from pathlib import Path

        from django.conf import settings
        base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        self.assertIn("treasury_page", base)
        self.assertEqual(base.count("⛁"), 1)

    def test_a_user_with_no_broker_sees_the_blocker_not_a_crash(self):
        self.client.login(username="tr_page", password="x")
        page = self.client.get(reverse("treasury_page"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "No broker row exists")
