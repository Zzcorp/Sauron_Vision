"""Every close reaches the dashboards, and a new signal's card answers.

The pages hear about a close from push_eye_event and nothing else —
and four close paths finished trades without calling it. The user's
exact story: a live close fails once, the retry succeeds silently, and
the position sits on every open page until a manual refresh. And a
freshly-arrived rail card kept `sr-slide-in` forever, whose FILLING
transform animation made the wrap the fixed popup's containing block —
hover looked dead on every new signal until a full page render.

Run with:  python manage.py test tests.test_close_liveness
"""
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


def _trade(user, status="CLOSE_PENDING", **kw):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="crypto", name="cl_live",
        defaults=dict(enabled=True, mode="paper", symbols=[],
                      capital=Decimal("1000")))
    defaults = dict(config=cfg, asset_class="crypto", symbol="BTCUSD",
                    side="BUY", qty=Decimal("1"),
                    entry_price=Decimal("100"), status=status)
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


class RetriedCloseIsHeardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("cl_u",
                                                         password="x")

    def test_the_finaliser_pushes_fill_close(self):
        """A close that failed once and succeeded on retry used to
        vanish invisibly — grade, audit and tax lots all ran, and the
        one channel the pages listen to stayed silent."""
        from bot_program.pending_closes import _finalise_closed
        trade = _trade(self.user)
        with patch("dashboard.consumers.push_eye_event") as push:
            _finalise_closed(trade, fill={"price": Decimal("110"), "metadata": {}},
                             reason="test")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        # The close notification raises its own bell push; the call
        # under test is the fill_close one.
        kinds = [c.args[1] for c in push.call_args_list]
        self.assertIn("fill_close", kinds)
        call = push.call_args_list[kinds.index("fill_close")]
        self.assertEqual(call.args[0], self.user)
        self.assertEqual(call.args[2]["trade_id"], trade.id)

    def test_the_finaliser_rings_the_bell_too(self):
        """First-attempt closes notify; retried ones never did — same
        hole, second channel."""
        from bot_program.pending_closes import _finalise_closed
        trade = _trade(self.user)
        with patch("bot_program.notifications.notify_bot_fill_close") \
                as notify:
            _finalise_closed(trade, fill={"price": Decimal("110"), "metadata": {}},
                             reason="test")
        notify.assert_called_once()
        self.assertEqual(notify.call_args[0][0], self.user)
        self.assertEqual(notify.call_args[1]["trade_id"], trade.id)

    def test_giving_up_is_also_news(self):
        """ERROR leaves every OPEN/CLOSE_PENDING read at once — the row
        must re-render out now, not at the next slow sweep."""
        from bot_program.pending_closes import _give_up
        trade = _trade(self.user)
        with patch("dashboard.consumers.push_eye_event") as push:
            _give_up(trade, "broker unreachable")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "ERROR")
        # The abandoned-alert Notification row raises its own bell push;
        # the call under test is the close_pending one.
        kinds = [c.args[1] for c in push.call_args_list]
        self.assertIn("close_pending", kinds)
        call = push.call_args_list[kinds.index("close_pending")]
        self.assertTrue(call.args[2]["abandoned"])

    def test_every_silent_close_path_now_pushes(self):
        """Source pins for the remaining holes: the kill switch, the
        orphan reconciler and the NL console's legacy close each carry
        the push — the dashboards hear a close from push_eye_event and
        NOTHING else, so a path without it is a silent close."""
        base = Path(settings.BASE_DIR) / "bot_program"
        ks = (base / "engine" / "kill_switch.py").read_text(
            encoding="utf-8")
        self.assertIn("def _push_close_event", ks)
        self.assertEqual(ks.count("_push_close_event("), 5)
        # The stranded-residual branch is the one close state the success
        # path can never announce — the except arm must push it.
        self.assertIn('_push_close_event(trade.config.user, trade,\n'
                      '                                      '
                      '"close_pending")', ks)
        rec = (base / "reconcile_asset.py").read_text(encoding="utf-8")
        self.assertIn('push_eye_event(trade.config.user, "fill_close"',
                      rec.split("def _close_as_orphan")[1]
                      .split("\ndef ")[0])
        nl = (base / "nl_trader.py").read_text(encoding="utf-8")
        self.assertIn('push_eye_event(user, "fill_close"', nl)


class NewSignalCardAnswersTests(TestCase):
    def test_the_entrance_animation_never_fills_forwards(self):
        """fill-mode `both` keeps a transform animation APPLYING forever,
        which acts as will-change:transform and makes the wrap the
        containing block for its position:fixed popup — the popup then
        positions against the 280px card and dies inside the rail's
        overflow:hidden. `backwards` keeps the only fill the entrance
        needs."""
        css = (Path(settings.BASE_DIR) / "static" / "css"
               / "sauron.css").read_text(encoding="utf-8")
        block = css.split(".sr-signal-wrap.sr-slide-in")[1].split("}")[0]
        self.assertIn("cubic-bezier(.2,.8,.25,1) backwards", block)
        self.assertNotIn(".25,1) both", block)

    def test_the_class_retires_at_the_curtain_call(self):
        """Belt to the fill-mode's braces: a hover DURING the half-second
        slide would still misposition once — the class leaves on
        animationend."""
        shell = (Path(settings.BASE_DIR) / "templates"
                 / "base.html").read_text(encoding="utf-8")
        seg = shell.split("w.classList.add('sr-slide-in')")[1][:400]
        self.assertIn("animationend", seg)
        self.assertIn("w.classList.remove('sr-slide-in')", seg)
        self.assertIn("{ once: true }", seg)
