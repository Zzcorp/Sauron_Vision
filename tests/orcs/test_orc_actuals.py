"""THE CALENDAR ACTUALS MEASUREMENT (bot_program/orcs/sources.py, spec
§5.2a item 7): whether the free calendar feed carries the printed actual
is unmeasured; O1 measures it over the past high-impact prints, per
source, and records it at the day roll. `manage.py orcs actuals` prints
it; `--record` writes it. Read-only otherwise.

Run with:  python manage.py test tests.orcs.test_orc_actuals
"""
import io
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.core.management import call_command
from django.test import TestCase

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=dt_tz.utc)


def _event(title, hours_ago, *, actual="", source="forexfactory",
           impact="High", ccy="USD"):
    from market_data.models import EconomicEvent
    return EconomicEvent.objects.create(
        title=title, country="US", datetime=NOW - timedelta(hours=hours_ago),
        impact=impact, actual=actual, forecast="0.2%", previous="0.1%",
        currency_affected=ccy, source=source)


class TheMeasurementTests(TestCase):

    def setUp(self):
        _event("CPI m/m", 30, actual="0.3%")
        _event("Retail Sales m/m", 50, actual="")
        _event("Unemployment Claims", 70, actual="221K")
        _event("ISM Services PMI", 100, actual="", source="fmp_macro")
        _event("A low one", 20, actual="1", impact="Low")
        _event("Too old", 24 * 20, actual="1")
        _event("Not yet", -5, actual="")

    def test_the_share_per_source(self):
        from bot_program.orcs.sources import actuals_measurement
        m = actuals_measurement(14, NOW)
        self.assertEqual((m["n"], m["with_actual"]), (4, 2))
        self.assertEqual(m["by_source"]["forexfactory"],
                         {"n": 3, "with_actual": 2})
        self.assertEqual(m["by_source"]["fmp_macro"],
                         {"n": 1, "with_actual": 0})
        self.assertEqual(m["words"], "2 of 4 high-impact prints in the last "
                                     "14 days carry an actual "
                                     "(forexfactory 2 of 3; fmp_macro 0 of "
                                     "1).")

    def test_nothing_to_measure_says_so(self):
        from market_data.models import EconomicEvent

        from bot_program.orcs.sources import actuals_measurement
        EconomicEvent.objects.all().delete()
        m = actuals_measurement(14, NOW)
        self.assertEqual(m["n"], 0)
        self.assertEqual(m["words"], "— (no high-impact print in the last "
                                     "14 days)")

    def test_the_command_prints_and_records_only_when_asked(self):
        from unittest.mock import patch

        from bot_program.orcs.models import OrcSetting
        out = io.StringIO()
        with patch("django.utils.timezone.now", return_value=NOW):
            call_command("orcs", "actuals", "--days", "14", stdout=out)
        self.assertIn("2 of 4 high-impact prints", out.getvalue())
        self.assertIsNone(OrcSetting.get("calendar_actuals"))
        with patch("django.utils.timezone.now", return_value=NOW):
            call_command("orcs", "actuals", "--days", "14", "--record",
                         stdout=io.StringIO())
        self.assertEqual(OrcSetting.get("calendar_actuals")["n"], 4)
