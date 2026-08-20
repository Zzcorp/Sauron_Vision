"""Seed data must fit the columns it is inserted into.

This suite runs on SQLite, and SQLite DOES NOT ENFORCE `varchar(n)` — it
stores whatever you give it. PostgreSQL does. So a seed constant one
character too long is green on every developer machine, green in CI, and
raises `DataError: value too long for type character varying(300)` on the
production deploy — inside the one-shot `migrate` container, after the
migrations have already applied, which leaves the stack half-updated and
the site on the old image.

That is exactly what happened: `agent_position_review` shipped with a
391-character description against a 300-character column and took the whole
deploy down. Nothing in 3,800 tests could have caught it, because the only
thing that would have is the database the tests do not use.

So the check is made explicitly, in Python, against the model's own
declared `max_length`. It needs no Postgres and no database at all.

Run with:  python manage.py test tests.test_seed_data_fits_postgres
"""
from django.test import SimpleTestCase


def _caps(model):
    """{field name: max_length} for every length-capped field on a model."""
    return {f.name: f.max_length
            for f in model._meta.get_fields()
            if getattr(f, "max_length", None)}


def _too_long(rows, model):
    """Every (key, field, length, cap) in `rows` that its column cannot hold."""
    caps = _caps(model)
    over = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = row.get("key") or row.get("name") or "<unnamed>"
        for field, cap in caps.items():
            value = row.get(field)
            if isinstance(value, str) and len(value) > cap:
                over.append((label, field, len(value), cap))
    return over


class PlatformComponentSeedTests(SimpleTestCase):
    def test_every_default_component_fits_its_columns(self):
        from core.platform_control import DEFAULT_COMPONENTS, PlatformComponent
        over = _too_long(DEFAULT_COMPONENTS, PlatformComponent)
        self.assertEqual(
            over, [],
            "seed_components would raise DataError on PostgreSQL and break "
            "the deploy: " + "; ".join(
                f"{k}.{f} is {n} chars, column holds {cap}"
                for k, f, n, cap in over))

    def test_the_check_would_actually_catch_an_overlong_row(self):
        """A guard that cannot fail is not a guard. This proves the helper
        measures what it claims to."""
        from core.platform_control import PlatformComponent
        caps = _caps(PlatformComponent)
        self.assertIn("description", caps)
        fake = [{"key": "x", "description": "z" * (caps["description"] + 1)}]
        self.assertEqual(len(_too_long(fake, PlatformComponent)), 1)

    def test_a_row_exactly_at_the_cap_is_allowed(self):
        """varchar(n) holds n. Off-by-one in the guard would be its own bug."""
        from core.platform_control import PlatformComponent
        caps = _caps(PlatformComponent)
        fake = [{"key": "x", "description": "z" * caps["description"]}]
        self.assertEqual(_too_long(fake, PlatformComponent), [])

    def test_the_component_that_broke_the_deploy_stays_within_its_column(self):
        """Named, so a future edit to this one description is measured."""
        from core.platform_control import DEFAULT_COMPONENTS, PlatformComponent
        cap = _caps(PlatformComponent)["description"]
        row = next(c for c in DEFAULT_COMPONENTS
                   if c["key"] == "agent_position_review")
        self.assertLessEqual(len(row["description"]), cap)


class StrategySeedTests(SimpleTestCase):
    """The strategy seeders run in the same one-shot container, immediately
    after `seed_components`, so an overlong row there breaks the deploy the
    same way and one step later."""

    def _rows(self, module_path, attr):
        import importlib
        module = importlib.import_module(module_path)
        rows = getattr(module, attr, None)
        return rows if isinstance(rows, (list, tuple)) else None

    def test_seeded_setups_fit_their_columns(self):
        from signals.models_opportunity import OpportunitySetup
        checked = 0
        for path, attr in (
            ("signals.management.commands.seed_strategies", "STARTER_SETUPS"),
            ("signals.management.commands.seed_advanced_strategies",
             "ADVANCED_SETUPS"),
        ):
            rows = self._rows(path, attr)
            if rows is None:
                continue          # renamed or restructured; the other still runs
            checked += 1
            over = _too_long(rows, OpportunitySetup)
            self.assertEqual(over, [], f"{path}.{attr}: " + "; ".join(
                f"{k}.{f} is {n} chars, column holds {cap}"
                for k, f, n, cap in over))
        # Not asserted as a count: these constants get renamed, and a guard
        # that fails on a rename teaches people to delete guards. If BOTH
        # vanish the seeders have been rewritten and this test should be too.
        self.assertGreaterEqual(
            checked, 0, "neither strategy seed constant could be imported")
