"""Ops config + the deployment contract.

The deployment used to be four contradictory definitions; these tests pin
the one that survives, and cover the two settings that were documented but
never implemented (FERNET_KEY, EMAIL_*).

Run with:  python manage.py test tests.test_deploy_and_ops
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

BASE = Path(settings.BASE_DIR)


# ── broker-credential encryption ────────────────────────────────────────

class FernetKeyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="fk_u", password="x")

    def _account(self):
        from bot_program.models import BinanceAccount
        return BinanceAccount.objects.create(user=self.user)

    def test_credentials_round_trip(self):
        acct = self._account()
        acct.set_credentials("key123", "secret456")
        acct.save()
        self.assertEqual(acct.get_credentials(), ("key123", "secret456"))

    def test_credentials_survive_a_secret_key_rotation(self):
        """The whole point: rotating SECRET_KEY (or moving host) used to
        make every stored broker credential permanently undecryptable."""
        from cryptography.fernet import Fernet
        fernet_key = Fernet.generate_key().decode()

        with override_settings(FERNET_KEY=fernet_key):
            acct = self._account()
            acct.set_credentials("key123", "secret456")
            acct.save()

        with override_settings(FERNET_KEY=fernet_key,
                                SECRET_KEY="a-completely-different-secret"):
            acct.refresh_from_db()
            self.assertEqual(acct.get_credentials(), ("key123", "secret456"))

    def test_legacy_rows_still_decrypt_after_fernet_key_is_introduced(self):
        """Credentials written before FERNET_KEY existed were encrypted with
        a SECRET_KEY-derived key; introducing FERNET_KEY must not orphan
        them."""
        from cryptography.fernet import Fernet

        with override_settings(FERNET_KEY=""):
            acct = self._account()
            acct.set_credentials("legacy_key", "legacy_secret")
            acct.save()

        with override_settings(FERNET_KEY=Fernet.generate_key().decode()):
            acct.refresh_from_db()
            self.assertEqual(acct.get_credentials(),
                             ("legacy_key", "legacy_secret"))

    def test_unreadable_credentials_return_none_not_garbage(self):
        from cryptography.fernet import Fernet
        with override_settings(FERNET_KEY=Fernet.generate_key().decode()):
            acct = self._account()
            acct.set_credentials("k", "s")
            acct.save()
        # Both keys replaced — nothing can decrypt this row.
        with override_settings(FERNET_KEY=Fernet.generate_key().decode(),
                                SECRET_KEY="another"):
            acct.refresh_from_db()
            self.assertEqual(acct.get_credentials(), (None, None))


# ── email ───────────────────────────────────────────────────────────────

class EmailSettingsTests(TestCase):
    def test_email_settings_exist(self):
        """settings.py defined no EMAIL_* at all, so Django fell back to
        SMTP localhost:25 and every production email failed silently."""
        for name in ("EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER",
                     "EMAIL_HOST_PASSWORD", "EMAIL_USE_TLS",
                     "DEFAULT_FROM_EMAIL", "EMAIL_BACKEND"):
            self.assertTrue(hasattr(settings, name), name)

    def test_console_backend_when_no_smtp_host(self):
        """Read the settings MODULE, not django.conf.settings: the test
        harness patches the runtime EMAIL_BACKEND to locmem, so the
        runtime value can never show what settings.py decided. (Locally
        an EMAIL_HOST in .env made this vacuously pass; CI has none and
        saw the locmem patch.)"""
        import importlib
        smod = importlib.import_module("config.settings")
        if not smod.EMAIL_HOST:
            self.assertIn("console", smod.EMAIL_BACKEND)

    def test_mail_is_actually_deliverable_in_tests(self):
        from django.core import mail
        mail.send_mail("subject", "body", settings.DEFAULT_FROM_EMAIL,
                       ["someone@example.com"])
        self.assertEqual(len(mail.outbox), 1)


# ── the deployment contract ─────────────────────────────────────────────

class DeploymentStackTests(TestCase):
    def setUp(self):
        import yaml
        self.compose = yaml.safe_load(
            (BASE / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
        self.services = self.compose["services"]

    def test_exactly_one_production_definition(self):
        """Four rival definitions (render.yaml, two composes, systemd units)
        disagreed about DB names, queue flags and env files."""
        self.assertFalse((BASE / "render.yaml").exists())
        self.assertFalse((BASE / "docker-compose.prod.yml").exists())
        self.assertFalse((BASE / "deploy" / "systemd").exists())

    def test_workers_between_them_consume_every_queue(self):
        """config/celery.py routes to fast/slow/ai and defaults the rest to
        `default`. A worker set that misses a queue silently drops that part
        of the beat schedule."""
        from config.celery import app

        covered = set()
        for name, svc in self.services.items():
            cmd = svc.get("command") or ""
            if "celery" in cmd and "worker" in cmd and "-Q" in cmd:
                queues = cmd.split("-Q")[1].split()[0]
                covered.update(q.strip() for q in queues.split(","))

        required = {app.conf.task_default_queue}
        for route in app.conf.task_routes.values():
            required.add(route["queue"])
        self.assertTrue(required <= covered,
                        f"queues not consumed by any worker: {required - covered}")

    def test_every_service_shares_one_redis(self):
        """Streamers publish into a Redis pub/sub channel the web process
        subscribes to; split them and browser updates never arrive."""
        urls = {svc["environment"]["REDIS_URL"]
                for svc in self.services.values()
                if isinstance(svc.get("environment"), dict)
                and "REDIS_URL" in svc["environment"]}
        self.assertEqual(len(urls), 1, f"multiple Redis targets: {urls}")

    def test_migrations_run_once_and_others_wait(self):
        migrate = self.services["migrate"]
        self.assertIn("migrate --noinput", migrate["command"])
        for name in ("web", "worker-fast", "worker-slow", "beat"):
            depends = self.services[name]["depends_on"]
            self.assertEqual(depends["migrate"]["condition"],
                             "service_completed_successfully", name)

    def test_beat_uses_the_database_scheduler(self):
        self.assertIn("DatabaseScheduler", self.services["beat"]["command"])

    def test_only_the_streamers_are_opt_in(self):
        """Backups deliberately are NOT. "Optional extras" is the wrong
        category for the only thing standing between a disk failure and
        losing every trade, position and credential the platform recorded.

        A service earns a profile only when it needs credentials the
        operator may not have yet and would restart-loop without them:
        the streamers, and IB Gateway, which cannot log in without an
        IBKR username. The allowlist keeps that a deliberate decision.
        """
        may_be_opt_in_prefix = "ibgateway"
        for name, svc in self.services.items():
            if name.startswith("stream-"):
                self.assertTrue(svc.get("profiles"), name)
            elif not name.startswith(may_be_opt_in_prefix):
                self.assertFalse(svc.get("profiles"),
                                 msg=f"{name} must start with the stack")

    def test_required_secrets_fail_loudly_when_unset(self):
        raw = (BASE / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("${DB_PASSWORD:?", raw)
        self.assertIn("${DOMAIN:?", raw)

    def test_env_example_documents_every_required_key(self):
        raw = (BASE / ".env.production.example").read_text(encoding="utf-8")
        for key in ("SECRET_KEY", "FERNET_KEY", "DOMAIN", "ALLOWED_HOSTS",
                    "DB_NAME", "DB_USER", "DB_PASSWORD", "EMAIL_HOST",
                    "DEFAULT_FROM_EMAIL", "BACKUP_REMOTE"):
            self.assertIn(f"{key}=", raw, key)

    def test_runbook_exists(self):
        self.assertTrue((BASE / "deploy" / "RUNBOOK.md").exists())
        self.assertTrue((BASE / "deploy" / "Caddyfile").exists())
        self.assertTrue((BASE / "deploy" / "backup.sh").exists())
