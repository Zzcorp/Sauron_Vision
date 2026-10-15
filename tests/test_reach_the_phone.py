"""Reach the phone, keep the record (2026-10-08, the wiring audit's PR1).

The audit found that what a human must act on did not reach the phone.
The five live positions were all hand trades (manual_take); the care never
cuts a hand trade on a rule (bot_program/position_care.py), so the
position reviewer was the only per-position reasoning acting on them, and
its "tighten XAUUSD" / "exit USDCNH" went to the in-app bell alone. This
PR changes what a human reads, never an order path. These tests pin, in
the order the PR builds them:

  1. the reviewer      an exit / tighten / take-part call on a REAL row
                       goes through dispatch_notification (the bell and
                       Telegram, quiet hours honoured) with the position,
                       the call, the stop or the part, the R now and the
                       reason; the 6 h cooldown holds; a hand trade says
                       the operator decides; a simulated row keeps the
                       bell alone; the free pass sends ONE notice when a
                       real row's thesis turns to exit
  2. the ladder        a move touching a live stage tells the staff and
                       writes an audit row; the sweep sends one summary
                       with its refusals; the morning digest reads the
                       night's moves
  3. the brakes        disable_config / enable_config write config_braked
                       / config_rearmed; the activity feed, the position
                       page and the 07:00 digest read them
  4. one posture word  the briefing stores the measured posture beside
                       its own word; its title shows both
  5. the weekly review the live book apart from paper, the scorecard per
                       lane, the skips, the guards, FRED and the stress;
                       never macro=""; no wizard plan graded

The review of 2026-10-08 added what the messages must NOT do: keep a call
off the phone because quiet hours held an earlier one, say one dead thesis
twice, call a bot row a hand trade, ring an `adjust`, name a stop that no
longer exists, tell the same refusals every night, promise "full size" or
"trades" a stage and a signal record do not deliver, name the sweep for
bar_losers, call nothing measured "calm", count demo closes as real money,
drop a standing Morgul finding, print a monthly release as a week's change,
count a lifted brake as a fault, or call an adopted stop a fresh brake.

No alarm-group text is written here, and no message carries a balance.

Run with:  python manage.py test tests.test_reach_the_phone
"""
import json
import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


# ── fixtures ──────────────────────────────────────────────────────────────

def _operator(name="phone_op", *, chat="-100main", staff=True):
    """A user whose channel is Telegram, with a chat to reach."""
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile
    user = User.objects.create(username=name, is_staff=staff)
    TraderProfile.objects.create(user=user, notify_channel="telegram")
    UserNotificationPrefs.objects.create(user=user, telegram_chat_id=chat)
    return user


def _real(trade, *, broker="etoro"):
    """Make a test row a REAL-money row at a broker (world "live")."""
    meta = dict(trade.metadata or {})
    meta["broker"] = broker
    trade.metadata = meta
    trade.paper = False
    trade.save(update_fields=["metadata", "paper"])
    return trade


def _review(trade, *, verdict="exit", **over):
    from brain.position_review_models import PositionReview
    fields = dict(
        book="bot", position_id=trade.id, symbol=trade.symbol,
        side=trade.side, user=trade.config.user, verdict=verdict,
        confidence=0.7, unrealized_r=-0.4,
        reasoning_md="The structure broke under the entry.",
        triggers=[{"code": "near_stop",
                   "text": "Only 0.20R from the stop."}],
        facts={"thesis": {"verdict": "exit",
                          "words": "Thesis DEAD: a displaced break."}},
        model_used="claude-stub")
    fields.update(over)
    return PositionReview.objects.create(**fields)


#: A money figure in a currency, as the platform prints one: "1,234.56 USD".
MONEY = re.compile(r"\d[\d,]*\.?\d*\s?(USD|EUR|GBP|CHF|JPY)\b|[$€£]\s?\d")


def _sent_text(call) -> str:
    """Everything one _send_telegram call would have put on the phone."""
    args, kwargs = call
    parts = [str(a) for a in args[1:]]
    for key in ("lines", "details"):
        parts.extend(str(x) for x in (kwargs.get(key) or []))
    for key in ("subtitle", "summary", "mark"):
        parts.append(str(kwargs.get(key) or ""))
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════
# 1. The reviewer's verdicts reach the phone
# ══════════════════════════════════════════════════════════════════════════

