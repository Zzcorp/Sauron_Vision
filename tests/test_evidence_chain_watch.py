"""The chain is watched, and the report does not bury itself (2026-09-15).

TWO DEFECTS, ONE RUN AGAINST THE LIVE BOX.

`paper_readiness` was run on the real fleet for the first time. It worked —
the chain was complete, 163 of 169 closed signals carried a realized_r, the
ladder had evidence. It also produced a WORTH READING list of SIXTY-FIVE
near-identical paragraphs, each saying a US market was shut. Above them sat
the two findings that mattered: `actuator_mode_live` and
`meta_allocator_mode_live` both ON, proposers allowed to act on live capital
during what was meant to be a paper campaign.

A report that repeats itself sixty-five times is not thorough. It is
unreadable, and an operator who scrolls past it once scrolls past it every
time. That is the same failure as a bar age with no market beside it: the
information is present and cannot be used. So findings are grouped by CAUSE
and name their symbols, because "8 symbols are stale" sends an operator to a
page and "LEANHOGS, LIVECATTLE, LUMBER" sends them to a feed.

THE SECOND DEFECT WAS THAT NOTHING WATCHED.

`paper_readiness` answers the question the moment it is asked. A campaign
that starts green and goes cold on day twelve spends seventy-eight days
producing nothing, and `guarded_task` no-ops without raising on a component
that is off or has no row. Nothing would have noticed. `watch_evidence_chain`
asks daily on the operator's behalf, and the alert is what a campaign's
silence sounds like.

The watchdog is READ-ONLY on purpose. One that repaired the chain would be
one nobody could trust to report it honestly, and switching a pipeline back
on is an operator's decision.

IT TELLS THE TRUTH FOR A LIVE OPERATOR (2026-11-12).

The operator, 2026-11-11, quoted its alarm: "The evidence chain is broken".
Every link was ON. He trades real money by decision, and two of the checks
ask whether the campaign is PAPER: the five live-action switches off, one
paper bot on. A live operator can never meet them, so the alarm came back
every one to two days, for ever, with a title and a summary that were false
for him. Pinned below:

  * a decision is said once ("Live by decision"), never alarmed, and the
    bell rows are its memory, so an emptied cache cannot repeat it;
  * a fault is alarmed: a link OFF or with NO ROW, an unticked beat entry,
    closed signals with no result, bars missing or stale, no symbol;
  * it speaks when the SET of faults changes, never because a day passed
    or because a fault's sentence moved (a stale bar a day older, one more
    signal with no result), and reminds after seven days;
  * a live hand lane is not a bot: paper bots beside one are still a paper
    campaign;
  * a rule born at research that reached the paper stage and has no paper
    bot to trade on is the one paper check a live operator keeps.
"""
import os
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import campaign_readiness as cr


def _component(key, enabled):
    from core.platform_control import PlatformComponent
    row, _ = PlatformComponent.objects.get_or_create(
        key=key, defaults={"name": key, "description": ""})
    row.is_enabled = enabled
    row.save(update_fields=["is_enabled"])
    return row


def _warm_chain():
    _component("platform_master", True)
    for key, _why in cr.EVIDENCE_CHAIN:
        _component(key, True)
    for key in cr.MUST_BE_OFF:
        _component(key, False)


def _config(user, symbols, name="p1", mode="paper", asset_class="stock"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=list(symbols), capital=Decimal("1000"),
        base_currency="EUR", enabled=True)


def _bar(symbol, age_hours, *, asset_class="stock", exchange="NYSE"):
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange})
    PriceData.objects.update_or_create(
        instrument=inst, timeframe="4h",
        timestamp=timezone.now() - timedelta(hours=age_hours),
        defaults={"open": 1, "high": 2, "low": 1, "close": Decimal("10"),
                  "volume": 1, "source": "test"})
    return inst


SHUT = {"session": "NYSE", "code": "NYSE", "is_open": False}
OPEN = {"session": "NYSE", "code": "NYSE", "is_open": True}


class OneCauseIsOneFindingTests(TestCase):
    """Sixty-one symbols behind one shut exchange is one fact."""

    def setUp(self):
        _warm_chain()
        self.user = User.objects.create_user("group_u", password="x")

    def _readiness(self, market):
        with mock.patch("core.exchange_status.market_status_for",
                        return_value=market):
            return cr.readiness()

    def test_twenty_symbols_behind_one_shut_market_make_one_note(self):
        syms = [f"SYM{i:02d}" for i in range(20)]
        for s in syms:
            _bar(s, 12.0)
        _config(self.user, syms)
        report = self._readiness(SHUT)
        shut_notes = [n for n in report["notes"] if "shut" in n]
        self.assertEqual(
            len(shut_notes), 1,
            f"twenty symbols produced {len(shut_notes)} notes; the live box "
            f"produced sixty-five and buried two real blockers")

    def test_the_note_names_the_symbols(self):
        syms = ["AAA", "BBB", "CCC"]
        for s in syms:
            _bar(s, 12.0)
        _config(self.user, syms)
        note = next(n for n in self._readiness(SHUT)["notes"] if "shut" in n)
        for s in syms:
            self.assertIn(s, note,
                          "the note gives a count and no names — that sends "
                          "an operator to a page instead of to a feed")

    def test_a_long_list_is_truncated_rather_than_dumped(self):
        syms = [f"S{i:03d}" for i in range(40)]
        for s in syms:
            _bar(s, 12.0)
        # Two configs, because one config is capped at SYMBOLS_PER_CONFIG.
        _config(self.user, syms[:20], name="p1")
        _config(self.user, syms[20:], name="p2")
        note = next(n for n in self._readiness(SHUT)["notes"] if "shut" in n)
        self.assertIn("more", note)
        self.assertLessEqual(
            note.count(", "), cr.NAMES_SHOWN + 2,
            "the note lists every symbol; past a dozen names nobody reads it")

    def test_the_worst_age_is_the_one_reported(self):
        _bar("OLD", 40.0)
        _bar("NEW", 7.0)
        _config(self.user, ["OLD", "NEW"])
        note = next(n for n in self._readiness(SHUT)["notes"] if "shut" in n)
        self.assertIn("40.0h", note)

    def test_open_and_shut_stay_separate_findings(self):
        """Grouping must not merge two different diagnoses back into one."""
        _bar("LATE", 12.0)
        _config(self.user, ["LATE"])
        report = self._readiness(OPEN)
        self.assertEqual(report["notes"], [])
        self.assertTrue(any("OPEN" in b for b in report["blockers"]))

    def test_symbols_with_no_bars_are_one_finding_too(self):
        syms = ["NOBAR1", "NOBAR2", "NOBAR3"]
        from instruments.models import Instrument
        for s in syms:
            Instrument.objects.get_or_create(
                symbol=s, defaults={"name": s, "asset_class": "stock"})
        _config(self.user, syms)
        report = self._readiness(SHUT)
        hits = [b for b in report["blockers"] if "no 4h bars" in b]
        self.assertEqual(len(hits), 1, hits)
        for s in syms:
            self.assertIn(s, hits[0])


