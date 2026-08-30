"""The broker's own reading of an interfaced account — beside, never instead.

The operator connected a funded ISA and the Operations Center showed the
seeded 10,000 — a number nobody typed. The fix is NOT to swap the display:
the displays compute one book, the gates divide by another, and a page
showing broker truth over gates using platform truth is worse than the
honest inconsistency ("2% of 50,000" that halts at 2% of 10,000).

So Phase A is a labelled broker cell BESIDE the platform figure, and a
broker-holdings panel of its own — no gate denominator touched anywhere.
These tests pin the contracts that make that safe:

  * The client refuses an UNSCOPED read. account("") spans every account
    under the login and kept whichever currency row arrived last, so a
    panel named for one account could show another's money.
  * Currency travels with the value. A UK ISA is GBP, the platform book
    defaults to EUR, and this platform has no FX conversion by design.
  * None means unmeasured and NEVER 0 — a gateway that restarts nightly
    for 2FA must read as stale, not as emptied.
  * Broker I/O lives in the sync beat task only. Pages read cached
    columns plus their AGE.
  * The holdings snapshot is DISPLAY ONLY — importing it into Position
    rows would double-count every bot-opened position, because
    unified_open_positions concatenates the two row sets with no dedup.
  * A funded ISA with no bot armed still gets the unknown-position sweep
    — it used to return a confident {unclaimed: 0} from a book nobody
    read.

Run with:  python manage.py test tests.test_broker_truth
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="bk_u"):
    return User.objects.create_user(name, password="x")


def _acct(user, account_id="U1234567", port=4001, **fields):
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, label="ISA_CAPITAL",
                                      host="ibgateway", port=port,
                                      client_id=1, **fields)
    if account_id:
        acct.set_credentials(account_id)
        acct.save(update_fields=["account_id_enc"])
    return acct


def _trader(account_id="U1234567"):
    """An IBKRTrader with the socket layer stubbed out."""
    from bot_program.engine.ibkr_client import IBKRTrader
    t = IBKRTrader(host="h", port=4001, client_id=201,
                   account_id=account_id, paper=False)
    t._connect = MagicMock(return_value=True)
    t._ib = MagicMock()
    return t


def _av(tag, value, currency):
    return SimpleNamespace(tag=tag, value=value, currency=currency)


class TheClientRefusesAnUnscopedReadTests(TestCase):
    """account("") spans every account under the login. The ORDER path
    already refuses that ambiguity; the balance path silently resolved
    it — to whichever row arrived last."""

    def test_account_values_refuses_an_empty_account_id(self):
        t = _trader(account_id="")
        self.assertIsNone(t.account_values())
        t._connect.assert_not_called()

    def test_broker_portfolio_refuses_too(self):
        t = _trader(account_id="")
        self.assertIsNone(t.broker_portfolio())
        t._connect.assert_not_called()

    def test_currency_rides_with_every_value(self):
        t = _trader()
        t._ib.accountValues.return_value = [
            _av("NetLiquidation", "52340.12", "GBP")]
        self.assertEqual(t.account_values()["NetLiquidation"],
                         ("52340.12", "GBP"))

    def test_a_BASE_row_wins_its_tag(self):
        """The old account() kept whichever row arrived LAST —
        nondeterministic on a multi-currency account."""
        t = _trader()
        t._ib.accountValues.return_value = [
            _av("TotalCashBalance", "100.00", "USD"),
            _av("TotalCashBalance", "50000.00", "BASE"),
            _av("TotalCashBalance", "1.00", "JPY"),
        ]
        self.assertEqual(t.account_values()["TotalCashBalance"],
                         ("50000.00", "BASE"))

    def test_without_a_BASE_row_first_wins_deterministically(self):
        t = _trader()
        t._ib.accountValues.return_value = [
            _av("TotalCashBalance", "100.00", "USD"),
            _av("TotalCashBalance", "1.00", "JPY"),
        ]
        self.assertEqual(t.account_values()["TotalCashBalance"],
                         ("100.00", "USD"))

    def test_unreachable_is_None_never_zeros(self):
        t = _trader()
        t._connect = MagicMock(return_value=False)
        self.assertIsNone(t.account_values())
        self.assertIsNone(t.net_liquidation())

    def test_net_liquidation_returns_value_and_currency(self):
        t = _trader()
        t._ib.accountValues.return_value = [
            _av("NetLiquidation", "52340.12", "GBP")]
        self.assertEqual(t.net_liquidation(), (52340.12, "GBP"))

    def test_a_zero_or_garbage_reading_is_not_a_reading(self):
        t = _trader()
        t._ib.accountValues.return_value = [
            _av("NetLiquidation", "0", "GBP"),
            _av("AvailableFunds", "not-a-number", "GBP")]
        self.assertIsNone(t.net_liquidation())


class TheHoldingsReadTests(TestCase):

    def _item(self, symbol="AZN", sec="STK", qty=100.0, account="U1234567",
              currency="GBP"):
        return SimpleNamespace(
            account=account, position=qty,
            contract=SimpleNamespace(symbol=symbol, secType=sec,
                                     currency=currency),
            averageCost=105.5, marketPrice=110.0, marketValue=qty * 110.0,
            unrealizedPNL=450.0, realizedPNL=0.0)

    def test_rows_carry_the_marks_and_the_currency(self):
        t = _trader()
        t._ib.portfolio.return_value = [self._item()]
        row = t.broker_portfolio()[0]
        self.assertEqual(row["symbol"], "AZN")
        self.assertEqual(row["market_value"], 11000.0)
        self.assertEqual(row["currency"], "GBP")
        self.assertEqual(row["side"], "BUY")

    def test_cash_pairs_are_rebuilt_to_match_trade_rows(self):
        """Forex contracts carry only the base in .symbol ("EUR") — the
        same convention get_positions() uses, so a row here can be
        matched against AssetBotTrade.symbol."""
        t = _trader()
        t._ib.portfolio.return_value = [
            self._item(symbol="EUR", sec="CASH", currency="USD")]
        self.assertEqual(t.broker_portfolio()[0]["symbol"], "EURUSD")

    def test_another_accounts_rows_are_filtered_out(self):
        """One login can hold several accounts; a panel named for the ISA
        must not list the taxable account's holdings."""
        t = _trader()
        t._ib.portfolio.return_value = [
            self._item(), self._item(symbol="TSLA", account="U9999999")]
        self.assertEqual([r["symbol"] for r in t.broker_portfolio()],
                         ["AZN"])

    def test_get_positions_contract_is_untouched(self):
        """Reconcile and the close-retry depend on its exact shape and
        its raise-on-unreachable; broker_portfolio must not have leaked
        into it."""
        t = _trader()
        t._connect = MagicMock(return_value=False)
        with self.assertRaises(RuntimeError):
            t.get_positions()


