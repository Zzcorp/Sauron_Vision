"""The briefing wears its own clothes — page, row, and card.

The strategist writes **emphasis** the page printed as literal
asterisks; the notification dressed as a generic bot event; the dwell
card showed a text stub while posture, ideas and cost sat unrendered.
briefing_md escapes EVERYTHING first — it runs on LLM output, so the
one thing it must never do is pass markup through.

Run with:  python manage.py test tests.test_briefing_style
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase


def _briefing(**kw):
    from brain.briefing_models import StrategistBriefing
    defaults = dict(
        outlook_md=("**Your brain is wrong** and your book is "
                    "concentrated.\n\nDiscount the `dead tape` narrative."),
        posture="defensive",
        posture_rationale="Cut structure, not signals.",
        watchlist=[{"kind": "concentration", "ref": "EUR net delta",
                    "what_to_watch": "Cap it as one line item"}],
        ideas=[{"summary": "Stop trusting the random-walk read.",
                "confidence": 0.52, "hypothesis_kind": "regime_holds",
                "horizon_hours": 24}],
        model_used="claude-opus-5", tokens_in=22034, tokens_out=3141,
        cost_usd=Decimal("0.18870"),
    )
    defaults.update(kw)
    return StrategistBriefing.objects.create(**defaults)


class BriefingMdTests(TestCase):
    def _md(self, text):
        from core.templatetags.sauron_tags import briefing_md
        return str(briefing_md(text))

    def test_bold_and_code_render_and_asterisks_do_not(self):
        html = self._md("**loud** and `quiet`")
        self.assertIn("<strong>loud</strong>", html)
        self.assertIn("<code>quiet</code>", html)
        self.assertNotIn("**", html)

    def test_llm_markup_is_escaped_never_executed(self):
        """The filter runs on model output — one permissive pass and a
        crafted briefing is a script tag on the operator's dashboard."""
        html = self._md('<script>alert(1)</script> **<b>x</b>**')
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<strong>&lt;b&gt;x&lt;/b&gt;</strong>", html)

    def test_the_first_paragraph_is_the_lead(self):
        html = self._md("Lead paragraph.\n\nSecond paragraph.")
        self.assertIn('class="brf-p brf-lead">Lead paragraph.', html)
        self.assertIn('class="brf-p">Second paragraph.', html)

    def test_a_bold_span_cannot_straddle_a_paragraph_break(self):
        """Inline passes run per paragraph: a ** pair whose members sat
        in different paragraphs shipped an unbalanced <strong> via
        mark_safe, and the browser's recovery bolded both fragments."""
        html = self._md("**A.\n\nB.** C.")
        for para in html.split("</p>"):
            self.assertEqual(para.count("<strong>"),
                             para.count("</strong>"), para)

    def test_empty_prose_renders_nothing(self):
        self.assertEqual(self._md(""), "")
        self.assertEqual(self._md(None), "")


class BriefingPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("brf_u",
                                                         password="x")
        self.client.force_login(self.user)

    def test_the_outlook_renders_styled_not_raw(self):
        _briefing()
        body = self.client.get("/briefing/").content.decode()
        self.assertIn("<strong>Your brain is wrong</strong>", body)
        self.assertIn("brf-lead", body)
        self.assertNotIn("**Your brain is wrong**", body)

    def test_the_card_wears_its_posture(self):
        _briefing(posture="defensive")
        body = self.client.get("/briefing/").content.decode()
        self.assertIn("brf-card brf-defensive", body)

    def test_watchlist_and_ideas_wear_the_new_chrome(self):
        _briefing()
        body = self.client.get("/briefing/").content.decode()
        self.assertIn("brf-wl-kind", body)
        self.assertIn("what to watch", body)
        self.assertIn("brf-idea", body)
        self.assertIn("CONF 0.52", body)
        self.assertIn("brf-chip--graded", body)
        self.assertIn("24H", body)
        self.assertIn("22034 IN / 3141 OUT", body)


class BriefingNotificationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("brf_n",
                                                         password="x")
        from alerts.models import UserNotificationPrefs
        prefs, _ = UserNotificationPrefs.objects.get_or_create(
            user=self.user)
        prefs.receive_strategist_briefing = True
        prefs.save()

    def test_the_row_is_a_briefing_with_its_facts_aboard(self):
        from alerts.models import Notification
        from bot_program.notifications import (
            notify_strategist_briefing_to_all)
        b = _briefing()
        out = notify_strategist_briefing_to_all(b)
        self.assertEqual(out["n_delivered"], 1)
        n = Notification.objects.get(user=self.user)
        self.assertEqual(n.notification_type, "briefing")
        self.assertIn(f"?id={b.pk}", n.url)
        labels = [it["label"] for it in n.data["items"]]
        self.assertIn("IDEA 1", labels)
        self.assertIn("WATCHLIST", labels)
        self.assertIn("COST", labels)
        self.assertEqual(n.data["briefing"]["posture"], "defensive")
        # The bell body is plain text on every channel — the strategist's
        # ** markers come off before the 800-char truncation.
        self.assertNotIn("**", n.body)
        self.assertIn("Your brain is wrong", n.body)

    def test_the_bell_row_and_card_know_the_new_clothes(self):
        """Source pins: the CSS tones ni-briefing and the posture chip,
        and the card builder reads the briefing payload."""
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        css = (base / "static" / "css" / "sauron.css").read_text(
            encoding="utf-8")
        self.assertIn(".notif-item.ni-briefing", css)
        self.assertIn(".nf-pop-chip--defensive", css)
        self.assertIn(".brf-card.brf-defensive", css)
        js = (base / "static" / "js" / "sv-notif-card.js").read_text(
            encoding="utf-8")
        self.assertIn("payloadOf(row).briefing", js)
        self.assertIn("nf-pop-chip nf-pop-chip--", js)

    def test_the_inbox_dresses_the_row(self):
        from bot_program.notifications import (
            notify_strategist_briefing_to_all)
        notify_strategist_briefing_to_all(_briefing())
        self.client.force_login(self.user)
        body = self.client.get("/notifications/").content.decode()
        self.assertIn("ni-briefing", body)
