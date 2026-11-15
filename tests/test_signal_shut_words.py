"""A signal announced while its market is shut says so (2026-11-12).

The operator, 2026-11-11: signals were announced while their market was
shut, with nothing to tell them from the ones he could act on ("please
fix it"). Told the announcements would wait for the open, he answered on
2026-11-12: "non, faites que l'on reçoive quand même les signaux live,
c'est plus intéressant". So nothing waits and nothing is hidden: every
signal is announced the moment it fires, as before, and when its
instrument's market is shut at that moment each channel says so in plain
words, with the hour the market opens when the clock knows it:

    market shut · opens Sun 22:00 UTC

No switch: it is a statement of fact (signals/market_hold.shut_label, on
the market clock the bots, the paper venue and the ticket already read).

Pinned here, at fixed instants:
  * a shut market: the banner's payload gains one key, the bell's body
    and the email and WhatsApp copies one clause, the Telegram message one
    line under its summary; nothing else moves, and all three steps still
    run at once;
  * an open market, crypto, and a market in its first quarter hour: every
    byte is main's (the literals below were printed by origin/main
    15dd487 for the same rows);
  * an unknown reopening says "market shut" alone;
  * a rule still at research keeps Telegram quiet, as before, and its
    banner and bell say the market is shut;
  * a label that cannot be read never costs an announcement;
  * the banner's own script draws the words (run under node).

Run with:  python manage.py test tests.test_signal_shut_words
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from tests.test_signal_market_hold import (MON_0900, MON_1000, SAT_NOON,
                                           SUN_2205, _at)
from tests.test_telegram_v2 import jargon

NODE = shutil.which("node")
TOKEN = "123456:shut-words-test-token"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100999",
       "DOMAIN": ""}
CHAT = "-4000000001"
SHUT_SUN = "market shut · opens Sun 22:00 UTC"
SHUT_MON = "market shut · opens Mon 14:30 UTC"

#: What origin/main 15dd487 announces for the rows _signal builds (printed
#: by a scratch run of main's own banner_payload, notify_new_signal and
#: dispatch_signal_alert): the bytes an open market must keep.
MAIN = {
    "EURUSD": {
        "banner": {"direction": "bearish", "entry": "1.08500", "rr": 2.0,
                   "rule_name": "mh_rule", "score": 0.55, "stop": "1.09000",
                   "symbol": "EURUSD", "target": "1.07500",
                   "title": "MACD cross on EURUSD", "url": "/signals/"},
        "bell": ("signal", "BEARISH EURUSD",
                 "MACD cross on EURUSD — Score: 0.55",
                 "/instruments/EURUSD/"),
        "telegram": [
            "<b>\U0001F4C9 Signal · EURUSD · SELL</b>",
            "Sauron flags EURUSD as a sell at 1.08500.",
            "",
            "Score: 0.55",
            "Rule: Mh rule",
            "Entry 1.08500 · stop 1.09000 · target 1.07500",
            "Reward to risk: 2.00",
            "Urgency: medium",
            "Page: /instruments/EURUSD/ on the platform"],
        "email": ("Signal: EURUSD BEARISH",
                  "Score: 0.55 | MACD cross on EURUSD"),
    },
    "AAPL": {
        "banner": {"direction": "bullish", "entry": "100", "rr": 2.0,
                   "rule_name": "mh_rule", "score": 0.55, "stop": "95",
                   "symbol": "AAPL", "target": "110",
                   "title": "MACD cross on AAPL", "url": "/signals/"},
        "bell": ("signal", "BULLISH AAPL", "MACD cross on AAPL — Score: 0.55",
                 "/instruments/AAPL/"),
        "telegram": [
            "<b>\U0001F4C8 Signal · AAPL · BUY</b>",
            "Sauron flags AAPL as a buy at 100.00.",
            "",
            "Score: 0.55",
            "Rule: Mh rule",
            "Entry 100.00 · stop 95.00 · target 110.00",
            "Reward to risk: 2.00",
            "Urgency: medium",
            "Page: /instruments/AAPL/ on the platform"],
        "email": ("Signal: AAPL BULLISH", "Score: 0.55 | MACD cross on AAPL"),
    },
    "BTCUSD": {
        "banner": {"direction": "bullish", "entry": "60000", "rr": 2.0,
                   "rule_name": "mh_rule", "score": 0.55, "stop": "58000",
                   "symbol": "BTCUSD", "target": "64000",
                   "title": "MACD cross on BTCUSD", "url": "/signals/"},
        "bell": ("signal", "BULLISH BTCUSD",
                 "MACD cross on BTCUSD — Score: 0.55",
                 "/instruments/BTCUSD/"),
        "telegram": [
            "<b>\U0001F4C8 Signal · BTCUSD · BUY</b>",
            "Sauron flags BTCUSD as a buy at 60000.00.",
            "",
            "Score: 0.55",
            "Rule: Mh rule",
            "Entry 60000.00 · stop 58000.00 · target 64000.00",
            "Reward to risk: 2.00",
            "Urgency: medium",
            "Page: /instruments/BTCUSD/ on the platform"],
        "email": ("Signal: BTCUSD BULLISH",
                  "Score: 0.55 | MACD cross on BTCUSD"),
    },
}
ROWS = {
    "EURUSD": ("forex", "", "bearish", "1.08500", "1.09000", "1.07500"),
    "AAPL": ("stock", "NASDAQ", "bullish", "100", "95", "110"),
    "BTCUSD": ("crypto", "", "bullish", "60000", "58000", "64000"),
}


def _ok():
    return MagicMock(ok=True, status_code=200, text='{"ok":true}')


def _reader(name="mh_reader", *, staff=True, chat=CHAT, email=True):
    from alerts.models import UserNotificationPrefs
    u = User.objects.create_user(name, password="x", email=f"{name}@x.io",
                                 is_staff=staff)
    p, _ = UserNotificationPrefs.objects.get_or_create(user=u)
    p.telegram_chat_id = chat
    p.receive_signals = True
    p.email_notifications = email
    p.save()
    return u


def _signal(symbol, rule="mh_rule", **kw):
    """One synthetic signal on `symbol`, the rows MAIN was printed for."""
    from instruments.models import Instrument
    from signals.models import Signal
    cls, exch, direction, entry, stop, target = ROWS[symbol]
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": cls,
                                 "exchange": exch, "is_active": True})
    fields = dict(instrument=inst, signal_type="technical",
                  direction=direction, urgency="medium",
                  title=f"MACD cross on {symbol}", description="d",
                  rule_name=rule, score=0.55, sub_scores={},
                  price_at_signal=Decimal(entry),
                  suggested_entry=Decimal(entry),
                  suggested_stop=Decimal(stop),
                  suggested_target=Decimal(target), risk_reward_ratio=2.0)
    fields.update(kw)
    return Signal.objects.create(**fields)


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        self.user = _reader()

    def _announce(self, sig, when, gate=True):
        """Announce `sig` at `when`: what each channel carried.
        {"out", "banner": [payload, ...], "bell": [(type, title, body,
        url), ...], "telegram": [lines, ...], "email": [(title, message),
        ...]}."""
        from alerts.models import Notification
        from signals.announce import announce_new_signal
        pushed = []

        def push(user, kind, payload):
            pushed.append((kind, dict(payload)))
            return True

        Notification.objects.all().delete()
        with _at(when, gate), \
                patch("dashboard.consumers.push_eye_event", side_effect=push), \
                patch("requests.post", return_value=_ok()) as post, \
                patch("alerts.channels.email_alert.send_email_to_user") as em:
            out = announce_new_signal(sig)
        return {
            "out": out,
            "banner": [p for kind, p in pushed if kind == "new_signal"],
            "bell": [(n.notification_type, n.title, n.body, n.url)
                     for n in Notification.objects.order_by("pk")],
            "telegram": [c.kwargs["json"]["text"].split("\n")
                         for c in post.call_args_list],
            "email": [tuple(c.args[1:]) for c in em.call_args_list],
        }

    def assertMainsBytes(self, got, symbol, sig):
        main = MAIN[symbol]
        self.assertEqual(got["banner"], [{**main["banner"],
                                          "signal_id": sig.pk}])
        self.assertEqual(got["bell"], [main["bell"]])
        self.assertEqual(got["telegram"], [main["telegram"]])
        self.assertEqual(got["email"], [main["email"]])


class AShutMarketSaysSoTests(_Base):
    def test_announced_at_once_on_every_channel_with_the_words(self):
        """Nothing waits and nothing is hidden: the three steps run at the
        signal's birth, and each says the market is shut."""
        sig = _signal("EURUSD")
        got = self._announce(sig, SAT_NOON)
        main = MAIN["EURUSD"]
        self.assertEqual(got["out"]["banner"], 1)
        self.assertEqual(got["out"]["bell"], "ok")
        self.assertEqual(got["out"]["channels"],
                         {"chats": 1, "sent": 1, "held": 0, "refused": 0})
        # the banner: main's payload and one more key
        self.assertEqual(got["banner"], [{**main["banner"],
                                          "signal_id": sig.pk,
                                          "market": SHUT_SUN}])
        # the bell: main's row, the body one clause longer
        kind, title, body, url = main["bell"]
        self.assertEqual(got["bell"], [(kind, title, f"{body} · {SHUT_SUN}",
                                        url)])
        # Telegram: main's message and one line, right under the summary
        want = list(main["telegram"])
        want.insert(3, "Market shut · opens Sun 22:00 UTC")
        self.assertEqual(got["telegram"], [want])
        # the email copy
        subject, message = main["email"]
        self.assertEqual(got["email"], [(subject, f"{message} | {SHUT_SUN}")])

    def test_a_us_share_before_the_bell(self):
        sig = _signal("AAPL")
        got = self._announce(sig, MON_0900)
        self.assertEqual(got["banner"][0]["market"], SHUT_MON)
        self.assertTrue(got["bell"][0][2].endswith(f" · {SHUT_MON}"))
        self.assertEqual(got["telegram"][0][3],
                         "Market shut · opens Mon 14:30 UTC")
        self.assertEqual(len(got["telegram"][0]),
                         len(MAIN["AAPL"]["telegram"]) + 1)

    def test_an_unknown_reopening_says_only_market_shut(self):
        clock = {"is_open": False, "session": "FOREX", "modelled": True,
                 "reopens": None, "reopens_words": "", "opened": None,
                 "closed": None}
        sig = _signal("EURUSD")
        with patch("signals.market_hold.market_clock", return_value=clock):
            got = self._announce(sig, SAT_NOON)
        self.assertEqual(got["banner"][0]["market"], "market shut")
        self.assertTrue(got["bell"][0][2].endswith("Score: 0.55 · market shut"))
        self.assertEqual(got["telegram"][0][3], "Market shut")

    def test_the_rule_based_email_and_whatsapp_copies_say_it_too(self):
        from alerts.models import AlertRule
        AlertRule.objects.create(user=self.user, name="every signal",
                                 min_score=0.0, notify_telegram=False,
                                 notify_email=True, notify_whatsapp=True,
                                 is_active=True)
        sig = _signal("EURUSD")
        with _at(SAT_NOON), \
                patch("alerts.channels.email_alert.send_email_to_user") as em, \
                patch("alerts.channels.whatsapp_alert.send_whatsapp_to_user"
                      ) as wa:
            from alerts.dispatch import dispatch_signal_alert
            dispatch_signal_alert(sig)
        main_message = ("Score: 0.55\nType: technical\nMACD cross on EURUSD\n"
                        "Urgency: medium")
        want = f"{main_message}\nMarket shut · opens Sun 22:00 UTC"
        self.assertEqual(em.call_args.args[1:],
                         ("Signal: EURUSD BEARISH", want))
        self.assertEqual(wa.call_args.args[1:],
                         ("Signal: EURUSD BEARISH", want))
        # and on an open market the rule's message is main's
        with _at(MON_1000), \
                patch("alerts.channels.email_alert.send_email_to_user") as em, \
                patch("alerts.channels.whatsapp_alert.send_whatsapp_to_user"
                      ) as wa:
            dispatch_signal_alert(sig)
        self.assertEqual(em.call_args.args[1:],
                         ("Signal: EURUSD BEARISH", main_message))
        self.assertEqual(wa.call_args.args[1:],
                         ("Signal: EURUSD BEARISH", main_message))

    def test_a_rule_still_at_research_keeps_telegram_quiet(self):
        """The rule of signals/announce stands: stored, graded, on the
        banner and the bell; no channel message while no bot trades it."""
        from signals.rule_birth import BORN_AT_RESEARCH
        sig = _signal("EURUSD", rule=sorted(BORN_AT_RESEARCH)[0])
        got = self._announce(sig, SAT_NOON)
        self.assertEqual(got["banner"][0]["market"], SHUT_SUN)
        self.assertTrue(got["bell"][0][2].endswith(f" · {SHUT_SUN}"))
        self.assertEqual(got["telegram"], [])
        self.assertEqual(got["email"], [])
        self.assertIn("quiet", got["out"]["channels"])

    def test_the_words_are_plain_english_in_the_house_style(self):
        sig = _signal("EURUSD")
        got = self._announce(sig, SAT_NOON)
        text = "\n".join(got["telegram"][0])
        self.assertEqual(jargon(text), [])
        self.assertEqual(jargon(got["bell"][0][2]), [])
        for said in (SHUT_SUN, got["telegram"][0][3]):
            self.assertRegex(said, r"^[Mm]arket shut · opens [A-Z][a-z]{2} "
                                   r"\d\d:\d\d UTC$")

    def test_every_user_gets_the_bell_row(self):
        _reader("mh_second", staff=False, chat="", email=False)
        got = self._announce(_signal("EURUSD"), SAT_NOON)
        self.assertEqual(len(got["bell"]), 2)
        self.assertEqual({row[2] for row in got["bell"]},
                         {f"MACD cross on EURUSD — Score: 0.55 · {SHUT_SUN}"})


