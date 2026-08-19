"""The regime node must not announce yesterday's answer as CURRENT.

The knowledge graph showed `regime:portfolio = unknown, confidence 0.00`
labelled CURRENT for a full day, because only the 03:00 consolidation
writes that node — it had frozen the 02:56 reading taken during a probe
blackout, while the 05:56 synthesis had already concluded "trending,
0.78". The brain itself was fine (brain/context.py reads the latest
report, not the node); the graph was the part telling the operator
something false about the present.

Run with:  python manage.py test tests.test_regime_node_freshness
"""
from unittest.mock import patch

from django.test import TestCase


class ReviewRegressionTests(TestCase):
    """Defects the adversarial review caught in the notifications/quotes
    wave. Each one shipped inside code that already had green tests."""

    def test_mark_read_survives_a_crafted_id(self):
        """isdigit() is not int()'s alphabet: '²' passes the guard and then
        raises ValueError — a 500 from a crafted body."""
        from django.contrib.auth.models import User

        from alerts.models import Notification
        u = User.objects.create_user("crafted_u")
        n = Notification.objects.create(
            user=u, notification_type="system", title="t")
        self.client.force_login(u)
        r = self.client.post("/notifications/read-all/",
                             {"ids": ["²", "①", str(n.pk)]},
                             HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)
        n.refresh_from_db()
        self.assertTrue(n.read, "the valid id must still be marked")

    def test_the_card_excludes_the_bottom_chrome_that_exists(self):
        """The engine excluded ".info-bar", a class that exists nowhere —
        so the card could land under the real bottom band."""
        with open("static/js/sv-notif-card.js", encoding="utf-8") as fh:
            src = fh.read()
        # The selector list itself, not the file: the comment explaining
        # the fix necessarily names the class it replaced.
        self.assertIn('".topbar, .ticker-bar, .data-headband, .info-panel-wrap"',
                      src)

    def test_the_card_never_hides_itself_behind_the_panel(self):
        with open("static/js/sv-notif-card.js", encoding="utf-8") as fh:
            src = fh.read()
        # Clamping into the remaining room slid the card back over the
        # panel, where a hovercard loses to a menu and simply vanishes.
        self.assertNotIn("top = Math.min(hr.bottom + GAP, cb.bottom - ph);", src)
        self.assertIn('pop.style.display = "none";', src)

    def test_the_default_sort_does_not_cancel_the_bucket_order(self):
        """The Sort By select is always a successful control, so every
        search submitted sort=symbol and put the alphabet back."""
        import re
        with open("dashboard/views.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIsNotNone(re.search(
            r'movers != "all" and request\.GET\.get\("sort", "symbol"\) == "symbol"',
            src))

    def test_unknown_cells_are_all_em_dashes(self):
        with open("dashboard/views.py", encoding="utf-8") as fh:
            src = fh.read()
        for field in ('"exchange": inst.exchange or', '"sector": inst.sector or',
                      '"country": inst.country or', '"source": q.source if q else'):
            with self.subTest(field=field):
                idx = src.find(field)
                self.assertGreater(idx, 0)
                self.assertIn("—", src[idx:idx + 60])

    def test_the_funding_scan_looks_each_symbol_up_once(self):
        with open("market_data/funding_alerts.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertEqual(
            src.count('Instrument.objects.filter(symbol__iexact=sym)'), 1,
            "one lookup per symbol — iexact cannot use the symbol index")


class RegimeNodeFollowsTheBrainTests(TestCase):
    def _report(self, label, confidence):
        from brain.models import BrainReport
        return BrainReport.objects.create(
            regime_label=label, regime_confidence=confidence,
            portfolio_health_score=0.5, error="")

    def test_consolidating_publishes_the_latest_report(self):
        from brain.consolidation import _consolidate_regime
        from brain.knowledge_models import KnowledgeNode
        self._report("unknown", 0.0)
        _consolidate_regime()
        node = KnowledgeNode.current(KnowledgeNode.KIND_REGIME, "portfolio")
        self.assertEqual(node.payload["label"], "unknown")

        self._report("trending", 0.78)
        _consolidate_regime()
        node = KnowledgeNode.current(KnowledgeNode.KIND_REGIME, "portfolio")
        self.assertEqual(node.payload["label"], "trending",
                         "the node still announced the blackout reading")
        self.assertAlmostEqual(node.payload["confidence"], 0.78, places=2)

    def test_an_unchanged_regime_does_not_spam_versions(self):
        """Publishing on every synthesis is only safe because the upsert
        no-ops when the state has not moved."""
        from brain.consolidation import _consolidate_regime
        from brain.knowledge_models import KnowledgeNode
        self._report("trending", 0.78)
        _consolidate_regime()
        self._report("trending", 0.79)   # within the epsilon
        _consolidate_regime()
        self.assertEqual(
            KnowledgeNode.objects.filter(
                kind=KnowledgeNode.KIND_REGIME, key="portfolio").count(), 1)

    def test_synthesis_publishes_the_regime_without_waiting_for_the_night(self):
        """A successful synthesis hands its regime to the graph on the spot;
        the nightly pass still owns everything else."""
        with open("brain/synthesizer.py", encoding="utf-8") as fh:
            src = fh.read()
        tail = src.split("def synthesize_now")[1]
        self.assertIn("_consolidate_regime()", tail)
        # Fenced: the graph must never be able to fail a synthesis.
        publish_at = tail.find("_consolidate_regime()")
        self.assertIn("try:", tail[max(0, publish_at - 200):publish_at])
