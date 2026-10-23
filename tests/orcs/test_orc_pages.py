"""THE ORCS' PAGES (spec §9.2, O1d): /orcs/, /orcs/<id>/, /orcs/seats/.

Pinned here: login and the investor cage; the viewer's own Orcs only, a
404 that names nobody, a leg's number redirecting to its idea; the detail
page's sections with facts, notes and the operator's words drawn apart;
the operator's thesis kept beside the entry's (kind `thesis`, author
`operator`, no fact id, Orc.thesis untouched), refused while OFF and for
another user, escaped everywhere; the spend lines and the seats page staff
only and never pooled; a constant number of queries; no money on the
pages but the staff's spend lines; the OFF banner.

Run with:  python manage.py test tests.orcs.test_orc_pages
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tests.orcs.helpers import (_config, _drum_heard, _on, _paper_cap, _row,
                                _user, _wake_card, born)

SCRIPT = "<script>alert(1)</script>"


def _main(response):
    """The page's own content (the Orc page's block), without the shell
    every page carries (the headband's tickers, the strip's money)."""
    html = response.content.decode()
    start = html.index('<div class="orc-page">')
    return html[start:html.index("<style>", start)]


def _table(html, table_id):
    """The rows of the table `table_id` as lists of cell texts."""
    import re
    body = html.split(f'id="{table_id}"', 1)[1].split("<tbody>", 1)[1] \
               .split("</tbody>", 1)[0]
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", body, flags=re.S):
        rows.append([re.sub(r"<[^>]+>", "", c).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", tr,
                                         flags=re.S)])
    return rows


class _Pages(TestCase):

    def setUp(self):
        cache.clear()
        _on()
        self.user = _user("orc_pages")
        self.client.force_login(self.user)
        self.cfg = _config(self.user)
        self.row = _row(self.cfg, meta={"broker": "paper"})
        self.orc = born(self, self.row)

    def page(self, name="orcs_list", *args, status=200, **kw):
        r = self.client.get(reverse(name, args=args), **kw)
        self.assertEqual(r.status_code, status, r.content[:300])
        return r

    def detail(self, n=None):
        return self.page("orc_detail", n or self.row.pk)

    def post_thesis(self, text, n=None):
        return self.client.post(reverse("orc_thesis", args=[n or self.row.pk]),
                                {"thesis": text})


class TheDoorTests(_Pages):

    def test_login_required_and_an_investor_is_sent_away(self):
        from portfolio.investor_models import InvestorAccess
        self.client.logout()
        for name, args in (("orcs_list", []), ("orc_detail", [self.row.pk]),
                           ("orcs_seats", [])):
            r = self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 302, name)
        investor = get_user_model().objects.create_user("lp_pages",
                                                        password="x")
        InvestorAccess.objects.create(investor=investor, owner=self.user,
                                      label="Fund")
        self.client.force_login(investor)
        for name, args in (("orcs_list", []), ("orc_detail", [self.row.pk])):
            r = self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r["Location"].startswith("/investor/"),
                            r["Location"])
        r = self.client.post(reverse("orc_thesis", args=[self.row.pk]),
                             {"thesis": "x"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/investor/"))

    def test_the_list_shows_only_the_viewers_orcs(self):
        other = _user("orc_pages_b")
        ocfg = _config(other)
        orow = _row(ocfg, symbol="ETHUSD")
        born(self, orow)
        html = _main(self.page())
        self.assertIn(f"Orc #{self.row.pk}", html)
        self.assertNotIn(f"Orc #{orow.pk}", html)
        self.assertNotIn("ETHUSD", html)
        self.assertNotIn("orc_pages_b", html)

    def test_another_users_page_is_a_404_naming_nobody(self):
        other = _user("orc_pages_c")
        orow = _row(_config(other), symbol="ETHUSD")
        born(self, orow)
        for n in (orow.pk, 999999):
            r = self.client.get(reverse("orc_detail", args=[n]))
            self.assertEqual(r.status_code, 404)
            self.assertNotIn(b"orc_pages_c", r.content)
            self.assertNotIn(b"ETHUSD", r.content)
            r = self.post_thesis("mine", n=n)
            self.assertEqual(r.status_code, 404)

    def test_the_list_keeps_the_ended_ideas_of_30_days(self):
        from datetime import timedelta

        from bot_program.orcs.models import Orc
        _paper_cap()
        now = timezone.now()
        recent = born(self, _row(self.cfg, symbol="ETHUSD"))
        old = born(self, _row(self.cfg, symbol="SOLUSD"))
        Orc.objects.filter(pk=recent.pk).update(
            state="dead", died_at=now - timedelta(days=2))
        Orc.objects.filter(pk=old.pk).update(
            state="dead", died_at=now - timedelta(days=40))
        html = _main(self.page())
        self.assertIn(f">{recent.label}<", html)
        self.assertNotIn(f">{old.label}<", html)
        self.assertIn(f">{self.orc.label}<", html)

    def test_a_leg_number_redirects_to_the_root(self):
        from bot_program.orcs.models import OrcLeg
        add = _row(self.cfg, qty="0.5")
        OrcLeg.objects.create(orc=self.orc, trade=add, kind="add", seq=2)
        r = self.client.get(reverse("orc_detail", args=[add.pk]))
        self.assertRedirects(r, reverse("orc_detail", args=[self.row.pk]),
                             fetch_redirect_response=False)


class TheDetailTests(_Pages):

    def test_the_detail_sections(self):
        _wake_card(self.orc)
        _drum_heard(self.orc)
        html = self.detail().content.decode()
        for anchor in ('id="orc-thesis"', 'id="orc-yours"', 'id="orc-plan"',
                       'id="orc-journal"', 'id="orc-arms"',
                       'id="orc-wakes"', 'id="orc-grade"'):
            self.assertIn(anchor, html)
        self.assertIn("No plan yet: Orcs write plans once they reason.",
                      html)
        self.assertIn("No intents: an Orc proposes nothing until it "
                      "reasons.", html)
        self.assertIn("care ghost", html)
        self.assertIn("score 58 · complex", html)
        self.assertIn("No model (code only)", html)
        self.assertIn("invalidates on a displaced break against it", html)
        self.assertIn("L0 · Snaga", html)

    def test_facts_and_notes_are_visually_distinct(self):
        from bot_program.orcs import journal
        journal.append(self.orc, "reading", "A code reading of the 4h.",
                       author="orc")
        self.post_thesis("Gold holds the range.")
        html = self.detail().content.decode()
        self.assertIn('class="orc-j orc-j--fact"', html)
        self.assertIn('class="orc-j orc-j--note"', html)
        self.assertIn('class="orc-j orc-j--yours"', html)

    def test_the_operator_thesis_is_kept_beside_the_entrys(self):
        from bot_program.orcs.models import Orc, OrcJournal
        before = Orc.objects.get(pk=self.orc.pk).thesis
        r = self.post_thesis("  Gold   holds the range\nuntil the print. ")
        self.assertRedirects(r, reverse("orc_detail", args=[self.row.pk]),
                             fetch_redirect_response=False)
        e = OrcJournal.objects.get(orc=self.orc, kind="thesis")
        self.assertEqual(e.author, "operator")
        self.assertEqual(e.fact_id, "")
        self.assertEqual(e.headline,
                         "Your thesis: Gold holds the range until the "
                         "print.")
        self.assertEqual(e.body, {"thesis": {
            "source": "operator",
            "text": "Gold holds the range until the print."}})
        orc = Orc.objects.get(pk=self.orc.pk)
        self.assertEqual(orc.thesis, before)
        self.assertEqual(orc.card["thesis_operator"]["t"],
                         "Gold holds the range until the print.")
        # the same words again write nothing; a long one is cut at 600
        self.post_thesis("Gold holds the range until the print.")
        self.assertEqual(OrcJournal.objects.filter(kind="thesis").count(), 1)
        self.post_thesis("x" * 900)
        last = OrcJournal.objects.filter(kind="thesis").order_by("-id")[0]
        self.assertEqual(len(last.body["thesis"]["text"]), 600)
        self.assertLessEqual(len(last.headline), 200)
        html = self.detail().content.decode()
        self.assertIn("Thesis · the entry&#x27;s own record", html)
        # the Horde and the lines read the operator's words as his
        from bot_program.orcs import notes
        sl = notes.for_rows([self.row.pk], user=self.user)[f"bot:{self.row.pk}"]
        self.assertEqual(sl["thesis"]["source"], "operator")
        self.assertEqual(sl["thesis"]["source_t"], "yours")

    def test_the_thesis_post_is_refused_while_off_and_for_another_user(self):
        from bot_program.orcs.models import OrcJournal
        _on(False)
        r = self.post_thesis("Mine.")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(OrcJournal.objects.filter(kind="thesis").exists())
        # the write reads the switch itself too, past the page's door
        _on(True)
        with patch("bot_program.orcs.switches.orcs_on",
                   side_effect=[True, False]):
            r = self.post_thesis("Mine.")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(OrcJournal.objects.filter(kind="thesis").exists())
        _on(True)
        self.assertEqual(self.client.get(
            reverse("orc_thesis", args=[self.row.pk])).status_code, 405)
        stranger = _user("orc_pages_d")
        self.client.force_login(stranger)
        self.assertEqual(self.post_thesis("Theirs.").status_code, 404)
        self.client.force_login(self.user)
        self.post_thesis("   ")
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(state="dead",
                                                  died_at=timezone.now())
        self.post_thesis("Too late.")
        self.assertFalse(OrcJournal.objects.filter(kind="thesis").exists())

    def test_the_adoption_notice_points_at_the_page(self):
        from bot_program.orcs.birth import notify_adopted
        real = _row(self.cfg, symbol="ETHUSD", paper=False,
                    meta={"broker": "etoro"})
        orc = born(self, real, adopted=True)
        with patch("bot_program.notifications.dispatch_notification",
                   return_value=True) as send:
            self.assertTrue(notify_adopted(orc.pk))
        self.assertEqual(send.call_args.kwargs["url"], f"/orcs/{real.pk}/")
        self.assertEqual(self.client.get(f"/orcs/{real.pk}/").status_code,
                         200)

    def test_a_closed_ideas_page_shows_no_risk(self):
        from decimal import Decimal

        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc
        now = timezone.now()
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            status="CLOSED", closed_at=now, exit_price=Decimal("99"))
        Orc.objects.filter(pk=self.orc.pk).update(state="dead", died_at=now)
        html = _main(self.detail())
        self.assertIn("State</span><span>Ended.", html)
        self.assertIn('<span class="k">Risk</span><span>—</span>', html)
        self.assertNotRegex(html, r"risk \d+\.\dR of")
        self.assertNotIn("holds", html)

    def test_the_journal_reads_newest_first(self):
        from datetime import timedelta

        from bot_program.orcs import journal
        now = timezone.now()
        journal.append(self.orc, "fact", "The older line.", at=now
                       + timedelta(minutes=1))
        journal.append(self.orc, "fact", "The newer line.", at=now
                       + timedelta(minutes=2))
        html = _main(self.detail())
        block = html.split('id="orc-journal"', 1)[1].split("</ol>", 1)[0]
        self.assertLess(block.index("The newer line."),
                        block.index("The older line."))

    def test_the_thesis_is_escaped_everywhere(self):
        self.post_thesis(f"Gold {SCRIPT} holds.")
        for r in (self.detail(), self.page()):
            body = r.content.decode()
            self.assertNotIn(SCRIPT, body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;",
                      self.detail().content.decode())


class TheStaffTests(_Pages):

    def test_the_spend_lines_are_staff_only(self):
        html = _main(self.page())
        self.assertNotIn("AI spend today", html)
        self.assertNotIn("$", html)
        staff = get_user_model().objects.create_user("orc_staff",
                                                     password="x",
                                                     is_staff=True)
        self.client.force_login(staff)
        html = self.page().content.decode()
        self.assertIn("AI spend today (staff)", html)

    def test_the_seats_page_is_staff_only_and_never_pools(self):
        from bot_program.orcs.models import Orc, OrcGrade, OrcSeat
        r = self.client.get(reverse("orcs_seats"))
        self.assertEqual(r.status_code, 302)
        staff = get_user_model().objects.create_user("orc_staff2",
                                                     password="x",
                                                     is_staff=True)
        self.client.force_login(staff)
        _paper_cap()
        now = timezone.now()
        b = born(self, _row(self.cfg, symbol="ETHUSD"))
        c = born(self, _row(self.cfg, symbol="SOLUSD"))
        Orc.objects.filter(pk__in=[self.orc.pk, b.pk, c.pk]).update(
            state="dead", died_at=now)
        # one seat, two bar sources, and a grade that does not count
        OrcGrade.objects.create(orc=self.orc, delta_care=0.3,
                                counts_for_seat=True, bar_source="etoro",
                                army_type="line")
        OrcGrade.objects.create(orc=b, delta_care=-0.5, counts_for_seat=True,
                                bar_source="yahoo", army_type="line")
        OrcGrade.objects.create(orc=c, delta_care=9.0,
                                counts_for_seat=False, bar_source="etoro",
                                army_type="line")
        demo = OrcSeat.objects.create(venue="demo", asset_class="crypto")
        html = self.page("orcs_seats").content.decode()
        self.assertIn("In this release no Orc takes a step", html)
        self.assertNotIn("+9.00R", html)
        seats = _table(html, "orc-seats")
        mine = [r for r in seats if r[0] == self.orc.seat.venue
                and r[1] == "crypto" and r[2] == self.orc.seat.rule_key]
        # Venue Class Rule Bars Rank Graded Counted Mean SE LB80 UB80 ...
        self.assertEqual([(r[3], r[5], r[6], r[7]) for r in mine],
                         [("etoro", "2", "1", "+0.30R"),
                          ("yahoo", "1", "1", "-0.50R")])
        self.assertTrue(any(r[0] == "demo" for r in seats))
        armies = _table(html, "orc-armies")
        # Army Venue Class Bars Graded Counted Mean LB80 UB80 Against
        self.assertEqual([(r[0], r[1], r[2], r[3], r[4], r[5], r[6])
                          for r in armies],
                         [("Line Orcs", "paper", "crypto", "etoro", "2", "1",
                           "+0.30R"),
                          ("Line Orcs", "paper", "crypto", "yahoo", "1", "1",
                           "-0.50R")])
        self.assertTrue(demo.pk)

    def test_the_army_table_never_pools_venues(self):
        from bot_program.orcs.models import Orc, OrcGrade, OrcSeat
        staff = get_user_model().objects.create_user("orc_staff3",
                                                     password="x",
                                                     is_staff=True)
        self.client.force_login(staff)
        _paper_cap()
        b = born(self, _row(self.cfg, symbol="ETHUSD"))
        live = OrcSeat.objects.create(venue="live", asset_class="crypto",
                                      rule_key=self.orc.seat.rule_key)
        Orc.objects.filter(pk=b.pk).update(seat=live)
        Orc.objects.filter(pk__in=[self.orc.pk, b.pk]).update(
            state="dead", died_at=timezone.now())
        for orc, d in ((self.orc, 0.5), (b, 0.1)):
            OrcGrade.objects.create(orc=orc, delta_care=d,
                                    counts_for_seat=True, bar_source="etoro",
                                    army_type="line")
        armies = _table(self.page("orcs_seats").content.decode(),
                        "orc-armies")
        self.assertEqual(sorted((r[1], r[5], r[6]) for r in armies),
                         [("live", "1", "+0.10R"), ("paper", "1", "+0.50R")])

    def test_the_pages_cost_constant_queries(self):
        def count(fn):
            with CaptureQueriesContext(connection) as ctx:
                fn()
            return len(ctx.captured_queries)
        _wake_card(self.orc)
        self.page()
        self.detail()
        small_list, small_detail = count(self.page), count(self.detail)
        _paper_cap()
        for _ in range(6):
            o = born(self, _row(self.cfg, symbol="ETHUSD"))
            _wake_card(o)
            _drum_heard(o)
        for _ in range(5):
            _drum_heard(self.orc)
        self.assertEqual(count(self.page), small_list)
        self.assertEqual(count(self.detail), small_detail)

    def test_no_money_but_the_staff_spend_lines(self):
        from decimal import Decimal

        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(r_money=Decimal("321.5"),
                                                  spend_today_usd=Decimal(
                                                      "0.75"))
        for html in (_main(self.page()), _main(self.detail())):
            for word in ("321.5", "0.75", "cost_usd", "tokens_in"):
                self.assertNotIn(word, html)

    def test_the_route_probe_counts_them_switched_off_never_missing(self):
        """The forge reads the probe's "missing": OFF, the Orc pages' 404
        is the design, counted under "off" and never "missing"; ON they
        are probed and answer."""
        from io import StringIO

        from django.contrib.auth.models import User
        from django.core.management import call_command
        from django.test import override_settings

        from core.management.commands import probe_routes as pr
        User.objects.create_superuser("orc_probe_su", "p@x", "x")
        names = {"orcs_list", "orcs_seats"}

        def run():
            cache.delete(pr.PROBE_KEY)
            with patch.object(pr, "free_routes", return_value=[
                    r for r in pr.free_routes() if r[0] in names
                    or r[0] in ("positions_list",)]), \
                    override_settings(ALLOWED_HOSTS=["testserver"]):
                out = StringIO()
                call_command("probe_routes", stdout=out)
            return cache.get(pr.PROBE_KEY), out.getvalue()
        _on(False)
        stored, body = run()
        self.assertEqual(stored["missing"], [])
        self.assertEqual(stored["counts"]["off"], 2)
        self.assertIn("2 switched-off routes were NOT probed", body)
        _on(True)
        stored, body = run()
        self.assertEqual(stored["counts"]["off"], 0)
        self.assertEqual(stored["missing"], [])
        self.assertEqual(stored["counts"]["broken"], 0)
        self.assertGreaterEqual(stored["counts"]["ok"], 3)

    def test_off_the_pages_are_the_404_they_were(self):
        """OFF is today (§11 O1): before the Orcs these URLs were unknown,
        a bare 404 for anyone, signed in or not. OFF they answer exactly
        that, before any login redirect; ON they are served."""
        def bodies():
            out = []
            for url in ("/orcs/", f"/orcs/{self.row.pk}/", "/orcs/seats/",
                        "/orcs/no-such-page/"):
                r = self.client.get(url)
                out.append((r.status_code, r.content))
            r = self.client.post(f"/orcs/{self.row.pk}/thesis/",
                                 {"thesis": "x"})
            out.append((r.status_code, r.content))
            return out
        staff = get_user_model().objects.create_user("orc_staff_off",
                                                     password="x",
                                                     is_staff=True)
        _on(False)
        unknown = (404, self.client.get("/orcs/no-such-page/").content)
        for who in (None, self.user, staff):
            self.client.logout()
            if who is not None:
                self.client.force_login(who)
            self.assertEqual(bodies(), [unknown] * 5, who)
        _on(True)
        self.client.force_login(self.user)
        self.assertEqual(self.page().status_code, 200)
        self.assertEqual(self.detail().status_code, 200)
        self.assertIn('name="thesis"', self.detail().content.decode())
