"""T15, EVERY SENTENCE O2a MAKES FALSE IS REWRITTEN, AND SAYS SO WITH THE
MINDS ON AND OFF (the O2 spec A.62, A.3, A.4, N6, K-P16-P18; §1.1.7 T15;
2026-11-05).

The minds arrive OFF behind the PIN and the Orcs line at 0, so every new
text must be true with both OFF and with both ON.

- the slot (notes.slot): the born and active states; the comparison with
  the care ghost for the O arm in mode `real` and in would mode; the next
  wake, its words read from `minds` as its caller read it once per page
  (O1's "no model" words only while the minds are off); the rung as the
  card says it (a model's rung in tier words, or no model for a code
  answer, O1's legacy words read as no model); the three newest intents
  from the card, with no query; for_rows still two queries
- the render's words: the wake headline ends in its status words, the
  card's intellect carries no O1 rung
- the statuses (A.3) and their words (A.4), the codes, `pre_o2` for O1's
  stored reason, every status within 12 characters (P18)
- the dossier's dashes (PS3, PS5, PS9, PS10, PS12)
- Telegram (surfaces.py): the model calls today, the question, the
  switch-off answer and the help line
- the pages (dashboard/views_orcs.py and its templates): no intents, the
  seats' note, the wakes table's status and rung, the intents with the
  officer's verdict, the refusals, "Graded in shadow", the list's title
  and its staff line with the line off and on; /ai-models/'s Orcs card
  and the day's Orc calls from the ledger; the council band
- every new sentence that names an Orc is registered (N6); no Orc verb;
  the slot carries no money or model key
- the budget's own words: the operator turns the Orcs line on (U-C4)

Run with:  python manage.py test tests.orcs.test_orc_o2a_words
"""
import inspect
import json
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from tests.orcs.helpers import (_config, _on, _row, _switch, _user,
                                _wake_card, born, tracks_of)
from tests.orcs.helpers_o2 import MindTestCase, fake_answer, minds_on
from tests.orcs.test_orc_o2a_call import MindFixture, answer

UTC = dt_tz.utc
ORC_WORD = re.compile(r"\b(Orc|Orcs|Captain|Captains)\b")
VERB = re.compile(r"Orc\w*\s+(decided|closed|trimmed|tightened|added|moved|"
                  r"exited)")
MONEY_KEYS = {"cost_usd", "tokens_in", "tokens_out", "model_used", "model",
              "r_money", "spend", "spend_today_usd", "ai_cost_usd",
              "net_edge_money", "pnl", "balance", "equity", "est_usd"}
#: A.4's table: one sentence per status.
STATUS_TABLE = {
    "recorded": "recorded: its dossier is being written",
    "quiet": "nothing new: a code reading",
    "pending": "waiting for its model call",
    "running": "a model is reading it",
    "done": "answered in shadow",
    "refused": "the answer was refused by the validator",
    "failed": "the model call failed",
    "late": "answered after the position closed: kept, applied to nothing",
    "stale": "not answered in time: the care holds",
    "merged": "merged into a newer wake",
}
#: Three intents as the settle writes them on the card (A.41).
CARD_INTENTS = [
    {"kind_t": "proposed in shadow: tighten to S1h-L1 (99.00)",
     "mode": "shadow", "status_t": "applied to the shadow arm"},
    {"kind_t": "proposed in shadow: exit at P1h-H1 (103.00)",
     "mode": "refused", "status_t": "would be refused"},
    {"kind_t": "proposed in shadow: trim at RN-1 (102.00)",
     "mode": "shadow", "status_t": "queued for the shadow arm"},
]


def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _strings(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _strings(v, out)
    elif isinstance(obj, str):
        out.append(obj)
    return out


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text)
            if s.strip()]


class _Words(MindTestCase):
    """One paper Orc, the `orcs` switch ON; the minds as each test sets
    them."""

    def setUp(self):
        _on()
        self.user = _user(f"o2a_words_{type(self).__name__.lower()[:16]}")
        self.cfg = _config(self.user)
        self.row = _row(self.cfg, meta={"broker": "paper"})
        self.orc = born(self, self.row)
        self.row.refresh_from_db()

    def slot(self, **kw):
        from bot_program.orcs import notes
        self.orc.refresh_from_db()
        return notes.slot(self.orc, trade=self.row,
                          tracks=list(tracks_of(self.orc).values()), **kw)

    def card(self, **extra):
        from bot_program.orcs.models import Orc
        self.orc.refresh_from_db()
        card = dict(self.orc.card or {})
        card.update(extra)
        Orc.objects.filter(pk=self.orc.pk).update(card=card)
        self.orc.refresh_from_db()


