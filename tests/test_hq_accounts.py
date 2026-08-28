"""Onboarding an account without a shell, and seeing where it can trade.

Three operator requests, all the same shape — a thing the platform could
do, reachable only by someone with SSH:

  "make that this command: `seed_bots --user <username> --activate` can be
   done by inputs or selections ... on the main account"

  "improve the IBKR inputs for each account similarly"

  "add for this IBKR and multiple accounts views by cards properly in the
   eye, with more details on hover and clicks to open popups or detailed
   pages"

The through-line: a new operator cannot run a container command from the
account they are being onboarded into, and the broker TABLE answered
"which brokers exist" when the question is "where can this account lose
money".

Run with:  python manage.py test tests.test_hq_accounts
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase


def _admin(name="hq_admin"):
    return User.objects.create_superuser(name, f"{name}@x.com", "x")


def _seed_instruments():
    """`seed_bots` skips any config whose symbols have no Instrument row —
    `if not present: continue` — which is right (a config with nothing to
    trade is not a config) and means a bare test database seeds nothing at
    all. The fleet needs a catalogue to be seeded from."""
    from bot_program.management.commands.seed_bots import FLEET
    from instruments.models import Instrument
    for asset_class, _name, symbols in FLEET:
        for sym in symbols:
            Instrument.objects.get_or_create(
                symbol=sym, defaults={"name": sym,
                                      "asset_class": asset_class,
                                      "is_active": True})


class SeedingAFleetNeedsNoShellTests(TestCase):

    def setUp(self):
        _seed_instruments()
        self.admin = _admin()
        self.client.force_login(self.admin)
        self.target = User.objects.create_user("trader_a", password="x")

    def test_the_page_offers_the_form(self):
        body = self.client.get("/admin-dashboard/",
                               HTTP_HOST="127.0.0.1").content.decode()
        self.assertIn("Give an account the starter fleet", body)
        self.assertIn('action="/admin-dashboard/bots/seed/"', body)

    def test_it_creates_the_fleet_for_the_named_account(self):
        from bot_program.models import AssetBotConfig
        self.client.post("/admin-dashboard/bots/seed/",
                         {"target_username": "trader_a"},
                         HTTP_HOST="127.0.0.1")
        made = AssetBotConfig.objects.filter(user=self.target)
        self.assertTrue(made.exists())
        self.assertTrue(all(c.name.startswith("starter_") for c in made))

    def test_arming_is_a_separate_choice(self):
        """Creating six configs is reversible bookkeeping; arming them puts
        a bot on the five-minute tick with real sizing behind it. Those two
        acts must not share a button."""
        from bot_program.models import AssetBotConfig
        self.client.post("/admin-dashboard/bots/seed/",
                         {"target_username": "trader_a"},
                         HTTP_HOST="127.0.0.1")
        self.assertFalse(
            AssetBotConfig.objects.filter(user=self.target, enabled=True)
            .exists())

    def test_but_it_is_available(self):
        from bot_program.models import AssetBotConfig
        self.client.post("/admin-dashboard/bots/seed/",
                         {"target_username": "trader_a", "activate": "on"},
                         HTTP_HOST="127.0.0.1")
        self.assertTrue(
            AssetBotConfig.objects.filter(user=self.target, enabled=True)
            .exists())

    def test_running_it_twice_refreshes_rather_than_duplicates(self):
        from bot_program.models import AssetBotConfig
        for _ in range(2):
            self.client.post("/admin-dashboard/bots/seed/",
                             {"target_username": "trader_a"},
                             HTTP_HOST="127.0.0.1")
        names = list(AssetBotConfig.objects.filter(user=self.target)
                     .values_list("name", flat=True))
        self.assertEqual(len(names), len(set(names)))

    def test_an_unknown_user_is_refused_by_name(self):
        res = self.client.post("/admin-dashboard/bots/seed/",
                               {"target_username": "nobody"},
                               HTTP_HOST="127.0.0.1", follow=True)
        self.assertIn("no user named", res.content.decode())

    def test_a_non_superuser_cannot_seed_anyone(self):
        self.client.force_login(self.target)
        res = self.client.post("/admin-dashboard/bots/seed/",
                               {"target_username": "trader_a"},
                               HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 403)

    def test_a_get_does_nothing(self):
        """A state change behind a link is a state change a crawler makes."""
        res = self.client.get("/admin-dashboard/bots/seed/",
                              HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 405)


class NoFormAsksForATypedUsernameTests(TestCase):
    """"what to put for username?" was asked about a text box. A text box
    cannot answer it; the list of real accounts can — and it removes the
    whole class of typo that redirects with "no user named 'sauron '"."""

    def setUp(self):
        self.admin = _admin("hq_admin2")
        self.client.force_login(self.admin)
        User.objects.create_user("trader_b", password="x")

    def _page(self):
        return self.client.get("/admin-dashboard/",
                               HTTP_HOST="127.0.0.1").content.decode()

    def test_the_free_text_field_is_gone(self):
        body = self._page()
        self.assertNotIn('name="target_username" placeholder=', body)

    def test_every_form_offers_the_real_accounts(self):
        body = self._page()
        self.assertIn('<option value="trader_b">', body)
        self.assertIn("— pick an account —", body)

    def test_the_admin_is_marked_in_the_list(self):
        """Picking the wrong account is how credentials end up on a user
        who cannot use them."""
        self.assertIn("· admin", self._page())


class TheCardsSayWhereMoneyCanBeLostTests(TestCase):
    """The broker table answered "which brokers exist", so an account with
    a funded OANDA row and no bots looked identical to one ready to trade,
    and an account on the simulator looked identical to one wired live."""

    def setUp(self):
        _seed_instruments()
        self.admin = _admin("hq_admin3")
        self.client.force_login(self.admin)
        self.u = User.objects.create_user("trader_c", password="x")

    def _pages(self):
        return [self.client.get(p, HTTP_HOST="127.0.0.1").content.decode()
                for p in ("/admin-dashboard/", "/admin-dashboard/eye/")]

    def test_an_account_with_no_broker_reads_as_paper_only(self):
        for body in self._pages():
            self.assertIn("PAPER ONLY", body)

    def test_a_live_broker_is_marked_on_the_card(self):
        from bot_program.models import OANDAAccount
        acct = OANDAAccount.objects.create(user=self.u, practice=False)
        acct.set_credentials("k", "101-1")
        acct.save()
        for body in self._pages():
            self.assertIn("LIVE MONEY", body)

    def test_a_practice_broker_is_not(self):
        from bot_program.models import OANDAAccount
        acct = OANDAAccount.objects.create(user=self.u, practice=True)
        acct.set_credentials("k", "101-1")
        acct.save()
        for body in self._pages():
            self.assertNotIn("LIVE MONEY", body)

    def test_a_broker_row_with_no_credentials_is_not_counted_as_live(self):
        """A row somebody started and did not finish is not a venue."""
        from bot_program.models import OANDAAccount
        OANDAAccount.objects.create(user=self.u, practice=False)
        for body in self._pages():
            self.assertNotIn("LIVE MONEY", body)

    def test_ibkr_hover_carries_the_socket_that_routes_the_order(self):
        """The port is what selects the account. A card that names the
        broker and not the socket has not said which money moves."""
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(user=self.u, host="ibgateway",
                                          port=4001, client_id=3)
        acct.set_credentials("U1234567")
        acct.save()
        for body in self._pages():
            self.assertIn("ibgateway:4001", body)
            self.assertIn("client 3", body)

    def test_a_paper_flag_disagreeing_with_the_port_is_flagged(self):
        """`paper` is documented as informational; the PORT decides. When
        they disagree, the card says so rather than picking one."""
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(user=self.u, host="ibgateway",
                                          port=4001, paper=True)
        acct.set_credentials("U1234567")
        acct.save()
        for body in self._pages():
            self.assertIn("PORT is what routes the order", body)

    def test_armed_bots_are_shown_against_the_total(self):
        """Six configs that exist and none armed is a fleet doing nothing,
        and it should not read the same as six running."""
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.create(
            user=self.u, asset_class="forex", name="starter_fx",
            mode="paper", symbols=["EURUSD"], capital=Decimal("1000"),
            enabled=False)
        for body in self._pages():
            self.assertIn("BOTS ARMED", body)
            self.assertIn("0<small>/1</small>", body)

    def test_the_card_links_into_that_accounts_book_row(self):
        for body in self._pages():
            self.assertIn("#book-trader_c", body)

    def test_the_book_row_is_addressable(self):
        """The anchor the cards link into. Without it the jump lands at the
        top of a table the operator then has to find the name in."""
        from bot_program.models import AssetBotConfig
        # ENABLED: the books page pools only armed configs, because a
        # disabled bot has no book. A card linking to an account with no
        # book is a separate question from whether the anchor works.
        AssetBotConfig.objects.create(
            user=self.u, asset_class="forex", name="starter_fx_majors",
            mode="paper", symbols=["EURUSD"], capital=Decimal("1000"),
            enabled=True)
        body = self.client.get("/admin-dashboard/books/",
                               HTTP_HOST="127.0.0.1").content.decode()
        self.assertIn('id="book-trader_c"', body)

    def test_one_anchor_per_trader_not_one_per_row(self):
        """The table is one row per (trader, MODE, currency), so a user
        holding both a paper and a live book gets several rows — and a
        repeated id is invalid HTML that sends every link to whichever the
        browser saw first."""
        from bot_program.models import AssetBotConfig
        for mode in ("paper", "live"):
            AssetBotConfig.objects.create(
                user=self.u, asset_class="forex", name=f"starter_{mode}",
                mode=mode, symbols=["EURUSD"], capital=Decimal("1000"),
                enabled=True)
        body = self.client.get("/admin-dashboard/books/",
                               HTTP_HOST="127.0.0.1").content.decode()
        self.assertEqual(body.count('id="book-trader_c"'), 1)

    def test_an_account_with_no_fleet_is_offered_one_in_place(self):
        body = self.client.get("/admin-dashboard/",
                               HTTP_HOST="127.0.0.1").content.decode()
        self.assertIn("Give this account the starter fleet", body)