class TheWatchdogSpeaksWhenTheChainGoesColdTests(TestCase):

    def setUp(self):
        cache.clear()
        _warm_chain()
        self.user = User.objects.create_user(
            "watch_staff", password="x", is_staff=True)
        _config(self.user, ["WATCHED"])
        _bar("WATCHED", 1.0)

    def _run(self):
        from bot_program.tasks import watch_evidence_chain
        with mock.patch("core.exchange_status.market_status_for",
                        return_value=OPEN):
            return watch_evidence_chain.__wrapped__.__wrapped__()

    def test_a_complete_chain_says_nothing(self):
        with mock.patch("bot_program.notifications."
                        "notify_evidence_chain_cold") as notify:
            out = self._run()
        notify.assert_not_called()
        self.assertEqual(out["cold_links"], [])
        self.assertEqual(out["blockers"], 0)

    def test_a_cold_link_notifies_once_and_names_it(self):
        _component("pipeline_promotion", False)
        with mock.patch("bot_program.notifications."
                        "notify_evidence_chain_cold",
                        return_value=True) as notify:
            out = self._run()
        notify.assert_called_once()
        self.assertEqual(notify.call_args.kwargs["cold"],
                         ["pipeline_promotion"])
        self.assertEqual(out["notified"], 1)

    def test_it_does_not_repeat_itself_every_day(self):
        """A chain cold for a week is one problem. Seven identical alerts is
        how an operator learns to ignore the eighth."""
        _component("pipeline_promotion", False)
        with mock.patch("bot_program.notifications."
                        "notify_evidence_chain_cold",
                        return_value=True) as notify:
            self._run()
            out = self._run()
        notify.assert_called_once()
        self.assertEqual(out["status"], "cooldown")

    def test_a_chain_that_recovers_can_speak_again_at_once(self):
        """The cooldown must not swallow a NEW cold spell."""
        _component("pipeline_promotion", False)
        with mock.patch("bot_program.notifications."
                        "notify_evidence_chain_cold",
                        return_value=True) as notify:
            self._run()
            _component("pipeline_promotion", True)
            self._run()                       # complete: clears the gate
            _component("pipeline_promotion", False)
            self._run()                       # cold again: speaks
        self.assertEqual(notify.call_count, 2)

    def test_it_says_so_when_there_is_nobody_to_tell(self):
        """Not an error and not a success. The check ran, the chain is cold,
        and no active staff user exists — returning a clean dict would be the
        defect this whole watchdog exists to prevent."""
        User.objects.filter(is_staff=True).update(is_staff=False)
        _component("pipeline_promotion", False)
        out = self._run()
        self.assertEqual(out["status"], "nobody_to_tell")
        self.assertEqual(out["notified"], 0)

    def test_it_repairs_nothing(self):
        """A watchdog that switched the chain back on could not be trusted to
        report it honestly — and turning a pipeline on is an operator's
        decision, not a task's."""
        from core.platform_control import PlatformComponent
        _component("pipeline_promotion", False)
        before = sorted(PlatformComponent.objects.values_list(
            "key", "is_enabled"))
        with mock.patch("bot_program.notifications."
                        "notify_evidence_chain_cold", return_value=True):
            self._run()
        after = sorted(PlatformComponent.objects.values_list(
            "key", "is_enabled"))
        self.assertEqual(before, after)

    def test_one_failing_recipient_does_not_silence_the_rest(self):
        User.objects.create_user("watch_staff2", password="x", is_staff=True)
        _component("pipeline_promotion", False)
        with mock.patch("bot_program.notifications."
                        "notify_evidence_chain_cold",
                        side_effect=[RuntimeError("boom"), True]):
            out = self._run()
        self.assertEqual(out["notified"], 1)


class TheWatchdogIsWiredTests(TestCase):
    """It is gated and scheduled, or it is a function nobody calls."""

    def test_it_has_a_component_row_of_its_own(self):
        from core.platform_control import DEFAULT_COMPONENTS
        keys = {c["key"] for c in DEFAULT_COMPONENTS}
        self.assertIn("pipeline_campaign_watch", keys)

    def test_the_gate_is_the_component_it_declares(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "tasks.py").read_text(
            encoding="utf-8")
        self.assertIn('@guarded_task("pipeline_campaign_watch")', src)

    def test_it_is_on_the_beat_schedule(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "config" / "celery.py").read_text(
            encoding="utf-8")
        self.assertIn("bot_program.tasks.watch_evidence_chain", src)

    def test_the_command_and_the_watchdog_read_one_implementation(self):
        """A command and a watchdog that disagreed about whether the chain
        was cold would be the worst possible pair: the page says fine and the
        alert never comes, or the reverse, and neither can be trusted."""
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        cmd = (base / "bot_program" / "management" / "commands"
               / "paper_readiness.py").read_text(encoding="utf-8")
        tasks = (base / "bot_program" / "tasks.py").read_text(encoding="utf-8")
        self.assertIn("from bot_program.campaign_readiness import", cmd)
        self.assertIn("from .campaign_readiness import readiness", tasks)


# ── 2026-11-12: a decision is said once, a fault is alarmed ─────────────────

NOTICE_TITLE = "● Live by decision: the paper-campaign checks stand down"
PAPER_ONLY_TITLE = "▲ The paper campaign is no longer paper-only"
STUCK_TITLE = "▲ No paper bot for the rules at the paper stage"
BROKEN_TITLE = "▲ The evidence chain is broken"
COLD_PROMOTION_TITLE = BROKEN_TITLE + " at the promotion pipeline"
CLOSING_LINE = ("A link that is off is a decision; a link with no row was "
                "never set up")
ACTUATOR_WORDS = ("the rule actuator's live mode (a superuser may apply a "
                  "pause or a size cut to a rule; nothing applies by itself)")
NO_PAPER_BOT_LINE = ("No paper bot is on: nothing trades on the simulator "
                     "except entries a live bot's rule sends there")
NOT_A_FAULT = ("So this is not a paper campaign: that is your decision, not "
               "a fault.")
#: A rule born at research (signals/rule_birth) that fires on forex,
#: commodities, indices and crypto, never on a share
#: (backtester.proving.families.session_markets).
BORN_RULE = "po3_london_sweep_short"


def _rule_at(name, stage):
    from signals.models_control import RuleControl
    return RuleControl.objects.create(
        rule_name=name, promotion_stage=stage,
        stage_entered_at=timezone.now())


def _rows(title):
    from alerts.models import Notification
    return Notification.objects.filter(title=title).order_by("pk")


def _titles():
    """Everything the watchdog put in a bell, oldest first (its rows open
    the ops page)."""
    from alerts.models import Notification
    return list(Notification.objects.filter(url="/ops/").order_by("pk")
                .values_list("title", flat=True))


