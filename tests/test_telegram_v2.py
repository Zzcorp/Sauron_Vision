"""The Telegram messages written for people (2026-09-27).

The operator, 2026-09-27: "the telegram messages are still basic still".
The fills read like a log line ("FOREX · qty 7900.00000000 @ 1.60725571",
"Rule golden_cross", "Trade #108"), with the attack mode and a stop eToro
moved riding inside rule_name; the father reads them on a phone for three
weeks.

Pinned here, with requests.post patched (no real HTTP):
  * the exact HTML of a bot open (paper EURCAD), a real-money eToro open
    with the attack mode and a stop eToro moved (the engine's own words),
    a close in profit, a close at a loss by its stop, a hand-taken open,
    a working entry that filled (through the engine), and a signal;
  * ONE URL button, only with a DOMAIN a phone can open, never a callback
    button anywhere, and a refused button costing the button, never the
    message;
  * the folded record escaped; 4,096 characters still held, the record
    going first;
  * the bell row still created, the message's facts as its items;
  * every builder read for jargon: no snake_case outside a code key, no
    "None", no "Decimal(", no eight decimals;
  * the words in one place (money, price, quantity, percent, units);
  * a caller that passes none of the new fields renders as before, the
    Eye's replies too.

Run with:  python manage.py test tests.test_telegram_v2
"""
import inspect
import json
import os
import re
from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

TOKEN = "123456:telegram-v2-test-token"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100999",
       "DOMAIN": ""}
HOST = "sauron.invalid"
UTC = dt_tz.utc
GREEN, RED = "\U0001F7E2", "\U0001F534"
HAND, WAIT = "\U0000270B", "\U000023F3"
GAIN, LOSS, FLAT = "\U00002705", "\U0001F53B", "\U000026AA"
MINUS = "\U00002212"
SIGNAL_UP = "\U0001F4C8"


def _ok():
    return MagicMock(ok=True, status_code=200, text='{"ok":true}')


def _payloads(post):
    return [c.kwargs["json"] for c in post.call_args_list]


def _button(path, text="Open position"):
    return {"inline_keyboard": [[{"text": text,
                                  "url": f"https://{HOST}{path}"}]]}


def _user(name="tg2_ops"):
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile
    u = User.objects.create_user(name, password="x", email=f"{name}@x.io",
                                 is_staff=True)
    p, _ = UserNotificationPrefs.objects.get_or_create(user=u)
    p.telegram_chat_id = "123"
    p.receive_bot_alerts = True
    p.email_notifications = False
    p.save()
    tp, _ = TraderProfile.objects.get_or_create(user=u)
    tp.notify_channel = "telegram"
    tp.save()
    return u


def _cfg(user, asset_class, name, *, mode="paper", capital="10000", **kw):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=[], capital=Decimal(capital), base_currency="USD",
        enabled=True, **kw)


def _trade(cfg, pk, **kw):
    from bot_program.models import AssetBotTrade
    opened = kw.pop("opened_at", None)
    closed = kw.pop("closed_at", None)
    row = AssetBotTrade.objects.create(id=pk, config=cfg,
                                       asset_class=cfg.asset_class, **kw)
    if opened or closed:
        AssetBotTrade.objects.filter(pk=row.pk).update(
            opened_at=opened or row.opened_at, closed_at=closed)
        row.refresh_from_db()
    return row


def _eurcad(cfg, **kw):
    """Row #108 as the operator quoted it: 7,900 EURCAD at 1.60725571,
    its stop 5% under and its target 10% over, USD 0.73 a CAD."""
    fields = dict(symbol="EURCAD", side="BUY", qty=Decimal("7900.00000000"),
                  entry_price=Decimal("1.60725571"),
                  stop_loss=Decimal("1.52689292"),
                  take_profit=Decimal("1.76798128"), paper=True,
                  rule_name="golden_cross",
                  metadata={"value_per_unit": 0.73,
                            "initial_stop_loss": 1.52689292})
    fields.update(kw)
    return _trade(cfg, 108, **fields)


def _eurusd_attack(cfg):
    """A real eToro row in the attack mode whose stop eToro moved."""
    return _trade(cfg, 109, symbol="EURUSD", side="BUY",
                  qty=Decimal("1700"), entry_price=Decimal("1.17650"),
                  stop_loss=Decimal("1.15297"),
                  take_profit=Decimal("1.22356"), paper=False,
                  rule_name="ema_cross_4h",
                  metadata={"value_per_unit": 1.0,
                            "initial_stop_loss": 1.15297,
                            "broker": "etoro", "broker_env": "live",
                            "attack": {"tier": "HIGH",
                                       "risk_fraction": 0.02,
                                       "leverage": 20},
                            "stop_rewritten_by_venue": {"sent": 1.15297,
                                                        "held": 1.14}})


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _signal(inst, pk=None, **kw):
    from signals.models import Signal
    fields = dict(
        instrument=inst, signal_type="composite", direction="bullish",
        urgency="medium", title=f"starter_stock_momentum matched on "
                                f"{inst.symbol}",
        description="d", rule_name="starter_stock_momentum", score=0.8234,
        sub_scores={}, price_at_signal=Decimal("421.37"),
        suggested_entry=Decimal("421.37000000"),
        suggested_stop=Decimal("410"), suggested_target=Decimal("440"),
        risk_reward_ratio=1.8456)
    fields.update(kw)
    if pk is not None:
        fields["id"] = pk
    return Signal.objects.create(**fields)


def _bot(cfg, asset_class):
    from bot_program.asset_engine.base import AssetBot

    class _Bot(AssetBot):
        pass
    _Bot.asset_class = asset_class
    return _Bot(cfg)


#: A word joined by an underscore: a key, not English.
SNAKE = re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]")
EIGHT = re.compile(r"\d\.\d{8}")
CODE = re.compile(r"<code>.*?</code>", re.S)


def jargon(text):
    """What a person should never read in a sent text; a rule's key set
    as code in the folded record is the one key allowed."""
    plain = CODE.sub("", text)
    found = [m.group(0) for m in SNAKE.finditer(plain)]
    found += re.findall(r"\bNone\b|Decimal\(|\bnan\b|\binf\b", plain)
    found += [m.group(0) for m in EIGHT.finditer(plain)]
    return found


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.user = _user()

    def _send(self, call, domain="", posts=1):
        with patch.dict(os.environ, {"DOMAIN": domain}), \
                patch("requests.post", return_value=_ok()) as post:
            call()
        self.assertEqual(post.call_count, posts)
        return _payloads(post)[-1] if posts else None


# ── T2: the fills, exactly as the phone shows them ───────────────────────

