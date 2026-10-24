"""Every door that checks the trading PIN counts on one session counter.

The operator's decisions of 2026-10-23 ("Oui fait les deux"):

* D1. Every door that checks the trading PIN counts wrong answers on the
  idle lock's own session counter (core/trading_pin.py is THE check).
  A STOPPING door (closing a position, close-all, close-selected, both
  kill switches, a stop edit that only tightens) counts a wrong PIN but
  never logs the operator out, and a right PIN always stops, whatever
  the counter says. Every other door follows the switch's rule: the
  fifth wrong answer ends the session, and a spent counter ends it
  before any hash is checked.
* D2. The system map and the admin bot panel ask for the acting user's
  PIN to arm a live bot. Turning one OFF stays free; paper is unchanged.

Each door is driven through its real URL. What a door would do once the
PIN checks out is observed through a sentinel patched BEHIND the check,
so no broker is ever reached. The PIN is a test-only value set through
the profile's own helper (tests/test_switch_pin.py).

Run with:  python manage.py test tests.test_pin_wide
"""
import ast
import json
import logging
import os
import re
import threading
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.db.models import Max
from django.test import Client, RequestFactory, TestCase, TransactionTestCase

from tests.test_switch_pin import TEST_PIN, WRONG_PIN, _set_count, _set_pin

User = get_user_model()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The session counter's key and limit, as the idle lock has always had
#: them (dashboard/lock_views.py).
ATTEMPTS_KEY = "pin_lock_attempts"
MAX = 5

STOP_DOORS = ("S1", "S2", "S3", "S4", "S5", "M1t")
ACT_DOORS = ("M1w", "N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9",
             "N10", "N11", "N12", "N13", "N14", "N15", "N16", "N17", "N18",
             "G1", "G2", "G3")
ALL_DOORS = STOP_DOORS + ACT_DOORS + ("L1",)


def _tp():
    """The module under test, imported late: before it exists, each test
    that needs it fails on its own instead of the whole file."""
    import core.trading_pin as m
    return m


def _src(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _pin_rows(kind=None, since=0):
    """The chain's pin_* rows, oldest first; `since` fences off the rows
    an earlier door wrote (the chain is hash-linked: never deleted)."""
    from bot_program.audit_models import AuditLogEntry
    rows = AuditLogEntry.objects.filter(kind__startswith="pin_",
                                        id__gt=since)
    if kind:
        rows = rows.filter(kind=kind)
    return list(rows.order_by("id"))


def _row_mark():
    from bot_program.audit_models import AuditLogEntry
    return AuditLogEntry.objects.aggregate(m=Max("id"))["m"] or 0


def _join_alarms(timeout=5):
    """The alarm's Telegram call runs on its own short thread: wait for
    every one of them before counting what was sent."""
    for t in threading.enumerate():
        if t.name == _tp().ALARM_THREAD:
            t.join(timeout)


def _legacy_rows(kind):
    from bot_program.audit_models import AuditLogEntry
    return list(AuditLogEntry.objects.filter(kind=kind).order_by("id"))


def _real_check_password():
    from django.contrib.auth import hashers
    return hashers.check_password


class _BenchMixin:
    """One superuser with a PIN set BEFORE the login (so the session's
    login mark is current), a live book, and a sentinel behind every
    door."""

    def setUp(self):
        from bot_program.models import (AssetBotConfig, AssetBotTrade,
                                        BotConfig, EtoroAccount)
        from core import security
        from core.platform_control import seed_components
        from instruments.models import Instrument
        from signals.models import Signal

        cache.clear()
        security._login_attempts.clear()
        # The IP limiter is a module-level dict: leave it empty for the
        # next test in this process, whoever it is.
        self.addCleanup(security._login_attempts.clear)
        seed_components()
        self.admin = User.objects.create_superuser(
            "pw_admin", "pw_admin@example.test", "pw-of-the-test")
        _set_pin(self.admin)
        self.other = User.objects.create_user("pw_other", password="x")

        self.book = AssetBotConfig.objects.create(
            user=self.admin, asset_class="forex", name="pw_book",
            mode="live", enabled=True, symbols=[], capital=Decimal("1000"))
        self.trade = self._live_trade()
        self.arm_cfg = AssetBotConfig.objects.create(
            user=self.admin, asset_class="stock", name="pw_arm",
            mode="live", enabled=False, symbols=[], capital=Decimal("1000"))
        self.legacy = BotConfig.objects.create(user=self.admin, mode="live",
                                               enabled=False)
        self.legacy_other = BotConfig.objects.create(
            user=self.other, mode="live", enabled=False)
        inst = Instrument.objects.create(symbol="EURUSD", name="EURUSD",
                                         asset_class="forex", is_active=True)
        self.signal = Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="medium", title="pw signal", description="d",
            rule_name="pw_rule", score=0.8, sub_scores={},
            price_at_signal=Decimal("1.1"), is_active=True)
        acct = EtoroAccount.objects.create(user=self.other, demo=True)
        acct.set_credentials("pw-api-key", "pw-user-key")
        acct.save()

        self.live_ticket = True
        self.m = {}
        self._sentinels()
        self._login()
        self.row_mark = _row_mark()

    # ── fixtures ─────────────────────────────────────────────────────────
    def _live_trade(self, **kw):
        from bot_program.models import AssetBotTrade
        d = dict(config=self.book, asset_class="forex", symbol="EURUSD",
                 side="BUY", qty=Decimal("1000"),
                 entry_price=Decimal("1.1000"),
                 stop_loss=Decimal("1.0900"), take_profit=Decimal("1.1200"),
                 status="OPEN", paper=False, rule_name="pw_rule",
                 metadata={"initial_stop_loss": 1.09})
        d.update(kw)
        return AssetBotTrade.objects.create(**d)

    def _patch(self, name, target, **kw):
        p = mock.patch(target, **kw)
        self.m[name] = p.start()
        self.addCleanup(p.stop)
        return self.m[name]

    def _sentinels(self):
        from bot_program.share_allocator import ShareAllocatorError
        bench = self

        def ticket(name):
            def fake(*a, pin_ok=False, **kw):
                if bench.live_ticket and not pin_ok:
                    return {"error": "This is a LIVE order — real funds "
                                     "move. Enter your trading PIN to "
                                     "confirm"}
                bench.m[name + "_called"] = True
                return {"ok": True, "trade_id": 1}
            return fake

        def lane(user, *, asset_class, mode, capital=None, pin_ok=False,
                 track=None, share=None):
            if mode == "live" and not pin_ok:
                return {"error": "Arming the manual lane LIVE takes the "
                                 "trading PIN"}
            bench.m["arm_called"] = True
            return {"ok": True}

        self._patch("claim", "bot_program.manual_close._claim",
                    return_value=(None, "pw sentinel"))
        self._patch("kill", "bot_program.engine.kill_switch."
                            "execute_kill_switch", return_value={})
        self._patch("kill_alarm", "bot_program.alarm.after_kill_switch")
        self._patch("adjust", "bot_program.adjust_levels.adjust_levels",
                    return_value={"ok": True})
        self._patch("take", "bot_program.manual_trade.execute_take_trade",
                    side_effect=ticket("take"))
        self._patch("asset", "bot_program.manual_trade.execute_asset_trade",
                    side_effect=ticket("asset"))
        self._patch("arm", "bot_program.manual_trade.arm_manual_lane",
                    side_effect=lane)
        self._patch("pool", "portfolio.risk_gate.pool_vs_book",
                    return_value={"ok": True, "reason": ""})
        self._patch("equity", "bot_program.capital_truth.account_equity",
                    return_value=None)
        self._patch("persona", "bot_program.personas.apply_persona",
                    return_value={"ok": False, "reason": "pw sentinel",
                                  "warnings": []})
        self._patch("live_mode", "bot_program.share_allocator.is_live_mode",
                    return_value=True)
        self._patch("apply", "bot_program.share_allocator.apply_share_plan",
                    side_effect=ShareAllocatorError("pw sentinel"))
        self._patch("rollback",
                    "bot_program.share_allocator.rollback_share_plan",
                    side_effect=ShareAllocatorError("pw sentinel"))
        self._patch("own_plan", "dashboard.views_admin_hq._own_share_plan",
                    return_value=SimpleNamespace(pk=1))
        for name, fn in (("w_create", "create_request"),
                         ("w_paid", "mark_paid"),
                         ("w_cancel", "cancel_request"),
                         ("w_correct", "correct_paid")):
            self._patch(name, f"bot_program.withdrawals.{fn}",
                        return_value={"error": "pw sentinel"})
        self._patch("own_wr", "dashboard.views_withdrawals._own_request",
                    return_value=SimpleNamespace(
                        pk=1, amount=Decimal("1"), currency="USD"))
        self._patch("probe", "dashboard.views_brokers.etoro_probe",
                    return_value=("fail", "pw sentinel"))

    def _login(self):
        """A fresh session (a new counter), logged in under the current
        PIN."""
        self.client.logout()
        cache.clear()
        self.client.force_login(self.admin)
        self.hash0 = self._hash()

    def _hash(self):
        from portfolio.trader_profile import TraderProfile
        return TraderProfile.objects.get(user=self.admin).access_pin_hash

    def _reset(self):
        from bot_program.models import AssetBotConfig, BotConfig
        from core.platform_control import PlatformComponent
        for name, m in self.m.items():
            if isinstance(m, mock.Mock):
                m.reset_mock()
        for flag in [k for k in self.m if k.endswith("_called")]:
            self.m.pop(flag)
        BotConfig.objects.filter(pk__in=[self.legacy.pk,
                                         self.legacy_other.pk]) \
            .update(enabled=False, mode="live")
        AssetBotConfig.objects.filter(pk=self.arm_cfg.pk).update(
            enabled=False, mode="live")
        AssetBotConfig.objects.filter(name="pw_new").delete()
        PlatformComponent.objects.filter(key="aragorn").update(
            is_enabled=False)
        _set_pin(self.admin)
        self.live_ticket = True
        self._login()
        self.row_mark = _row_mark()

    # ── the doors ────────────────────────────────────────────────────────
    def _json(self, url, body):
        return self.client.post(url, json.dumps(body),
                                content_type="application/json")

    def fire(self, door, pin):
        self._last = getattr(self, "door_" + door)(pin)
        return self._last

    def door_S1(self, pin):
        return self._json(f"/positions/{self.trade.pk}/close/", {"pin": pin})

    def door_S2(self, pin):
        return self._json("/positions/close-all/", {"pin": pin})

    def door_S3(self, pin):
        return self._json("/positions/close-selected/",
                          {"ids": [self.trade.pk], "pin": pin})

    def door_S4(self, pin):
        return self._json("/api/kill-switch/", {"pin": pin})

    def door_S5(self, pin):
        return self.client.post("/admin-hq/flatten-all/", {"pin": pin})

    def door_M1t(self, pin):
        # The level dialog's real body: the stored target is pre-filled
        # and always sent (static/js/sv-level-edit.js).
        return self._json(f"/positions/{self.trade.pk}/levels/",
                          {"stop": "1.0950", "target": "1.1200",
                           "clear_target": False, "pin": pin})

    def door_M1w(self, pin):
        return self._json(f"/positions/{self.trade.pk}/levels/",
                          {"stop": "1.0800", "target": "1.1200",
                           "clear_target": False, "pin": pin})

    def door_N1(self, pin):
        return self._json(f"/signals/{self.signal.pk}/take-trade/",
                          {"pin": pin})

    def door_N2(self, pin):
        return self._json("/instruments/EURUSD/take-trade/",
                          {"side": "BUY", "pin": pin})

    def door_N3(self, pin):
        return self._json("/take-trade/arm/",
                          {"asset_class": "forex", "mode": "live",
                           "pin": pin})

    def door_N4(self, pin):
        return self.client.post("/bot/toggle/", {"pin": pin})

    def door_N5(self, pin):
        return self.client.post("/admin-dashboard/asset-bots/create/",
                                {"asset_class": "forex", "name": "pw_new",
                                 "mode": "live", "pin": pin})

    def door_N6(self, pin):
        return self.client.post("/admin-dashboard/asset-bots/toggle/",
                                {"config_id": self.arm_cfg.pk, "pin": pin})

    def door_N7(self, pin):
        return self.client.post("/admin-dashboard/asset-bots/follow/",
                                {"config_id": self.book.pk, "follow": "1",
                                 "pin": pin})

    def door_N8(self, pin):
        from bot_program.personas import PERSONA_KEYS
        return self.client.post("/admin-dashboard/personas/apply/",
                                {"config_id": self.book.pk,
                                 "persona": PERSONA_KEYS[0], "pin": pin})

    def door_N9(self, pin):
        return self.client.post("/admin-dashboard/shares/apply/",
                                {"plan_id": "1", "pin": pin})

    def door_N10(self, pin):
        return self.client.post("/admin-dashboard/shares/rollback/",
                                {"plan_id": "1", "pin": pin})

    def door_N11(self, pin):
        return self.client.post("/withdrawals/request/",
                                {"amount": "1", "pin": pin})

    def door_N12(self, pin):
        return self.client.post("/withdrawals/1/paid/", {"pin": pin})

    def door_N13(self, pin):
        return self.client.post("/withdrawals/1/cancel/", {"pin": pin})

    def door_N14(self, pin):
        return self.client.post("/withdrawals/1/correct/", {"pin": pin})

    def door_N15(self, pin):
        return self.client.post("/admin-dashboard/brokers/etoro/save/",
                                {"target_username": "pw_other",
                                 "etoro_api_key": "k2",
                                 "etoro_user_key": "u2", "pin": pin})

    def door_N16(self, pin):
        return self.client.post("/profile/change-pin-modal/",
                                {"current_pin": pin, "new_pin": TEST_PIN,
                                 "confirm_pin": TEST_PIN})

    def door_N17(self, pin):
        return self.client.post("/profile/change-pin/",
                                {"current_pin": pin, "new_pin": TEST_PIN,
                                 "confirm_pin": TEST_PIN})

    def door_N18(self, pin):
        return self.client.post("/admin-dashboard/toggle/",
                                {"key": "aragorn", "next": "ops",
                                 "want": "on", "pin": pin})

    def door_G1(self, pin):
        return self.client.post("/admin-dashboard/system-map/toggle/",
                                {"kind": "bot", "key": self.arm_cfg.pk,
                                 "want": "on", "pin": pin})

    def door_G2(self, pin):
        return self.client.post(
            f"/htmx/admin/bots/{self.legacy_other.pk}/toggle/",
            {"want": "on", "pin": pin})

    def door_G3(self, pin):
        return self.client.post("/bot/console/pause/",
                                {"want": "on", "pin": pin})

    def door_L1(self, pin):
        s = self.client.session
        s["pin_locked"] = True
        s.save()
        r = self.client.post("/api/session/unlock/", {"pin": pin})
        if "_auth_user_id" in self.client.session:
            s = self.client.session      # the fixture lifts its own flag
            s.pop("pin_locked", None)
            s.save()
        return r

    def acted(self, door):
        from bot_program.models import AssetBotConfig, BotConfig
        from core.platform_control import PlatformComponent
        if door in ("S1", "S2", "S3"):
            return self.m["claim"].called
        if door in ("S4", "S5"):
            return self.m["kill"].called
        if door in ("M1t", "M1w"):
            return self.m["adjust"].called
        if door == "N1":
            return bool(self.m.get("take_called"))
        if door == "N2":
            return bool(self.m.get("asset_called"))
        if door == "N3":
            return bool(self.m.get("arm_called"))
        if door in ("N4", "G3"):
            return BotConfig.objects.get(pk=self.legacy.pk).enabled
        if door == "G2":
            return BotConfig.objects.get(pk=self.legacy_other.pk).enabled
        if door == "N5":
            return AssetBotConfig.objects.filter(name="pw_new").exists()
        if door in ("N6", "G1"):
            return AssetBotConfig.objects.get(pk=self.arm_cfg.pk).enabled
        if door == "N7":
            return self.m["equity"].called
        if door == "N8":
            return self.m["persona"].called
        if door == "N9":
            return self.m["apply"].called
        if door == "N10":
            return self.m["rollback"].called
        if door == "N11":
            return self.m["w_create"].called
        if door == "N12":
            return self.m["w_paid"].called
        if door == "N13":
            return self.m["w_cancel"].called
        if door == "N14":
            return self.m["w_correct"].called
        if door == "N15":
            return self.m["probe"].called
        if door in ("N16", "N17"):
            return self._hash() != self.hash0
        if door == "N18":
            return PlatformComponent.objects.get(key="aragorn").is_enabled
        if door == "L1":
            return self._last.json().get("status") == "ok"
        raise AssertionError(door)

    # ── reading the answers ──────────────────────────────────────────────
    def said(self, resp):
        """Every word the door answered: JSON fields or this request's
        flashes."""
        if "json" in (resp.get("Content-Type") or ""):
            j = resp.json()
            out = [str(j.get(k, "")) for k in ("error", "message", "status",
                                               "detail")]
            out += [str(f.get("error", "")) for f in j.get("failed") or []]
            return " ".join(out)
        return " | ".join(str(m) for m in get_messages(resp.wsgi_request))

    def count(self):
        return int(self.client.session.get(ATTEMPTS_KEY, 0) or 0)

    def alive(self):
        return "_auth_user_id" in self.client.session

    def spend(self, n=MAX):
        """This session has given `n` wrong answers (the cache's count and
        the session's copy)."""
        _set_count(self.client.session, n)

    def stale_mirror(self, n):
        """A stale write of the session's own copy alone."""
        s = self.client.session
        s[ATTEMPTS_KEY] = n
        s.save()

    def mark_stale(self):
        """The PIN changed after this session logged in (any door)."""
        _set_pin(self.admin, WRONG_PIN)


