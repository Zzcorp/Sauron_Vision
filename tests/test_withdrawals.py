"""Withdrawals asked for in advance — held back first, never read as a loss.

The operator and Gandalf, 2026-09-28: a page where either of them can file,
ahead of time, a request to take money out of the real account WITHOUT
upsetting the portfolio — no forced sale, no change to the pools' shares,
the bots keep trading their plan; the platform only stops deploying the
reserved amount and lets cash build up as positions close.

Pinned here:
  * the request: who asks, a positive amount of money, the account's
    currency (USD only when no reading exists, said so), refused past
    the account, warned past half of it; cancel and mark-paid act on a
    reserved request only, once;
  * the arithmetic: the reserve is the sum of reserved requests; a paid
    withdrawal is a flow, taken off every reading made before it;
  * the sizing: _follow_the_account takes the reserve off the reading
    ONCE — every follower shrinks by the same proportion, shares stay,
    nothing closes, typed and paper pools are untouched; arming the
    manual lane takes it off too; the eToro cash gate refuses an order
    that would need the reserved cash;
  * the history: a 20% withdrawal marked paid is not a drawdown, not a
    shock and not a governor cut — and the same drop without it still is;
  * the page: login, owner scope, the PIN on every act, POST-redirect-GET,
    an empty database renders with em dashes;
  * the message: one per act, kind "withdrawal", never raising;
  * what the review of 2026-09-28 found: the eToro gate holds only the
    book's own reserve, in the cash's own currency; marking paid refuses
    an amount larger than the account, asks the time when the sync has
    already read the money gone, and wants a tick for an amount or a time
    the readings contradict; a paid row can be corrected, PIN in hand; a
    fallback USD request filed before any reading still counts as a flow
    once the account reads in EUR; the Follow button and `manage.py
    follow` size from the reading less the hold and quote what they
    wrote; the page shows a pool that trades elsewhere as not retuned,
    exactly as the sync skips it; and, from the second pass, a time typed
    before the latest reading while it still holds the money needs the
    tick too, and the flow is then held back from that reading, as a
    blank "now" would be, until the next one.

Run with:  python manage.py test tests.test_withdrawals
"""
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

PIN = "4321"


def _user(name="wd_u"):
    return get_user_model().objects.create_user(name, password="x")


def _pin(user, pin=PIN):
    from django.contrib.auth.hashers import make_password
    from portfolio.trader_profile import TraderProfile
    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.access_pin_hash = make_password(pin)
    prof.save(update_fields=["access_pin_hash"])


def _ibkr_book(user, value="1000", currency="EUR", *, age_seconds=0):
    """An IBKR row that is the book, with a stored reading."""
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, label="ISA", host="ibgateway",
                                      port=4003, client_id=1)
    acct.set_credentials("U1234567")
    if value is not None:
        acct.last_equity = Decimal(value)
        acct.last_equity_currency = currency
        acct.last_equity_at = timezone.now() - timedelta(seconds=age_seconds)
    acct.save()
    return acct


def _stamp(acct, value, currency="EUR", *, age_seconds=0):
    acct.last_equity = Decimal(str(value))
    acct.last_equity_currency = currency
    acct.last_equity_at = timezone.now() - timedelta(seconds=age_seconds)
    acct.save()


def _reading(acct, value, *, hours_ago, currency="EUR"):
    from bot_program.models import BrokerEquityReading
    return BrokerEquityReading.objects.create(
        account=acct, value=Decimal(str(value)), currency=currency,
        env="live", at=timezone.now() - timedelta(hours=hours_ago))


def _cfg(user, *, name, asset_class="stock", mode="live", capital="100",
         tracks=False, share=None, symbols=None, currency="EUR"):
    from bot_program.models import AssetBotConfig
    extras = {}
    if tracks:
        extras["capital_tracks_broker"] = True
    if share is not None:
        extras["account_share_pct"] = share
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=list(symbols if symbols is not None else []),
        capital=Decimal(capital), base_currency=currency, enabled=True,
        extras=extras)


def _wr(user, amount, *, status="reserved", currency="EUR", paid_at=None,
        paid_amount=None, who="operator", assumed=False, held_through=None):
    from bot_program.models import WithdrawalRequest
    return WithdrawalRequest.objects.create(
        user=user, requested_by=who, amount=Decimal(str(amount)),
        currency=currency, currency_assumed=assumed, status=status,
        paid_at=paid_at, held_through=held_through,
        paid_amount=(Decimal(str(paid_amount)) if paid_amount is not None
                     else None))


class _Quiet(TestCase):
    """Every act sends one message; these tests are not about it."""

    def setUp(self):
        cache.clear()
        p = patch("bot_program.notifications.dispatch_notification",
                  return_value=True)
        self.dispatch = p.start()
        self.addCleanup(p.stop)


# ── 1. The request ───────────────────────────────────────────────────────

