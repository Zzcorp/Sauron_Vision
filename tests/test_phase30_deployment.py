"""Deployment-stack smoke tests.

We can't `docker build` from a Django test (needs Docker on the host and
several minutes). What we CAN check is that the one production stack under
`deploy/` is internally consistent — which is exactly where the previous
four rival compose files went wrong: each was individually plausible and
they disagreed with each other about database names, queue flags and env
files, so following any one of them led into a wall part-way through.

These tests pin the invariants that make the stack followable:
  - the files exist where the runbook says they are
  - the compose parses and names every service the runbook references
  - every Celery queue in the routing table has a worker consuming it
  - production doesn't bind-mount source or publish the database port
  - .env.production.example documents what compose demands

Run with:  python manage.py test tests.test_phase30_deployment
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase


REPO = Path(settings.BASE_DIR)
DEPLOY = REPO / "deploy"
COMPOSE = DEPLOY / "docker-compose.yml"


def _yaml():
    try:
        import yaml
        return yaml
    except ImportError:
        return None


class DeploymentFilesExistTests(TestCase):
    def test_dockerfile_prod_exists(self):
        self.assertTrue((REPO / "Dockerfile.prod").is_file())

    def test_single_production_compose_exists(self):
        self.assertTrue(COMPOSE.is_file())

    def test_no_rival_compose_files_remain(self):
        """One stack, one file. A second prod compose is how the old set
        drifted out of agreement in the first place."""
        for stale in ("docker-compose.prod.yml", "docker-compose.production.yml",
                      "docker-compose.vps.yml"):
            self.assertFalse((REPO / stale).exists(),
                             msg=f"{stale} is back — the stack has forked again")

    def test_caddyfile_exists(self):
        self.assertTrue((DEPLOY / "Caddyfile").is_file())

    def test_runbook_exists(self):
        self.assertTrue((DEPLOY / "RUNBOOK.md").is_file())

    def test_backup_script_exists(self):
        self.assertTrue((DEPLOY / "backup.sh").is_file())

    def test_no_second_migration_path_exists(self):
        """scripts/entrypoint.sh ran `migrate` on every container start and
        was wired to nothing — not the Dockerfile, not compose. A dead
        script that does the wrong thing is worse than no script: the next
        person to need an entrypoint finds it and wires it up, restoring
        the very race the one-shot `migrate` service exists to prevent."""
        self.assertFalse((REPO / "scripts" / "entrypoint.sh").exists())

    def test_env_production_example_exists(self):
        self.assertTrue((REPO / ".env.production.example").is_file())


class DockerfileProdStructureTests(TestCase):
    def setUp(self):
        self.text = (REPO / "Dockerfile.prod").read_text(encoding="utf-8")

    def test_uses_multi_stage_build(self):
        self.assertIn("AS builder", self.text)
        self.assertIn("AS runtime", self.text)

    def test_creates_non_root_user(self):
        self.assertIn("useradd", self.text)
        self.assertIn("USER sauron", self.text)

    def test_sets_django_settings_module(self):
        self.assertIn("DJANGO_SETTINGS_MODULE", self.text)

    def test_default_cmd_serves_asgi(self):
        # ASGI, not WSGI — Channels carries the Eye WebSocket.
        self.assertIn("config.asgi:application", self.text)

    def test_has_healthcheck(self):
        self.assertIn("HEALTHCHECK", self.text)

    def test_references_the_real_compose_path(self):
        """A comment pointing at a file that no longer exists is how an
        operator ends up running a stack that was deleted."""
        self.assertNotIn("docker-compose.prod.yml", self.text)


class ComposeProdStructureTests(TestCase):
    def setUp(self):
        self.text = COMPOSE.read_text(encoding="utf-8")
        yaml = _yaml()
        self.data = yaml.safe_load(self.text) if yaml else None

    def test_compose_yaml_parses(self):
        if self.data is None:
            self.skipTest("PyYAML not installed")
        self.assertIn("services", self.data)
        self.assertIn("volumes", self.data)

    def test_all_required_services_present(self):
        if self.data is None:
            self.skipTest("PyYAML not installed")
        for svc in ("postgres", "redis", "migrate", "web",
                    "worker-fast", "worker-slow", "beat", "caddy"):
            self.assertIn(svc, self.data["services"],
                          msg=f"Service '{svc}' missing from the stack")

    def test_every_celery_queue_has_a_consumer(self):
        """config/celery.py routes tasks to fast/slow/ai and everything else
        to `default`. A worker set that misses one queue drops that slice of
        the schedule on the floor, silently — the tasks just queue forever."""
        if self.data is None:
            self.skipTest("PyYAML not installed")
        consumed = set()
        for name, svc in self.data["services"].items():
            cmd = svc.get("command") or ""
            if isinstance(cmd, list):
                cmd = " ".join(cmd)
            if "celery" not in cmd or " worker" not in cmd:
                continue
            m = re.search(r"-Q\s+([\w,]+)", cmd)
            if m:
                consumed.update(m.group(1).split(","))
        self.assertEqual({"fast", "slow", "ai", "default"} - consumed, set(),
                         msg=f"queues consumed: {sorted(consumed)}")

    def test_migrations_run_once_before_the_app_starts(self):
        """Racing `migrate` in every service's entrypoint is how beat starts
        against tables django_celery_beat hasn't created yet."""
        if self.data is None:
            self.skipTest("PyYAML not installed")
        migrate = self.data["services"]["migrate"]
        self.assertIn("migrate", str(migrate.get("command", "")))
        # And it must be the ONLY thing that migrates.
        for name, svc in self.data["services"].items():
            if name == "migrate":
                continue
            cmd = svc.get("command") or ""
            if isinstance(cmd, list):
                cmd = " ".join(cmd)
            self.assertNotIn("manage.py migrate", cmd,
                             msg=f"{name} migrates too — that is the race")
        for svc in ("web", "worker-fast", "beat"):
            depends = self.data["services"][svc].get("depends_on") or {}
            self.assertIn("migrate", depends,
                          msg=f"{svc} may start before migrations finish")
            self.assertEqual(depends["migrate"]["condition"],
                             "service_completed_successfully")

    def test_all_django_services_share_one_redis(self):
        """The streamers publish into a pub/sub channel the web process
        subscribes to. Split them across Redis instances and browser updates
        stop arriving with nothing in any log to say why."""
        if self.data is None:
            self.skipTest("PyYAML not installed")
        urls = {svc["environment"]["REDIS_URL"]
                for svc in self.data["services"].values()
                if isinstance(svc.get("environment"), dict)
                and "REDIS_URL" in svc["environment"]}
        # Exactly one, not "at most one": an empty set would mean no service
        # configures Redis at all, which this assertion must not call a pass.
        self.assertEqual(len(urls), 1, msg=f"REDIS_URLs seen: {urls}")
        for svc in ("web", "worker-fast", "worker-slow", "beat"):
            self.assertIn("REDIS_URL",
                          self.data["services"][svc].get("environment") or {},
                          msg=f"{svc} does not pin REDIS_URL")

    def test_no_source_bind_mount_on_any_app_service(self):
        """Production must not bind-mount the source — the image is the
        artefact, or a deploy means 'whatever happens to be on the box'.
        Checks the parsed volumes of every service, not two literal strings
        that any reformatting of the file would slip past."""
        if self.data is None:
            self.skipTest("PyYAML not installed")
        for name, svc in self.data["services"].items():
            for vol in (svc.get("volumes") or []):
                target = (vol.split(":")[1] if isinstance(vol, str)
                          and ":" in vol else "")
                self.assertNotEqual(
                    target, "/app",
                    msg=f"{name} bind-mounts source over /app: {vol}")

    def test_postgres_port_not_exposed(self):
        if self.data is None:
            self.skipTest("PyYAML not installed")
        self.assertNotIn("ports", self.data["services"]["postgres"])

    def test_only_the_tls_terminator_publishes_ports(self):
        if self.data is None:
            self.skipTest("PyYAML not installed")
        publishing = {n for n, s in self.data["services"].items() if s.get("ports")}
        self.assertEqual(publishing, {"caddy"})

    def test_restart_unless_stopped_present(self):
        self.assertIn("unless-stopped", self.text)

    def test_healthchecks_on_db_and_redis(self):
        if self.data is None:
            self.skipTest("PyYAML not installed")
        for svc in ("postgres", "redis", "web"):
            self.assertIn("healthcheck", self.data["services"][svc],
                          msg=f"{svc} has no healthcheck")

    def test_only_the_streamers_are_behind_profiles(self):
        """A first deploy should have as few moving parts as possible, so the
        market-data streamers are opt-in. Backups are NOT: "optional extras"
        is the wrong category for the only thing standing between a disk
        failure and losing every trade, position and credential recorded."""
        if self.data is None:
            self.skipTest("PyYAML not installed")
        for svc in ("stream-binance", "stream-oanda"):
            self.assertIn("streamers",
                          self.data["services"][svc].get("profiles", []))
        for name, svc in self.data["services"].items():
            if svc.get("profiles") and not name.startswith("stream-"):
                self.fail(f"{name} is opt-in but should start with the stack")

    def test_data_lives_on_named_volumes(self):
        if self.data is None:
            self.skipTest("PyYAML not installed")
        for vol in ("pgdata", "redisdata", "caddydata"):
            self.assertIn(vol, self.data["volumes"])