# ── the slot ─────────────────────────────────────────────────────────────

class TheSlotWordsTests(_Words):

    def test_the_born_and_active_states_are_true_on_and_off(self):
        from bot_program.orcs.models import Orc
        for minds in (True, False, None):
            with self.subTest(minds=minds):
                self.assertEqual(
                    self.slot(minds=minds)["state_t"],
                    "Watching: a journal written by code; no model has read "
                    "it yet.")
        Orc.objects.filter(pk=self.orc.pk).update(state="active")
        for minds in (True, False, None):
            with self.subTest(minds=minds):
                self.assertEqual(
                    self.slot(minds=minds)["state_t"],
                    "Active: its wakes are read in shadow when the minds are "
                    "on; nothing it decides is applied.")

    def test_the_comparison_names_the_proposals_by_the_arms_mode(self):
        from bot_program.orcs.models import OrcTrack
        OrcTrack.objects.filter(orc=self.orc, arm="care").update(
            open=False, exit_r=0.5)
        OrcTrack.objects.filter(orc=self.orc, arm="orc_shadow").update(
            open=False, exit_r=-0.25)
        real = self.slot()["care_compare"]["t"]
        self.assertEqual(real, "The position -0.25R and the care ghost "
                               "+0.50R so far; none of the Orc's proposals "
                               "has been applied.")
        o = OrcTrack.objects.get(orc=self.orc, arm="orc_shadow")
        OrcTrack.objects.filter(pk=o.pk).update(
            state={**(o.state or {}), "mode": "would"})
        would = self.slot()["care_compare"]["t"]
        self.assertEqual(would, "In shadow, the Orc's proposals -0.25R and "
                                "the care ghost +0.50R so far; none was "
                                "applied to the position.")
        from bot_program.orcs import notes
        for text in (real, would):
            self.assertTrue(notes.is_reserved(text), text)
        self.assertNotIn("has taken no step", real + would)

    def test_the_next_wake_reads_the_minds_its_caller_read(self):
        from bot_program.orcs import notes
        from bot_program.orcs.models import Orc
        friday = datetime(2026, 10, 23, 22, 5, tzinfo=UTC)
        Orc.objects.filter(pk=self.orc.pk).update(next_wake_due=friday)
        self.orc.refresh_from_db()
        now = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
        later = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)

        def said(minds, at=now):
            return notes.slot(self.orc, now=at, minds=minds)["next_wake_t"]
        self.assertEqual(said(True), "Next wake 22:05 UTC.")
        self.assertEqual(said(None), "Next wake 22:05 UTC.",
                         "unread, it says what is true either way")
        self.assertEqual(said(False), "Next wake 22:05 UTC: detected and "
                                      "recorded only, no model.")
        self.assertEqual(said(True, later),
                         "Next wake overdue since Fri 23 Oct 22:05 UTC.")
        self.assertEqual(said(False, later),
                         "Next wake overdue since Fri 23 Oct 22:05 UTC: "
                         "detected and recorded only, no model.")
        Orc.objects.filter(pk=self.orc.pk).update(next_wake_due=None)
        self.orc.refresh_from_db()
        for minds in (True, False, None):
            self.assertEqual(said(minds),
                             "No wake scheduled: no model is called.")

    def test_the_rung_is_the_cards_and_no_model_for_a_code_answer(self):
        from bot_program.orcs.constants import RUNG_NONE
        _wake_card(self.orc)
        self.assertEqual(self.slot()["intellect"]["rung_t"], RUNG_NONE,
                         "O1's stored words read as no model")
        self.assertEqual(RUNG_NONE, "No model (code only)")
        it = dict(self.orc.card["intellect"])
        self.card(intellect={**it, "rung_t": "r0 · balanced tier, low "
                                             "effort", "late": True})
        got = self.slot()["intellect"]
        self.assertEqual(got["rung_t"], "r0 · balanced tier, low effort")
        self.assertTrue(got["late"])
        self.card(intellect={**it, "rung_t": RUNG_NONE})
        self.assertEqual(self.slot()["intellect"]["rung_t"], RUNG_NONE)
        # never a word the code did not write: anything else is no model
        self.card(intellect={**it, "rung_t": "claude-x via the API"})
        self.assertEqual(self.slot()["intellect"]["rung_t"], RUNG_NONE)

    def test_the_intents_come_from_the_card_with_no_query(self):
        from bot_program.orcs import notes
        from bot_program.orcs.models import Orc
        self.assertEqual(self.slot()["intents"], [])
        self.card(intents=CARD_INTENTS + ["not an intent"])
        orc = Orc.objects.select_related("seat").get(pk=self.orc.pk)
        tracks = list(tracks_of(orc).values())
        with self.assertNumQueries(0):
            got = notes.slot(orc, trade=self.row, tracks=tracks)
        self.assertEqual(got["intents"], CARD_INTENTS)
        for it in got["intents"]:
            self.assertIn(it["mode"], ("shadow", "refused"))
            self.assertTrue(it["kind_t"].startswith("proposed in shadow: "))

    def test_for_rows_stays_at_two_queries_with_the_cards_intents(self):
        from bot_program.orcs import notes
        self.card(intents=CARD_INTENTS)
        with self.assertNumQueries(2):
            got = notes.for_rows([self.row.pk], user=self.user, minds=True)
        sl = got[f"bot:{self.row.pk}"]
        self.assertEqual(sl["intents"], CARD_INTENTS)

    def test_the_slot_carries_no_money_or_model_key_and_no_orc_verb(self):
        from bot_program.orcs.models import Orc
        _wake_card(self.orc)
        it = dict(self.orc.card["intellect"])
        self.card(intents=CARD_INTENTS, intellect={
            **it, "rung_t": "r0 · balanced tier, low effort"})
        Orc.objects.filter(pk=self.orc.pk).update(
            state="active", llm_wakes_today=4,
            spend_today_usd=Decimal("1.25"))
        for minds in (True, False):
            sl = self.slot(minds=minds)
            self.assertFalse(_keys(sl) & MONEY_KEYS, _keys(sl) & MONEY_KEYS)
            text = json.dumps(sl, ensure_ascii=False)
            for word in ("$", "1.25", "claude", "sonnet", "opus", "haiku"):
                self.assertNotIn(word, text.lower() if word.isalpha()
                                 else text)
            for t in _strings(sl):
                self.assertIsNone(VERB.search(t), t)

    def test_the_line_and_the_close_note_say_a_plan_once_there_is_one(self):
        from bot_program.orcs import notes
        from bot_program.orcs.models import Orc
        sl = self.slot()
        self.assertIn(" · no plan yet · ", notes.line(sl) + " · ")
        self.assertIn(": no plan yet.", notes.close_note(sl)["t"])
        Orc.objects.filter(pk=self.orc.pk).update(plan={
            "v": 1, "clauses": [{"clause": "tighten", "level_id": "S1h-L1",
                                 "price": 99.0, "trigger": "touch"}]})
        sl = self.slot()
        self.assertNotIn("no plan yet", notes.line(sl))
        self.assertIn(" · a plan in shadow", notes.line(sl))
        note = notes.close_note(sl)["t"]
        self.assertNotIn("no plan yet", note)
        self.assertIn(": a plan in shadow. ", note)
        self.assertIn("Plan in shadow: tighten to S1h-L1 (", note)