class TheRequestTests(_Quiet):

    def setUp(self):
        super().setUp()
        self.user = _user("wd_req")

    def _create(self, **kw):
        from bot_program.withdrawals import create_request
        args = dict(requested_by="gandalf", amount="200")
        args.update(kw)
        return create_request(self.user, **args)

    def test_a_request_reserves_the_amount_in_the_accounts_currency(self):
        # a date in the FUTURE, relative to today: the literal "2026-10-05"
        # this test carried became "already past" at midnight on 2026-10-06
        # and failed every suite from then on (a wanted-by date in the past
        # is accepted with a warning, which the last assertion refuses)
        from datetime import date, timedelta
        soon = (date.today() + timedelta(days=30)).isoformat()
        _ibkr_book(self.user, "1000", "EUR")
        out = self._create(wanted_by=soon, reason="Roof repair")
        self.assertTrue(out.get("ok"), out)
        wr = out["request"]
        self.assertEqual(wr.status, "reserved")
        self.assertEqual(wr.amount, Decimal("200.00"))
        self.assertEqual(wr.currency, "EUR")
        self.assertEqual(wr.requested_by, "gandalf")
        self.assertEqual(str(wr.wanted_by), soon)
        self.assertEqual(out["warnings"], [])

    def test_no_reading_records_usd_and_says_so(self):
        out = self._create()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["request"].currency, "USD")
        self.assertTrue(any("No account reading" in w and "USD" in w
                            for w in out["warnings"]), out["warnings"])

    def test_what_is_not_an_amount_is_refused_and_writes_nothing(self):
        from bot_program.models import WithdrawalRequest
        _ibkr_book(self.user)
        for bad, words in (("0", "more than zero"), ("-5", "more than zero"),
                           ("abc", "not an amount"), ("", "missing"),
                           ("10.001", "two decimals"), ("NaN", "finite"),
                           ("Infinity", "finite")):
            with self.subTest(bad):
                out = self._create(amount=bad)
                self.assertIn("error", out)
                self.assertIn(words, out["error"])
                self.assertIn("Nothing was reserved", out["error"])
        self.assertEqual(WithdrawalRequest.objects.count(), 0)

    def test_a_french_or_grouped_amount_is_read_as_money(self):
        from bot_program.withdrawals import parse_amount
        self.assertEqual(parse_amount("1 234,56")[0], Decimal("1234.56"))
        self.assertEqual(parse_amount("1,234.56")[0], Decimal("1234.56"))
        self.assertEqual(parse_amount("250")[0], Decimal("250.00"))
        self.assertEqual(parse_amount("12,5")[0], Decimal("12.50"))
        amount, why = parse_amount("1,234")
        self.assertIsNone(amount)
        self.assertIn("two ways", why)

    def test_nobody_named_as_asking_is_refused(self):
        _ibkr_book(self.user)
        out = self._create(requested_by="sauron")
        self.assertIn("the operator or Gandalf", out["error"])

    def test_a_reserve_larger_than_the_account_is_refused_in_plain_words(self):
        from bot_program.models import WithdrawalRequest
        _ibkr_book(self.user, "1000", "EUR")
        self.assertTrue(self._create(amount="700").get("ok"))
        out = self._create(amount="400")
        self.assertIn("error", out)
        self.assertIn("1,100.00 EUR would be reserved in total", out["error"])
        self.assertIn("1,000.00 EUR", out["error"])
        self.assertIn("cannot be larger than the account", out["error"])
        self.assertEqual(WithdrawalRequest.objects.count(), 1)

    def test_more_than_half_the_account_is_accepted_with_a_warning(self):
        _ibkr_book(self.user, "1000", "EUR")
        out = self._create(amount="600")
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(any("60% of the account" in w
                            for w in out["warnings"]), out["warnings"])

    def test_a_past_wanted_by_date_is_accepted_with_a_warning(self):
        _ibkr_book(self.user)
        out = self._create(wanted_by="2020-01-01")
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(any("already past" in w for w in out["warnings"]))
        self.assertIn("error", self._create(wanted_by="05/10/2026"))

    def test_cancel_releases_a_reserved_request_once(self):
        from bot_program.withdrawals import cancel_request, reserved_total
        _ibkr_book(self.user)
        wr = self._create()["request"]
        out = cancel_request(self.user, wr.pk, acted_by="operator",
                             note="not needed")
        self.assertTrue(out.get("ok"), out)
        wr.refresh_from_db()
        self.assertEqual(wr.status, "cancelled")
        self.assertEqual(wr.acted_by, "operator")
        self.assertEqual(wr.closing_note, "not needed")
        self.assertIsNotNone(wr.cancelled_at)
        self.assertEqual(reserved_total(self.user), Decimal("0"))
        again = cancel_request(self.user, wr.pk, acted_by="operator")
        self.assertIn("already cancelled", again["error"])

    def test_mark_paid_defaults_to_the_amount_and_now(self):
        from bot_program.withdrawals import mark_paid
        _ibkr_book(self.user)
        wr = self._create()["request"]
        before = timezone.now()
        out = mark_paid(self.user, wr.pk, acted_by="gandalf")
        self.assertTrue(out.get("ok"), out)
        wr.refresh_from_db()
        self.assertEqual(wr.status, "paid")
        self.assertEqual(wr.paid_amount, Decimal("200.00"))
        self.assertGreaterEqual(wr.paid_at, before)
        self.assertEqual(wr.acted_by, "gandalf")
        self.assertIn("already withdrawn",
                      mark_paid(self.user, wr.pk, acted_by="gandalf")["error"])

    def test_mark_paid_takes_the_amount_and_moment_given(self):
        from bot_program.withdrawals import mark_paid
        _ibkr_book(self.user)
        wr = self._create()["request"]
        out = mark_paid(self.user, wr.pk, acted_by="operator",
                        paid_amount="195.50", paid_at="2026-09-01T10:30")
        self.assertTrue(out.get("ok"), out)
        wr.refresh_from_db()
        self.assertEqual(wr.paid_amount, Decimal("195.50"))
        self.assertEqual(wr.paid_at.isoformat(), "2026-09-01T10:30:00+00:00")

    def test_a_paid_time_in_the_future_or_a_bad_amount_changes_nothing(self):
        from bot_program.withdrawals import mark_paid
        _ibkr_book(self.user)
        wr = self._create()["request"]
        later = (timezone.now() + timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M")
        self.assertIn("in the future", mark_paid(
            self.user, wr.pk, acted_by="operator", paid_at=later)["error"])
        self.assertIn("more than zero", mark_paid(
            self.user, wr.pk, acted_by="operator", paid_amount="0")["error"])
        self.assertIn("the operator or Gandalf", mark_paid(
            self.user, wr.pk, acted_by="")["error"])
        wr.refresh_from_db()
        self.assertEqual(wr.status, "reserved")

    def test_another_users_request_cannot_be_acted_on(self):
        from bot_program.withdrawals import cancel_request, mark_paid
        other = _user("wd_other")
        wr = _wr(other, 100)
        self.assertIn("No such request", cancel_request(
            self.user, wr.pk, acted_by="operator")["error"])
        self.assertIn("No such request", mark_paid(
            self.user, wr.pk, acted_by="operator")["error"])
        wr.refresh_from_db()
        self.assertEqual(wr.status, "reserved")

    def test_a_failing_message_or_follow_never_breaks_the_request(self):
        from bot_program.withdrawals import create_request
        _ibkr_book(self.user)
        with patch("bot_program.notifications.notify_withdrawal",
                   side_effect=RuntimeError("telegram down")), \
                patch("bot_program.tasks._follow_the_account",
                      side_effect=RuntimeError("db hiccup")):
            out = create_request(self.user, requested_by="operator",
                                 amount="50")
        self.assertTrue(out.get("ok"), out)


# ── 2. The arithmetic ────────────────────────────────────────────────────

class TheArithmeticTests(TestCase):

    def setUp(self):
        self.user = _user("wd_math")

    def test_the_reserve_is_the_sum_of_reserved_requests_only(self):
        from bot_program.withdrawals import reserved_total
        self.assertEqual(reserved_total(self.user), Decimal("0"))
        _wr(self.user, "100.50")
        _wr(self.user, "49.50", who="gandalf")
        _wr(self.user, 1000, status="cancelled")
        _wr(self.user, 1000, status="paid", paid_at=timezone.now())
        _wr(_user("wd_math_other"), 777)
        self.assertEqual(reserved_total(self.user), Decimal("150.00"))

    def test_a_paid_flow_comes_off_every_reading_made_before_it(self):
        from bot_program.withdrawals import flow_adjusted_value, paid_flows
        now = timezone.now()
        _wr(self.user, 200, status="paid", paid_at=now - timedelta(hours=1),
            paid_amount=180)
        _wr(self.user, 50, status="paid", paid_at=now - timedelta(days=3))
        _wr(self.user, 999, status="reserved")       # not a flow
        _wr(self.user, 70, status="paid", currency="GBP",
            paid_at=now - timedelta(hours=2))
        flows = paid_flows(self.user, currency="EUR")
        self.assertEqual([a for _t, a in flows],
                         [Decimal("50.00"), Decimal("180.00")])
        self.assertEqual(
            flow_adjusted_value(1000.0, now - timedelta(days=5), flows), 770.0)
        self.assertEqual(
            flow_adjusted_value(1000.0, now - timedelta(hours=5), flows),
            820.0)
        self.assertEqual(flow_adjusted_value(800.0, now, flows), 800.0)
        self.assertEqual(
            flow_adjusted_value(Decimal("1000"), now - timedelta(days=5),
                                flows), Decimal("770.00"))
        self.assertEqual(flow_adjusted_value(5.0, now, []), 5.0)

    def test_what_is_held_back_counts_a_withdrawal_the_reading_still_holds(self):
        from bot_program.withdrawals import deployable, held_back
        now = timezone.now()
        _wr(self.user, 100)
        _wr(self.user, 300, status="paid", paid_at=now - timedelta(minutes=5))
        # a reading taken BEFORE the payment still counts the 300
        self.assertEqual(held_back(self.user, now - timedelta(minutes=10)),
                         Decimal("400.00"))
        # a reading taken after it does not
        self.assertEqual(held_back(self.user, now), Decimal("100.00"))
        self.assertEqual(held_back(self.user, None), Decimal("100.00"))
        base, held = deployable(self.user, 1000.0, reading_at=now)
        self.assertEqual((base, held), (Decimal("900.00"), Decimal("100.00")))
        base, _ = deployable(self.user, 50.0, reading_at=now)
        self.assertEqual(base, Decimal("0"))

    def test_a_flow_confirmed_early_is_held_through_the_reading_it_was_checked_against(
            self):
        # marked "at 10:00", ticked, while the 10:50 reading still showed
        # the money: the history reads the time typed, the hold reads the
        # reading it was checked against — held from it, and from every
        # earlier one, as a blank "now" would have been; not from a later
        from bot_program.withdrawals import (flow_adjusted_value, held_back,
                                             held_back_in, paid_flows)
        now = timezone.now()
        r_at = now - timedelta(minutes=5)
        _wr(self.user, 200, status="paid", paid_at=now - timedelta(hours=1),
            held_through=r_at)
        self.assertEqual(held_back(self.user, r_at), Decimal("200.00"))
        self.assertEqual(held_back(self.user, now - timedelta(hours=3)),
                         Decimal("200.00"))
        self.assertEqual(held_back(self.user, now), Decimal("0"))
        self.assertEqual(held_back_in(self.user, "EUR", r_at),
                         (Decimal("200.00"), {}))
        self.assertEqual(held_back_in(self.user, "EUR", now),
                         (Decimal("0"), {}))
        flows = paid_flows(self.user, currency="EUR")
        self.assertEqual(flow_adjusted_value(1000.0, r_at, flows), 1000.0)
        self.assertEqual(
            flow_adjusted_value(1000.0, now - timedelta(hours=2), flows),
            800.0)


# ── 3. The sizing ────────────────────────────────────────────────────────

class TheFollowShrinksEveryPoolTests(_Quiet):

    def setUp(self):
        super().setUp()
        self.user = _user("wd_follow")

    def test_every_follower_shrinks_by_the_same_proportion_and_keeps_its_share(
            self):
        from bot_program.models import AssetBotConfig
        from bot_program.tasks import _follow_the_account
        from tests.test_execution_trust import _trade
        manual = _cfg(self.user, name="manual", tracks=True)
        etf = _cfg(self.user, name="etf", tracks=True, share=30)
        typed = _cfg(self.user, name="typed", capital="150")
        paper = _cfg(self.user, name="paper", mode="paper", capital="5000")
        trade = _trade(etf, symbol="GLDM")
        _wr(self.user, 200)
        with self.assertLogs("bot_program.tasks", "INFO") as cm:
            _follow_the_account(self.user, 1000.0, "EUR")
        for c in (manual, etf, typed, paper):
            c.refresh_from_db()
        # 800 deployable: 70% / 30% of it, where 1,000 gave 700 / 300
        self.assertEqual(float(manual.capital), 560.0)
        self.assertEqual(float(etf.capital), 240.0)
        self.assertAlmostEqual(float(manual.capital) / 700.0,
                               float(etf.capital) / 300.0)
        self.assertEqual(etf.extras.get("account_share_pct"), 30)
        self.assertNotIn("account_share_pct", manual.extras)
        self.assertEqual(float(typed.capital), 150.0)     # not a follower
        self.assertEqual(float(paper.capital), 5000.0)    # follows nothing
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")             # nothing closes
        self.assertEqual(AssetBotConfig.objects.filter(enabled=True).count(),
                         4)
        log = "\n".join(cm.output)
        self.assertIn("200.00 EUR held back for withdrawal requests", log)
        self.assertIn("(200.00 held back for withdrawals)", log)

    def test_no_reserve_is_the_old_arithmetic_exactly(self):
        from bot_program.tasks import _follow_the_account
        manual = _cfg(self.user, name="manual", tracks=True)
        _follow_the_account(self.user, 412.5, "EUR")
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 412.5)

    def test_a_reserve_past_the_reading_floors_the_pools_at_zero(self):
        from bot_program.tasks import _follow_the_account
        manual = _cfg(self.user, name="manual", tracks=True)
        _wr(self.user, 900)
        _follow_the_account(self.user, 500.0, "EUR")
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 0.0)

    def test_an_unreadable_reserve_retunes_nothing(self):
        from bot_program.tasks import _follow_the_account
        manual = _cfg(self.user, name="manual", tracks=True, capital="123")
        with patch("bot_program.withdrawals.reserved_total",
                   side_effect=RuntimeError("db down")):
            _follow_the_account(self.user, 1000.0, "EUR")
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 123.0)

    def test_filing_cancelling_and_paying_re_size_the_pools_at_once(self):
        from bot_program.withdrawals import (cancel_request, create_request,
                                             mark_paid)
        acct = _ibkr_book(self.user, "1000", "EUR")
        manual = _cfg(self.user, name="manual", tracks=True, capital="1000")
        wr = create_request(self.user, requested_by="gandalf",
                            amount="250")["request"]
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 750.0)
        cancel_request(self.user, wr.pk, acted_by="gandalf")
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 1000.0)
        wr = create_request(self.user, requested_by="operator",
                            amount="400")["request"]
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 600.0)
        # Paid before the next sync: the stored reading still counts the
        # 400, so the pool must NOT grow back into money that has left.
        mark_paid(self.user, wr.pk, acted_by="operator")
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 600.0)
        # the sync then reads the account without it
        from bot_program.tasks import _follow_the_account
        _stamp(acct, "600")
        _follow_the_account(self.user, 600.0, "EUR")
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 600.0)