class TheReviewerReachesThePhoneTests(TestCase):

    def setUp(self):
        from tests.test_position_review import _quote, _trade
        self.user = _operator()
        self.trade = _real(_trade("XAUUSD", entry="100", initial_stop="99",
                                  stop="99", target="103", user=self.user,
                                  rule_name="manual_take"))
        _quote("XAUUSD", 99.6)

    def test_the_kind_is_an_operator_kind(self):
        """A decision handed to the operator about a position they hold:
        a muted bot feed must not mute it."""
        from bot_program.notifications import (BOT_KINDS, NOTIFY_MARKS,
                                               OPERATOR_KINDS)
        self.assertIn("position_review", OPERATOR_KINDS)
        self.assertNotIn("position_review", BOT_KINDS)
        self.assertIn("position_review", NOTIFY_MARKS)

    def test_an_exit_on_a_real_row_reaches_telegram(self):
        from alerts.models import Notification
        from brain.position_review_agent import _notify
        review = _review(self.trade, verdict="exit")
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            self.assertTrue(_notify(review))
        self.assertEqual(tg.call_count, 1)
        text = _sent_text(tg.call_args)
        self.assertIn("XAUUSD", text)
        self.assertIn("exit", text)
        self.assertIn("−0.40R", text)          # the R now, a true minus
        self.assertIn("Only 0.20R from the stop.", text)   # the reason
        self.assertIn("Thesis DEAD", text)
        self.assertIn("Real money", text)
        self.assertIn("confidence 70%", text)
        self.assertIn("Stop now: 99", text)    # the row's stop, in force
        self.assertIsNone(MONEY.search(text), text)
        # the bell row is the same row as before, kind and card payload
        n = Notification.objects.get(user=self.user)
        self.assertEqual(n.notification_type, "portfolio")
        self.assertEqual(n.data.get("kind"), "position_review")
        self.assertEqual(n.data.get("review_id"), review.id)
        self.assertIn("nothing has been closed", n.body)

    def test_a_hand_trade_says_the_operator_decides(self):
        from brain.position_review_agent import _notify
        review = _review(self.trade, verdict="exit")
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            _notify(review)
        text = _sent_text(tg.call_args)
        self.assertIn("hand trade", text)
        self.assertIn("you decide", text.lower())

    def test_a_tighten_carries_the_suggested_stop(self):
        from brain.position_review_agent import _notify
        review = _review(self.trade, verdict="tighten",
                         suggested_stop=Decimal("99.5"))
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            _notify(review)
        text = _sent_text(tg.call_args)
        self.assertIn("tighten the stop", text)
        self.assertIn("Suggested stop: 99.5", text)

    def test_a_take_part_carries_the_part(self):
        from brain.position_review_agent import _notify
        review = _review(self.trade, verdict="take_part", take_part_pct=40)
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            _notify(review)
        text = _sent_text(tg.call_args)
        self.assertIn("take part off", text)
        self.assertIn("40%", text)

    def test_the_cooldown_holds_on_the_phone_too(self):
        from brain.position_review_agent import _notify
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            self.assertTrue(_notify(_review(self.trade, verdict="exit")))
            self.assertFalse(_notify(_review(self.trade, verdict="exit")))
        self.assertEqual(tg.call_count, 1)

    def test_a_muted_bot_feed_does_not_mute_the_reviewer(self):
        """receive_bot_alerts off mutes the bots' own news, never a
        decision handed to the operator (OPERATOR_KINDS)."""
        from brain.position_review_agent import _notify
        prefs = self.user.notification_prefs
        prefs.receive_bot_alerts = False
        prefs.save()
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            self.assertTrue(_notify(_review(self.trade, verdict="exit")))
        self.assertEqual(tg.call_count, 1)

    def test_a_bot_row_is_never_called_a_hand_trade(self):
        """The care DOES cut a bot rule's row: "the platform never cuts it
        on a rule" is the hand trade's sentence alone."""
        from brain.position_review_agent import _notify
        from tests.test_position_review import _trade
        bot = _real(_trade("BOTQ", user=self.user, rule_name="golden_cross",
                           cfg_name="bot_cfg"))
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            self.assertTrue(_notify(_review(bot, verdict="exit")))
        text = _sent_text(tg.call_args)
        self.assertNotIn("hand trade", text)
        self.assertIn("opened by Golden cross", text)
        self.assertIn("you decide", text)

    def test_a_call_held_by_quiet_hours_reaches_the_phone_after_them(self):
        """The bell row a call leaves during quiet hours holds the bell
        (one row, not one every pass) but never the phone: the first call
        after quiet hours goes out, once; the next waits the 6 h."""
        from alerts.models import Notification
        from brain.position_review_agent import _notify
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            with patch("bot_program.notifications._in_quiet_hours",
                       return_value=True):
                self.assertTrue(_notify(_review(self.trade, verdict="exit")))
                # still quiet: the bell already has it
                self.assertFalse(_notify(_review(self.trade, verdict="exit")))
            self.assertEqual(tg.call_count, 0)
            held = Notification.objects.get(user=self.user)
            self.assertTrue(held.data.get("phone_held"))
            Notification.objects.filter(pk=held.pk).update(
                created_at=timezone.now() - timedelta(hours=1))
            with patch("bot_program.notifications._in_quiet_hours",
                       return_value=False):
                self.assertTrue(_notify(_review(self.trade, verdict="exit")))
                self.assertEqual(tg.call_count, 1)
                self.assertFalse(_notify(_review(self.trade, verdict="exit")))
        self.assertEqual(tg.call_count, 1)
        self.assertEqual(Notification.objects.filter(user=self.user).count(),
                         2)

    def test_the_stop_now_is_the_stop_in_force_not_the_fill_echo(self):
        """eToro rewrote the stop at the fill (sent 99, held 98.5); the care
        then locked it at 99.7 and mirrored it onto eToro (a stop_moves
        entry). The phone names 99.7 — the stop that exists — and the
        fill's echo only while nothing has moved."""
        from brain.position_review_agent import _notify
        meta = dict(self.trade.metadata or {}, protected=True,
                    stop_rewritten_by_venue={"sent": 99.0, "held": 98.5})
        meta_moved = dict(meta, stop_moves=[{"from": 99.0, "to": 99.7,
                                             "when": "2026-10-08T09:00"}])
        self.trade.metadata, self.trade.stop_loss = meta_moved, Decimal("99.7")
        self.trade.save(update_fields=["metadata", "stop_loss"])
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            _notify(_review(self.trade, verdict="tighten",
                            suggested_stop=Decimal("99.8")))
        text = _sent_text(tg.call_args)
        self.assertIn("Stop now: 99.7", text)
        self.assertIn("at eToro", text)
        self.assertNotIn("98.5", text)
        # nothing moved since the fill: the venue's echo is the stop
        from bot_program.notifications import _stop_now_line
        self.trade.metadata, self.trade.stop_loss = meta, Decimal("99")
        self.assertIn("98.5", _stop_now_line(self.trade, "stock", "XAUUSD"))
        # and a care-set stop on a row eToro had left with none
        self.trade.metadata = dict(
            meta, stop_rewritten_by_venue={"sent": 99.0, "held": 0.0},
            stop_moves=[{"from": 99.0, "to": 99.4}])
        self.trade.stop_loss = Decimal("99.4")
        line = _stop_now_line(self.trade, "stock", "XAUUSD")
        self.assertIn("99.4", line)
        self.assertNotIn("none", line)
        # a row the venue's levels cannot be read for (not protected, or
        # its venue stop unread): the echo still yields once a stop moved
        for extra in ({"protected": False}, {"venue_stop_unread": True}):
            self.trade.metadata = dict(meta_moved, **extra)
            self.trade.stop_loss = Decimal("99.7")
            line = _stop_now_line(self.trade, "stock", "XAUUSD")
            self.assertIn("Stop now: 99.7", line)
            self.assertNotIn("98.5", line)

    def test_quiet_hours_keep_the_bell_and_mute_the_phone(self):
        from datetime import time
        from alerts.models import Notification
        from brain.position_review_agent import _notify
        prefs = self.user.notification_prefs
        prefs.quiet_start, prefs.quiet_end = time(0, 0), time(23, 59)
        prefs.save()
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg, \
                patch("bot_program.notifications._in_quiet_hours",
                      return_value=True):
            self.assertTrue(_notify(_review(self.trade, verdict="exit")))
        tg.assert_not_called()
        self.assertEqual(Notification.objects.filter(
            user=self.user).count(), 1)

    def test_a_hold_says_nothing_anywhere(self):
        from alerts.models import Notification
        from brain.position_review_agent import _notify
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            self.assertFalse(_notify(_review(self.trade, verdict="hold")))
        tg.assert_not_called()
        self.assertFalse(Notification.objects.exists())

    def test_a_simulated_row_keeps_the_bell_alone(self):
        """A paper row is not money a human must act on: the bell row as
        before, never the phone."""
        from alerts.models import Notification
        from brain.position_review_agent import _notify
        from tests.test_position_review import _trade
        paper = _trade("PAPERX", user=self.user, cfg_name="paper_cfg")
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            self.assertTrue(_notify(_review(paper, verdict="exit")))
        tg.assert_not_called()
        self.assertEqual(Notification.objects.get(user=self.user)
                         .data.get("kind"), "position_review")

    def test_the_model_pass_reaches_the_phone_end_to_end(self):
        """review_open_positions_now → review_one → _notify → Telegram, the
        per-pass and per-day caps untouched. (Gold's platform quote is the
        future, which values no real row: a share is used here.)"""
        from brain.position_review_agent import review_open_positions_now
        from tests.test_position_review import EXIT, _quote, _stub_agent
        self.trade.status = "CLOSED"
        self.trade.save(update_fields=["status"])
        from tests.test_position_review import _trade
        _real(_trade("EDGEQ", entry="100", initial_stop="99", stop="99",
                     target="103", user=self.user, cfg_name="e2e_cfg"))
        _quote("EDGEQ", 99.2)
        with _stub_agent(EXIT), \
                patch("brain.position_review._thesis",
                      return_value={"verdict": "watch", "why": [],
                                    "words": ""}), \
                patch("bot_program.notifications._send_telegram",
                      return_value=True) as tg:
            result = review_open_positions_now()
        self.assertEqual(result["n_model_reviews"], 1)
        self.assertTrue(result["reviews"][0]["notified"])
        self.assertEqual(tg.call_count, 1)


