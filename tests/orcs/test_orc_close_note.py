"""THE ORC IN THE CLOSE DIALOG (spec §9.2, O1d): the Orc's note beside the
early-close warning. Information only: the last word stays the
operator's.

Pinned here: the note's place and words; the preview is otherwise exactly
what it was (the PIN rule, the exit, the R); preview_close itself and the
close are untouched; a note that cannot be read costs the preview
nothing.

Run with:  python manage.py test tests.orcs.test_orc_close_note
"""
import inspect
import json
import pathlib
import re
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from tests.orcs.helpers import _config, _on, _row, born

ORC_RE = re.compile(r"\borcs?\b", re.I)


class TheCloseNoteTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        _on()
        self.user = get_user_model().objects.create_user("orc_close",
                                                         password="x")
        self.client.force_login(self.user)
        inst, _ = Instrument.objects.get_or_create(
            symbol="BTCUSD", defaults={"name": "BTCUSD",
                                       "asset_class": "crypto"})
        LiveQuote.objects.update_or_create(
            instrument=inst, defaults={"last": Decimal("101"),
                                       "source": "binance_public"})
        self.cfg = _config(self.user)
        self.row = _row(self.cfg, meta={"broker": "paper"})
        self.orc = born(self, self.row)

    def preview(self, pk=None):
        r = self.client.post(f"/positions/{pk or self.row.pk}/close/preview/",
                             data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        return r.json()

    def test_the_note_beside_the_early_close_warning(self):
        out = self.preview()
        self.assertIn("early_close", out)
        note = out["orc"]
        self.assertEqual(set(note), {"label", "t", "page"})
        self.assertEqual(note["label"], f"Orc #{self.row.pk}")
        self.assertTrue(note["t"].startswith("L0 · Snaga, watching: no plan "
                                             "yet."), note["t"])
        self.assertTrue(note["t"].endswith("Information only: the choice is "
                                           "yours."))
        base = (pathlib.Path(settings.BASE_DIR) / "templates" /
                "base.html").read_text(encoding="utf-8")
        block = base.split("'/close/preview/'", 1)[1].split(
            "SV.overlay.confirm({", 1)[0]
        self.assertIn("if (p.orc && p.orc.label && p.orc.t) facts.push(", block)
        # a row with no Orc carries no key at all
        plain = _row(self.cfg, symbol="BTCUSD")
        self.assertNotIn("orc", self.preview(plain.pk))

    def test_the_operators_thesis_is_never_shown_as_a_fact(self):
        """Beside an irreversible close, his own opinion is never labelled
        a code-verified fact."""
        from bot_program.orcs import journal
        journal.append(self.orc, "thesis", "Your thesis: up only.",
                       author="operator", body={"thesis": {
                           "source": "operator", "text": "up only."}})
        t = self.preview()["orc"]["t"]
        self.assertNotIn("Your thesis", t)
        self.assertNotRegex(t, r"Last fact \S+ UTC: Your")
        self.assertIn("Thesis: yours", t)
        self.assertIn("Last fact ", t)

    def test_the_note_changes_nothing_the_close_does(self):
        on = self.preview()
        _on(False)
        off = self.preview()
        self.assertNotIn("orc", off)
        on.pop("orc")
        self.assertEqual(json.dumps(on, sort_keys=True),
                         json.dumps(off, sort_keys=True))
        for key in ("requires_pin", "exit", "r", "venue", "early_close"):
            if key in off:
                self.assertEqual(on[key], off[key], key)

    def test_preview_close_itself_is_untouched(self):
        from bot_program import manual_close
        from dashboard import views_close
        for fn in (manual_close.preview_close, manual_close.execute_close,
                   views_close.close_position_execute,
                   views_close.close_all_preview):
            self.assertIsNone(ORC_RE.search(inspect.getsource(fn)),
                              fn.__name__)

    def test_a_failing_note_never_costs_the_preview(self):
        with patch("bot_program.orcs.notes.close_note_for",
                   side_effect=RuntimeError("boom")), \
                self.assertLogs("dashboard.views_close", level="WARNING"):
            out = self.preview()
        self.assertNotIn("orc", out)
        self.assertIn("early_close", out)
        with patch.dict("sys.modules", {"bot_program.orcs.notes": None}), \
                self.assertLogs("dashboard.views_close", level="WARNING"):
            self.assertNotIn("orc", self.preview())
