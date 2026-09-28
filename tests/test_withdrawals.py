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
  * the message: one per act, kind "withdrawal", never raising.

Run with:  python manage.py test tests.test_withdrawals
"""
from datetime import timedelta
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
        paid_amount=None, who="operator"):
    from bot_program.models import WithdrawalRequest
    return WithdrawalRequest.objects.create(
        user=user, requested_by=who, amount=Decimal(str(amount)),
        currency=currency, status=status, paid_at=paid_at,
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
        _ibkr_book(self.user, "1000", "EUR")
        out = self._create(wanted_by="2026-10-05", reason="Roof repair")
        self.assertTrue(out.get("ok"), out)
        wr = out["request"]
        self.assertEqual(wr.status, "reserved")
        self.assertEqual(wr.amount, Decimal("200.00"))
        self.assertEqual(wr.currency, "EUR")
        self.assertEqual(wr.requested_by, "gandalf")
        self.assertEqual(str(wr.wanted_by), "2026-10-05")
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
        with patch("bot_program.withdrawals.reserved_total",
                   side_effect=RuntimeError("db down")):
            why = self._room()
        self.assertIn("withdrawal reserve could not be read", why)


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