class ArmingTheManualLaneTakesTheReserveOffTests(_Quiet):

    def setUp(self):
        super().setUp()
        from tests.test_take_trade_live import (_components_on, _instrument,
                                                _quote)
        self.user = _user("wd_arm")
        _quote("BTCUSD", 60000)
        _instrument("BTCUSD", "crypto")
        _components_on()

    def _arm(self):
        from bot_program.manual_trade import arm_manual_lane
        from tests.test_take_trade_live import ROUTER
        with patch(ROUTER, return_value=type("IBKRTrader", (), {})()):
            return arm_manual_lane(self.user, asset_class="crypto",
                                   mode="live", pin_ok=True, track=True)

    def test_tracking_takes_its_share_of_the_reading_less_the_reserve(self):
        _ibkr_book(self.user, "500.00", "EUR")
        _wr(self.user, 100)
        out = self._arm()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["capital"], 400.0)

    def test_without_a_reserve_it_is_the_whole_reading(self):
        _ibkr_book(self.user, "500.00", "EUR")
        out = self._arm()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["capital"], 500.0)

    def test_an_unreadable_reserve_arms_nothing(self):
        _ibkr_book(self.user, "500.00", "EUR")
        with patch("bot_program.withdrawals.reserved_total",
                   side_effect=RuntimeError("db down")):
            out = self._arm()
        self.assertIn("withdrawal reserve could not be read", out["error"])
        from bot_program.manual_trade import manual_config_for
        self.assertEqual(manual_config_for(self.user, "crypto").mode, "paper")


class TheEtoroCashGateHoldsTheReserveTests(TestCase):

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.engine.etoro_client import EtoroTrader
        from tests.test_etoro_leverage import _account
        self.user = _user("wd_cash")
        self.cfg = _cfg(self.user, name="ET", symbols=["AAPL"],
                        currency="USD", capital="10000")
        _account(self.user, cash=1000, equity=100000)
        self.bot = StockBot(self.cfg)
        self.client_ = EtoroTrader("api-k", "user-k", env="demo")

    def _room(self, qty=6, price=100.0):
        return self.bot._leverage_headroom(self.client_, "AAPL", qty=qty,
                                           price=price, leverage=1)

    def test_without_a_reserve_the_cash_covers_the_order(self):
        self.assertIsNone(self._room())

    def test_the_reserved_cash_is_never_pledged(self):
        _wr(self.user, 500, currency="USD")
        why = self._room()           # 600 needed, 1,000 - 500 free
        self.assertIsNotNone(why)
        self.assertIn("needs 600.00 USD of margin and 500.00 is free", why)
        self.assertIn("less 500.00 held for withdrawals", why)
        self.assertIn("refused", why)
        self.assertIsNone(self._room(qty=4))    # 400 still fits

    def test_a_withdrawal_paid_since_the_cash_was_read_is_held_too(self):
        _wr(self.user, 500, currency="USD", status="paid",
            paid_at=timezone.now())
        self.assertIn("held for withdrawals", self._room())

    def test_an_unreadable_reserve_refuses(self):
        # held_back_in since the review: the gate reads the hold split by
        # currency, never the plain sum
        with patch("bot_program.withdrawals.held_back_in",
                   side_effect=RuntimeError("db down")):
            why = self._room()
        self.assertIn("withdrawal reserve could not be read", why)

    def test_a_hold_in_another_currency_is_refused_never_converted(self):
        _wr(self.user, 500, currency="EUR")
        why = self._room(qty=1)          # 100 USD would fit twice over
        self.assertIn("500.00 EUR is held for withdrawals against cash read "
                      "in USD — nothing here converts", why)
        self.assertIn("cancelled or filed again in USD", why)

    def test_an_assumed_currency_counts_as_the_cells_own(self):
        # filed before any reading: "USD" was a guess, and the cash cell
        # reads EUR — the hold is the account's money, in EUR
        from bot_program.models import EtoroAccount
        EtoroAccount.objects.filter(user=self.user).update(
            last_equity_currency="EUR")
        self.cfg.base_currency = "EUR"
        self.cfg.save(update_fields=["base_currency"])
        _wr(self.user, 500, currency="USD", assumed=True)
        why = self._room()
        self.assertIn("needs 600.00 EUR of margin and 500.00 is free", why)
        self.assertIn("less 500.00 held for withdrawals", why)


# ── 4. The history: a withdrawal is not a loss ───────────────────────────

class AWithdrawalIsNotALossTests(TestCase):
    """1,000 for days, 800 now. With a 200 withdrawal marked paid an hour
    ago, that is the same money, net: no drawdown, no 24 h drop, no shock,
    governor 1.00. Without it — or with it only reserved — it is a 20%
    fall, and every reader still says so."""

    def setUp(self):
        cache.clear()
        self.user = _user("wd_flow")
        self.acct = _ibkr_book(self.user, "1000", "EUR")
        _reading(self.acct, 1000, hours_ago=24 * 10)
        _reading(self.acct, 1000, hours_ago=12)
        _reading(self.acct, 1000, hours_ago=2)
        _stamp(self.acct, "800")

    def _readers(self):
        from bot_program.capital_desk import budget_for
        from bot_program.capital_truth import equity_drawdown
        from bot_program.share_allocator import (drop_24h, governor_for,
                                                 shock_detected)
        dd = equity_drawdown(self.user)
        return {"dd": dd["drawdown_pct"], "hwm": dd["hwm"],
                "drop": drop_24h(self.user),
                "shock": shock_detected(self.user),
                "governor": governor_for(dd["drawdown_pct"]),
                "desk_governor": budget_for(self.user, "live")["governor"]}

    def test_the_drop_without_a_withdrawal_is_still_a_drop(self):
        r = self._readers()
        self.assertAlmostEqual(r["dd"], 0.2)
        self.assertAlmostEqual(r["drop"], 0.2)
        self.assertTrue(r["shock"])
        self.assertAlmostEqual(r["governor"], 0.4)
        self.assertAlmostEqual(r["desk_governor"], 0.4)

    def test_a_reserve_that_has_not_left_is_still_a_drop(self):
        _wr(self.user, 200)
        r = self._readers()
        self.assertAlmostEqual(r["dd"], 0.2)
        self.assertTrue(r["shock"])

    def test_a_twenty_percent_withdrawal_marked_paid_is_not_a_loss(self):
        from bot_program.withdrawals import create_request, mark_paid
        with patch("bot_program.notifications.dispatch_notification"):
            wr = create_request(self.user, requested_by="gandalf",
                                amount="200")["request"]
            paid_at = (timezone.now() - timedelta(hours=1)).strftime(
                "%Y-%m-%dT%H:%M")
            self.assertTrue(mark_paid(self.user, wr.pk, acted_by="gandalf",
                                      paid_at=paid_at).get("ok"))
        r = self._readers()
        self.assertEqual(r["dd"], 0.0)
        self.assertEqual(r["hwm"], 800.0)       # in today's money
        self.assertEqual(r["drop"], 0.0)
        self.assertFalse(r["shock"])
        self.assertEqual(r["governor"], 1.0)
        self.assertEqual(r["desk_governor"], 1.0)
        from bot_program.capital_truth import equity_drawdown
        dd = equity_drawdown(self.user)
        self.assertEqual(dd["value"], 800.0)    # the reading, as read
        self.assertEqual(dd["withdrawn"], 200.0)

    def test_a_real_loss_after_the_withdrawal_is_still_measured(self):
        _wr(self.user, 200, status="paid",
            paid_at=timezone.now() - timedelta(hours=1))
        _stamp(self.acct, "720")                 # 800 net, then -10%
        r = self._readers()
        self.assertAlmostEqual(r["dd"], 0.1)
        self.assertAlmostEqual(r["drop"], 0.1)
        self.assertTrue(r["shock"])
        self.assertLess(r["governor"], 1.0)

    def test_a_withdrawal_in_another_currency_is_not_converted(self):
        _wr(self.user, 200, status="paid", currency="GBP",
            paid_at=timezone.now() - timedelta(hours=1))
        self.assertAlmostEqual(self._readers()["dd"], 0.2)

    def test_the_market_state_stays_normal(self):
        from bot_program.share_allocator import MODE_SHOCK, market_state
        self.assertEqual(market_state(self.user, {})["mode"], MODE_SHOCK)
        _wr(self.user, 200, status="paid",
            paid_at=timezone.now() - timedelta(hours=1))
        self.assertNotEqual(market_state(self.user, {})["mode"], MODE_SHOCK)

    def test_unreadable_flows_fall_back_to_the_raw_history(self):
        _wr(self.user, 200, status="paid",
            paid_at=timezone.now() - timedelta(hours=1))
        with patch("bot_program.withdrawals.paid_flows",
                   side_effect=RuntimeError("db down")):
            self.assertAlmostEqual(self._readers()["dd"], 0.2)