# ── the render's words and the statuses ─────────────────────────────────

class TheStatusWordsTests(_Words):

    def test_every_status_has_its_sentence_and_fits_twelve(self):
        """A.3, A.4 and P18."""
        from bot_program.orcs import notes
        from bot_program.orcs.constants import STATUS_WORDS, WAKE_STATUSES
        from bot_program.orcs.models import OrcWake
        width = OrcWake._meta.get_field("status").max_length
        self.assertEqual(width, 12)
        self.assertEqual(set(WAKE_STATUSES), set(STATUS_TABLE) | {"skipped"})
        for status in WAKE_STATUSES:
            self.assertLessEqual(len(status), width, status)
        for status, words in STATUS_TABLE.items():
            self.assertEqual(notes.wake_status_t(status), words, status)
        self.assertEqual(STATUS_WORDS["skipped"], "answered by code: {code}")

    def test_a_code_answer_says_its_code_and_o1s_reason_is_pre_o2(self):
        from bot_program.orcs import notes
        from bot_program.orcs.constants import (WAKE_CODE_WORDS, WAKE_CODES,
                                                WAKE_SKIPPED_REASON)
        for code in ("platform_off", "minds_off", "orcs_off", "line_off",
                     "total", "line", "deep_share", "triage", "inflight",
                     "day_cap", "routine_cap", "dollar_cap", "spacing",
                     "dead", "row_closed", "over_budget", "breaker",
                     "render_failed", "paused", "backlog", "authority",
                     "pre_o2"):
            self.assertIn(code, WAKE_CODES, code)
            self.assertEqual(notes.wake_status_t("skipped", code),
                             f"answered by code: {WAKE_CODE_WORDS[code]}")
        self.assertEqual(notes.wake_status_t("skipped", "minds_off"),
                         "answered by code: the minds switch is off")
        self.assertEqual(WAKE_SKIPPED_REASON, "no model before O2")
        self.assertEqual(notes.wake_status_t("skipped", WAKE_SKIPPED_REASON),
                         "answered by code: no model before O2")
        # a failed, late or stale wake says its cause beside its words
        self.assertEqual(notes.wake_status_t("failed", "wall_time"),
                         "the model call failed (the call ran past its wall "
                         "time)")
        self.assertEqual(notes.wake_status_t("stale", "worker_silent"),
                         "not answered in time: the care holds (the worker "
                         "was silent)")
        self.assertEqual(notes.wake_status_t("late", "row_closed"),
                         STATUS_TABLE["late"])
        self.assertEqual(notes.wake_status_t("late", "minds_off"),
                         "answered too late (the minds switch is off): "
                         "kept, applied to nothing")
        self.assertEqual(notes.wake_status_t("refused", "V7"),
                         "the answer was refused by the validator (V7)")

    def test_the_render_says_its_status_and_no_o1_rung(self):
        """A.62: the wake headline ends in its status words; the card's
        intellect carries no model's rung for a code answer, never O1's
        words. With the minds off, the render answers by code itself; on,
        it hands the wake on (scheduler.admit decides)."""
        from bot_program.orcs import wake
        from bot_program.orcs.models import OrcJournal, OrcWake
        at = timezone.now()
        self.orc.refresh_from_db()
        w = wake.record(self.orc, self.row, [{"code": "W1", "key": "W1",
                                              "t": "birth",
                                              "urgent": True}],
                        now=at, price="100.5")
        self.assertEqual((w.status, w.skipped_reason), ("recorded", ""))
        w = OrcWake.objects.select_related("orc", "orc__root_trade").get(
            pk=w.pk)
        wake.render_wake(w)
        w.refresh_from_db()
        self.assertEqual((w.status, w.skipped_reason),
                         ("skipped", "minds_off"))
        entry = OrcJournal.objects.get(orc=self.orc, kind="wake", wake=w)
        self.assertRegex(entry.headline,
                         r"^Wake detected: birth\. Complexity \d+ \(\w+\); "
                         r"the day is \w+\. Answered by code: the minds "
                         r"switch is off\.$")
        self.orc.refresh_from_db()
        it = self.orc.card["intellect"]
        self.assertEqual(it["rung_t"], "No model (code only)")
        self.assertEqual(it["status_t"],
                         "answered by code: the minds switch is off")
        self.assertEqual(it["wake"], w.pk)
        self.assertNotIn("O1", json.dumps(self.orc.card))
        self.assertNotIn("Recorded only", entry.headline)