class _Bench(_BenchMixin, TestCase):
    pass


# ══ A. the check itself ═══════════════════════════════════════════════════
class TheCheckTests(_Bench):

    def _req(self):
        from importlib import import_module
        from django.conf import settings
        engine = import_module(settings.SESSION_ENGINE)
        r = RequestFactory().post("/pw/")
        r.session = engine.SessionStore(
            self.client.cookies[settings.SESSION_COOKIE_NAME].value)
        r.user = self.admin
        return r

    def test_a_door_class_is_required(self):
        tp = _tp()
        r = self._req()
        with self.assertRaises(TypeError):
            tp.check(r, TEST_PIN, act="pw")             # noqa: the point
        with self.assertRaises(TypeError):
            tp.check(r, TEST_PIN, door=tp.STOP)         # no act either
        with self.assertRaises(ValueError):
            tp.check(r, TEST_PIN, door="close", act="pw")
        with self.assertRaises(TypeError):
            tp.gate(r, TEST_PIN, act="pw")
        with self.assertRaises(ValueError):
            tp.gate(r, TEST_PIN, door="close", act="pw")
        self.assertEqual(tp.DOOR_CLASSES, {tp.STOP, tp.ACT, tp.LOCK})

    def test_the_rule_table_at_a_stop_door(self):
        tp = _tp()
        r = self._req()
        v = tp.check(r, "", door=tp.STOP, act="pw stop")
        self.assertEqual((v.ok, v.refusal), (False, tp.PIN_MISSING))
        self.assertEqual(tp.attempts(r), 0)
        for n in range(1, MAX):
            v = tp.check(r, WRONG_PIN, door=tp.STOP, act="pw stop")
            self.assertEqual((v.ok, v.refusal, v.attempts_left, v.spent,
                              v.logged_out),
                             (False, tp.PIN_WRONG, MAX - n, False, False))
        v = tp.check(r, WRONG_PIN, door=tp.STOP, act="pw stop")
        self.assertEqual((v.refusal, v.spent, v.logged_out),
                         (tp.PIN_WRONG, True, False))
        for _ in range(10):
            v = tp.check(r, WRONG_PIN, door=tp.STOP, act="pw stop")
            self.assertFalse(v.logged_out)
        self.assertEqual(r.user, self.admin)            # never logged out
        r.session.pop(tp.LOGIN_MARK_KEY, None)          # a STOP door ignores it
        v = tp.check(r, TEST_PIN, door=tp.STOP, act="pw stop")
        self.assertEqual((v.ok, v.spent), (True, True))
        self.assertGreaterEqual(tp.attempts(r), MAX)    # not cleared

    def test_the_rule_table_at_an_act_door(self):
        tp = _tp()
        r = self._req()
        v = tp.check(r, "  ", door=tp.ACT, act="pw act")
        self.assertEqual(v.refusal, tp.PIN_MISSING)
        mark = r.session.pop(tp.LOGIN_MARK_KEY)
        with mock.patch("core.trading_pin._hash_ok") as hashed:
            v = tp.check(r, TEST_PIN, door=tp.ACT, act="pw act")
        self.assertEqual(v.refusal, tp.LOGIN_AGAIN)
        self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
        self.assertEqual(tp.attempts(r), 0)             # not a guess
        r.session[tp.LOGIN_MARK_KEY] = mark
        for n in range(1, MAX):
            v = tp.check(r, WRONG_PIN, door=tp.ACT, act="pw act")
            self.assertEqual((v.refusal, v.attempts_left), (tp.PIN_WRONG,
                                                             MAX - n))
        v = tp.check(r, TEST_PIN, door=tp.ACT, act="pw act")
        self.assertTrue(v.ok)
        self.assertEqual(tp.attempts(r), 0)             # a right answer clears
        for _ in range(MAX - 1):
            tp.check(r, WRONG_PIN, door=tp.ACT, act="pw act")
        v = tp.check(r, WRONG_PIN, door=tp.ACT, act="pw act")
        self.assertEqual((v.refusal, v.logged_out), (tp.LOCKED_OUT, True))
        self.assertFalse(r.user.is_authenticated)

    def test_a_spent_counter_ends_an_act_door_before_blank_or_hash(self):
        tp = _tp()
        for pin in ("", TEST_PIN):
            with self.subTest(pin=bool(pin)):
                self._login()
                r = self._req()
                _set_count(r.session, MAX)
                with mock.patch("core.trading_pin._hash_ok") as hashed:
                    v = tp.check(r, pin, door=tp.ACT, act="pw act")
                self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
                self.assertEqual((v.refusal, v.logged_out),
                                 (tp.LOCKED_OUT, True))

    def test_the_rule_table_at_the_lock(self):
        tp = _tp()
        r = self._req()
        v = tp.check(r, "", door=tp.LOCK, act="Idle lock")
        self.assertEqual(v.refusal, tp.PIN_MISSING)
        self.assertEqual(tp.attempts(r), 0)
        r.session.pop(tp.LOGIN_MARK_KEY, None)          # the lock ignores it
        v = tp.check(r, WRONG_PIN, door=tp.LOCK, act="Idle lock")
        self.assertEqual(v.attempts_left, MAX - 1)
        v = tp.check(r, TEST_PIN, door=tp.LOCK, act="Idle lock")
        self.assertTrue(v.ok)
        self.assertEqual(tp.attempts(r), 0)
        # A1: a spent session behind the lock gets one guess per lock.
        _set_count(r.session, MAX)
        v = tp.check(r, TEST_PIN, door=tp.LOCK, act="Idle lock")
        self.assertEqual((v.ok, v.spent), (True, True))
        self.assertGreaterEqual(tp.attempts(r), MAX)    # not cleared
        v = tp.check(r, WRONG_PIN, door=tp.LOCK, act="Idle lock")
        self.assertEqual((v.refusal, v.logged_out), (tp.LOCKED_OUT, True))

    def test_blank_and_pinless_are_never_counted_at_any_door(self):
        tp = _tp()
        bare = User.objects.create_superuser("pw_bare", "b@x.test", "x")
        for door in (tp.STOP, tp.ACT, tp.LOCK):
            with self.subTest(door=door):
                self._login()
                r = self._req()
                for _ in range(8):
                    v = tp.check(r, "", door=door, act="pw")
                    self.assertEqual(v.refusal, tp.PIN_MISSING)
                self.assertEqual(tp.attempts(r), 0)
                r.user = bare
                for _ in range(8):
                    v = tp.check(r, WRONG_PIN, door=door, act="pw")
                    self.assertEqual(v.refusal, tp.PIN_NOT_SET)
                self.assertEqual(tp.attempts(r), 0)
        # ...and the profile is read, never created (critique A6)
        from portfolio.trader_profile import TraderProfile
        self.assertFalse(TraderProfile.objects.filter(user=bare).exists())

    def test_an_overwritten_session_does_not_reset_the_count(self):
        """A request that loaded the session before a wrong answer and
        saved it after must not write the count back down."""
        s = self.client.session
        s["pin_locked"] = True
        s.save()
        stale = self.client.session
        dict(stale.items())                             # loaded now
        r = self.client.post("/api/session/unlock/", {"pin": WRONG_PIN})
        self.assertEqual(r.json()["attempts_left"], MAX - 1)
        stale.save()                                    # the old dict wins
        r = self.client.post("/api/session/unlock/", {"pin": WRONG_PIN})
        self.assertEqual(r.json()["attempts_left"], MAX - 2)

    def test_a_reservation_past_five_is_never_checked_at_an_act_door(self):
        """A parallel guess read the counter below five, and reserved the
        sixth: it ends the session with no hash checked."""
        tp = _tp()
        r = self._req()
        for _ in range(MAX):
            tp.check(r, WRONG_PIN, door=tp.STOP, act="pw stop")
        r.session[ATTEMPTS_KEY] = 0                     # a stale mirror
        with mock.patch("core.trading_pin.attempts", return_value=0), \
                mock.patch("core.trading_pin._hash_ok") as hashed:
            v = tp.check(r, TEST_PIN, door=tp.ACT, act="pw act")
        self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
        self.assertEqual((v.refusal, v.logged_out), (tp.LOCKED_OUT, True))

    def test_the_gate_is_lazy_and_counts_once(self):
        tp = _tp()
        r = self._req()
        g = tp.gate(r, WRONG_PIN, door=tp.ACT, act="pw act")
        self.assertIsNone(g.verdict)
        self.assertIsNone(tp.refusal_of(g))
        self.assertEqual(tp.attempts(r), 0)
        self.assertFalse(g)
        self.assertFalse(g)                              # asked twice
        self.assertEqual(tp.attempts(r), 1)
        self.assertEqual(tp.refusal_of(g).refusal, tp.PIN_WRONG)
        self.assertIsNone(tp.refusal_of(True))
        self.assertIsNone(tp.refusal_of(False))

    def test_the_new_audit_kinds_fit_the_column_with_no_migration(self):
        from bot_program.audit import AUDIT_KINDS_PIN
        from bot_program.audit_models import AuditLogEntry
        width = AuditLogEntry._meta.get_field("kind").max_length
        choices = {k for k, _ in AuditLogEntry.KIND_CHOICES}
        self.assertTrue(AUDIT_KINDS_PIN)
        for kind in AUDIT_KINDS_PIN:
            self.assertLessEqual(len(kind), width, kind)
            self.assertNotIn(kind, choices)              # no migration

    def test_audit_rows_carry_no_pin_length_or_hash(self):
        from core.audit import AuditLog
        grabbed = []

        class _Grab(logging.Handler):
            def emit(self, record):
                grabbed.append(record.getMessage())

        h = _Grab(level=logging.DEBUG)
        logging.getLogger().addHandler(h)
        self.addCleanup(logging.getLogger().removeHandler, h)
        for _ in range(MAX + 1):
            self.fire("S4", WRONG_PIN)
        self.fire("S4", TEST_PIN)                       # pin_ok_spent
        self._login()
        for _ in range(MAX):
            self.fire("N3", WRONG_PIN)                  # session ended
        self._login()
        self.mark_stale()
        self.fire("N3", WRONG_PIN)                      # log in again
        rows = _pin_rows()
        kinds = {r.kind for r in rows}
        self.assertTrue({"pin_refused", "pin_spent", "pin_ok_spent"} <= kinds,
                        kinds)
        texts = [json.dumps(r.data, sort_keys=True) for r in rows]
        texts += [a.description for a in AuditLog.objects.all()]
        texts += grabbed
        texts.append(json.dumps(dict(self.client.session.items()),
                                default=str))
        stored = self._hash()
        for t in texts:
            for secret in (TEST_PIN, WRONG_PIN, stored, stored[-20:]):
                self.assertNotIn(secret, t)
            self.assertNotRegex(t, rf"\b{len(TEST_PIN)}[- ]digit")
        for r in rows:
            self.assertEqual(r.data.get("who"), "pw_admin")

    def test_fifty_wrong_answers_at_a_stop_door_write_a_bounded_chain(self):
        """Critique A4: past five, guesses at a stopping door are
        unlimited by design; the tamper-evident chain must not be."""
        for _ in range(50):
            self.fire("S1", WRONG_PIN)
        self.assertTrue(self.alive())
        rows = _pin_rows()
        self.assertGreaterEqual(len(rows), MAX)          # 1..5 recorded
        self.assertLessEqual(len(rows), MAX + 2)
        self.assertEqual(len(_pin_rows("pin_spent")), 1)
        self.assertFalse(_pin_rows("pin_spent")[0].data["ended"])

    def test_log_in_again_is_recorded_once_per_act(self):
        self.mark_stale()
        for _ in range(10):
            self.fire("N3", TEST_PIN)
        again = [r for r in _pin_rows("pin_refused")
                 if r.data.get("reason") == "login_again"]
        self.assertEqual(len(again), 1)
        self.assertEqual(self.count(), 0)

    def test_the_alarm_rings_once_and_never_for_a_contained_session(self):
        """Critique A7: the alarm chat hears a PIN found after five misses
        or active probing at a stopping door, once per session; never the
        operator's own typos at the lock, nor a session already ended."""
        from tests.test_alarm_bot import MONEY
        with mock.patch("bot_program.alarm.send_alarm",
                        return_value=True) as send:
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(MAX):
                    self.fire("L1", WRONG_PIN)          # ended at the lock
            _join_alarms()
            self.assertEqual(send.call_count, 0)
            self._login()
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(MAX):
                    self.fire("N3", WRONG_PIN)          # ended at an ACT door
            _join_alarms()
            self.assertEqual(send.call_count, 0)
            self._login()
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(MAX):
                    self.fire("S1", WRONG_PIN)
            _join_alarms()
            self.assertEqual(send.call_count, 0)        # five typos: quiet
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(MAX * 3):
                    self.fire("S1", WRONG_PIN)
                self.fire("S1", TEST_PIN)
            _join_alarms()
            self.assertEqual(send.call_count, 1)        # once per session
        title, lines = send.call_args[0][0], send.call_args[0][1]
        text = " ".join([title, *lines])
        self.assertIsNone(MONEY.search(text), text)
        self.assertIn("pw_admin", text)
        self.assertNotIn(TEST_PIN, text)

    def test_a_right_pin_at_a_stop_door_stops_even_when_its_records_fail(self):
        """Critique A6: the cache, the chain and the AuditLog may all fail;
        a right PIN at a stopping door still stops, and no exception text
        reaches the page."""
        boom = RuntimeError("pw boom")
        with mock.patch("bot_program.audit.record_event", side_effect=boom), \
                mock.patch("core.audit.AuditLog.objects.create",
                           side_effect=boom), \
                mock.patch("django.core.cache.cache.incr", side_effect=boom), \
                mock.patch("django.core.cache.cache.add", side_effect=boom):
            for _ in range(MAX + 1):
                r = self.fire("S1", WRONG_PIN)
                self.assertNotIn("pw boom", r.content.decode())
            self.assertTrue(self.alive())
            self.assertGreaterEqual(self.count(), MAX)  # the session's copy
            r = self.fire("S1", TEST_PIN)
        self.assertTrue(self.acted("S1"))
        self.assertNotIn("pw boom", r.content.decode())

    def test_a_right_pin_at_a_stop_door_stops_when_the_check_itself_fails(
            self):
        """An error that escapes the check's own fences (here the counter)
        reaches its fallback: a right PIN at a stopping door still stops, a
        wrong one is still refused, and no exception text reaches the
        page."""
        boom = RuntimeError("pw boom")
        for door in ("S1", "S4"):
            with self.subTest(door=door):
                self._reset()
                with mock.patch("core.trading_pin._reserve",
                                side_effect=boom):
                    r = self.fire(door, WRONG_PIN)
                    self.assertFalse(self.acted(door))
                    self.assertNotIn("pw boom", r.content.decode())
                    r = self.fire(door, TEST_PIN)
                self.assertTrue(self.acted(door))
                self.assertTrue(self.alive())
                self.assertNotIn("pw boom", r.content.decode())

    def test_a_stale_session_save_cannot_bring_a_cleared_count_back(self):
        """A request that loaded the session before a right PIN cleared the
        count, and saved it after, writes back the old copy; the cache's
        count, the authority, stays at zero."""
        self.fire("L1", WRONG_PIN)
        self.fire("L1", WRONG_PIN)
        self.assertEqual(self.count(), 2)
        stale = self.client.session
        dict(stale.items())                             # loaded now, at 2
        self.fire("N3", TEST_PIN)                       # a right answer
        self.assertTrue(self.acted("N3"))
        self.assertEqual(self.count(), 0)
        stale.save()                                    # the old dict wins
        self.assertEqual(self.count(), 2)               # the stale copy...
        self.assertEqual(_tp().attempts(
            SimpleNamespace(session=self.client.session)), 0)  # ...overruled
        r = self.fire("L1", WRONG_PIN)
        self.assertEqual(r.json()["attempts_left"], MAX - 1)
        for _ in range(MAX - 2):
            self.fire("L1", WRONG_PIN)
        self.assertTrue(self.alive())                   # four, not five

    def test_the_lock_never_counts_a_blank_pin(self):
        s = self.client.session
        s["pin_locked"] = True
        s.save()
        for _ in range(MAX + 1):
            r = self.client.post("/api/session/unlock/", {"pin": ""})
            self.assertEqual(r.json(), {"status": "error",
                                        "error": "Enter your PIN."})
        self.assertEqual(self.count(), 0)
        self.assertTrue(self.alive())
        self.assertTrue(self.client.session.get("pin_locked"))


