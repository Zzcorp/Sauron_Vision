"""CLOSE POSITION — manual exit of one open trade.

TAKE TRADE could open a position; nothing could close one. A trade left the
book only when the tick hit its stop or target, or when the kill switch
flattened every position the user held. This pins the way out.

What the file guards, in order:
  * the happy path writes a CLOSED row through the ENGINE's own close, so
    grading, the audit entry, the tax lots, the notification and the Eye
    push all fire exactly as they do for a stop-out;
  * realized R is denominated by the stop the trade OPENED with, never the
    trailed one — otherwise every manual exit scores ~1.0R;
  * a double submit closes once;
  * a LIVE trade whose broker is unreachable REFUSES and stays OPEN, rather
    than stamping the row closed while the position lives at the broker;
  * a paper trade closes with no broker at all;
  * closing another user's trade 404s;
  * the PIN gates live closes and does not gate paper ones;
  * the button reaches every surface that lists an open position.

Run with:  python manage.py test tests.test_manual_close
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "binance_public"})
    return inst


def _signal(inst, *, direction="bullish", entry=60000, stop=59100,
            target=61800, score=0.8):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="high", title=f"{inst.symbol} {direction}", description="d",
        rule_name="test_rule", score=score, sub_scores={},
        price_at_signal=Decimal(str(entry)),
        suggested_entry=Decimal(str(entry)),
        suggested_stop=Decimal(str(stop)),
        suggested_target=Decimal(str(target)), is_active=True)


def _open_paper_trade(user, inst):
    """One tracked paper position, opened the way the operator opens one."""
    from bot_program.manual_trade import execute_take_trade
    from bot_program.models import AssetBotTrade
    out = execute_take_trade(user, _signal(inst))
    assert out.get("ok"), out
    return AssetBotTrade.objects.get(pk=out["trade_id"])


def _live_trade(user, inst, *, symbol="BTCUSD", qty="0.5", entry=60000,
                stop=59100, target=61800):
    """A LIVE row on a live-mode config with no broker credentials.

    The router hands such a config a PaperTrader — that IS the unreachable
    broker case, and it is the one the close path must refuse.
    """
    from bot_program.models import AssetBotConfig, AssetBotTrade
    cfg = AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name="live_book",
        enabled=True, mode="live", symbols=[], capital=Decimal("10000"))
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="crypto", symbol=symbol, side="BUY",
        qty=Decimal(qty), entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)), take_profit=Decimal(str(target)),
        status="OPEN", paper=False, rule_name="live_rule",
        metadata={"initial_stop_loss": float(stop), "value_per_unit": 1.0})


class ManualCloseEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("mc_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    # ── the happy path ───────────────────────────────────────────────

    def test_a_paper_close_writes_a_closed_row(self):
        from bot_program.manual_close import execute_close
        trade = _open_paper_trade(self.user, self.inst)
        out = execute_close(self.user, trade)
        self.assertTrue(out.get("ok"), out)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIsNotNone(trade.exit_price)
        self.assertIsNotNone(trade.closed_at)
        self.assertEqual(trade.outcome, "manual_close")

    def test_a_paper_trade_closes_with_no_broker_at_all(self):
        """No BinanceAccount, no OANDA key, nothing configured — a paper
        position must still be closable, or the rehearsal venue is a trap
        the operator cannot get out of."""
        from bot_program.models import BinanceAccount
        from bot_program.manual_close import execute_close
        self.assertFalse(
            BinanceAccount.objects.filter(user=self.user).exists())
        trade = _open_paper_trade(self.user, self.inst)
        self.assertTrue(trade.paper)
        self.assertTrue(execute_close(self.user, trade).get("ok"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_the_exit_is_charged_the_paper_round_trip(self):
        """_close_trade charges half the round trip adversely on a paper
        exit. A close that booked the raw mark would overstate expectancy
        by exactly the quantity the cost filter exists to defend."""
        from bot_program.manual_close import execute_close
        trade = _open_paper_trade(self.user, self.inst)
        out = execute_close(self.user, trade)
        self.assertTrue(out.get("ok"), out)
        trade.refresh_from_db()
        # A long exits by SELLING, so the fill is BELOW the 60000 mark.
        self.assertLess(float(trade.exit_price), 60000.0)

    def test_realized_r_is_denominated_by_the_entry_stop(self):
        """A trailing stop rewrites trade.stop_loss. Grading against THAT
        makes pnl and risk the same quantity and every manual exit scores
        ~1.0R — the number that sizes live positions."""
        from bot_program.manual_close import execute_close
        trade = _open_paper_trade(self.user, self.inst)
        entry_stop = float(trade.metadata["initial_stop_loss"])
        # Trail the stop most of the way to the mark, as the tick would.
        trade.stop_loss = Decimal("59980")
        trade.save(update_fields=["stop_loss"])

        self.assertTrue(execute_close(self.user, trade).get("ok"))
        trade.refresh_from_db()
        self.assertIsNotNone(trade.realized_r)
        risk = abs(float(trade.entry_price) - entry_stop) * float(trade.qty)
        self.assertAlmostEqual(trade.realized_r,
                               round(float(trade.pnl) / risk, 4), places=3)

    def test_the_preview_promises_the_r_the_close_books(self):
        """The dialog's number and the ledger's number are the same number
        — otherwise the confirm screen is a guess dressed as a fact."""
        from bot_program.manual_close import execute_close, preview_close
        trade = _open_paper_trade(self.user, self.inst)
        p = preview_close(self.user, trade)
        self.assertNotIn("error", p)
        self.assertEqual(p["venue"], "paper")
        self.assertIsNotNone(p["r"])
        self.assertTrue(execute_close(self.user, trade).get("ok"))
        trade.refresh_from_db()
        self.assertAlmostEqual(p["r"], trade.realized_r, places=2)
        self.assertAlmostEqual(p["pnl"], float(trade.pnl), places=2)

    def test_every_close_hook_the_engine_runs_also_runs_here(self):
        """A close path that skips a hook grades the trade differently from
        a stop-out on the same row, and the two stop being comparable."""
        from alerts.models import Notification
        from bot_program.audit_models import AuditLogEntry
        from bot_program.manual_close import execute_close
        trade = _open_paper_trade(self.user, self.inst)
        self.assertTrue(execute_close(self.user, trade).get("ok"))
        trade.refresh_from_db()

        # Grading (Phase 17).
        self.assertTrue(trade.outcome)
        self.assertIsNotNone(trade.realized_r)
        self.assertIsNotNone(trade.duration_minutes)
        # Audit (Phase 28).
        self.assertTrue(AuditLogEntry.objects.filter(
            user=self.user, kind="trade_close").exists(),
            "no trade_close audit entry for the manual close")
        # Notification (Phase 20).
        self.assertTrue(Notification.objects.filter(
            user=self.user, notification_type="bot",
            title__contains="closed").exists(),
            "no close notification for the manual close")
        # Tax lots (Phase 27) — the lot opened at entry must be consumed,
        # or the next trade's close eats a lot that was never its own.
        from bot_program.tax_lot_models import TaxLotConsumption
        self.assertTrue(
            TaxLotConsumption.objects.filter(consuming_trade=trade).exists(),
            "the entry's tax lot was never consumed by the close")

    # ── dedupe ───────────────────────────────────────────────────────

    def test_a_double_submit_closes_once(self):
        from bot_program.manual_close import execute_close
        trade = _open_paper_trade(self.user, self.inst)
        first = execute_close(self.user, trade)
        self.assertTrue(first.get("ok"), first)
        trade.refresh_from_db()
        booked_pnl, booked_exit = trade.pnl, trade.exit_price

        second = execute_close(self.user, trade)
        self.assertIn("error", second)
        self.assertNotIn("ok", second)
        trade.refresh_from_db()
        self.assertEqual(trade.pnl, booked_pnl, "the close was booked twice")
        self.assertEqual(trade.exit_price, booked_exit)

    def test_a_close_already_in_flight_is_refused(self):
        """The sequential guard above cannot see the real race: two clicks
        land while the FIRST is still inside the broker call, so the row is
        still OPEN. The claim is what closes that window."""
        from bot_program.manual_close import CLAIM_KEY, execute_close
        trade = _open_paper_trade(self.user, self.inst)
        meta = dict(trade.metadata or {})
        meta[CLAIM_KEY] = timezone.now().isoformat()
        trade.metadata = meta
        trade.save(update_fields=["metadata"])

        out = execute_close(self.user, trade)
        self.assertIn("error", out)
        self.assertIn("already in flight", out["error"])
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_a_stale_claim_does_not_strand_the_position(self):
        """A worker that died between the claim and the broker call must
        not make the position permanently unclosable — that is a worse
        failure than the double-close the claim prevents."""
        from datetime import timedelta
        from bot_program.manual_close import (CLAIM_KEY, CLAIM_TTL_SECONDS,
                                              execute_close)
        trade = _open_paper_trade(self.user, self.inst)
        meta = dict(trade.metadata or {})
        meta[CLAIM_KEY] = (timezone.now()
                           - timedelta(seconds=CLAIM_TTL_SECONDS + 60)
                           ).isoformat()
        trade.metadata = meta
        trade.save(update_fields=["metadata"])

        self.assertTrue(execute_close(self.user, trade).get("ok"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_the_claim_is_released_on_the_closed_row(self):
        from bot_program.manual_close import CLAIM_KEY, execute_close
        trade = _open_paper_trade(self.user, self.inst)
        self.assertTrue(execute_close(self.user, trade).get("ok"))
        trade.refresh_from_db()
        self.assertNotIn(CLAIM_KEY, trade.metadata or {})

    # ── refusals ─────────────────────────────────────────────────────

    def test_a_live_trade_with_an_unreachable_broker_refuses_and_stays_open(self):
        """asset_engine/base.py:100-110 documents the defect: the router
        never returns None, so closing through a PaperTrader fallback gets
        a synthetic FILLED order back and stamps the row CLOSED while the
        position is still on at the broker."""
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.engine.paper_trader import PaperTrader
        from bot_program.manual_close import execute_close
        trade = _live_trade(self.user, self.inst)
        self.assertIsInstance(
            client_for_symbol(self.user, trade.symbol, trade.config),
            PaperTrader, "this fixture no longer reproduces the fallback")

        out = execute_close(self.user, trade, pin_ok=True)
        self.assertIn("error", out)
        self.assertTrue(out.get("still_open"))
        self.assertIn("broker", out["error"].lower())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN",
                         "a live position was marked closed behind the "
                         "operator's back")
        self.assertIsNone(trade.exit_price)

    def test_the_refused_live_close_is_announced_out_of_band(self):
        """A dismissed dialog is not a record. The position is still on."""
        from alerts.models import Notification
        from bot_program.manual_close import execute_close
        trade = _live_trade(self.user, self.inst)
        execute_close(self.user, trade, pin_ok=True)
        self.assertTrue(Notification.objects.filter(
            user=self.user, title__contains="Close refused").exists())

    def test_the_preview_refuses_the_unreachable_live_broker_too(self):
        """The dialog must not offer a close the execute path will refuse."""
        from bot_program.manual_close import preview_close
        trade = _live_trade(self.user, self.inst)
        p = preview_close(self.user, trade)
        self.assertIn("error", p)
        self.assertIn("broker", p["error"].lower())

    def test_no_price_mark_leaves_the_position_open(self):
        """Booking an exit at a price nobody quoted fabricates P&L, and the
        grading built on it is evidence for real money."""
        from market_data.models import LiveQuote
        from bot_program.manual_close import execute_close, preview_close
        trade = _open_paper_trade(self.user, self.inst)
        # PaperTrader reports a stale quote as 0 — "no price", not a fossil.
        from datetime import timedelta
        LiveQuote.objects.filter(instrument=self.inst).update(
            updated_at=timezone.now() - timedelta(days=2))

        p = preview_close(self.user, trade)
        self.assertIn("error", p)
        self.assertIn("mark", p["error"].lower())
        out = execute_close(self.user, trade)
        self.assertIn("error", out)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_a_closed_trade_cannot_be_closed_again(self):
        from bot_program.manual_close import execute_close, preview_close
        trade = _open_paper_trade(self.user, self.inst)
        self.assertTrue(execute_close(self.user, trade).get("ok"))
        trade.refresh_from_db()
        self.assertIn("error", preview_close(self.user, trade))
        self.assertIn("error", execute_close(self.user, trade))

    # ── the PIN decision ─────────────────────────────────────────────

    def test_a_paper_close_does_not_ask_for_the_pin(self):
        """Closing REDUCES exposure. Gating the platform's safest action
        behind its heaviest friction costs seconds in a fast market and
        buys nothing — a paper close risks a row in the ledger."""
        from bot_program.manual_close import execute_close, requires_pin
        trade = _open_paper_trade(self.user, self.inst)
        self.assertFalse(requires_pin(trade))
        self.assertTrue(execute_close(self.user, trade, pin_ok=False).get("ok"))

    def test_a_live_close_requires_the_pin(self):
        """Irreversible, real money, no re-entry at the same price — the
        same bar the kill switch sets."""
        from bot_program.manual_close import execute_close, requires_pin
        trade = _live_trade(self.user, self.inst)
        self.assertTrue(requires_pin(trade))
        out = execute_close(self.user, trade, pin_ok=False)
        self.assertIn("error", out)
        self.assertIn("PIN", out["error"])
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_the_preview_tells_the_dialog_a_pin_is_coming(self):
        from bot_program.manual_close import preview_close
        trade = _open_paper_trade(self.user, self.inst)
        self.assertFalse(preview_close(self.user, trade)["requires_pin"])

    # ── CLOSE_PENDING goes through the existing machinery ────────────

    def test_a_close_pending_row_is_retried_not_re_closed(self):
        """Sending a fresh market order at a CLOSE_PENDING row is how a
        retry turns into a NEW naked position in the opposite direction:
        the original close may already have filled. pending_closes asks
        the broker first, so the manual path must go through it."""
        from bot_program import manual_close
        trade = _live_trade(self.user, self.inst)
        trade.status = "CLOSE_PENDING"
        trade.save(update_fields=["status"])

        from bot_program import pending_closes
        seen = {}

        def _fake_retry(t):
            seen["trade_id"] = t.id
            t.status = "CLOSED"
            t.exit_price = Decimal("60000")
            t.pnl = Decimal("0")
            t.closed_at = timezone.now()
            t.save()
            return True

        real = pending_closes.retry_trade_close
        pending_closes.retry_trade_close = _fake_retry
        try:
            out = manual_close.execute_close(self.user, trade, pin_ok=True)
        finally:
            pending_closes.retry_trade_close = real
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out.get("retried"),
                        "the manual path built its own close instead of "
                        "going through the retry machinery")
        self.assertEqual(seen.get("trade_id"), trade.id)

    def test_the_pending_preview_says_the_position_is_still_open(self):
        from bot_program.manual_close import preview_close
        trade = _live_trade(self.user, self.inst)
        trade.status = "CLOSE_PENDING"
        trade.save(update_fields=["status"])
        p = preview_close(self.user, trade)
        self.assertTrue(p["pending"])
        self.assertEqual(p["action"], "retry")


class MultiplierTests(TestCase):
    """A close path that drops a multiplier grades the trade wrong: an
    options R is inflated ~100x, and a JPY stop-out scores -0.0067."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("mcm_u", password="x")

    def _trade(self, **kw):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.user, asset_class=kw.pop("cfg_class", "forex"),
            name="mult", defaults={"enabled": True, "mode": "paper",
                                   "symbols": []})
        defaults = dict(
            config=cfg, asset_class="forex", symbol="USDJPY", side="BUY",
            qty=Decimal("10000"), entry_price=Decimal("150.00"),
            stop_loss=Decimal("149.00"), take_profit=Decimal("152.00"),
            status="OPEN", paper=True,
            metadata={"initial_stop_loss": 149.0, "value_per_unit": 0.0067})
        defaults.update(kw)
        return AssetBotTrade.objects.create(**defaults)

    def test_forex_risk_converts_at_the_entry_time_rate(self):
        from bot_program.manual_close import _risk_dollars
        trade = self._trade()
        # 1.00 quote-currency point x 10,000 units x 0.0067 USD/JPY.
        self.assertAlmostEqual(_risk_dollars(trade), 67.0, places=2)

    def test_option_risk_carries_the_contract_multiplier(self):
        from bot_program.manual_close import _risk_dollars
        trade = self._trade(
            cfg_class="options", asset_class="options", symbol="AAPL",
            qty=Decimal("2"), entry_price=Decimal("5.00"),
            stop_loss=Decimal("3.00"), take_profit=Decimal("9.00"),
            metadata={"initial_stop_loss": 3.0, "multiplier": 100})
        # 2 premium points x 2 contracts x 100 shares.
        self.assertAlmostEqual(_risk_dollars(trade), 400.0, places=2)

    def test_a_row_with_no_entry_stop_has_no_r_rather_than_zero(self):
        """Unknown renders as a dash. 0.0R would read as a scratch trade."""
        from bot_program.manual_close import _risk_dollars
        trade = self._trade(stop_loss=None, metadata={})
        self.assertEqual(_risk_dollars(trade), 0.0)


class CloseEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("mce_u", password="x")
        cls.other = get_user_model().objects.create_user("mce_o", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        self.client.force_login(self.user)
        self.trade = _open_paper_trade(self.user, self.inst)

    def test_preview_endpoint_returns_the_facts(self):
        resp = self.client.post(
            f"/positions/{self.trade.id}/close/preview/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["symbol"], "BTCUSD")
        self.assertEqual(data["venue"], "paper")
        self.assertFalse(data["requires_pin"])

    def test_execute_endpoint_closes_the_position(self):
        from bot_program.models import AssetBotTrade
        resp = self.client.post(
            f"/positions/{self.trade.id}/close/", data="{}",
            content_type="application/json", HTTP_HOST="127.0.0.1")
        self.assertTrue(resp.json().get("ok"), resp.json())
        self.assertEqual(AssetBotTrade.objects.get(pk=self.trade.id).status,
                         "CLOSED")

    def test_closing_someone_elses_trade_404s(self):
        """Not 403: answering "forbidden" confirms the row exists."""
        self.client.force_login(self.other)
        for url in (f"/positions/{self.trade.id}/close/preview/",
                    f"/positions/{self.trade.id}/close/"):
            resp = self.client.post(url, data="{}",
                                    content_type="application/json",
                                    HTTP_HOST="127.0.0.1")
            self.assertEqual(resp.status_code, 404, url)
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.status, "OPEN")

    def test_get_is_refused(self):
        resp = self.client.get(f"/positions/{self.trade.id}/close/",
                               HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 405)

    def test_anonymous_users_are_bounced(self):
        self.client.logout()
        resp = self.client.post(
            f"/positions/{self.trade.id}/close/", data="{}",
            content_type="application/json", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 302)

    def test_a_malformed_body_is_400_not_500(self):
        resp = self.client.post(
            f"/positions/{self.trade.id}/close/", data="[1, 2]",
            content_type="application/json", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 400)

    def test_a_live_close_without_the_pin_is_refused_over_http(self):
        from bot_program.manual_close import CLOSE_REASON  # noqa: F401
        live = _live_trade(self.user, self.inst)
        resp = self.client.post(
            f"/positions/{live.id}/close/", data='{"pin": "0000"}',
            content_type="application/json", HTTP_HOST="127.0.0.1")
        data = resp.json()
        self.assertIn("error", data)
        self.assertIn("PIN", data["error"])
        live.refresh_from_db()
        self.assertEqual(live.status, "OPEN")


class CloseButtonSurfaceTests(TestCase):
    """The complaint was not "there is no close endpoint" — it was that an
    open position on screen had no way out. Every surface that lists one
    must carry the control."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("mcs_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        self.client.force_login(self.user)
        self.trade = _open_paper_trade(self.user, self.inst)

    def _body(self, url):
        resp = self.client.get(url, HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200, url)
        return resp.content.decode("utf-8", "replace")

    def test_the_positions_page_offers_a_close(self):
        body = self._body("/positions/")
        self.assertIn(f'data-sv-close-trade="{self.trade.id}"', body)

    def test_the_portfolio_page_offers_a_close(self):
        body = self._body("/portfolio/")
        self.assertIn(f'data-sv-close-trade="{self.trade.id}"', body)

    def test_the_operations_center_live_tab_offers_a_close(self):
        body = self._body("/command/tab/live/")
        self.assertIn(f'data-sv-close-trade="{self.trade.id}"', body)

    def test_the_headband_position_popup_offers_a_close(self):
        """The fastest surface to reach — it lists open positions on every
        page of the platform and could only ever be read."""
        body = self._body("/positions/")
        self.assertIn("ipr-sym", body)
        self.assertIn("data-sv-close-trade", body.split("ip-dd-head", 1)[1])

    def test_the_flow_uses_the_house_dialog_and_never_a_native_one(self):
        import re
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        flow = src.split("CLOSE POSITION — the way out", 1)[1].split(
            "</script>", 1)[0]
        self.assertIn("SV.overlay.confirm", flow)
        stripped = re.sub(r"/\*.*?\*/", "", flow, flags=re.S)
        stripped = stripped.replace("SV.overlay.confirm(", "").replace(
            "SV.overlay.alert(", "")
        self.assertIsNone(
            re.search(r"(?<![.\w])(?:window\.)?(?:confirm|alert)\s*\(",
                      stripped),
            "the close flow fell back to a native dialog")

    def test_the_dialog_shows_what_closes_at_what_mark_for_what_r(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        flow = src.split("CLOSE POSITION — the way out", 1)[1]
        for fact in ("'Closing'", "'Mark now'", "'Realises'", "'Venue'"):
            self.assertIn(fact, flow, f"the confirm dialog omits {fact}")


class PositionsLayoutTests(TestCase):
    """The operator named this page: its card content forced the whole body
    to scroll sideways. A wide table may scroll inside its own wrapper; the
    body may not move, and nothing may be clipped."""

    @staticmethod
    def _positions_style():
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "dashboard"
               / "positions_list.html").read_text(encoding="utf-8")
        return src.split("<style>", 1)[1].split("</style>", 1)[0]

    def test_the_trade_row_wraps_instead_of_pushing_the_page(self):
        """Flex items do not shrink below min-content and .card is
        overflow:visible — without wrapping the row leaves the card and
        drags the body with it."""
        style = self._positions_style()
        row = style.split(".ph-trade-row {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-wrap: wrap", row)
        self.assertIn(".ph-trade-row > div { min-width: 0", style)

    def test_the_detail_grid_tracks_can_actually_shrink(self):
        """repeat(4, 1fr) sets a floor at its content width — the defect
        the sheet's OVERFLOW HONESTY section names."""
        style = self._positions_style()
        grid = style.split(".ph-detail-grid {", 1)[1].split("}", 1)[0]
        self.assertNotIn("repeat(4, 1fr)", grid)
        self.assertIn("minmax(", grid)

    def test_the_expanded_detail_scrolls_rather_than_amputating(self):
        style = self._positions_style()
        expanded = style.split(
            ".ph-trade-card.expanded .ph-trade-detail {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow: auto", expanded)

    def test_the_wide_table_scrolls_inside_its_own_wrapper(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "dashboard"
               / "positions_list.html").read_text(encoding="utf-8")
        open_tab = src.split("Current Positions", 1)[1].split(
            "Position Analytics", 1)[0]
        self.assertIn('<div class="table-wrapper">', open_tab)
        # Numbers and dates keep nowrap; only the identifier column wraps,
        # which is what stops one long rule name setting the table's floor.
        self.assertIn('class="sv-ident"', open_tab)
        self.assertIn('<th class="num">Qty</th>', open_tab)

    def test_no_multiline_hash_comment_slipped_into_the_touched_templates(self):
        """{# #} is single-line; spanning it renders the text verbatim."""
        import re
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for rel in (("templates", "dashboard", "positions_list.html"),
                    ("templates", "dashboard", "portfolio_overview.html"),
                    ("templates", "dashboard", "_command_live.html"),
                    ("templates", "dashboard", "_command_portfolio.html"),
                    ("templates", "dashboard", "_eye_body.html"),
                    ("templates", "base.html")):
            text = base.joinpath(*rel).read_text(encoding="utf-8")
            for m in re.finditer(r"\{#(.*?)#\}", text, re.S):
                self.assertNotIn("\n", m.group(1),
                                 f"{rel[-1]}: {m.group(1).strip()[:60]}")
