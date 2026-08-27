"""IB Gateway reachable by name, and reachable by nobody else.

IBKR speaks a socket rather than an API key, so something has to be
logged in and listening. `127.0.0.1` in the admin form means the Sauron
container itself — the one place nothing is listening — and the runbook's
own answer, `host.docker.internal`, resolved to nothing because the
compose anchor never declared it.

Running Gateway inside the stack removes the whole class of problem: no
bridge address to look up (and it is NOT the docker0 address — compose
builds its own network), no ufw rule for the docker subnet, no virtual
display, no trusted-IP list. The host field becomes `ibgateway`.

The two things that must stay true are both about blast radius: the
trading socket is never published to the host, and the profile cannot
break a stack that does not use IBKR.

Run with:  python manage.py test tests.test_ibkr_gateway_service
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

REPO = Path(settings.BASE_DIR)
COMPOSE = REPO / "deploy" / "docker-compose.yml"


def _compose():
    import yaml
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


class TheSocketIsNeverPublishedTests(SimpleTestCase):
    """4001 and 4002 accept unauthenticated, unencrypted orders from
    anyone who can reach them."""

    def test_no_ports_are_mapped_to_the_host(self):
        svc = _compose()["services"]["ibgateway"]
        self.assertFalse(svc.get("ports"),
                         "a trading socket must not be on the public IP")

    def test_it_is_on_the_compose_network_where_sauron_can_reach_it(self):
        """No explicit networks key means the default compose network —
        which is exactly where the web and worker containers are."""
        svc = _compose()["services"]["ibgateway"]
        self.assertNotIn("network_mode", svc)


class ItCannotBreakAStackThatDoesNotUseItTests(SimpleTestCase):
    def test_it_is_opt_in(self):
        self.assertIn("ibkr",
                      _compose()["services"]["ibgateway"].get("profiles", []))

    def test_its_variables_are_not_demanded_at_parse_time(self):
        """Compose interpolates the WHOLE file before it looks at
        profiles, so a required-variable marker here would refuse to
        start the stack for every operator who never opts in."""
        raw = COMPOSE.read_text(encoding="utf-8")
        for var in ("IBKR_USERNAME", "IBKR_PASSWORD"):
            self.assertNotIn("${%s:?" % var, raw)
            self.assertIn("${%s:-" % var, raw)

    def test_the_trading_mode_defaults_to_paper(self):
        raw = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("${IBKR_TRADING_MODE:-paper}", raw)


class TheDocumentedHostRouteResolvesTests(SimpleTestCase):
    """The runbook told operators to use host.docker.internal for a
    Gateway running on the box. Nothing declared it, so it timed out."""

    def test_every_app_service_can_resolve_the_host(self):
        services = _compose()["services"]
        for name in ("web", "worker-fast", "worker-slow", "beat"):
            self.assertIn("host.docker.internal:host-gateway",
                          services[name].get("extra_hosts", []), name)


class TheOperatorIsToldWhatToSetTests(SimpleTestCase):
    def test_both_env_examples_document_the_variables(self):
        for name in (".env.example", ".env.production.example"):
            text = (REPO / name).read_text(encoding="utf-8")
            for var in ("IBKR_USERNAME=", "IBKR_PASSWORD=",
                        "IBKR_TRADING_MODE="):
                self.assertIn(var, text, f"{name} omits {var}")

    def test_the_runbook_names_the_host_field_value(self):
        text = (REPO / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("--profile ibkr", text)
        self.assertIn("`ibgateway`", text)

    def test_the_runbook_warns_about_the_single_session_limit(self):
        """Logging into the IBKR portal with the same credentials kicks
        Gateway out mid-session — a surprise worth spending a line on."""
        text = (REPO / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("One session per IBKR username", text)

    def test_the_runbook_pairs_each_mode_with_its_port(self):
        """paper/4002 and live/4001 must agree or the socket never
        answers, which looks exactly like a network fault."""
        text = (REPO / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("4002", text)
        self.assertIn("4001", text)