# ══ B. every door counts, on the one counter ══════════════════════════════
class EveryDoorCountsTests(_Bench):

    def test_every_door_counts_a_wrong_pin_on_the_shared_counter(self):
        for door in ALL_DOORS:
            with self.subTest(door=door):
                self._reset()
                self.fire(door, WRONG_PIN)
                self.assertEqual(self.count(), 1)
                self.assertFalse(self.acted(door))
                self.assertTrue(self.alive())
                for _ in range(MAX - 1):
                    self.fire("L1", WRONG_PIN)
                self.assertFalse(self.alive())          # the same five

    def test_the_fifth_wrong_at_every_act_door_ends_the_session(self):
        from core.audit import AuditLog
        for door in ACT_DOORS + ("L1",):
            with self.subTest(door=door):
                self._reset()
                AuditLog.objects.all().delete()
                for _ in range(MAX - 1):
                    self.fire(door, WRONG_PIN)
                    self.assertTrue(self.alive())
                r = self.fire(door, WRONG_PIN)
                self.assertFalse(self.alive())
                self.assertFalse(self.acted(door))
                said = self.said(r)
                if door == "L1":
                    self.assertIn("logged_out", said)
                else:
                    self.assertIn("session has ended", said)
                self.assertTrue(AuditLog.objects.filter(
                    user=self.admin, action="login",
                    description__contains="session terminated").exists())
                spent = _pin_rows("pin_spent", since=self.row_mark)
                self.assertTrue(spent)                  # this door's own row
                self.assertTrue(spent[-1].data["ended"])

    def test_no_stop_door_ever_ends_the_session(self):
        for door in STOP_DOORS:
            with self.subTest(door=door):
                self._reset()
                for _ in range(20):
                    self.fire(door, WRONG_PIN)
                self.assertTrue(self.alive())
                self.assertEqual(self.client.get("/ops/").status_code, 200)
                self.assertGreaterEqual(self.count(), MAX)
                self.assertFalse(self.acted(door))
                spent = _pin_rows("pin_spent", since=self.row_mark)
                self.assertTrue(spent)                  # this door's own row
                self.assertFalse(spent[-1].data["ended"])

    def test_every_stop_door_stops_on_the_right_pin_with_a_spent_counter(self):
        for door in STOP_DOORS:
            with self.subTest(door=door):
                self._reset()
                for _ in range(MAX):
                    self.fire(door, WRONG_PIN)
                self.fire(door, TEST_PIN)
                self.assertTrue(self.acted(door))
                self.assertTrue(self.alive())
                self.assertTrue(_pin_rows("pin_ok_spent",
                                          since=self.row_mark))

    def test_a_right_pin_at_a_stop_door_does_not_clear_a_spent_counter(self):
        for door in STOP_DOORS:
            with self.subTest(door=door):
                self._reset()
                self.spend()
                self.fire(door, TEST_PIN)
                self.assertTrue(self.acted(door))
                self.assertGreaterEqual(self.count(), MAX)
                self.assertTrue(_pin_rows("pin_ok_spent",
                                          since=self.row_mark))
                with mock.patch("django.contrib.auth.hashers.check_password",
                                wraps=_real_check_password()) as hashed:
                    self.fire("N18", TEST_PIN)
                self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
                self.assertFalse(self.alive())
                self.assertFalse(self.acted("N18"))

    def test_a_parallel_reservation_past_five_still_stops_and_never_clears(
            self):
        """Critique A9: the cache holds MAX+3, the session's own copy 0
        (a stale write); the right PIN closes, the count survives, and the
        next act ends the session before any hash."""
        for _ in range(MAX + 3):
            self.fire("S4", WRONG_PIN)
        self.stale_mirror(0)
        self.fire("S1", TEST_PIN)
        self.assertTrue(self.acted("S1"))
        self.assertGreaterEqual(
            _tp().attempts(SimpleNamespace(session=self.client.session)), MAX)
        with mock.patch("django.contrib.auth.hashers.check_password",
                        wraps=_real_check_password()) as hashed:
            self.fire("N18", TEST_PIN)
        self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
        self.assertFalse(self.alive())

    def test_below_five_a_right_pin_clears_at_every_door(self):
        for door in ALL_DOORS:
            with self.subTest(door=door):
                self._reset()
                self.fire("L1", WRONG_PIN)
                self.fire("L1", WRONG_PIN)
                self.assertEqual(self.count(), 2)
                self.fire(door, TEST_PIN)
                self.assertTrue(self.acted(door))
                self.assertEqual(self.count(), 0)

    def test_a_spent_counter_ends_the_session_at_every_act_door_first(self):
        for door in ACT_DOORS:
            with self.subTest(door=door):
                self._reset()
                self.spend()
                with mock.patch("django.contrib.auth.hashers.check_password",
                                wraps=_real_check_password()) as hashed:
                    self.fire(door, TEST_PIN)
                self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
                self.assertFalse(self.alive())
                self.assertFalse(self.acted(door))

    def test_a_session_logged_in_before_the_pin_changed_cannot_act_but_can_stop(
            self):
        for door in ACT_DOORS:
            with self.subTest(door=door):
                self._reset()
                self.mark_stale()
                self.hash0 = self._hash()
                r = self.fire(door, WRONG_PIN)          # the NEW PIN
                self.assertIn("did not log in with your current trading PIN",
                              self.said(r))
                self.assertFalse(self.acted(door))
                self.assertEqual(self.count(), 0)       # not a guess
                self.assertTrue(self.alive())
        for door in STOP_DOORS + ("L1",):
            with self.subTest(door=door):
                self._reset()
                self.mark_stale()
                self.fire(door, WRONG_PIN)              # the NEW PIN stops
                self.assertTrue(self.acted(door))

    def test_paper_and_disarms_never_touch_the_counter(self):
        from bot_program.models import (AssetBotConfig, AssetBotTrade,
                                        BotConfig)
        paper_cfg = AssetBotConfig.objects.create(
            user=self.admin, asset_class="crypto", name="pw_paper",
            mode="paper", enabled=True, symbols=[], capital=Decimal("1000"))
        paper = self._live_trade(config=paper_cfg, paper=True,
                                 asset_class="crypto")
        AssetBotTrade.objects.filter(pk=self.trade.pk).update(status="CLOSED")
        self._json(f"/positions/{paper.pk}/close/", {"pin": WRONG_PIN})
        self.assertTrue(self.m["claim"].called)          # paper closed
        self._json("/positions/close-all/", {"pin": WRONG_PIN})
        self._json(f"/positions/{paper.pk}/levels/",
                   {"stop": "1.0800", "pin": WRONG_PIN})
        self.live_ticket = False
        self.fire("N1", WRONG_PIN)
        self.assertTrue(self.m.get("take_called"))
        self._json("/take-trade/arm/", {"asset_class": "forex",
                                        "mode": "paper", "pin": WRONG_PIN})
        AssetBotConfig.objects.filter(pk=self.arm_cfg.pk).update(enabled=True)
        self.client.post("/admin-dashboard/system-map/toggle/",
                         {"kind": "bot", "key": self.arm_cfg.pk,
                          "want": "off", "pin": WRONG_PIN})
        BotConfig.objects.filter(pk__in=[self.legacy.pk,
                                         self.legacy_other.pk]) \
            .update(enabled=True)
        self.client.post(f"/htmx/admin/bots/{self.legacy_other.pk}/toggle/",
                         {"want": "off", "pin": WRONG_PIN})
        self.client.post("/bot/console/pause/",
                         {"want": "off", "pin": WRONG_PIN})
        self.assertFalse(AssetBotConfig.objects.get(pk=self.arm_cfg.pk)
                         .enabled)
        self.assertFalse(BotConfig.objects.get(pk=self.legacy.pk).enabled)
        self.assertFalse(BotConfig.objects.get(pk=self.legacy_other.pk)
                         .enabled)
        # close-selected on a paper row, and the instrument page's paper
        # ticket: the PIN is never asked, so never counted
        self.m["claim"].reset_mock()
        self._json("/positions/close-selected/",
                   {"ids": [paper.pk], "pin": WRONG_PIN})
        self.assertTrue(self.m["claim"].called)          # paper closed
        self._json("/instruments/EURUSD/take-trade/",
                   {"side": "BUY", "pin": WRONG_PIN})
        self.assertTrue(self.m.get("asset_called"))
        self.assertEqual(self.count(), 0)
        # ...while a live close with the same wrong PIN counts.
        AssetBotTrade.objects.filter(pk=self.trade.pk).update(status="OPEN")
        self.fire("S1", WRONG_PIN)
        self.assertEqual(self.count(), 1)

    def test_close_all_counts_once_and_says_why_on_each_live_row(self):
        self._live_trade(symbol="GBPUSD")
        r = self.fire("S2", WRONG_PIN)
        self.assertEqual(self.count(), 1)
        j = r.json()
        self.assertNotIn("error", j)                    # never "unknown"
        self.assertEqual(j["n_failed"], 2)
        for row in j["failed"]:
            self.assertIn("Incorrect trading PIN", row["error"])
            self.assertIn(row["symbol"], row["error"])
            self.assertTrue(row["error"].endswith("."), row["error"])

    def test_close_selected_answers_its_403_with_the_sentence(self):
        r = self.fire("S3", WRONG_PIN)
        self.assertEqual(r.status_code, 403)
        j = r.json()
        self.assertTrue(j["pin_required"])
        self.assertIs(j["logged_out"], False)
        self.assertIn("Incorrect trading PIN", j["error"])
        self.assertEqual(j["closed"], [])

    def test_tightening_a_stop_is_a_stop_door_and_widening_is_not(self):
        for _ in range(MAX):
            self.fire("S1", WRONG_PIN)
        r = self.fire("M1t", TEST_PIN)                  # the dialog's body
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.acted("M1t"))
        self.assertTrue(self.alive())
        _, kw = self.m["adjust"].call_args
        self.assertTrue(kw.get("tighten_only"))
        self.m["adjust"].reset_mock()
        r = self.fire("M1w", TEST_PIN)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.json()["logged_out"])
        self.assertFalse(self.acted("M1w"))
        self.assertFalse(self.alive())

    def test_clearing_or_moving_the_target_is_not_a_stop_door(self):
        self.spend()
        r = self._json(f"/positions/{self.trade.pk}/levels/",
                       {"stop": "1.0950", "target": "1.1300",
                        "clear_target": False, "pin": TEST_PIN})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.alive())

    def test_an_edit_refused_on_its_own_merits_never_reaches_the_pin(self):
        """Critique A3: the stop edit's non-secret refusals come before the
        PIN, so a right PIN with a doomed edit is no silent oracle."""
        self.spend()
        for pin in (TEST_PIN, WRONG_PIN):
            with mock.patch("django.contrib.auth.hashers.check_password",
                            wraps=_real_check_password()) as hashed:
                r = self._json(f"/positions/{self.trade.pk}/levels/",
                               {"stop": "1.1300", "target": "1.1200",
                                "clear_target": False, "pin": pin})
            self.assertEqual(r.status_code, 400)
            self.assertIn("The stop is above the target", r.json()["error"])
            self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
            self.assertTrue(self.alive())
        self.assertEqual(self.count(), MAX)


