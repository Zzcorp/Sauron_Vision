"""THE GAP SHOWN POSITION BY POSITION, AND THE GATES COUNT WHAT eTORO
BLOCKS (2026-11-02).

The operator measured the gap himself on 2026-11-01 (one GET /portfolio,
nothing sent): every eToro position matched Sauron's figure to the cent
but two USD-based exotic pairs, where eToro blocked more than notional / L
at the very multiplier Sauron sent. The whole gap was those two rows. The
split called it "outside Sauron", because outside was a remainder (eToro's
used minus Sauron's rows), and the gates counted Sauron's formula alone.

  1. AN UNNAMED POSITION NO ROW CLAIMS IS REPORTED (the fix spec's fix 6).
     A position the client cannot name (ETORO:<id>) was counted
     "unreadable" by the sweep's config loop and dropped by its
     account-entry path, the only one a TAKE TRADE lane alone gets. It is
     now reported when no live row's position id claims it, with its side,
     units, open rate and multiplier, so it can be found in the eToro app.
     Report only; the three-hour dedupe stays.
  2. THE OUTSIDE FIGURE, POSITION BY POSITION. "Outside Sauron" is the
     positions eToro lists that no Sauron row claims, plus what eToro
     holds as frozen cash beyond Sauron's WORKING rows. eToro's own amount
     on Sauron's own rows, less Sauron's figure for them, is its own line,
     listed position by position on /treasury/ and in the treasury
     command. What neither explains is said as unexplained, with its age.
  3. THE GATES COUNT WHAT eTORO BLOCKS. The exposure gate and the used
     figures value an eToro row at the larger of Sauron's capital_at_work
     and eToro's own amount for its position, from the stored holdings
     when they are fresh and of the row's world. Never lower.
  4. NO MARK IS A DASH. A holding with no mark prints an em dash, never 0,
     in the treasury command and the positions page's broker card.

Ported in part from the investigation's red test FixSpecRed.test_R9.
Illustrative round numbers only; no account figures. No socket opens.

Run with:  python manage.py test tests.test_used_by_position
"""
import re
import socket
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bot_program.models import EtoroAccount
from tests.test_used_is_etoros import (_cfg, _etoro, _fresh, _held, _row,
                                       _used, _user)

LOCMEM = {"default": {"BACKEND":
                      "django.core.cache.backends.locmem.LocMemCache"}}
TRADER = "bot_program.engine.etoro_client.EtoroTrader"
UNNAMED_IID = 9001                 # an instrument no client here can name
GOLD_IID = 18                      # VENUE_ID_PINS: named from construction


class _NoNetwork:
    """Every connect raises and is recorded: no test may open a socket."""

    def __init__(self, testcase):
        self.attempts = []
        guard = self

        def _connect(sock, address, *a, **k):
            guard.attempts.append(repr(address))
            raise ConnectionRefusedError(f"test: no network ({address!r})")

        def _create(address, *a, **k):
            guard.attempts.append(repr(address))
            raise ConnectionRefusedError(f"test: no network ({address!r})")

        real = socket.socket.connect

        def _maybe(sock, address, *a, **k):
            if getattr(sock, "family", None) == getattr(socket, "AF_UNIX",
                                                        object()):
                return real(sock, address, *a, **k)
            return _connect(sock, address, *a, **k)

        for p in (mock.patch.object(socket.socket, "connect", _maybe),
                  mock.patch("socket.create_connection", _create)):
            p.start()
            testcase.addCleanup(p.stop)


def _raw(pid, iid, units, rate, lev, *, buy=True, amount=None):
    """One /portfolio row on the measured row's keys (capital ID)."""
    from tests.test_etoro_client import PORTFOLIO_ROW
    amt = (round(units * rate / max(int(lev), 1), 2) if amount is None
           else float(amount))
    return dict(PORTFOLIO_ROW, positionID=int(pid), instrumentID=int(iid),
                isBuy=bool(buy), units=float(units),
                initialUnits=float(units), openRate=float(rate), amount=amt,
                initialAmountInDollars=amt, leverage=int(lev))


