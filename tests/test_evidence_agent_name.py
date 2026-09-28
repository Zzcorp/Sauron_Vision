"""The shadow's name fits the column it is written to.

`shadow_agent_for` registers a config's shadow calls with the calibration
under `bot:NAME#id`. AssetBotConfig.name is 80 characters wide and
AgentPrediction.agent is 50, and `log_direction_prediction` passes the
key through untouched — so on Postgres a config named past ~44 characters
raised DataError inside log_shadow_entry's broad except, every one of its
calls was "not registered", and the ledger printed calls 0 for a config
that had made them. SQLite does not enforce the width, which is why the
ledger's own tests could not see it.

The key is now bounded to the column: a name that fits is unchanged, a
name that does not keeps its head and carries an 8-hex digest of the whole
name — never a silent cut, which would fold two long names into one key.
Writer and reader share the helper, so they meet on the same string.

Run with:  python manage.py test tests.test_evidence_agent_name
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _limit() -> int:
    from ai_agents.models import AgentPrediction
    return AgentPrediction._meta.get_field("agent").max_length


def _cfg(user, name, **extras):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, mode="live",
        symbols=["AAPL"], capital=Decimal("1000"), enabled=True,
        extras=extras)


LONG_A = "research_commodity_livestock_and_lumber_paper_" + "a" * 34   # 80
LONG_B = "research_commodity_livestock_and_lumber_paper_" + "a" * 33 + "b"


class TheKeyFitsTheColumnTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("agn_u", password="x")

    def test_the_fixture_names_are_the_models_full_width(self):
        from bot_program.models import AssetBotConfig
        width = AssetBotConfig._meta.get_field("name").max_length
        self.assertEqual((len(LONG_A), len(LONG_B)), (width, width))

    def test_a_short_name_keeps_the_readable_key(self):
        from bot_program.evidence import shadow_agent_for
        cfg = _cfg(self.user, "SHADOWED")
        self.assertEqual(shadow_agent_for(cfg), f"bot:SHADOWED#{cfg.pk}")

    def test_a_full_width_name_fits_the_column(self):
        from bot_program.evidence import shadow_agent_for
        cfg = _cfg(self.user, LONG_A)
        key = shadow_agent_for(cfg)
        self.assertLessEqual(len(key), _limit(), key)
        self.assertTrue(key.startswith("bot:research_commodity"), key)
        self.assertTrue(key.endswith(f"#{cfg.pk}"), key)

    def test_the_boundary_is_the_columns_own_width(self):
        """A name that lands the key EXACTLY on the limit is left whole; one
        character more is shortened. Read off the field, not a literal."""
        from bot_program.evidence import shadow_agent_for
        probe = _cfg(self.user, "x")
        overhead = len(f"bot:#{probe.pk}")
        fits = "n" * (_limit() - overhead)
        probe.name = fits
        probe.save(update_fields=["name"])
        self.assertEqual(shadow_agent_for(probe), f"bot:{fits}#{probe.pk}")
        self.assertEqual(len(shadow_agent_for(probe)), _limit())
        probe.name = fits + "n"
        probe.save(update_fields=["name"])
        key = shadow_agent_for(probe)
        self.assertEqual(len(key), _limit(), key)
        self.assertNotEqual(key, f"bot:{fits + 'n'}#{probe.pk}")

    def test_two_long_names_that_share_a_head_do_not_share_a_key(self):
        """The cut is not silent: the digest of the WHOLE name tells two
        configs apart whose first forty characters agree."""
        from bot_program.evidence import shadow_agent_for
        a = _cfg(self.user, LONG_A)
        b = _cfg(self.user, LONG_B)
        ka, kb = shadow_agent_for(a), shadow_agent_for(b)
        self.assertNotEqual(ka, kb)
        # and not only by the id — the digest alone separates them
        self.assertNotEqual(ka.rsplit("#", 1)[0], kb.rsplit("#", 1)[0])

    def test_the_key_is_stable(self):
        from bot_program.evidence import shadow_agent_for
        from bot_program.models import AssetBotConfig
        cfg = _cfg(self.user, LONG_A)
        self.assertEqual(shadow_agent_for(cfg), shadow_agent_for(cfg))
        self.assertEqual(shadow_agent_for(cfg),
                         shadow_agent_for(AssetBotConfig.objects.get(pk=cfg.pk)))


class TheWriterAndTheReaderMeetTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        self.user = User.objects.create_user("agn_w", password="x")
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        PriceData.objects.create(
            instrument=inst, timeframe="1h",
            timestamp=timezone.now() - timedelta(hours=1),
            open=100, high=100, low=100, close=Decimal("100"), volume=1,
            source="test")
        until = (timezone.now() + timedelta(hours=24)).isoformat()
        self.cfg = _cfg(self.user, LONG_A, shadow_until=until)

    def test_a_long_named_shadow_registers_and_the_ledger_counts_it(self):
        from ai_agents.models import AgentPrediction
        from bot_program.asset_engine.safety import log_shadow_entry
        from bot_program.evidence import config_rows, shadow_agent_for
        decision = SimpleNamespace(direction="BUY", score=0.72,
                                   rule_name="r1", reasons=[])
        log_shadow_entry(self.cfg, "AAPL", decision, 100.0, 3)
        pred = AgentPrediction.objects.get(agent=shadow_agent_for(self.cfg))
        self.assertLessEqual(len(pred.agent), _limit())
        row = next(c for c in config_rows() if c["cfg"].pk == self.cfg.pk)
        self.assertEqual(row["calls_n"], 1)