class TightenOnlyUnderTheLockTests(TestCase):

    def test_a_tighten_only_edit_that_would_widen_under_the_lock_is_refused(
            self):
        from bot_program.adjust_levels import adjust_levels, tightens_only
        from bot_program.models import AssetBotConfig, AssetBotTrade
        user = User.objects.create_user("pw_lock_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="forex", name="pw_tl", mode="paper",
            enabled=True, symbols=[], capital=Decimal("1000"))
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol="PWXUSD", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("1.1000"),
            stop_loss=Decimal("1.0900"), take_profit=Decimal("1.1200"),
            status="OPEN", paper=True, metadata={"initial_stop_loss": 1.09})
        self.assertTrue(tightens_only(trade, "1.0950", "1.1200", False))
        self.assertTrue(tightens_only(trade, "1.0950", None, False))
        self.assertFalse(tightens_only(trade, "1.0800", None, False))
        self.assertFalse(tightens_only(trade, "1.0950", "1.1300", False))
        self.assertFalse(tightens_only(trade, "1.0950", None, True))
        self.assertFalse(tightens_only(trade, None, "1.1200", False))
        # the row moved under the dialog: the same stop now widens
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            stop_loss=Decimal("1.1000"))
        out = adjust_levels(user, trade, stop="1.0950", target="1.1200",
                            tighten_only=True)
        self.assertFalse(out["ok"])
        self.assertIn("enter it again", out["error"])
        trade.refresh_from_db()
        self.assertEqual(trade.stop_loss, Decimal("1.1000"))