class InterfacedIsAConfigurationFactTests(TestCase):
    """Never `connected` — that boolean has no expiry and a gateway that
    restarts nightly for 2FA leaves it True forever. Reachability is the
    AGE of the last reading."""

    def test_no_account_row_is_not_backed(self):
        from bot_program.capital_truth import broker_backed
        self.assertIsNone(broker_backed(_user()))

    def test_an_account_with_no_id_is_not_backed(self):
        from bot_program.capital_truth import broker_backed
        u = _user("bk_noid")
        _acct(u, account_id="")
        self.assertIsNone(broker_backed(u))

    def test_a_stored_id_is_backed_whatever_connected_says(self):
        from bot_program.capital_truth import broker_backed
        u = _user("bk_yes")
        acct = _acct(u, connected=False)
        self.assertEqual(broker_backed(u), acct)

    def test_equity_is_None_until_a_sync_has_landed(self):
        """Unmeasured, not zero — and not the platform's book either."""
        from bot_program.capital_truth import account_equity
        u = _user("bk_nosync")
        _acct(u)
        self.assertIsNone(account_equity(u))

    def test_a_landed_reading_carries_value_currency_and_age(self):
        from bot_program.capital_truth import account_equity
        u = _user("bk_read")
        acct = _acct(u)
        acct.last_equity = Decimal("52340.12")
        acct.last_equity_currency = "GBP"
        acct.last_equity_at = timezone.now()
        acct.save()
        eq = account_equity(u)
        self.assertEqual(eq["value_text"], "52,340.12")
        self.assertEqual(eq["currency"], "GBP")
        self.assertLess(eq["age_seconds"], 60)

    def test_broker_view_is_None_when_not_interfaced(self):
        """The partial renders nothing rather than an empty frame."""
        from bot_program.capital_truth import broker_view
        self.assertIsNone(broker_view(_user("bk_none")))


