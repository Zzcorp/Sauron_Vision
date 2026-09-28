"""Every registered component fits its columns — on Postgres, not just SQLite.

2026-09-12: two new component descriptions were 600 characters. The
SQLite test suite does not enforce CharField max_length, so 142 tests
were green; the VPS runs Postgres, `seed_components` (the third step
of the migrate service) raised "value too long for type character
varying(300)", the service exited 1, and every container that depends
on it stayed created-but-not-started. This test is the column limit,
enforced where the suite runs.

Run with:  python manage.py test tests.test_component_limits
"""
from django.test import SimpleTestCase


class ComponentColumnLimitsTests(SimpleTestCase):

    def test_every_default_component_fits_its_columns(self):
        from core.platform_control import DEFAULT_COMPONENTS, PlatformComponent
        limits = {f.name: f.max_length
                  for f in PlatformComponent._meta.get_fields()
                  if getattr(f, "max_length", None)}
        too_long = []
        for comp in DEFAULT_COMPONENTS:
            for field in ("key", "name", "description", "category"):
                value = comp.get(field, "")
                cap = limits[field]
                if len(value) > cap:
                    too_long.append(f"{comp['key']}.{field}: {len(value)} > {cap}")
        self.assertEqual(too_long, [], "\n".join(too_long))
