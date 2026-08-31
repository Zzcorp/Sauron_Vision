"""The Gateway login lives with the account, encrypted, not in .env.

Sauron never authenticates to IBKR — it connects to a socket that is
already logged in — so a username and password exist only so IBC can
sign the Gateway CONTAINER in, and a container reads its environment
once, at boot. That is why saving cannot simply apply: bouncing a
Gateway drops a live session that may have positions behind it, so the
restart stays the operator's to time.

What the UI buys is a single source of truth that is encrypted at rest,
backed up with everything else, and editable per account rather than by
whoever can SSH to the box.

Run with:  python manage.py test tests.test_ibkr_login_store
"""
from django.contrib.auth.models import User
from django.test import TestCase


def _acct(user, **kw):
    from bot_program.models import IBKRAccount
    return IBKRAccount.objects.create(user=user, **kw)


class TheLoginIsEncryptedAtRestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ib_u", password="x")

    def test_a_round_trip_returns_what_was_stored(self):
        a = _acct(self.user)
        a.set_login("myuser", "mypass")
        a.save()
        a.refresh_from_db()
        self.assertEqual(a.get_login(), ("myuser", "mypass"))

    def test_the_password_is_not_stored_in_the_clear(self):
        a = _acct(self.user)
        a.set_login("myuser", "hunter2")
        a.save()
        a.refresh_from_db()
        self.assertNotIn("hunter2", a.password_enc)
        self.assertNotIn("myuser", a.username_enc)

    def test_blank_keeps_what_is_stored(self):
        """Nobody should retype a brokerage password to change a routing
        checkbox — and a form that cleared it would take the Gateway down
        on its next restart."""
        a = _acct(self.user)
        a.set_login("myuser", "mypass")
        a.set_login("", "")
        self.assertEqual(a.get_login(), ("myuser", "mypass"))

    def test_an_account_with_no_login_says_so(self):
        a = _acct(self.user)
        self.assertFalse(a.has_login)
        self.assertEqual(a.get_login(), (None, None))
        a.set_login("u", "p")
        self.assertTrue(a.has_login)


class TheSlotNamesItsContainerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("slot_u", password="x")

    def test_slot_one_is_the_unnumbered_service(self):
        a = _acct(self.user, gateway_slot=1)
        self.assertEqual(a.gateway_host, "ibgateway")
        self.assertEqual(a.env_prefix, "IBKR")

    def test_later_slots_are_numbered(self):
        a = _acct(self.user, gateway_slot=3)
        self.assertEqual(a.gateway_host, "ibgateway-3")
        self.assertEqual(a.env_prefix, "IBKR3")


class RenderingWritesWhatComposeReadsTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("r_a", password="x")
        self.b = User.objects.create_user("r_b", password="x")

    def _render(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("render_ibkr_env", stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_each_slot_gets_its_own_prefix(self):
        x = _acct(self.a, gateway_slot=1)
        x.set_login("alpha", "pw1")
        x.save()
        y = _acct(self.b, gateway_slot=2)
        y.set_login("bravo", "pw2")
        y.save()
        out = self._render()
        # Quoted since the $$ incident: compose expands $ in UNQUOTED
        # .env values at read time, so an operator's password containing
        # $$ reached the Gateway one $ short and was refused behind a
        # dialog IBC cannot read. Single quotes make the value literal.
        self.assertIn("IBKR_USERNAME='alpha'", out)
        self.assertIn("IBKR2_USERNAME='bravo'", out)

    def test_the_mode_follows_the_port(self):
        """paper with 4002, live with 4001 — a mismatch is a socket that
        never answers and reads as a network fault."""
        x = _acct(self.a, gateway_slot=1, port=4001)
        x.set_login("alpha", "pw")
        x.save()
        self.assertIn("IBKR_TRADING_MODE=live", self._render())

    def test_an_account_with_no_login_is_skipped(self):
        _acct(self.a, gateway_slot=1)
        self.assertIn("No IBKR logins stored yet", self._render())

    def test_two_different_logins_on_one_slot_are_refused(self):
        """One Gateway session is one username, so the second would
        silently never connect. Named, not merged."""
        from io import StringIO

        from django.core.management import call_command
        x = _acct(self.a, gateway_slot=1)
        x.set_login("alpha", "pw1")
        x.save()
        y = _acct(self.b, gateway_slot=1)
        y.set_login("bravo", "pw2")
        y.save()
        err = StringIO()
        call_command("render_ibkr_env", stdout=StringIO(), stderr=err)
        self.assertIn("two different logins", err.getvalue())

    def test_the_block_is_replaceable_not_appended(self):
        """Re-rendering must not stack copies in .env."""
        from io import StringIO

        from django.core.management import call_command
        x = _acct(self.a, gateway_slot=1)
        x.set_login("alpha", "pw")
        x.save()
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("SECRET_KEY=x\n", encoding="utf-8")
            for _ in range(3):
                call_command("render_ibkr_env", "--write", f"--env={env}",
                             stdout=StringIO(), stderr=StringIO())
            text = env.read_text(encoding="utf-8")
        self.assertEqual(text.count("IBKR_USERNAME='alpha'"), 1)
        self.assertIn("SECRET_KEY=x", text)


class TheStripsScrollSidewaysOnAWheelTests(TestCase):
    def test_the_bottom_headband_takes_the_wheel(self):
        from pathlib import Path

        from django.conf import settings
        shell = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        self.assertIn("svWheelScrollsSideways(ipScroll)", shell)

    def test_it_falls_through_at_either_end(self):
        """Reaching the last cell must not trap the page scroll on a
        strip 48 pixels tall."""
        from pathlib import Path

        from django.conf import settings
        shell = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        seg = shell.split("function svWheelScrollsSideways")[1][:900]
        self.assertIn("if (el.scrollLeft !== before) e.preventDefault();", seg)

    def test_a_trackpad_swipe_wins_over_a_wheel(self):
        from pathlib import Path

        from django.conf import settings
        shell = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        seg = shell.split("function svWheelScrollsSideways")[1][:900]
        self.assertIn("Math.abs(e.deltaX) > Math.abs(e.deltaY)", seg)


class BothMarqueeStripsAnswerTheWheelTests(TestCase):
    """The ticker and the data headband are CSS marquees moved by
    `transform`, not scroll containers, so the sideways scroller used on
    the bottom panel does nothing to them. They need their own driver —
    and both were subtly broken in their own way: the ticker snapped
    back after 1.5s, undoing the operator's positioning while they were
    still reading it, and the data headband moved twelve pixels per
    wheel notch, which is working and indistinguishable from broken.
    """

    def _shell(self):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")

    def test_both_strips_use_the_shared_driver(self):
        shell = self._shell()
        self.assertIn("window.svWheelMarquee(ticker,", shell)
        self.assertIn("window.svWheelMarquee(dhFrame, dhTrack)", shell)

    def test_the_ticker_no_longer_snaps_back(self):
        """A timeout that undoes the operator's scroll is why this felt
        broken rather than absent."""
        shell = self._shell()
        self.assertNotIn("ticker._rt = setTimeout", shell)

    def test_the_headband_no_longer_moves_twelve_pixels(self):
        shell = self._shell()
        self.assertNotIn("dhStep(e.deltaY > 0 ? -3 : 3)", shell)

    def test_the_move_is_proportional_to_the_gesture(self):
        seg = self._shell().split("window.svWheelMarquee = function")[1][:1400]
        self.assertIn("Math.abs(e.deltaX) > Math.abs(e.deltaY)", seg)
        self.assertIn("offset - delta", seg)

    def test_it_lets_go_at_the_ends(self):
        """At either end the wheel belongs to the page, not to a strip
        38 pixels tall."""
        seg = self._shell().split("window.svWheelMarquee = function")[1][:1400]
        self.assertIn("if (next === offset) return;", seg)

    def test_leaving_the_strip_hands_it_back_to_the_marquee(self):
        seg = self._shell().split("window.svWheelMarquee = function")[1][:1400]
        self.assertIn("mouseleave", seg)
        self.assertIn("animationPlayState = ''", seg)

    def test_the_arrow_buttons_keep_their_own_crawl(self):
        """dhStep was written for a slow crawl on arrow hover — that is
        what it is good at, and it keeps that job."""
        shell = self._shell()
        self.assertIn("setInterval(function(){ dhStep(dir); }, 16)", shell)