# ── 5. Readiness ─────────────────────────────────────────────────────────

class ReadinessTests(TestCase):

    def setUp(self):
        self.user = _user("wd_ready")

    def test_an_empty_database_is_em_dashes_not_zeros(self):
        from bot_program.withdrawals import readiness
        r = readiness(self.user)
        self.assertIsNone(r["value"])
        self.assertIsNone(r["free_cash"])
        self.assertIsNone(r["cash_ready"])
        self.assertIsNone(r["deployable"])
        self.assertEqual(r["reserved"], Decimal("0"))
        self.assertEqual(r["following"], [])

    def test_the_pages_cash_takes_off_the_flows_the_cash_gate_holds(self):
        """A flow confirmed early (paid_at before the cell was read,
        held_through at or after it) is money the gate still refuses to
        pledge; the page's "cash ready" must not count it as free. A flow
        paid before the cell with no hold is the cell's own business."""
        from bot_program.withdrawals import readiness
        from tests.test_etoro_leverage import _account
        acct = _account(self.user, cash=300, equity=1000, age_s=300)
        cell_at = acct.last_margin_at
        _wr(self.user, 100, status="paid", paid_amount=100, currency="USD",
            paid_at=cell_at - timedelta(hours=1), held_through=cell_at)
        _wr(self.user, 50, status="paid", paid_amount=50, currency="USD",
            paid_at=cell_at - timedelta(hours=2))
        r = readiness(self.user)
        self.assertEqual(r["free_cash"], Decimal("200.00"))

    def test_etoro_cash_says_ready_or_short_by_how_much(self):
        from bot_program.withdrawals import readiness
        from tests.test_etoro_leverage import _account
        _account(self.user, cash=300, equity=1000)
        _wr(self.user, 200, currency="USD")
        r = readiness(self.user)
        self.assertEqual(r["value"], Decimal("1000.00"))
        self.assertEqual(r["free_cash"], Decimal("300.00"))
        self.assertTrue(r["cash_ready"])
        _wr(self.user, 250, currency="USD")
        r = readiness(self.user)
        self.assertFalse(r["cash_ready"])
        self.assertEqual(r["shortfall"], Decimal("150.00"))
        self.assertEqual(r["deployable"], Decimal("550.00"))

    def test_the_pools_are_listed_before_and_after_and_by_kind(self):
        from bot_program.withdrawals import readiness
        _ibkr_book(self.user, "1000", "EUR")
        _cfg(self.user, name="follower", tracks=True, share=50)
        _cfg(self.user, name="typed", capital="900")
        _cfg(self.user, name="paper", mode="paper")
        _wr(self.user, 400)
        r = readiness(self.user)
        self.assertIsNone(r["free_cash"])          # IBKR stores no cash cell
        self.assertIn("stores no cash", r["cash_note"])
        f = r["following"][0]
        self.assertEqual((f["before"], f["after"]),
                         (Decimal("500.00"), Decimal("300.00")))
        self.assertEqual(r["typed_live"][0]["name"], "typed")
        self.assertTrue(r["typed_live"][0]["over"])   # 900 > 600 deployable
        self.assertEqual([p["name"] for p in r["paper"]], ["paper"])


# ── 6. The page ──────────────────────────────────────────────────────────

class ThePageTests(_Quiet):

    def setUp(self):
        super().setUp()
        self.user = _user("wd_page")
        _pin(self.user)
        self.client.force_login(self.user)

    def _messages(self, resp):
        return " | ".join(str(m) for m in get_messages(resp.wsgi_request))

    def test_anonymous_is_sent_to_log_in_and_changes_nothing(self):
        from django.conf import settings
        from django.shortcuts import resolve_url
        from bot_program.models import WithdrawalRequest
        self.client.logout()
        login = resolve_url(settings.LOGIN_URL)
        for url in (reverse("withdrawals"), reverse("withdrawal_create")):
            resp = self.client.post(url, {"requested_by": "operator",
                                          "amount": "10", "pin": PIN})
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(resp["Location"].startswith(login),
                            resp["Location"])
        self.assertEqual(self.client.get(reverse("withdrawals")).status_code,
                         302)
        self.assertEqual(WithdrawalRequest.objects.count(), 0)

    def test_the_page_renders_on_an_empty_database(self):
        resp = self.client.get(reverse("withdrawals"))
        self.assertEqual(resp.status_code, 200)
        page = resp.content.decode()
        self.assertIn("File a withdrawal request", page)
        self.assertIn("sells nothing and closes nothing", page)
        self.assertIn("recorded in USD by default", page)
        self.assertIn("No active request", page)
        ours = page[page.index("What a request does"):
                    page.index("Nothing withdrawn or cancelled yet")]
        self.assertIn("—", ours)                        # unmeasured, never 0
        self.assertIn("no broker reading yet", ours)
        self.assertNotIn("None", ours)
        self.assertNotIn("0.00", ours)
        self.assertIn('href="/withdrawals/"', page)    # the rail row

    def test_a_wrong_pin_changes_nothing(self):
        from bot_program.models import WithdrawalRequest
        resp = self.client.post(reverse("withdrawal_create"),
                                {"requested_by": "gandalf", "amount": "10",
                                 "pin": "0000"})
        self.assertRedirects(resp, reverse("withdrawals"),
                             fetch_redirect_response=False)
        self.assertIn("PIN", self._messages(resp))
        self.assertEqual(WithdrawalRequest.objects.count(), 0)
        wr = _wr(self.user, 10)
        for name in ("withdrawal_mark_paid", "withdrawal_cancel"):
            resp = self.client.post(reverse(name, args=[wr.pk]),
                                    {"acted_by": "operator", "pin": "0000"})
            self.assertEqual(resp.status_code, 302)
            self.assertIn("Nothing changed", self._messages(resp))
        wr.refresh_from_db()
        self.assertEqual(wr.status, "reserved")
        self.dispatch.assert_not_called()

    def test_file_then_mark_withdrawn_happy_path(self):
        from bot_program.models import WithdrawalRequest
        _ibkr_book(self.user, "5000", "EUR")
        resp = self.client.post(reverse("withdrawal_create"), {
            "requested_by": "gandalf", "amount": "1234.56",
            "wanted_by": "2026-10-05", "reason": "Roof", "pin": PIN})
        self.assertRedirects(resp, reverse("withdrawals"),
                             fetch_redirect_response=False)
        self.assertIn("1,234.56 EUR is held back", self._messages(resp))
        wr = WithdrawalRequest.objects.get()
        self.assertEqual(wr.requested_by, "gandalf")
        page = self.client.get(reverse("withdrawals")).content.decode()
        self.assertIn("1,234.56 EUR", page)
        self.assertIn("Mark withdrawn", page)
        self.assertIn("at the moment you send the withdrawal at the broker",
                      page)
        resp = self.client.post(
            reverse("withdrawal_mark_paid", args=[wr.pk]),
            {"acted_by": "operator", "paid_amount": "1234.56", "paid_at": "",
             "note": "sent from the app", "pin": PIN})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("marked withdrawn", self._messages(resp))
        wr.refresh_from_db()
        self.assertEqual(wr.status, "paid")
        self.assertEqual(wr.acted_by, "operator")
        self.assertEqual(wr.closing_note, "sent from the app")
        page = self.client.get(reverse("withdrawals")).content.decode()
        self.assertIn("Withdrawn", page)
        self.assertIn("No active request", page)

    def test_cancel_happy_path(self):
        wr = _wr(self.user, 75)
        resp = self.client.post(reverse("withdrawal_cancel", args=[wr.pk]),
                                {"acted_by": "gandalf", "pin": PIN})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("cancelled", self._messages(resp))
        wr.refresh_from_db()
        self.assertEqual(wr.status, "cancelled")
        self.assertEqual(wr.acted_by, "gandalf")

    def test_a_refusal_is_flashed_and_writes_nothing(self):
        from bot_program.models import WithdrawalRequest
        _ibkr_book(self.user, "100", "EUR")
        resp = self.client.post(reverse("withdrawal_create"), {
            "requested_by": "operator", "amount": "500", "pin": PIN})
        self.assertIn("cannot be larger than the account",
                      self._messages(resp))
        self.assertEqual(WithdrawalRequest.objects.count(), 0)

    def test_another_users_request_is_a_404(self):
        other = _user("wd_page_other")
        wr = _wr(other, 10)
        for name in ("withdrawal_mark_paid", "withdrawal_cancel"):
            resp = self.client.post(reverse(name, args=[wr.pk]),
                                    {"acted_by": "operator", "pin": PIN})
            self.assertEqual(resp.status_code, 404)
        wr.refresh_from_db()
        self.assertEqual(wr.status, "reserved")
        page = self.client.get(reverse("withdrawals")).content.decode()
        self.assertNotIn(f"withdrawals/{wr.pk}/", page)

    def test_the_acts_are_post_only(self):
        wr = _wr(self.user, 10)
        self.assertEqual(self.client.get(reverse("withdrawal_create"))
                         .status_code, 405)
        self.assertEqual(self.client.get(
            reverse("withdrawal_cancel", args=[wr.pk])).status_code, 405)

    def test_it_needs_no_superuser(self):
        self.assertFalse(self.user.is_superuser)
        wr = _wr(self.user, 10)
        resp = self.client.post(reverse("withdrawal_cancel", args=[wr.pk]),
                                {"acted_by": "operator", "pin": PIN})
        self.assertEqual(resp.status_code, 302)
        wr.refresh_from_db()
        self.assertEqual(wr.status, "cancelled")