class TheDeadThesisNoticeTests(TestCase):
    """The free pass: ONE notice when a real row's thesis turns to exit,
    de-duplicated per row and verdict."""

    DEAD = {"verdict": "exit", "alive": False,
            "why": ["structure broke against it: a displaced close "
                    "through 99.2 2 bar(s) ago, not reclaimed"],
            "words": "Thesis DEAD: structure broke against it.",
            "adjust": None, "as_of": None}

    def setUp(self):
        from tests.test_position_review import _quote, _trade
        self.user = _operator("thesis_op")
        self.trade = _real(_trade("USDCNH", entry="100", initial_stop="99",
                                  stop="99", target="103", user=self.user,
                                  rule_name="manual_take",
                                  cfg_name="thesis_cfg"))
        _quote("USDCNH", 100.4)

    def _pass(self, thesis=None):
        from brain.position_review import deterministic_pass
        with patch("brain.position_review._thesis",
                   return_value=dict(thesis or self.DEAD)), \
                patch("bot_program.notifications._send_telegram",
                      return_value=True) as tg:
            deterministic_pass()
        return tg

    def test_a_dead_thesis_on_a_real_row_reaches_the_phone_once(self):
        from alerts.models import Notification
        first = self._pass()
        self.assertEqual(first.call_count, 1)
        text = _sent_text(first.call_args)
        self.assertIn("USDCNH", text)
        self.assertIn("thesis", text.lower())
        self.assertIn("structure broke against it", text)
        self.assertIn("hand trade", text)
        self.assertIn("The thesis check reads this trade as dead", text)
        self.assertIsNone(MONEY.search(text), text)
        # the next passes say nothing: one notice per row and verdict
        self.assertEqual(self._pass().call_count, 0)
        self.assertEqual(self._pass().call_count, 0)
        self.assertEqual(Notification.objects.filter(
            user=self.user, data__kind="thesis_exit").count(), 1)

    def test_a_thesis_dead_on_the_odds_alone_claims_no_structure(self):
        """The recovery odds can read a thesis dead with no structural
        break: the summary says what the check found, never "the structure
        no longer supports this trade"."""
        odds = dict(self.DEAD, why=["only 20% of 15 analogs -1.50R deep "
                                    "came back to win"],
                    words="Thesis DEAD: the recovery odds are gone.")
        text = _sent_text(self._pass(odds).call_args)
        self.assertNotIn("structure", text.lower())
        self.assertIn("only 20% of 15 analogs", text)

    def test_an_adjust_is_not_a_dead_thesis(self):
        adjust = dict(self.DEAD, verdict="adjust", alive=True,
                      words="Thesis ALIVE — tighten to the structure.")
        self.assertEqual(self._pass(adjust).call_count, 0)

    def test_a_bot_row_s_dead_thesis_is_not_a_hand_trade(self):
        self.trade.rule_name = "golden_cross"
        self.trade.save(update_fields=["rule_name"])
        text = _sent_text(self._pass().call_args)
        self.assertNotIn("hand trade", text)
        self.assertIn("opened by Golden cross", text)

    def test_the_reviewer_s_exit_after_the_notice_rings_the_bell_alone(self):
        """One dead thesis, one phone message: the free pass said it, so
        the reviewer's exit on the same row in the same pass (trigger
        T13) leaves its bell row and stays off the phone. A tighten is
        not the notice repeated, and still goes out."""
        from alerts.models import Notification
        from brain.position_review_agent import _notify
        self.assertEqual(self._pass().call_count, 1)
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            self.assertTrue(_notify(_review(self.trade, verdict="exit")))
            self.assertEqual(tg.call_count, 0)
            self.assertTrue(Notification.objects.filter(
                user=self.user, data__kind="position_review").exists())
            self.assertTrue(_notify(_review(self.trade, verdict="tighten",
                                            suggested_stop=Decimal("99.5"))))
        self.assertEqual(tg.call_count, 1)

    def test_a_live_thesis_says_nothing(self):
        alive = dict(self.DEAD, verdict="hold", alive=True,
                     why=["the bias is long at 0.80"],
                     words="Thesis ALIVE — hold.")
        self.assertEqual(self._pass(alive).call_count, 0)

    def test_a_simulated_row_is_not_rung(self):
        self.trade.paper = True
        self.trade.save(update_fields=["paper"])
        self.assertEqual(self._pass().call_count, 0)

    def test_quiet_hours_hold_the_notice_for_the_next_pass(self):
        """Quiet hours honoured: nothing goes out, nothing is recorded, and
        the first pass after them sends the one notice if the thesis is
        still dead."""
        from alerts.models import Notification
        with patch("bot_program.notifications._in_quiet_hours",
                   return_value=True):
            self.assertEqual(self._pass().call_count, 0)
        self.assertFalse(Notification.objects.filter(
            data__kind="thesis_exit").exists())
        self.assertEqual(self._pass().call_count, 1)

    def test_the_notice_never_touches_the_position(self):
        self._pass()
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.status, "OPEN")
        self.assertEqual(self.trade.stop_loss, Decimal("99.00000000"))


# ══════════════════════════════════════════════════════════════════════════
# 2. The ladder's moves are told and audited
# ══════════════════════════════════════════════════════════════════════════

def _control(rule, stage):
    from signals.models_control import RuleControl
    return RuleControl.objects.create(rule_name=rule, promotion_stage=stage,
                                      stage_entered_at=timezone.now())