class TheSyncTaskIsTheOnlyWriterTests(TestCase):

    def _run(self, reading=(52340.12, "GBP"), rows=None):
        from bot_program.tasks import sync_broker_account
        trader = MagicMock()
        trader.net_liquidation.return_value = reading
        trader.broker_portfolio.return_value = rows
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True), \
             patch("bot_program.engine.ibkr_client.IBKRTrader",
                   return_value=trader):
            return sync_broker_account.__wrapped__.__wrapped__(), trader

    def test_a_reading_lands_on_the_account_row(self):
        u = _user("bk_sync")
        acct = _acct(u)
        out, _ = self._run(rows=[{"symbol": "AZN"}])
        acct.refresh_from_db()
        self.assertEqual(float(acct.last_equity), 52340.12)
        self.assertEqual(acct.last_equity_currency, "GBP")
        self.assertIsNotNone(acct.last_equity_at)
        self.assertEqual(acct.broker_positions, [{"symbol": "AZN"}])
        self.assertEqual(out["stored"], 1)

    def test_unreachable_leaves_the_previous_reading_standing(self):
        """A dead gateway must read as STALE, never as emptied — the age
        stamp is the honesty, not a zero."""
        u = _user("bk_stale")
        acct = _acct(u)
        old = timezone.now()
        acct.last_equity = Decimal("50000")
        acct.last_equity_currency = "GBP"
        acct.last_equity_at = old
        acct.save()
        out, _ = self._run(reading=None, rows=None)
        acct.refresh_from_db()
        self.assertEqual(float(acct.last_equity), 50000.0)
        self.assertEqual(acct.last_equity_at, old)
        self.assertEqual(out["unreachable"], 1)
        self.assertEqual(out["stored"], 0)

    def test_work_without_store_grades_as_a_warning(self):
        """task_gate sums WORK vs DONE keys — a gateway down all day must
        look yellow on the health page, not green."""
        from core.task_gate import judge_result
        u = _user("bk_grade")
        _acct(u)
        out, _ = self._run(reading=None, rows=None)
        status, _detail = judge_result(out)
        self.assertEqual(status, "warning")

    def test_it_connects_with_the_probe_id_and_disconnects(self):
        """The trade clientId would EVICT the live trader; a held slot
        fails every later connection with error 326."""
        from bot_program.engine.ibkr_client import purpose_client_id
        u = _user("bk_probe")
        acct = _acct(u)
        from bot_program.tasks import sync_broker_account
        trader = MagicMock()
        trader.net_liquidation.return_value = (1.0, "GBP")
        trader.broker_portfolio.return_value = []
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True), \
             patch("bot_program.engine.ibkr_client.IBKRTrader",
                   return_value=trader) as ctor:
            # purpose_client_id reads CLIENT_ID_PURPOSE_OFFSET off the
            # class — give the mock the real table, or the derived id is
            # a MagicMock and the assertion tests nothing.
            ctor.CLIENT_ID_PURPOSE_OFFSET = {"trade": 0, "data": 100,
                                             "probe": 200}
            sync_broker_account.__wrapped__.__wrapped__()
        del purpose_client_id  # imported for documentation of intent only
        self.assertEqual(ctor.call_args.kwargs["client_id"],
                         acct.client_id + 200)
        trader.disconnect.assert_called()