class AnOpenMarketIsMainsBytesTests(_Base):
    def test_forex_on_a_monday(self):
        sig = _signal("EURUSD")
        self.assertMainsBytes(self._announce(sig, MON_1000), "EURUSD", sig)

    def test_a_us_share_in_session(self):
        from tests.test_signal_market_hold import _t
        sig = _signal("AAPL")
        self.assertMainsBytes(self._announce(sig, _t(2026, 11, 9, 15, 30)),
                              "AAPL", sig)

    def test_crypto_on_a_saturday(self):
        sig = _signal("BTCUSD")
        self.assertMainsBytes(self._announce(sig, SAT_NOON), "BTCUSD", sig)

    def test_the_first_quarter_hour_after_an_open(self):
        sig = _signal("EURUSD")
        self.assertMainsBytes(self._announce(sig, SUN_2205), "EURUSD", sig)

    def test_the_gate_off_is_mains_bytes_at_any_hour(self):
        """The suite's default (tests/__init__.py): no existing test reads
        the hour it runs at."""
        sig = _signal("EURUSD")
        self.assertMainsBytes(self._announce(sig, SAT_NOON, gate=False),
                              "EURUSD", sig)

    def test_a_label_that_cannot_be_read_never_costs_an_announcement(self):
        sig = _signal("EURUSD")
        with patch("signals.market_hold.market_state",
                   side_effect=RuntimeError("boom")), \
                self.assertLogs("signals.market_hold", "WARNING"):
            got = self._announce(sig, SAT_NOON)
        self.assertMainsBytes(got, "EURUSD", sig)
        self.assertEqual((got["out"]["banner"], got["out"]["bell"]),
                         (1, "ok"))


