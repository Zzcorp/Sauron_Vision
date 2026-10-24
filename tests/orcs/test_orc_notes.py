"""THE ORC'S READ API (spec §9.5, §10.2; O1d): bot_program/orcs/notes.py.

Pinned here:
  - the reads cost nothing while the switch is OFF or no row is stamped,
    two queries for the rows whatever their number, one for the bands;
  - the stamp is read inside the package only;
  - the O1 slot's exact keys: no temperament or honor yet, `lineage` and
    never `seat`, no money or spend key at any depth, `mode` on every key
    that describes an outcome, and no Orc verb;
  - L0 · Snaga whatever the seat row says; the risk at the stop the venue
    holds; the care beside the position, in shadow; the predicates' words
    and states; the card's intellect, integrity, army and drums; the day's
    weather per band;
  - the card stays v1 (O1a's journal pin) and gains the operator's thesis;
  - every sentence that names an Orc is reserved;
  - the positions line and the close note.

Run with:  python manage.py test tests.orcs.test_orc_notes
"""
import json
import re
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from tests.orcs.helpers import (_config, _drum_heard, _manual_config,
                                _manual_row, _on, _row, _user, _wake_card,
                                born)

O1_KEYS = {"v", "mode", "id", "label", "state", "state_t", "authority",
           "thesis", "plan_line", "latest_note", "latest_note_at",
           "risk_line", "care_compare", "next_wake_at", "next_wake_t",
           "journal", "intents", "intellect", "lineage", "integrity", "army",
           "drums", "page"}
MONEY_KEYS = {"cost_usd", "tokens_in", "tokens_out", "model_used", "r_money",
              "spend", "spend_today_usd", "ai_cost_usd", "net_edge_money",
              "pnl", "balance", "equity"}
VERB = re.compile(r"Orc\w*\s+(decided|closed|trimmed|tightened|added|moved|"
                  r"exited)")
BY = re.compile(r"(closed|trimmed|tightened|held|decided) by (the|an) Orc")


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


class _Seen(TestCase):

    def setUp(self):
        _on()
        self.user = _user("orc_seen")
        self.cfg = _config(self.user)
        self.row = _row(self.cfg, meta={"broker": "paper"})
        self.orc = born(self, self.row)
        self.row.refresh_from_db()

    def rows(self, ids=None, **kw):
        from bot_program.orcs import notes
        return notes.for_rows(ids or [self.row.pk], user=self.user, **kw)

    def slot(self):
        return self.rows()[f"bot:{self.row.pk}"]


class TheReadsTests(_Seen):

    def test_off_or_no_ids_reads_nothing(self):
        from bot_program.orcs import notes
        with self.assertNumQueries(0):
            self.assertEqual(notes.for_rows([], user=self.user), {})
            self.assertEqual(notes.for_rows(None), {})
            self.assertEqual(notes.for_classes(self.user, []), {})
        _on(False)
        with self.assertNumQueries(1):          # the switch, nothing else
            self.assertEqual(notes.for_trades([self.row], user=self.user), {})
        plain = _row(self.cfg, symbol="ETHUSD")
        with self.assertNumQueries(0):          # no stamp: not even the switch
            self.assertEqual(notes.for_trades([plain], user=self.user), {})
            self.assertIsNone(notes.close_note_for(plain, user=self.user))

    def test_the_stamp_is_read_inside_the_package(self):
        from bot_program.orcs import notes
        plain = _row(self.cfg, symbol="ETHUSD")
        self.assertEqual(notes.stamped([self.row, plain, None]),
                         [self.row.pk])
        with self.assertNumQueries(3):          # switch + legs + arms
            got = notes.for_trades([self.row, plain], user=self.user)
        self.assertEqual(set(got), {self.row.pk})

    def test_for_rows_keys_every_leg_and_scopes_the_user(self):
        from bot_program.orcs.models import OrcLeg
        add = _row(self.cfg, symbol="BTCUSD", qty="0.5")
        OrcLeg.objects.create(orc=self.orc, trade=add, kind="add", seq=2)
        got = self.rows([self.row.pk, add.pk])
        self.assertEqual(set(got), {f"bot:{self.row.pk}", f"bot:{add.pk}"})
        self.assertEqual(got[f"bot:{add.pk}"]["id"], self.orc.pk)
        self.assertEqual(got[f"bot:{add.pk}"]["label"],
                         f"Orc #{self.row.pk}")
        other = _user("orc_seen_b")
        from bot_program.orcs import notes
        self.assertEqual(notes.for_rows([self.row.pk], user=other), {})

    def test_for_rows_costs_two_queries_for_3_and_30_ideas(self):
        from bot_program.orcs import notes
        from tests.orcs.helpers import _paper_cap
        _paper_cap()
        ids = [self.row.pk]
        for i in range(2):
            r = _row(self.cfg, symbol="ETHUSD")
            born(self, r)
            ids.append(r.pk)
        with self.assertNumQueries(2):
            small = notes.for_rows(ids, user=self.user)
        for i in range(27):
            r = _row(self.cfg, symbol="ETHUSD")
            born(self, r)
            ids.append(r.pk)
        with self.assertNumQueries(2):
            big = notes.for_rows(ids, user=self.user)
        self.assertEqual((len(small), len(big)), (3, 30))