class TheFillMessagesTests(_Base):
    def test_a_paper_bot_open_reads_as_a_sentence_and_its_facts(self):
        from bot_program.notifications import notify_bot_fill_open
        row = _eurcad(_cfg(self.user, "forex", "FX trend"))
        p = self._send(lambda: notify_bot_fill_open(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=row.qty, entry_price=row.entry_price,
            rule_name=row.rule_name, trade=row, trade_id=row.id,
            attack="", stop_moved=""))
        self.assertEqual(p["parse_mode"], "HTML")
        self.assertTrue(p["disable_web_page_preview"])
        self.assertEqual(p["chat_id"], "123")
        self.assertEqual(p["text"], "\n".join([
            f"<b>{GREEN} Bought EURCAD</b>",
            "<i>Simulated</i>",
            "7,900 units at 1.60726 — about 9,269 USD.",
            "",
            "Stop: 1.52689 (5.0% below)",
            "Target: 1.76798 (10.0% above)",
            "Risk if the stop is hit: 463.45 USD",
            "Why: Golden cross",
            "<blockquote expandable>Trade: #108",
            "Rule key: <code>golden_cross</code>",
            "Config: FX trend</blockquote>"]))
        # no DOMAIN, no button
        self.assertNotIn("reply_markup", p)

    def test_a_real_money_etoro_open_with_the_attack_mode_and_a_moved_stop(
            self):
        """The engine's own words (_fill_words), each its own argument:
        1,700 EURUSD at 1.17650 against the 1.15297 stop sent is 40.00 USD
        at risk, 2.0% of the 2,000 pool; 2,000.05 / 20 is 100.00 of margin;
        eToro holds the stop at 1.14000, 3.1% under the fill. The row is
        protected, so no bot-side check enforces the stop sent: the Stop
        and risk lines read the stop eToro holds, 1,700 x 0.0365 = 62.05
        USD (2026-09-27, the fixer), and the attack line says its figure
        is the one at the stop sent."""
        from bot_program.notifications import notify_bot_fill_open
        cfg = _cfg(self.user, "forex", "FX attack", mode="live",
                   capital="2000", extras={"leverage": "auto"})
        row = _eurusd_attack(cfg)
        words = _bot(cfg, "forex")._fill_words(row)
        self.assertEqual(words, {
            "attack": ("Attack mode: high conviction · 2.0% of the pool at "
                       "risk at the stop sent · 20x · 100.00 USD of margin"),
            "stop_moved": ("Stop moved by eToro: it holds 1.14000, not the "
                           "1.15297 sent (3.1% below the entry)"),
            # the fill against the quote it was sized on (2026-10-05):
            # nothing recorded on this row
            "slippage": ""})
        p = self._send(lambda: notify_bot_fill_open(
            self.user, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=row.qty, entry_price=row.entry_price,
            rule_name=row.rule_name, trade=row, trade_id=row.id, **words),
            domain=HOST)
        self.assertEqual(p["text"], "\n".join([
            f"<b>{GREEN} Bought EURUSD</b>",
            "<i>Real money · eToro</i>",
            "1,700 units at 1.17650 — about 2,000 USD.",
            "",
            "Stop: 1.14000 at eToro (3.1% below)",
            "Target: 1.22356 (4.0% above)",
            "Risk if the stop is hit: 62.05 USD, not the 40.00 USD planned",
            "Why: EMA cross 4h",
            "Attack mode: high conviction · 2.0% of the pool at risk at the "
            "stop sent · 20x · 100.00 USD of margin",
            "Stop moved by eToro: it holds 1.14000, not the 1.15297 sent "
            "(3.1% below the entry)",
            "<blockquote expandable>Trade: #109",
            "Rule key: <code>ema_cross_4h</code>",
            "Config: FX attack</blockquote>"]))
        self.assertEqual(p["reply_markup"], _button("/forensics/109/"))

    def test_a_short_open_says_sold_short_in_red(self):
        from bot_program.notifications import notify_bot_fill_open
        cfg = _cfg(self.user, "stock", "Stocks main")
        row = _trade(cfg, 113, symbol="AAPL", side="SELL", qty=Decimal("10"),
                     entry_price=Decimal("227.53"),
                     stop_loss=Decimal("234.36"),
                     take_profit=Decimal("213.88"), paper=True,
                     rule_name="rsi_reversal",
                     metadata={"value_per_unit": 1.0})
        p = self._send(lambda: notify_bot_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="SELL",
            qty=row.qty, entry_price=row.entry_price,
            rule_name=row.rule_name, trade=row, trade_id=row.id))
        lines = p["text"].split("\n")
        self.assertEqual(lines[0], f"<b>{RED} Sold short AAPL</b>")
        self.assertEqual(lines[2],
                         "10 shares at 227.53 — about 2,275 USD.")
        self.assertIn("Stop: 234.36 (3.0% above)", lines)
        self.assertIn("Target: 213.88 (6.0% below)", lines)
        self.assertIn("Why: RSI reversal", lines)

    def test_a_close_in_profit(self):
        from bot_program.notifications import notify_bot_fill_close
        row = _eurcad(_cfg(self.user, "forex", "FX trend"), status="CLOSED",
                      exit_price=Decimal("1.61035"), pnl=Decimal("17.8400"),
                      realized_r=0.04, outcome="manual_close",
                      reason="golden cross | closed:MANUAL",
                      opened_at=datetime(2026, 9, 24, 9, 12, tzinfo=UTC),
                      closed_at=datetime(2026, 9, 27, 13, 12, tzinfo=UTC))
        p = self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=row.qty, exit_price=row.exit_price, pnl=row.pnl,
            outcome=row.outcome, trade_id=row.id, trade=row), domain=HOST)
        self.assertEqual(p["text"], "\n".join([
            f"<b>{GAIN} Closed EURCAD · +17.84 USD</b>",
            "Sold 7,900 units at 1.61035 after 3 days 4 hours.",
            "",
            "Result: +17.84 USD · 0.04 times the risk",
            "How it ended: closed by hand",
            "Simulated",
            "<blockquote expandable>Trade: #108",
            "Rule key: <code>golden_cross</code>",
            "Config: FX trend",
            "Entry price: 1.60726",
            "Opened: 2026-09-24 09:12 UTC",
            "Closed: 2026-09-27 13:12 UTC</blockquote>"]))
        self.assertEqual(p["reply_markup"], _button("/forensics/108/"))

    def test_a_close_at_a_loss_by_its_stop(self):
        from bot_program.notifications import notify_bot_fill_close
        cfg = _cfg(self.user, "stock", "Stocks main", mode="live")
        row = _trade(cfg, 111, symbol="AAPL", side="SELL", qty=Decimal("10"),
                     entry_price=Decimal("227.53"),
                     stop_loss=Decimal("234.36"),
                     take_profit=Decimal("213.88"),
                     exit_price=Decimal("234.36"), pnl=Decimal("-68.30"),
                     realized_r=-1.0, outcome="stopped_out",
                     status="CLOSED", paper=False, rule_name="rsi_reversal",
                     reason="rsi | closed:SL",
                     metadata={"broker": "etoro", "broker_env": "live",
                               "value_per_unit": 1.0,
                               "initial_stop_loss": 234.36},
                     opened_at=datetime(2026, 9, 25, 13, 40, tzinfo=UTC),
                     closed_at=datetime(2026, 9, 25, 19, 10, tzinfo=UTC))
        p = self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="stock", symbol="AAPL", side="SELL",
            qty=row.qty, exit_price=row.exit_price, pnl=row.pnl,
            outcome=row.outcome, trade_id=row.id, trade=row))
        self.assertEqual(p["text"], "\n".join([
            f"<b>{LOSS} Closed AAPL · {MINUS}68.30 USD</b>",
            "Bought back 10 shares at 234.36 after 5 hours 30 minutes.",
            "",
            f"Result: {MINUS}68.30 USD · a loss of 1.00 times the risk",
            "How it ended: stop loss hit",
            "Real money · eToro",
            "<blockquote expandable>Trade: #111",
            "Rule key: <code>rsi_reversal</code>",
            "Config: Stocks main",
            "Entry price: 227.53",
            "Opened: 2026-09-25 13:40 UTC",
            "Closed: 2026-09-25 19:10 UTC</blockquote>"]))

    def test_a_close_the_platform_only_recorded_says_so(self):
        """GBPCHF #130, 2026-10-03: eToro closed it on Friday 12:37, the
        platform found the row a day later, booked it at the last mark and
        stamped the booking. The message read a mark as a fill and a
        Saturday as the close. An estimate is said to be one, and the
        stamp says what it is."""
        from bot_program.notifications import notify_bot_fill_close
        cfg = _cfg(self.user, "forex", "fx_majors_live", mode="live")
        row = _trade(cfg, 130, symbol="GBPCHF", side="BUY",
                     qty=Decimal("3600"), entry_price=Decimal("1.09716"),
                     stop_loss=Decimal("1.09000"),
                     take_profit=Decimal("1.11000"),
                     exit_price=Decimal("1.09728"), pnl=Decimal("0.52"),
                     realized_r=0.02, outcome="manual_close",
                     status="CLOSED", paper=False,
                     rule_name="starter_forex_breakout",
                     reason="breakout | reconciled-orphan",
                     metadata={"broker": "etoro", "broker_env": "live",
                               "value_per_unit": 1.0,
                               "exit_price_inferred": True,
                               "exit_fill_source": "mark"},
                     opened_at=datetime(2026, 10, 1, 18, 26, tzinfo=UTC),
                     closed_at=datetime(2026, 10, 3, 13, 0, tzinfo=UTC))
        p = self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="forex", symbol="GBPCHF", side="BUY",
            qty=row.qty, exit_price=row.exit_price, pnl=row.pnl,
            outcome=row.outcome, trade_id=row.id, trade=row))
        self.assertEqual(p["text"], "\n".join([
            f"<b>{GAIN} Closed GBPCHF · about +0.52 USD</b>",
            "Sold 3,600 units at about 1.09728.",
            "",
            "Result: about +0.52 USD · about 0.02 times the risk",
            "Priced from the last mark, not from a broker fill.",
            "How it ended: closed at the broker",
            "Real money · eToro",
            "<blockquote expandable>Trade: #130",
            "Rule key: <code>starter_forex_breakout</code>",
            "Config: fx_majors_live",
            "Entry price: 1.09716",
            "Opened: 2026-10-01 18:26 UTC",
            "Recorded closed: 2026-10-03 13:00 UTC — the broker had closed "
            "it before; the exact moment is not readable</blockquote>"]))

    def test_a_close_at_zero_and_one_nobody_could_price(self):
        from bot_program.notifications import notify_bot_fill_close
        row = _eurcad(_cfg(self.user, "forex", "FX trend"), status="CLOSED",
                      exit_price=Decimal("1.60725571"), pnl=Decimal("0"),
                      realized_r=0.0, outcome="time_stop")
        p = self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=row.qty, exit_price=row.exit_price, pnl=row.pnl,
            outcome=row.outcome, trade_id=row.id, trade=row))
        lines = p["text"].split("\n")
        self.assertEqual(lines[0], f"<b>{FLAT} Closed EURCAD · 0.00 USD</b>")
        self.assertIn("How it ended: time limit reached", lines)
        p = self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=Decimal("7900"), exit_price=None, pnl=None, outcome="",
            trade_id=None))
        lines = p["text"].split("\n")
        self.assertEqual(lines[0],
                         f"<b>{FLAT} Closed EURCAD · result unknown</b>")
        self.assertEqual(lines[1], "Sold 7,900 units. The exit price could "
                                   "not be read.")
        self.assertIn("Result: unknown, since the exit could not be priced",
                      lines)

    def test_a_hand_taken_open_from_a_signal(self):
        from bot_program.notifications import notify_manual_fill_open
        _signal(_instrument("AAPL"), pk=415, rule_name="golden_cross")
        cfg = _cfg(self.user, "stock", "Manual stocks", mode="live")
        row = _trade(cfg, 110, symbol="AAPL", side="BUY", qty=Decimal("3"),
                     entry_price=Decimal("227.53"),
                     stop_loss=Decimal("220.70"),
                     take_profit=Decimal("241.18"), paper=False,
                     rule_name="manual_take",
                     metadata={"manual": True, "signal_id": 415,
                               "broker": "etoro", "broker_env": "paper",
                               "value_per_unit": 1.0})
        p = self._send(lambda: notify_manual_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=row.qty, entry_price=row.entry_price, trade_id=row.id,
            live=True, trade=row), domain=HOST)
        self.assertEqual(p["text"], "\n".join([
            f"<b>{HAND} Bought AAPL by hand</b>",
            "<i>Simulated · eToro demo</i>",
            "3 shares at 227.53 — about 683 USD.",
            "",
            "Stop: 220.70 (3.0% below)",
            "Target: 241.18 (6.0% above)",
            "Risk if the stop is hit: 20.49 USD",
            "Taken: by hand, from signal #415 (Golden cross)",
            "<blockquote expandable>Trade: #110",
            "Config: Manual stocks</blockquote>"]))
        self.assertEqual(p["reply_markup"], _button("/forensics/110/"))
        self.assertNotIn("manual_take", p["text"])

    def test_a_queued_order_names_no_price(self):
        from bot_program.notifications import notify_manual_fill_open
        cfg = _cfg(self.user, "stock", "Manual stocks", mode="live")
        row = _trade(cfg, 114, symbol="AAPL", side="BUY", qty=Decimal("1"),
                     entry_price=Decimal("227.53"),
                     stop_loss=Decimal("220.70"), paper=False,
                     rule_name="manual_take",
                     metadata={"manual": True, "entry_working": True,
                               "broker": "etoro", "broker_env": "live"})
        p = self._send(lambda: notify_manual_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=row.qty, entry_price=None, trade_id=row.id, live=True,
            working=True, trade=row))
        self.assertEqual(p["text"], "\n".join([
            f"<b>{WAIT} Waiting to buy AAPL</b>",
            "<i>Real money · eToro</i>",
            "The broker has the order for 1 share; nothing has filled yet, "
            "so no position is open.",
            "",
            "Taken: by hand, from the instrument page",
            "Stop: 220.70",
            "Target: not set",
            "<blockquote expandable>Trade: #114",
            "Config: Manual stocks</blockquote>"]))

    def test_a_working_entry_that_filled_through_the_engine(self):
        """12 of 20 shares fill at 100.50 against the 95.00 stop sent:
        66.00 at risk; the engine hands its row (_finish_working_entry)."""
        cfg = _cfg(self.user, "stock", "Stocks main", mode="live")
        row = _trade(cfg, 112, symbol="MSFT", side="BUY", qty=Decimal("20"),
                     entry_price=Decimal("100"), stop_loss=Decimal("95"),
                     take_profit=Decimal("110"), paper=False,
                     rule_name="breakout_20d",
                     metadata={"entry_working": True, "qty_requested": 20.0,
                               "protective_order_ids": [],
                               "protected": False, "initial_stop_loss": 95.0,
                               "value_per_unit": 1.0, "broker": "ibkr",
                               "broker_env": "live"})
        p = self._send(lambda: _bot(cfg, "stock")._finish_working_entry(
            row, MagicMock(), qty=12.0, price=100.5, source="broker"))
        self.assertEqual(p["text"], "\n".join([
            f"<b>{GREEN} Bought MSFT</b>",
            "<i>Real money · IBKR</i>",
            "The waiting order filled: 12 shares at 100.50 — about "
            "1,206 USD.",
            "",
            "Filled: 12 of the 20 shares ordered",
            "Stop: 95.00 (5.5% below)",
            "Target: 110.00 (9.5% above)",
            "Risk if the stop is hit: 66.00 USD",
            "Why: Breakout 20d",
            "<blockquote expandable>Trade: #112",
            "Rule key: <code>breakout_20d</code>",
            "Config: Stocks main</blockquote>"]))

    def test_the_bell_row_is_still_created_with_its_items(self):
        from alerts.models import Notification
        from bot_program.notifications import notify_bot_fill_open
        row = _eurcad(_cfg(self.user, "forex", "FX trend"))
        self._send(lambda: notify_bot_fill_open(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=row.qty, entry_price=row.entry_price,
            rule_name=row.rule_name, trade=row, trade_id=row.id))
        n = Notification.objects.get(user=self.user)
        # the message's title and summary (2026-09-27, the polish)
        self.assertEqual(n.title, "◉ Bought EURCAD")
        self.assertEqual(n.notification_type, "bot")
        self.assertEqual(n.url, "/forensics/108/")
        self.assertEqual(n.body, "7,900 units at 1.60726 — about 9,269 USD.")
        # whose money it is first; the rule's key is not repeated where a
        # fact already names the rule, and never set raw
        self.assertEqual(n.data["items"], [
            "Simulated",
            "Stop: 1.52689 (5.0% below)", "Target: 1.76798 (10.0% above)",
            "Risk if the stop is hit: 463.45 USD", "Why: Golden cross",
            "Trade: #108", "Config: FX trend"])
        self.assertEqual(n.data["mark"], GREEN)

    def test_the_bell_items_of_a_close_and_a_hand_taken_open(self):
        from alerts.models import Notification
        from bot_program.notifications import (notify_bot_fill_close,
                                               notify_manual_fill_open)
        row = _eurcad(_cfg(self.user, "forex", "FX trend"), status="CLOSED",
                      exit_price=Decimal("1.61035"), pnl=Decimal("17.8400"),
                      realized_r=0.04, outcome="hit_target")
        self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=row.qty, exit_price=row.exit_price, pnl=row.pnl,
            outcome=row.outcome, trade_id=row.id, trade=row))
        items = Notification.objects.get(user=self.user).data["items"]
        self.assertIn("Rule: Golden cross", items)
        self.assertFalse([i for i in items if "golden_cross" in i], items)
        Notification.objects.all().delete()
        cfg = _cfg(self.user, "stock", "Manual stocks", mode="live")
        man = _trade(cfg, 130, symbol="AAPL", side="BUY", qty=Decimal("3"),
                     entry_price=Decimal("227.53"),
                     stop_loss=Decimal("220.70"), paper=False,
                     rule_name="manual_take",
                     metadata={"manual": True, "broker": "etoro",
                               "broker_env": "paper"})
        self._send(lambda: notify_manual_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=man.qty, entry_price=man.entry_price, trade_id=man.id,
            live=True, trade=man))
        items = Notification.objects.get(user=self.user).data["items"]
        self.assertEqual(items[0], "Simulated · eToro demo")

    def test_a_bot_open_without_a_rule_names_none(self):
        from bot_program.notifications import notify_bot_fill_open
        row = _eurcad(_cfg(self.user, "forex", "FX trend"), rule_name="")
        p = self._send(lambda: notify_bot_fill_open(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=row.qty, entry_price=row.entry_price,
            rule_name=row.rule_name, trade=row, trade_id=row.id))
        lines = p["text"].split("\n")
        self.assertFalse([ln for ln in lines if ln.startswith("Why")], lines)
        self.assertNotIn("Rule key", p["text"])
        self.assertEqual(lines[0], f"<b>{GREEN} Bought EURCAD</b>")

    def test_a_message_that_cannot_be_built_keeps_the_engines_facts(self):
        from alerts.models import Notification
        from bot_program import notifications as N
        with patch.object(N, "fill_open_message",
                          side_effect=RuntimeError("boom")), \
                self.assertLogs("bot_program.notifications", "ERROR"):
            p = self._send(lambda: N.notify_bot_fill_open(
                self.user, asset_class="forex", symbol="EURUSD", side="BUY",
                qty=Decimal("1700"), entry_price=Decimal("1.1765"),
                rule_name="ema_cross_4h", attack="Attack mode: high "
                "conviction", stop_moved="Stop moved by eToro: it holds "
                "1.14000, not the 1.15297 sent"))
        items = Notification.objects.get(user=self.user).data["items"]
        self.assertEqual(items[1:], [
            "Attack mode: high conviction",
            "Stop moved by eToro: it holds 1.14000, not the 1.15297 sent"])
        self.assertIn("Attack mode: high conviction", p["text"])
        self.assertIn("Stop moved by eToro", p["text"])

    def test_the_old_multi_line_rule_name_still_reads(self):
        """A caller that still hands the attack line inside rule_name: the
        first line is the key, the others are facts."""
        from bot_program.notifications import notify_bot_fill_open
        p = self._send(lambda: notify_bot_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10.00000000"), entry_price=Decimal("180.50000000"),
            rule_name="golden_cross\nAttack: HIGH · risk 7.0% of pool · 20x "
                      "· margin 100.00 USD"))
        self.assertEqual(p["text"], "\n".join([
            f"<b>{GREEN} Bought AAPL</b>",
            "10 shares at 180.50.",
            "",
            "Why: Golden cross",
            "Attack: HIGH · risk 7.0% of pool · 20x · margin 100.00 USD",
            "<blockquote expandable>Rule key: <code>golden_cross</code>"
            "</blockquote>"]))