# ══ C. the change-PIN oracle (guidance g) ═════════════════════════════════
class ChangePinTests(_Bench):

    def test_a_bad_new_pin_never_checks_the_current_one(self):
        answers = set()
        for current in (TEST_PIN, WRONG_PIN):
            with mock.patch("django.contrib.auth.hashers.check_password",
                            wraps=_real_check_password()) as hashed:
                r = self.client.post("/profile/change-pin-modal/",
                                     {"current_pin": current, "new_pin": "",
                                      "confirm_pin": ""})
            self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
            answers.add(json.dumps(r.json(), sort_keys=True))
        self.assertEqual(len(answers), 1, answers)
        self.assertEqual(self.count(), 0)

    def test_a_wrong_current_pin_is_counted_and_the_fifth_ends_the_session(
            self):
        for door in ("N16", "N17"):
            with self.subTest(door=door):
                self._reset()
                for n in range(1, MAX):
                    r = self.fire(door, WRONG_PIN)
                    self.assertEqual(self.count(), n)
                    self.assertIn("Incorrect trading PIN", self.said(r))
                r = self.fire(door, WRONG_PIN)
                self.assertFalse(self.alive())
                if door == "N16":
                    self.assertIs(r.json()["logged_out"], True)
                self.assertIn("session has ended", self.said(r))

    def test_the_forced_reset_still_waives_the_current_pin(self):
        s = self.client.session
        s["force_pin_reset"] = True
        s.save()
        r = self.client.post("/profile/change-pin-modal/",
                             {"new_pin": TEST_PIN, "confirm_pin": TEST_PIN})
        self.assertTrue(r.json()["ok"])
        self.assertNotEqual(self._hash(), self.hash0)
        self.assertEqual(self.count(), 0)
        # the session logged in on the password alone: the new PIN must
        # come through a login before it opens or arms anything
        r = self.fire("N3", TEST_PIN)
        self.assertIn("did not log in with your current trading PIN",
                      self.said(r))
        self.assertFalse(self.acted("N3"))

    def test_a_changed_pin_asks_for_a_new_login_before_any_live_act(self):
        r = self.client.post("/profile/change-pin-modal/",
                             {"current_pin": TEST_PIN, "new_pin": WRONG_PIN,
                              "confirm_pin": WRONG_PIN})
        self.assertTrue(r.json()["ok"])
        r = self.fire("N3", WRONG_PIN)
        self.assertIn("did not log in with your current trading PIN",
                      self.said(r))
        self.fire("S1", WRONG_PIN)                      # closing still works
        self.assertTrue(self.acted("S1"))

    def test_the_old_form_keeps_the_modals_rule_on_the_new_pin(self):
        r = self.client.post("/profile/change-pin/",
                             {"current_pin": TEST_PIN, "new_pin": "1" * 9,
                              "confirm_pin": "1" * 9})
        self.assertIn("PIN must be 4-8 digits.", self.said(r))
        self.assertEqual(self._hash(), self.hash0)


class ThePinIsAskedLastTests(_Bench):
    """The HQ create form and the HQ toggle ask for the PIN only after
    every refusal that holds no secret: a doomed save costs no guess, and
    no later refusal can tell a right PIN from a wrong one."""

    def test_the_create_forms_number_checks_come_before_the_pin(self):
        for pin in (WRONG_PIN, TEST_PIN):
            with self.subTest(right=pin == TEST_PIN):
                self._reset()
                with mock.patch("django.contrib.auth.hashers.check_password",
                                wraps=_real_check_password()) as hashed:
                    r = self.client.post(
                        "/admin-dashboard/asset-bots/create/",
                        {"asset_class": "forex", "name": "pw_new",
                         "mode": "live", "trail_pct": "abc", "pin": pin})
                self.assertIn("trail_pct must be a number", self.said(r))
                self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
                self.assertEqual(self.count(), 0)
                self.assertFalse(self.acted("N5"))

    def test_the_toggles_pool_check_comes_before_the_pin(self):
        self.m["pool"].return_value = {"ok": False, "reason": "pw pool"}
        for pin in (WRONG_PIN, TEST_PIN):
            with self.subTest(right=pin == TEST_PIN):
                with mock.patch("django.contrib.auth.hashers.check_password",
                                wraps=_real_check_password()) as hashed:
                    r = self.fire("N6", pin)
                self.assertIn("not armed", self.said(r))
                self.assertEqual(hashed.call_count, 0)   # never the args: they carry the PIN
                self.assertEqual(self.count(), 0)
                self.assertFalse(self.acted("N6"))


class ALoginStartsAFreshCountTests(_Bench):
    """The refusals of a spent session say "log in again"; a login over the
    live session (Django keeps the session and its key for the same user)
    is that fresh proof, so the count starts again from zero."""

    def test_logging_in_again_over_a_spent_session_clears_its_count(self):
        from core import security
        self.spend(MAX + 1)
        security._login_attempts.clear()
        r = self.client.post("/login/", {"username": "pw_admin",
                                         "password": "pw-of-the-test"})
        self.assertEqual(r.status_code, 302)            # to the PIN step
        r = self.client.post("/login/pin/", {"pin": TEST_PIN})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.alive())
        self.assertEqual(self.count(), 0)
        self.assertEqual(_tp().attempts(
            SimpleNamespace(session=self.client.session)), 0)
        r = self.fire("N3", TEST_PIN)                   # the right PIN arms
        self.assertTrue(self.acted("N3"))
        self.assertTrue(self.alive())
        self.assertNotIn("session has ended", self.said(r))

    def test_a_stale_save_after_the_login_cannot_bring_the_count_back(self):
        self.spend(MAX + 1)
        stale = self.client.session
        dict(stale.items())                             # loaded, spent
        self.client.force_login(self.admin)             # the same session
        stale.save()
        self.assertEqual(_tp().attempts(
            SimpleNamespace(session=self.client.session)), 0)
        self.fire("N3", TEST_PIN)
        self.assertTrue(self.acted("N3"))
        self.assertTrue(self.alive())