def _first_problem(row):
    return next(i for i in row.data["items"]
                if i.startswith("First problem: "))


def _closed_with_no_result(symbol="WATCHED"):
    from instruments.models import Instrument
    from signals.models import Signal
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock",
                                 "exchange": "NYSE"})
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction="bullish",
        urgency="medium", title="t", description="t", rule_name="r1",
        score=0.8, sub_scores={}, price_at_signal=Decimal("100"),
        is_active=False, realized_r=None)


class _CacheClock:
    """The time a cache backend reads (django.core.cache.backends call
    `time.time()`): the test's own day. A memory kept as a key that expires
    then expires under the test as it does in production. That is how the
    24-hour key missed: the existing test ran the task twice in the same
    second and could not see it."""

    def __init__(self, now):
        self._seconds = now.timestamp()

    def time(self):
        return self._seconds


class _Watch(TestCase):
    """The task itself, one run a day on a clock the test moves: the
    application's clock and the cache's.

    The notifiers are the real ones unless a test patches them: the bell
    rows are what an operator gets, and they are the notice's memory. No
    Telegram token, so nothing leaves the process.
    """

    def setUp(self):
        cache.clear()
        # ...and after: nothing written under a later day's clock may
        # outlive the test that wrote it.
        self.addCleanup(cache.clear)
        _warm_chain()
        self.user = User.objects.create_user(
            "watch_ops", password="x", is_staff=True)
        self.base = timezone.now()
        env = mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""})
        env.start()
        self.addCleanup(env.stop)

    def _run(self, day=0, fresh=("WATCHED",)):
        """The run of `day`. Each `fresh` symbol gets a one-hour-old bar
        first, so a feed that is not the subject of a test never becomes
        one as the days pass."""
        from bot_program.tasks import watch_evidence_chain
        now = self.base + timedelta(days=day)
        clock = _CacheClock(now)
        with mock.patch("django.utils.timezone.now", return_value=now), \
                mock.patch("django.core.cache.backends.base.time", clock), \
                mock.patch("django.core.cache.backends.locmem.time", clock), \
                mock.patch("core.exchange_status.market_status_for",
                           return_value=OPEN):
            for sym in fresh:
                _bar(sym, 1.0)
            return watch_evidence_chain.__wrapped__.__wrapped__()

    def _alarm(self):
        return mock.patch("bot_program.notifications."
                          "notify_evidence_chain_cold", return_value=True)


