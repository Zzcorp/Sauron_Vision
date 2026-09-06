"""The bell stops shouting about a halt that halts nothing.

On 2026-09-06 the operator had roughly a hundred queued notifications titled
"Circuit breaker: manual". In the same bell, unread, sat a quote stream that
had been silent for four days and a bar feed frozen since Thursday. Neither
was noticed. The noise did not merely annoy — it is what hid the outage, and
the outage is what made the brain publish confident regime reads off a frozen
frame for two days.

Three defects produced that hundred:

1. `tick` evaluates can_open_new BEFORE the symbol loop, so a config with
   symbols=[] reports a halt over a loop that had nothing to iterate — while
   the manual TAKE TRADE lane it serves does not consult these breakers at
   all (it calls risk_gate.preflight directly).
2. The cadence was "once an hour while tripped", and a tripped breaker cannot
   clear itself: check_consecutive_losses only breaks its streak when a
   winning trade closes, and the breaker forbids the entries that would
   produce one. "While tripped" therefore means "forever".
3. The de-dupe key is (user, type, title) and the title was the config NAME
   alone. This deployment runs SIX configs called "manual", one per asset
   class — so they silenced each other, and the bell could not say which.

With real money armed a drowned alert is a drowned stop, which is why this
is a money test and not a tidiness test.

Run with:  python manage.py test tests.test_breaker_alert_fatigue
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _cfg(*, name="manual", asset_class="stock", symbols=(), user=None):
    from bot_program.models import AssetBotConfig
    user = user or User.objects.create_user(
        f"brk_{name}_{asset_class}", password="x")
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode="paper",
        symbols=list(symbols), capital=Decimal("10000"), enabled=True)


def _notify(cfg, reasons=("4 consecutive losing trades (max 4)",)):
    from bot_program.asset_engine.safety import notify_circuit_breaker
    notify_circuit_breaker(cfg, list(reasons))


def _notes(user=None):
    from alerts.models import Notification
    qs = Notification.objects.filter(notification_type="bot")
    return qs.filter(user=user) if user else qs


def _age_all(user, hours):
    """Push every existing alert `hours` into the past.

    Through a queryset update because created_at is auto_now_add: assigning it
    on the instance is silently overwritten, which would leave every alert in
    this file freshly stamped and every cadence assertion vacuous.
    """
    from alerts.models import Notification
    for n in Notification.objects.filter(user=user):
        Notification.objects.filter(pk=n.pk).update(
            created_at=n.created_at - timedelta(hours=hours))


class TheTitleNamesWhichBotTests(TestCase):
    """Six configs share the name "manual". The de-dupe key must not."""

    def test_the_asset_class_is_in_the_title(self):
        cfg = _cfg(asset_class="stock")
        _notify(cfg)
        note = _notes(cfg.user).first()
        self.assertIn("manual", note.title)
        self.assertIn("stock", note.title)

    def test_two_manual_configs_in_different_classes_do_not_silence_each_other(self):
        """The one that cost the outage: a commodity trip suppressed a forex
        trip for the whole cooldown, and the bell said only "manual"."""
        user = User.objects.create_user("brk_shared", password="x")
        fx = _cfg(asset_class="forex", user=user)
        cm = _cfg(asset_class="commodity", user=user)
        _notify(fx)
        _notify(cm)
        titles = set(_notes(user).values_list("title", flat=True))
        self.assertEqual(len(titles), 2, f"one silenced the other: {titles}")

    def test_the_same_config_twice_in_the_hour_still_de_dupes(self):
        """Decaying the cadence must not remove the cadence."""
        cfg = _cfg()
        _notify(cfg)
        _notify(cfg)
        self.assertEqual(_notes(cfg.user).count(), 1)


class TheCadenceDecaysTests(TestCase):

    def test_hourly_while_the_news_is_still_news(self):
        from bot_program.asset_engine.safety import BREAKER_ALERT_FAST_HOURS
        cfg = _cfg()
        _notify(cfg)
        _age_all(cfg.user, BREAKER_ALERT_FAST_HOURS + 0.1)
        _notify(cfg)
        self.assertEqual(_notes(cfg.user).count(), 2)

    def test_after_enough_of_them_hourly_becomes_daily(self):
        """Hourly has failed to get a decision; repeating it faster will not
        help, and the cost of repeating is a buried stop."""
        from bot_program.asset_engine.safety import (
            BREAKER_ALERT_FAST_COUNT, BREAKER_ALERT_FAST_HOURS,
            BREAKER_ALERT_SLOW_HOURS)
        cfg = _cfg()
        for _ in range(BREAKER_ALERT_FAST_COUNT):
            _notify(cfg)
            _age_all(cfg.user, BREAKER_ALERT_FAST_HOURS + 0.1)
        sent = _notes(cfg.user).count()
        self.assertEqual(sent, BREAKER_ALERT_FAST_COUNT)

        # An hour later: refused, because we are past the fast count.
        _age_all(cfg.user, BREAKER_ALERT_FAST_HOURS + 0.1)
        _notify(cfg)
        self.assertEqual(_notes(cfg.user).count(), sent)

        # A day later: allowed.
        _age_all(cfg.user, BREAKER_ALERT_SLOW_HOURS)
        _notify(cfg)
        self.assertEqual(_notes(cfg.user).count(), sent + 1)

    def test_a_breaker_that_really_cleared_starts_fast_again(self):
        """Quiet for longer than an episode means it genuinely cleared. The
        next trip is news again and must not inherit the slow cadence."""
        from bot_program.asset_engine.safety import (
            BREAKER_ALERT_EPISODE_DAYS, BREAKER_ALERT_FAST_COUNT,
            BREAKER_ALERT_FAST_HOURS)
        cfg = _cfg()
        for _ in range(BREAKER_ALERT_FAST_COUNT + 2):
            _notify(cfg)
            _age_all(cfg.user, BREAKER_ALERT_FAST_HOURS + 0.1)
        before = _notes(cfg.user).count()
        _age_all(cfg.user, BREAKER_ALERT_EPISODE_DAYS * 24 + 1)
        _notify(cfg)
        self.assertEqual(_notes(cfg.user).count(), before + 1)

    def test_the_fast_cadence_is_not_the_slow_one(self):
        """A pin on the shape: collapsing these two constants to one value
        would satisfy every test above while restoring the original bug."""
        from bot_program.asset_engine.safety import (
            BREAKER_ALERT_FAST_HOURS, BREAKER_ALERT_SLOW_HOURS)
        self.assertLess(BREAKER_ALERT_FAST_HOURS, BREAKER_ALERT_SLOW_HOURS)
        self.assertGreaterEqual(BREAKER_ALERT_SLOW_HOURS, 12)


class TheBodyDoesNotClaimAHaltThatDidNotHappenTests(TestCase):

    def test_a_symbol_less_config_is_told_nothing_was_going_to_open(self):
        cfg = _cfg(asset_class="forex", symbols=())
        _notify(cfg)
        body = _notes(cfg.user).first().body
        self.assertIn("scans no symbols", body)
        self.assertIn("TAKE TRADE", body)
        self.assertNotIn("has stopped opening", body)

    def test_a_scanning_config_IS_told_it_stopped_opening(self):
        """The guard must not swallow the case the alert exists for."""
        cfg = _cfg(name="starter_megacaps", asset_class="stock",
                   symbols=("AAPL", "MSFT"))
        _notify(cfg)
        body = _notes(cfg.user).first().body
        self.assertIn("has stopped opening", body)

    def test_the_reason_survives_in_both_shapes(self):
        """Whatever else the body says, the operator must be able to read WHY
        without opening another page."""
        for symbols in ((), ("AAPL",)):
            cfg = _cfg(name=f"c{len(symbols)}", symbols=symbols)
            _notify(cfg, reasons=("drawdown 12.3% from peak",))
            self.assertIn("drawdown 12.3%", _notes(cfg.user).first().body)


class TheManualLaneIsNotGatedByTheseBreakersTests(SimpleTestCase):
    """The claim the new alert body makes, pinned against the code that has
    to stay true for it: if TAKE TRADE ever starts consulting CircuitBreakers,
    the message becomes the lie it replaced."""

    def test_the_manual_trade_module_does_not_consult_the_breakers(self):
        import inspect

        from bot_program import manual_trade
        src = inspect.getsource(manual_trade)
        self.assertNotIn("CircuitBreakers", src)
        self.assertNotIn("can_open_new", src)


class TheIbkrHelpTextTellsTheTruthAboutCollisionsTests(SimpleTestCase):
    """An operator picks this number while setting up a funded account. The
    help said IBKR evicts the earlier holder; it REFUSES the newcomer with
    error 326. Believing the old text, a collision reads as "something stole
    my session" instead of "my second socket was turned away", which sends
    the diagnosis in the wrong direction at the worst moment."""

    def test_it_does_not_promise_an_eviction(self):
        from bot_program.models import IBKRAccount
        help_text = IBKRAccount._meta.get_field("client_id").help_text
        self.assertNotIn("evicts", help_text)

    def test_it_names_the_refusal_and_its_error_code(self):
        from bot_program.models import IBKRAccount
        help_text = IBKRAccount._meta.get_field("client_id").help_text
        self.assertIn("REFUSES", help_text)
        self.assertIn("326", help_text)


class TheRenderedEnvDoesNotContradictItselfTests(TestCase):
    """`ibkr-apply` captures stdout and splices .env itself; render's stderr
    goes straight to the operator's terminal. A successful apply therefore
    printed "Nothing written. Re-run with --write" immediately above
    "applied to .../.env" — the alarming line first. Read during a live
    cutover, that says the credential did not land."""

    def _run(self, *args):
        from io import StringIO

        from django.core.management import call_command
        out, err = StringIO(), StringIO()
        call_command("render_ibkr_env", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_quiet_suppresses_the_trailer_and_keeps_the_block(self):
        out, err = self._run("--quiet")
        self.assertNotIn("Nothing written", err)
        self.assertIn("IBKR", out)

    def test_without_quiet_a_human_still_gets_the_advice(self):
        _out, err = self._run()
        self.assertIn("Nothing written", err)

    def test_the_apply_script_passes_quiet(self):
        """The fix is only a fix if the caller opts into it."""
        from pathlib import Path

        from django.conf import settings
        script = (Path(settings.BASE_DIR) / "deploy" / "ibkr-apply")
        text = script.read_text(encoding="utf-8")
        self.assertIn("render_ibkr_env --quiet", text)
