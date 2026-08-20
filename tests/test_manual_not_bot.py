"""A trade the operator took by hand is the OPERATOR'S, end to end.

The operator pressed TAKE TRADE and the platform called it a bot trigger in
two places at once:

  * the fill went out through `notify_bot_fill_open`, so it landed in the
    bell typed "Bot Event" — and vanished entirely for an operator who had
    turned the bots' alerts off, which is not a preference about their own
    fills at all.
  * the headband's BOT cell listed the per-class "manual" AssetBotConfig as
    a bot and counted its positions as bot positions. That config is enabled
    with an EMPTY symbols list — it manages hand-taken trades and can never
    open one — so the cell was claiming automation that does not exist, and
    on an account with no other config it went further and reported STALLED
    because the "bot" the operator never armed had never ticked.

Both halves are attribution, not visibility: every assertion that a figure
drops out of the BOT cell is paired with one that the same trade is still
counted where it belongs.

Run with:  python manage.py test tests.test_manual_not_bot
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone


# ── Fixtures ─────────────────────────────────────────────────────────────

def _user(name):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    return inst


def _signal(inst, *, direction="bullish", entry=60000, stop=59100,
            target=61800):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="high", title=f"{inst.symbol} {direction}", description="d",
        rule_name="test_rule", score=0.8, sub_scores={},
        price_at_signal=Decimal(str(entry)),
        suggested_entry=Decimal(str(entry)),
        suggested_stop=Decimal(str(stop)),
        suggested_target=Decimal(str(target)), is_active=True)


def _components():
    """Seed the platform switches the bot tick passes, both ON.

    A fresh database has no component rows and guarded_task reads a missing
    row as off, which would park every BOT cell at HALTED and hide the thing
    these tests are actually measuring.
    """
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    PlatformComponent.objects.filter(
        key__in=("platform_master", "pipeline_asset_bots")).update(
        is_enabled=True)


def _bot_config(user, name="alpha", asset_class="crypto", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(enabled=True, mode="paper", symbols=[],
                    capital=Decimal("10000"), base_currency="USD")
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, **defaults)


def _tick(cfg, seconds_ago=30):
    """The heartbeat the runner writes, so the fleet reads as ticking."""
    extras = dict(cfg.extras or {})
    extras["last_tick_at"] = (
        timezone.now() - timedelta(seconds=seconds_ago)).isoformat()
    extras["last_tick_status"] = "OK"
    cfg.extras = extras
    cfg.save(update_fields=["extras", "updated_at"])
    return cfg


def _trade(cfg, symbol, **kw):
    from bot_program.models import AssetBotTrade
    fields = dict(side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
                  status="OPEN")
    fields.update(kw)
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, **fields)


def _hand_taken(user, symbol, asset_class="crypto", **kw):
    """A position opened through TAKE TRADE, on the real manual config."""
    from bot_program.manual_trade import MANUAL_RULE, manual_config_for
    cfg = manual_config_for(user, asset_class)
    stop = kw.get("stop_loss")
    metadata = {"manual": True,
                "initial_stop_loss": float(stop) if stop is not None else None}
    kw.setdefault("metadata", metadata)
    return _trade(cfg, symbol, rule_name=MANUAL_RULE, paper=True, **kw)


def _ctx(user):
    from core.context_processors import sauron_context
    request = RequestFactory().get("/")
    request.user = user
    return sauron_context(request)


# ── 1. The bell says who did it ──────────────────────────────────────────

class ManualFillNotificationTests(TestCase):
    def setUp(self):
        self.user = _user("mnb_bell")

    def _notify(self):
        from bot_program.notifications import notify_manual_fill_open
        return notify_manual_fill_open(
            self.user, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("0.5"), entry_price=Decimal("60000"))

    def test_the_row_is_not_typed_as_a_bot_event(self):
        from alerts.models import Notification
        self.assertTrue(self._notify())
        n = Notification.objects.get(user=self.user)
        self.assertNotEqual(n.notification_type, "bot")
        # "portfolio" is a real member of Notification.TYPES, so the bell and
        # the inbox tab render a label rather than a raw slug.
        self.assertEqual(n.notification_type, "portfolio")
        self.assertIn(n.notification_type, {t[0] for t in Notification.TYPES})

    def test_the_title_says_the_operator_did_it_in_words(self):
        from alerts.models import Notification
        self._notify()
        n = Notification.objects.get(user=self.user)
        self.assertIn("BTCUSD", n.title)
        self.assertIn("BUY", n.title)
        self.assertIn("by hand", n.title)
        self.assertIn("TAKE TRADE", n.body)
        # The rule name is never echoed: "manual_take" sitting where a bot
        # fill prints its rule reads as a rule that fired.
        self.assertNotIn("manual_take", n.body)

    def test_the_words_survive_the_external_channels(self):
        """Telegram/mail/Discord get the title with the mark stripped, so the
        attribution cannot live in the glyph alone."""
        from bot_program.notifications import _plain_title
        plain = _plain_title("▸ BTCUSD BUY opened by hand")
        self.assertTrue(plain.startswith("BTCUSD"))
        self.assertIn("by hand", plain)

    def test_muting_the_bots_does_not_mute_the_operators_own_fill(self):
        """`receive_bot_alerts` answers "tell me when the program acts on its
        own". An operator who turns it off has not asked to stop hearing
        about the trades they take themselves."""
        from alerts.models import Notification, UserNotificationPrefs
        from bot_program.notifications import notify_bot_fill_open
        UserNotificationPrefs.objects.create(user=self.user,
                                             receive_bot_alerts=False)
        self.assertTrue(self._notify())
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

        # ...while the bot's own fill stays gated, which is what the switch
        # is for.
        self.assertFalse(notify_bot_fill_open(
            self.user, asset_class="crypto", symbol="ETHUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100")))
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_the_kind_is_registered_as_an_operator_kind(self):
        from bot_program.notifications import (BOT_KINDS, OPERATOR_KINDS,
                                               dispatch_notification)
        self.assertIn("manual_fill_open", OPERATOR_KINDS)
        self.assertNotIn("manual_fill_open", BOT_KINDS)
        # The unknown-kind guard still refuses everything else.
        self.assertFalse(dispatch_notification(self.user, "nonsense",
                                               title="t"))

    def test_the_row_pushes_silent_because_take_trade_pushes_its_own(self):
        """manual_trade raises the same fill_open banner on /ws/eye/ that the
        engine does. The row still moves the bell badge; drawing a second
        card for one fill is the duplicate this flag exists to stop."""
        with patch("dashboard.consumers.push_eye_event") as pushed:
            self._notify()
        self.assertTrue(pushed.called)
        self.assertTrue(pushed.call_args.args[2]["silent"])

    def test_the_link_lands_on_the_operators_own_book_not_the_fleet(self):
        from alerts.models import Notification
        self._notify()
        n = Notification.objects.get(user=self.user)
        # No trade id was passed, so the fallback is exercised — and it must
        # not be /asset-bots/, which is the bot fleet's config list.
        self.assertEqual(n.url, "/positions/")


class TakeTradeEndToEndTests(TestCase):
    """The button itself, not just the helper it should be calling."""

    def test_pressing_take_trade_lands_in_the_bell_as_the_operators(self):
        from alerts.models import Notification, UserNotificationPrefs
        from bot_program.manual_trade import execute_take_trade
        user = _user("mnb_e2e")
        UserNotificationPrefs.objects.create(user=user,
                                             receive_bot_alerts=False)
        inst = _quote("BTCUSD", 60000)
        out = execute_take_trade(user, _signal(inst))
        self.assertTrue(out.get("ok"), out)

        rows = list(Notification.objects.filter(user=user))
        self.assertEqual(len(rows), 1, rows)
        self.assertNotEqual(rows[0].notification_type, "bot")
        self.assertIn("by hand", rows[0].title)
        self.assertIn(str(out["trade_id"]), rows[0].url)


# ── 2. The headband's BOT cell counts bots ───────────────────────────────

class HeadbandAttributionTests(TestCase):
    def setUp(self):
        _components()
        self.user = _user("mnb_band")

    def _bot(self):
        return _ctx(self.user)["panel_bot"]

    def test_a_hand_taken_trade_is_not_a_bot_program(self):
        """The reported bug, end to end: the only config on this account is
        the manual one, so there is no bot — and the cell used to answer
        "0 live · 1 paper · 1 open", STALLED, because that config had never
        ticked."""
        _quote("BTCUSD", "110")
        _hand_taken(self.user, "BTCUSD", entry_price=Decimal("100"),
                    stop_loss=Decimal("95"))
        bot = self._bot()
        self.assertEqual(bot["state"], "NONE")
        self.assertEqual(bot["configs"], 0)
        self.assertEqual(bot["enabled"], 0)
        self.assertEqual(bot["paper"], 0)
        self.assertEqual(bot["open"], 0)
        self.assertEqual(bot["bots"], [])
        self.assertIsNone(bot["open_r_display"])

    def test_the_hand_taken_position_is_still_counted_and_named(self):
        """Attribution, not concealment: the same trade is on the POSITIONS
        cell, in the manual block, and named in the string the dropdown and
        the cell tooltip both print."""
        _quote("BTCUSD", "110")
        _hand_taken(self.user, "BTCUSD", entry_price=Decimal("100"),
                    stop_loss=Decimal("95"))
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_positions"], 1)
        self.assertEqual(ctx["panel_bot"]["manual"]["open"], 1)
        self.assertEqual(ctx["panel_bot"]["manual"]["configs"], 1)
        self.assertIn("by hand", ctx["panel_bot"]["reason"])

    def test_a_bot_the_user_named_manual_is_still_a_bot(self):
        """`manual_trade` REFUSES to trade through a config the user named
        "manual" and gave symbols to — that one scans a real universe and can
        open on its own, so the cell must keep counting it."""
        _tick(_bot_config(self.user, name="manual", symbols=["BTCUSD"]))
        bot = self._bot()
        self.assertEqual(bot["configs"], 1)
        self.assertEqual([b["name"] for b in bot["bots"]], ["manual"])
        self.assertEqual(bot["state"], "PAPER")

    def test_open_and_open_r_count_the_same_positions(self):
        """They sit side by side in the dropdown. A bot-only OPEN beside an
        OPEN R that still carried the operator's R would be the platform's
        oldest disease: a cell and its popup disagreeing on one screen."""
        cfg = _tick(_bot_config(self.user))
        _quote("BTCUSD", "110")
        _trade(cfg, "BTCUSD", entry_price=Decimal("100"),
               stop_loss=Decimal("95"))          # +2.00R
        _quote("ETHUSD", "110")
        _hand_taken(self.user, "ETHUSD", entry_price=Decimal("100"),
                    stop_loss=Decimal("90"))     # +1.00R, the operator's
        bot = self._bot()
        self.assertEqual(bot["open"], 1)
        self.assertEqual(bot["open_r_display"], "+2.00R")
        self.assertEqual(bot["manual"]["open"], 1)
        # Both positions are still in the book the POSITIONS cell counts.
        self.assertEqual(_ctx(self.user)["panel_positions"], 2)

    def test_the_fleets_24h_figures_are_the_fleets_alone(self):
        cfg = _tick(_bot_config(self.user))
        now = timezone.now()
        _trade(cfg, "BTCUSD", status="CLOSED", pnl=Decimal("30"),
               closed_at=now - timedelta(minutes=5))
        _hand_taken(self.user, "ETHUSD", status="CLOSED", pnl=Decimal("-10"),
                    closed_at=now - timedelta(minutes=6))
        bot = self._bot()
        self.assertEqual(bot["closed_24h"], 1)
        self.assertEqual(bot["opened_24h"], 1)
        self.assertEqual(bot["winrate"], 100)
        self.assertEqual(bot["pnl_24h_display"], "+30.00")
        self.assertEqual(bot["manual"]["closed_24h"], 1)
        self.assertEqual(bot["manual"]["pnl_24h_display"], "-10.00")

    def test_a_hand_taken_close_is_still_money_the_day_made(self):
        """The realised line answers "what did today make", where a close the
        operator made by hand is money like any other. Narrowing the raw
        figure the way the BOT cell's display is narrowed would have this
        strip report "nothing closed" on a day the operator closed three."""
        _hand_taken(self.user, "ETHUSD", status="CLOSED", pnl=Decimal("-10"),
                    closed_at=timezone.now() - timedelta(minutes=6))
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_realised_24h_n"], 1)
        self.assertEqual(ctx["panel_realised_24h_display"], "-10.00")
        self.assertEqual(ctx["panel_bot"]["pnl_24h"], -10.0)
        # ...and the BOT cell still claims none of it.
        self.assertEqual(ctx["panel_bot"]["closed_24h"], 0)
        self.assertIsNone(ctx["panel_bot"]["pnl_24h_display"])

    def test_nothing_at_all_still_measures_nothing(self):
        """The em-dash rule survives the carve-out: no bot and no manual
        trade must not manufacture a 0% win rate or a +0.00."""
        _tick(_bot_config(self.user))
        bot = self._bot()
        self.assertIsNone(bot["winrate"])
        self.assertIsNone(bot["pnl_24h_display"])
        self.assertIsNone(bot["pnl_24h"])
        self.assertIsNone(bot["manual"]["pnl_24h_display"])
        self.assertEqual(bot["manual"]["open"], 0)