def _account(user, *, demo=False):
    acct = EtoroAccount.objects.create(
        user=user, demo=demo, label="Main", is_primary_for_stocks=True,
        is_primary_for_commodity=True, connected=True)
    acct.set_credentials("k", "u")
    acct.save()
    return acct


def _instrument(symbol, cls):
    from instruments.models import Instrument
    Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": cls,
                                 "currency": "USD"})


def _live_row(cfg, symbol, *, pid, qty=1.0, entry=100.0, side="BUY",
              status="OPEN"):
    """A real eToro row of the live world that records its position id."""
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        status=status, paper=False,
        metadata={"broker": "etoro", "broker_env": "live",
                  "broker_position_id": str(pid)})


# ── 1. the sweep reports an unnamed position no row claims ───────────────

class TheAdapterKeepsWhatTheAppShowsTests(SimpleTestCase):
    """The rate and the multiplier of a position this client cannot name
    ride with it from get_positions to the sweep's reader: they are what
    the eToro app shows of it."""

    def test_an_unnamed_row_carries_its_open_rate_and_multiplier(self):
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.reconcile_asset import _broker_open_symbols
        t = EtoroTrader("k", "u", env="live")
        with mock.patch.object(EtoroTrader, "_open_positions", return_value=[
                _raw(7777000011, UNNAMED_IID, 3, 50.0, 2, buy=False),
                _raw(7777000012, GOLD_IID, 0.5, 4000.0, 1)]):
            rows = t.get_positions()
            state = _broker_open_symbols(t, asset_class="stock")
        unnamed, gold = rows
        self.assertIs(unnamed["symbol_unresolved"], True)
        self.assertEqual((unnamed["avg_cost"], unnamed["leverage"]),
                         (50.0, 2))
        self.assertNotIn("symbol_unresolved", gold)
        self.assertEqual(state["unnamed"], 1)
        [held] = [p for p in state["positions"] if p["unnamed"]]
        self.assertEqual(
            {k: held[k] for k in ("position_id", "side", "qty", "avg_cost",
                                  "leverage")},
            {"position_id": "7777000011", "side": "SELL", "qty": 3.0,
             "avg_cost": 50.0, "leverage": 2})

    def test_a_row_that_states_no_multiplier_carries_none(self):
        from bot_program.engine.etoro_client import EtoroTrader
        raw = _raw(7777000013, UNNAMED_IID, 3, 50.0, 1)
        raw.pop("leverage")
        t = EtoroTrader("k", "u", env="live")
        with mock.patch.object(EtoroTrader, "_open_positions",
                               return_value=[raw]):
            [row] = t.get_positions()
        self.assertNotIn("leverage", row)
        self.assertEqual(row["avg_cost"], 50.0)