# ── T1: the button, the fold, the limit ──────────────────────────────────

class TheButtonTests(_Base):
    def test_only_a_host_a_phone_can_open_gets_a_button(self):
        from alerts.channels.telegram_alert import button_markup
        for domain in ("", "localhost:8000", "sauron.example.com",
                       "https://x.io", "bad host"):
            with self.subTest(domain), \
                    patch.dict(os.environ, {"DOMAIN": domain}):
                self.assertIsNone(button_markup(("Open", "/positions/")))
        with patch.dict(os.environ, {"DOMAIN": HOST}):
            self.assertEqual(button_markup(("Open positions", "/positions/")),
                             _button("/positions/", "Open positions"))
            self.assertIsNone(button_markup(("Open", "https://evil.io/")))
            self.assertIsNone(button_markup(("", "/positions/")))
            self.assertIsNone(button_markup(None))

    def test_no_callback_button_anywhere(self):
        from alerts.channels import telegram_alert
        from alerts.dispatch import dispatch_signal_alert
        from bot_program import notifications
        for module in (telegram_alert, notifications):
            self.assertNotIn("callback_data", inspect.getsource(module))
        cfg = _cfg(self.user, "forex", "FX trend")
        row = _eurcad(cfg)
        with patch.dict(os.environ, {"DOMAIN": HOST}), \
                patch("requests.post", return_value=_ok()) as post:
            notifications.notify_bot_fill_open(
                self.user, asset_class="forex", symbol="EURCAD", side="BUY",
                qty=row.qty, entry_price=row.entry_price,
                rule_name=row.rule_name, trade=row, trade_id=row.id)
            notifications.notify_drawdown_warning(
                self.user, asset_class="forex", config_name="FX trend",
                realized_pnl=-200.0, limit=-100.0, currency="USD")
            dispatch_signal_alert(_signal(_instrument("MSFT")))
        sent = _payloads(post)
        self.assertEqual(len(sent), 3)
        for p in sent:
            markup = p["reply_markup"]
            self.assertNotIn("callback_data", json.dumps(markup))
            for row_ in markup["inline_keyboard"]:
                for b in row_:
                    self.assertEqual(set(b), {"text", "url"})
                    self.assertTrue(b["url"].startswith(f"https://{HOST}/"))

    def test_a_refused_button_costs_the_button_never_the_message(self):
        from bot_program.notifications import notify_bot_fill_open
        row = _eurcad(_cfg(self.user, "forex", "FX trend"))
        refused = MagicMock(ok=False, status_code=400,
                            text="Bad Request: BUTTON_URL_INVALID")
        with patch.dict(os.environ, {"DOMAIN": HOST}), \
                patch("requests.post", side_effect=[refused, _ok()]) as post, \
                self.assertLogs("bot_program.notifications", "WARNING") as cm:
            notify_bot_fill_open(
                self.user, asset_class="forex", symbol="EURCAD", side="BUY",
                qty=row.qty, entry_price=row.entry_price,
                rule_name=row.rule_name, trade=row, trade_id=row.id)
        first, second = _payloads(post)
        self.assertIn("reply_markup", first)
        self.assertNotIn("reply_markup", second)
        # the button's page stays, as a line: the facts, then the page
        page = f"Page: https://{HOST}/forensics/108/"
        self.assertNotIn(page, first["text"])
        self.assertEqual(second["text"], first["text"].replace(
            "Why: Golden cross\n", f"Why: Golden cross\n{page}\n"))
        self.assertIn("telegram refused the button (400)",
                      "\n".join(cm.output))
        # the per-chat sender does the same, on its own logger
        from alerts.channels.telegram_alert import send_to_chat
        with patch.dict(os.environ, {"DOMAIN": HOST}), \
                patch("requests.post", side_effect=[refused, _ok()]) as post, \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            self.assertTrue(send_to_chat("-1", "T", lines=["a"],
                                         button=("Open", "/positions/")))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(_payloads(post)[1]["text"],
                         f"<b>T</b>\na\nPage: https://{HOST}/positions/")
        # anything but a refusal OF THE BUTTON is answered as it came: no
        # second post, and the log does not blame the button
        for answer in (MagicMock(ok=False, status_code=429,
                                 text="Too Many Requests"),
                       MagicMock(ok=False, status_code=400,
                                 text="Bad Request: chat not found"),
                       MagicMock(ok=False, status_code=400,
                                 text="Bad Request: can't parse entities")):
            with self.subTest(answer.text), \
                    patch.dict(os.environ, {"DOMAIN": HOST}), \
                    patch("requests.post", return_value=answer) as post, \
                    self.assertLogs("alerts.channels.telegram_alert",
                                    "WARNING") as cm:
                self.assertFalse(send_to_chat("-1", "T", lines=["a"],
                                              button=("Open", "/positions/")))
            self.assertEqual(post.call_count, 1)
            self.assertNotIn("refused the button", "\n".join(cm.output))

    def test_a_signal_whose_button_is_refused_keeps_its_page(self):
        from alerts.dispatch import dispatch_signal_alert
        refused = MagicMock(ok=False, status_code=400,
                            text="Bad Request: BUTTON_URL_INVALID")
        with patch.dict(os.environ, {"DOMAIN": HOST}), \
                patch("requests.post", side_effect=[refused, _ok()]) as post, \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            dispatch_signal_alert(_signal(_instrument("MSFT")))
        first, second = _payloads(post)
        self.assertNotIn("Page:", first["text"])
        self.assertTrue(second["text"].endswith(
            f"Page: https://{HOST}/instruments/MSFT/"), second["text"])
        self.assertNotIn("reply_markup", second)

    def test_a_symbol_without_a_page_gets_the_signals_button(self):
        from alerts.dispatch import signal_extras
        sig = _signal(_instrument("BTC/USD", "crypto"))
        self.assertEqual(signal_extras(sig)["button"],
                         ("Open signals", "/signals/"))
        self.assertEqual(signal_extras(_signal(_instrument("MSFT")))["button"],
                         ("Open instrument", "/instruments/MSFT/"))


