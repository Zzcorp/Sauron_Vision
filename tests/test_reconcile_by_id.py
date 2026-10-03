"""Reconcile judges a row by its own position id (2026-10-03).

Morgul, Saturday 00:24 UTC: "Drift · GBPCHF long #130 · live — not in the
holdings eToro reported; the platform counts it open; seen since
2026-10-02 12:37 UTC". Twelve hours. The reconciler had seen the miss on
every pass and refused it every time: "EtoroTrader listed 1 position(s) it
could not name, so a miss proves nothing" — the account's other-class
holding (GLDM) stayed "ETORO:3190" because a forex pass warmed only forex
names, and one unnamed position made every miss in every class
untrustworthy.

Two fixes, pinned here:
  * the warm covers every open row's symbol, whatever its class;
  * a row that carries the venue's position id (venue_close.position_id_for)
    is judged by it when the venue listed ids — present is open whatever
    the name, absent is an absence even beside positions nobody could name.
    A row with no id keeps the old caution.

Run with:  python manage.py test tests.test_reconcile_by_id
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from bot_program import reconcile_asset


class _Venue:
    """A client that lists positions with ids and names only some."""

    def __init__(self, rows):
        self.rows = rows
        self.warmed = []

    def instrument_id(self, symbol):
        self.warmed.append(symbol)
        return 1

    def get_positions(self):
        return list(self.rows)


def _cfg(user, asset_class="forex", name="fx"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode="live",
        enabled=True, symbols=[], capital=Decimal("1000"))


def _trade(cfg, symbol="GBPCHF", *, pid="555"):
    from bot_program.models import AssetBotTrade
    meta = {"broker": "etoro", "broker_env": "live", "value_per_unit": 1.0}
    if pid:
        meta["broker_position_id"] = pid
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("3600"), entry_price=Decimal("1.09716"),
        stop_loss=Decimal("1.09"), status="OPEN", paper=False,
        rule_name="starter_forex_breakout", metadata=meta)
    AssetBotTrade.objects.filter(pk=t.pk).update(
        opened_at=timezone.now() - timedelta(hours=30))
    t.refresh_from_db()
    return t


UNNAMED_OTHER = {"symbol": "ETORO:3190", "symbol_unresolved": True,
                 "qty": 1.0, "side": "BUY", "position_id": "777"}


class ByIdTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("rc_u", password="x")
        self.cfg = _cfg(self.user)

    def _run(self, venue):
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=venue):
            return reconcile_asset.reconcile_user(self.user)

    def test_an_id_absent_from_the_book_is_an_absence_despite_unnamed_rows(self):
        t = _trade(self.cfg, pid="555")
        out = self._run(_Venue([UNNAMED_OTHER]))
        t.refresh_from_db()
        self.assertEqual(out["closed_as_orphan"], 1, out)
        self.assertEqual(t.status, "CLOSED")

    def test_an_id_present_in_the_book_is_open_whatever_the_name(self):
        t = _trade(self.cfg, pid="555")
        out = self._run(_Venue([dict(UNNAMED_OTHER, position_id="555")]))
        t.refresh_from_db()
        self.assertEqual(out["closed_as_orphan"], 0, out)
        self.assertEqual(out["broker_unavailable"], 0, out)
        self.assertEqual(t.status, "OPEN")

    def test_a_row_without_an_id_keeps_the_old_caution(self):
        t = _trade(self.cfg, pid="")
        out = self._run(_Venue([UNNAMED_OTHER]))
        t.refresh_from_db()
        self.assertEqual(out["closed_as_orphan"], 0, out)
        self.assertEqual(out["broker_unavailable"], 1, out)
        self.assertEqual(t.status, "OPEN")

    def test_the_warm_names_every_open_row_whatever_its_class(self):
        _trade(self.cfg, "GBPCHF", pid="555")
        _trade(_cfg(self.user, "stock", "stocks"), "GLDM", pid="777")
        venue = _Venue([dict(UNNAMED_OTHER, position_id="555"),
                        {"symbol": "GLDM", "qty": 1.0, "side": "BUY",
                         "position_id": "777"}])
        self._run(venue)
        self.assertEqual(sorted(set(venue.warmed)), ["GBPCHF", "GLDM"])

    def test_the_state_carries_the_ids(self):
        state = reconcile_asset._broker_open_symbols(
            _Venue([UNNAMED_OTHER, {"symbol": "GLDM", "position_id": 42}]),
            asset_class="forex")
        self.assertEqual(state["position_ids"], {"777", "42"})
        self.assertEqual(state["unnamed"], 1)
        self.assertEqual(state["symbols"], {"GLDM"})