# ── 7. The message ───────────────────────────────────────────────────────

class TheMessageTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _user("wd_msg")
        _ibkr_book(self.user, "5000", "EUR")

    def test_each_act_sends_one_withdrawal_message(self):
        from bot_program.withdrawals import (cancel_request, create_request,
                                             mark_paid)
        with patch("bot_program.notifications.dispatch_notification",
                   return_value=True) as d:
            wr = create_request(self.user, requested_by="gandalf",
                                amount="1234.56",
                                wanted_by="2026-10-05")["request"]
            self.assertEqual(d.call_count, 1)
            args, kw = d.call_args
            self.assertEqual(args[1], "withdrawal")
            self.assertEqual(kw["title"], "Withdrawal requested: 1,234.56 EUR")
            items = kw["row_data"]["items"]
            self.assertIn("Amount: 1,234.56 EUR", items)
            self.assertIn("Asked by: Gandalf", items)
            self.assertIn("Wanted by: 2026-10-05", items)
            self.assertIn("Reserved in total: 1,234.56 EUR", items)
            self.assertEqual(kw["row_data"]["mark"], "\U0001F3E6")
            self.assertEqual(kw["url"], "/withdrawals/")

            mark_paid(self.user, wr.pk, acted_by="operator",
                      paid_amount="1200")
            self.assertEqual(d.call_count, 2)
            kw = d.call_args.kwargs
            self.assertEqual(kw["title"], "Withdrawal sent: 1,200.00 EUR")
            self.assertIn("Asked for: 1,234.56 EUR", kw["row_data"]["items"])
            self.assertIn("Marked withdrawn by: The operator",
                          kw["row_data"]["items"])
            self.assertIn("Reserved in total: 0.00 EUR",
                          kw["row_data"]["items"])

            other = create_request(self.user, requested_by="operator",
                                   amount="10")["request"]
            cancel_request(self.user, other.pk, acted_by="gandalf")
            self.assertEqual(d.call_count, 4)
            kw = d.call_args.kwargs
            self.assertEqual(kw["title"],
                             "Withdrawal request cancelled: 10.00 EUR")
            self.assertIn("Cancelled by: Gandalf", kw["row_data"]["items"])

    def test_the_kind_is_an_operator_kind_and_reaches_the_bell(self):
        from alerts.models import Notification
        from bot_program.notifications import NOTIFY_MARKS, OPERATOR_KINDS
        from bot_program.withdrawals import create_request
        self.assertIn("withdrawal", OPERATOR_KINDS)
        self.assertIn("withdrawal", NOTIFY_MARKS)
        create_request(self.user, requested_by="operator", amount="5")
        n = Notification.objects.get(user=self.user)
        self.assertEqual(n.title, "Withdrawal requested: 5.00 EUR")
        self.assertEqual(n.notification_type, "portfolio")

    def test_a_notifier_never_raises(self):
        from bot_program.notifications import notify_withdrawal
        with patch("bot_program.notifications.dispatch_notification",
                   side_effect=RuntimeError("boom")):
            self.assertFalse(notify_withdrawal(
                self.user, _wr(self.user, 1), event="requested",
                reserved_total=Decimal("1")))


# ── 8. What the review of 2026-09-28 found ───────────────────────────────

def _readers(user):
    """What the governor, the shock detector and the pools read."""
    from bot_program.capital_truth import equity_drawdown
    from bot_program.share_allocator import drop_24h, shock_detected
    from bot_program.withdrawals import held_back
    dd = equity_drawdown(user)
    return {"dd": dd["drawdown_pct"], "hwm": dd["hwm"],
            "drop": drop_24h(user), "shock": shock_detected(user),
            "held": held_back(user)}


class TheCashGateReadsOnlyTheBooksOwnReserveTests(TestCase):
    """Saxo is the book (live, stocks first by VENUE_PRECEDENCE); this
    eToro row is a demo account beside it. A reserve filed against the
    Saxo book already shrinks the Saxo followers — it is not this row's
    cash, and a real-money reserve must not block the paper world."""

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.engine.etoro_client import EtoroTrader
        from tests.test_etoro_leverage import _account
        from tests.test_saxo_wiring import saxo
        self.user = _user("wd_gate_book")
        book = saxo(self.user, flags=("stock",), sim=False)
        _stamp(book, "10000", "EUR")
        _account(self.user, cash=1000, equity=100000)
        self.cfg = _cfg(self.user, name="ET", symbols=["AAPL"],
                        currency="USD", capital="10000")
        self.bot = StockBot(self.cfg)
        self.client_ = EtoroTrader("api-k", "user-k", env="demo")

    def _room(self, qty=6):
        return self.bot._leverage_headroom(self.client_, "AAPL", qty=qty,
                                           price=100.0, leverage=1)

    def test_a_reserve_at_the_saxo_book_is_not_etoro_cash(self):
        from bot_program.capital_truth import broker_backed
        self.assertEqual(type(broker_backed(self.user)).__name__,
                         "SaxoAccount")
        _wr(self.user, 500, currency="EUR")
        self.assertIsNone(self._room())          # 600 of 1,000 USD
        self.assertIsNone(self._room(qty=9))     # 900 of 1,000 USD

    def test_a_withdrawal_paid_at_the_book_is_not_etoro_cash_either(self):
        _wr(self.user, 500, currency="EUR", status="paid",
            paid_at=timezone.now())
        self.assertIsNone(self._room())

    def test_the_cash_itself_still_binds(self):
        _wr(self.user, 500, currency="EUR")
        why = self._room(qty=11)                 # 1,100 of 1,000
        self.assertIn("needs 1,100.00 USD of margin and 1,000.00 is free",
                      why)
        self.assertNotIn("held for withdrawals", why)