class TheFoldAndTheLimitTests(SimpleTestCase):
    def test_the_folded_record_is_escaped(self):
        from bot_program.notifications import _telegram_text
        text = _telegram_text("T & co", lines=["a < b"], summary="Said & done.",
                              subtitle="Real <money>",
                              details=["x < y & z", ("Rule key", "a<b>_c"),
                                       ("Empty", ""), ""])
        self.assertEqual(text, "\n".join([
            "<b>T &amp; co</b>",
            "<i>Real &lt;money&gt;</i>",
            "Said &amp; done.",
            "",
            "a &lt; b",
            "<blockquote expandable>x &lt; y &amp; z",
            "Rule key: <code>a&lt;b&gt;_c</code></blockquote>"]))

    def test_four_thousand_ninety_six_is_still_held(self):
        from alerts.channels.telegram_alert import (CONTINUED,
                                                    TELEGRAM_MAX_CHARS,
                                                    fit_text)

        def units(s):
            return len(s.encode("utf-16-le")) // 2

        lines = [f"Fact {i}: " + "x & y " * 20 for i in range(300)]
        text = fit_text("Bought EURCAD", lines=lines, mark=GREEN,
                        subtitle="Simulated", summary="7,900 units at 1.6.",
                        details=[f"Detail {i} <&>" * 10 for i in range(300)])
        self.assertLessEqual(units(text), TELEGRAM_MAX_CHARS)
        self.assertTrue(text.endswith(CONTINUED), text[-60:])
        self.assertNotIn("<blockquote", text)
        self.assertIn("<i>Simulated</i>\n7,900 units at 1.6.\n\nFact 0", text)
        # the record alone too long: it goes, whole, and every fact stays
        text = fit_text("T", lines=["a", "b"], summary="s",
                        details=["d &lt; " * 2000])
        self.assertEqual(text, "<b>T</b>\ns\n\na\nb")
        # a summary cannot push a message past the limit
        text = fit_text("T", lines=["a"], summary="& " * 5000)
        self.assertLessEqual(units(text), TELEGRAM_MAX_CHARS)

    def test_a_caller_with_none_of_the_new_fields_renders_as_before(self):
        from alerts.channels.telegram_alert import fit_text
        from bot_program.notifications import _telegram_text
        from bot_program.telegram_eye import Reply
        self.assertEqual(_telegram_text("t <b>", "a & b"),
                         "<b>t &lt;b&gt;</b>\n\na &amp; b")
        self.assertEqual(_telegram_text("T", "ignored", lines=["a", "", "b"],
                                        mark="M"), "<b>M T</b>\na\nb")
        self.assertEqual(fit_text("T", lines=["a"]), "<b>T</b>\na")
        self.assertEqual(Reply("M", "Title", ["one", "two"]).text(),
                         "<b>M Title</b>\none\ntwo")