# ── the dossier's dashes ─────────────────────────────────────────────────

class TheDossierDashesTests(_Words):

    def test_ps3_ps5_ps9_ps10_and_ps12_say_what_stands(self):
        from bot_program.orcs import dossier_position
        self.assertEqual(dossier_position.PS3_WORDS, "no plan yet")
        out = dossier_position.ps(self.orc, self.row, {"now": timezone.now()})
        self.assertEqual(out["ps3"], "no plan yet")
        self.assertEqual(out["ps9"], "— (no temperament drawn)")
        self.assertEqual(out["ps10"], "— (no lesson yet)")
        tail = dossier_position.ps12({})
        self.assertEqual(tail["odds"]["continuation"], "— (not measured)")
        from bot_program.orcs import dossier
        src = inspect.getsource(dossier)
        self.assertIn('"— (no note yet)"', src)
        for module in (dossier, dossier_position):
            words = [n.value for n in __import__("ast").walk(
                __import__("ast").parse(inspect.getsource(module)))
                if isinstance(n, __import__("ast").Constant)
                and isinstance(n.value, str) and n.value.startswith("—")]
            for text in words:
                self.assertNotRegex(text, r"\bO2\b", text)


# ── Telegram ─────────────────────────────────────────────────────────────

class TheTelegramWordsTests(_Words):

    def test_the_model_calls_today_are_the_orcs_own_count(self):
        from bot_program.orcs import surfaces
        from bot_program.orcs.models import Orc
        from bot_program.orcs.scheduler import utc_day
        now = timezone.now()

        def calls():
            self.orc.refresh_from_db()
            reply = surfaces.orc_card(self.orc, now=now)
            return [ln for ln in reply.lines
                    if ln.startswith("Model calls today")]
        self.assertEqual(calls(), ["Model calls today: 0"])
        Orc.objects.filter(pk=self.orc.pk).update(
            llm_wakes_today=3, seen={**self.orc.seen,
                                     "counters_day": utc_day(now)})
        self.assertEqual(calls(), ["Model calls today: 3"])
        # yesterday's counters read 0 until a settle resets them
        Orc.objects.filter(pk=self.orc.pk).update(seen={
            **self.orc.seen, "counters_day": utc_day(now - timedelta(
                days=1))})
        self.assertEqual(calls(), ["Model calls today: 0"])
        self.assertEqual(surfaces.MODEL_CALLS, "Model calls today: {n}")

    def test_the_question_the_switch_off_and_the_help_line(self):
        from bot_program.orcs import notes, surfaces
        self.assertEqual(surfaces.QUESTION_LATER,
                         "Orcs do not answer questions yet. Ask Sauron "
                         "instead: /q <question>.")
        self.assertEqual(surfaces.ORCS_OFF_NONE,
                         "Nothing to switch off: no Orc acts on a position; "
                         "the care holds every position.")
        self.assertEqual(surfaces.HELP_LINES[0],
                         "/orc NUMBER — one Orc: its thesis, journal, plan "
                         "in shadow and the care beside it")
        for text in (surfaces.QUESTION_LATER, surfaces.ORCS_OFF_NONE,
                     surfaces.HELP_LINES[0]):
            self.assertNotIn("no model", text)
            self.assertNotIn("calls a model", text)
            self.assertNotIn("journal only", text)
            for sentence in _sentences(text):
                if ORC_WORD.search(sentence):
                    self.assertTrue(notes.is_reserved(sentence), sentence)

    def test_the_next_wake_on_telegram_reads_the_minds_once(self):
        from unittest.mock import patch

        from bot_program.orcs import surfaces, switches
        from bot_program.orcs.models import Orc
        due = timezone.now() + timedelta(hours=2)
        Orc.objects.filter(pk=self.orc.pk).update(next_wake_due=due)
        self.orc.refresh_from_db()
        with patch.object(switches, "minds_on",
                          wraps=switches.minds_on) as read:
            lines = surfaces.orc_card(self.orc).lines
        self.assertEqual(read.call_count, 1)
        wake_line = [ln for ln in lines if ln.startswith("Next wake")][0]
        self.assertTrue(wake_line.endswith(": detected and recorded only, "
                                           "no model."), wake_line)
        minds_on(self)
        lines = surfaces.orc_card(self.orc).lines
        wake_line = [ln for ln in lines if ln.startswith("Next wake")][0]
        self.assertRegex(wake_line, r"^Next wake .+ UTC\.$")