class CaddyfileTests(TestCase):
    def setUp(self):
        self.text = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")

    def test_proxies_to_the_web_service(self):
        self.assertIn("web:8000", self.text)

    def test_domain_is_configurable(self):
        # Auto-TLS needs the real hostname; hard-coding one makes the file
        # unusable for anyone else.
        self.assertIn("{$DOMAIN", self.text)

    def test_forwarded_proto_is_set_on_the_upstream(self):
        """Django only honours SECURE_PROXY_SSL_HEADER when the proxy sets
        it. Without this header the app believes every request is plain
        HTTP behind an HTTPS terminator and answers with a redirect to
        HTTPS — a loop that takes the whole site down, TLS certificate and
        all."""
        self.assertIn("X-Forwarded-Proto", self.text)
        self.assertIn("header_up Host", self.text)


class EnvExampleCoverageTests(TestCase):
    """Every env var compose demands should appear in the example file, or
    the first `up -d` fails on a variable nobody knew to set."""

    def setUp(self):
        self.compose = COMPOSE.read_text(encoding="utf-8")
        self.env_example = (REPO / ".env.production.example").read_text(encoding="utf-8")

    def test_required_vars_are_documented(self):
        for var in ("DB_PASSWORD", "SECRET_KEY", "DOMAIN"):
            self.assertIn(f"{var}=", self.env_example,
                          msg=f"{var} is required but undocumented")

    def test_every_mandatory_compose_var_is_documented(self):
        """`${VAR:?...}` in compose means 'refuse to start without this'."""
        for var in set(re.findall(r"\$\{(\w+):\?", self.compose)):
            self.assertIn(f"{var}=", self.env_example,
                          msg=f"compose demands {var} but the example omits it")

    def test_example_does_not_ship_a_usable_secret(self):
        """A placeholder that looks like a key is one someone will deploy."""
        for line in self.env_example.splitlines():
            if line.startswith("SECRET_KEY="):
                value = line.split("=", 1)[1].strip()
                self.assertTrue(
                    not value or "change" in value.lower()
                    or "generate" in value.lower() or "your" in value.lower(),
                    msg="SECRET_KEY example looks like a real key")