class TheSlotTests(_Seen):

    def test_the_o1_slot_shape(self):
        sl = self.slot()
        self.assertEqual(set(sl), O1_KEYS)
        self.assertEqual(sl["v"], 2)
        self.assertEqual(sl["mode"], "shadow")
        self.assertNotIn("temperament", sl)
        self.assertNotIn("honor", sl)
        self.assertNotIn("seat", _keys(sl))
        self.assertEqual(set(sl["lineage"]), {
            "rank", "rank_t", "badge", "earned_level", "white_hand",
            "provisional_t", "venue_t", "probation_t", "scars", "breaches_t",
            "disbanded"})
        self.assertEqual(set(sl["authority"]), {
            "level", "level_t", "commission", "commission_t", "stood_down",
            "care_owned_reason"})
        self.assertEqual(sl["intents"], [])
        self.assertEqual(sl["page"], f"/orcs/{self.row.pk}/")
        self.assertEqual(sl["state_t"],
                         "Watching: a journal written by code, no model.")
        self.assertEqual(sl["plan_line"],
                         "No plan yet: Orcs write plans once they reason.")
        self.assertEqual(sl["lineage"]["rank_t"], "Snaga · n 0")
        self.assertEqual(sl["lineage"]["provisional_t"], "n 0 of 20")
        self.assertEqual(sl["lineage"]["venue_t"], "on paper")
        json.dumps(sl)                          # it travels as JSON

    def test_level_is_l0_snaga_whatever_the_seat_row(self):
        seat = self.orc.seat
        seat.level = 3
        seat.save()
        sl = self.slot()
        self.assertEqual(sl["authority"]["level"], 0)
        self.assertEqual(sl["authority"]["level_t"], "L0 · Snaga")
        self.assertEqual(sl["lineage"]["badge"], "○")
        self.assertEqual(sl["authority"]["commission"], "class")
        self.assertEqual(sl["authority"]["commission_t"],
                         "class: its class seat decides, in shadow")

    def test_risk_line_from_the_stop_the_venue_holds(self):
        from bot_program.orcs import notes
        from bot_program.models import AssetBotTrade
        self.assertAlmostEqual(notes.risk_r(self.row), 1.0)
        self.assertEqual(self.slot()["risk_line"], "risk 1.0R of 2R")
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            stop_loss=Decimal("100"))
        self.row.refresh_from_db()
        self.assertEqual(notes.risk_r(self.row), 0.0)
        self.assertEqual(notes.risk_line(self.row), "risk 0.0R of 2R")
        # the fill's echo: eToro holds no stop (0.0), still in force
        real = _row(self.cfg, symbol="ETHUSD", paper=False, meta={
            "broker": "etoro", "stop_rewritten_by_venue": {
                "sent": 98.0, "held": 0.0}})
        self.assertIsNone(notes.risk_r(real))
        self.assertEqual(notes.risk_line(real),
                         "no stop at the venue: the risk is not capped")
        # a held stop wider than the one sent is the one counted
        wide = _row(self.cfg, symbol="ETHUSD", paper=False, meta={
            "broker": "etoro", "stop_rewritten_by_venue": {
                "sent": 98.0, "held": 97.0}})
        self.assertAlmostEqual(notes.risk_r(wide), 1.5)
        nor = _row(self.cfg, symbol="ETHUSD", stop=None)
        self.assertEqual(notes.risk_line(nor),
                         "no R: the position opened with no stop")
        # a scaled-out row risks its remainder only
        half = _row(self.cfg, symbol="ETHUSD", qty="0.5", meta={
            "scale_out": {"original_qty": "1"}})
        self.assertAlmostEqual(notes.risk_r(half), 0.5)
        # a stop in profit risks 0 (§2.1), never a negative risk
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            stop_loss=Decimal("101"))
        self.row.refresh_from_db()
        self.assertEqual(notes.risk_r(self.row), 0.0)
        self.assertEqual(notes.risk_line(self.row), "risk 0.0R of 2R")

    def test_risk_line_of_a_short(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import notes
        short = _row(self.cfg, symbol="ETHUSD", side="SELL", entry="100",
                     stop="102", target="90")
        self.assertAlmostEqual(notes.risk_r(short), 1.0)
        self.assertEqual(notes.risk_line(short), "risk 1.0R of 2R")
        # its stop moved to the entry, then into profit (below the entry)
        for stop in ("100", "99"):
            AssetBotTrade.objects.filter(pk=short.pk).update(
                stop_loss=Decimal(stop))
            short.refresh_from_db()
            self.assertEqual(notes.risk_r(short), 0.0, stop)
            self.assertEqual(notes.risk_line(short), "risk 0.0R of 2R")
        # a short's stop widened above the first: more than 1R
        AssetBotTrade.objects.filter(pk=short.pk).update(
            stop_loss=Decimal("103"))
        short.refresh_from_db()
        self.assertAlmostEqual(notes.risk_r(short), 1.5)

    def test_a_closed_row_has_no_risk(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import notes
        from bot_program.orcs.models import Orc
        for status in ("CLOSED", "CANCELED", "ERROR"):
            AssetBotTrade.objects.filter(pk=self.row.pk).update(
                status=status, closed_at=timezone.now(),
                exit_price=Decimal("99"))
            self.row.refresh_from_db()
            self.assertIsNone(notes.risk_r(self.row), status)
            self.assertIsNone(notes.risk_line(self.row), status)
        Orc.objects.filter(pk=self.orc.pk).update(state="dead",
                                                  died_at=timezone.now())
        sl = self.slot()
        self.assertIsNone(sl["risk_line"])
        self.assertNotIn("risk", notes.line(sl))
        # a close still pending at the venue still holds a stop
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            status="CLOSE_PENDING")
        self.row.refresh_from_db()
        self.assertEqual(notes.risk_line(self.row), "risk 1.0R of 2R")

    def test_care_compare_is_shadow_and_reads_the_arms(self):
        from bot_program.orcs.models import OrcTrack
        cmp_ = self.slot()["care_compare"]
        self.assertEqual(cmp_["mode"], "shadow")
        self.assertEqual(cmp_["t"],
                         "Not measured yet: the arms have not stepped.")
        OrcTrack.objects.filter(orc=self.orc, arm="care").update(
            open=False, exit_r=0.5)
        OrcTrack.objects.filter(orc=self.orc, arm="orc_shadow").update(
            open=False, exit_r=-0.25)
        cmp_ = self.slot()["care_compare"]
        self.assertEqual((cmp_["orc_r"], cmp_["care_r"]), (-0.25, 0.5))
        self.assertEqual(cmp_["t"], "The position -0.25R and the care ghost "
                                    "+0.50R so far; the Orc has taken no "
                                    "step.")

    def test_next_wake_says_its_day_and_when_it_is_overdue(self):
        from datetime import datetime, timezone as dt_tz

        from bot_program.orcs import notes
        from bot_program.orcs.models import Orc
        friday = datetime(2026, 10, 23, 22, 5, tzinfo=dt_tz.utc)
        Orc.objects.filter(pk=self.orc.pk).update(next_wake_due=friday)
        self.orc.refresh_from_db()
        on_friday = notes.slot(self.orc, now=datetime(
            2026, 10, 23, 20, 0, tzinfo=dt_tz.utc))
        self.assertEqual(on_friday["next_wake_t"],
                         "Next wake 22:05 UTC: detected and recorded only, "
                         "no model.")
        on_thursday = notes.slot(self.orc, now=datetime(
            2026, 10, 22, 20, 0, tzinfo=dt_tz.utc))
        self.assertEqual(on_thursday["next_wake_t"],
                         "Next wake Fri 23 Oct 22:05 UTC: detected and "
                         "recorded only, no model.")
        # the market shut: no tick ran it, and it is not "tonight"
        on_saturday = notes.slot(self.orc, now=datetime(
            2026, 10, 24, 9, 0, tzinfo=dt_tz.utc))
        self.assertEqual(on_saturday["next_wake_t"],
                         "Next wake overdue since Fri 23 Oct 22:05 UTC: "
                         "detected and recorded only, no model.")
        self.assertEqual(on_saturday["next_wake_at"], friday.isoformat())

    def test_care_compare_prices_both_arms_on_the_same_mark(self):
        """§6.1, §2.1: the position (the O arm) and the care ghost on the
        same tick, the closing side of the spread, banked parts counted at
        birth size. No Orc steps in O1, so the two read the same R, after
        a spread and after a paper scale-out alike."""
        from datetime import datetime, timedelta, timezone as dt_tz

        from bot_program.models import AssetBotTrade
        from bot_program.orcs import notes
        from tests.orcs.helpers import _switch, drive, tracks_of
        t0 = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)
        for scale in (False, True):
            _switch("aragorn")
            _switch("aragorn_scale_out", scale)
            row = _row(self.cfg, symbol="ETHUSD")
            AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=t0)
            row.refresh_from_db()
            orc = born(self, row)
            if scale:
                drive(self, self.cfg, row, [(t0 + timedelta(minutes=30),
                                             "102.2")])
                row.refresh_from_db()
                self.assertLess(row.qty, Decimal("1"), "no scale-out")
            drive(self, self.cfg, row, [(t0 + timedelta(minutes=60),
                                         "101.0", "100.9", "101.1")])
            arms = tracks_of(orc)
            cmp_ = notes.compare(list(arms.values()))
            self.assertIsNotNone(cmp_["orc_r"], scale)
            self.assertAlmostEqual(cmp_["orc_r"], cmp_["care_r"], places=9,
                                   msg=(scale, cmp_))
            # the bid, not the tick price: below the care's own r_now
            care_r_now = arms["care"].state.get("r_now")
            if not scale:
                self.assertLess(cmp_["care_r"], float(care_r_now))
            orc_r = notes.r_words(cmp_["orc_r"])
            self.assertEqual(cmp_["t"], f"The position {orc_r} and the care "
                                        f"ghost {orc_r} so far; the Orc has "
                                        f"taken no step.")

    def test_an_adopted_row_reads_its_thesis_as_reconstructed(self):
        from bot_program.orcs import notes
        real = _row(self.cfg, symbol="ETHUSD", paper=False,
                    meta={"broker": "etoro"})
        born(self, real, adopted=True)
        sl = notes.for_rows([real.pk], user=self.user)[f"bot:{real.pk}"]
        th = sl["thesis"]
        self.assertEqual(th["source"], "reconstructed")
        self.assertEqual(th["source_t"], "reconstructed from the row")
        self.assertTrue(th["t"].startswith(notes.RECONSTRUCTED_T), th["t"])
        self.assertIn("Thesis: reconstructed from the row",
                      notes.close_note(sl)["t"])
        # a bot's own entry is the entry's record
        self.assertEqual(self.slot()["thesis"]["source_t"],
                         "the entry's own record")

    def test_invalidation_words_and_states(self):
        from bot_program.orcs import journal, notes
        thesis = dict(self.orc.thesis)
        thesis["invalidation"] = [
            {"kind": "time", "market_h": 96.0, "min_mfe_r": 1.0},
            {"kind": "displaced_bos_against", "tf": "4h"},
            {"kind": "close_beyond", "tf": "4h", "level_id": "L4",
             "level": 99.25, "side": "below"},
            {"kind": "close_beyond", "tf": "4h", "level_id": "L5",
             "level": 101.0, "side": "above"}]
        self.orc.thesis = thesis
        self.orc.save(update_fields=["thesis"])
        self.assertEqual(notes.invalidation_t(self.orc, self.row), [
            "invalidates after 96 market hours without +1R",
            "invalidates on a displaced break against it on the 4h",
            "invalidates on a 4h close below 99.25",
            "invalidates on a 4h close above 101.00"])
        journal.remember(self.orc, predicates={
            "close_beyond:4h:L4": {"state": "met",
                                   "at": "2026-10-22T14:05:00+00:00"},
            "displaced_bos_against:4h:": {"state": "unchecked"},
            "time::": {"state": "unchecked"}})
        self.assertEqual(notes.invalidation_t(self.orc, self.row), [
            "invalidates after 96 market hours without +1R (unchecked: the "
            "care measures no best excursion)",
            "invalidates on a displaced break against it on the 4h "
            "(unchecked: no fresh 4h bars)",
            "invalidates on a 4h close below 99.25 (met 14:05 UTC)",
            "invalidates on a 4h close above 101.00"])

    def test_refresh_keeps_the_v1_journal_and_adds_wake_drum_thesis_keys(self):
        from bot_program.orcs import journal
        _wake_card(self.orc)
        _drum_heard(self.orc, kind="lock", symbol="XAGUSD")
        journal.append(self.orc, "thesis", "Your thesis: gold holds 2,600.",
                       author="operator", body={"thesis": {
                           "source": "operator",
                           "text": "Gold   holds 2,600."}})
        self.orc.refresh_from_db()
        card = self.orc.card
        self.assertEqual(card["v"], 1)
        for j in card["journal"]:
            self.assertEqual(set(j), {"at", "kind", "author", "t"})
        self.assertNotIn("wake", [j["kind"] for j in card["journal"]])
        self.assertEqual(card["thesis_operator"]["t"], "Gold holds 2,600.")
        self.assertEqual(card["drums"][-1]["kind_t"], "a lock")
        self.assertEqual(card["intellect"]["band"], "complex")

    def test_a_card_from_before_o1d_reads_dashes(self):
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(card={})
        sl = self.slot()
        self.assertEqual(set(sl), O1_KEYS)
        self.assertEqual(sl["journal"], [])
        self.assertIsNone(sl["intellect"])
        self.assertIsNone(sl["integrity"])
        self.assertEqual(sl["drums"], [])
        self.assertEqual(sl["next_wake_t"],
                         "No wake scheduled: no model is called.")
        Orc.objects.filter(pk=self.orc.pk).update(card={"v": 1, "journal": [
            "not a dict"], "drums": "nope", "intellect": [1]})
        sl = self.slot()
        self.assertEqual((sl["journal"], sl["drums"], sl["intellect"]),
                         ([], [], None))

    def test_intellect_reads_no_model_and_the_score(self):
        _wake_card(self.orc, score=61.6, band="complex", day="stormy")
        it = self.slot()["intellect"]
        self.assertEqual(it, {"score_v": 62, "score_t": "score 62 · complex",
                              "band": "complex", "day_class": "stormy",
                              "rung_t": "No model (code only)",
                              "escalated": False, "late": False,
                              "at": "2026-10-22T14:05:00+00:00"})
        self.assertNotIn("O1", json.dumps(self.slot()))

    def test_integrity_words(self):
        _wake_card(self.orc, flag="ok")
        self.assertEqual(self.slot()["integrity"], {
            "flag": "ok",
            "t": "The dossier is whole: nothing stale or contradictory."})
        _wake_card(self.orc, flag="stale")
        self.assertEqual(self.slot()["integrity"], {
            "flag": "stale", "t": "Stale: the 4h venue bars are 9 h old."})
        _wake_card(self.orc, flag="contradiction")
        self.assertEqual(self.slot()["integrity"]["t"],
                         "Contradiction: the venue mark and the quote "
                         "differ.")

    def test_army_type_with_the_corsair_overlay(self):
        from bot_program.orcs.army import name_of
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(
            army_type="mercenaries", army_why={"base": "mercenaries"})
        self.assertEqual(self.slot()["army"], {
            "type": "mercenaries", "type_t": name_of("mercenaries"),
            "overlay": "", "overlay_t": ""})
        Orc.objects.filter(pk=self.orc.pk).update(
            army_type="line", army_why={"base": "line", "overlay": "corsairs",
                                        "overlay_why": ["two prints inside "
                                                        "the hold"]})
        army = self.slot()["army"]
        self.assertEqual(army, {"type": "line",
                                "type_t": "Line Orcs · Corsair overlay",
                                "overlay": "corsairs",
                                "overlay_t": "two prints inside the hold"})

    def test_the_drums_heard(self):
        _drum_heard(self.orc, kind="stop_hit", symbol="XAGUSD")
        drums = self.slot()["drums"]
        self.assertEqual(len(drums), 1)
        self.assertEqual(set(drums[0]), {"kind_t", "from_symbol", "at"})
        self.assertEqual((drums[0]["kind_t"], drums[0]["from_symbol"]),
                         ("a stop hit", "XAGUSD"))

    def test_for_classes_one_query_and_no_label(self):
        from bot_program.orcs import notes
        from bot_program.orcs.models import OrcDayBaseline
        from bot_program.orcs.sessions import trading_day
        now = timezone.now()
        OrcDayBaseline.objects.create(
            user=self.user, asset_class="crypto", trading_day=trading_day(now),
            day_class="eventful", score=41.4)
        OrcDayBaseline.objects.create(
            user=self.user, asset_class="forex",
            trading_day=trading_day(now) - timedelta(days=1),
            day_class="stormy", score=70)
        other = _user("orc_seen_c")
        OrcDayBaseline.objects.create(
            user=other, asset_class="crypto", trading_day=trading_day(now),
            day_class="stormy", score=80)
        with self.assertNumQueries(1):
            got = notes.for_classes(self.user, ["crypto", "forex"], now=now)
        self.assertEqual(got, {"crypto": {"day": {
            "class": "eventful", "score_t": "score 41",
            "t": "eventful · score 41"}}})
        self.assertNotIn("label", got["crypto"])

    def test_no_money_or_spend_key_at_any_depth(self):
        from bot_program.orcs.models import Orc
        _wake_card(self.orc)
        _drum_heard(self.orc)
        Orc.objects.filter(pk=self.orc.pk).update(
            spend_today_usd=Decimal("1.5"), r_money=Decimal("250"))
        sl = self.slot()
        self.assertFalse(_keys(sl) & MONEY_KEYS, _keys(sl) & MONEY_KEYS)
        text = json.dumps(sl, ensure_ascii=False)
        for word in ("$", "€", "£", "¥", "250", "balance", "equity"):
            self.assertNotIn(word, text)
        self.assertNotRegex(text, r"\bUSD\b")

    def test_no_orc_verb_and_every_outcome_key_carries_mode(self):
        _wake_card(self.orc)
        _drum_heard(self.orc)
        sl = self.slot()
        self.assertEqual(sl["mode"], "shadow")
        self.assertEqual(sl["care_compare"]["mode"], "shadow")
        for j in sl["journal"]:
            self.assertEqual(j["mode"], "shadow")
        for text in _strings(sl):
            self.assertIsNone(VERB.search(text), text)
            self.assertIsNone(BY.search(text), text)

    def test_every_orc_sentence_is_reserved(self):
        from bot_program.orcs import notes
        _wake_card(self.orc)
        _drum_heard(self.orc)
        sl = self.slot()
        word = re.compile(r"\b(Orc|Orcs|Captain|Captains)\b")
        journal = {j["t"] for j in sl["journal"]}
        for text in _strings(sl):
            if text in journal or not word.search(text):
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", text):
                if word.search(sentence):
                    self.assertTrue(notes.is_reserved(sentence), sentence)
        for name in ("Line Orcs", "Corsairs of Umbar · Corsair overlay",
                     "Orc #12", "No plan yet: Orcs write plans once they "
                                "reason."):
            self.assertTrue(notes.is_reserved(name), name)
        self.assertFalse(notes.is_reserved("The Orc closed it."))