@override_settings(CACHES=LOCMEM)
class TheSweepReportsAnUnnamedPositionTests(TestCase):

    def setUp(self):
        cache.clear()
        self.guard = _NoNetwork(self)
        self.user = _user("u3_sweep")
        self.acct = _account(self.user)
        _instrument("XAUUSD", "commodity")

    def tearDown(self):
        self.assertEqual(self.guard.attempts, [], "a socket was opened")

    def _take_trade_lane_alone(self):
        from bot_program.manual_trade import manual_config_for
        cfg = manual_config_for(self.user, "commodity")
        cfg.mode = "live"
        cfg.capital = Decimal("100000")
        cfg.save(update_fields=["mode", "capital"])
        return cfg

    def _gold_bot(self):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name="gold bot",
            mode="live", enabled=True, symbols=["XAUUSD"],
            capital=Decimal("100000"), base_currency="USD")

    def _sweep(self, raw):
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.reconcile_asset import reconcile_unknown_positions
        with mock.patch.object(EtoroTrader, "_open_positions",
                               return_value=list(raw)), \
                mock.patch("requests.post"):
            return reconcile_unknown_positions(_fresh(self.user))

    def _bells(self):
        from alerts.models import Notification
        return list(Notification.objects.filter(
            user=self.user, title__contains="no row claims").order_by("pk"))

    def test_R9_an_unnamed_position_with_the_take_trade_lane_alone(self):
        """The investigation's red test: a position placed in the eToro app
        on an instrument this client cannot name, with only the TAKE TRADE
        lane armed (the account-entry path): unclaimed 0 and no alert."""
        self._take_trade_lane_alone()
        out = self._sweep([_raw(7777000051, UNNAMED_IID, 0.5, 6000.0, 1)])
        self.assertEqual(out["unclaimed"], 1, out)
        self.assertEqual(out["symbols"],
                         ["unnamed position BUY 0.5 units opened at 6000 "
                          "(1x)"])
        [bell] = self._bells()
        self.assertEqual(bell.title,
                         "▲ 1 position at eToro Main that no row claims")
        self.assertTrue(bell.body.startswith(
            "unnamed position BUY 0.5 units opened at 6000 (1x). "),
            bell.body)

    def test_the_config_loop_reports_it_too(self):
        """A bot armed on gold: the unnamed position beside it is compared
        by its id and reported, no longer counted "unreadable"."""
        cfg = self._gold_bot()
        _live_row(cfg, "XAUUSD", pid=7777000061, qty=0.5, entry=4000.0)
        out = self._sweep([
            _raw(7777000061, GOLD_IID, 0.5, 4000.0, 1),
            _raw(7777000062, UNNAMED_IID, 2, 50.0, 2, buy=False)])
        self.assertEqual(out["unclaimed"], 1, out)
        self.assertEqual(out["symbols"],
                         ["unnamed position SELL 2 units opened at 50 "
                          "(2x)"])
        self.assertEqual(out["broker_unavailable"], 0, out)
        [bell] = self._bells()
        self.assertEqual(bell.title,
                         "▲ 1 position at EtoroTrader that no row claims")
        self.assertNotIn("XAUUSD", bell.body)

    def test_an_unnamed_position_a_row_claims_by_its_id_is_not_reported(self):
        """The old caution, narrowed to what it protects: an unnamed
        position whose id a live row records is that row's."""
        for path in ("account entry", "config loop"):
            with self.subTest(path=path):
                from bot_program.models import AssetBotConfig, AssetBotTrade
                AssetBotTrade.objects.all().delete()
                AssetBotConfig.objects.all().delete()
                lane = self._take_trade_lane_alone()
                if path == "config loop":
                    self._gold_bot()
                _live_row(lane, "COCOAUSD", pid=7777000071, qty=0.5,
                          entry=6000.0)
                out = self._sweep(
                    [_raw(7777000071, UNNAMED_IID, 0.5, 6000.0, 1)])
                self.assertEqual((out["unclaimed"], out["symbols"]), (0, []))
                self.assertEqual(self._bells(), [])

    def test_a_close_given_up_on_claims_it_and_is_said_apart(self):
        from bot_program.notifications import notify_given_up_held
        lane = self._take_trade_lane_alone()
        _live_row(lane, "COCOAUSD", pid=7777000072, qty=0.5, entry=6000.0,
                  status="ERROR")
        with mock.patch("bot_program.notifications.notify_given_up_held",
                        wraps=notify_given_up_held) as said:
            out = self._sweep([_raw(7777000072, UNNAMED_IID, 0.5, 6000.0, 1)])
        self.assertEqual(out["unclaimed"], 0, out)
        self.assertEqual(out["given_up_symbols"], ["COCOAUSD"])
        self.assertTrue(said.called)
        self.assertEqual(self._bells(), [])

    def test_the_alert_names_no_position_id(self):
        from bot_program import notifications as N
        self._take_trade_lane_alone()
        seen, real = [], N.dispatch_notification

        def spy(*args, **kwargs):
            seen.append(kwargs)
            return real(*args, **kwargs)

        with mock.patch("bot_program.notifications.dispatch_notification",
                        side_effect=spy):
            self._sweep([_raw(7777000081, UNNAMED_IID, 0.5, 6000.0, 1)])
        self.assertEqual(len(seen), 1)
        said = repr(seen[0])
        self.assertIn("unnamed position BUY 0.5 units opened at 6000 (1x)",
                      said)
        self.assertNotIn("7777000081", said)
        self.assertNotIn(str(UNNAMED_IID), said)

    def test_the_three_hour_dedupe_stays(self):
        self._take_trade_lane_alone()
        raw = [_raw(7777000091, UNNAMED_IID, 0.5, 6000.0, 1)]
        first = self._sweep(raw)
        second = self._sweep(raw)
        self.assertEqual((first["unclaimed"], second["unclaimed"]), (1, 1))
        self.assertEqual(len(self._bells()), 1)
        # a second unnamed position is a changed condition, said at once
        self._sweep(raw + [_raw(7777000092, UNNAMED_IID, 1, 6100.0, 1)])
        self.assertEqual(len(self._bells()), 2)
        self.assertEqual(self._bells()[-1].title,
                         "▲ 2 positions at eToro Main that no row claims")

    def test_two_alike_are_two_positions(self):
        self._take_trade_lane_alone()
        out = self._sweep([_raw(7777000101, UNNAMED_IID, 0.5, 6000.0, 1),
                           _raw(7777000102, UNNAMED_IID, 0.5, 6000.0, 1)])
        self.assertEqual(out["unclaimed"], 2)
        [bell] = self._bells()
        self.assertTrue(bell.body.startswith(
            "unnamed position BUY 0.5 units opened at 6000 (1x) ×2. "),
            bell.body)