class TheLadderIsToldTests(TestCase):

    def _move(self, rule, frm, to, **kw):
        from signals.promotion_pipeline import _transition
        _control(rule, frm)
        # the patch outlives the capture: the callbacks run as it exits
        with patch("bot_program.notifications.notify_staff",
                   return_value={"n_delivered": 1}) as staff, \
                self.captureOnCommitCallbacks(execute=True):
            _transition(rule, to, user=kw.pop("user", None),
                        reason=kw.pop("reason", "auto_promote"),
                        notes=kw.pop("notes", ""))
        return staff

    def _audit(self, kind="ladder_move"):
        from bot_program.audit_models import AuditLogEntry
        return list(AuditLogEntry.objects.filter(kind=kind))

    def test_a_promotion_onto_real_money_tells_the_staff(self):
        staff = self._move("golden_cross", "paper", "live_small")
        self.assertEqual(staff.call_count, 1)
        title = staff.call_args.kwargs["title"]
        body = staff.call_args.kwargs["body"]
        self.assertIn("Golden cross", title)
        self.assertIn("real money", title)
        self.assertIn("paper", body)
        self.assertIn("the nightly sweep", body)
        self.assertIsNone(MONEY.search(title + body), body)

    def test_live_small_to_live_full_lifts_the_cap_never_the_size(self):
        """The stage bounds the size; the proof gate and Aragorn's pair
        verdicts set it (an unproven class stays at a quarter on
        live_full): never "four times larger", never "at full size"."""
        staff = self._move("orb_breakout", "live_small", "live_full")
        body = staff.call_args.kwargs["body"]
        self.assertIn("up to full size", body)
        self.assertIn("proof gate (unproven: a quarter; failed: none)", body)
        self.assertNotIn("four times", body)
        self.assertNotIn("at full size", body)
        from signals.promotion_pipeline import _transition
        with patch("bot_program.notifications.notify_staff",
                   return_value={"n_delivered": 1}) as staff, \
                self.captureOnCommitCallbacks(execute=True):
            _transition("orb_breakout", "live_small", user=None,
                        reason="auto_demote")
        self.assertIn("caps its real-money size at a quarter",
                      staff.call_args.kwargs["body"])

    def test_aragorn_s_promotion_says_the_pair_verdicts_it_set(self):
        """Aragorn's rule_live sets live_full but only one class trades,
        on probation; the rest stay on paper. The message says so."""
        from bot_program.aragorn import _apply
        from bot_program.aragorn_models import PairVerdict
        _control("golden_cross", "paper")
        with patch("bot_program.notifications.notify_staff",
                   return_value={"n_delivered": 1}) as staff, \
                self.captureOnCommitCallbacks(execute=True):
            _apply({"kind": "rule_live", "rule": "golden_cross",
                    "asset_class": "forex", "reason": "proven on the bench",
                    "stats": {}}, now=timezone.now())
        body = staff.call_args.kwargs["body"]
        self.assertIn("by Aragorn", body)
        self.assertIn("forex on probation at 0.25x", body)
        self.assertIn("every other class stays on paper", body)
        self.assertNotIn("at full size", body)
        self.assertEqual(PairVerdict.objects.get(
            rule_name="golden_cross", asset_class="forex").state, "probation")
        self.assertIn("forex on probation",
                      self._audit()[0].data["size_note"])

    def test_the_record_at_the_move_is_a_signal_record(self):
        """The event's expectancy and n are the Signal table's
        (_stats_since): predictions, not trades."""
        from signals.models_control import PromotionEvent
        from signals.promotion_pipeline import ladder_move_words
        ev = PromotionEvent(rule_name="golden_cross", from_stage="paper",
                            to_stage="live_small", reason="auto_promote",
                            expectancy_at_transition=0.31,
                            n_at_transition=25)
        body = ladder_move_words(ev)[1]
        self.assertIn("Its signal record (last 90 days): +0.31R a signal "
                      "over 25 graded signals.", body)
        self.assertNotIn("trade over", body)
        self.assertNotIn("graded trade", body)

    def test_bar_losers_is_named_never_the_nightly_sweep(self):
        """`bar_losers --apply` is a person at a shell: its demotion says
        so in the message, the audit row and the morning digest."""
        from django.core.management import call_command
        from io import StringIO
        from alerts.scheduled_digests import ladder_overnight_lines
        from signals.promotion_pipeline import BY_BAR_LOSERS
        _control("rsi_reversal", "live_small")
        with patch("signals.promotion_pipeline.measured_loser",
                   return_value="expectancy -0.12R over 40"), \
                patch("signals.promotion_pipeline.hand_promoted_recently",
                      return_value=False), \
                patch("bot_program.notifications.notify_staff",
                      return_value={"n_delivered": 1}) as staff, \
                self.captureOnCommitCallbacks(execute=True):
            call_command("bar_losers", "--apply", stdout=StringIO())
        self.assertEqual(staff.call_count, 1)
        body = staff.call_args.kwargs["body"]
        self.assertIn(f"by {BY_BAR_LOSERS}", body)
        self.assertNotIn("nightly sweep", body)
        self.assertEqual(self._audit()[0].data["by"], BY_BAR_LOSERS)
        line = "\n".join(ladder_overnight_lines())
        self.assertIn(f"(by {BY_BAR_LOSERS})", line)
        self.assertNotIn("nightly sweep", line)

    def test_a_demotion_from_real_money_is_told_and_audited(self):
        staff = self._move("rsi_reversal", "live_full", "paper",
                           reason="auto_demote",
                           notes="measured loser: expectancy -0.12R")
        self.assertEqual(staff.call_count, 1)
        self.assertIn("paper", staff.call_args.kwargs["title"])
        rows = self._audit()
        self.assertEqual(len(rows), 1)
        d = rows[0].data
        self.assertEqual((d["rule_name"], d["from_stage"], d["to_stage"]),
                         ("rsi_reversal", "live_full", "paper"))
        self.assertEqual(d["reason"], "auto_demote")
        self.assertIn("measured loser", d["notes"])
        self.assertEqual(d["by"], "the nightly sweep")

    def test_a_hand_move_names_the_hand(self):
        op = User.objects.create(username="ladder_op", is_staff=True)
        self._move("macd_cross", "paper", "live_small", user=op,
                   reason="manual_promote")
        self.assertEqual(self._audit()[0].data["by"], "ladder_op")
        self.assertEqual(self._audit()[0].user, op)

    def test_a_move_below_real_money_is_neither_told_nor_audited(self):
        staff = self._move("new_rule", "research", "paper")
        staff.assert_not_called()
        self.assertEqual(self._audit(), [])

    def test_a_move_rolled_back_leaves_no_row_and_no_message(self):
        from django.db import transaction
        from signals.promotion_pipeline import _transition
        _control("rolled", "paper")
        with patch("bot_program.notifications.notify_staff") as staff, \
                self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    _transition("rolled", "live_small", user=None,
                                reason="auto_promote")
                    raise RuntimeError("the caller failed after the move")
            except RuntimeError:
                pass
        staff.assert_not_called()
        self.assertEqual(self._audit(), [])

    def test_the_sweep_sends_one_summary_with_its_refusals(self):
        from signals.promotion_pipeline import auto_evaluate_all_rules
        _control("climber", "paper")
        _control("held_one", "paper")
        _control("faller", "live_full")

        def due(rule):
            return "paper" if rule == "faller" else None

        def eligible(rule):
            return {"climber": "live_small", "held_one": "live_small"}.get(rule)

        def gate(rule, target, caller=""):
            if rule == "held_one":
                return False, "no out-of-sample proof on its classes"
            return True, "proven out of sample"

        # the capture INSIDE the patch: the on_commit callbacks run as the
        # capture exits, while notify_staff is still the mock, so a move
        # told one by one would be counted here
        with patch("signals.promotion_pipeline.is_due_for_demotion", due), \
                patch("signals.promotion_pipeline.is_eligible_for_promotion",
                      eligible), \
                patch("signals.promotion_pipeline.measured_loser",
                      return_value=""), \
                patch("signals.promotion_evidence.gate_promotion", gate), \
                patch("bot_program.notifications.notify_staff",
                      return_value={"n_delivered": 1}) as staff, \
                self.captureOnCommitCallbacks(execute=True):
            result = auto_evaluate_all_rules()
        self.assertEqual(result["promoted"], ["climber"])
        self.assertEqual(result["demoted"], ["faller"])
        self.assertEqual(len(result["blocked"]), 1)
        # ONE message for the whole sweep, the refusal in it
        self.assertEqual(staff.call_count, 1)
        title = staff.call_args.kwargs["title"]
        body = staff.call_args.kwargs["body"]
        self.assertIn("1 promoted", title)
        self.assertIn("1 demoted", title)
        self.assertIn("1 held back", title)
        self.assertIn("Climber", body)
        self.assertIn("Faller", body)
        self.assertIn("Held one", body)
        self.assertIn("no out-of-sample proof", body)
        # the record: each live move, and the sweep with its refusals
        self.assertEqual(len(self._audit("ladder_move")), 2)
        sweep = self._audit("ladder_sweep")
        self.assertEqual(len(sweep), 1)
        self.assertEqual(sweep[0].data["blocked"][0]["rule_name"],
                         "held_one")

    def test_the_same_rules_held_back_night_after_night_are_told_once(self):
        """A rule eligible every night and refused by the evidence gate
        every night: recorded every night, told once, told again only
        when the set held back changes or a rule moves."""
        from signals.promotion_pipeline import auto_evaluate_all_rules
        for rule in ("held_a", "held_b", "held_c"):
            _control(rule, "paper")
        held = {"held_a", "held_b", "held_c"}

        def night(eligible_rules, refused):
            with patch("signals.promotion_pipeline.is_due_for_demotion",
                       return_value=None), \
                    patch("signals.promotion_pipeline."
                          "is_eligible_for_promotion",
                          lambda r: "live_small" if r in eligible_rules
                          else None), \
                    patch("signals.promotion_evidence.gate_promotion",
                          lambda r, t, caller="": (
                              (False, "no out-of-sample proof")
                              if r in refused else (True, "proven"))), \
                    patch("bot_program.notifications.notify_staff",
                          return_value={"n_delivered": 1}) as staff, \
                    self.captureOnCommitCallbacks(execute=True):
                auto_evaluate_all_rules()
            return staff.call_count

        self.assertEqual(night(held, held), 1)
        self.assertEqual(night(held, held), 0)
        self.assertEqual(night(held, held), 0)
        self.assertEqual(len(self._audit("ladder_sweep")), 3)
        # one rule drops out of the held set: that is news
        self.assertEqual(night({"held_a", "held_b"}, held), 1)
        # one rule is promoted, the other still held: news too
        self.assertEqual(night({"held_a", "held_b"}, {"held_b"}), 1)

    def test_a_quiet_sweep_says_nothing(self):
        from signals.promotion_pipeline import auto_evaluate_all_rules
        _control("steady", "paper")
        with patch("signals.promotion_pipeline.is_due_for_demotion",
                   return_value=None), \
                patch("signals.promotion_pipeline.is_eligible_for_promotion",
                      return_value=None), \
                patch("bot_program.notifications.notify_staff") as staff:
            auto_evaluate_all_rules()
        staff.assert_not_called()
        self.assertEqual(self._audit("ladder_sweep"), [])