# ── the pages ────────────────────────────────────────────────────────────

class ThePagesWordsTests(_Words):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client.force_login(self.user)

    def detail(self):
        return self.client.get(reverse("orc_detail", args=[self.row.pk]))

    def test_no_intents_and_the_seats_note(self):
        from bot_program.orcs import notes
        from dashboard import views_orcs
        self.assertEqual(views_orcs.NO_INTENTS,
                         "No intents: this Orc has proposed none.")
        self.assertEqual(views_orcs.SEATS_NOTE,
                         "Δ measures the Orc's shadow arm (its proposals "
                         "applied in shadow, when it has any) against the "
                         "care ghost; no seat holds any power.")
        for text in (views_orcs.NO_INTENTS, views_orcs.SEATS_NOTE):
            self.assertTrue(notes.is_reserved(text), text)
        html = self.detail().content.decode()
        self.assertIn("No intents: this Orc has proposed none.", html)

    def test_the_wakes_table_says_each_status_and_its_rung(self):
        from bot_program.orcs.models import OrcWake
        OrcWake.objects.create(orc=self.orc, reasons=[], dedupe_key="a",
                               status="skipped", skipped_reason="minds_off",
                               kind="routine")
        OrcWake.objects.create(orc=self.orc, reasons=[], dedupe_key="b",
                               status="done", kind="material",
                               started_at=timezone.now(),
                               components={"rung": "r0"})
        OrcWake.objects.create(orc=self.orc, reasons=[], dedupe_key="c",
                               status="merged", kind="routine",
                               components={"merged_into": 1})
        html = self.detail().content.decode()
        block = html.split('id="orc-wakes"', 1)[1].split("</table>", 1)[0]
        self.assertIn(">Wakes detected<", block)
        self.assertNotIn("no model is called", block)
        self.assertIn("<th>Status</th>", block)
        self.assertIn("<th>Rung</th>", block)
        self.assertIn("answered by code: the minds switch is off", block)
        self.assertIn("answered in shadow", block)
        self.assertIn("merged into a newer wake", block)
        self.assertIn(">r0<", block)

    def test_the_intents_with_the_officers_verdict_and_the_refusals(self):
        from bot_program.orcs import journal
        from bot_program.orcs.models import OrcIntent
        OrcIntent.objects.create(
            orc=self.orc, kind="tighten", mode="shadow", status="simulated",
            level={"level_id": "S1h-L1", "kind": "swing", "tf": "1h",
                   "price": 99.0}, level_id="S1h-L1",
            officer={"verdict": "allow", "rule": "", "words": ""},
            rung="r0", s_version="s1", schema_version="d1")
        OrcIntent.objects.create(
            orc=self.orc, kind="trim", mode="refused", status="refused",
            share=0.5, level={"level_id": "P1h-H1", "kind": "pool",
                              "tf": "1h", "price": 103.0},
            level_id="P1h-H1", rule="I12",
            officer={"verdict": "refuse", "rule": "I12",
                     "words": "a trim waits one bar after the last"},
            rung="r0", s_version="s1", schema_version="d1")
        journal.append(self.orc, "refusal",
                       "Refused by the validator (V7): a stop at CARE.",
                       body={"rule": "V7"})
        html = self.detail().content.decode()
        plan = html.split('id="orc-plan"', 1)[1].split('id="orc-journal"',
                                                       1)[0]
        self.assertNotIn("No intents", plan)
        self.assertIn("proposed in shadow: tighten to S1h-L1 (", plan)
        self.assertIn("applied to the shadow arm", plan)
        self.assertIn("the officer would allow it", plan)
        self.assertIn("proposed in shadow: trim at P1h-H1 (", plan)
        self.assertIn("the officer would refuse it (I12: a trim waits one "
                      "bar after the last)", plan)
        self.assertIn("Refused by the validator (V7): a stop at CARE.", plan)

    def test_the_grade_reads_graded_in_shadow(self):
        from bot_program.orcs.models import Orc, OrcGrade
        Orc.objects.filter(pk=self.orc.pk).update(state="dead",
                                                  died_at=timezone.now())
        OrcGrade.objects.create(orc=self.orc, delta_care=0.2,
                                counts_for_seat=True, bar_source="etoro")
        html = self.detail().content.decode()
        self.assertIn("Graded in shadow: ", html)
        self.assertNotIn("no Orc action", html)

    def test_the_list_title_and_the_staff_line_off_and_on(self):
        from ai_agents.models import AgentTask
        staff = get_user_model().objects.create_user(
            "o2a_words_staff", password="x", is_staff=True)
        self.client.force_login(staff)
        html = self.client.get(reverse("orcs_list")).content.decode()
        self.assertIn("ORCS · IN SHADOW", html)
        self.assertNotIn("JOURNALS BY CODE", html)
        self.assertIn("Orcs line: off (ORC_DAILY_BUDGET_USD=0).", html)
        self.assertNotIn("in this release", html)
        minds_on(self)
        AgentTask.objects.create(agent="orc", provider="claude", model="m",
                                 prompt_summary="an Orc call",
                                 cost_usd=Decimal("0.12"))
        html = self.client.get(reverse("orcs_list")).content.decode()
        self.assertIn("Orcs line: $0.12 of $6.00 today · minds switch on · "
                      "1 call today.", html)
        _switch("orcs_minds", False)
        html = self.client.get(reverse("orcs_list")).content.decode()
        self.assertIn("· minds switch off ·", html)

    def test_the_ai_models_card_and_the_days_orc_calls(self):
        from ai_agents.models import AgentTask
        staff = get_user_model().objects.create_user(
            "o2a_words_ai", password="x", is_staff=True)
        self.client.force_login(staff)

        def card():
            html = self.client.get("/ai-models/").content.decode()
            return " ".join(html.split('The Orcs (read-only)', 1)[1]
                            .split("</div>\n</div>", 1)[0].split())
        text = card()
        self.assertIn("read by the Orcs from O2; tier settings never move "
                      "it. Their calls bill the Orcs' own budget line "
                      "(ORC_DAILY_BUDGET_USD, off at 0). O2a answers every "
                      "wake on r0.", text)
        self.assertNotIn("No Orc runs today", text)
        self.assertIn("Orc calls today, from the ledger: 0.", text)
        AgentTask.objects.create(agent="orc", provider="claude", model="m",
                                 prompt_summary="an Orc call",
                                 cost_usd=Decimal("0.05"))
        AgentTask.objects.create(agent="research", provider="claude",
                                 model="m", prompt_summary="not an Orc",
                                 cost_usd=Decimal("0.05"))
        self.assertIn("Orc calls today, from the ledger: 1.", card())