# ── 2. the outside figure, position by position ──────────────────────────

def _fx_row(cfg, symbol, qty, entry, vpu, *, lev, pid, side="BUY",
            status="OPEN", env=None):
    """A forex row as the engine books it: its value per unit recorded."""
    t = _row(cfg, symbol, qty, entry, side=side, status=status, lev=lev,
             pid=pid, env=env)
    meta = dict(t.metadata)
    meta["value_per_unit"] = vpu
    type(t).objects.filter(pk=t.pk).update(metadata=meta)
    t.refresh_from_db()
    return t


class _TwoExoticPairs(TestCase):
    """Three eToro positions, all Sauron's, claimed by their ids: a stock
    at 1x where eToro's amount is Sauron's figure, and two USD-based
    exotic pairs where eToro blocks more than notional / L at the
    multiplier Sauron sent (illustrative: 100 counted, 150 and 120
    blocked). eToro's used is the three amounts, 2,270."""

    USED = "2270.00"

    def setUp(self):
        cache.clear()
        self.user = _user("u3_pairs")
        self.stocks = _cfg(self.user)
        self.fx = _cfg(self.user, cls="forex", name="fx")

    def _book(self, *, used=None, held_age_s=None, demo=False,
              mxn_amount=150.0, env=None, frozen="0.00", extra=()):
        held = [_held("AAPL", 10, 200, pid=31, amount=2000.0, lev=1),
                _held("USDMXN", 1000, 16, pid=32, amount=mxn_amount, lev=10),
                _held("USDZAR", 2000, 8, side="SELL", pid=33, amount=120.0,
                      lev=20)] + list(extra)
        _etoro(self.user, used=used or self.USED, held=held,
               held_age_s=held_age_s, demo=demo, frozen=frozen)
        self.aapl = _row(self.stocks, "AAPL", 10, 200, pid=31, env=env)
        self.mxn = _fx_row(self.fx, "USDMXN", 1000, 16, 0.0625, lev=10,
                           pid=32, env=env)
        self.zar = _fx_row(self.fx, "USDZAR", 2000, 8, 0.125, lev=20,
                           pid=33, side="SELL", env=env)