class TheMorningDigestReadsTheLadderTests(TestCase):

    def test_the_night_s_moves_and_refusals_are_a_section(self):
        from alerts.scheduled_digests import (digest_lines,
                                              generate_morning_digest)
        from bot_program.audit import record_event
        from signals.models_control import PromotionEvent
        PromotionEvent.objects.create(rule_name="golden_cross",
                                      from_stage="live_small",
                                      to_stage="live_full",
                                      reason="auto_promote",
                                      expectancy_at_transition=0.31,
                                      n_at_transition=24)
        old = PromotionEvent.objects.create(rule_name="ancient_rule",
                                            from_stage="paper",
                                            to_stage="live_small",
                                            reason="auto_promote")
        PromotionEvent.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=3))
        record_event("ladder_sweep", {
            "promoted": ["golden_cross"], "demoted": [],
            "blocked": [{"rule_name": "held_one", "target": "live_small",
                         "reason": "no out-of-sample proof"}]})
        digest = generate_morning_digest(user=None)
        lines = [str(x) for x in digest_lines(digest)]
        self.assertIn("Ladder overnight", lines)
        text = "\n".join(lines)
        self.assertIn("Golden cross", text)
        self.assertIn("live (real money), up to full size", text)
        self.assertNotIn("Ancient rule", text)
        self.assertIn("Held back: 1", text)
        self.assertIn("Held one", text)

    def test_a_still_night_says_so(self):
        from alerts.scheduled_digests import (digest_lines,
                                              generate_morning_digest)
        lines = [str(x) for x in digest_lines(
            generate_morning_digest(user=None))]
        i = lines.index("Ladder overnight")
        self.assertIn("No rule changed stage", lines[i + 1])


# ══════════════════════════════════════════════════════════════════════════
# 3. The brakes leave a record
# ══════════════════════════════════════════════════════════════════════════