class TheLinesTests(_Seen):

    def test_the_positions_line(self):
        from bot_program.orcs import notes
        sl = self.slot()
        first = (sl["thesis"]["invalidation_t"] or ["no invalidation is "
                                                    "written"])[0]
        self.assertEqual(notes.line(sl),
                         f"Orc #{self.row.pk} · L0 · Snaga, class · {first} "
                         f"· no plan yet · risk 1.0R of 2R")
        d = notes.line_dict(sl)
        self.assertEqual(set(d), {"label", "line", "page", "plan", "compare",
                                  "j1", "j2", "j3"})
        self.assertEqual(d["page"], f"/orcs/{self.row.pk}/")
        self.assertTrue(d["j1"])                 # the birth's lines
        newest = sl["journal"][-1]
        self.assertTrue(d["j1"].endswith(newest["t"]), d["j1"])

    def test_the_close_note(self):
        from bot_program.orcs import notes
        sl = self.slot()
        note = notes.close_note(sl)
        self.assertEqual(note["label"], f"Orc #{self.row.pk}")
        t = note["t"]
        self.assertTrue(t.startswith("L0 · Snaga, watching: no plan yet. "
                                     "Thesis: the entry's own record"), t)
        self.assertIn("Last fact ", t)
        self.assertTrue(t.endswith("Information only: the choice is yours."))
        for word in ("$", "balance", "equity", "account"):
            self.assertNotIn(word, t)

    def test_the_line_and_the_note_carry_the_latest_note(self):
        """§9.2: the line carries the latest note and its time; §9.1/9.2:
        the close note and /orc carry it whole. O1's latest note is the
        deterministic reading of a quiet wake."""
        from datetime import datetime, timezone as dt_tz

        from bot_program.orcs import journal, notes
        from bot_program.orcs.models import Orc
        note = ("Nothing new: +0.4R, care BE at 1.0832, 4h structure "
                "unchanged.")
        Orc.objects.filter(pk=self.orc.pk).update(
            latest_note=note,
            latest_note_at=datetime(2026, 10, 22, 14, 5, tzinfo=dt_tz.utc))
        journal.append(self.orc, "fact", "The care moved its soft stop.",
                       fact=True)
        sl = self.slot()
        line = notes.line(sl)
        self.assertIn(' · "Nothing new: +0.4R, care BE at 1.0832…" '
                      '14:05 · risk 1.0R of 2R', line)
        t = notes.close_note(sl)["t"]
        self.assertIn(f"Latest note 14:05 UTC: {note}", t)
        self.assertRegex(t, r"Last fact \d\d:\d\d UTC: \S*The care moved "
                            r"its soft stop\.")
        # a short note is quoted whole
        Orc.objects.filter(pk=self.orc.pk).update(latest_note="Quiet.")
        self.assertIn(' · "Quiet." 14:05 · ', notes.line(self.slot()))

    def test_the_operators_thesis_is_never_the_last_fact(self):
        from bot_program.orcs import journal, notes
        journal.append(self.orc, "thesis", "Your thesis: up only.",
                       author="operator", body={"thesis": {
                           "source": "operator", "text": "up only."}})
        sl = self.slot()
        self.assertEqual(sl["journal"][-1]["author"], "operator")
        t = notes.close_note(sl)["t"]
        self.assertNotIn("Your thesis", t)
        self.assertIn("Last fact ", t)
        self.assertEqual(notes.last_fact(sl["journal"]), sl["journal"][-2])
        self.assertIsNone(notes.last_fact([{"author": "operator",
                                            "t": "mine"}]))
        self.assertIsNone(notes.last_fact(None))

    def test_a_manual_idea_says_advise(self):
        mcfg = _manual_config(self.user)
        row = _manual_row(mcfg, symbol="ETHUSD")
        orc = born(self, row)
        from bot_program.orcs import notes
        sl = notes.for_rows([row.pk], user=self.user)[f"bot:{row.pk}"]
        self.assertEqual(orc.commission, "advise")
        self.assertEqual(sl["authority"]["commission_t"],
                         "advise: journal and notes only; the care runs as "
                         "it always has")
