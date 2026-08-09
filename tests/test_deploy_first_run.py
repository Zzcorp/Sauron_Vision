"""What a first deploy actually needs in order to work.

Every test here corresponds to something that was broken on a fresh box and
that no existing test noticed, because they all ran against a database and a
settings module a developer had already made work by hand.

Run with:  python manage.py test tests.test_deploy_first_run
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase


REPO = Path(settings.BASE_DIR)
COMPOSE = REPO / "deploy" / "docker-compose.yml"


def _yaml():
    try:
        import yaml
        return yaml
    except ImportError:
        return None


class TradingPinTests(TestCase):
    """The PIN gates every money-arming action. On a fresh install there was
    no way to set one: the modal called three functions that did not exist,
    and a bare `except` reported "profile module unavailable". No PIN meant
    no bot could ever be flipped to live."""

    def setUp(self):
        self.user = User.objects.create_user(username="pin_u", password="x")
        self.client.force_login(self.user)

    def test_a_fresh_user_can_set_a_first_pin(self):
        r = self.client.post("/profile/change-pin-modal/", {
            "current_pin": "", "new_pin": "4321", "confirm_pin": "4321"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"], msg=r.json())

        from portfolio.trader_profile import get_or_create_profile
        profile = get_or_create_profile(self.user)
        self.assertTrue(profile.has_pin)
        self.assertTrue(profile.check_pin("4321"))

    def test_the_raw_pin_is_never_stored(self):
        self.client.post("/profile/change-pin-modal/", {
            "current_pin": "", "new_pin": "4321", "confirm_pin": "4321"})
        from portfolio.trader_profile import get_or_create_profile
        self.assertNotIn("4321", get_or_create_profile(self.user).access_pin_hash)

    def test_changing_a_pin_requires_the_current_one(self):
        self.client.post("/profile/change-pin-modal/", {
            "current_pin": "", "new_pin": "4321", "confirm_pin": "4321"})
        r = self.client.post("/profile/change-pin-modal/", {
            "current_pin": "0000", "new_pin": "9999", "confirm_pin": "9999"})
        self.assertFalse(r.json()["ok"])
        from portfolio.trader_profile import get_or_create_profile
        self.assertTrue(get_or_create_profile(self.user).check_pin("4321"))

    def test_an_unset_pin_does_not_match_everything(self):
        """check_pin on a profile with no PIN must be False, not truthy by
        accident -- otherwise "no PIN set" quietly means "no second factor"."""
        from portfolio.trader_profile import get_or_create_profile
        profile = get_or_create_profile(self.user)
        self.assertFalse(profile.check_pin(""))
        self.assertFalse(profile.check_pin("0000"))

    def test_a_short_or_non_numeric_pin_is_refused(self):
        for bad in ("123", "abcd", ""):
            r = self.client.post("/profile/change-pin-modal/", {
                "current_pin": "", "new_pin": bad, "confirm_pin": bad})
            self.assertFalse(r.json()["ok"], msg=f"accepted {bad!r}")

    def test_get_or_create_profile_is_idempotent(self):
        from portfolio.trader_profile import TraderProfile, get_or_create_profile
        get_or_create_profile(self.user)
        get_or_create_profile(self.user)
        self.assertEqual(TraderProfile.objects.filter(user=self.user).count(), 1)


class ProductionSettingsTests(TestCase):
    def test_the_health_probe_is_reachable_from_the_loopback(self):
        """The container healthcheck speaks plain HTTP to 127.0.0.1. With
        ALLOWED_HOSTS set to the domain it got a 400, and with
        SECURE_SSL_REDIRECT a 301 to a port with no TLS on it -- so the
        service reported unhealthy forever."""
        self.assertIn("127.0.0.1", settings.ALLOWED_HOSTS)
        self.assertIn("localhost", settings.ALLOWED_HOSTS)

    def test_allowed_hosts_entries_are_stripped(self):
        for host in settings.ALLOWED_HOSTS:
            self.assertEqual(host, host.strip())

    def test_celery_waits_for_a_broker_that_is_not_up_yet(self):
        self.assertTrue(settings.CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP)

    def test_production_never_degrades_to_in_memory_infrastructure(self):
        """A container that starts during a brief Redis outage -- a reboot,
        which unattended-upgrades causes -- used to pin itself to LocMemCache,
        an InMemoryChannelLayer and a filesystem broker for its whole life,
        report healthy, and silently stop running scheduled work."""
        src = (REPO / "config" / "settings.py").read_text(
            encoding="utf-8", errors="replace")
        probe = src[src.index("REDIS_URL = "):src.index("if _redis_available:")]
        self.assertIn("if DEBUG:", probe)
        self.assertIn("_redis_available = True", probe.split("else:")[-1])


class FirstBootDataTests(TestCase):
    def test_the_stack_seeds_instruments_before_anything_starts(self):
        """With zero Instrument rows the bar feed writes nothing, and the
        broker router defaults every unknown symbol to crypto/Binance."""
        if _yaml() is None:
            self.skipTest("PyYAML not installed")
        cmd = str(_yaml().safe_load(COMPOSE.read_text(encoding="utf-8"))
                  ["services"]["migrate"]["command"])
        self.assertIn("seed_instruments", cmd)
        self.assertIn("seed_components", cmd)

    def test_seed_instruments_exists_and_is_idempotent(self):
        from django.core.management import call_command
        from instruments.models import Instrument
        call_command("seed_instruments", verbosity=0)
        first = Instrument.objects.count()
        self.assertGreater(first, 0)
        call_command("seed_instruments", verbosity=0)
        self.assertEqual(Instrument.objects.count(), first)


class BackupPathTests(TestCase):
    def test_no_in_app_backup_task_is_scheduled(self):
        """core.backups shells out to pg_dump, which is not in the app image,
        and returned ok=False instead of raising -- so it recorded a SUCCESS
        every night while producing nothing at all."""
        from config.celery import app
        self.assertNotIn("daily-postgres-backup", app.conf.beat_schedule)

    def test_the_backup_service_has_rclone_and_is_not_optional(self):
        if _yaml() is None:
            self.skipTest("PyYAML not installed")
        svc = _yaml().safe_load(
            COMPOSE.read_text(encoding="utf-8"))["services"]["backup"]
        self.assertNotIn("profiles", svc,
                         msg="the only real backup path must not be opt-in")
        self.assertIn("Dockerfile.backup", str(svc.get("build")))
        text = (REPO / "deploy" / "Dockerfile.backup").read_text(encoding="utf-8")
        self.assertIn("rclone", text)

    def test_the_offsite_target_is_verified_before_the_first_dump(self):
        sh = (REPO / "deploy" / "backup.sh").read_text(encoding="utf-8")
        preflight = sh[:sh.index("while true")]
        self.assertIn("rclone lsd", preflight,
                      msg="a misnamed remote must fail loudly, not at restore time")


class ComposeInvocationTests(TestCase):
    def test_every_documented_command_passes_env_file(self):
        """Compose interpolates ${VAR} from the compose file's directory, not
        the repo root where the runbook puts .env. Without --env-file the very
        first command aborts saying DB_PASSWORD is unset while it is set."""
        runbook = (REPO / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        bad = [ln.strip() for ln in runbook.splitlines()
               if "docker compose" in ln and "--env-file" not in ln
               and "-f deploy/docker-compose.yml" in ln]
        self.assertEqual(bad, [], msg=f"missing --env-file: {bad}")

    def test_the_database_name_and_user_cannot_silently_diverge(self):
        """A `:-` default let Postgres initialise one database while Django
        read another from .env -- and once pgdata exists that is only fixable
        by destroying the volume."""
        text = COMPOSE.read_text(encoding="utf-8")
        for var in ("DB_NAME", "DB_USER", "DB_PASSWORD"):
            self.assertNotIn("${" + var + ":-", text,
                             msg=f"{var} has a default that can diverge from .env")


class ImageHygieneTests(TestCase):
    def test_a_dockerignore_keeps_secrets_out_of_the_image(self):
        text = (REPO / ".dockerignore").read_text(encoding="utf-8")
        for entry in (".env", ".git", "db.sqlite3", ".celery/"):
            self.assertIn(entry, text)

    def test_static_files_are_baked_into_the_image(self):
        """collectstatic in the one-shot migrate service wrote into a
        filesystem that is then discarded, leaving web with nothing to serve
        and the whole app unstyled behind a valid certificate."""
        text = (REPO / "Dockerfile.prod").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("collectstatic", text)
        self.assertIn("DB_ENGINE=sqlite ", text,
                      msg="must match the settings branch exactly, not sqlite3")
        if _yaml() is not None:
            cmd = str(_yaml().safe_load(COMPOSE.read_text(encoding="utf-8"))
                      ["services"]["migrate"]["command"])
            self.assertNotIn("collectstatic", cmd)

    def test_the_image_declares_no_healthcheck_the_workers_cannot_answer(self):
        text = (REPO / "Dockerfile.prod").read_text(
            encoding="utf-8", errors="replace")
        self.assertNotIn("\nHEALTHCHECK", text)

    def test_ibkr_support_is_actually_installed(self):
        """ib_insync is imported by the broker router; without it the import
        fails, the router falls back to PaperTrader, and a bot the UI labels
        "ibkr" records paper fills as if they were real."""
        reqs = (REPO / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(reqs, r"(?mi)^ib[_-]insync")