class TheBrakesLeaveARecordTests(TestCase):

    def setUp(self):
        from tests.test_position_review import _config
        self.user = User.objects.create(username="brake_owner",
                                        is_staff=True)
        self.cfg = _config(self.user, name="Forex live eToro")

    def _rows(self, kind):
        from bot_program.audit_models import AuditLogEntry
        return list(AuditLogEntry.objects.filter(kind=kind).order_by("id"))

    def test_the_kinds_fit_the_column(self):
        from bot_program.audit import AUDIT_KINDS_20261008
        from bot_program.audit_models import AuditLogEntry
        width = AuditLogEntry._meta.get_field("kind").max_length
        for kind in AUDIT_KINDS_20261008:
            self.assertLessEqual(len(kind), width, kind)

    def test_a_brake_is_on_the_chain_with_by_why_who_and_config(self):
        from bot_program.asset_engine import disarm
        self.assertTrue(disarm.disable_config(
            self.cfg, by=disarm.BY_MORGUL,
            why="Market-shut booking: PG 22 minutes before the open",
            who="Morgul"))
        rows = self._rows("config_braked")
        self.assertEqual(len(rows), 1)
        d = rows[0].data
        self.assertEqual(d["by"], "morgul")
        self.assertEqual(d["by_words"], "Morgul's brake")
        self.assertTrue(d["brake"])
        self.assertIn("Market-shut booking", d["why"])
        self.assertEqual(d["who"], "Morgul")
        self.assertEqual(d["config_id"], self.cfg.pk)
        self.assertEqual(d["config"], "Forex live eToro")
        self.assertEqual(rows[0].user, self.user)

    def test_a_hand_stop_is_recorded_and_is_not_a_brake(self):
        from bot_program.asset_engine import disarm
        disarm.disable_config(self.cfg, by=disarm.BY_BOT_OFF, why="bot off",
                              who="shell")
        d = self._rows("config_braked")[0].data
        self.assertEqual(d["by"], "bot_off")
        self.assertFalse(d["brake"])

    def test_a_config_already_off_writes_nothing_more(self):
        from bot_program.asset_engine import disarm
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1")
        disarm.disable_config(self.cfg, by=disarm.BY_EYE, why="/stop")
        self.assertEqual(len(self._rows("config_braked")), 1)

    def test_the_kill_switch_superseding_a_brake_is_recorded(self):
        from bot_program.asset_engine import disarm
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1")
        disarm.disable_config(self.cfg, by=disarm.BY_KILL_SWITCH,
                              why="kill switch", who="op")
        rows = self._rows("config_braked")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].data["by"], "kill_switch")
        self.assertTrue(rows[1].data["superseded"])

    def test_re_arming_says_whose_stop_it_lifted(self):
        """enable_config pops the record; the chain keeps it."""
        from bot_program.asset_engine import disarm
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1",
                              who="Morgul")
        cleared = disarm.enable_config(self.cfg, who="brake_owner",
                                       why="the HQ toggle")
        self.assertEqual(cleared["by"], "morgul")
        self.cfg.refresh_from_db()
        self.assertNotIn(disarm.RECORD_KEY, self.cfg.extras)
        rows = self._rows("config_rearmed")
        self.assertEqual(len(rows), 1)
        d = rows[0].data
        self.assertEqual(d["lifted_by"], "morgul")
        self.assertEqual(d["lifted_why"], "g1")
        self.assertEqual(d["who"], "brake_owner")
        self.assertEqual(d["config_id"], self.cfg.pk)
        # the brake itself is still on the chain after the re-arm
        self.assertEqual(self._rows("config_braked")[0].data["why"], "g1")

    def test_arming_a_config_already_on_writes_nothing(self):
        from bot_program.asset_engine import disarm
        disarm.enable_config(self.cfg)
        self.assertEqual(self._rows("config_rearmed"), [])

    def test_adopting_an_unrecorded_stop_is_a_brake_on_the_chain(self):
        """`bot brake` on a bot ALREADY off with no record: on the chain,
        flagged adopted, and no reader calls it a stop made then or says
        its exits "kept running" — they had stopped with the bot and run
        again from this moment."""
        from bot_program.asset_engine import disarm
        from core.component_digest import collect_faults
        from dashboard.activity_feed import activity_events
        from dashboard.views_forensics import _lifecycle
        from tests.test_position_review import _trade
        trade = _trade("ADPQ", user=self.user, cfg_name="Forex live eToro")
        type(self.cfg).objects.filter(pk=self.cfg.pk).update(enabled=False)
        self.cfg.refresh_from_db()
        self.assertTrue(disarm.adopt_unrecorded(self.cfg, why="adopt",
                                                who="shell"))
        d = self._rows("config_braked")[0].data
        self.assertEqual(d["by"], "bot_brake")
        self.assertTrue(d["brake"])
        self.assertTrue(d["adopted"])
        feed = [e for e in activity_events(self.user)
                if e["id"].startswith("audit:")]
        said = " ".join(f"{e['title']} {e.get('detail') or ''}" for e in feed)
        self.assertIn("off with no record", said)
        self.assertIn("its exits run again from this moment", said)
        self.assertNotIn("stay managed", said)
        line = collect_faults()["brakes"][0]["message"]
        self.assertIn("off with no record", line)
        self.assertNotIn("stopped by", line)
        events = [e for e in _lifecycle(trade)
                  if e["label"] == "Bot's stop recorded"]
        self.assertEqual(len(events), 1)
        self.assertIn("its exits run again", events[0]["detail"])
        self.assertNotIn("kept running", events[0]["detail"])

    # ── who reads them ────────────────────────────────────────────────────

    def test_the_activity_feed_prints_the_brake_and_the_re_arm(self):
        from bot_program.asset_engine import disarm
        from dashboard.activity_feed import activity_events
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1",
                              who="Morgul")
        disarm.enable_config(self.cfg, who="brake_owner")
        titles = [e["title"] for e in activity_events(self.user)
                  if e["id"].startswith("audit:")]
        self.assertTrue(any("Forex live eToro" in t and "Morgul's brake" in t
                            for t in titles), titles)
        self.assertTrue(any("Forex live eToro" in t and "re-armed" in t
                            for t in titles), titles)

    def test_the_position_page_reads_the_brakes_of_its_life(self):
        from bot_program.asset_engine import disarm
        from dashboard.views_forensics import _audit_entries, _lifecycle
        from tests.test_position_review import _trade
        trade = _trade("BRKQ", user=self.user, cfg_name="Forex live eToro")
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1",
                              who="Morgul")
        disarm.enable_config(self.cfg, who="brake_owner")
        kinds = [r.kind for r in _audit_entries(trade)]
        self.assertIn("config_braked", kinds)
        self.assertIn("config_rearmed", kinds)
        labels = [e["label"] for e in _lifecycle(trade)]
        self.assertIn("Bot braked", labels)
        self.assertIn("Bot re-armed", labels)
        # another config's brake is not this trade's story
        from tests.test_position_review import _config
        other = _config(self.user, name="Other bot")
        disarm.disable_config(other, by=disarm.BY_MORGUL, why="other")
        self.assertEqual(
            sum(1 for r in _audit_entries(trade) if r.kind == "config_braked"),
            1)

    def test_the_07_00_digest_lists_the_brakes_of_the_last_day(self):
        from bot_program.asset_engine import disarm
        from bot_program.audit_models import AuditLogEntry
        from core.component_digest import collect_faults, render_digest
        from tests.test_position_review import _config
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL,
                              why="loss of 523.10 USD on the day",
                              who="Morgul")
        hand = _config(self.user, name="Hand stopped")
        disarm.disable_config(hand, by=disarm.BY_BOT_OFF, why="bot off")
        old = _config(self.user, name="Old brake")
        disarm.disable_config(old, by=disarm.BY_EYE, why="/stop")
        AuditLogEntry.objects.filter(data__config_id=old.pk).update(
            created_at=timezone.now() - timedelta(hours=30))
        faults = collect_faults()
        names = [b["name"] for b in faults["brakes"]]
        self.assertEqual(names, ["Forex live eToro"])
        title, body = render_digest(faults)
        self.assertIn("Braked in the last 24 hours (1)", body)
        self.assertIn("Morgul's brake", body)
        self.assertIn("still off", body)
        # the phone's words: never the why (free text) nor a money figure
        self.assertNotIn("523.10", body)
        self.assertIsNone(MONEY.search(body), body)

    def test_a_brake_lifted_since_is_noted_never_counted(self):
        """A brake already re-armed is not a thing that needs attention: it
        never counts in the title, and alone it sends nothing (silence
        means healthy); beside a real fault it is listed apart. Each hour
        carries its day: a 07:00 digest reads "08:00" as today's."""
        from bot_program.asset_engine import disarm
        from core.component_digest import collect_faults, render_digest
        from tests.test_position_review import _config
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1")
        disarm.enable_config(self.cfg, who="brake_owner")
        faults = collect_faults()
        self.assertEqual(faults["brakes"], [])
        self.assertEqual(len(faults["rearmed"]), 1)
        message = faults["rearmed"][0]["message"]
        self.assertRegex(message, r"at (Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
                                  r"\d\d:\d\d UTC; re-armed at "
                                  r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d\d:\d\d")
        quiet = {"errors": [], "warnings": [], "silent": [], "feeds": [],
                 "checked": 3}
        self.assertEqual(render_digest(dict(quiet, brakes=[],
                                            rearmed=faults["rearmed"])),
                         (None, None))
        still = _config(self.user, name="Still off")
        disarm.disable_config(still, by=disarm.BY_EYE, why="/stop")
        faults = collect_faults()
        title, body = render_digest(dict(quiet, brakes=faults["brakes"],
                                         rearmed=faults["rearmed"]))
        self.assertIn("1 thing needs attention", title)
        self.assertIn("Braked in the last 24 hours (1)", body)
        self.assertIn("Braked, and re-armed since (1)", body)
        self.assertIn("Forex live eToro", body)

    def test_a_brake_after_a_re_arm_is_still_off(self):
        """Brake, re-arm, brake again: the newest brake is after the
        re-arm, so the bot is still off — never "re-armed"."""
        from bot_program.asset_engine import disarm
        from bot_program.audit_models import AuditLogEntry
        from core.component_digest import collect_faults
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1")
        disarm.enable_config(self.cfg, who="brake_owner")
        AuditLogEntry.objects.filter(
            kind__in=("config_braked", "config_rearmed")).update(
            created_at=timezone.now() - timedelta(hours=2))
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1 again")
        faults = collect_faults()
        self.assertEqual(len(faults["brakes"]), 1)
        self.assertIn("still off", faults["brakes"][0]["message"])
        self.assertEqual(faults["rearmed"], [])

    def test_a_brake_before_the_entry_is_not_the_trade_s_story(self):
        from bot_program.asset_engine import disarm
        from bot_program.audit_models import AuditLogEntry
        from dashboard.views_forensics import _audit_entries, _lifecycle
        from tests.test_position_review import _trade
        disarm.disable_config(self.cfg, by=disarm.BY_MORGUL, why="g1")
        AuditLogEntry.objects.filter(kind="config_braked").update(
            created_at=timezone.now() - timedelta(days=2))
        trade = _trade("BRKQ", user=self.user, cfg_name="Forex live eToro")
        self.assertNotIn("config_braked",
                         [r.kind for r in _audit_entries(trade)])
        self.assertNotIn("Bot braked",
                         [e["label"] for e in _lifecycle(trade)])


# ══════════════════════════════════════════════════════════════════════════
# 4. One posture word: the brief's, beside the measured one
# ══════════════════════════════════════════════════════════════════════════

STRESSED = {"level": "stressed", "score": 41.5, "at": None, "fresh": True,
            "why": "SPX500 5.2% under its 60-day high"}


class OnePostureWordTests(TestCase):

    def test_the_snapshot_reads_the_measured_posture(self):
        from brain.strategist import _build_strategist_snapshot
        with patch("bot_program.market_stress.current",
                   return_value=dict(STRESSED)), \
                patch("bot_program.posture.crisis_mode_on",
                      return_value=True):
            snap = _build_strategist_snapshot()
        mp = snap["measured_posture"]
        self.assertEqual(mp["level"], "stressed")
        self.assertEqual(mp["score"], 41.5)
        self.assertIn("SPX500", mp["why"])
        self.assertTrue(mp["crisis_mode_on"])
        self.assertTrue(mp["sizes_real_orders"])
        self.assertIn("leverage halved", mp["what_it_does"])

    def test_the_prompt_says_whose_word_sizes_orders(self):
        from types import SimpleNamespace
        from brain.strategist import StrategistAgent
        prompt = StrategistAgent.get_system_prompt(SimpleNamespace())
        self.assertIn("measured_posture", prompt)
        self.assertIn("sizes nothing", prompt)
        # "read every 15 minutes" only while crisis mode is on
        self.assertIn("While `crisis_mode_on` is true it is read every 15 "
                      "minutes", prompt)
        self.assertIn("while `crisis_mode_on` is false no reading is taken",
                      prompt)
        self.assertIn("never call an unmeasured posture calm", prompt)

    def test_the_briefing_stores_the_measured_posture_beside_its_word(self):
        from brain.briefing_models import StrategistBriefing
        from brain.strategist import run_strategist_now
        from tests.test_brain_phase40_strategist import (
            _stub_strategist_provider)
        with _stub_strategist_provider({"posture": "defensive",
                                        "outlook_md": "Risk is rising."}), \
                patch("bot_program.market_stress.current",
                      return_value=dict(STRESSED, level="calm",
                                        why="business as usual")), \
                patch("bot_program.posture.crisis_mode_on",
                      return_value=False):
            result = run_strategist_now()
        self.assertTrue(result["ok"])
        b = StrategistBriefing.objects.get()
        self.assertEqual(b.posture, "defensive")
        # crisis mode OFF: the level sizes nothing, and the title says so
        self.assertEqual(b.measured_posture, "crisis mode OFF: calm")
        self.assertIn("crisis mode is OFF", b.measured_posture_note)

    def test_nothing_measured_is_never_called_calm(self):
        """market_stress.current() answers "calm" with no reading, with one
        past HOLD_HOURS, on a failed read and for an override: the stored
        word names each, and crisis mode OFF leads it."""
        from types import SimpleNamespace
        from brain.strategist import measured_posture, posture_title
        now = timezone.now()
        cases = (
            ({"level": "calm", "score": None, "at": None, "fresh": False,
              "why": "no stress reading yet"}, "unmeasured"),
            ({"level": "calm", "score": None, "at": now - timedelta(days=2),
              "fresh": False, "why": "last reading 48h old: calm by default"},
             "unmeasured"),
            ({"level": "calm", "score": None, "at": None, "fresh": False,
              "why": "posture unreadable: OperationalError"}, "unmeasured"),
            ({"level": "stressed", "score": None, "at": now, "fresh": True,
              "why": "operator override until 2026-10-09T10:00"},
             "stressed (override)"),
            ({"level": "stressed", "score": 33.0,
              "at": now - timedelta(hours=5), "fresh": False,
              "why": "last reading 5.0h old: its level holds"},
             "stressed, 5h old"),
            (dict(STRESSED), "stressed"),
        )
        for cur, word in cases:
            with self.subTest(word=word, why=cur["why"]):
                with patch("bot_program.market_stress.current",
                           return_value=cur), \
                        patch("bot_program.posture.crisis_mode_on",
                              return_value=True):
                    mp = measured_posture(now)
                self.assertEqual(mp["level"], word)
                self.assertEqual(mp["title_word"], word)
                self.assertLessEqual(len("crisis mode OFF: " + word), 40)
                b = SimpleNamespace(posture="defensive",
                                    measured_posture=mp["title_word"])
                self.assertEqual(posture_title(b),
                                 f"DEFENSIVE · measured: {word}")
        # the empty book, read for real: no reading at all
        with patch("bot_program.posture.crisis_mode_on", return_value=False):
            mp = measured_posture()
        self.assertEqual(mp["title_word"], "crisis mode OFF: unmeasured")
        self.assertEqual(mp["what_it_does"], "")

    def test_a_failed_briefing_keeps_the_measured_posture(self):
        from unittest.mock import MagicMock
        from brain.briefing_models import StrategistBriefing
        from brain.strategist import run_strategist_now

        def bad_init(agent, *a, **kw):
            agent.agent_name, agent.provider_name = "strategist", "stub"
            agent.model = "stub"
            agent.provider = MagicMock()
            agent.provider.complete = MagicMock(
                side_effect=RuntimeError("api 500"))
        with patch("brain.strategist.StrategistAgent.__init__", bad_init), \
                patch("bot_program.market_stress.current",
                      return_value=dict(STRESSED)), \
                patch("bot_program.posture.crisis_mode_on",
                      return_value=True):
            self.assertFalse(run_strategist_now()["ok"])
        b = StrategistBriefing.objects.get()
        self.assertEqual(b.model_used, "error")
        self.assertEqual(b.measured_posture, "stressed")

    def test_the_telegram_title_shows_both_words(self):
        from alerts.models import UserNotificationPrefs
        from brain.briefing_models import StrategistBriefing
        from bot_program.notifications import (
            notify_strategist_briefing_to_all)
        user = _operator("brief_reader")
        UserNotificationPrefs.objects.filter(user=user).update(
            receive_strategist_briefing=True)
        b = StrategistBriefing.objects.create(
            posture="defensive", outlook_md="Risk is rising.",
            measured_posture="calm",
            measured_posture_note="business as usual; crisis mode is ON")
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as tg:
            notify_strategist_briefing_to_all(b)
        title = tg.call_args.args[1]
        self.assertIn("DEFENSIVE · measured: calm", title)
        lines = [str(x) for x in tg.call_args.kwargs.get("lines") or []]
        measured = [x for x in lines if x.startswith("Measured posture")]
        self.assertEqual(len(measured), 1, lines)
        self.assertIn("calm", measured[0])
        self.assertIsNone(MONEY.search(measured[0]), measured[0])

    def test_a_briefing_from_before_keeps_its_one_word(self):
        from brain.briefing_models import StrategistBriefing
        from brain.strategist import posture_title
        b = StrategistBriefing.objects.create(posture="balanced")
        self.assertEqual(posture_title(b), "BALANCED")

    def test_the_email_subject_shows_both_words(self):
        from alerts.channels.briefing_email import briefing_subject
        from brain.briefing_models import StrategistBriefing
        b = StrategistBriefing.objects.create(posture="aggressive",
                                              measured_posture="crisis")
        self.assertIn("AGGRESSIVE · measured: crisis", briefing_subject(b))


# ══════════════════════════════════════════════════════════════════════════
# 5. The weekly review reads the live book
# ══════════════════════════════════════════════════════════════════════════

def _closed(symbol, r, *, user, rule="golden_cross", real=False,
            cfg_name="wk_cfg", days_ago=2, by_hand=False):
    from tests.test_position_review import _trade
    t = _trade(symbol, user=user, rule_name=rule, cfg_name=cfg_name)
    if real:
        _real(t)
    type(t).objects.filter(pk=t.pk).update(
        status="CLOSED", realized_r=r,
        outcome="hit_target" if r > 0 else "stopped_out",
        closed_at=timezone.now() - timedelta(days=days_ago),
        reason=("closed:MANUAL" if by_hand else t.reason))
    return t


class TheWeeklyReviewReadsTheLiveBookTests(TestCase):

    def setUp(self):
        self.user = _operator("weekly_op")

    def test_live_and_paper_are_apart_and_labelled(self):
        from ai_agents.tasks import weekly_book_context
        _closed("LIVA", 1.2, user=self.user, real=True, cfg_name="live_cfg")
        _closed("LIVB", -1.0, user=self.user, real=True, cfg_name="live_cfg")
        _closed("PAPA", 0.5, user=self.user, cfg_name="paper_cfg")
        _closed("HAND", 0.8, user=self.user, rule="manual_take", real=True,
                cfg_name="manual_cfg")
        _closed("OLDX", 3.0, user=self.user, real=True, cfg_name="live_cfg",
                days_ago=12)
        ctx = weekly_book_context()
        live, paper = ctx["live_book"], ctx["paper_book"]
        self.assertIn("real money", live["venue"])
        self.assertIn("simulated", paper["venue"])
        live_n = {(r["rule_name"]): r["n"] for r in live["by_rule"]}
        self.assertEqual(live_n, {"golden_cross": 2, "manual_take": 1})
        self.assertEqual({r["rule_name"]: r["n"] for r in paper["by_rule"]},
                         {"golden_cross": 1})
        # the scorecard per lane, per venue: the hand lane apart
        self.assertEqual(live["scorecard"]["manual"]["n"], 1)
        self.assertEqual(live["scorecard"]["bots"]["n"], 2)
        self.assertAlmostEqual(live["scorecard"]["bots"]["expectancy"], 0.1)
        self.assertIn("diagnosis", live["scorecard"]["bots"])
        self.assertEqual(paper["scorecard"]["bots"]["n"], 1)

    def test_a_demo_close_is_never_in_the_live_book(self):
        """A broker's demo account is paper=False, and it is not money: its
        closes are the DEMO BOOK, apart from the live and the paper ones,
        in the grades and in the scorecard."""
        from ai_agents.tasks import weekly_book_context
        live = _closed("LIVA", 1.2, user=self.user, real=True,
                       cfg_name="live_cfg")
        demo = _closed("AAPL", -0.6, user=self.user, rule="manual_take",
                       real=True, cfg_name="demo_cfg")
        type(demo).objects.filter(pk=demo.pk).update(
            metadata=dict(demo.metadata, broker_env="paper"))
        _closed("PAPA", 0.5, user=self.user, cfg_name="paper_cfg")
        ctx = weekly_book_context()
        self.assertIsNotNone(live)
        self.assertEqual(ctx["live_book"]["n_closed_graded"], 1)
        self.assertEqual([r["rule_name"] for r in ctx["live_book"]["by_rule"]],
                         ["golden_cross"])
        self.assertNotIn("manual", ctx["live_book"]["scorecard"])
        self.assertEqual(ctx["demo_book"]["n_closed_graded"], 1)
        self.assertEqual(ctx["demo_book"]["scorecard"]["manual"]["n"], 1)
        self.assertIn("demo", ctx["demo_book"]["venue"])
        self.assertIn("not money", ctx["demo_book"]["venue"])
        self.assertEqual(ctx["paper_book"]["n_closed_graded"], 1)
        self.assertEqual(ctx["live_book"]["venue"], "live: real money")

    def test_the_skips_the_guards_and_the_brakes_of_the_week(self):
        from django.core.cache import cache
        from ai_agents.tasks import weekly_book_context
        from bot_program.asset_engine import disarm
        from bot_program.morgul import STATE_KEY
        from tests.test_position_review import _config
        cfg = _config(self.user, name="Stocks live")
        cfg.extras = {"skip_counts": {"no_signals": 40, "market_shut": 12}}
        cfg.save(update_fields=["extras"])
        disarm.disable_config(cfg, by=disarm.BY_MORGUL,
                              why="booked while NYSE was shut")
        now = timezone.now()
        cache.set(STATE_KEY, {
            "g1:26": {"guard": "g1", "name": "Market shut", "severity":
                      "critical", "label": "PG booked 22 min before the open",
                      "subject": "26", "first": (now - timedelta(days=2))
                      .isoformat(), "sent": now.isoformat(), "braked": True},
            "g9:old": {"guard": "g9", "name": "Drift", "severity": "warning",
                       "label": "an old one", "subject": "x",
                       "first": (now - timedelta(days=20)).isoformat()}},
            3600)
        try:
            ctx = weekly_book_context()
        finally:
            cache.delete(STATE_KEY)
        skips = {s["config"]: s for s in ctx["skips"]["configs"]}
        self.assertEqual(skips["Stocks live"]["top"][0],
                         {"code": "no_signals", "count": 40})
        self.assertIn("cumulative", ctx["skips"]["note"])
        # every finding still standing, the old one too, each dated
        found = {f["label"]: f for f in ctx["guards"]["findings"]}
        self.assertEqual(set(found), {"PG booked 22 min before the open",
                                      "an old one"})
        self.assertTrue(found["PG booked 22 min before the open"]
                        ["new_this_week"])
        self.assertFalse(found["an old one"]["new_this_week"])
        self.assertTrue(found["an old one"]["first_seen"])
        self.assertIn("still standing", ctx["guards"]["note"])
        self.assertNotIn("seven days", ctx["guards"]["note"])
        brakes = ctx["guards"]["brakes"]
        self.assertEqual(len(brakes), 1)
        self.assertEqual(brakes[0]["config"], "Stocks live")
        self.assertEqual(brakes[0]["by"], "Morgul's brake")

    def test_the_macro_is_fred_and_the_measured_stress_never_empty(self):
        from ai_agents.tasks import weekly_book_context
        from market_data.models import MacroIndicator, MacroObservation
        vix = MacroIndicator.objects.create(series_id="VIXCLS", name="VIX",
                                            category="vol", frequency="d")
        today = timezone.now().date()
        MacroObservation.objects.create(indicator=vix, value=Decimal("21.4"),
                                        date=today - timedelta(days=1))
        MacroObservation.objects.create(indicator=vix, value=Decimal("20.0"),
                                        date=today - timedelta(days=3))
        MacroObservation.objects.create(indicator=vix, value=Decimal("19.0"),
                                        date=today - timedelta(days=8))
        # a monthly series: compared with its previous RELEASE, dated
        ff = MacroIndicator.objects.create(series_id="FEDFUNDS",
                                           name="Fed funds", category="rates",
                                           frequency="m")
        MacroObservation.objects.create(indicator=ff, value=Decimal("4.33"),
                                        date=today - timedelta(days=14))
        MacroObservation.objects.create(indicator=ff, value=Decimal("4.58"),
                                        date=today - timedelta(days=45))
        MacroObservation.objects.create(indicator=ff, value=Decimal("4.83"),
                                        date=today - timedelta(days=75))
        with patch("bot_program.market_stress.current",
                   return_value=dict(STRESSED)):
            macro = weekly_book_context()["macro"]
        vixr = macro["fred"]["VIXCLS"]
        self.assertEqual(vixr["value"], 21.4)
        # a daily series: the value a week before, not the one before last
        self.assertEqual(vixr["previous"], 19.0)
        self.assertEqual(vixr["previous_date"],
                         (today - timedelta(days=8)).isoformat())
        self.assertNotIn("week_ago", vixr)
        fed = macro["fred"]["FEDFUNDS"]
        self.assertEqual((fed["previous"], fed["previous_date"]),
                         (4.58, (today - timedelta(days=45)).isoformat()))
        # a series with no observation is said, not left out
        self.assertEqual(macro["fred"]["GDP"],
                         {"name": "Gross Domestic Product", "missing": True})
        self.assertEqual(macro["fred_note"], "")
        self.assertEqual(macro["market_stress"]["level"], "stressed")
        self.assertIn("crisis_mode_on", macro)

    def test_no_fred_row_is_said_not_left_empty(self):
        from ai_agents.tasks import weekly_book_context
        from core.constants import FRED_SERIES
        macro = weekly_book_context()["macro"]
        self.assertEqual(set(macro["fred"]), set(FRED_SERIES))
        self.assertTrue(all(v.get("missing") for v in macro["fred"].values()))
        self.assertIn("no FRED observation", macro["fred_note"])

    def test_the_review_is_built_from_the_book_and_grades_no_wizard_plan(self):
        from ai_agents.tasks import generate_weekly_review
        from strategies.models import Strategy
        Strategy.objects.create(name="Wizard plan nobody executes",
                                description="d", time_horizon="swing",
                                status="active", pnl_pct=37.0)
        _closed("LIVA", 1.2, user=self.user, real=True, cfg_name="live_cfg")
        seen = {}

        def fake_run(agent, **kwargs):
            seen.update(kwargs)
            seen["context"] = agent.build_context(**kwargs)
            return {"review": "A short review."}

        with patch("ai_agents.agents.weekly_reviewer.WeeklyReviewerAgent.run",
                   fake_run), \
                patch("requests.post"):
            generate_weekly_review.__wrapped__.__wrapped__()
        self.assertNotIn("strategies", seen)
        self.assertNotEqual(seen["macro"], "")
        self.assertIn("market_stress", json.loads(seen["macro"]))
        context = seen["context"]
        self.assertNotIn("Wizard plan nobody executes", context)
        self.assertIn("LIVE BOOK", context)
        self.assertIn("DEMO BOOK", context)
        self.assertIn("PAPER BOOK", context)
        self.assertIn("SCORECARD", context)
        self.assertIn("SKIPS", context)
        self.assertIn("GUARDS", context)
        self.assertIn("MACRO DATA", context)
        self.assertIn("golden_cross", context)

    def test_the_prompt_keeps_the_books_apart_and_names_no_strategy(self):
        from ai_agents.agents.weekly_reviewer import WeeklyReviewerAgent
        prompt = WeeklyReviewerAgent().get_system_prompt()
        self.assertIn("LIVE BOOK", prompt)
        self.assertIn("DEMO BOOK", prompt)
        self.assertIn("a demo or paper result is not money made or lost",
                      " ".join(prompt.split()))
        self.assertIn("previous observation with ITS date",
                      " ".join(prompt.split()))
        self.assertIn("never add", prompt.lower())
        self.assertIn("wizard", prompt.lower())
        self.assertIn("sizing_note", prompt)
        self.assertNotIn("How did each active strategy perform", prompt)