# ── T3: the signal and the trade-adjacent alerts ─────────────────────────

class TheOtherMessagesTests(_Base):
    def test_the_signal_reads_its_rule_in_words_with_a_button(self):
        from alerts.dispatch import dispatch_signal_alert
        sig = _signal(_instrument("MSFT"))
        p = self._send(lambda: dispatch_signal_alert(sig), domain=HOST)
        self.assertEqual(p["text"], "\n".join([
            f"<b>{SIGNAL_UP} Signal · MSFT · BUY</b>",
            "Sauron flags MSFT as a buy at 421.37.",
            "",
            "Score: 0.82",
            "Rule: Starter stock momentum",
            "Entry 421.37 · stop 410.00 · target 440.00",
            "Reward to risk: 1.85",
            "Urgency: medium"]))
        self.assertEqual(p["reply_markup"],
                         _button("/instruments/MSFT/", "Open instrument"))
        # without a host a phone can open, the Page line stands in
        p = self._send(lambda: dispatch_signal_alert(_signal(
            _instrument("MSFT"))))
        self.assertTrue(p["text"].endswith(
            "Page: /instruments/MSFT/ on the platform"), p["text"])
        self.assertNotIn("reply_markup", p)

    def test_the_trade_alerts_keep_their_facts_and_gain_a_sentence(self):
        from bot_program import notifications as N
        cfg = _cfg(self.user, "stock", "Stocks main", mode="live")
        row = _trade(cfg, 115, symbol="AAPL", side="BUY",
                     qty=Decimal("2.00000000"), entry_price=Decimal("210"),
                     stop_loss=Decimal("200.5"), paper=False,
                     rule_name="golden_cross")
        cases = [
            (lambda: N.notify_drawdown_warning(
                self.user, asset_class="stock", config_name="Stocks main",
                realized_pnl=-200.0, limit=-100.0, currency="USD"),
             "Stocks main has lost 200.00 USD in the last 24 hours, past "
             "its limit of 100.00 USD, so it opens no new trades for now.",
             _button("/risk/", "Open risk page")),
            (lambda: N.notify_protection_vanished(
                self.user, asset_class="stock", symbol="AAPL", side="BUY",
                qty=row.qty, stop_loss=row.stop_loss,
                reason="the stop leg 77 no longer rests at the broker",
                trade_id=row.id),
             "The stop at the broker is gone while the AAPL position is "
             "still open.", _button("/forensics/115/")),
            (lambda: N.notify_unclaimed_position(
                self.user, symbols=["AAPL", "MSFT"], venue="IBKR"),
             "IBKR holds positions Sauron has no record of, so nothing on "
             "the platform guards them.",
             _button("/positions/", "Open positions")),
            (lambda: N.notify_manual_close_refused(
                self.user, asset_class="stock", symbol="AAPL",
                trade_id=row.id),
             "The broker could not be reached, so the close of AAPL was "
             "refused and the position is still open.",
             _button("/forensics/115/")),
        ]
        for call, summary, button in cases:
            with self.subTest(summary[:30]):
                p = self._send(call, domain=HOST)
                lines = p["text"].split("\n")
                self.assertEqual(lines[1], summary)
                self.assertEqual(lines[2], "")
                self.assertGreaterEqual(len(lines), 4)
                self.assertEqual(p["reply_markup"], button)
        from alerts.models import Notification
        dd = Notification.objects.filter(
            title__startswith="▲ Drawdown limit reached").get()
        self.assertEqual(dd.data["items"], [
            "Bot: Stocks main", "Asset class: STOCK",
            f"Realized 24h P&L: {MINUS}200.00 USD",
            f"Limit: {MINUS}100.00 USD", "New entries halted"])
        pv = Notification.objects.get(title__contains="UNPROTECTED")
        self.assertEqual(pv.data["items"][0], "Position: long 2 shares")