class NothingElseMovesTests(_Base):
    def test_the_signal_row_is_untouched_by_its_announcement(self):
        from signals.models import Signal
        sig = _signal("EURUSD")

        def row():
            s = Signal.objects.get(pk=sig.pk)
            return {f.attname: getattr(s, f.attname)
                    for f in s._meta.concrete_fields}

        before = row()
        self._announce(sig, SAT_NOON)
        self.assertEqual(row(), before)

    def test_the_ticket_button_stays_on_the_telegram_message(self):
        """A shut market changes no button: "Prepare ticket" opens the
        ticket, which says the market is shut itself (a paper ticket is
        refused, a live one warns)."""
        from alerts.dispatch import signal_extras
        sig = _signal("EURUSD")
        with _at(MON_1000):
            open_buttons = signal_extras(sig)
        with _at(SAT_NOON):
            shut_buttons = signal_extras(sig)
        self.assertEqual(shut_buttons, open_buttons)


# ── the banner's own script, as shipped, under node ──────────────────────

RUN_JS = r"""
'use strict';
const fs = require('fs');
const IN = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const describe = new Function(IN.source + '\nreturn describe;')();
const out = IN.payloads.map(p => describe('new_signal', p));
process.stdout.write(JSON.stringify(out));
"""


def _banner_source():
    """esc, num, row and describe, cut from the banner script in
    templates/base.html (they are function declarations of one IIFE)."""
    text = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")
    start = text.index("    function esc(v) {",
                       text.index('id="svBannerStack"'))
    end = text.index("/* Replay/burst guards for notification banners", start)
    return text[start:end]


