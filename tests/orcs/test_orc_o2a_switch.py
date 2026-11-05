"""T2, ORC MINDS ARRIVES OFF AND ONLY THE PIN TURNS IT ON (the O2 spec N2
for `orcs_minds`, A.1-A.5, A.17, P2, P18; §1.1.7 T2; 2026-11-05).

- N2's list for the minds switch: seeded OFF in a fresh database, a
  System row with A.1's name and description (under 300 characters), in
  ORC_MIND_SWITCHES and BULK_ENABLE_EXEMPT and never in
  LIVE_MONEY_SWITCHES; "all on" leaves it OFF; turning it ON takes the
  trading PIN at /ops/ (none, a wrong one, the shell and the Django admin
  change nothing), turning it OFF takes none; /ops/ shows its PIN field
- the gates as pairs (N7): one request with every gate ON, then the minds
  switch OFF, or the Orcs line at 0, and the render pass answers the wake
  by code (`minds_off`, `line_off`), with none; the platform master
  switched OFF between two claims of one orc_think run leaves the second
  wake `platform_off`, with none; the minds switch OFF closes the waiting
  wakes (`minds_off`), with none
- `orcs` OFF stays byte-identical with the minds ON (hard rule 1,
  extended): the tick is the tick without its hook, no Orc table is
  read, the minds' tasks skip and nothing is written
- A.5: with `orcs` ON and the minds switch OFF, the journal differs from
  O1's by exactly A.5's list: the tick records `recorded`, a rendered
  wake that is not quiet reads `skipped` with `minds_off`, and no
  `budget` entry, evidence fact, plan or proposal is written; a code
  answer writes its `budget` entry only while the minds switch is ON,
  its dollars in the body only
- P18: every status fits OrcWake.status

Run with:  python manage.py test tests.orcs.test_orc_o2a_switch
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.utils import timezone

from tests.orcs.helpers import _switch, born
from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_admission import W4, QueueFixture
from tests.orcs.test_orc_o2a_call import NOW, answer
from tests.orcs.test_orc_tick_off import _Tick

KEY = "orcs_minds"
NAME = "Orc Minds (models in shadow)"
#: A.1's description, word for word.
DESCRIPTION = ("Off (default). With orcs on and the Orcs' budget line set "
               "(ORC_DAILY_BUDGET_USD above 0), a model reads each Orc's "
               "wake in shadow and writes plans and proposals that are "
               "graded. Nothing it decides sends an order or moves a stop. "
               "Turning it on takes the PIN.")
#: Test-only values, never the operator's.
TEST_PIN = "583920"
WRONG_PIN = "104729"
#: A second urgent reason: F6 makes a routine wake on facts a model has
#: just answered quiet, so the second wake of a test is urgent.
W4B = {**W4, "key": "W4:-0.75", "t": "-0.75R reached"}
#: A reason neither urgent nor routine (the book's risk turned hot): F6
#: never quiets it (it reads W2 and W11 only) and the spacing binds it.
W7 = {"code": "W7", "key": "W7:risk:x", "t": "open risk at 80% of its limit",
      "urgent": False}
#: What O1 wrote and A.5 allows beside it with the minds switch OFF.
O1_KINDS = {"birth", "adopt", "fact", "wake", "reading", "drum", "thesis",
            "takeover", "grade", "error"}
EVIDENCE = {"bar", "gap", "level_reached", "expectation"}


def _row_of(key=KEY):
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.get(key=key)


# ── N2: the switch itself ────────────────────────────────────────────────

class TheSwitchShipsOffTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()

    def test_it_is_seeded_off_in_a_fresh_database(self):
        from core.platform_control import DEFAULT_COMPONENTS
        row = _row_of()
        self.assertFalse(row.is_enabled)
        self.assertEqual((row.name, row.category), (NAME, "system"))
        self.assertEqual(row.description, DESCRIPTION)
        self.assertLess(len(row.description), 300)
        entry = [c for c in DEFAULT_COMPONENTS if c["key"] == KEY]
        self.assertEqual(len(entry), 1)
        self.assertNotIn("is_enabled", entry[0], "it arrives OFF")
        self.assertNotIn("enabled", entry[0])
        # beside `orcs`, which keeps its own name and words (K-C1)
        keys = [c["key"] for c in DEFAULT_COMPONENTS]
        self.assertEqual(keys.index(KEY), keys.index("orcs") + 1)
        orcs = DEFAULT_COMPONENTS[keys.index("orcs")]
        self.assertEqual(orcs["name"], "Orcs (journals, no model)")
        self.assertIn("No model, no order, no stop moved.",
                      orcs["description"])
        # an unreadable switch reads OFF
        from bot_program.orcs import switches
        with patch("core.platform_control.is_component_enabled",
                   side_effect=RuntimeError("the table is gone")):
            self.assertFalse(switches.minds_switch_on())

    def test_it_is_exempt_held_back_and_never_live(self):
        from core import switch_pin
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           LIVE_MONEY_SWITCHES,
                                           ORC_MIND_SWITCHES, PIN_SWITCHES)
        self.assertIn(KEY, ORC_MIND_SWITCHES)
        self.assertIn(KEY, BULK_ENABLE_EXEMPT)
        self.assertIn(KEY, PIN_SWITCHES)
        self.assertNotIn(KEY, LIVE_MONEY_SWITCHES)
        self.assertFalse(switch_pin.is_live("orcs"))
        switch_pin.set_category("system", True, via=switch_pin.VIA_ALL_ON)
        self.assertFalse(_row_of().is_enabled, '"all on" never reaches it')
        self.assertTrue(_row_of("orcs").is_enabled,
                        "`orcs` is no PIN switch: all on turns it on")


class OnlyThePinTurnsItOnTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        from portfolio.trader_profile import get_or_create_profile
        cache.clear()
        seed_components()
        self.admin = get_user_model().objects.create_superuser(
            "o2a_minds_admin", "o2a_minds@example.test", "x")
        prof = get_or_create_profile(self.admin)
        prof.set_pin(TEST_PIN)
        prof.save()
        self.client.force_login(self.admin)

    def ops(self, **extra):
        return self.client.post("/admin-dashboard/toggle/",
                                {"key": KEY, "next": "ops", **extra})

    def test_every_door_refuses_on_without_the_pin(self):
        self.ops()
        self.ops(want="on")
        self.ops(want="on", pin="")
        self.ops(want="on", pin=WRONG_PIN)
        self.client.post("/admin-dashboard/toggle/", {"key": KEY})
        self.client.post("/admin-dashboard/system-map/toggle/",
                         {"kind": "component", "key": KEY})
        with self.assertRaises(CommandError) as ctx:
            call_command("component", "on", KEY, stdout=StringIO())
        self.assertIn("/ops/", str(ctx.exception))
        row = _row_of()
        data = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
                "form-0-id": str(row.pk), "form-0-is_enabled": "on",
                "_save": "Save"}
        self.client.post("/admin/core/platformcomponent/", data)
        self.assertFalse(_row_of().is_enabled, "no door armed it")
        from core import switch_pin
        out = switch_pin.set_switch(KEY, True, via=switch_pin.VIA_SHELL)
        self.assertFalse(out.ok)
        self.assertFalse(_row_of().is_enabled)

    def test_the_right_pin_turns_it_on_and_off_takes_none(self):
        from bot_program.audit_models import AuditLogEntry
        self.ops(want="on", pin=TEST_PIN)
        self.assertTrue(_row_of().is_enabled)
        armed = [e for e in AuditLogEntry.objects.filter(kind="switch_armed")
                 if (e.data or {}).get("key") == KEY]
        self.assertEqual(len(armed), 1)
        out = StringIO()
        call_command("component", "off", KEY, stdout=out)
        self.assertIn(f"{KEY}: ON → OFF", out.getvalue())
        self.assertFalse(_row_of().is_enabled)

    def test_ops_shows_its_pin_field_while_off(self):
        import re
        html = self.client.get("/ops/").content.decode()
        forms = re.findall(r'<form method="post" action="/admin-dashboard/'
                           r'toggle/"[^>]*>(.*?)</form>', html, re.S)
        mine = [f for f in forms if f'name="key" value="{KEY}"' in f]
        self.assertEqual(len(mine), 1)
        self.assertIn('name="pin"', mine[0])
        self.assertIn('type="password"', mine[0])
        self.assertIn(NAME, html)


# ── the gates, each a pair (N7) ──────────────────────────────────────────

class TheGatesArePairsTests(QueueFixture):

    def passed(self, reasons=None):
        """A wake the tick recorded and the render pass rendered and
        admitted (A.7), as of now."""
        from bot_program.orcs import wake
        from bot_program.orcs.models import OrcWake
        self.orc.refresh_from_db()
        w = wake.record(self.orc, self.orc.root_trade, list(reasons or [W4]),
                        now=timezone.now(), price="100.5")
        wake.render_queued()
        return OrcWake.objects.get(pk=w.pk)

    def test_the_minds_switch_off_gives_minds_off(self):
        w = self.passed()
        self.assertEqual(w.status, "pending")
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        _switch(KEY, False)
        off = self.passed([W4B])
        self.assertIsNone(self.serve()["wake"])
        self.assert_no_call(code="minds_off", got=off.skipped_reason)
        self.assertEqual(off.status, "skipped")

    def test_the_line_at_zero_gives_line_off(self):
        """P2: the Orcs line at 0 with every switch ON."""
        w = self.passed()
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}):
            off = self.passed([W4B])
            self.assertIsNone(self.serve()["wake"])
        self.assert_no_call(code="line_off", got=off.skipped_reason)
        self.assertEqual(off.status, "skipped")

    def test_the_platform_master_off_between_two_claims_of_one_run(self):
        """A.2: orc_think's guard read the platform master when the run
        began; each claim reads it again."""
        from bot_program.orcs import mind, tasks
        a, b = self.orcs(2)
        first = self.pending(self.rendered(orc=a), timezone.now()
                             - timedelta(minutes=1), orc=a)
        second = self.pending(self.rendered(orc=b), timezone.now(), orc=b)
        real_think = mind.think

        def think(w, **kw):
            out = real_think(w, **kw)
            _switch("platform_master", False)
            return out
        self.use_fake(fake_answer(answer()))
        with patch.object(mind, "think", think):
            out = tasks.orc_think()
        self.assertEqual(out, {"status": "success", "thought": 1,
                               "by_code": 1})
        first.refresh_from_db()
        self.assertEqual(first.status, "done")
        self.assert_one_call()
        second.refresh_from_db()
        self.assert_no_call(code="platform_off", got=second.skipped_reason)

    def test_the_minds_switch_off_closes_what_waits(self):
        from bot_program.orcs import tasks
        from bot_program.orcs.models import OrcJournal
        w = self.passed()
        self.serve(script=fake_answer(answer()))
        self.assert_one_call()
        waiting = self.passed([W4B])
        self.assertEqual(waiting.status, "pending")
        _switch(KEY, False)
        budget = OrcJournal.objects.filter(kind="budget").count()
        self.assertEqual(tasks.orc_think(), {
            "idle": "the minds switch is off; 1 waiting wake(s) answered "
                    "by code"})
        waiting.refresh_from_db()
        self.assert_no_call(code="minds_off", got=waiting.skipped_reason)
        self.assertEqual(OrcJournal.objects.filter(kind="budget").count(),
                         budget, "no budget entry while the switch is OFF")
        self.assertNotEqual(w.pk, waiting.pk)


# ── hard rule 1, extended: `orcs` OFF with the minds ON ──────────────────

class TheOrcsOffStaysByteIdenticalTests(MindTestCase, _Tick):

    def test_orcs_off_with_the_minds_on_is_the_tick_before_the_orcs(self):
        from bot_program.orcs import tasks
        from bot_program.orcs.models import (OrcIntent, OrcJournal,
                                             OrcWake)
        from tests.orcs.helpers import _on
        from tests.orcs.helpers_o2 import minds_on
        _on()
        (a, ra), (b, rb) = self._pair()
        born(self, ra)
        born(self, rb)
        ra.refresh_from_db()
        rb.refresh_from_db()
        minds_on(self)
        _on(False)
        n = (OrcWake.objects.count(), OrcIntent.objects.count(),
             OrcJournal.objects.count())
        out = self._run(a, ra, hooked=False)
        real = self._run(b, rb, hooked=True)
        for run in (out, real):
            run["row"]["metadata"].pop("orc")
            run.pop("sql")
        self.assertEqual(real["orc_sql"], [], "no Orc table read")
        self.assertLessEqual(real.pop("queries") - out.pop("queries"), 1)
        self.assertEqual(out, real)
        for task in (tasks.orc_render_wakes, tasks.orc_think,
                     tasks.orc_minds_watch):
            self.assertEqual(task()["status"], "skipped", task.name)
        self.assertEqual((OrcWake.objects.count(), OrcIntent.objects.count(),
                          OrcJournal.objects.count()), n)


# ── A.5: the journal with the minds switch OFF ───────────────────────────

class TheJournalWithTheMindsOffTests(QueueFixture):

    def control(self):
        """The positive control's run: with every gate ON, one wake
        through the render pass, served by the fake model. The test
        asserts its one request itself (T16 reads the pair in the test's
        own source)."""
        from bot_program.orcs import wake
        self.orc.refresh_from_db()
        wake.record(self.orc, self.orc.root_trade, [W4],
                    now=timezone.now() - timedelta(minutes=30),
                    price="100.5")
        self.assertEqual(wake.render_queued().admitted, 1)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["settle"]["status"], "done")

    def test_the_minds_off_journal_differs_from_o1s_by_a5s_list(self):
        from bot_program.orcs import wake
        from bot_program.orcs.models import (OrcIntent, OrcJournal,
                                             OrcWake)
        self.control()
        self.assert_one_call()
        _switch(KEY, False)
        self.orc.refresh_from_db()
        before = set(OrcJournal.objects.filter(orc=self.orc)
                     .values_list("id", flat=True))
        w = wake.record(self.orc, self.orc.root_trade, [W4B],
                        now=timezone.now(), price="100.5")
        w.refresh_from_db()
        self.assertEqual((w.status, w.skipped_reason), ("recorded", ""),
                         "the tick records `recorded`")
        out = wake.render_queued()
        self.assertEqual((tuple(out), out.admitted), ((1, 0), 0))
        w.refresh_from_db()
        self.assertEqual((w.status, w.skipped_reason),
                         ("skipped", "minds_off"))
        self.assertEqual(w.components["render"], "done")
        new = list(OrcJournal.objects.filter(orc=self.orc)
                   .exclude(id__in=before).order_by("id"))
        kinds = {e.kind for e in new}
        self.assertLessEqual(kinds, O1_KINDS, kinds)
        self.assertNotIn("budget", kinds)
        self.assertFalse([e for e in new if (e.body or {}).get("fk")
                          in EVIDENCE], "no evidence fact")
        [entry] = [e for e in new if e.kind == "wake"]
        self.assertTrue(entry.headline.endswith(
            "Answered by code: the minds switch is off."), entry.headline)
        self.assertEqual(entry.body["status"], "skipped")
        self.orc.refresh_from_db()
        self.assertFalse((self.orc.plan or {}).get("clauses"), "no plan")
        self.assertEqual(OrcIntent.objects.filter(orc=self.orc).count(), 0)
        self.assertFalse(OrcWake.objects.filter(status="pending").exists())
        self.assertNotIn("vctx", w.components, "no validation context")
        self.assertIsNone(self.serve()["wake"])
        self.assert_no_call(code="minds_off", got=w.skipped_reason)

    def test_a_code_answer_is_journaled_only_while_the_switch_is_on(self):
        """A.5: kind `budget`, author code, off the card, its headline
        "Answered by code: {words}." and its dollars in the body only."""
        from bot_program.orcs import wake
        from bot_program.orcs.models import OrcJournal
        self.control()
        self.assert_one_call()

        def answered(reasons):
            self.orc.refresh_from_db()
            w = wake.record(self.orc, self.orc.root_trade, reasons,
                            now=timezone.now(), price="100.5")
            wake.render_queued()
            w.refresh_from_db()
            return w, list(OrcJournal.objects.filter(kind="budget", wake=w))
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}):
            w, [entry] = answered([W4])
        self.assertEqual((w.status, w.skipped_reason), ("skipped",
                                                        "line_off"))
        self.assertEqual(entry.author, "code")
        self.assertEqual(entry.headline, "Answered by code: the Orcs budget "
                                         "line is off "
                                         "(ORC_DAILY_BUDGET_USD=0).")
        self.assertNotIn("$", entry.headline)
        self.orc.refresh_from_db()
        self.assertNotIn(entry.headline,
                         [j["t"] for j in self.orc.card["journal"]],
                         "off the card")
        # a money code keeps the line's numbers in its body, never the
        # headline
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(
            last_wake_at=timezone.now() - timedelta(minutes=2))
        w, [spaced] = answered([W7])
        self.assertEqual(w.skipped_reason, "spacing")
        self.assertNotIn("$", spaced.headline)
        self.hold_usd(2.95)
        w, [held] = answered([W4])
        self.assertEqual(w.skipped_reason, "inflight")
        self.assertIn("line", held.body)
        self.assertNotIn("$", held.headline)
        _switch(KEY, False)
        w, entries = answered([W4])
        self.assertEqual((w.status, w.skipped_reason, entries),
                         ("skipped", "minds_off", []))
        self.assertIsNone(self.serve()["wake"])
        self.assert_no_call(code="minds_off", got=w.skipped_reason)


class TheStatusesFitTests(MindTestCase):

    def test_every_status_fits_the_column(self):
        """P18: each of A.3's statuses is saved whole."""
        from bot_program.orcs.constants import WAKE_STATUSES
        from bot_program.orcs.models import OrcWake
        from tests.orcs.helpers import _config, _on, _row, _user
        self.assertEqual(set(WAKE_STATUSES), {
            "recorded", "quiet", "skipped", "pending", "running", "done",
            "refused", "failed", "late", "stale", "merged"})
        _on()
        user = _user("o2a_switch_fit")
        orc = born(self, _row(_config(user)))
        for n, status in enumerate(WAKE_STATUSES):
            w = OrcWake.objects.create(orc=orc, reasons=[], status=status,
                                       dedupe_key=f"fit{n}")
            w.refresh_from_db()
            self.assertEqual(w.status, status)
        self.assertEqual(NOW.tzinfo is not None, True)