class ALiveOperatorIsToldOnceTests(_Watch):
    """Trading real money is his decision. It is said once, in words that
    are true of him, and it is never the alarm."""

    def setUp(self):
        super().setUp()
        _config(self.user, ["WATCHED"], name="l1", mode="live")

    def test_an_armed_switch_is_one_notice_and_no_alarm(self):
        _component("actuator_mode_live", True)
        with self._alarm() as alarm:
            out = self._run()
        alarm.assert_not_called()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["campaign"], "live")
        self.assertEqual(out["blockers"], 0)
        self.assertEqual(out["notified"], 0)
        self.assertEqual(out["noticed"], 1)
        row = _rows(NOTICE_TITLE).get()
        self.assertEqual(row.user, self.user)
        self.assertEqual(row.body,
                         "1 bot is armed for real money. " + NOT_A_FAULT)
        self.assertIn("Armed: " + ACTUATOR_WORDS, row.data["items"])
        self.assertTrue(row.data["fingerprint"])
        self.assertEqual(
            _titles(), [NOTICE_TITLE],
            "a live operator with every link ON was sent something else "
            "than the one notice")

    def test_the_next_morning_says_nothing(self):
        _component("actuator_mode_live", True)
        self._run(0)
        out = self._run(1)
        self.assertEqual(out["noticed"], 0)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(_titles(), [NOTICE_TITLE])

    def test_ten_mornings_one_notice(self):
        """The alarm he quoted came back every one to two days, for ever."""
        _component("actuator_mode_live", True)
        _component("share_allocator_mode_live", True)
        for day in range(10):
            self._run(day)
        self.assertEqual(_titles(), [NOTICE_TITLE])

    def test_a_second_armed_switch_is_one_new_notice(self):
        _component("actuator_mode_live", True)
        self._run(0)
        _component("share_allocator_mode_live", True)
        out = self._run(1)
        self.assertEqual(out["noticed"], 1)
        first, second = _rows(NOTICE_TITLE)
        self.assertNotEqual(first.data["fingerprint"],
                            second.data["fingerprint"])
        self.assertIn(
            "Armed: the share allocator's live mode (a share plan may be "
            "applied with the PIN, which re-sizes the pools)",
            second.data["items"])
        self._run(2)
        self.assertEqual(_rows(NOTICE_TITLE).count(), 2)
        # Back to a set already said: the bell remembers it.
        _component("share_allocator_mode_live", False)
        out = self._run(3)
        self.assertEqual(out["noticed"], 0)
        self.assertEqual(_rows(NOTICE_TITLE).count(), 2)

    def test_a_cold_link_still_alarms_and_the_armed_switch_is_not_its_problem(
            self):
        _component("actuator_mode_live", True)
        _component("pipeline_promotion", False)
        out = self._run()
        self.assertEqual(out["cold_links"], ["pipeline_promotion"])
        self.assertEqual(out["blockers"], 1)
        self.assertEqual(out["notified"], 1)
        alarm = _rows(COLD_PROMOTION_TITLE).get()
        self.assertIn("the promotion pipeline is off", _first_problem(alarm))
        self.assertNotIn("actuator", " ".join(alarm.data["items"]).lower())
        self.assertFalse([i for i in alarm.data["items"]
                          if i.startswith("And ")], alarm.data["items"])
        self.assertEqual(sorted(_titles()),
                         sorted([NOTICE_TITLE, COLD_PROMOTION_TITLE]))

    def test_an_emptied_cache_does_not_repeat_the_notice(self):
        """The cache is not its memory: the bell rows are."""
        _component("actuator_mode_live", True)
        self._run(0)
        cache.clear()
        out = self._run(1)
        self.assertEqual(out["noticed"], 0)
        self.assertEqual(_titles(), [NOTICE_TITLE])

    def test_no_armed_switch_and_a_paper_bot_on_is_silence(self):
        _config(self.user, ["PAPERED"], name="p1")
        out = self._run(fresh=("WATCHED", "PAPERED"))
        self.assertEqual(
            (out["campaign"], out["blockers"], out["notified"],
             out["noticed"]), ("live", 0, 0, 0))
        self.assertEqual(_titles(), [])

    def test_no_armed_switch_and_no_paper_bot_is_said_once(self):
        out = self._run(0)
        self.assertEqual(out["noticed"], 1)
        row = _rows(NOTICE_TITLE).get()
        self.assertIn(NO_PAPER_BOT_LINE, row.data["items"])
        self.assertFalse([i for i in row.data["items"]
                          if i.startswith("Armed: ")], row.data["items"])
        self._run(1)
        self.assertEqual(_titles(), [NOTICE_TITLE])

    def test_a_paper_bot_coming_on_is_not_a_second_notice(self):
        """Once per set of armed switches: a paper bot he turns on later
        changes one line, and is no reason to speak again."""
        _component("actuator_mode_live", True)
        self._run(0)
        _config(self.user, ["PAPERED"], name="p1")
        out = self._run(1, fresh=("WATCHED", "PAPERED"))
        self.assertEqual(out["noticed"], 0)
        self.assertEqual(_titles(), [NOTICE_TITLE])

    def test_each_staff_account_is_told_once(self):
        User.objects.create_user("watch_ops2", password="x", is_staff=True)
        _component("actuator_mode_live", True)
        out = self._run(0)
        self.assertEqual(out["noticed"], 2)
        self._run(1)
        self.assertEqual(
            sorted(_rows(NOTICE_TITLE).values_list("user__username",
                                                   flat=True)),
            ["watch_ops", "watch_ops2"])
        # A staff account that arrives later is told once; the others are
        # not told again.
        User.objects.create_user("watch_ops3", password="x", is_staff=True)
        out = self._run(2)
        self.assertEqual(out["noticed"], 1)
        self.assertEqual(_rows(NOTICE_TITLE).count(), 3)

    def test_a_notice_that_cannot_be_said_never_stops_the_alarm(self):
        _component("actuator_mode_live", True)
        _component("pipeline_promotion", False)
        with mock.patch("bot_program.tasks._say_live_by_decision",
                        side_effect=RuntimeError("no bell table")), \
                self.assertLogs("bot_program.tasks", "WARNING") as logs:
            out = self._run()
        self.assertIn("no bell table", "\n".join(logs.output))
        self.assertEqual(out["noticed"], 0)
        self.assertEqual(out["notified"], 1)
        self.assertEqual(_titles(), [COLD_PROMOTION_TITLE])
        # ...and one account whose notice fails does not cost the others
        # theirs.
        User.objects.create_user("watch_ops2", password="x", is_staff=True)
        _component("pipeline_promotion", True)
        from bot_program import notifications
        real = notifications.notify_live_by_decision

        def flaky(user, **kw):
            if user.username == "watch_ops":
                raise RuntimeError("boom")
            return real(user, **kw)

        with mock.patch.object(notifications, "notify_live_by_decision",
                               flaky):
            out = self._run(1)
        self.assertEqual(out["noticed"], 1)
        self.assertEqual(
            list(_rows(NOTICE_TITLE).values_list("user__username",
                                                 flat=True)), ["watch_ops2"])

    def test_nobody_to_tell_is_not_an_error_for_a_notice(self):
        User.objects.filter(is_staff=True).update(is_staff=False)
        _component("actuator_mode_live", True)
        out = self._run()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["noticed"], 0)

    def test_the_hand_lanes_are_named_apart_from_the_bots(self):
        """A TAKE TRADE lane is an enabled config with no symbols, in live
        mode once it is armed. It scans nothing: it is not a bot."""
        _config(self.user, [], name="manual", mode="live",
                asset_class="forex")
        _config(self.user, ["SECOND"], name="l2", mode="live")
        _component("actuator_mode_live", True)
        self._run(fresh=("WATCHED", "SECOND"))
        row = _rows(NOTICE_TITLE).get()
        self.assertEqual(
            row.body, "2 bots are armed for real money; 1 hand lane is in "
                      "live mode. " + NOT_A_FAULT)

    def test_a_live_bot_on_the_demo_world_is_not_called_real_money(self):
        """A live-mode config whose broker row answers the demo world moves
        no real money (the row decides the world, broker_router)."""
        from bot_program.models import EtoroAccount
        EtoroAccount.objects.create(user=self.user, demo=True,
                                    is_primary_for_stocks=True)
        _component("actuator_mode_live", True)
        out = self._run()
        self.assertEqual(out["campaign"], "live")
        row = _rows(NOTICE_TITLE).get()
        self.assertEqual(row.body, "1 bot is in live mode on the demo "
                                   "world. " + NOT_A_FAULT)
        self.assertNotIn("armed for real money",
                         row.body + " ".join(row.data["items"]))

    def test_a_live_bot_on_the_real_world_is_called_real_money(self):
        from bot_program.models import EtoroAccount
        EtoroAccount.objects.create(user=self.user, demo=False,
                                    is_primary_for_stocks=True)
        _component("actuator_mode_live", True)
        self._run()
        self.assertEqual(_rows(NOTICE_TITLE).get().body,
                         "1 bot is armed for real money. " + NOT_A_FAULT)

    def test_the_notice_is_never_drawn_as_a_warning(self):
        from bot_program.notifications import NOTIFY_MARKS
        from dashboard.activity_feed import _alert_marks
        _component("actuator_mode_live", True)
        self._run()
        row = _rows(NOTICE_TITLE).get()
        self.assertEqual(row.data["mark"], NOTIFY_MARKS["live_by_decision"])
        self.assertNotIn(row.data["mark"], _alert_marks()[0])
        self.assertNotIn(row.data["mark"],
                         (NOTIFY_MARKS["evidence_chain_cold"],
                          NOTIFY_MARKS["staff_warning"]))
        self.assertNotIn("▲", row.title)
        self.assertNotIn("⚠", row.title)

    def test_it_moves_nothing(self):
        """Money direction: none. The watchdog reads and notifies: no
        switch, no bot, no rule's stage or weight, no order, whatever it
        found and whatever it said."""
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from core.platform_control import PlatformComponent
        from signals.models import Signal
        from signals.models_control import RuleControl
        _config(self.user, [], name="manual", mode="live",
                asset_class="forex")
        _component("actuator_mode_live", True)
        _component("pipeline_promotion", False)
        _rule_at(BORN_RULE, "paper")
        _closed_with_no_result()

        def state():
            return (
                sorted(PlatformComponent.objects.values_list(
                    "key", "is_enabled")),
                list(AssetBotConfig.objects.order_by("id").values_list(
                    "id", "enabled", "mode", "symbols", "capital",
                    "extras")),
                list(RuleControl.objects.order_by("id").values_list(
                    "rule_name", "status", "promotion_stage",
                    "weight_multiplier", "allocator_weight",
                    "paused_until")),
                list(Signal.objects.order_by("id").values_list(
                    "id", "is_active", "realized_r", "outcome")),
                AssetBotTrade.objects.count())

        before = state()
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        side_effect=AssertionError("a broker was called")):
            for day in range(3):
                out = self._run(day)
        self.assertEqual(out["blockers"], 3)
        self.assertEqual(state(), before)


