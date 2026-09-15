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
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
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


def _config(user, symbols, name="p1", mode="paper"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, mode=mode,
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