class TheOutsideFigureByPositionTests(_TwoExoticPairs):

    def test_an_excess_on_two_rows_and_none_outside(self):
        """The operator's case: the whole gap is on Sauron's own rows, and
        nothing is outside Sauron."""
        self._book()
        u = _used(self.user)
        self.assertEqual((u["sauron"], u["sauron_n"]), (2200.0, 3))
        self.assertEqual(u["outside"], 0.0)
        self.assertEqual(u["positions_part"], 0.0)
        self.assertEqual(u["excess"], 70.0)
        self.assertEqual(u["unexplained"], 0.0)
        self.assertEqual(
            [(r["symbol"], r["side"], r["sauron"], r["amount"], r["diff"])
             for r in u["excess_rows"]],
            [("USDMXN", "BUY", 100.0, 150.0, 50.0),
             ("USDZAR", "SELL", 100.0, 120.0, 20.0)])
        self.assertEqual(
            [(r["leverage"], r["venue_leverage"], r["diff_t"])
             for r in u["excess_rows"]], [(10, 10, "+50.00"),
                                          (20, 20, "+20.00")])
        self.assertEqual(u["split_t"], (
            "At that read: opened by Sauron 2,200.00 · eToro holds more than "
            "Sauron counts on Sauron's own rows 70.00 · outside Sauron 0.00 "
            "· P&L +500.00"))
        self.assertNotIn("unexplained", u["split_t"])

    def test_outside_is_the_positions_no_row_claims_plus_the_held_part(self):
        """An NVDA opened in the eToro app (350) and an order eToro holds
        with no Sauron row (500 of frozen cash): outside is those two, and
        the excess on Sauron's own rows is not in it."""
        self._book(used="3120.00", frozen="500.00",
                   extra=[_held("NVDA", 2, 175, pid=12, amount=350.0)])
        u = _used(self.user)
        self.assertEqual((u["positions_part"], u["held"], u["outside"]),
                         (350.0, 500.0, 850.0))
        self.assertEqual((u["excess"], u["unexplained"]), (70.0, 0.0))
        self.assertIn("· eToro holds more than Sauron counts on Sauron's own "
                      "rows 70.00 · outside Sauron 850.00 (held at eToro, no "
                      "Sauron row 500.00, read 4 min ago; positions 350.00) "
                      "· P&L", u["split_t"])

    def test_a_residual_neither_explains_is_said_unexplained_with_its_age(self):
        self._book(used="2570.00")
        u = _used(self.user)
        self.assertEqual((u["outside"], u["excess"], u["unexplained"]),
                         (0.0, 70.0, 300.0))
        self.assertIn("· outside Sauron 0.00 · unexplained 300.00 (eToro's "
                      "used read 4 min ago) · P&L", u["split_t"])
        self.assertEqual(u["unexplained_t"], "300.00")

    def test_holdings_read_apart_from_the_cells_say_both_ages(self):
        self._book(used="2570.00", held_age_s=1200)
        self.assertIn("· unexplained 300.00 (eToro's used read 4 min ago, "
                      "its positions 20 min ago) · ", _used(self.user)["split_t"])

    def test_a_residual_below_zero_is_said_the_other_way_round(self):
        self._book(used="2070.00")
        u = _used(self.user)
        self.assertEqual(u["unexplained"], -200.0)
        self.assertIn("· outside Sauron 0.00 · unexplained: Sauron's rows "
                      "count 200.00 more than eToro's used (eToro's used read "
                      "4 min ago; a row eToro no longer holds, or an "
                      "unconverted currency) · P&L", u["split_t"])
        self.assertNotIn("outside Sauron -", u["split_t"])

    def test_holdings_never_read_leave_outside_unread_and_the_rest_unexplained(self):
        self._book()
        EtoroAccount.objects.filter(user=self.user).update(
            broker_positions_at=None)
        u = _used(self.user)
        self.assertIsNone(u["outside"])
        self.assertIsNone(u["positions_part"])
        self.assertIsNone(u["excess"])
        self.assertEqual(u["excess_rows"], [])
        self.assertEqual(u["unexplained"], 70.0)
        self.assertIn("· outside Sauron — (eToro's positions never read) · "
                      "unexplained 70.00 (eToro's used read 4 min ago, its "
                      "positions never read) · ", u["split_t"])

    def test_less_on_sauron_s_own_rows_is_said_the_other_way_round(self):
        """eToro's amount under Sauron's figure on one row, over it on the
        other: the line is their sum, and below zero it says so."""
        self._book(mxn_amount=40.0, used="2160.00")
        u = _used(self.user)
        self.assertEqual((u["excess"], u["unexplained"]), (-40.0, 0.0))
        self.assertEqual([(r["symbol"], r["diff_t"]) for r in u["excess_rows"]],
                         [("USDZAR", "+20.00"), ("USDMXN", "-60.00")])
        self.assertIn("· Sauron counts more than eToro holds on Sauron's own "
                      "rows 40.00 · outside Sauron 0.00 · P&L", u["split_t"])
        self.assertNotIn("eToro holds more than", u["split_t"])

    def test_an_amount_etoro_did_not_state_is_no_excess(self):
        """Never an estimate on Sauron's own rows: a holding that carries
        no amount says nothing of what eToro blocks for it."""
        self._book(mxn_amount=None)
        u = _used(self.user)
        self.assertEqual(u["excess"], 20.0)
        self.assertEqual([r["symbol"] for r in u["excess_rows"]], ["USDZAR"])
        # eToro's 150 on it is in its used, and nothing here says it
        self.assertEqual(u["unexplained"], 50.0)

    def test_only_rows_counted_at_that_read_take_part(self):
        """A row booked after eToro's cells were read is not in eToro's
        used: its own excess is not in the line either."""
        self._book()
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=self.mxn.pk).update(
            opened_at=timezone.now() - timedelta(seconds=10))
        u = _used(self.user)
        self.assertEqual(u["since_n"], 1)
        self.assertEqual(u["excess"], 20.0)
        self.assertEqual([r["symbol"] for r in u["excess_rows"]], ["USDZAR"])

    def test_the_title_says_what_outside_and_the_line_are(self):
        self._book()
        title = _used(self.user)["title"]
        for words in ("Outside Sauron is the positions eToro lists that no "
                      "Sauron row claims",
                      "eToro holds more than Sauron counts on Sauron's own "
                      "rows", "unexplained"):
            self.assertIn(words, title)