# ── the council band ─────────────────────────────────────────────────────

@override_settings(CACHES={"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "o2a-words-band"}})
class TheCouncilBandWordsTests(_Words):

    def test_the_orcs_sentence_counts_the_living_orcs(self):
        from unittest.mock import patch

        from bot_program.orcs import notes
        from bot_program.orcs.models import Orc
        from dashboard import council_band as B
        traders = {"unread": True}

        def said():
            cache.clear()
            with patch.dict(B.READERS, {"traders": lambda u, n: traders}):
                return B.build_room(self.user)["traders"]["orcs"]
        self.assertEqual(said(), "One Orc watches in shadow; it acts on no "
                                 "position.")
        born(self, _row(self.cfg, symbol="ETHUSD"))
        self.assertEqual(said(), "2 Orcs watch in shadow; none acts on a "
                                 "position.")
        for text in (said(), B.ORCS_ONE, B.ORCS):
            self.assertTrue(notes.is_reserved(text), text)
        Orc.objects.filter(user=self.user).update(state="dead")
        self.assertEqual(said(), "The Orcs are not in the field yet.")
        Orc.objects.filter(user=self.user).update(state="born")
        _on(False)
        self.assertEqual(said(), "The Orcs are not in the field yet.",
                         "the orcs switch OFF: the band as before the Orcs")


# ── registration, and the budget's own words ─────────────────────────────

class TheRegistrationTests(MindTestCase):

    def test_every_new_sentence_that_names_an_orc_is_registered(self):
        from bot_program.orcs import notes, surfaces
        from dashboard import council_band, views_orcs
        texts = [notes.COMPARE.format(orc="+0.40R", care="-0.10R"),
                 notes.COMPARE_WOULD.format(orc="+0.40R", care="-0.10R"),
                 surfaces.QUESTION_LATER, surfaces.ORCS_OFF_NONE,
                 surfaces.HELP_LINES[0], views_orcs.NO_INTENTS,
                 views_orcs.SEATS_NOTE, council_band.ORCS,
                 council_band.ORCS_ONE,
                 council_band.ORCS_N.format(n=7)]
        for text in texts:
            for sentence in _sentences(text):
                if ORC_WORD.search(sentence):
                    self.assertTrue(notes.is_reserved(sentence), sentence)
                self.assertIsNone(VERB.search(sentence), sentence)
        # the old words are gone from the registry and the surfaces
        old = ("the Orc has taken no step", "none calls a model",
               "each keeps a journal only", "proposes nothing until it "
               "reasons", "In this release no Orc takes a step")
        for module in (notes, surfaces, views_orcs):
            src = inspect.getsource(module)
            for words in old:
                self.assertNotIn(words, src, (module.__name__, words))

    def test_the_operator_turns_the_orcs_line_on(self):
        """U-C4: spend.py's comments say who turns the line on; its
        default stays 0."""
        from ai_agents import spend
        src = Path(spend.__file__).read_text(encoding="utf-8")
        self.assertNotIn("O2 turns it on", src)
        self.assertNotIn("until O2 turns", src)
        self.assertEqual(src.count("the operator turns it on"), 2)
        with override_settings(AI_CONFIG={
                k: v for k, v in settings.AI_CONFIG.items()
                if k != "orc_daily_budget_usd"}):
            self.assertEqual(spend.orc_line_cap(), 0.0)


# ── the last fact is code's (N5; 2026-11-05, completing O2a) ─────────────

class TheLastFactIsCodesTests(MindFixture):
    """N5, A.62: the last fact Telegram /orc and the close dialog's note
    print is a line code wrote. A model's own lines on the card (its
    decision, its plan, its proposals, author `orc`; a Captain's and the
    Emperor's from O2c) are its words, never a fact: they are shown under
    their own labels (the latest note, the plan, the intents)."""

    def _said(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import notes, surfaces
        from bot_program.orcs.models import Orc
        orc = Orc.objects.select_related("seat", "root_trade").get(
            pk=self.orc.pk)
        row = AssetBotTrade.objects.get(pk=self.row.pk)
        return (orc, surfaces.orc_card(orc).text(),
                notes.close_note_for(row, user=self.user)["t"])

    def test_a_models_decision_is_never_the_last_fact(self):
        from bot_program.orcs import notes
        base = self.rendered()
        self.think(self.copy_of(base), fake_answer(answer()))
        orc, telegram, note = self._said()
        lines = orc.card["journal"]
        self.assertEqual((lines[-1]["author"], lines[-1]["kind"]),
                         ("orc", "decision"))
        fact = [j for j in lines if j["author"] == "code"][-1]
        said = f"Last fact {notes.hhmm(fact['at'])} UTC: {fact['t']}"
        for name, text in (("telegram", telegram), ("close note", note)):
            self.assertIn(said, text, name)
            self.assertNotRegex(text, r"Last fact \S+ UTC: (?:Decision|Plan "
                                      r"v\d+|Proposed) in shadow", name)
        # two more answers: the card's three lines are the model's alone,
        # and no line is called a fact; its note keeps its own label
        for _ in range(2):
            self.think(self.copy_of(base), fake_answer(answer()))
        orc, telegram, note = self._said()
        self.assertEqual({j["author"] for j in orc.card["journal"]},
                         {"orc"})
        for name, text in (("telegram", telegram), ("close note", note)):
            self.assertNotIn("Last fact", text, name)
            self.assertIn("Holding: the 4h structure intact.", text, name)

    def test_the_last_fact_is_the_newest_line_code_wrote(self):
        from bot_program.orcs import notes
        from bot_program.orcs.constants import AUTHORS, FACT_AUTHORS
        self.assertEqual(set(FACT_AUTHORS), {"code", "care", "reconcile",
                                             "morgul"})
        self.assertTrue(set(FACT_AUTHORS) <= set(AUTHORS))
        for author in FACT_AUTHORS:
            lines = [{"author": "code", "t": "older"},
                     {"author": author, "t": "newest"}]
            self.assertEqual(notes.last_fact(lines)["t"], "newest", author)
        for author in ("orc", "captain", "emperor", "operator", ""):
            lines = [{"author": "care", "t": "the fact"},
                     {"author": author, "t": "not a fact"}]
            self.assertEqual(notes.last_fact(lines)["t"], "the fact",
                             author)
            self.assertIsNone(notes.last_fact(lines[1:]), author)