# ── T4: no jargon in any builder, the words in one place ─────────────────

class NoJargonTests(_Base):
    def test_every_builder_passes_the_no_jargon_walk(self):
        from alerts.dispatch import dispatch_signal_alert
        from bot_program import notifications as N
        _signal(_instrument("AAPL"), pk=416, rule_name="golden_cross")
        fx = _cfg(self.user, "forex", "FX trend")
        fx_live = _cfg(self.user, "forex", "FX attack", mode="live",
                       capital="2000", extras={"leverage": "auto"})
        st = _cfg(self.user, "stock", "Stocks main", mode="live")
        eurcad = _eurcad(fx)
        eurusd = _eurusd_attack(fx_live)
        man = _trade(st, 120, symbol="AAPL", side="BUY", qty=Decimal("3"),
                     entry_price=Decimal("227.53000000"),
                     stop_loss=Decimal("220.70000000"), paper=False,
                     rule_name="manual_take",
                     metadata={"manual": True, "signal_id": 416,
                               "broker": "etoro", "broker_env": "live"})
        closed = _trade(st, 121, symbol="NVDA", side="SELL",
                        qty=Decimal("4.00000000"),
                        entry_price=Decimal("120.12345678"),
                        exit_price=Decimal("118.00000000"),
                        pnl=Decimal("8.4938"), realized_r=0.52,
                        outcome="hit_target", status="CLOSED", paper=False,
                        rule_name="asset_bot_weighted_consensus",
                        reason="x | closed:TP",
                        metadata={"broker": "saxo", "broker_env": "paper"})
        words = _bot(fx_live, "forex")._fill_words(eurusd)
        calls = [
            lambda: N.notify_bot_fill_open(
                self.user, asset_class="forex", symbol="EURCAD", side="BUY",
                qty=eurcad.qty, entry_price=eurcad.entry_price,
                rule_name=eurcad.rule_name, trade=eurcad,
                trade_id=eurcad.id),
            lambda: N.notify_bot_fill_open(
                self.user, asset_class="forex", symbol="EURUSD", side="BUY",
                qty=eurusd.qty, entry_price=eurusd.entry_price,
                rule_name=eurusd.rule_name, trade=eurusd,
                trade_id=eurusd.id, **words),
            lambda: N.notify_bot_fill_open(
                self.user, asset_class="crypto", symbol="BTCUSD",
                side="SELL", qty=Decimal("0.00020000"),
                entry_price=Decimal("84145.80000000"),
                rule_name="rsi_reversal_4h"),
            lambda: N.notify_manual_fill_open(
                self.user, asset_class="stock", symbol="AAPL", side="BUY",
                qty=man.qty, entry_price=man.entry_price, trade_id=man.id,
                live=True, trade=man),
            lambda: N.notify_manual_fill_open(
                self.user, asset_class="stock", symbol="AAPL", side="SELL",
                qty=Decimal("1.00000000"), entry_price=None, live=True,
                working=True),
            lambda: N.notify_bot_fill_close(
                self.user, asset_class="stock", symbol="NVDA", side="SELL",
                qty=closed.qty, exit_price=closed.exit_price,
                pnl=closed.pnl, outcome=closed.outcome, trade_id=closed.id,
                trade=closed),
            lambda: N.notify_bot_fill_close(
                self.user, asset_class="stock", symbol="AAPL", side="BUY",
                qty=Decimal("10.00000000"),
                exit_price=Decimal("182.12345678"),
                pnl=Decimal("-2.5200"), outcome="stopped_out"),
            lambda: N.notify_bot_fill_close(
                self.user, asset_class="stock", symbol="AAPL", side="BUY",
                qty=Decimal("10.00000000"), exit_price=None, pnl=None,
                outcome=""),
            lambda: N.notify_drawdown_warning(
                self.user, asset_class="stock", config_name="Stocks main",
                realized_pnl=-200.123456789, limit=Decimal("-100.00000000"),
                currency="USD"),
            lambda: N.notify_protection_vanished(
                self.user, asset_class="stock", symbol="AAPL", side="BUY",
                qty=Decimal("2.00000000"), stop_loss=Decimal("200.50000000"),
                reason="the stop leg 77 no longer rests at the broker",
                trade_id=man.id),
            lambda: N.notify_unclaimed_position(
                self.user, symbols=["AAPL"], venue="IBKR"),
            lambda: N.notify_manual_close_refused(
                self.user, asset_class="stock", symbol="MSFT",
                trade_id=man.id),
            lambda: dispatch_signal_alert(_signal(_instrument("MSFT"))),
        ]
        with patch.dict(os.environ, {"DOMAIN": HOST}), \
                patch("requests.post", return_value=_ok()) as post:
            for call in calls:
                call()
        texts = [p["text"] for p in _payloads(post)]
        self.assertEqual(len(texts), len(calls))
        for text in texts:
            with self.subTest(text.split("\n")[0]):
                self.assertEqual(jargon(text), [], text)
        # the walk itself sees what it is for
        for bad in ("Rule golden_cross", "qty 7900.00000000", "None",
                    "Decimal('1')"):
            self.assertTrue(jargon(bad), bad)
        self.assertEqual(jargon("Rule key: <code>golden_cross</code>"), [])