class TheTreasuryListsTheExcessTests(_TwoExoticPairs):

    def test_the_page_lists_it_position_by_position(self):
        self._book()
        self.client.force_login(self.user)
        page = self.client.get(reverse("treasury_page")).content.decode()
        at = page.index("eToro holds more than Sauron counts on Sauron's own "
                        "rows — position by position")
        card = page[at:page.index("Every broker")]
        rows = re.findall(r'<td data-label="Symbol"[^>]*>([^<]*)</td>.*?'
                          r'<td data-label="Sauron counts"[^>]*>([^<]*)</td>'
                          r'.*?<td data-label="eToro amount"[^>]*>'
                          r'([^<]*)</td>.*?<td data-label="eToro minus '
                          r'Sauron"[^>]*>([^<]*)</td>', card, re.S)
        self.assertEqual([tuple(c.strip() for c in r) for r in rows],
                         [("USDMXN", "100.00", "150.00", "+50.00"),
                          ("USDZAR", "100.00", "120.00", "+20.00")])
        self.assertIn("70.00", card)
        self.assertIn("while eToro's holdings are at most an hour old", card)
        # the split's own line, a variable the page escapes
        self.assertIn("eToro holds more than Sauron counts on Sauron&#x27;s "
                      "own rows 70.00", page)

    def test_the_command_lists_it_in_section_5b(self):
        self._book()
        out = StringIO()
        call_command("treasury", user="u3_pairs", stdout=out)
        body = out.getvalue()
        part = body[body.index("5b. OUTSIDE SAURON AT eTORO"):
                    body.index("6. DIVERGENCE")]
        self.assertIn("eToro holds more than Sauron counts on Sauron's own "
                      "rows: 70.00 in all", part)
        squeezed = re.sub(r" +", " ", part)
        self.assertIn("USDMXN BUY 1000.0000 lev 10x/10x Sauron 100.00 eToro "
                      "150.00 +50.00", squeezed)
        self.assertIn("USDZAR SELL 2000.0000 lev 20x/20x Sauron 100.00 eToro "
                      "120.00 +20.00", squeezed)
        self.assertNotIn("AAPL", part)
        self.assertIn("while eToro's holdings are at most an hour old", part)

    def test_the_footers_say_outside_is_by_position(self):
        self._book(extra=[_held("NVDA", 2, 175, pid=12, amount=350.0)],
                   used="2620.00")
        self.client.force_login(self.user)
        page = self.client.get(reverse("treasury_page")).content.decode()
        card = page[page.index("Outside Sauron at eToro"):]
        card = card[:card.index("Every broker")]
        out = StringIO()
        call_command("treasury", user="u3_pairs", stdout=out)
        for text in (card.replace("&#x27;", "'"), out.getvalue()):
            self.assertIn("these positions plus what eToro holds as frozen "
                          "cash beyond Sauron's WORKING rows", text)
            self.assertNotIn("eToro's used minus Sauron's rows", text)
        # the book card's own line and the split's title say it too
        for text in (page.replace("&#x27;", "'"), out.getvalue()):
            self.assertNotIn("used minus", text)