# ══ D. the login step (guidance e) ════════════════════════════════════════
class TheLoginPinTests(TestCase):
    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def setUp(self):
        from core import security
        cache.clear()
        security._login_attempts.clear()
        self.addCleanup(security._login_attempts.clear)   # for the next test
        self.user = User.objects.create_user("pw_login", password="pw-login")
        _set_pin(self.user)

    def _password(self):
        from core import security
        security._login_attempts.clear()
        r = self.client.post("/login/", {"username": "pw_login",
                                         "password": "pw-login"}, **self.AJAX)
        self.assertEqual(r.json()["status"], "pin_required")

    def _pin(self, pin, ajax=True):
        return self.client.post("/login/pin/", {"pin": pin},
                                **(self.AJAX if ajax else {}))

    def test_five_wrong_login_pins_drop_the_pending_login(self):
        from core import security
        self._password()
        for n in range(1, MAX):
            r = self._pin(WRONG_PIN)
            self.assertEqual(r.status_code, 400)
            self.assertIn(f"{MAX - n} attempt", r.json()["message"])
            self.assertNotIn("restart", r.json())
        r = self._pin(WRONG_PIN)
        self.assertEqual(r.status_code, 400)
        self.assertIs(r.json()["restart"], True)
        self.assertIn("sign in again with your password", r.json()["message"])
        security._login_attempts.clear()
        r = self._pin(TEST_PIN)                         # the pad is gone
        self.assertIn("Session expired", r.json()["message"])
        self.assertNotIn("_auth_user_id", self.client.session)
        self._password()                                # the password again
        r = self._pin(TEST_PIN)
        self.assertEqual(r.json()["status"], "ok")

    def test_the_login_counter_never_reaches_the_logged_in_session(self):
        from core.trading_pin import LOGIN_ATTEMPTS_KEY
        self._password()
        self._pin(WRONG_PIN)
        self._pin(WRONG_PIN)
        r = self._pin(TEST_PIN)
        self.assertEqual(r.json()["status"], "ok")
        self.assertNotIn(LOGIN_ATTEMPTS_KEY, self.client.session)
        self.assertEqual(int(self.client.session.get(ATTEMPTS_KEY, 0) or 0),
                         0)

    def test_a_blank_login_pin_is_not_counted(self):
        from core import security
        self._password()
        for _ in range(8):
            security._login_attempts.clear()    # the IP limiter is apart
            r = self._pin("")
            self.assertNotIn("restart", r.json())
            self.assertIn("Enter your PIN", r.json()["message"])
        security._login_attempts.clear()
        r = self._pin(TEST_PIN)
        self.assertEqual(r.json()["status"], "ok")

    def test_the_login_alarm_is_sent_once_per_account_per_hour(self):
        from tests.test_alarm_bot import MONEY
        with mock.patch("bot_program.alarm.send_alarm",
                        return_value=True) as send:
            for _ in range(2):
                self._password()
                with self.captureOnCommitCallbacks(execute=True):
                    for _ in range(MAX):
                        self._pin(WRONG_PIN)
            _join_alarms()
        self.assertEqual(send.call_count, 1)
        text = " ".join([send.call_args[0][0], *send.call_args[0][1]])
        self.assertIsNone(MONEY.search(text), text)
        self.assertIn("pw_login", text)

    def test_the_standalone_page_goes_straight_back_to_the_password(self):
        """Critique A12."""
        self._password()
        for _ in range(MAX - 1):
            self._pin(WRONG_PIN, ajax=False)
        r = self._pin(WRONG_PIN, ajax=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])
        self.assertNotIn("/login/pin/", r["Location"])


# ══ E. arming a live bot (D2, and the doors found beyond it) ═════════════
class SystemMapArmsALiveBotOnlyWithThePinTests(_Bench):

    def test_no_pin_is_refused_uncounted_and_says_why(self):
        r = self.fire("G1", "")
        self.assertEqual(r.status_code, 403)
        j = r.json()
        self.assertTrue(j["pin_required"])
        self.assertIs(j["logged_out"], False)
        self.assertIn("takes your trading PIN", j["error"])
        self.assertTrue(j["detail"])
        self.assertNotIn("superuser", j["detail"])
        self.assertFalse(self.acted("G1"))
        self.assertEqual(self.count(), 0)

    def test_the_right_pin_arms_and_the_rearm_is_recorded(self):
        from bot_program.audit_models import AuditLogEntry
        r = self.fire("G1", WRONG_PIN)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.acted("G1"))
        r = self.fire("G1", TEST_PIN)
        self.assertEqual(r.json()["ok"], True)
        self.assertTrue(self.acted("G1"))
        self.assertTrue(AuditLogEntry.objects.filter(
            kind="config_rearmed").exists())

    def test_off_paper_unchanged_and_another_users_bot(self):
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.filter(pk=self.arm_cfg.pk).update(enabled=True)
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "bot", "key": self.arm_cfg.pk})
        self.assertEqual(r.json()["enabled"], False)    # OFF is free
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "bot", "key": self.arm_cfg.pk,
                              "want": "off"})
        self.assertTrue(r.json().get("unchanged"))      # a stale stop: nothing
        self.assertFalse(AssetBotConfig.objects.get(pk=self.arm_cfg.pk)
                         .enabled)
        paper = AssetBotConfig.objects.create(
            user=self.admin, asset_class="crypto", name="pw_map_paper",
            mode="paper", enabled=False, symbols=[])
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "bot", "key": paper.pk})
        self.assertEqual(r.json()["enabled"], True)     # paper: no PIN
        theirs = AssetBotConfig.objects.create(
            user=self.other, asset_class="stock", name="pw_theirs",
            mode="live", enabled=False, symbols=[])
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "bot", "key": theirs.pk,
                              "pin": TEST_PIN})
        self.assertEqual(r.status_code, 404)
        # ...and the live arm with no PIN is what changed.
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "bot", "key": self.arm_cfg.pk})
        self.assertEqual(r.status_code, 403)

    def test_the_maps_refresh_carries_each_bots_mode(self):
        """Critique A11: the page asks for the PIN from the node's mode,
        which must not go stale between renders."""
        r = self.client.get("/admin-dashboard/system-map/state/")
        bots = [n for n in r.json()["nodes"] if n["key"].startswith("bot_")]
        self.assertTrue(bots)
        for n in bots:
            self.assertIn(n.get("mode"), ("paper", "live"))


class AdminBotToggleArmsALiveBotOnlyWithThePinTests(_Bench):

    def test_staff_arm_another_users_live_bot_with_their_own_pin(self):
        r = self.fire("G2", "")
        self.assertEqual(r.json()["ok"], False)
        self.assertTrue(r.json()["pin_required"])
        self.assertFalse(self.acted("G2"))
        self.assertEqual(self.count(), 0)
        self.fire("G2", WRONG_PIN)
        self.assertEqual(self.count(), 1)
        r = self.fire("G2", TEST_PIN)
        self.assertEqual(r.json(), {"ok": True, "enabled": True})
        self.assertTrue(self.acted("G2"))
        [row] = _legacy_rows("legacy_bot_armed") or [None]
        self.assertIsNotNone(row)
        self.assertEqual(row.data["who"], "pw_admin")
        self.assertEqual(row.data["owner"], "pw_other")
        self.assertEqual(row.data["via"], "admin_bots")

    def test_off_and_paper_need_nothing(self):
        from bot_program.models import BotConfig
        BotConfig.objects.filter(pk=self.legacy_other.pk).update(enabled=True)
        r = self.client.post(f"/htmx/admin/bots/{self.legacy_other.pk}/toggle/")
        self.assertEqual(r.json()["enabled"], False)
        self.assertTrue(_legacy_rows("legacy_bot_off"))
        BotConfig.objects.filter(pk=self.legacy_other.pk).update(mode="paper")
        r = self.client.post(f"/htmx/admin/bots/{self.legacy_other.pk}/toggle/")
        self.assertEqual(r.json()["enabled"], True)
        self.assertEqual(self.count(), 0)

    def test_no_raw_exception_text_reaches_the_panel(self):
        with mock.patch("bot_program.models.BotConfig.save",
                        side_effect=RuntimeError("pw boom")):
            r = self.client.post(
                f"/htmx/admin/bots/{self.legacy_other.pk}/toggle/",
                {"want": "on", "pin": TEST_PIN})
        self.assertEqual(r.json()["ok"], False)
        self.assertNotIn("pw boom", r.content.decode())
        self.assertIn("server log", r.json()["error"])
        r = self.client.post("/htmx/admin/bots/999999/toggle/")
        self.assertEqual(r.json(), {"ok": False, "error": "No such bot."})


class BotConsoleResumesALiveBotOnlyWithThePinTests(_Bench):

    def test_resume_takes_the_pin_and_pause_is_free(self):
        from bot_program.models import BotConfig
        r = self.fire("G3", "")
        self.assertEqual(r.json()["ok"], False)
        self.assertIn("takes your trading PIN", r.json()["error"])
        self.assertFalse(self.acted("G3"))
        self.fire("G3", TEST_PIN)
        self.assertTrue(self.acted("G3"))
        r = self.client.post("/bot/console/pause/", {"want": "off"})
        self.assertEqual(r.json()["enabled"], False)
        BotConfig.objects.filter(pk=self.legacy.pk).update(mode="paper")
        r = self.client.post("/bot/console/pause/")
        self.assertEqual(r.json()["enabled"], True)


class TheLegacyToggleCountsTests(_Bench):

    def test_a_wrong_pin_is_counted_and_said(self):
        r = self.fire("N4", WRONG_PIN)
        self.assertIn("Incorrect trading PIN", self.said(r))
        self.assertIn(f"{MAX - 1} attempts left", self.said(r))
        self.assertEqual(self.count(), 1)
        self.fire("N4", TEST_PIN)
        self.assertTrue(self.acted("N4"))
        self.assertTrue(_legacy_rows("legacy_bot_armed"))