class TheWordsTests(SimpleTestCase):
    def test_money_price_quantity_percent_and_units(self):
        from bot_program.notifications import (money_words, pct_words,
                                               price_words, qty_words,
                                               units_words)
        self.assertEqual(money_words(1234.5, "USD"), "1,234.50 USD")
        self.assertEqual(money_words(17.38, "USD", signed=True),
                         "+17.38 USD")
        self.assertEqual(money_words(Decimal("-45.789"), "USD", signed=True),
                         f"{MINUS}45.79 USD")
        self.assertEqual(money_words(-0.004, "USD", signed=True), "0.00 USD")
        self.assertEqual(money_words(None, "USD"), "")
        self.assertEqual(money_words("x"), "")
        self.assertEqual(price_words(Decimal("1.60725571"), "forex",
                                     "EURCAD"), "1.60726")
        self.assertEqual(price_words(Decimal("148.3254"), "forex", "USDJPY"),
                         "148.325")
        self.assertEqual(price_words(Decimal("227.53000000"), "stock",
                                     "AAPL"), "227.53")
        self.assertEqual(price_words(None), "")
        self.assertEqual(qty_words(Decimal("7900.00000000")), "7,900")
        self.assertEqual(qty_words(Decimal("0.00020000")), "0.0002")
        self.assertEqual(qty_words(None), "")
        self.assertEqual(pct_words(5.0), "5.0%")
        self.assertEqual(pct_words(0.15), "0.15%")
        self.assertEqual(pct_words(12.345), "12.3%")
        self.assertEqual(units_words(Decimal("1.00000000"), "stock"),
                         "1 share")
        self.assertEqual(units_words(Decimal("7900"), "forex"), "7,900 units")
        self.assertEqual(units_words(2, "options"), "2 contracts")

    def test_two_prices_never_read_as_one(self):
        from bot_program.asset_engine.base import stop_moved_words
        from bot_program.notifications import price_pair_words
        self.assertEqual(price_pair_words(220.70, 220.704, "stock", "AAPL"),
                         ("220.700", "220.704"))
        self.assertEqual(price_pair_words(1.14, 1.15297, "forex", "EURUSD"),
                         ("1.14000", "1.15297"))
        self.assertEqual(price_pair_words(5, 5, "stock", "AAPL"),
                         ("5.00", "5.00"))
        self.assertEqual(stop_moved_words(
            {"stop_rewritten_by_venue": {"sent": 220.704, "held": 220.70}},
            227.53, "stock", "AAPL"),
            "Stop moved by eToro: it holds 220.700, not the 220.704 sent "
            "(3.0% below the entry)")


# ── the fixer (2026-09-27): the stop that can be hit, the refusals ───────