class TheSweepEntersFromTheAccountTests(TestCase):
    """A funded ISA with hand-bought stock and NO bot armed used to get
    zero sweeps and return a confident {unclaimed: 0} from a book nobody
    read — the signature failure, in the sweep that exists to catch it."""

    def _sweep(self, positions):
        from bot_program.reconcile_asset import reconcile_unknown_positions
        trader = MagicMock()
        if isinstance(positions, Exception):
            trader.get_positions.side_effect = positions
        else:
            trader.get_positions.return_value = positions
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True), \
             patch("bot_program.engine.ibkr_client.IBKRTrader",
                   return_value=trader), \
             patch("bot_program.notifications.notify_unclaimed_position") \
                as notify:
            out = reconcile_unknown_positions(self.user)
        return out, notify

    def setUp(self):
        self.user = _user("bk_sweep")
        _acct(self.user)

    def test_an_isa_with_no_configs_is_still_swept(self):
        out, notify = self._sweep(
            [{"symbol": "AZN", "sec_type": "STK"}])
        self.assertEqual(out["unclaimed"], 1)
        self.assertIn("AZN", out["symbols"])
        notify.assert_called_once()

    def test_an_unreadable_broker_is_not_a_clean_sweep(self):
        out, notify = self._sweep(RuntimeError("socket down"))
        self.assertEqual(out["unclaimed"], 0)
        self.assertGreaterEqual(out["broker_unavailable"], 1)
        notify.assert_not_called()

    def test_reconcile_all_users_selects_the_config_less_operator(self):
        """Both existing selectors enter from Sauron's side of the ledger;
        the interfaced account is the third entry point."""
        from bot_program import reconcile_asset
        seen = []
        with patch.object(reconcile_asset, "reconcile_user",
                          side_effect=lambda u: (seen.append(u.username),
                                                 {"checked": 0})[1]), \
             patch.object(reconcile_asset, "reconcile_unknown_positions",
                          return_value={"unclaimed": 0}):
            reconcile_asset.reconcile_all_users()
        self.assertIn("bk_sweep", seen)


class ThePagesRenderTheBrokerBesideTheBookTests(TestCase):

    def setUp(self):
        self.user = _user("bk_ui")
        self.client.force_login(self.user)

    def _sync(self, rows=None):
        acct = self.user.ibkr_account
        acct.last_equity = Decimal("52340.12")
        acct.last_equity_currency = "GBP"
        acct.last_equity_at = timezone.now()
        if rows is not None:
            acct.broker_positions = rows
            acct.broker_positions_at = timezone.now()
        acct.save()

    def test_no_interfaced_account_renders_no_broker_cell(self):
        body = self.client.get("/command/").content.decode()
        self.assertNotIn("bk-card", body)
        self.assertNotIn("PLATFORM BOOK", body)

    def test_the_ops_center_names_both_books(self):
        """The unlabelled number beside a labelled one reads as the same
        fact twice — and these are different facts."""
        _acct(self.user)
        self._sync()
        body = self.client.get("/command/").content.decode()
        self.assertIn("PLATFORM BOOK", body)
        self.assertIn("ISA_CAPITAL", body)
        self.assertIn("52,340.12", body)
        self.assertIn("GBP", body)

    def test_an_unsynced_account_is_an_em_dash_with_the_reason(self):
        _acct(self.user)
        body = self.client.get("/command/").content.decode()
        self.assertIn("no reading yet", body)
        self.assertIn("sv-unknown", body.split("bk-card", 1)[1][:800])

    def test_the_reading_always_carries_its_age(self):
        _acct(self.user)
        self._sync()
        seg = self.client.get("/command/").content.decode()
        seg = seg.split("bk-card", 1)[1][:900]
        self.assertIn("data-sv-at", seg)

    def test_a_live_port_is_marked_live(self):
        _acct(self.user, port=4001)
        self._sync()
        body = self.client.get("/command/").content.decode()
        self.assertIn("bk-env--live", body)

    def test_the_positions_page_lists_broker_rows_with_claims(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        _acct(self.user)
        self._sync(rows=[
            {"symbol": "AZN", "sec_type": "STK", "side": "BUY",
             "qty": 100.0, "avg_cost": 105.5, "market_price": 110.0,
             "market_value": 11000.0, "unrealized_pnl": 450.0,
             "currency": "GBP"},
            {"symbol": "TSLA", "sec_type": "STK", "side": "BUY",
             "qty": 5.0, "avg_cost": 200.0, "market_price": 210.0,
             "market_value": 1050.0, "unrealized_pnl": 50.0,
             "currency": "USD"},
        ])
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="S", mode="live",
            symbols=["TSLA"], capital=Decimal("10000"), enabled=True)
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="TSLA", side="BUY",
            qty=Decimal("5"), entry_price=Decimal("200"), status="OPEN",
            paper=False, opened_at=timezone.now())
        body = self.client.get("/positions/").content.decode()
        self.assertIn("At the broker", body)
        # Search inside the broker panel only — the Sauron open-positions
        # list below it also renders TSLA, and matching that row instead
        # made this test read the wrong table.
        panel = body.split("At the broker", 1)[1]
        panel = panel.split("</table>", 1)[0]
        azn = panel.split(">AZN<", 1)[1][:600]
        tsla = panel.split(">TSLA<", 1)[1][:600]
        self.assertIn("UNCLAIMED", azn)
        self.assertNotIn("UNCLAIMED", tsla)
        self.assertIn("CLAIMED", tsla)

    def test_setup_shows_the_reading_beside_the_capital_form(self):
        """Adopting the broker's number goes through the EXISTING writer —
        the operator types it; nothing auto-adopts a gate denominator."""
        _acct(self.user)
        self._sync()
        body = self.client.get("/setup/").content.decode()
        self.assertIn("bk-card", body)
        self.assertIn("52,340.12", body)


