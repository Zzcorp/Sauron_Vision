"""What a price alert is allowed to say, and how often it may say it.

Three defects, all of them in the checker's favour and against the operator:

  * `cross` evaluated `price >= target or price <= target`, which is true of
    every finite price. The alert fired on the first beat whatever the market
    was doing — "BTCUSD cross 250000 — Current price: 90000" — and, being
    consumed, could never fire when the level was actually crossed.

  * The row was claimed by mutating a snapshot loaded when the queryset was
    iterated and calling `save()`. The beat runs every 60s on a queue with
    two worker slots and sends a Telegram POST plus an SMTP mail per firing
    alert, so a busy open runs long enough for the next copy to start on rows
    the first has not reached: two notifications, two Telegram messages and
    two emails for one price cross. The unqualified save also wrote back
    every field of the stale row, reverting a target the user had just
    edited.

  * LiveQuote was read with no freshness bound, alone among the consumers of
    that table. A Sunday beat fired "DAX40 below 21000 — Current price:
    20800" off Friday's close, and the operator opened a position into
    Monday's gap.

Run with:  python manage.py test tests.test_price_alert_truth
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="pa_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(inst, last, *, age_seconds=10):
    from market_data.models import LiveQuote
    q, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    LiveQuote.objects.filter(pk=q.pk).update(
        updated_at=timezone.now() - timedelta(seconds=age_seconds))
    return q


def _alert(user, inst, condition, target, **kw):
    from alerts.models import PriceAlert
    return PriceAlert.objects.create(
        user=user, instrument=inst, condition=condition,
        target_price=Decimal(str(target)),
        notify_telegram=False, notify_email=False, **kw)


def _fired(user):
    from alerts.models import Notification
    return Notification.objects.filter(
        user=user, title__startswith="Price Alert").count()


class CrossConditionTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.inst = _instrument()

    def test_a_cross_alert_does_not_fire_the_moment_it_is_created(self):
        from alerts.models import check_price_alerts
        alert = _alert(self.user, self.inst, "cross", 250000)
        _quote(self.inst, 90000)

        self.assertEqual(check_price_alerts(), 0)

        alert.refresh_from_db()
        self.assertFalse(alert.triggered)
        self.assertEqual(_fired(self.user), 0)
        # It armed instead: the side it will measure the crossing from.
        self.assertEqual(alert.baseline_price, Decimal("90000.00000000"))

    def test_a_cross_alert_fires_when_the_level_is_actually_crossed(self):
        from alerts.models import check_price_alerts
        alert = _alert(self.user, self.inst, "cross", 250000)
        _quote(self.inst, 90000)
        check_price_alerts()

        _quote(self.inst, 250001)
        self.assertEqual(check_price_alerts(), 1)

        alert.refresh_from_db()
        self.assertTrue(alert.triggered)
        self.assertEqual(_fired(self.user), 1)

    def test_a_cross_alert_sits_still_while_the_price_stays_on_its_side(self):
        from alerts.models import check_price_alerts
        alert = _alert(self.user, self.inst, "cross", 250000)
        _quote(self.inst, 90000)
        check_price_alerts()

        for px in (95000, 120000, 249999):
            _quote(self.inst, px)
            check_price_alerts()

        alert.refresh_from_db()
        self.assertFalse(alert.triggered)
        self.assertEqual(_fired(self.user), 0)

    def test_a_cross_from_above_counts_too(self):
        from alerts.models import check_price_alerts
        _alert(self.user, self.inst, "cross", 100000)
        _quote(self.inst, 110000)
        check_price_alerts()

        _quote(self.inst, 99000)
        self.assertEqual(check_price_alerts(), 1)

    def test_above_and_below_still_fire_on_the_first_look(self):
        """'cross' asks whether the level was crossed; these two ask whether
        the price is past it, and they must keep answering immediately."""
        from alerts.models import check_price_alerts
        _alert(self.user, self.inst, "above", 80000)
        _quote(self.inst, 90000)
        self.assertEqual(check_price_alerts(), 1)

        inst2 = _instrument("ETHUSD")
        _alert(self.user, inst2, "below", 5000)
        _quote(inst2, 4000)
        self.assertEqual(check_price_alerts(), 1)


class QuoteFreshnessTests(TestCase):
    def setUp(self):
        self.user = _user("pa_stale")
        self.inst = _instrument("DAX40", asset_class="index")

    def test_a_weekend_old_quote_does_not_fire_an_alert(self):
        from alerts.models import check_price_alerts
        alert = _alert(self.user, self.inst, "below", 21000)
        _quote(self.inst, 20800, age_seconds=40 * 3600)

        self.assertEqual(check_price_alerts(), 0)

        alert.refresh_from_db()
        self.assertFalse(alert.triggered)
        self.assertEqual(_fired(self.user), 0)

    def test_the_alert_survives_to_fire_on_a_fresh_print(self):
        """Skipping a stale quote must not consume the alert."""
        from alerts.models import check_price_alerts
        _alert(self.user, self.inst, "below", 21000)
        _quote(self.inst, 20800, age_seconds=40 * 3600)
        check_price_alerts()

        _quote(self.inst, 20750, age_seconds=5)
        self.assertEqual(check_price_alerts(), 1)

    def test_an_instrument_with_no_quote_is_skipped_not_errored(self):
        from alerts.models import check_price_alerts
        _alert(self.user, _instrument("XRPUSD"), "above", 1)
        self.assertEqual(check_price_alerts(), 0)


class ConcurrentBeatTests(TestCase):
    """The second worker's copy of the row is a snapshot, not the truth."""

    def setUp(self):
        self.user = _user("pa_race")
        self.inst = _instrument("SOLUSD")

    def _run_with_stale_snapshot(self, stale_rows):
        """Run the checker over rows loaded before another worker got there."""
        from alerts.models import PriceAlert, check_price_alerts
        real_filter = PriceAlert.objects.filter

        def fake_filter(*args, **kwargs):
            if kwargs == {"triggered": False}:
                handle = MagicMock()
                handle.select_related.return_value = stale_rows
                return handle
            return real_filter(*args, **kwargs)

        with patch.object(PriceAlert.objects, "filter", fake_filter):
            return check_price_alerts()

    def test_an_alert_another_worker_already_sent_is_not_sent_twice(self):
        from alerts.models import PriceAlert, check_price_alerts
        alert = _alert(self.user, self.inst, "above", 100)
        _quote(self.inst, 150)

        stale = list(PriceAlert.objects.filter(pk=alert.pk)
                     .select_related("instrument", "user"))
        # The other worker gets there first and fires it.
        self.assertEqual(check_price_alerts(), 1)

        self.assertEqual(self._run_with_stale_snapshot(stale), 0)
        self.assertEqual(_fired(self.user), 1)

    def test_a_stale_snapshot_does_not_revert_an_edited_target(self):
        from alerts.models import PriceAlert
        alert = _alert(self.user, self.inst, "above", 100)
        _quote(self.inst, 150)

        stale = list(PriceAlert.objects.filter(pk=alert.pk)
                     .select_related("instrument", "user"))
        # The user raises the target while the beat is mid-pass.
        PriceAlert.objects.filter(pk=alert.pk).update(
            target_price=Decimal("500"))

        self._run_with_stale_snapshot(stale)

        alert.refresh_from_db()
        self.assertEqual(alert.target_price, Decimal("500.00000000"))
        # And the decision the edit invalidated is dropped rather than sent:
        # 150 is above the old 100, not above the 500 the user now wants.
        self.assertFalse(alert.triggered)
        self.assertEqual(_fired(self.user), 0)