class TheHeldStopTests(_Base):
    """A stop the venue rewrote at the fill is the only one that can be
    hit: the row keeps the SENT stop (the risk denominator), is marked
    protected, and a protected row skips every bot-side stop check."""

    def _row(self, pk, held):
        cfg = _cfg(self.user, "stock", "Manual stocks", mode="live")
        return _trade(cfg, pk, symbol="AAPL", side="BUY", qty=Decimal("2"),
                      entry_price=Decimal("250"),
                      stop_loss=Decimal("237.50"),
                      take_profit=Decimal("275"), paper=False,
                      rule_name="manual_take",
                      metadata={"manual": True, "broker": "etoro",
                                "broker_env": "live", "value_per_unit": 1.0,
                                "protected": True,
                                "initial_stop_loss": 237.5,
                                "stop_rewritten_by_venue": {"sent": 237.5,
                                                            "held": held}})

    def _open(self, row):
        from bot_program.notifications import notify_manual_fill_open
        return self._send(lambda: notify_manual_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=row.qty, entry_price=row.entry_price, trade_id=row.id,
            live=True, trade=row))

    def test_a_wider_stop_is_the_stop_and_the_risk(self):
        """2 x (250 - 237.50) = 25.00 planned; 2 x (250 - 230) = 40.00 at
        the stop eToro holds. The hand lane hands no stop-moved line: the
        message reads the row's own."""
        lines = self._open(self._row(140, 230.0))["text"].split("\n")
        self.assertEqual(lines[4:9], [
            "Stop: 230.00 at eToro (8.0% below)",
            "Target: 275.00 (10.0% above)",
            "Risk if the stop is hit: 40.00 USD, not the 25.00 USD planned",
            "Taken: by hand, from the instrument page",
            "Stop moved by eToro: it holds 230.00, not the 237.50 sent "
            "(8.0% below the entry)"])

    def test_no_stop_at_the_venue_is_an_uncapped_risk(self):
        text = self._open(self._row(141, 0.0001))["text"]
        lines = text.split("\n")
        self.assertEqual(lines[4:9], [
            "Stop: none at eToro",
            "Target: 275.00 (10.0% above)",
            "Risk: not capped, since eToro holds no stop",
            "Taken: by hand, from the instrument page",
            "No stop at eToro: it holds none, not the 237.50 sent"])
        self.assertNotIn("Risk if the stop is hit", text)

    def test_the_hand_lane_records_a_stop_the_venue_rewrote(self):
        """TAKE TRADE live, through its own harness: the stop eToro echoes
        is compared with the one sent, as the engine does; recorded only."""
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import (ROUTER, _arm_live,
                                                _components_on,
                                                _fake_live_client,
                                                _filled_response, _quote)
        from tests.test_take_trade_live import _signal as _tt_signal
        inst = _quote("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        fake = _fake_live_client(_filled_response(venueStopLoss=58000.0))
        with patch(ROUTER, return_value=fake), \
                patch("requests.post", return_value=_ok()) as post:
            out = execute_take_trade(self.user, _tt_signal(inst), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        sent = float(fake.market_order.call_args.kwargs["stop_loss"])
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(trade.metadata["stop_rewritten_by_venue"],
                         {"sent": sent, "held": 58000.0})
        self.assertEqual(float(trade.stop_loss), sent)
        texts = [p["text"] for p in _payloads(post)
                 if "Bought BTCUSD by hand" in p["text"]]
        self.assertEqual(len(texts), 1, _payloads(post))
        self.assertIn("at eToro (", texts[0])
        self.assertIn("Stop moved by eToro: it holds 58000", texts[0])
        # the stop echoed as sent: nothing recorded (a second signal; the
        # first position closed so no cap of the lane is in the way)
        AssetBotTrade.objects.filter(pk=trade.pk).update(status="CLOSED")
        fake = _fake_live_client(_filled_response(venueStopLoss=sent))
        cache.clear()
        with patch(ROUTER, return_value=fake), \
                patch("requests.post", return_value=_ok()):
            out = execute_take_trade(self.user, _tt_signal(inst), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertNotIn("stop_rewritten_by_venue", AssetBotTrade.objects.get(
            pk=out["trade_id"]).metadata)


class TheFixerTests(_Base):
    def test_a_close_that_reads_zero_is_never_a_loss_of_zero(self):
        from bot_program.notifications import notify_bot_fill_close
        row = _trade(_cfg(self.user, "forex", "FX trend"), 150,
                     symbol="USDJPY", side="BUY", qty=Decimal("1000"),
                     entry_price=Decimal("148.325"),
                     exit_price=Decimal("148.325"), pnl=Decimal("-0.0040"),
                     realized_r=-0.001, outcome="manual_close",
                     status="CLOSED", paper=True, rule_name="golden_cross",
                     reason="x | EMERGENCY FLATTEN")
        p = self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="forex", symbol="USDJPY", side="BUY",
            qty=row.qty, exit_price=row.exit_price, pnl=row.pnl,
            outcome=row.outcome, trade_id=row.id, trade=row))
        lines = p["text"].split("\n")
        self.assertEqual(lines[0], f"<b>{FLAT} Closed USDJPY · 0.00 USD</b>")
        self.assertIn("Result: 0.00 USD · 0.00 times the risk", lines)
        self.assertIn("How it ended: closed by the kill switch", lines)

    def test_the_drawdown_says_at_least_when_closes_went_unpriced(self):
        from alerts.models import Notification
        from bot_program.notifications import notify_drawdown_warning
        p = self._send(lambda: notify_drawdown_warning(
            self.user, asset_class="stock", config_name="Stocks main",
            realized_pnl=-200.0, limit=-100.0, currency="USD", unpriced=2))
        self.assertEqual(p["text"].split("\n")[1],
                         "Stocks main has lost at least 200.00 USD in the "
                         "last 24 hours (2 closes could not be priced), past "
                         "its limit of 100.00 USD, so it opens no new trades "
                         "for now.")
        n = Notification.objects.get(user=self.user)
        self.assertIn("Closes that could not be priced: 2", n.data["items"])

    def test_without_a_row_a_live_caller_claims_no_venue(self):
        from bot_program.notifications import (fill_open_message,
                                               fill_queued_message)
        live = fill_open_message(asset_class="stock", symbol="AAPL",
                                 side="BUY", qty=1, entry_price=100,
                                 manual=True, live=True)
        self.assertEqual(live["subtitle"], "")
        paper = fill_open_message(asset_class="stock", symbol="AAPL",
                                  side="BUY", qty=1, entry_price=100,
                                  manual=True, live=False)
        self.assertEqual(paper["subtitle"], "Simulated")
        self.assertEqual(fill_queued_message(asset_class="stock",
                                             symbol="AAPL", side="BUY", qty=1,
                                             live=True)["subtitle"], "")

    def test_a_refused_close_without_a_page_opens_the_positions(self):
        from bot_program.notifications import notify_manual_close_refused
        p = self._send(lambda: notify_manual_close_refused(
            self.user, asset_class="stock", symbol="MSFT", trade_id=None),
            domain=HOST)
        self.assertEqual(p["reply_markup"],
                         _button("/positions/", "Open positions"))

    def test_every_fill_call_site_hands_its_row(self):
        from bot_program import manual_trade, pending_closes, reconcile_asset
        from bot_program.asset_engine.base import AssetBot

        def calls(fn, name):
            src, out, at = inspect.getsource(fn), [], 0
            while True:
                i = src.find(name + "(", at)
                if i < 0:
                    return out
                j, depth = i + len(name) + 1, 1
                while depth:
                    depth += {"(": 1, ")": -1}.get(src[j], 0)
                    j += 1
                out.append(src[i:j])
                at = j

        for fn, name, n in (
                (AssetBot._finish_working_entry, "notify_bot_fill_open", 1),
                (AssetBot._finish_working_entry, "notify_manual_fill_open", 1),
                (AssetBot.execute_entry, "notify_bot_fill_open", 1),
                (AssetBot._close_trade, "notify_bot_fill_close", 1),
                (manual_trade._execute, "notify_manual_fill_open", 1),
                (reconcile_asset._close_as_orphan, "notify_bot_fill_close", 1),
                (pending_closes._finalise_closed, "notify_bot_fill_close", 1)):
            with self.subTest(f"{fn.__name__} {name}"):
                found = calls(fn, name)
                self.assertEqual(len(found), n, found)
                for call in found:
                    self.assertIn("trade=trade", call)