class APaperCampaignKeepsItsChecksTests(_Watch):
    """With no bot armed for real money the five switches are still a
    fault, under a title and with words that are true of it."""

    def setUp(self):
        super().setUp()
        _config(self.user, ["WATCHED"])           # one paper bot

    def _paper_only(self, out):
        self.assertEqual(out["campaign"], "paper")
        self.assertEqual(out["notified"], 1)
        self.assertEqual(out["noticed"], 0)
        alarm = _rows(PAPER_ONLY_TITLE).get()
        self.assertEqual(
            alarm.body, "A switch that lets real money move is on while "
                        "every enabled bot trades on paper.")
        self.assertEqual(alarm.data["items"],
                         ["First problem: the rule actuator's live mode is "
                          "on (a superuser may apply a pause or a size cut "
                          "to a rule; nothing applies by itself)"])
        self.assertEqual(_titles(), [PAPER_ONLY_TITLE])

    def test_an_armed_switch_is_the_no_longer_paper_only_alarm(self):
        _component("actuator_mode_live", True)
        self._paper_only(self._run())

    def test_a_live_hand_lane_beside_the_paper_bots_changes_nothing(self):
        """The lane does not make the campaign live: every bot is on paper,
        so the alarm stands and nothing is 'live by decision'."""
        _config(self.user, [], name="manual", mode="live")
        _component("actuator_mode_live", True)
        self._paper_only(self._run())

    def test_a_chain_fault_leads_and_the_switches_are_counted_behind_it(
            self):
        _component("actuator_mode_live", True)
        _component("share_allocator_mode_live", True)
        _component("pipeline_promotion", False)
        out = self._run()
        self.assertEqual(out["blockers"], 3)
        alarm = _rows(COLD_PROMOTION_TITLE).get()
        items = alarm.data["items"]
        self.assertIn("the promotion pipeline is off", _first_problem(alarm))
        self.assertIn("And 2 more findings: run the full check", items)
        self.assertEqual(items[-1], CLOSING_LINE)
        self.assertEqual(_titles(), [COLD_PROMOTION_TITLE])

    def test_one_finding_behind_the_first_is_counted_in_the_singular(self):
        _component("actuator_mode_live", True)
        _component("pipeline_promotion", False)
        self._run()
        self.assertIn("And 1 more finding: run the full check",
                      _rows(COLD_PROMOTION_TITLE).get().data["items"])

    def test_a_fault_with_no_link_to_name_says_what_is_true(self):
        """No link is off, so nothing is said about links being off; and
        the ladder has less to grade, not nothing."""
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.filter(name="p1").update(
            symbols=["WATCHED", "NOBARS"])
        out = self._run()
        self.assertEqual(out["cold_links"], [])
        alarm = _rows(BROKEN_TITLE).get()
        self.assertEqual(
            alarm.body, "Evidence is not being produced, so the days "
                        "passing now give the promotion ladder less to "
                        "grade.")
        self.assertIn("NOBARS", _first_problem(alarm))
        self.assertNotIn(CLOSING_LINE, alarm.data["items"])

    def test_the_old_daily_key_is_deleted_and_silences_nothing(self):
        """Before 2026-11-12 a 24-hour cache key was the cooldown. Redis
        keeps it across a deploy."""
        cache.set("campaign_watch:alerted", 1, 24 * 3600)
        _component("pipeline_promotion", False)
        out = self._run()
        self.assertEqual(out["notified"], 1)
        self.assertIsNone(cache.get("campaign_watch:alerted"))


class ItSpeaksWhenSomethingChangesTests(_Watch):
    """Once when a fault appears, at once when the set of faults changes,
    a reminder after seven days while it stands. Never because a day
    passed: the old cooldown was 24 hours on a 24-hour schedule, and a
    standing fault came back every one to two days."""

    def setUp(self):
        super().setUp()
        self.config = _config(self.user, ["WATCHED"])

    def _lists(self, *symbols):
        self.config.symbols = list(symbols)
        self.config.save(update_fields=["symbols"])

    def _stale_from_the_start(self, symbol, hours=30.0):
        with mock.patch("django.utils.timezone.now", return_value=self.base):
            _bar(symbol, hours)

    def test_a_standing_fault_is_said_once_then_once_a_week(self):
        _component("pipeline_promotion", False)
        with self._alarm() as alarm:
            for day in range(7):
                out = self._run(day)
            self.assertEqual(alarm.call_count, 1,
                             "seven daily runs on one standing fault")
            self.assertEqual(out["status"], "cooldown")
            out = self._run(7)
            self.assertEqual(alarm.call_count, 2,
                             "the eighth run is the weekly reminder")
            self.assertEqual(out["notified"], 1)
            for day in range(8, 14):
                self._run(day)
            self.assertEqual(alarm.call_count, 2)
            self._run(14)
            self.assertEqual(alarm.call_count, 3)

    def test_a_fault_whose_words_move_every_day_is_still_one_fault(self):
        """A cold link's sentence never moves, so it proves nothing here.
        A stale bar is a day older every morning and the count of closed
        signals with no result grows: the same two faults, said once."""
        self._lists("WATCHED", "STALE")
        self._stale_from_the_start("STALE")
        seen = []
        real = cr.readiness

        def spy(*args, **kwargs):
            report = real(*args, **kwargs)
            seen.append(report["blockers"])
            return report

        with self._alarm() as alarm, mock.patch.object(cr, "readiness", spy):
            for day in range(7):
                _closed_with_no_result()
                self._run(day)
        self.assertEqual(alarm.call_count, 1)
        self.assertEqual(len(seen), 7)
        bars = {str(b) for day in seen for b in day if "is OPEN" in b}
        results = {str(b) for day in seen for b in day if "NOT ONE" in b}
        self.assertEqual(len(bars), 7,
                         f"the stale bar's sentence did not move: {bars}")
        self.assertEqual(len(results), 7,
                         f"the count's sentence did not move: {results}")
        self.assertEqual(len({tuple(sorted(b.key for b in day))
                              for day in seen}), 1)

    def test_a_second_stale_symbol_speaks_the_day_it_joins(self):
        self._lists("WATCHED", "STALE", "SECOND")
        self._stale_from_the_start("STALE")
        with self._alarm() as alarm:
            for day in range(4):
                self._run(day, fresh=("WATCHED", "SECOND"))
            self.assertEqual(alarm.call_count, 1)
            # SECOND's feed stops: its newest bar is yesterday's.
            self._run(4)
            self.assertEqual(alarm.call_count, 2)
            self._run(5)
            self.assertEqual(alarm.call_count, 2)

    def test_a_second_fault_speaks_the_day_it_appears(self):
        _component("pipeline_promotion", False)
        with self._alarm() as alarm:
            for day in range(3):
                self._run(day)
            self.assertEqual(alarm.call_count, 1)
            _component("pipeline_signals", False)
            out = self._run(3)
            self.assertEqual(alarm.call_count, 2,
                             "a new fault waited behind a cooldown")
            self.assertEqual(out["notified"], 1)
            self.assertEqual(alarm.call_args.kwargs["cold"],
                             ["pipeline_signals", "pipeline_promotion"])
            self._run(4)
            self.assertEqual(alarm.call_count, 2)

    def test_a_link_going_from_off_to_no_row_is_another_fault(self):
        """Off is a decision, no row is an omission: two different fixes."""
        from core.platform_control import PlatformComponent
        _component("pipeline_promotion", False)
        with self._alarm() as alarm:
            self._run(0)
            PlatformComponent.objects.filter(
                key="pipeline_promotion").delete()
            self._run(1)
        self.assertEqual(alarm.call_count, 2)

    def test_the_reminder_counts_from_the_last_time_it_spoke(self):
        _component("pipeline_promotion", False)
        with self._alarm() as alarm:
            self._run(0)
            _component("pipeline_signals", False)
            self._run(3)                    # the set changed: said again
            for day in range(4, 10):
                self._run(day)              # six quiet days after day 3
            self.assertEqual(alarm.call_count, 2)
            self._run(10)                   # seven days after day 3
            self.assertEqual(alarm.call_count, 3)

    def test_a_repaired_chain_forgets_and_a_new_fault_speaks_at_once(self):
        _component("pipeline_promotion", False)
        with self._alarm() as alarm:
            self._run(0)
            _component("pipeline_promotion", True)
            out = self._run(1)
            self.assertEqual(out["status"], "ok")
            _component("pipeline_promotion", False)
            self._run(2)
        self.assertEqual(alarm.call_count, 2)

    def test_an_emptied_cache_repeats_one_alarm_at_most(self):
        _component("pipeline_promotion", False)
        with self._alarm() as alarm:
            self._run(0)
            cache.clear()
            self._run(1)
            self._run(2)
            self._run(3)
        self.assertEqual(alarm.call_count, 2)

    def test_an_alarm_nobody_received_is_not_remembered_as_said(self):
        """Told to nobody (a muted feed, a notifier that failed): the next
        run tries again instead of sitting out a week."""
        _component("pipeline_promotion", False)
        with mock.patch("bot_program.notifications."
                        "notify_evidence_chain_cold",
                        side_effect=[False, True]) as alarm:
            out = self._run(0)
            self.assertEqual(out["notified"], 0)
            out = self._run(1)
            self.assertEqual(out["notified"], 1)
            self._run(2)
        self.assertEqual(alarm.call_count, 2)