class ConfigureNeverArmsLiveTests(_Bench):

    def _form(self, **over):
        from django.forms.models import model_to_dict
        from bot_program.models import BotConfig
        cfg = BotConfig.objects.get(pk=self.legacy.pk)
        data = {k: v for k, v in model_to_dict(cfg).items()
                if k not in ("id", "user", "updated_at", "enabled")
                and v is not None}
        for k, v in list(data.items()):
            if isinstance(v, (list, dict)):
                data[k] = json.dumps(v)
            elif isinstance(v, bool):
                if v:
                    data[k] = "on"
                else:
                    data.pop(k)
        data["symbols"] = json.dumps(["BTCUSDT"])
        data.update(over)
        return data

    def test_a_crafted_post_cannot_arm_a_live_bot(self):
        from bot_program.models import BotConfig
        r = self.client.post("/bot/configure/",
                             self._form(enabled="on", mode="live"))
        self.assertEqual(r.status_code, 200)            # the form again
        self.assertFalse(BotConfig.objects.get(pk=self.legacy.pk).enabled)
        self.assertContains(r, "takes your trading PIN")
        self.assertTrue([x for x in _pin_rows("pin_refused")
                         if x.data.get("reason") == "no_pin_here"])

    def test_the_pages_own_save_is_unchanged(self):
        from bot_program.models import BotConfig
        r = self.client.post("/bot/configure/", self._form(mode="live"))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(BotConfig.objects.get(pk=self.legacy.pk).enabled)


class SeedActivateSkipsLiveConfigsTests(TestCase):

    def test_activate_never_arms_a_live_starter_config(self):
        from bot_program.management.commands.seed_bots import seed_bots
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        user = User.objects.create_superuser("pw_seed", "s@x.test", "x")
        for sym in ("AAPL", "EURUSD"):
            Instrument.objects.get_or_create(
                symbol=sym, defaults={"name": sym, "asset_class": "stock",
                                      "is_active": True})
        AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="starter_megacaps",
            mode="live", enabled=False, symbols=["AAPL"])
        out = seed_bots(user, activate=True)
        self.assertEqual(out["skipped_live"], ["starter_megacaps"])
        self.assertFalse(AssetBotConfig.objects.get(
            name="starter_megacaps").enabled)
        self.assertTrue(AssetBotConfig.objects.get(
            name="starter_fx_majors").enabled)          # paper: armed

    def test_the_hq_button_says_which_it_left_off(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        admin = User.objects.create_superuser("pw_seed2", "s2@x.test", "x")
        Instrument.objects.create(symbol="AAPL", name="AAPL",
                                  asset_class="stock", is_active=True)
        AssetBotConfig.objects.create(
            user=admin, asset_class="stock", name="starter_megacaps",
            mode="live", enabled=False, symbols=["AAPL"])
        self.client.force_login(admin)
        r = self.client.post("/admin-dashboard/bots/seed/",
                             {"target_username": "pw_seed2",
                              "activate": "on"})
        said = " | ".join(str(m) for m in get_messages(r.wsgi_request))
        self.assertIn("left OFF because they are LIVE: starter_megacaps", said)
        self.assertNotIn("paper bot config", said)


class DjangoAdminNeverArmsALiveBotTests(_Bench):

    def _change(self, **over):
        from django.forms.models import model_to_dict
        from bot_program.models import BotConfig
        cfg = BotConfig.objects.get(pk=self.legacy.pk)
        data = {k: v for k, v in model_to_dict(cfg).items()
                if k not in ("id", "updated_at", "enabled")
                and v is not None}
        for k, v in list(data.items()):
            if isinstance(v, (list, dict)):
                data[k] = json.dumps(v)
            elif isinstance(v, bool):
                if v:
                    data[k] = "on"
                else:
                    data.pop(k)
        data["symbols"] = json.dumps(["BTCUSDT"])
        data.update(over)
        return self.client.post(
            f"/admin/bot_program/botconfig/{cfg.pk}/change/", data)

    def test_the_change_form_refuses_a_live_arm_and_off_is_free(self):
        from bot_program.models import BotConfig
        r = self._change(enabled="on")
        self.assertEqual(r.status_code, 200)            # the form, refused
        self.assertContains(r, "takes your trading PIN")
        self.assertFalse(BotConfig.objects.get(pk=self.legacy.pk).enabled)
        BotConfig.objects.filter(pk=self.legacy.pk).update(enabled=True)
        r = self._change()                              # enabled unticked
        self.assertEqual(r.status_code, 302)
        self.assertFalse(BotConfig.objects.get(pk=self.legacy.pk).enabled)


class TheAlarmNeverHoldsUpAStopTests(_BenchMixin, TransactionTestCase):
    """No outer transaction, as in production (no ATOMIC_REQUESTS): the
    alarm's on_commit callback runs at once. Telegram held for seconds
    must not hold the close, the kill switch or the flatten it reports."""

    def test_a_slow_telegram_never_delays_a_stop_on_a_spent_session(self):
        tp = _tp()
        for door in ("S1", "S4", "S5"):
            with self.subTest(door=door):
                self._reset()
                self.spend()
                entered, release = threading.Event(), threading.Event()

                def slow(*a, **kw):
                    entered.set()
                    release.wait(5)
                    return True

                try:
                    with mock.patch("bot_program.alarm.send_alarm",
                                    side_effect=slow) as send:
                        self.fire(door, TEST_PIN)
                        self.assertTrue(self.acted(door))
                        self.assertTrue(self.alive())
                        self.assertTrue(entered.wait(5))    # it was sent...
                        held = [t for t in threading.enumerate()
                                if t.name == tp.ALARM_THREAD and t.is_alive()]
                        self.assertTrue(held)       # ...and is still held
                        release.set()
                        _join_alarms()
                    self.assertEqual(send.call_count, 1)
                finally:
                    release.set()


# ══ F. contracts: the words and the pages ═════════════════════════════════
class TheWordsTests(TestCase):

    def test_every_refusal_is_one_sentence_without_the_pin(self):
        tp = _tp()
        long_symbol = "NATURALGASUSD.X"
        for refusal in (tp.PIN_MISSING, tp.PIN_NOT_SET, tp.PIN_WRONG,
                        tp.LOCKED_OUT, tp.LOGIN_AGAIN):
            for door in (tp.STOP, tp.ACT, tp.LOCK):
                for left, spent in ((3, False), (1, False), (0, True)):
                    v = tp.PinVerdict(ok=False, refusal=refusal,
                                      attempts_left=left, spent=spent,
                                      door=door)
                    s = tp.sentence(v, subject=f"Closing {long_symbol}",
                                    nothing=f"{long_symbol} was not closed")
                    with self.subTest(refusal=refusal, door=door, left=left):
                        self.assertTrue(s.endswith("."), s)
                        self.assertNotIn(". ", s, s)
                        self.assertNotIn(TEST_PIN, s)
                        self.assertNotRegex(s, r"\d[- ]digit")
                        # close-all and close-selected cut a row's error at
                        # 160 characters (critique A5)
                        self.assertLessEqual(len(s), 160, s)

    def test_the_known_gap_paragraph_is_closed(self):
        import core.switch_pin as sp
        doc = sp.__doc__
        self.assertNotIn("KNOWN GAP, awaiting the operator's decision (D1)",
                         doc)
        self.assertIn("core/trading_pin.py", doc)
        self.assertEqual(sp.check_trading_pin.__module__, "core.switch_pin")
        tp = _tp()
        self.assertIs(sp.PinVerdict, tp.PinVerdict)
        self.assertEqual(sp.LOGIN_MARK_KEY, tp.LOGIN_MARK_KEY)
        from dashboard import lock_views
        self.assertEqual((lock_views.MAX_ATTEMPTS, lock_views.ATTEMPTS_KEY),
                         (tp.MAX_ATTEMPTS, tp.ATTEMPTS_KEY))


class OnlyTheOneCheckHashesThePinTests(TestCase):
    """Critique A10: a door that still checked the hash itself would pass
    every "never checked" assertion above."""

    SKIP_DIRS = {"tests", "migrations", "venv", ".venv", "node_modules",
                 "staticfiles", ".git", ".claude", "__pycache__"}
    ALLOWED = {os.path.join("core", "trading_pin.py"),
               os.path.join("portfolio", "trader_profile.py")}

    def _sources(self):
        for dirpath, dirnames, files in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in self.SKIP_DIRS]
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(dirpath, f)
                    yield os.path.relpath(path, ROOT), path

    def test_no_module_but_the_check_hashes_a_pin(self):
        pat = re.compile(r"\.check_pin\(|check_password\([^)]*access_pin_hash")
        found = []
        for rel, path in self._sources():
            if rel in self.ALLOWED:
                continue
            with open(path, encoding="utf-8", errors="ignore") as fh:
                src = fh.read()
            if pat.search(src):
                found.append(rel)
        self.assertEqual(found, [])

    def test_every_call_names_its_door_and_the_stop_set_is_fixed(self):
        """Every call of the check (`check`, `gate`, or a door's `_pin_ok`)
        names its class and its act, and the STOP set is fixed. A name
        bound by `from ... import` counts under its own name, so a bare
        `check(...)` (the lock, change PIN) and an alias such as
        `_trading_pin_ok` are covered like `trading_pin.check(...)`."""
        names = {"check", "gate", "_pin_ok"}
        stops, missing, seen = set(), [], set()
        for rel, path in self._sources():
            if not rel.startswith(("dashboard", "bot_program", "core")):
                continue
            with open(path, encoding="utf-8", errors="ignore") as fh:
                src = fh.read()
            if "trading_pin" not in src and "_pin_ok" not in src:
                continue
            tree = ast.parse(src)
            # The names this module binds by `from X import a as b`: b -> a,
            # and which of them come from the one check.
            alias, from_check = {}, set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for a in node.names:
                        bound = a.asname or a.name
                        alias[bound] = a.name
                        if node.module == "core.trading_pin":
                            from_check.add(bound)
            own = rel.endswith("trading_pin.py")
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef,
                                       ast.AsyncFunctionDef)):
                    continue
                for call in ast.walk(fn):
                    if not isinstance(call, ast.Call):
                        continue
                    f = call.func
                    if isinstance(f, ast.Name):
                        name = alias.get(f.id, f.id)
                        of_check = f.id in from_check
                    elif isinstance(f, ast.Attribute):
                        name = f.attr
                        of_check = "trading_pin" in ast.dump(f.value)
                    else:
                        continue
                    if name not in names:
                        continue
                    if name == "check" and not (of_check or own):
                        continue        # some other module's check()
                    seen.add(f"{rel}:{fn.name}")
                    kws = {k.arg: k.value for k in call.keywords}
                    if "door" not in kws or "act" not in kws:
                        if not (own and fn.name in ("gate", "__bool__")):
                            missing.append(f"{rel}:{call.lineno}")
                        continue
                    if "STOP" in ast.dump(kws["door"]):
                        stops.add(f"{rel}:{fn.name}")
        self.assertEqual(missing, [])
        # the bare and the aliased calls are in the walk...
        self.assertTrue({
            "dashboard/lock_views.py:session_unlock",
            "dashboard/views_profile_modals.py:change_pin_answer",
            "dashboard/views.py:take_trade_execute",
        } <= seen, sorted(seen))
        # ...and none of them is a stopping door.
        self.assertEqual(stops, {
            "dashboard/views_close.py:close_position_execute",
            "dashboard/views_close.py:close_all_execute",
            "dashboard/views_close.py:close_selected_execute",
            "dashboard/views_close.py:position_levels",
            "dashboard/views.py:kill_switch_api",
            "dashboard/views_admin_hq.py:flatten_all_positions",
        })