class MarkingTheAmountIsCheckedTests(_Quiet):
    """One slipped digit must not erase every real loss for 90 days."""

    def setUp(self):
        super().setUp()
        self.user = _user("wd_amount")
        self.acct = _ibkr_book(self.user, "1000", "EUR")
        _reading(self.acct, 1000, hours_ago=24 * 10)
        _reading(self.acct, 1000, hours_ago=12)

    def _file(self, amount="200"):
        from bot_program.withdrawals import create_request
        return create_request(self.user, requested_by="operator",
                              amount=amount)["request"]

    def test_an_amount_larger_than_the_account_is_refused_even_ticked(self):
        from bot_program.withdrawals import mark_paid
        wr = self._file()
        for confirm in (False, True):
            with self.subTest(confirm=confirm):
                out = mark_paid(self.user, wr.pk, acted_by="operator",
                                paid_amount="2000", confirm=confirm)
                self.assertIn("2,000.00 EUR cannot have left an account "
                              "that held 1,000.00 EUR", out["error"])
                self.assertIn("Nothing changed", out["error"])
        wr.refresh_from_db()
        self.assertEqual(wr.status, "reserved")
        self.assertIsNone(wr.paid_amount)
        self.dispatch.assert_called_once()       # the filing, nothing more

    def test_so_a_real_loss_after_the_withdrawal_is_still_measured(self):
        from bot_program.withdrawals import mark_paid
        wr = self._file()
        self.assertIn("error", mark_paid(self.user, wr.pk,
                                         acted_by="operator",
                                         paid_amount="2000"))
        self.assertTrue(mark_paid(self.user, wr.pk,
                                  acted_by="operator").get("ok"))
        _stamp(self.acct, "500")          # 800 after the 200, then -37.5%
        r = _readers(self.user)
        self.assertAlmostEqual(r["dd"], 0.375)
        self.assertEqual(r["hwm"], 800.0)
        self.assertTrue(r["shock"])

    def test_an_amount_far_from_the_one_asked_needs_the_box(self):
        from bot_program.withdrawals import mark_paid
        wr = self._file()
        out = mark_paid(self.user, wr.pk, acted_by="operator",
                        paid_amount="150")
        self.assertIn("Refused until checked", out["error"])
        self.assertIn("150.00 EUR withdrawn is not the 200.00 EUR asked for",
                      out["error"])
        self.assertIn("I have checked", out["error"])
        wr.refresh_from_db()
        self.assertEqual(wr.status, "reserved")
        out = mark_paid(self.user, wr.pk, acted_by="operator",
                        paid_amount="150", confirm=True)
        self.assertTrue(out.get("ok"), out)
        wr.refresh_from_db()
        self.assertEqual(wr.paid_amount, Decimal("150.00"))

    def test_a_large_withdrawal_the_sync_already_read_is_asked_its_time(
            self):
        # 900 of 1,000, and the sync read the 100 left before the mark:
        # "900 cannot have left an account that held 100" would be false
        # — the question is WHEN it left, and the answer passes the bound
        from bot_program.models import BrokerEquityReading
        from bot_program.withdrawals import mark_paid
        wr = self._file("900")
        BrokerEquityReading.objects.create(
            account=self.acct, value=Decimal("1000"), currency="EUR",
            env="live", at=timezone.now() - timedelta(minutes=20))
        _stamp(self.acct, "100", age_seconds=300)
        self.acct.refresh_from_db()
        b_at = self.acct.last_equity_at
        BrokerEquityReading.objects.create(
            account=self.acct, value=Decimal("100"), currency="EUR",
            env="live", at=b_at)
        out = mark_paid(self.user, wr.pk, acted_by="operator")
        self.assertIn("the readings say the money has already left",
                      out["error"])
        self.assertNotIn("cannot have left", out["error"])
        when = b_at.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M")
        out = mark_paid(self.user, wr.pk, acted_by="operator", paid_at=when)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_readers(self.user)["dd"], 0.0)

    def test_a_fee_or_a_rounding_is_taken_as_typed(self):
        from bot_program.withdrawals import mark_paid
        wr = self._file()
        out = mark_paid(self.user, wr.pk, acted_by="operator",
                        paid_amount="195.00")    # a 5.00 fee, 2.5%
        self.assertTrue(out.get("ok"), out)


class AMarkAfterTheSyncReadTheMoneyGoneTests(_Quiet):
    """History at 1,000; a 200 request; the money leaves; the sync reads
    800 five minutes ago; the request is marked now. Blank would take the
    200 off a reading that no longer holds it: a false 25% fall, a shock,
    and the pools held back twice until the next sync."""

    def setUp(self):
        super().setUp()
        from bot_program.models import BrokerEquityReading
        from bot_program.withdrawals import create_request
        self.user = _user("wd_late")
        self.acct = _ibkr_book(self.user, "1000", "EUR")
        _reading(self.acct, 1000, hours_ago=24 * 10)
        _reading(self.acct, 1000, hours_ago=12)
        self.follower = _cfg(self.user, name="manual", tracks=True,
                             capital="1000")
        self.wr = create_request(self.user, requested_by="gandalf",
                                 amount="200")["request"]
        now = timezone.now()
        self.a_at = now - timedelta(minutes=20)
        BrokerEquityReading.objects.create(
            account=self.acct, value=Decimal("1000"), currency="EUR",
            env="live", at=self.a_at)
        _stamp(self.acct, "800", age_seconds=300)       # the sync
        self.acct.refresh_from_db()
        self.b_at = self.acct.last_equity_at
        BrokerEquityReading.objects.create(
            account=self.acct, value=Decimal("800"), currency="EUR",
            env="live", at=self.b_at)

    def _mark(self, **kw):
        from bot_program.withdrawals import mark_paid
        return mark_paid(self.user, self.wr.pk, acted_by="gandalf", **kw)

    @staticmethod
    def _local(at):
        return at.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M")

    def test_a_blank_time_is_refused_and_says_when_it_left(self):
        out = self._mark()
        err = out["error"]
        self.assertIn("the readings say the money has already left", err)
        self.assertIn("1,000.00 EUR", err)
        self.assertIn("800.00 EUR", err)
        self.assertIn(f"{self.b_at.astimezone(dt_timezone.utc):%H:%M} UTC",
                      err)
        self.assertIn("counted twice", err)
        self.assertIn("Nothing changed", err)
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.status, "reserved")

    def test_the_time_it_left_counts_it_once(self):
        out = self._mark(paid_at=self._local(self.b_at))
        self.assertTrue(out.get("ok"), out)
        r = _readers(self.user)
        self.assertEqual(r["dd"], 0.0)
        self.assertEqual(r["drop"], 0.0)
        self.assertFalse(r["shock"])
        self.assertEqual(r["held"], Decimal("0"))
        self.follower.refresh_from_db()
        self.assertEqual(float(self.follower.capital), 800.0)

    def test_what_the_blank_default_would_have_done(self):
        # the harm the refusal prevents, measured: the same flow at "now"
        _wr(self.user, 200, status="paid", paid_at=timezone.now())
        r = _readers(self.user)
        self.assertAlmostEqual(r["dd"], 0.25)
        self.assertTrue(r["shock"])
        self.assertEqual(r["held"], Decimal("400.00"))

    def test_a_time_after_the_reading_needs_the_box(self):
        late = self._local(timezone.now() - timedelta(minutes=1))
        out = self._mark(paid_at=late)
        self.assertIn("Refused until checked", out["error"])
        self.assertIn("is after the latest reading", out["error"])
        self.assertTrue(self._mark(paid_at=late, confirm=True).get("ok"))

    def test_a_time_before_the_money_left_needs_the_box(self):
        early = self._local(self.a_at - timedelta(minutes=30))
        out = self._mark(paid_at=early)
        self.assertIn("Refused until checked", out["error"])
        self.assertIn("still holds the money", out["error"])
        self.assertIn("90 days", out["error"])
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.status, "reserved")
        self.assertTrue(self._mark(paid_at=early, confirm=True).get("ok"))

    def test_a_withdrawal_inside_the_market_noise_is_not_matched(self):
        from bot_program.withdrawals import create_request, mark_paid
        small = create_request(self.user, requested_by="operator",
                               amount="10")["request"]
        _stamp(self.acct, "790", age_seconds=60)
        self.assertTrue(mark_paid(self.user, small.pk,
                                  acted_by="operator").get("ok"))

    def test_the_page_shows_the_last_reading_beside_the_time(self):
        _pin(self.user)
        self.client.force_login(self.user)
        page = self.client.get(reverse("withdrawals")).content.decode()
        self.assertIn("Last account reading: "
                      f"{self.b_at.astimezone(dt_timezone.utc):%Y-%m-%d %H:%M}"
                      " UTC (800.00 EUR)", page)
        self.assertIn('name="confirm"', page)