class TheRuleWithNowhereToTradeTests(_Watch):
    """The one paper check a live operator keeps. A rule born at research
    that reaches the paper stage votes on a paper bot only, never on a live
    one (signals/rule_birth). With no paper bot that lists a market it
    fires on, it can earn no paper fill and the ladder stops at paper."""

    def setUp(self):
        super().setUp()
        _config(self.user, ["WATCHED"], name="l1", mode="live")
        _component("actuator_mode_live", True)      # said, never alarmed

    def _stuck(self, out):
        self.assertEqual(out["blockers"], 1)
        self.assertEqual(out["notified"], 1)
        alarm = _rows(STUCK_TITLE).get()
        self.assertIn("po3 london sweep short", _first_problem(alarm))
        self.assertNotIn(CLOSING_LINE, alarm.data["items"])
        self.assertEqual(sorted(_titles()),
                         sorted([NOTICE_TITLE, STUCK_TITLE]))

    def test_at_the_paper_stage_with_no_paper_bot_it_is_named(self):
        _rule_at(BORN_RULE, "paper")
        self._stuck(self._run())

    def test_a_paper_bot_on_a_market_it_fires_on_is_silence(self):
        _rule_at(BORN_RULE, "paper")
        _bar("EURUSD", 1.0, asset_class="forex", exchange="FOREX")
        _config(self.user, ["EURUSD"], name="p_fx", asset_class="forex")
        out = self._run(fresh=("WATCHED", "EURUSD"))
        self.assertEqual(out["blockers"], 0)
        self.assertEqual(_titles(), [NOTICE_TITLE])

    def test_a_paper_bot_of_another_class_does_not_silence_it(self):
        """A paper stock bot beside a rule that never fires on a share:
        the rule can still earn no paper fill."""
        _rule_at(BORN_RULE, "paper")
        _config(self.user, ["AAPL"], name="p_stock")
        self._stuck(self._run(fresh=("WATCHED", "AAPL")))

    def test_a_paper_hand_lane_does_not_silence_it(self):
        _rule_at(BORN_RULE, "paper")
        _config(self.user, [], name="manual", asset_class="forex")
        self._stuck(self._run())

    def test_a_fork_of_a_born_rule_is_named_too(self):
        _rule_at(BORN_RULE + "_evolved_v2", "paper")
        out = self._run()
        self.assertEqual(out["blockers"], 1)
        self.assertIn("po3 london sweep short evolved v2",
                      _first_problem(_rows(STUCK_TITLE).get()))

    def test_still_at_research_is_silence(self):
        _rule_at(BORN_RULE, "research")
        _rule_at("death_cross", "research")
        out = self._run()
        self.assertEqual(out["blockers"], 0)
        self.assertEqual(out["notified"], 0)
        self.assertEqual(_titles(), [NOTICE_TITLE])

    def test_no_row_at_all_is_silence(self):
        out = self._run()
        self.assertEqual(out["blockers"], 0)
        self.assertEqual(_titles(), [NOTICE_TITLE])

    def test_at_a_live_stage_is_silence(self):
        """Promoted past paper it votes on the live bots."""
        _rule_at(BORN_RULE, "live_small")
        _rule_at("death_cross", "live_full")
        out = self._run()
        self.assertEqual(out["blockers"], 0)

    def test_a_rule_that_was_not_born_at_research_is_not_its_business(self):
        """Any other rule at the paper stage trades on a live bot too: its
        entries go to the simulator there (rule_actuator.stage_policy)."""
        _rule_at("golden_cross", "paper")
        out = self._run()
        self.assertEqual(out["blockers"], 0)

    def test_it_is_said_once_and_again_when_another_rule_joins(self):
        _rule_at(BORN_RULE, "paper")
        with self._alarm() as alarm:
            for day in range(3):
                self._run(day)
            self.assertEqual(alarm.call_count, 1)
            _rule_at("death_cross", "paper")
            self._run(3)
            self.assertEqual(alarm.call_count, 2)
            self._run(4)
            self.assertEqual(alarm.call_count, 2)

    def test_the_reader_makes_one_read_and_names_only_the_paper_stage(self):
        from signals import rule_birth
        _rule_at(BORN_RULE, "paper")
        _rule_at("death_cross_evolved_v3", "paper")
        _rule_at("rsi_bear_divergence", "research")
        _rule_at("bull_trap_swing_high", "live_small")
        _rule_at("range_breakdown_short", "live_full")
        _rule_at("golden_cross", "paper")           # not born at research
        with mock.patch.object(rule_birth, "_born_rows",
                               wraps=rule_birth._born_rows) as read:
            self.assertEqual(rule_birth.at_paper_stage(),
                             ["death_cross_evolved_v3", BORN_RULE])
        read.assert_called_once()

    def test_the_reader_names_no_rule_it_could_not_read(self):
        """voteless() fails closed by returning EVERY born name. That is
        right for a vote and wrong for an alarm: a failed read would name
        rules that sit at a live stage."""
        from signals import rule_birth
        _rule_at(BORN_RULE, "paper")
        with mock.patch.object(rule_birth, "_born_rows",
                               side_effect=RuntimeError("no such table")), \
                self.assertLogs("signals.rule_birth", "WARNING") as logs:
            self.assertEqual(rule_birth.at_paper_stage(), [])
            out = self._run()
        self.assertIn("no such table", "\n".join(logs.output))
        self.assertEqual(out["blockers"], 0)
        self.assertEqual(_rows(STUCK_TITLE).count(), 0)