class TheWiringExistsTests(TestCase):
    """A gated task with no component row no-ops forever and leaves no
    trace; a task with no beat entry never runs at all. Both silent."""

    def test_the_component_is_registered(self):
        from core.platform_control import DEFAULT_COMPONENTS
        keys = {c["key"] for c in DEFAULT_COMPONENTS}
        self.assertIn("broker_account_sync", keys)

    def test_the_beat_entry_exists_and_is_not_hour_gated(self):
        from config.celery import app
        entry = app.conf.beat_schedule.get("sync-broker-account")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["task"],
                         "bot_program.tasks.sync_broker_account")
        self.assertEqual(entry["schedule"], 900.0)


class TheSocatPortsAreFirstClassTests(TestCase):
    """The dockerised Gateway's ONLY working ports were unknown ports.

    The gnzsnz/ib-gateway image binds the Gateway's own 4001/4002 to the
    container's 127.0.0.1 and relays them out through socat as 4003
    (live) and 4004 (paper). From the web container, ibgateway:4001
    answers CONNECTION REFUSED forever — even after a perfect login —
    which reads exactly like "Gateway is down" and is not. The runbook
    taught 4001/4002 for weeks; the operator's first real Gateway proved
    it wrong with a refused socket under a logged-in container.

    Worse than the refusal: with 4003 unrecognised, `render_ibkr_env`
    derived TRADING_MODE=paper from it — which would relaunch a LIVE
    login in paper mode. The wrong direction to fail.
    """

    def test_4003_is_live_and_4004_is_paper(self):
        from bot_program.models import IBKRAccount
        u = _user("bk_socat")
        acct = _acct(u, port=4003)
        self.assertEqual(acct.env, "live")
        self.assertTrue(acct.is_live)
        self.assertTrue(acct.env_is_certain)
        acct.port = 4004
        self.assertEqual(acct.env, "paper")
        self.assertFalse(acct.is_live)

    def test_the_label_names_the_relay(self):
        """An operator debugging a refused 4001 needs the label itself to
        say the docker path is different."""
        u = _user("bk_socatlbl")
        acct = _acct(u, port=4003)
        self.assertIn("socat", acct.env_label)
        self.assertIn("LIVE", acct.env_label)

    def test_render_ibkr_env_derives_live_from_4003(self):
        """The one that costs real money if wrong: TRADING_MODE decides
        which account the Gateway LOGS INTO."""
        from io import StringIO

        from django.core.management import call_command
        u = _user("bk_render")
        acct = _acct(u, port=4003)
        acct.set_login("liveuser", "pw")
        acct.save()
        out = StringIO()
        call_command("render_ibkr_env", stdout=out)
        self.assertIn("IBKR_TRADING_MODE=live", out.getvalue())

    def test_and_paper_from_4004(self):
        from io import StringIO

        from django.core.management import call_command
        u = _user("bk_render_p")
        acct = _acct(u, port=4004)
        acct.set_login("paperuser", "pw")
        acct.save()
        out = StringIO()
        call_command("render_ibkr_env", stdout=out)
        self.assertIn("IBKR_TRADING_MODE=paper", out.getvalue())

    def test_the_runbook_teaches_the_relay_ports(self):
        """The document that taught the wrong ports must now teach the
        right ones, verify against them, and admit the correction."""
        from pathlib import Path

        from django.conf import settings
        text = (Path(settings.BASE_DIR) / "deploy" / "RUNBOOK.md"
                ).read_text(encoding="utf-8")
        self.assertIn("4003", text)
        self.assertIn("4004", text)
        self.assertIn("socat", text)
        self.assertIn("('ibgateway', 4004)", text)
        self.assertNotIn("with port `4002`\nfor paper or `4001` for live",
                         text)