class AMarkBeforeTheSyncReadTheMoneyGoneTests(_Quiet):
    """History at 1,000 (-10d, -12h, -2h); the sync read 1,000 five
    minutes ago; a 200 request holds the follower at 800. The operator
    sent the money at the broker an hour ago and types that time — but
    the balance has not moved yet, by any reading. Before the second
    review the mark went through without a tick, and the reserve was
    released at once: paid_since held only a withdrawal paid AFTER the
    reading, and this one was "paid" before it — so the pools grew back
    into money about to leave, and the readings in between read as a 20%
    fall once it did."""

    def setUp(self):
        super().setUp()
        from bot_program.withdrawals import create_request
        self.user = _user("wd_early")
        self.acct = _ibkr_book(self.user, "1000", "EUR", age_seconds=300)
        _reading(self.acct, 1000, hours_ago=24 * 10)
        _reading(self.acct, 1000, hours_ago=12)
        _reading(self.acct, 1000, hours_ago=2)
        self.follower = _cfg(self.user, name="manual", tracks=True,
                             capital="1000")
        self.wr = create_request(self.user, requested_by="operator",
                                 amount="200")["request"]
        self.acct.refresh_from_db()
        self.r_at = self.acct.last_equity_at
        self.early = (timezone.now() - timedelta(hours=1)).astimezone(
            dt_timezone.utc).strftime("%Y-%m-%dT%H:%M")

    def _mark(self, **kw):
        from bot_program.withdrawals import mark_paid
        return mark_paid(self.user, self.wr.pk, acted_by="operator", **kw)

    def _capital(self):
        self.follower.refresh_from_db()
        return float(self.follower.capital)

    def test_a_time_before_the_reading_that_still_holds_the_money_needs_the_box(
            self):
        self.assertEqual(self._capital(), 800.0)
        out = self._mark(paid_at=self.early)
        err = out["error"]
        self.assertIn("Refused until checked", err)
        self.assertIn("is before the latest reading", err)
        self.assertIn(f"({self.r_at.astimezone(dt_timezone.utc):%Y-%m-%d %H:%M}"
                      " UTC)", err)
        self.assertIn("still holds the money", err)
        self.assertIn("nothing has left the account yet by the readings", err)
        self.assertIn("90 days", err)
        self.assertIn("leave the time blank", err)
        self.assertIn("tick", err)
        self.assertIn("Nothing changed", err)
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.status, "reserved")
        self.assertEqual(_readers(self.user)["held"], Decimal("200.00"))
        self.assertEqual(self._capital(), 800.0)

    def test_ticked_the_mark_goes_through_as_typed(self):
        out = self._mark(paid_at=self.early, confirm=True)
        self.assertTrue(out.get("ok"), out)
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.status, "paid")
        self.assertEqual(self.wr.paid_amount, Decimal("200.00"))
        self.assertEqual(self.wr.paid_at.astimezone(dt_timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M"), self.early)
        # and it remembers the reading it was checked against
        self.assertEqual(self.wr.held_through, self.r_at)

    def test_ticked_the_money_is_still_held_back_until_a_reading_shows_it_gone(
            self):
        from bot_program.tasks import _follow_the_account
        from bot_program.withdrawals import held_back, held_back_in
        self.assertTrue(self._mark(paid_at=self.early, confirm=True).get("ok"))
        # the follow after the mark sized from the 1,000 reading, which
        # still holds the money: the flow is held back from it, as the
        # reserve was
        self.assertEqual(held_back(self.user), Decimal("200.00"))
        self.assertEqual(held_back(self.user, self.r_at), Decimal("200.00"))
        self.assertEqual(held_back_in(self.user, "EUR", self.r_at),
                         (Decimal("200.00"), {}))
        self.assertEqual(self._capital(), 800.0)
        # the next sync reads the money gone: counted once, held no more
        _stamp(self.acct, "800")
        self.acct.refresh_from_db()
        _follow_the_account(self.user, 800.0, "EUR")
        self.assertEqual(held_back(self.user), Decimal("0"))
        self.assertEqual(held_back_in(self.user, "EUR",
                                      self.acct.last_equity_at),
                         (Decimal("0"), {}))
        self.assertEqual(self._capital(), 800.0)

    def test_a_correction_to_an_early_time_is_checked_and_held_the_same(self):
        from bot_program.withdrawals import correct_paid, held_back
        self.assertTrue(self._mark().get("ok"))          # blank: now
        self.wr.refresh_from_db()
        self.assertIsNone(self.wr.held_through)
        self.assertEqual(held_back(self.user), Decimal("200.00"))
        out = correct_paid(self.user, self.wr.pk, acted_by="operator",
                           paid_at=self.early)
        self.assertIn("still holds the money", out["error"])
        out = correct_paid(self.user, self.wr.pk, acted_by="operator",
                           paid_at=self.early, confirm=True)
        self.assertTrue(out.get("ok"), out)
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.held_through, self.r_at)
        self.assertEqual(held_back(self.user), Decimal("200.00"))

    def test_a_fall_the_noise_hid_is_still_a_fall_and_is_not_held_twice(self):
        # the sync read 770: the 200 left with a 30 market fall on top,
        # which no pair of readings matches — but the money IS gone by the
        # readings, so the time typed before that reading needs no tick,
        # and the flow is not held back from a reading that lacks it
        from bot_program.withdrawals import held_back
        _stamp(self.acct, "770", age_seconds=300)
        out = self._mark(paid_at=self.early)
        self.assertTrue(out.get("ok"), out)
        self.wr.refresh_from_db()
        self.assertIsNone(self.wr.held_through)
        self.assertEqual(held_back(self.user), Decimal("0"))
        self.assertEqual(self._capital(), 770.0)

    def test_a_withdrawal_inside_the_market_noise_goes_through_as_typed(self):
        # 10 on 1,000 cannot be told from the market: no tick, no hold
        from bot_program.withdrawals import create_request, held_back, mark_paid
        small = create_request(self.user, requested_by="operator",
                               amount="10")["request"]
        out = mark_paid(self.user, small.pk, acted_by="operator",
                        paid_at=self.early)
        self.assertTrue(out.get("ok"), out)
        small.refresh_from_db()
        self.assertIsNone(small.held_through)
        self.assertEqual(held_back(self.user), Decimal("200.00"))

    def test_no_history_or_no_reading_still_goes_through_as_typed(self):
        # the carve-out stays: when nothing can be checked, the act goes
        # through as typed, as it did before
        from bot_program.models import BrokerEquityReading
        from bot_program.withdrawals import mark_paid
        BrokerEquityReading.objects.filter(account=self.acct).delete()
        out = self._mark(paid_at=self.early)
        self.assertTrue(out.get("ok"), out)
        self.wr.refresh_from_db()
        self.assertIsNone(self.wr.held_through)
        blind = _user("wd_early_blind")
        _ibkr_book(blind, value=None)
        wr = _wr(blind, 50, currency="USD", assumed=True)
        out = mark_paid(blind, wr.pk, acted_by="operator", paid_at=self.early)
        self.assertTrue(out.get("ok"), out)
        self.assertIn("No account reading has landed", out["warnings"][0])
        wr.refresh_from_db()
        self.assertIsNone(wr.held_through)


class ACorrectionPutsAWrongNumberRightTests(_Quiet):
    """Marked with a time before the broker's balance moved: the reading
    two hours ago still held the money, so the history reads a 20% fall
    for 90 days. Before the review only the database could fix it."""

    def setUp(self):
        super().setUp()
        self.user = _user("wd_fix")
        self.acct = _ibkr_book(self.user, "1000", "EUR")
        _reading(self.acct, 1000, hours_ago=24 * 10)
        _reading(self.acct, 1000, hours_ago=12)
        _reading(self.acct, 1000, hours_ago=2)
        _stamp(self.acct, "800")
        self.wr = _wr(self.user, 200, status="paid", paid_amount=200,
                      paid_at=timezone.now() - timedelta(hours=3))

    def _fix(self, **kw):
        from bot_program.withdrawals import correct_paid
        return correct_paid(self.user, self.wr.pk, acted_by="operator", **kw)

    def test_the_time_is_corrected_and_the_false_fall_goes(self):
        self.assertAlmostEqual(_readers(self.user)["dd"], 0.2)
        when = (timezone.now() - timedelta(hours=1)).astimezone(
            dt_timezone.utc).strftime("%Y-%m-%dT%H:%M")
        out = self._fix(paid_at=when, note="the bank took an hour")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_readers(self.user)["dd"], 0.0)
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.paid_amount, Decimal("200.00"))
        self.assertEqual(self.wr.acted_by, "operator")
        self.assertIn("Corrected", self.wr.closing_note)
        self.assertIn("was 200.00 EUR at", self.wr.closing_note)
        self.assertIn("the bank took an hour", self.wr.closing_note)
        kw = self.dispatch.call_args.kwargs
        self.assertEqual(kw["title"], "Withdrawal corrected: 200.00 EUR")
        self.assertTrue(any(i.startswith("Was: 200.00 EUR at")
                            for i in kw["row_data"]["items"]))

    def test_a_correction_is_checked_like_the_mark(self):
        out = self._fix(paid_amount="2000", confirm=True)
        self.assertIn("cannot have left an account", out["error"])
        out = self._fix(paid_amount="150")
        self.assertIn("Refused until checked", out["error"])
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.paid_amount, Decimal("200.00"))
        self.dispatch.assert_not_called()

    def test_the_time_box_sent_back_untouched_keeps_the_moment(self):
        # the form shows the stored moment to the minute; sent back as it
        # is, with only the amount changed, the seconds are not "corrected"
        stored = self.wr.paid_at
        shown = stored.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M")
        out = self._fix(paid_at=shown, paid_amount="198", confirm=True)
        self.assertTrue(out.get("ok"), out)
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.paid_at, stored)
        self.assertEqual(self.wr.paid_amount, Decimal("198.00"))
        self.assertIn("Nothing to correct",
                      self._fix(paid_at=shown, paid_amount="198")["error"])

    def test_only_a_withdrawal_is_corrected_and_only_when_it_changes(self):
        from bot_program.withdrawals import correct_paid
        reserved = _wr(self.user, 50)
        out = correct_paid(self.user, reserved.pk, acted_by="gandalf",
                           paid_amount="50")
        self.assertIn("only a withdrawal can be corrected", out["error"])
        self.assertIn("Nothing to correct", self._fix(paid_amount="200")
                      ["error"])

    def test_the_page_corrects_with_the_pin_and_only_with_it(self):
        _pin(self.user)
        self.client.force_login(self.user)
        page = self.client.get(reverse("withdrawals")).content.decode()
        self.assertIn(reverse("withdrawal_correct", args=[self.wr.pk]), page)
        url = reverse("withdrawal_correct", args=[self.wr.pk])
        when = (timezone.now() - timedelta(hours=1)).astimezone(
            dt_timezone.utc).strftime("%Y-%m-%dT%H:%M")
        resp = self.client.post(url, {"acted_by": "gandalf",
                                      "paid_at": when, "pin": "0000"})
        self.assertEqual(resp.status_code, 302)
        self.wr.refresh_from_db()
        self.assertNotIn("Corrected", self.wr.closing_note)
        resp = self.client.post(url, {"acted_by": "gandalf",
                                      "paid_at": when, "pin": PIN})
        self.assertRedirects(resp, reverse("withdrawals"),
                             fetch_redirect_response=False)
        msgs = " | ".join(str(m) for m in get_messages(resp.wsgi_request))
        self.assertIn(f"Request #{self.wr.pk} corrected", msgs)
        self.wr.refresh_from_db()
        self.assertIn("Corrected", self.wr.closing_note)
        other = _wr(_user("wd_fix_other"), 10, status="paid",
                    paid_at=timezone.now())
        resp = self.client.post(
            reverse("withdrawal_correct", args=[other.pk]),
            {"acted_by": "gandalf", "paid_amount": "5", "pin": PIN})
        self.assertEqual(resp.status_code, 404)


