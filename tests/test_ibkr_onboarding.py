"""Interactive Brokers: the port is the switch, and it must never lie.

IBKR is the broker meant to carry the real book, and it had a save view, a
URL, and no way in the interface to reach either — this platform offered
OANDA and Alpaca forms and stopped. An operator's only route to configuring
the one broker that moves real money was Django admin.

The thing that makes IBKR different from every other broker wired here is
that paper-versus-live is a PORT NUMBER. There is no second switch inside
the API: 7497 and 4002 are simulated, 7496 and 4001 are funded, and one
digit separates them. The model even carries a `paper` boolean whose own
help text admits it is "informational — actual paper/live behaviour follows
TWS port", and the save view was building its confirmation message out of
that boolean. It could tell an operator "saved (paper)" while pointing at
their funded account.

So: the port decides, everywhere. And a port that is none of the four is
reported as UNKNOWN rather than assumed safe — "we could not tell" and "it
is simulated" are different answers, and only one of them is true.

Run with:  python manage.py test tests.test_ibkr_onboarding
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase


def _template():
    for d in settings.TEMPLATES[0]["DIRS"]:
        path = Path(d) / "dashboard" / "admin_dashboard.html"
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise AssertionError("admin_dashboard.html not found")


def _account(**kw):
    from bot_program.models import IBKRAccount
    user = get_user_model().objects.create_user(
        kw.pop("username", "ib_u"), password="x")
    fields = dict(host="127.0.0.1", port=7497, client_id=1, paper=True)
    fields.update(kw)
    return IBKRAccount.objects.create(user=user, **fields)


class PortIsTheSwitchTests(TestCase):
    def test_the_two_paper_ports_read_as_paper(self):
        for port in (7497, 4002):
            acct = _account(username=f"p{port}", port=port)
            self.assertEqual(acct.env, "paper", port)
            self.assertFalse(acct.is_live, port)
            self.assertTrue(acct.env_is_certain, port)

    def test_the_two_live_ports_read_as_live(self):
        for port in (7496, 4001):
            acct = _account(username=f"l{port}", port=port)
            self.assertEqual(acct.env, "live", port)
            self.assertTrue(acct.is_live, port)

    def test_an_unrecognised_port_is_unknown_and_not_paper(self):
        """The whole point. Guessing "paper" for a port we cannot classify
        is the one guess that costs real money when it is wrong."""
        acct = _account(port=9999)
        self.assertIsNone(acct.env)
        self.assertFalse(acct.env_is_certain)
        self.assertFalse(acct.is_live)
        self.assertIn("UNKNOWN", acct.env_label)
        self.assertIn("9999", acct.env_label)

    def test_a_typo_of_one_digit_does_not_silently_become_paper(self):
        """7946 for 7496 — the realistic slip."""
        self.assertIsNone(_account(port=7946).env)

    def test_the_label_names_the_venue(self):
        self.assertIn("TWS", _account(username="v1", port=7496).env_label)
        self.assertIn("Gateway", _account(username="v2", port=4002).env_label)

    def test_the_checkbox_disagreeing_with_the_port_is_reported(self):
        """`paper` ticked on a live socket is somebody believing something
        false about which account they are pointed at."""
        acct = _account(port=7496, paper=True)
        self.assertTrue(acct.paper_flag_disagrees)
        self.assertEqual(acct.env, "live", "the port still wins")

    def test_agreement_is_not_reported_as_a_disagreement(self):
        self.assertFalse(_account(port=7497, paper=True).paper_flag_disagrees)
        self.assertFalse(_account(username="a2", port=7496,
                                  paper=False).paper_flag_disagrees)

    def test_an_unknown_port_cannot_disagree_with_anything(self):
        self.assertFalse(_account(port=9999, paper=True).paper_flag_disagrees)

    def test_the_str_reports_the_port_and_not_the_checkbox(self):
        """It used to print "(paper)" off the boolean, so a live connection
        described itself as simulated in the admin list and the logs."""
        acct = _account(port=7496, paper=True)
        self.assertIn("live", str(acct))
        self.assertNotIn("paper", str(acct))


class TheFormExistsTests(SimpleTestCase):
    """It did not. The view and the URL were wired and unreachable."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = _template()

    def test_the_page_offers_an_ibkr_form(self):
        self.assertIn("hq_save_ibkr", self.html)

    def test_it_collects_what_the_view_requires(self):
        for field in ("target_username", "ibkr_account_id", "ibkr_host",
                      "ibkr_port", "ibkr_client_id"):
            self.assertIn(f'name="{field}"', self.html, field)

    def test_the_port_is_a_labelled_choice_and_not_a_bare_number_box(self):
        """A free-text port is a one-digit typo away from a funded account,
        and the number alone does not say which it is."""
        self.assertIn('id="ibkrPort"', self.html)
        for port in ("7497", "4002", "7496", "4001"):
            self.assertIn(f'value="{port}"', self.html, port)

    def test_every_port_option_says_paper_or_live_in_words(self):
        import re
        block = self.html.split('id="ibkrPort"', 1)[1].split("</select>", 1)[0]
        options = re.findall(r"<option[^>]*>([^<]+)</option>", block)
        # Six, not four: the dockerised Gateway's socat relay ports (4003
        # live, 4004 paper) joined the classic four when the operator's
        # first real Gateway proved 4001/4002 refuse from the compose
        # network. Every one of them still has to say which money it is.
        self.assertEqual(len(options), 6)
        for text in options:
            self.assertTrue(
                "PAPER" in text or "LIVE" in text,
                f"port option does not say which it is: {text!r}")

    def test_the_paper_default_is_a_paper_port(self):
        block = self.html.split('id="ibkrPort"', 1)[1].split("</select>", 1)[0]
        selected = [line for line in block.splitlines() if "selected" in line]
        self.assertEqual(len(selected), 1)
        self.assertIn("PAPER", selected[0])

    def test_the_routing_toggles_are_offered(self):
        for field in ("primary_for_options", "primary_for_stocks",
                      "primary_for_forex", "primary_for_commodity",
                      "primary_for_cfd"):
            self.assertIn(f'name="{field}"', self.html, field)

    def test_commodity_routing_says_what_it_changes(self):
        """Gold is what this operator trades, and it stays on the paper
        venue unless this box is ticked — the field's own help text says so
        and the form has to say it too."""
        self.assertIn("primary_for_commodity", self.html)
        idx = self.html.find('name="primary_for_commodity"')
        self.assertIn("paper venue", self.html[idx:idx + 400])

    def test_the_form_says_tws_must_be_running(self):
        """IBKR is a socket, not an API key. Saving credentials connects to
        nothing, and an operator who does not know that will think they are
        configured when they are not."""
        self.assertIn("ib-note", self.html)
        note = self.html.split('class="ib-note"', 1)[1][:400]
        self.assertIn("TWS", note)


class LiveSocketIsGatedTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = _template()

    def test_a_live_port_reveals_a_warning(self):
        self.assertIn('id="ibLiveWarning"', self.html)
        self.assertIn("hidden", self.html.split('id="ibLiveWarning"', 1)[1][:60])

    def test_saving_a_live_socket_requires_typing_something(self):
        """The house pattern for an irreversible-ish control: friction that
        a reflex Enter cannot satisfy."""
        script = self.html.split('id="ibkrForm"', 1)[1]
        self.assertIn('requireText: "LIVE"', script)

    def test_only_the_live_ports_arm_the_gate(self):
        script = self.html.split("LIVE_PORTS = {", 1)[1].split("}", 1)[0]
        self.assertIn("7496", script)
        self.assertIn("4001", script)
        self.assertNotIn("7497", script)
        self.assertNotIn("4002", script)

    def test_the_dialog_does_not_overstate_what_saving_does(self):
        """Saving points the platform at an account; it submits no orders. A
        warning that claims more than it should gets dismissed as noise the
        second time it appears, and then it protects nothing."""
        script = self.html.split('id="ibkrForm"', 1)[1]
        dialog = script.split("SV.overlay.confirm", 1)[1][:1200]
        self.assertIn("no", dialog)
        self.assertIn("armed", dialog)

    def test_the_warning_is_styled_and_not_a_bare_paragraph(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css") \
            .read_text(encoding="utf-8")
        for cls in (".ib-live-warning", ".ib-env--live", ".ib-env--paper",
                    ".ib-env--unknown"):
            self.assertIn(cls, css, cls)


class TheStatusTableTests(TestCase):
    """IBKR was absent from the broker table entirely, so a user whose only
    broker was the one meant to carry the real book did not appear in it —
    the page said "no broker accounts configured yet" over a live account."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            "ib_admin", "a@b.c", "x")
        self.client.force_login(self.admin)

    def _connected(self, port=7497, paper=True, user=None):
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(
            user=user or self.admin, host="127.0.0.1", port=port,
            client_id=1, paper=paper)
        acct.set_credentials("U1234567")
        acct.save()
        return acct

    def _page(self):
        resp = self.client.get("/admin-dashboard/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", "replace")

    def test_the_table_has_an_ibkr_column(self):
        # The table only renders once a broker exists; with none, the card
        # shows the "configure one below" empty state instead.
        self._connected()
        self.assertIn("<th>IBKR</th>", self._page())

    def test_a_user_with_only_ibkr_appears_in_the_table(self):
        self._connected()
        body = self._page()
        self.assertIn("ib_admin", body)
        self.assertNotIn("No broker accounts configured yet", body)

    def test_a_live_port_is_chipped_live_even_when_the_flag_says_paper(self):
        """The exact confusion this pass exists to remove."""
        self._connected(port=7496, paper=True)
        body = self._page()
        self.assertIn("ib-env--live", body)
        self.assertNotIn("ib-env--paper", body)

    def test_the_disagreement_is_shown_rather_than_silently_resolved(self):
        self._connected(port=7496, paper=True)
        self.assertIn("flag disagrees with port", self._page())

    def test_a_paper_port_is_chipped_paper(self):
        self._connected(port=7497, paper=True)
        body = self._page()
        self.assertIn("ib-env--paper", body)
        self.assertNotIn("ib-env--live", body)

    def test_an_unrecognised_port_is_chipped_unknown_and_never_paper(self):
        self._connected(port=9999, paper=True)
        body = self._page()
        self.assertIn("ib-env--unknown", body)
        self.assertNotIn("ib-env--paper", body)
        self.assertNotIn("ib-env--live", body)

    def test_a_connected_account_offers_a_disconnect(self):
        self._connected()
        self.assertIn('value="ibkr"', self._page())

    def test_the_disconnect_endpoint_clears_the_account_id(self):
        acct = self._connected()
        resp = self.client.post(
            "/admin-dashboard/brokers/disconnect/",
            {"target_username": "ib_admin", "broker": "ibkr"},
            HTTP_HOST="127.0.0.1")
        self.assertIn(resp.status_code, (302, 200))
        acct.refresh_from_db()
        self.assertEqual(acct.account_id_enc, "")
        self.assertFalse(acct.connected)


class ConnectionTestTests(TestCase):
    """Saving already pings, but that made verification a side effect of
    WRITING: the only way to re-check a socket was to re-submit the whole
    form, which rewrites the routing overrides from whatever the checkboxes
    happen to hold. An operator who starts TWS after saving had no way to
    confirm it without risking their configuration."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            "ib_t", "a@b.c", "x")
        self.client.force_login(self.admin)

    def _account(self, port=7497, account_id="DU1"):
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(
            user=self.admin, host="127.0.0.1", port=port, client_id=1,
            paper=port in IBKRAccount.PAPER_PORTS,
            is_primary_for_commodity=True)
        if account_id:
            acct.set_credentials(account_id)
        acct.save()
        return acct

    def _test_it(self, username="ib_t"):
        resp = self.client.post("/admin-dashboard/brokers/ibkr/test/",
                                {"target_username": username},
                                HTTP_HOST="127.0.0.1", follow=True)
        return [m.message for m in resp.context["messages"]]

    def test_the_button_is_offered(self):
        self._account()
        resp = self.client.get("/admin-dashboard/", HTTP_HOST="127.0.0.1")
        self.assertIn("Test IBKR", resp.content.decode("utf-8", "replace"))

    def test_an_unreachable_socket_says_what_to_check(self):
        self._account()
        msg = " ".join(self._test_it())
        self.assertIn("nothing answered", msg)
        self.assertIn("must be running", msg)

    def test_it_does_not_rewrite_the_routing_overrides(self):
        """The whole reason this exists rather than re-saving the form."""
        acct = self._account()
        self._test_it()
        acct.refresh_from_db()
        self.assertTrue(acct.is_primary_for_commodity)

    def test_a_disconnected_account_says_so_instead_of_pinging(self):
        """No account id means the router refuses the row either way, so a
        socket result would answer a question nobody asked."""
        self._account(account_id=None)
        msg = " ".join(self._test_it())
        self.assertIn("disconnected", msg)
        self.assertNotIn("nothing answered", msg)

    def test_an_unknown_user_is_refused(self):
        self.assertIn("not found", " ".join(self._test_it("nobody")))

    def test_a_user_with_no_ibkr_row_is_refused(self):
        self.assertIn("no connection saved", " ".join(self._test_it()))

    def test_it_is_post_only_and_admin_only(self):
        resp = self.client.get("/admin-dashboard/brokers/ibkr/test/",
                               HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 405)
        plain = get_user_model().objects.create_user("ib_plain", password="x")
        self.client.force_login(plain)
        resp = self.client.post("/admin-dashboard/brokers/ibkr/test/",
                                {"target_username": "ib_t"},
                                HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 403)


class ArmingABotLiveIsConfirmedTests(SimpleTestCase):
    """The PIN proves WHO is asking, not that they meant THIS. A live bot
    opens and closes positions on its own, on every beat, without asking
    again — the same friction the live IBKR socket gets applies here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = _template()

    def test_the_mode_options_say_which_money_they_spend(self):
        block = self.html.split('id="assetBotMode"', 1)[1].split("</select>", 1)[0]
        self.assertIn("simulated", block)
        self.assertIn("real funds", block)

    def test_choosing_live_requires_typing_it(self):
        script = self.html.split('id="assetBotForm"', 1)[1]
        self.assertIn('requireText: "LIVE"', script)

    def test_paper_is_not_gated(self):
        """Friction on the safe path teaches operators to click through."""
        script = self.html.split('id="assetBotForm"', 1)[1]
        self.assertIn('mode.value !== "live"', script)

    def test_the_dialog_names_where_the_orders_would_go(self):
        """"Live" does not say WHERE — and a commodity bot stays simulated
        unless an IBKR account is primary for that class."""
        script = self.html.split('id="assetBotForm"', 1)[1]
        dialog = script[script.find("SV.overlay.confirm"):][:1800]
        self.assertIn("Routes to", dialog)
        self.assertIn("paper venue unless IBKR", dialog)

    def test_the_dialog_does_not_claim_the_bot_starts_trading_immediately(self):
        script = self.html.split('id="assetBotForm"', 1)[1]
        dialog = script[script.find("SV.overlay.confirm"):][:2200]
        self.assertIn("ENABLED", dialog)
        self.assertIn("master switch", dialog)