# ── 3. the gates count what eToro blocks ─────────────────────────────────

class TheGatesCountWhatEtoroBlocksTests(_TwoExoticPairs):

    def _gate(self):
        from portfolio.risk_gate import limits_book, open_capital_at_work
        return open_capital_at_work(_fresh(self.user), limits_book())

    def _summary(self):
        from portfolio.services import capital_summary
        return capital_summary(_fresh(self.user))

    def test_a_fresh_snapshot_values_each_row_at_the_larger(self):
        self._book()
        book = self._gate()
        self.assertEqual(book["live_total"], 2270.0)
        self.assertEqual((book["etoro_over"], book["etoro_over_n"]),
                         (70.0, 2))
        cap = self._summary()
        self.assertEqual(cap["used_live"], 2270.0)
        by = {(c["asset_class"], c["mode"]): c["used"]
              for c in cap["classes"]}
        self.assertEqual((by[("forex", "live")], by[("stock", "live")]),
                         (270.0, 2000.0))

    def test_a_stale_snapshot_leaves_saurons_formula(self):
        from bot_program.capital_truth import TRACKING_FRESH_SECONDS
        self._book(held_age_s=TRACKING_FRESH_SECONDS + 60)
        book = self._gate()
        self.assertEqual(book["live_total"], 2200.0)
        self.assertEqual((book["etoro_over"], book["etoro_over_n"]),
                         (0.0, 0))
        self.assertEqual(self._summary()["used_live"], 2200.0)

    def test_a_snapshot_of_the_other_world_leaves_it(self):
        with self.subTest("the account trades demo, the rows are real"):
            self._book(demo=True)
            self.assertEqual(self._gate()["live_total"], 2200.0)
            self.assertEqual(self._summary()["used_live"], 2200.0)
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.all().delete()
        EtoroAccount.objects.all().delete()
        with self.subTest("the account trades live, the rows are demo"):
            self._book(env="paper")
            self.assertEqual(self._gate()["live_total"], 2200.0)
            self.assertEqual(self._summary()["used_paper"], 2200.0)

    def test_it_never_lowers_a_figure(self):
        self._book(mxn_amount=40.0)
        self.assertEqual(self._gate()["live_total"], 2220.0)
        self.assertEqual(self._summary()["used_live"], 2220.0)

    def test_a_row_whose_id_the_snapshot_does_not_list_keeps_its_figure(self):
        self._book()
        from bot_program.models import AssetBotTrade
        meta = dict(self.mxn.metadata, broker_position_id="7777000999")
        AssetBotTrade.objects.filter(pk=self.mxn.pk).update(metadata=meta)
        self.assertEqual(self._gate()["live_total"], 2220.0)

    def test_a_close_given_up_on_is_valued_the_same_way(self):
        self._book()
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=self.mxn.pk).update(status="ERROR")
        book = self._gate()
        self.assertEqual((book["abandoned_total"], book["abandoned_n"]),
                         (150.0, 1))
        self.assertEqual(book["live_total"], 2270.0)
        self.assertEqual(self._summary()["used_live"], 2270.0)

    def test_the_exposure_refusal_says_what_etoro_blocks(self):
        from portfolio.risk_gate import exposure_state, limits_book
        self._book()
        book = limits_book()
        book.max_total_exposure_pct = 20          # of the 10,000 account
        book.save(update_fields=["max_total_exposure_pct"])
        state = exposure_state(_fresh(self.user), portfolio=book,
                               venue="live")
        self.assertFalse(state["ok"], state["reason"])
        self.assertEqual(state["committed"], 2270.0)
        self.assertIn("on 2 of those positions eToro blocks 70.00 more than "
                      "Sauron's formula counts", state["reason"])

    def test_the_pledge_gate_is_unchanged(self):
        """It judges every eToro order on eToro's own cells, which hold the
        amounts already: nothing here is added to it."""
        from types import SimpleNamespace

        from bot_program.asset_engine.base import AssetBot
        self._book()
        acct = EtoroAccount.objects.get(user=self.user)
        since = AssetBot._pledged_since(SimpleNamespace(user=self.user),
                                        acct.last_margin_at, "etoro")
        self.assertEqual(since, 0.0)