class ThePagesAskAndFollowTests(TestCase):
    """The pages send the PIN where the server now asks for it, and follow
    a session that ended. Each assertion is on a call shape, not a word
    that a comment could carry."""

    def test_the_system_map_asks_for_the_pin_and_sends_want(self):
        src = _src("templates", "dashboard", "system_map.html")
        fn = src[src.index("function applyToggle"):]
        fn = fn[:fn.index("document.addEventListener")]
        self.assertIn('body.append("pin"', fn)
        self.assertIn('body.append("want"', fn)
        self.assertIn("secretLabel", fn)
        self.assertIn(".logged_out", fn)

    def test_the_admin_bot_panel_and_the_console_ask_too(self):
        panel = _src("templates", "dashboard", "_admin_bots.html")
        self.assertIn('data-bot-mode="{{ row.mode }}"', panel)
        fn = panel[panel.index("async function adminBotToggle"):]
        fn = fn[:fn.index("async function adminBotShadow")]
        self.assertIn("secretLabel", fn)
        self.assertIn('body.append("want"', fn)
        self.assertIn('body.append("pin"', fn)
        self.assertIn("botSessionEnded(r)", fn)
        helper = panel[panel.index("async function botSessionEnded"):]
        helper = helper[:helper.index("}\n")]
        self.assertIn("r.logged_out", helper)
        console = _src("templates", "dashboard", "bot_console.html")
        self.assertIn('data-bot-mode="{{ config.mode }}"', console)
        fn = console[console.index("async function togglePause"):]
        self.assertIn("secretLabel", fn)
        self.assertIn(".logged_out", fn)

    def test_every_act_reader_follows_a_session_that_ended(self):
        for parts, anchor in (
                (("templates", "base.html"), "title: 'Trade not taken'"),
                (("templates", "dashboard", "admin_dashboard.html"),
                 "take_trade_arm"),
                (("static", "js", "sv-level-edit.js"), "function submit("),
                (("templates", "dashboard", "_profile_pin_modal.html"),
                 "async function submitPinChange")):
            src = _src(*parts)
            i = src.index(anchor)
            window = src[max(0, i - 1500):i + 2500]
            with self.subTest(page=parts[-1]):
                self.assertIn(".logged_out", window)
                self.assertIn("/wall/", window)

    def test_the_wall_goes_back_to_the_password_on_restart(self):
        src = _src("templates", "landing", "the_wall.html")
        fn = src[src.index("function submitPin()"):]
        fn = fn[:fn.index("if (pinForm)")]
        self.assertIn("reply.body.restart", fn)


_NODE = __import__("shutil").which("node")


def _run_js(script):
    """Run a script under node and return what it printed as JSON."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(prefix="sv-pinwide-") as tmp:
        path = os.path.join(tmp, "case.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        proc = subprocess.run([_NODE, path], capture_output=True, text=True,
                              timeout=60)
    if proc.returncode != 0:
        raise AssertionError(f"node failed: {proc.stderr[:800]}")
    return json.loads(proc.stdout)


def _js_function(parts, start, stop):
    """The page's own function source, from `start` up to `stop`."""
    src = _src(*parts)
    i = src.index(start)
    return src[i:src.index(stop, i)]


@__import__("unittest").skipIf(_NODE is None, "node is not installed")
class ThePagesShowWhatTheServerSaidTests(TestCase):
    """The pages' own JavaScript, run under node with the browser stubbed:
    a box the PIN dialog held shows the server's state whatever the poll
    did meanwhile, and only a redirect to the Wall or a login page reads as
    a session that ended."""

    def test_the_maps_box_follows_the_server_never_a_flip(self):
        fn = _js_function(("templates", "dashboard", "system_map.html"),
                          "function applyToggle",
                          'document.addEventListener("change"')
        fn = fn.replace("{% url 'system_map_toggle' %}", "/map/toggle/")
        self.assertNotIn("{%", fn)
        script = r"""
const results = [], assigned = [];
globalThis.window = { location: { assign: (u) => assigned.push(u) } };
const byKey = {};
let pending, fetchImpl;
const SV = { overlay: {
    confirm: () => pending,
    alert: () => Promise.resolve(true) } };
function csrf() { return "t"; }
function refresh() {}
globalThis.fetch = (...a) => fetchImpl(...a);
const reply = (status, j) => Promise.resolve({ ok: status < 400, status,
    json: () => Promise.resolve(j) });
""" + fn + r"""
async function scenario(name, answer, fetcher) {
    const node = { enabled: false, mode: "live", label: "pw bot" };
    byKey.bot_1 = node;
    const input = { checked: true, disabled: false };   // he ticked an OFF box
    let release;
    pending = new Promise((r) => { release = r; });
    fetchImpl = fetcher;
    assigned.length = 0;
    const done = applyToggle("bot", "1", "bot_1", input);
    const held = input.disabled;
    input.checked = node.enabled;   // a poll reset the box under the dialog
    release(answer);
    await done;
    results.push({ name, checked: input.checked, disabled: input.disabled,
                   held, enabled: node.enabled, wall: assigned.slice() });
}
(async () => {
    await scenario("cancelled", false, () => { throw new Error("no fetch"); });
    await scenario("wrong pin", "pw", () => reply(403,
        { ok: false, enabled: false, error: "Incorrect trading PIN." }));
    await scenario("not found", "pw", () => reply(404,
        { ok: false, error: "bot not found" }));
    await scenario("network", "pw", () => Promise.reject(new TypeError("x")));
    await scenario("ended", "pw", () => reply(403,
        { ok: false, enabled: false, logged_out: true, error: "ended" }));
    await scenario("armed", "pw", () => reply(200,
        { ok: true, enabled: true }));
    await new Promise((r) => setTimeout(r, 0));
    process.stdout.write(JSON.stringify(results));
})().catch((e) => { console.error(String(e)); process.exit(1); });
"""
        got = {r["name"]: r for r in _run_js(script)}
        for name in ("cancelled", "wrong pin", "not found", "network",
                     "ended"):
            with self.subTest(name=name):
                self.assertIs(got[name]["held"], True)   # held for the dialog
                self.assertIs(got[name]["checked"], False)   # the bot is OFF
                self.assertIs(got[name]["disabled"], False)  # released after
        self.assertEqual(got["ended"]["wall"], ["/wall/"])
        self.assertIs(got["armed"]["checked"], True)
        self.assertIs(got["armed"]["enabled"], True)
        # ...and the 15-second poll leaves a held box alone.
        poll = _js_function(("templates", "dashboard", "system_map.html"),
                            "function refresh()", "/* ── Keeping")
        line = [x for x in poll.splitlines() if "box.checked =" in x]
        self.assertEqual(len(line), 1)
        self.assertIn("!box.disabled", line[0])

    def _non_json(self):
        return r"""
const notJson = (status, redirected, url) => () => Promise.resolve({
    ok: status < 400, status, redirected, url,
    json: () => Promise.reject(new SyntaxError("Unexpected token <")) });
const CASES = [
    ["wall", notJson(200, true, "https://sv.test/wall/?next=/x/")],
    ["admin login", notJson(200, true, "https://sv.test/admin/login/?next=/x/")],
    ["bad gateway", notJson(502, false, "https://sv.test/x/")],
    ["server error", notJson(500, false, "https://sv.test/x/")],
    ["csrf", notJson(403, false, "https://sv.test/x/")],
];
"""

    def test_the_admin_panel_reads_only_a_redirect_as_an_ended_session(self):
        fn = _js_function(("templates", "dashboard", "_admin_bots.html"),
                          "async function adminBotPost",
                          "async function botSessionEnded")
        script = r"""
function getCsrf() { return "t"; }
let fetchImpl;
globalThis.fetch = (...a) => fetchImpl(...a);
""" + fn + self._non_json() + r"""
(async () => {
    const out = {};
    for (const [name, f] of CASES) {
        fetchImpl = f;
        out[name] = await adminBotPost("/htmx/admin/bots/1/toggle/");
    }
    process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(String(e)); process.exit(1); });
"""
        got = _run_js(script)
        for name in ("wall", "admin login"):
            with self.subTest(name=name):
                self.assertIs(got[name]["logged_out"], True)
        for name, status in (("bad gateway", "502"), ("server error", "500"),
                             ("csrf", "403")):
            with self.subTest(name=name):
                self.assertFalse(got[name].get("logged_out"))
                self.assertIs(got[name]["ok"], False)
                self.assertIn(status, got[name]["error"])
                self.assertNotIn("session", got[name]["error"].lower())

    def test_the_console_reads_only_a_redirect_as_an_ended_session(self):
        fn = _js_function(("templates", "dashboard", "bot_console.html"),
                          "async function togglePause",
                          "window.togglePause")
        script = r"""
function getCsrf() { return "t"; }
let fetchImpl, titles, assigned, reloads;
globalThis.fetch = (...a) => fetchImpl(...a);
globalThis.document = { getElementById: () => ({ dataset: {
    botPaused: "0", botMode: "live" } }) };
globalThis.location = { reload: () => { reloads += 1; } };
globalThis.window = { location: { assign: (u) => assigned.push(u) } };
const SV = { overlay: {
    confirm: () => Promise.resolve(true),
    alert: (o) => { titles.push(o.title); return Promise.resolve(true); } } };
""" + fn + self._non_json() + r"""
(async () => {
    const out = {};
    for (const [name, f] of CASES) {
        fetchImpl = f; titles = []; assigned = []; reloads = 0;
        await togglePause();
        out[name] = { titles, assigned, reloads };
    }
    process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(String(e)); process.exit(1); });
"""
        got = _run_js(script)
        for name in ("wall", "admin login"):
            with self.subTest(name=name):
                self.assertEqual(got[name]["titles"], ["Session ended"])
                self.assertEqual(got[name]["assigned"], ["/wall/"])
        for name in ("bad gateway", "server error", "csrf"):
            with self.subTest(name=name):
                self.assertEqual(got[name]["titles"],
                                 ["Could not change the bot"])
                self.assertEqual(got[name]["assigned"], [])
                self.assertEqual(got[name]["reloads"], 0)