class ALiveFleetWithEveryLinkOnTests(_Watch):
    """A live operation of the kind the false alarm was reported from
    (2026-11-11), in synthetic rows: the master switch and the four links
    ON; the meta-allocator, the share allocator and the capital desk in
    live mode; the rule actuator's live mode and the automatic de-risk off;
    26 enabled live configs of which 4 are hand lanes that scan nothing; 2
    enabled paper hand lanes and no paper bot.

    On main that state is "The evidence chain is broken" every morning the
    24-hour key has expired, for ever. It is one notice, then silence day
    after day, and still the alarm on the morning a link goes OFF, loses
    its row, or a bar feed stops."""

    MARKETS = (("EURUSD", "forex", "FOREX"), ("BTCUSD", "crypto", "CRYPTO"),
               ("AAPL", "stock", "NASDAQ"), ("XAUUSD", "commodity", "COMEX"))
    SYMBOLS = tuple(m[0] for m in MARKETS)
    ARMED = ("meta_allocator_mode_live", "share_allocator_mode_live",
             "capital_desk_mode_live")
    SAID = [
        "Armed: the meta-allocator's live mode (a superuser may apply rule "
        "weights, 0.1x to 3x, to future entries)",
        "Armed: the share allocator's live mode (a share plan may be applied "
        "with the PIN, which re-sizes the pools)",
        "Armed: the capital desk's live mode (the bots obey the desk's plan: "
        "displaced entries are skipped and sizes cut)",
        NO_PAPER_BOT_LINE + " and trades taken by hand on a paper lane",
        "Still watched every day: the master switch, the indicators, the "
        "signals, the bots, the promotion ladder, the bar feeds and the "
        "graded outcomes",
    ]

    def setUp(self):
        super().setUp()
        # actuator_mode_live and share_allocator_auto_derisk stay off
        # (_warm_chain); the three others are in live mode.
        for key in self.ARMED:
            _component(key, True)
        for symbol, asset_class, exchange in self.MARKETS:
            _bar(symbol, 1.0, asset_class=asset_class, exchange=exchange)
        for i in range(22):                       # 22 bots that scan
            symbol, asset_class, _exchange = self.MARKETS[i % 4]
            _config(self.user, [symbol], name=f"bot{i + 1:02d}", mode="live",
                    asset_class=asset_class)
        for _symbol, asset_class, _exchange in self.MARKETS:
            _config(self.user, [], name="manual", mode="live",
                    asset_class=asset_class)      # 4 live hand lanes
        for asset_class in ("index", "etf"):      # 2 paper hand lanes
            _config(self.user, [], name="manual", asset_class=asset_class)

    def _morning(self, day, stale=()):
        """The run of `day`; the feeds of `stale` wrote nothing since the
        day before."""
        return self._run(day, fresh=tuple(s for s in self.SYMBOLS
                                          if s not in stale))

    def _quiet(self, out, status="ok", blockers=0):
        self.assertEqual(
            (out["campaign"], out["status"], out["blockers"],
             out["notified"], out["noticed"]),
            ("live", status, blockers, 0, 0))

    def test_the_fleet_is_the_one_described(self):
        from bot_program.models import AssetBotConfig
        on = AssetBotConfig.objects.filter(enabled=True)
        live = on.filter(mode="live")
        self.assertEqual(live.count(), 26)
        self.assertEqual(live.filter(name="manual", symbols=[]).count(), 4)
        self.assertEqual(
            list(on.filter(mode="paper").values_list("name", "symbols")),
            [("manual", [])] * 2)
        with mock.patch("core.exchange_status.market_status_for",
                        return_value=OPEN):
            report = cr.readiness()
        self.assertEqual(report["campaign"], "live")
        self.assertEqual(report["armed"], list(self.ARMED))
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["cold_links"], [])
        self.assertEqual(
            report["fleet"],
            {"live_bots": 22, "demo_bots": 0, "hand_lanes": 4,
             "paper_bots": 0, "paper_lanes": 2})

    def test_live_by_decision_is_said_once_then_silence_day_after_day(self):
        outs = [self._morning(day) for day in range(10)]
        cache.clear()                             # Redis flushed on day 10
        outs += [self._morning(day) for day in range(10, 30)]
        self.assertEqual(
            _titles(), [NOTICE_TITLE],
            "thirty mornings of a live operator with every link ON")
        self.assertEqual(
            (outs[0]["campaign"], outs[0]["status"], outs[0]["blockers"],
             outs[0]["notified"], outs[0]["noticed"]),
            ("live", "ok", 0, 0, 1))
        for out in outs[1:]:
            self._quiet(out)
        row = _rows(NOTICE_TITLE).get()
        self.assertEqual(
            row.body, "22 bots are armed for real money; 4 hand lanes are in "
                      "live mode. " + NOT_A_FAULT)
        self.assertEqual(row.data["items"], self.SAID)
        said = (row.body + " ".join(row.data["items"])).lower()
        self.assertNotIn("actuator", said)
        self.assertNotIn("de-risk", said)
        self.assertNotIn("broken", said)

    def test_a_link_going_off_alarms_that_morning(self):
        for day in range(5):
            self._morning(day)
        _component("pipeline_signals", False)
        out = self._morning(5)
        self.assertEqual(out["cold_links"], ["pipeline_signals"])
        self.assertEqual((out["blockers"], out["notified"], out["noticed"]),
                         (1, 1, 0))
        title = BROKEN_TITLE + " at the signal pipeline"
        alarm = _rows(title).get()
        self.assertIn("the signal pipeline is off", _first_problem(alarm))
        self.assertEqual(alarm.data["items"][-1], CLOSING_LINE)
        # One fault: the switches he armed are no finding behind it.
        self.assertFalse([i for i in alarm.data["items"]
                          if i.startswith("And ")], alarm.data["items"])
        self.assertEqual(_titles(), [NOTICE_TITLE, title])
        # It stands: quiet the next mornings. Back ON: forgotten, and no
        # second notice.
        self._quiet(self._morning(6), "cooldown", 1)
        _component("pipeline_signals", True)
        self._quiet(self._morning(7))
        self.assertEqual(_titles(), [NOTICE_TITLE, title])

    def test_a_link_with_no_row_alarms_that_morning(self):
        from core.platform_control import PlatformComponent
        for day in range(5):
            self._morning(day)
        PlatformComponent.objects.filter(key="pipeline_promotion").delete()
        out = self._morning(5)
        self.assertEqual(out["cold_links"], ["pipeline_promotion"])
        self.assertEqual((out["blockers"], out["notified"], out["noticed"]),
                         (1, 1, 0))
        alarm = _rows(COLD_PROMOTION_TITLE).get()
        self.assertIn("no row", _first_problem(alarm).lower())
        self.assertEqual(alarm.data["items"][-1], CLOSING_LINE)
        self.assertEqual(_titles(), [NOTICE_TITLE, COLD_PROMOTION_TITLE])
        self._quiet(self._morning(6), "cooldown", 1)

    def test_a_feed_going_stale_alarms_that_morning(self):
        for day in range(5):
            self._morning(day)
        # EURUSD's feed stops: on day 5 its newest bar is the day before's.
        out = self._morning(5, stale=("EURUSD",))
        self.assertEqual(out["cold_links"], [])
        self.assertEqual((out["blockers"], out["notified"], out["noticed"]),
                         (1, 1, 0))
        alarm = _rows(BROKEN_TITLE).get()
        self.assertEqual(
            alarm.body, "Evidence is not being produced, so the days passing "
                        "now give the promotion ladder less to grade.")
        problem = _first_problem(alarm)
        self.assertIn("EURUSD", problem)
        for symbol in ("BTCUSD", "AAPL", "XAUUSD"):
            self.assertNotIn(symbol, problem)
        self.assertNotIn(CLOSING_LINE, alarm.data["items"])
        # The same dead feed, a day older every morning: said once.
        for day in range(6, 10):
            self._quiet(self._morning(day, stale=("EURUSD",)), "cooldown", 1)
        self.assertEqual(_titles(), [NOTICE_TITLE, BROKEN_TITLE])
        # A second feed stops: said that morning.
        out = self._morning(10, stale=("EURUSD", "XAUUSD"))
        self.assertEqual(out["notified"], 1)
        self.assertEqual(_titles(),
                         [NOTICE_TITLE, BROKEN_TITLE, BROKEN_TITLE])
        # Both feeds back: the chain is whole, and nothing more is said.
        self._quiet(self._morning(11))
        self._quiet(self._morning(12))
        self.assertEqual(_rows(NOTICE_TITLE).count(), 1)