class TheHelpersReadersTests(SimpleTestCase):
    """One helper, read by the exposure gate and the used figures only; it
    reads the stored holdings itself and never bot_program.etoro_used."""

    READERS = {
        ("portfolio/risk_gate.py", "open_capital_at_work"),
        ("portfolio/services.py", "capital_summary"),
    }

    def test_only_the_exposure_gate_and_the_used_figures_read_it(self):
        from tests.test_closes_never_abandoned import _callers_of
        self.assertEqual(_callers_of("etoro_amount_floor"), self.READERS)

    def test_it_never_reads_the_split(self):
        import inspect

        from portfolio import services
        src = inspect.getsource(services.etoro_amount_floor)
        self.assertNotIn("etoro_used", src)
        from django.conf import settings
        from pathlib import Path
        gate = (Path(settings.BASE_DIR) / "portfolio" / "risk_gate.py"
                ).read_text(encoding="utf-8")
        self.assertNotIn("etoro_used", gate)


# ── 4. no mark is a dash ─────────────────────────────────────────────────

class NoMarkIsADashTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _user("u3_marks")

    def _command(self):
        out = StringIO()
        call_command("treasury", user="u3_marks", stdout=out)
        return re.sub(r" +", " ", out.getvalue())

    def test_the_command_prints_a_dash_for_a_holding_with_no_mark(self):
        _etoro(self.user, held=[_held("NVDA", 2, 175, pid=12)])
        body = self._command()
        part = body[body.index("5. WHAT EACH BROKER SAYS IT HOLDS"):
                    body.index("5b. OUTSIDE SAURON")]
        self.assertIn("NVDA BUY 2.0000 @ 175.0000 mark — ", part)
        self.assertNotIn("mark 0.0000", part)

    def test_a_holding_with_a_mark_keeps_it(self):
        from tests.test_treasury import HELD_AAPL, a_saxo
        a_saxo(self.user, held=[HELD_AAPL])
        body = self._command()
        self.assertIn("AAPL BUY 10.0000 @ 200.0000 mark 210.0000 ", body)

    def _cells(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("positions_list")).content.decode()
        panel = page[page.index("At the broker"):]
        panel = panel[:panel.index("</table>")]
        return (re.findall(r'<td data-label="Mark">(.*?)</td>', panel, re.S),
                re.findall(r'<td data-label="Value">(.*?)</td>', panel,
                           re.S))

    def test_the_positions_card_prints_a_dash_for_mark_and_value(self):
        _etoro(self.user, held=[_held("NVDA", 2, 175, pid=12)])
        marks, values = self._cells()
        self.assertEqual(len(marks), 1)
        for cell in marks + values:
            self.assertIn("—", cell)
            self.assertIsNone(re.search(r"\d", cell), cell)

    def test_the_positions_card_keeps_a_mark_the_broker_gave(self):
        from tests.test_treasury import HELD_AAPL, a_saxo
        a_saxo(self.user, held=[HELD_AAPL])
        marks, values = self._cells()
        self.assertEqual(([m.strip() for m in marks],
                          [v.strip() for v in values]),
                         (["210"], ["2100.00"]))
