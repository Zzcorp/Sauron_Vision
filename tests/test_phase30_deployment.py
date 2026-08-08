"""Phase-30 deployment-infrastructure smoke tests.

We can't actually `docker build` from a Django test (would require Docker on
the CI host + ~5 minutes). What we CAN check:
  - Required files exist with expected structure
  - docker-compose.prod.yml is valid YAML and references the right services
  - Dockerfile.prod has multi-stage build + non-root user
  - entrypoint.sh has the required steps
  - .env.production.example covers all env vars referenced by compose

Run with:  python manage.py test tests.test_phase30_deployment
"""
import os
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase


REPO = Path(settings.BASE_DIR)


class DeploymentFilesExistTests(TestCase):
    def test_dockerfile_prod_exists(self):
        self.assertTrue((REPO / "Dockerfile.prod").is_file())

    def test_compose_prod_exists(self):
        self.assertTrue((REPO / "docker-compose.prod.yml").is_file())

    def test_entrypoint_script_exists(self):
        ep = REPO / "scripts" / "entrypoint.sh"
        self.assertTrue(ep.is_file())

    def test_env_production_example_exists(self):
        self.assertTrue((REPO / ".env.production.example").is_file())


class DockerfileProdStructureTests(TestCase):
    def setUp(self):
        self.text = (REPO / "Dockerfile.prod").read_text()

    def test_uses_multi_stage_build(self):
        self.assertIn("AS builder", self.text)
        self.assertIn("AS runtime", self.text)

    def test_creates_non_root_user(self):
        self.assertIn("useradd", self.text)
        self.assertIn("USER sauron", self.text)

    def test_sets_django_settings_module(self):
        self.assertIn("DJANGO_SETTINGS_MODULE", self.text)

    def test_default_cmd_uses_uvicorn_worker(self):
        # ASGI for Channels (Phase 23 WS).
        self.assertIn("uvicorn.workers.UvicornWorker", self.text)
        self.assertIn("config.asgi:application", self.text)

    def test_has_healthcheck(self):
        self.assertIn("HEALTHCHECK", self.text)


class ComposeProdStructureTests(TestCase):
    def setUp(self):
        self.text = (REPO / "docker-compose.prod.yml").read_text()

    def _has_yaml_module(self):
        try:
            import yaml  # noqa: F401
            return True
        except ImportError:
            return False

    def test_compose_yaml_parses(self):
        if not self._has_yaml_module():
            self.skipTest("PyYAML not installed")
        import yaml
        data = yaml.safe_load(self.text)
        self.assertIn("services", data)
        self.assertIn("volumes", data)

    def test_all_required_services_present(self):
        for svc in ("db", "redis", "web",
                     "celery-worker-fast", "celery-worker-slow", "celery-beat"):
            self.assertIn(svc + ":", self.text,
                            msg=f"Service '{svc}' missing from compose")

    def test_no_source_bind_mount_on_web(self):
        """Production must not bind-mount the source — image is the artefact."""
        # The dev compose has `- .:/app`; prod should NOT.
        self.assertNotIn("- .:/app", self.text)

    def test_postgres_port_not_exposed(self):
        """Prod DB should not publish 5432 to the host."""
        # Heuristic — the dev file has `"5432:5432"` literally; prod should not.
        self.assertNotIn('"5432:5432"', self.text)

    def test_restart_unless_stopped_present(self):
        self.assertIn("unless-stopped", self.text)

    def test_log_caps_present(self):
        self.assertIn("max-size", self.text)
        self.assertIn("max-file", self.text)

    def test_healthchecks_on_db_and_redis(self):
        self.assertGreaterEqual(self.text.count("healthcheck:"), 2)


class EntrypointScriptTests(TestCase):
    def setUp(self):
        self.text = (REPO / "scripts" / "entrypoint.sh").read_text()

    def test_runs_migrations(self):
        self.assertIn("migrate", self.text)

    def test_runs_collectstatic(self):
        self.assertIn("collectstatic", self.text)

    def test_waits_for_db(self):
        # Should poll the DB before exec'ing the CMD.
        self.assertIn("psycopg2", self.text)

    def test_handsoff_to_cmd(self):
        # Last instruction should `exec "$@"` so signals reach the worker.
        self.assertIn('exec "$@"', self.text)

    def test_set_strict_mode(self):
        # `set -eu` so any failure aborts.
        self.assertRegex(self.text, r"(?m)^set\s+-[eu]+")


class EnvExampleCoverageTests(TestCase):
    """Every env var referenced from docker-compose.prod.yml should appear in
    .env.production.example so operators know what to set."""

    def setUp(self):
        self.compose = (REPO / "docker-compose.prod.yml").read_text()
        self.env_example = (REPO / ".env.production.example").read_text()

    def test_db_password_documented(self):
        self.assertIn("DB_PASSWORD", self.compose)
        self.assertIn("DB_PASSWORD=", self.env_example)

    def test_secret_key_documented(self):
        self.assertIn("SECRET_KEY=", self.env_example)

    def test_redis_url_documented(self):
        self.assertIn("REDIS_URL=", self.env_example)

    def test_celery_concurrency_documented(self):
        # If compose references it, env example should too.
        if "CELERY_FAST_CONCURRENCY" in self.compose:
            self.assertIn("CELERY_FAST_CONCURRENCY", self.env_example)
        if "CELERY_SLOW_CONCURRENCY" in self.compose:
            self.assertIn("CELERY_SLOW_CONCURRENCY", self.env_example)