class TheWordsOnTheSwitchTests(SimpleTestCase):
    """What /ops/ says the watchdog and its command do. The switch promised
    "one notification when a link goes cold" while a standing blocker came
    back every one to two days."""

    def test_the_switch_says_what_the_watchdog_now_does(self):
        from core.platform_control import DEFAULT_COMPONENTS
        row = next(c for c in DEFAULT_COMPONENTS
                   if c["key"] == "pipeline_campaign_watch")
        self.assertEqual(
            row["description"],
            "Daily read-only check that the evidence chain (bars -> "
            "indicators -> signals -> fills -> outcomes -> ladder) is "
            "complete. Speaks once when a link is off, missing or starved, "
            "again only when that changes, weekly while it lasts. Live "
            "trading by decision is said once, never alarmed. Writes "
            "nothing.")
        self.assertLessEqual(
            len(row["description"]), 300,
            "Postgres enforces the column; an overlong description once "
            "failed seed_components on deploy")
        self.assertEqual(row["name"], "Evidence Chain Watchdog")
        self.assertEqual(row["category"], "pipeline")

    def test_it_is_still_off_on_arrival_and_takes_no_pin(self):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES)
        row = next(c for c in DEFAULT_COMPONENTS
                   if c["key"] == "pipeline_campaign_watch")
        self.assertFalse(row.get("is_enabled", False))
        self.assertNotIn("pipeline_campaign_watch", LIVE_MONEY_SWITCHES)

    def test_the_command_is_said_to_name_a_live_operation(self):
        from core import ops_commands
        entry = next(e for e in ops_commands.COMMANDS
                     if e["name"] == "paper_readiness")
        self.assertIn("live operation", entry["purpose"])
        self.assertTrue(entry["read_only"])

    def test_the_reminder_is_a_week_and_the_daily_key_is_gone(self):
        from bot_program import tasks
        self.assertEqual(tasks.CHAIN_REMIND_AFTER, timedelta(days=7))
        self.assertFalse(hasattr(tasks, "CHAIN_COLD_ALERT_COOLDOWN"))

    def test_the_memory_reads_keys_never_sentences(self):
        from bot_program.tasks import _chain_fingerprint as fp
        stale = cr.Finding(("bars_stopped", "NYSE", ("EURUSD",)),
                           "a 4h bar up to 30.0h old")
        older = cr.Finding(("bars_stopped", "NYSE", ("EURUSD",)),
                           "a 4h bar up to 54.0h old")
        joined = cr.Finding(("bars_stopped", "NYSE", ("BTCUSD", "EURUSD")),
                            "a 4h bar up to 54.0h old")
        link = cr.Finding(("link", "pipeline_promotion", "off"), "off")
        self.assertEqual(fp([stale]), fp([older]))
        self.assertNotEqual(fp([older]), fp([joined]))
        self.assertEqual(fp([link, stale]), fp([older, link]))
        self.assertNotEqual(fp([link, stale]), fp([stale]))
        self.assertNotEqual(fp([link]), fp([]))
        # A sentence with no key is one fixed key: it may hide a change,
        # it cannot bring the daily alarm back.
        self.assertEqual(fp(["30.0h old"]), fp(["54.0h old"]))

    def test_the_memory_of_another_shape_or_day_was_not_said(self):
        from datetime import date

        from bot_program.tasks import _chain_already_said as said
        today = date(2026, 3, 9)
        mine = {"fp": "abc", "day": "2026-03-02"}
        self.assertFalse(said(mine, "abc", today))          # seven days on
        self.assertTrue(said(mine, "abc", date(2026, 3, 8)))
        self.assertTrue(said(mine, "abc", date(2026, 3, 2)))
        self.assertFalse(said(mine, "other", date(2026, 3, 3)))
        self.assertFalse(said(mine, "abc", date(2026, 3, 1)))   # a day ahead
        for broken in (None, 1, "abc", {}, {"fp": "abc"},
                       {"fp": "abc", "day": "yesterday"}):
            self.assertFalse(said(broken, "abc", today), broken)