@unittest.skipUnless(NODE, "node is not installed on this machine")
class TheBannerScriptTests(SimpleTestCase):
    def _describe(self, payloads):
        tmp = Path(tempfile.mkdtemp(prefix="sv-shutwords-"))
        try:
            (tmp / "run.js").write_text(RUN_JS, encoding="utf-8")
            (tmp / "input.json").write_text(json.dumps(
                {"source": _banner_source(), "payloads": payloads}),
                encoding="utf-8")
            proc = subprocess.run(
                [NODE, str(tmp / "run.js"), str(tmp / "input.json")],
                capture_output=True, text=True, timeout=120, encoding="utf-8")
            if proc.returncode != 0:
                raise AssertionError("the banner script failed: %s"
                                     % proc.stderr[:3000])
            return json.loads(proc.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_banner_draws_the_market_words_on_its_one_line(self):
        base = {**MAIN["EURUSD"]["banner"], "signal_id": 7}
        open_card, shut_card, hostile = self._describe([
            base, {**base, "market": SHUT_SUN},
            {**base, "market": "<b>shut</b>"}])
        # an open market: the card main draws, field for field
        self.assertEqual(open_card, {
            "cls": "signal", "kind": "New signal", "sym": "EURUSD",
            "val": "0.55", "valCls": "",
            "line": "BEARISH · MACD cross on EURUSD",
            "more": ('<div class="tp-row"><span class="lbl">Rule</span>'
                     '<span>mh_rule</span></div>'
                     '<div class="tp-row"><span class="lbl">Entry</span>'
                     '<span>1.08500</span></div>'
                     '<div class="tp-row"><span class="lbl">Stop</span>'
                     '<span>1.09000</span></div>'
                     '<div class="tp-row"><span class="lbl">Target</span>'
                     '<span>1.07500</span></div>'
                     '<div class="tp-row"><span class="lbl">Reward : risk'
                     '</span><span>2 : 1</span></div>'),
            "href": "/signals/"})
        # a shut market: the same card, its line saying so
        self.assertEqual(shut_card, {
            **open_card,
            "line": f"BEARISH · MACD cross on EURUSD · {SHUT_SUN}"})
        # the line is escaped where it is drawn, like every other field
        self.assertEqual(hostile["line"],
                         "BEARISH · MACD cross on EURUSD · <b>shut</b>")
        text = (Path(settings.BASE_DIR) / "templates" / "base.html"
                ).read_text(encoding="utf-8")
        self.assertIn("esc(m.line)", text)

    def test_the_script_reads_the_key_the_engine_sends(self):
        from signals.announce import banner_payload
        self.assertIn("d.market", _banner_source())
        self.assertTrue(re.search(r'"market"', Path(
            banner_payload.__code__.co_filename).read_text(encoding="utf-8")))