class AFallbackCurrencyIsNotALossTests(_Quiet):
    """A request filed before any reading is recorded in USD by default;
    the account then reads in EUR."""

    def setUp(self):
        super().setUp()
        self.user = _user("wd_ccy")

    def _eur_history_then_800(self):
        acct = _ibkr_book(self.user, "1000", "EUR")
        _reading(acct, 1000, hours_ago=24 * 10)
        _reading(acct, 1000, hours_ago=12)
        _reading(acct, 1000, hours_ago=2)
        _stamp(acct, "800")
        return acct

    def test_filed_before_any_reading_then_paid_reads_as_a_flow(self):
        from bot_program.withdrawals import create_request, mark_paid
        wr = create_request(self.user, requested_by="gandalf",
                            amount="200")["request"]
        self.assertEqual((wr.currency, wr.currency_assumed), ("USD", True))
        self._eur_history_then_800()
        when = (timezone.now() - timedelta(hours=1)).astimezone(
            dt_timezone.utc).strftime("%Y-%m-%dT%H:%M")
        out = mark_paid(self.user, wr.pk, acted_by="gandalf", paid_at=when)
        self.assertTrue(out.get("ok"), out)
        wr.refresh_from_db()
        self.assertEqual((wr.currency, wr.currency_assumed), ("EUR", False))
        r = _readers(self.user)
        self.assertEqual(r["dd"], 0.0)
        self.assertFalse(r["shock"])

    def test_a_flow_still_assumed_counts_in_the_readings_currency(self):
        _wr(self.user, 200, status="paid", currency="USD", assumed=True,
            paid_at=timezone.now() - timedelta(hours=1))
        self._eur_history_then_800()
        r = _readers(self.user)
        self.assertEqual(r["dd"], 0.0)
        self.assertFalse(r["shock"])

    def test_a_real_other_currency_cannot_be_marked_and_the_page_says_so(
            self):
        from bot_program.withdrawals import mark_paid, readiness
        _ibkr_book(self.user, "1000", "EUR")
        wr = _wr(self.user, 200, currency="GBP")
        out = mark_paid(self.user, wr.pk, acted_by="operator")
        self.assertIn("is in GBP and the account now reads in EUR",
                      out["error"])
        self.assertIn("Cancel it and file it again in EUR", out["error"])
        wr.refresh_from_db()
        self.assertEqual(wr.status, "reserved")
        r = readiness(self.user)
        self.assertEqual([f["id"] for f in r["foreign_ccy"]], [wr.pk])
        _wr(self.user, 100, currency="USD", assumed=True)   # not foreign
        self.assertEqual(len(readiness(self.user)["foreign_ccy"]), 1)


class TheFollowButtonSizesFromWhatIsLeftTests(_Quiet):
    """The Follow button and `manage.py follow --yes` write a pool's share
    themselves, before the follow runs: of the reading LESS the hold."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            "wd_follow_btn", password="x", is_staff=True, is_superuser=True)
        _pin(self.user)
        _ibkr_book(self.user, "1000", "EUR")
        self.cfg = _cfg(self.user, name="etf", capital="200")
        _wr(self.user, 200)

    def _post(self, **fields):
        data = {"config_id": self.cfg.id, "follow": "1", "share": "70",
                "pin": PIN}
        data.update(fields)
        self.client.force_login(self.user)
        return self.client.post(reverse("hq_follow_asset_bot"), data)

    def test_the_button_writes_and_quotes_the_pool_after_the_reserve(self):
        resp = self._post()
        msgs = " | ".join(str(m) for m in get_messages(resp.wsgi_request))
        self.cfg.refresh_from_db()
        self.assertEqual(float(self.cfg.capital), 560.0)     # 70% of 800
        self.assertIn("pool 560.00 EUR", msgs)
        self.assertIn("200.00 EUR held back for withdrawals", msgs)

    def test_an_unreadable_reserve_follows_nothing(self):
        with patch("bot_program.withdrawals.reserved_total",
                   side_effect=RuntimeError("db down")):
            resp = self._post()
        msgs = " | ".join(str(m) for m in get_messages(resp.wsgi_request))
        self.assertIn("withdrawal reserve could not be read", msgs)
        self.cfg.refresh_from_db()
        self.assertNotIn("capital_tracks_broker", self.cfg.extras)
        self.assertEqual(float(self.cfg.capital), 200.0)

    def test_the_command_plans_and_writes_the_pool_after_the_reserve(self):
        from io import StringIO

        from django.core.management import call_command
        plan = StringIO()
        call_command("follow", str(self.cfg.pk), share=70, stdout=plan)
        self.assertIn("held back for withdrawals: 200.00 EUR", plan.getvalue())
        self.assertIn("-> 560.00 EUR", plan.getvalue())
        out = StringIO()
        call_command("follow", str(self.cfg.pk), share=70, yes=True,
                     stdout=out)
        self.cfg.refresh_from_db()
        self.assertEqual(float(self.cfg.capital), 560.0)
        self.assertIn("pool 560.00 EUR", out.getvalue())
        listing = StringIO()
        call_command("follow", stdout=listing)
        self.assertIn("the pools follow 800.00", listing.getvalue())
        self.assertIn("(= 560.00)", listing.getvalue())


class ThePageShowsOnlyThePoolsTheSyncMovesTests(_Quiet):
    """A follower whose orders route to a broker other than the book is
    skipped by the sync — so the page must not show it shrinking."""

    ROUTE = "bot_program.engine.broker_router.broker_name_for_symbol"

    def setUp(self):
        super().setUp()
        self.user = _user("wd_venue")
        _ibkr_book(self.user, "1000", "EUR")
        self.fx = _cfg(self.user, name="fx", asset_class="forex",
                       tracks=True, share=50, symbols=["EURUSD"],
                       capital="321")
        self.st = _cfg(self.user, name="st", tracks=True, share=50,
                       symbols=["AAPL"])
        _wr(self.user, 400)

    @staticmethod
    def _venue(user, sym, cfg=None):
        return "saxo" if sym == "EURUSD" else "ibkr"

    def test_the_page_and_the_sync_agree(self):
        from bot_program.tasks import _follow_the_account
        from bot_program.withdrawals import readiness
        with patch(self.ROUTE, side_effect=self._venue):
            r = readiness(self.user)
            _follow_the_account(self.user, 1000.0, "EUR")
        rows = {f["name"]: f for f in r["following"]}
        self.assertEqual(rows["fx"]["foreign"], "saxo")
        self.assertIsNone(rows["fx"]["after"])
        self.assertEqual(rows["fx"]["before"], Decimal("500.00"))
        self.assertEqual(rows["st"]["after"], Decimal("300.00"))
        self.assertEqual([p["name"] for p in r["not_retuned"]], ["fx"])
        self.fx.refresh_from_db()
        self.st.refresh_from_db()
        self.assertEqual(float(self.fx.capital), 321.0)   # not moved
        self.assertEqual(float(self.st.capital), 300.0)   # as the page said

    def test_the_page_says_it_in_words(self):
        _pin(self.user)
        self.client.force_login(self.user)
        with patch(self.ROUTE, side_effect=self._venue):
            page = self.client.get(reverse("withdrawals")).content.decode()
        self.assertIn("not retuned — trades at saxo", page)
        self.assertIn("are NOT retuned by the sync", page)
