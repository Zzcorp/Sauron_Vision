"""The Lore, part 4: the pages, the review, the switches (2026-10-14).

Run with:  python manage.py test tests.test_lore_pages
"""
import html
import re
from types import SimpleNamespace

from django.contrib.auth.models import Permission, User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from tests.test_lore_library import make_entry, review, staff, switch
from tests.test_telegram_house_style import FRENCH

PAGE_RE = re.compile(r'<div id="lore-page">(.*)</div><!-- /lore-page -->', re.S)


def lore_text(body: str) -> str:
    """The library page's own words (the shell around it is every page's)."""
    m = PAGE_RE.search(body)
    assert m, "the lore page wrapper is missing"
    inner = re.sub(r"<style\b.*?</style>", " ", m.group(1), flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", inner))


def assert_english(test, body):
    low = " " + re.sub(r"[^a-zà-ÿ]+", " ", lore_text(body).lower()) + " "
    for word in FRENCH:
        test.assertNotIn(word, low, f"French {word!r} on the page")


class PageAccessTests(TestCase):

    def setUp(self):
        self.entry = make_entry()
        self.staff = staff("pages_staff")
        self.plain = User.objects.create_user("plain_pages", "p@x.io", "x")

    def test_anonymous_and_non_staff_are_redirected(self):
        for url in ("/lore/", "/lore/example-trend-rule/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/admin/login/", r["Location"])
        self.client.force_login(self.plain)
        for url in ("/lore/", "/lore/example-trend-rule/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
        r = self.client.post("/lore/example-trend-rule/review/", {"action": "retire"})
        self.assertEqual(r.status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, "draft")

    def test_staff_get_the_pages_private_and_never_stored(self):
        self.client.force_login(self.staff)
        for url in ("/lore/", "/lore/example-trend-rule/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertIn("private", r["Cache-Control"])
            self.assertIn("no-store", r["Cache-Control"])
            assert_english(self, r.content.decode())
        r = self.client.get("/lore/no-such-entry/")
        self.assertEqual(r.status_code, 404)

    def test_the_index_shows_the_entry_and_its_state(self):
        self.client.force_login(self.staff)
        body = self.client.get("/lore/").content.decode()
        self.assertIn("Example trend rule", body)
        self.assertIn("Draft: no agent reads it yet.", body)
        self.assertIn("1 draft waits for review.", body)
        self.assertIn("No agent has read the library yet.", body)
        self.assertIn("Reference data. Nothing here can change a rule, a gate, "
                      "a size, a limit or an order.", body)
        self.assertIn("search summary only", body)

    def test_search_and_filters_on_the_index(self):
        self.client.force_login(self.staff)
        make_entry(slug="example-carry", title="Example carry trade",
                   tags=["carry"], asset_classes=["forex"],
                   regimes_works=["risk_on"], regimes_breaks=["risk_off"],
                   kind="concept", horizons=["months"])
        body = self.client.get("/lore/?q=carry").content.decode()
        self.assertIn("Example carry trade", body)
        self.assertNotIn("Example trend rule", body)
        body = self.client.get("/lore/?regime=risk_off").content.decode()
        self.assertIn("Example carry trade", body)
        self.assertNotIn("Example trend rule", body)
        body = self.client.get("/lore/?kind=strategy").content.decode()
        self.assertIn("Example trend rule", body)
        self.assertNotIn("Example carry trade", body)
        body = self.client.get("/lore/?tag=carry").content.decode()
        self.assertIn("Example carry trade", body)
        self.assertNotIn("Example trend rule", body)
        body = self.client.get("/lore/?q=zebra+quantum").content.decode()
        self.assertIn("Nothing matches. Try fewer words or clear a filter.", body)
        body = self.client.get("/lore/?status=reviewed").content.decode()
        self.assertIn("Nothing matches.", body)

    def test_the_empty_library_says_how_to_load_it(self):
        from lore.models import LoreEntry
        LoreEntry.objects.all().delete()
        self.client.force_login(self.staff)
        body = self.client.get("/lore/").content.decode()
        self.assertIn("The library is empty. Load the catalogue with manage.py "
                      "lore import", body)

    def test_the_entry_page_shows_sources_dates_badges_and_the_review_state(self):
        self.client.force_login(self.staff)
        body = self.client.get("/lore/example-trend-rule/").content.decode()
        self.assertIn('[S1] Example Author. "A stand-in paper". Paper, 2012-05.', body)
        self.assertIn("Search summary only", body)
        self.assertIn("https://example.org/paper", body)
        self.assertIn("Draft: no agent reads this entry until it is reviewed.", body)
        self.assertIn("Nothing reputed is recorded: every claim in this entry is "
                      "documented.", body)
        self.assertIn("No proving family is linked to this entry.", body)
        self.assertIn("Not read by any agent yet.", body)
        self.assertIn("Version 1 · import · the platform", body)
        for text in ("I opened the sources I could", "The text is in our own words",
                     "Documented and reputed claims are on the right side",
                     "The tags are right", "Nothing in it concerns our own account"):
            self.assertIn(text, body)
        self.assertIn("Mark reviewed", body)
        self.assertIn("Edit in the admin", body)

    def test_the_nav_link_shows_for_staff_only(self):
        self.client.force_login(self.plain)
        body = self.client.get("/research/").content.decode()
        self.assertNotIn('href="/lore/"', body)
        self.client.force_login(self.staff)
        body = self.client.get("/research/").content.decode()
        self.assertIn('href="/lore/"', body)
        self.assertIn("The Lore", body)


class ReviewTests(TestCase):

    def setUp(self):
        self.entry = make_entry()
        self.reviewer = staff("reviewer")
        self.url = "/lore/example-trend-rule/review/"
        self.checks = {f"check_{k}": "1" for k in
                       ("opened", "own_words", "sides", "tags", "account")}

    def post(self, user, data):
        self.client.force_login(user)
        r = self.client.post(self.url, data, follow=True)
        self.entry.refresh_from_db()
        return r.content.decode()

    def test_review_is_refused_without_the_five_checks(self):
        data = dict(self.checks, action="reviewed", content_sha=self.entry.content_sha)
        data.pop("check_tags")
        body = self.post(self.reviewer, data)
        self.assertIn("Tick all five checks to mark this entry reviewed.", body)
        self.assertEqual(self.entry.status, "draft")

    def test_review_is_refused_without_the_permission(self):
        plain_staff = staff("staff_no_perm", superuser=False)
        body = self.post(plain_staff, dict(self.checks, action="reviewed",
                                           content_sha=self.entry.content_sha))
        self.assertIn("You do not have permission to review library entries.", body)
        self.assertEqual(self.entry.status, "draft")
        plain_staff.user_permissions.add(
            Permission.objects.get(codename="review_loreentry"))
        plain_staff = User.objects.get(pk=plain_staff.pk)
        body = self.post(plain_staff, dict(self.checks, action="reviewed",
                                           content_sha=self.entry.content_sha))
        self.assertIn("Reviewed. Agents cleared for the library may now read "
                      "this entry.", body)
        self.assertEqual(self.entry.status, "reviewed")
        self.assertEqual(self.entry.reviewed_by, plain_staff)
        self.assertEqual(self.entry.reviewed_sha, self.entry.content_sha)

    def test_review_is_refused_when_the_validator_fails(self):
        from lore.models import LoreEntry
        LoreEntry.objects.filter(pk=self.entry.pk).update(horizons_flat="")
        self.entry.refresh_from_db()
        body = self.post(self.reviewer, dict(self.checks, action="reviewed",
                                             content_sha=self.entry.content_sha))
        self.assertIn("This entry cannot be reviewed yet: V27 Tag the asset "
                      "classes and the horizon before review.", body)
        self.assertEqual(self.entry.status, "draft")

    def test_review_is_refused_when_the_entry_changed_since_the_page_was_opened(self):
        body = self.post(self.reviewer, dict(self.checks, action="reviewed",
                                             content_sha="stale-sha"))
        self.assertIn("This entry changed since you opened it. Reload and review "
                      "again.", body)
        self.assertEqual(self.entry.status, "draft")

    def test_review_is_refused_when_the_form_omits_the_sha(self):
        for data in (dict(self.checks, action="reviewed"),
                     dict(self.checks, action="reviewed", content_sha="  ")):
            body = self.post(self.reviewer, data)
            self.assertIn("This entry changed since you opened it. Reload and "
                          "review again.", body)
            self.assertEqual(self.entry.status, "draft")
            self.assertIsNone(self.entry.reviewed_at)

    def test_reviewed_then_back_to_draft_retire_reject_restore(self):
        from lore.models import LoreRevision
        body = self.post(self.reviewer, dict(self.checks, action="reviewed",
                                             content_sha=self.entry.content_sha,
                                             note="Opened both sources."))
        self.assertIn("Reviewed by reviewer on", body)
        self.assertEqual(self.entry.review_note, "Opened both sources.")
        body = self.post(self.reviewer, {"action": "draft"})
        self.assertIn("Back to draft. No agent reads this entry now.", body)
        self.assertEqual(self.entry.status, "draft")
        body = self.post(self.reviewer, {"action": "retire"})
        self.assertIn("Retired. No agent reads this entry now.", body)
        self.assertEqual(self.entry.status, "retired")
        self.assertIsNotNone(self.entry.retired_at)
        body = self.post(self.reviewer, {"action": "restore"})
        self.assertIn("Restored as a draft.", body)
        self.assertEqual(self.entry.status, "draft")
        body = self.post(self.reviewer, {"action": "reject", "note": "Thin sourcing."})
        self.assertIn("Rejected. It stays in the history.", body)
        self.assertEqual(self.entry.status, "rejected")
        self.assertIn("Rejected on", body)
        self.assertIn("Thin sourcing.", body)
        vias = list(LoreRevision.objects.filter(entry=self.entry)
                    .order_by("created_at").values_list("via", flat=True))
        self.assertEqual(vias, ["import", "review", "draft", "retire", "restore",
                                "reject"])

    def test_retire_and_reject_remove_the_entry_from_agents(self):
        from lore import curate
        from lore.read import block_for
        switch("lore_staff")
        review(self.entry, self.reviewer)
        self.assertTrue(block_for("research", query="trend rule",
                                  viewer=self.reviewer, ledger=False).text)
        curate.set_status(self.entry, "retired", self.reviewer, via="retire")
        b = block_for("research", query="trend rule", viewer=self.reviewer, ledger=False)
        self.assertEqual((b.text, b.reason), ("", "nothing matched"))
        curate.set_status(self.entry, "draft", self.reviewer, via="restore")
        review(self.entry, self.reviewer)
        curate.set_status(self.entry, "rejected", self.reviewer, via="reject")
        self.assertEqual(block_for("research", query="trend rule",
                                   viewer=self.reviewer, ledger=False).text, "")

    def test_marking_a_source_opened_stamps_it(self):
        body = self.post(self.reviewer, {"action": "opened", "opened": ["1"]})
        self.assertIn("Marked 1 source as opened.", body)
        src = self.entry.sources.get()
        self.assertEqual(src.found_via, "opened")
        self.assertEqual(src.checked_by, self.reviewer)
        self.assertIsNotNone(src.checked_on)
        self.assertIn("Opened", body)
        self.assertNotIn("Search summary only", body)
        # Opening a source is not a content change.
        self.assertEqual(self.entry.content_sha, self.entry.imported_sha)

    def test_an_admin_edit_of_a_reviewed_entry_returns_it_to_draft(self):
        from django.contrib.admin.sites import AdminSite
        from lore.admin import LoreEntryAdmin
        from lore.models import LoreEntry, LoreRevision
        review(self.entry, self.reviewer)
        self.entry.refresh_from_db()
        self.entry.mechanism = "Edited in the admin, in our words."
        self.entry.save()
        request = RequestFactory().post("/admin/lore/loreentry/1/change/")
        request.user = self.reviewer
        request.session = {}
        request._messages = FallbackStorage(request)
        admin = LoreEntryAdmin(LoreEntry, AdminSite())
        form = SimpleNamespace(instance=self.entry, save_m2m=lambda: None)
        admin.save_related(request, form, [], True)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, "draft")
        self.assertEqual(self.entry.version, 2)
        self.assertNotEqual(self.entry.content_sha, self.entry.imported_sha)
        self.assertTrue(LoreRevision.objects.filter(entry=self.entry, via="admin").exists())
        said = [str(m) for m in request._messages]
        self.assertIn("Saved. The text changed, so this entry is a draft again and "
                      "no agent reads it. Review it on its library page.", said)
        self.assertFalse(admin.has_delete_permission(request))


class SwitchTests(TestCase):

    def test_both_components_are_registered_off_and_fit_the_column(self):
        from core.platform_control import (DEFAULT_COMPONENTS, LIVE_MONEY_SWITCHES,
                                           PlatformComponent, seed_components)
        from lore.policy import POLICY, SWITCHES
        keys = {c["key"]: c for c in DEFAULT_COMPONENTS}
        self.assertEqual(set(SWITCHES), {"lore_staff", "lore_background"})
        for policy in POLICY.values():
            comp = keys[policy.switch]
            self.assertEqual(comp["category"], "agent")
            self.assertLessEqual(len(comp["description"]), 300)
            self.assertNotIn(policy.switch, LIVE_MONEY_SWITCHES)
        seed_components()
        for key in SWITCHES:
            self.assertFalse(PlatformComponent.objects.get(key=key).is_enabled)

    def test_the_agent_groups_all_on_never_arms_a_library_reader(self):
        """Each reader is a decision of its own: lore_staff after review,
        lore_background only after D1 (the briefing reaches non-staff)."""
        from core.platform_control import (BULK_ENABLE_EXEMPT, LORE_READER_SWITCHES,
                                           PlatformComponent, seed_components)
        from lore.policy import SWITCHES
        self.assertIn("lore_background", BULK_ENABLE_EXEMPT)
        self.assertIn("lore_staff", BULK_ENABLE_EXEMPT)
        # A reader added to the policy is held back too, or this fails.
        self.assertEqual(set(LORE_READER_SWITCHES), set(SWITCHES))
        seed_components()
        self.client.force_login(staff("bulk_admin"))
        self.client.post("/admin-dashboard/bulk-toggle/",
                         {"category": "agent", "action": "enable"})
        for key in SWITCHES:
            self.assertFalse(PlatformComponent.objects.get(key=key).is_enabled, key)
        self.assertTrue(PlatformComponent.objects.filter(
            category="agent", is_enabled=True).exists())
        self.client.post("/admin-dashboard/bulk-toggle/",
                         {"category": "agent", "action": "disable"})
        self.assertFalse(PlatformComponent.objects.filter(
            category="agent", is_enabled=True).exists())


class InferenceOnThePageTests(TestCase):

    def test_an_inference_carries_no_source_badge(self):
        user = staff("inference_staff")
        make_entry(fails_when=[
            {"how": "A guess about how it fails.", "episode": "Generic; inference.",
             "src": [0]},
            {"how": "A failure the paper shows.", "episode": "A stand-in episode.",
             "src": [0]}])
        self.client.force_login(user)
        body = self.client.get("/lore/example-trend-rule/").content.decode()
        guess = body[body.index("A guess about how it fails."):]
        guess = guess[:guess.index("</li>")]
        self.assertIn("our inference", guess)
        self.assertNotIn(">S1<", guess)
        shown = body[body.index("A failure the paper shows."):]
        self.assertIn(">S1<", shown[:shown.index("</li>")])
