"""The three trader personalities — presets, plans, windows, bands, page.

The operator's ask was "one short-term, short exposure in time and large
in volume and leverage; one swing trader, which is what Sauron is today;
and the long-termist, 'horizons'". A personality is NOT a new engine: it
is a COHERENT PRESET of knobs that already exist and are already read, a
GRADING WINDOW matched to the holding period, a SHARE BAND in the account
allocator and a WEIGHT on the 5-10 year prior.

What these tests exist to stop, each of which would be invisible:

  - a preset key NOTHING READS. A `max_notional_fraction` misspelt into
    extras is a knob the operator believes they set, a page that prints
    it back, and an engine that ignores it for ever. Every extras key the
    three presets set is grepped against the module that reads it.
  - a PLAN THAT WRITES. `plan_for` is what the page and the command print
    BEFORE the PIN; if it touched the row, the preview would be the
    change.
  - a warning that never fires. The three that cost money: a timeframe
    with no bars (decide() then reads no signals for ever), open
    positions whose exit moves under them (the time stop measures from
    opened_at, so a shorter ceiling flattens on the next tick), and a
    LIVE config (real risk, re-sized).
  - a persona that moves MONEY. It may write the trading knobs and
    nothing else: never `capital`, never `account_share_pct`, never the
    on/off switch.
  - one window grading all three. 21 days of scalps is a sample; 21 days
    of position trades is one trade.
  - a horizon prior that stops being weak. The factor is clamped to
    0.85..1.15 whatever the weight, and a scalp config lands EXACTLY 1.0.
  - the catalogue gap the first real HorizonView found: eight of eleven
    sectors absent from INSTRUMENTS_DATA, so the view had no call to make.

Run with:  python manage.py test tests.test_personas
"""
import ast
import os
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

User = get_user_model()
PIN = "4242"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── fixtures ────────────────────────────────────────────────────────────

def _cfg(user, *, name="bot", asset_class="stock", mode="paper",
         enabled=True, symbols=("AAPL",), extras=None, capital="1000",
         **fields):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        enabled=enabled, symbols=list(symbols), capital=Decimal(capital),
        extras=dict(extras or {}), **fields)


def _fill(cfg, r, *, paper=False, days_ago=1.0, rule="r1"):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("101"), status="CLOSED", pnl=Decimal("1"),
        rule_name=rule, paper=paper, realized_r=r, outcome="hit_target")
    AssetBotTrade.objects.filter(pk=t.pk).update(
        closed_at=timezone.now() - timedelta(days=days_ago))
    return t


def _open(cfg, symbol="AAPL"):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
        rule_name="r1", paper=True)


def _bars(symbol, timeframe, asset_class="stock", n=3):
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol,
                                 "asset_class": asset_class})
    now = timezone.now()
    for i in range(n):
        PriceData.objects.get_or_create(
            instrument=inst, timeframe=timeframe,
            timestamp=now - timedelta(days=i + 1),
            defaults={"open": Decimal("1"), "high": Decimal("1"),
                      "low": Decimal("1"), "close": Decimal("1"),
                      "volume": 1, "source": "test"})
    return inst


def _pin(user, pin=PIN):
    from django.contrib.auth.hashers import make_password
    from portfolio.trader_profile import TraderProfile
    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.access_pin_hash = make_password(pin)
    prof.save(update_fields=["access_pin_hash"])


def _flashes(resp) -> str:
    return " | ".join(str(m) for m in get_messages(resp.wsgi_request))


def _out(*argv, **opts) -> str:
    from io import StringIO
    buf = StringIO()
    call_command(*argv, stdout=buf, stderr=buf, **opts)
    return buf.getvalue()


def _src(rel) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ── 1. the presets are internally coherent ──────────────────────────────

class PresetCoherenceTests(TestCase):
    """A preset key nothing reads is a lie, and it is a silent one."""

    #: Where each extras key is actually consumed. The assertion is a
    #: grep of the SOURCE, not a mock: a key read through a constant in a
    #: module nobody imports is still a key nothing reads.
    READERS = ("bot_program/asset_engine/sizing.py",
               "bot_program/asset_engine/risk_levels.py",
               "bot_program/asset_engine/base.py",
               "bot_program/asset_engine/safety.py")

    def test_every_extras_key_the_presets_set_is_a_key_the_code_reads(self):
        from bot_program.personas import PERSONAS
        blob = "".join(_src(p) for p in self.READERS)
        for persona in PERSONAS.values():
            for key in persona.extras:
                self.assertTrue(f'"{key}"' in blob or f"'{key}'" in blob,
                                f"{persona.key} sets extras[{key!r}] and no "
                                f"engine module reads it — the operator "
                                f"would see a knob that does nothing")

    def test_every_field_the_presets_set_is_a_real_config_column(self):
        from bot_program.models import AssetBotConfig
        from bot_program.personas import PERSONAS
        columns = {f.name for f in AssetBotConfig._meta.get_fields()}
        for persona in PERSONAS.values():
            for name in persona.fields:
                self.assertIn(name, columns,
                              f"{persona.key} sets the field {name!r}, "
                              f"which AssetBotConfig does not have")

    def test_the_three_read_faster_to_slower_on_every_time_axis(self):
        """Timeframe, hold ceiling, signal age, cooldown and the grading
        window must all order the same way, or the preset is not one
        trade — it is five unrelated opinions, which is the state this
        module exists to end."""
        from bot_program.personas import PERSONAS
        keys = list(PERSONAS)
        self.assertEqual(keys, ["scalp", "swing", "position"])
        for name in ("max_hold_hours", "cool_down_minutes"):
            vals = [float(PERSONAS[k].fields[name]) for k in keys]
            self.assertEqual(vals, sorted(vals), name)
        ages = [float(PERSONAS[k].extras["max_signal_age_hours"])
                for k in keys]
        self.assertEqual(ages, sorted(ages))
        windows = [PERSONAS[k].evidence_days for k in keys]
        self.assertEqual(windows, sorted(windows))
        self.assertEqual([PERSONAS[k].fields["timeframe"] for k in keys],
                         ["1h", "4h", "1d"])
        # Fewer, larger bets as the horizon lengthens.
        conc = [PERSONAS[k].fields["max_concurrent_positions"] for k in keys]
        self.assertEqual(conc, sorted(conc, reverse=True))
        risk = [PERSONAS[k].extras["risk_per_trade_pct"] for k in keys]
        self.assertEqual(risk, sorted(risk))

    def test_every_stop_is_tighter_than_its_target_and_the_bands_are_sane(self):
        from bot_program.personas import PERSONAS
        for p in PERSONAS.values():
            self.assertLess(p.extras["atr_stop_mult"],
                            p.extras["atr_target_mult"], p.key)
            self.assertLess(0.0, p.share_floor_pct, p.key)
            self.assertLess(p.share_floor_pct, p.share_ceiling_pct, p.key)
            self.assertLessEqual(p.share_ceiling_pct, 100.0, p.key)
            self.assertGreaterEqual(p.horizon_weight, 0.0, p.key)
            # Every knob the page prints has a sentence saying why.
            for name in list(p.fields) + list(p.extras):
                self.assertTrue(p.why.get(name, "").strip(),
                                f"{p.key} sets {name} with no 'why'")

    def test_the_audit_kind_fits_the_column_postgres_enforces(self):
        """AuditLogEntry.kind is CharField(max_length=20) and Postgres
        enforces it; SQLite does not, so a longer kind passes every test
        here and raises on the deployment."""
        from bot_program.audit_models import AuditLogEntry
        from bot_program.personas import AUDIT_KIND
        self.assertLessEqual(
            len(AUDIT_KIND),
            AuditLogEntry._meta.get_field("kind").max_length)

    def test_a_preset_is_a_constant_not_a_setting(self):
        from bot_program.personas import PERSONAS, SCALP
        with self.assertRaises(Exception):
            SCALP.evidence_days = 99
        with self.assertRaises(TypeError):
            PERSONAS["scalp"].fields["timeframe"] = "4h"

    def test_options_wear_no_persona_at_all(self):
        """OptionsBot overrides scan_symbol wholesale and prices stops off
        premium: an ATR preset would describe a trade it never takes."""
        from bot_program.personas import PERSONA_ASSET_CLASSES, PERSONAS
        self.assertNotIn("options", PERSONA_ASSET_CLASSES)
        for p in PERSONAS.values():
            self.assertNotIn("options", p.asset_classes)


# ── 2. plan_for is pure, and every warning fires in its own scenario ────

class PlanForTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("plan_u", password="x")

    def test_an_unknown_key_is_refused_and_changes_nothing(self):
        from bot_program.personas import plan_for
        cfg = _cfg(self.user, name="a")
        plan = plan_for(cfg, "daytrader")
        self.assertFalse(plan["ok"])
        self.assertIn("scalp", plan["reason"])
        self.assertEqual(plan["changes"], {})
        self.assertEqual(plan["extras"], {})

    def test_an_options_config_is_refused_with_the_reason(self):
        from bot_program.personas import plan_for
        cfg = _cfg(self.user, name="o", asset_class="options")
        plan = plan_for(cfg, "swing")
        self.assertFalse(plan["ok"])
        self.assertIn("options", plan["reason"].lower())

    def test_the_plan_is_pure_and_writes_nothing(self):
        """What the page prints BEFORE the PIN must not be the change."""
        from bot_program.models import AssetBotConfig
        from bot_program.personas import plan_for
        cfg = _cfg(self.user, name="pure", timeframe="4h",
                   max_concurrent_positions=5, extras={"keep": 1})
        before = AssetBotConfig.objects.get(pk=cfg.pk)
        plan = plan_for(cfg, "scalp")
        self.assertTrue(plan["ok"])
        self.assertIn("timeframe", plan["changes"])
        after = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertEqual(after.timeframe, before.timeframe)
        self.assertEqual(after.max_concurrent_positions,
                         before.max_concurrent_positions)
        self.assertEqual(after.extras, {"keep": 1})
        # and the in-memory object is untouched too
        self.assertEqual(cfg.timeframe, "4h")

    def test_a_knob_already_at_the_personas_value_is_not_a_change(self):
        """An over-eager 'changed' writes a field for no reason and fills
        the audit log with no-ops. 5 vs 5.0 out of hand-edited JSON is
        the case that used to slip through."""
        from bot_program.personas import plan_for
        cfg = _cfg(self.user, name="same", timeframe="4h",
                   entry_score_min=0.60, min_signals_for_entry=1,
                   cool_down_minutes=60, max_concurrent_positions=5,
                   max_daily_loss_pct=2.0, max_hold_hours=72,
                   extras={"risk_per_trade_pct": 0.25})
        plan = plan_for(cfg, "swing")
        self.assertEqual(plan["changes"], {})
        self.assertNotIn("risk_per_trade_pct", plan["extras"])

    def test_a_timeframe_with_no_bars_warns_and_names_the_symbols(self):
        from bot_program.personas import plan_for
        cfg = _cfg(self.user, name="crypto", asset_class="crypto",
                   symbols=["BTCUSD", "ETHUSD"])
        plan = plan_for(cfg, "position")
        self.assertTrue(plan["ok"])
        warn = " ".join(plan["warnings"])
        self.assertIn("1d", warn)
        self.assertIn("BTCUSD", warn)
        self.assertIn("ETHUSD", warn)
        # the command that fixes it, not just the complaint
        self.assertIn("backfill_bars", warn)
        # crypto gets no daily bars from anything — say so by name
        self.assertIn("crypto", warn)

    def test_bars_that_exist_raise_no_bar_warning(self):
        """A DB read, not an assumption about classes: telling an
        operator to backfill what they already have is stale advice."""
        from bot_program.personas import plan_for
        _bars("AAPL", "1d")
        cfg = _cfg(self.user, name="stock", symbols=["AAPL"])
        plan = plan_for(cfg, "position")
        self.assertFalse([w for w in plan["warnings"] if "bars" in w],
                         plan["warnings"])

    def test_open_positions_warn_when_the_exit_moves_and_name_the_trades(self):
        from bot_program.personas import plan_for
        _bars("AAPL", "1h")
        cfg = _cfg(self.user, name="open", symbols=["AAPL"],
                   max_hold_hours=336.0)
        t = _open(cfg)
        plan = plan_for(cfg, "scalp")
        warn = " ".join(plan["warnings"])
        self.assertIn(f"#{t.pk}", warn)
        self.assertIn("max_hold_hours", warn)
        self.assertIn("opened_at", warn)

    def test_no_open_position_means_no_exit_warning(self):
        from bot_program.personas import plan_for
        _bars("AAPL", "1h")
        cfg = _cfg(self.user, name="flat", symbols=["AAPL"],
                   max_hold_hours=336.0)
        plan = plan_for(cfg, "scalp")
        self.assertFalse([w for w in plan["warnings"] if "OPEN" in w],
                         plan["warnings"])

    def test_a_live_config_warns_that_real_risk_is_re_sized(self):
        from bot_program.personas import plan_for
        _bars("AAPL", "4h")
        cfg = _cfg(self.user, name="live", mode="live", symbols=["AAPL"])
        plan = plan_for(cfg, "swing")
        warn = " ".join(plan["warnings"])
        self.assertIn("LIVE", warn)
        self.assertIn("REAL risk", warn)

    def test_forex_keeps_its_notional_fraction_and_the_plan_says_so(self):
        """sizing.MAX_NOTIONAL_FRACTION grants forex 4.0 because 20%
        notional on a major is an economically meaningless constraint.
        Writing scalp's 0.35 over it is a ninety-percent size cut nobody
        asked for."""
        from bot_program.asset_engine.sizing import MAX_NOTIONAL_FRACTION
        from bot_program.personas import plan_for
        _bars("EURUSD", "1h", asset_class="forex")
        cfg = _cfg(self.user, name="fx", asset_class="forex",
                   symbols=["EURUSD"])
        plan = plan_for(cfg, "scalp")
        self.assertNotIn("max_notional_fraction", plan["extras"])
        warn = " ".join(plan["warnings"])
        self.assertIn("forex", warn)
        self.assertIn("4.0", warn)
        self.assertGreaterEqual(float(MAX_NOTIONAL_FRACTION.get("forex", 0)),
                                1.0)
        # and no persona lowers it on any plan
        for key in ("swing", "position"):
            p = plan_for(cfg, key)
            self.assertNotIn("max_notional_fraction", p["extras"])
            self.assertTrue(any("forex" in w for w in p["warnings"]))

    def test_a_stock_config_is_never_raised_past_the_sizers_meaning(self):
        """max_notional_fraction is a cap on POSITION SIZE for one fixed
        cash risk budget, not a leverage dial: scalp's 0.35 must stay
        under the forex allowance and over the stock default it replaces,
        or the honest lever has become a loan in all but name."""
        from bot_program.asset_engine.sizing import (MAX_NOTIONAL_FRACTION,
                                                     MAX_RISK_FRACTION)
        from bot_program.personas import SCALP
        cap = SCALP.extras["max_notional_fraction"]
        self.assertLess(cap, float(MAX_NOTIONAL_FRACTION.get("forex", 4.0)))
        self.assertLessEqual(cap, 1.0, "a notional cap over 1.0 on a stock "
                                       "book is borrowing, and no "
                                       "personality borrows to fund a "
                                       "position")
        for p in (SCALP,):
            self.assertLessEqual(p.extras["risk_per_trade_pct"] / 100.0,
                                 float(MAX_RISK_FRACTION))


# ── 3. the write ────────────────────────────────────────────────────────

class ApplyPersonaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("apply_u", password="x")

    def test_apply_writes_the_fields_and_merges_extras_without_dropping_any(self):
        from bot_program.models import AssetBotConfig
        from bot_program.personas import apply_persona
        cfg = _cfg(self.user, name="w", symbols=["AAPL"], timeframe="4h",
                   max_concurrent_positions=5,
                   extras={"shadow_until": "2026-01-01", "keep_me": 7,
                           "account_share_pct": 33.0})
        res = apply_persona(cfg, "scalp", user=self.user)
        self.assertTrue(res["ok"], res.get("reason"))
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertEqual(row.timeframe, "1h")
        self.assertEqual(row.max_concurrent_positions, 8)
        self.assertEqual(row.max_hold_hours, 8.0)
        self.assertEqual(row.extras["risk_per_trade_pct"], 0.15)
        self.assertEqual(row.extras["atr_stop_mult"], 1.0)
        # every key it did not own survived
        self.assertEqual(row.extras["shadow_until"], "2026-01-01")
        self.assertEqual(row.extras["keep_me"], 7)

    def test_apply_refuses_a_live_config_without_force(self):
        from bot_program.models import AssetBotConfig
        from bot_program.personas import apply_persona
        cfg = _cfg(self.user, name="l", mode="live", symbols=["AAPL"],
                   timeframe="4h")
        res = apply_persona(cfg, "scalp", user=self.user)
        self.assertFalse(res["ok"])
        self.assertIn("LIVE", res["reason"])
        self.assertEqual(AssetBotConfig.objects.get(pk=cfg.pk).timeframe,
                         "4h")

    def test_apply_writes_a_live_config_with_force(self):
        from bot_program.models import AssetBotConfig
        from bot_program.personas import apply_persona
        cfg = _cfg(self.user, name="l2", mode="live", symbols=["AAPL"],
                   timeframe="4h")
        res = apply_persona(cfg, "scalp", user=self.user, force=True)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(AssetBotConfig.objects.get(pk=cfg.pk).timeframe,
                         "1h")

    def test_apply_stamps_the_persona_and_when(self):
        from bot_program.models import AssetBotConfig
        from bot_program.personas import (PERSONA_AT_EXTRAS_KEY,
                                          PERSONA_EXTRAS_KEY, apply_persona,
                                          persona_for, persona_of)
        cfg = _cfg(self.user, name="s", symbols=["AAPL"])
        apply_persona(cfg, "position", user=self.user)
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertEqual(row.extras[PERSONA_EXTRAS_KEY], "position")
        self.assertTrue(row.extras[PERSONA_AT_EXTRAS_KEY].startswith("20"))
        self.assertEqual(persona_of(row), "position")
        self.assertEqual(persona_for(row).evidence_days, 365)

    def test_apply_writes_an_audit_row_naming_what_moved(self):
        from bot_program.audit_models import AuditLogEntry
        from bot_program.personas import AUDIT_KIND, apply_persona
        cfg = _cfg(self.user, name="a", symbols=["AAPL"], timeframe="4h")
        apply_persona(cfg, "scalp", user=self.user)
        row = AuditLogEntry.objects.filter(kind=AUDIT_KIND).last()
        self.assertIsNotNone(row)
        self.assertEqual(row.data["persona"], "scalp")
        self.assertEqual(row.data["config_id"], cfg.pk)
        self.assertIn("timeframe", row.data["fields"])

    def test_apply_never_touches_capital_share_or_the_on_off_switch(self):
        """A personality is a trading STYLE. How much money a pool holds
        is the share allocator's question and the operator's; whether a
        bot runs is the toggle's."""
        from bot_program.models import AssetBotConfig
        from bot_program.personas import apply_persona
        cfg = _cfg(self.user, name="m", symbols=["AAPL"], capital="4321.00",
                   enabled=False,
                   extras={"account_share_pct": 33.0,
                           "capital_tracks_broker": True})
        apply_persona(cfg, "position", user=self.user)
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertEqual(row.capital, Decimal("4321.00"))
        self.assertEqual(row.extras["account_share_pct"], 33.0)
        self.assertTrue(row.extras["capital_tracks_broker"])
        self.assertFalse(row.enabled)

    def test_apply_refuses_what_the_plan_refuses(self):
        from bot_program.models import AssetBotConfig
        from bot_program.personas import apply_persona
        cfg = _cfg(self.user, name="opt", asset_class="options",
                   symbols=["AAPL"], timeframe="4h")
        res = apply_persona(cfg, "scalp", user=self.user, force=True)
        self.assertFalse(res["ok"])
        self.assertEqual(AssetBotConfig.objects.get(pk=cfg.pk).timeframe,
                         "4h")


# ── 4. the grading window follows the persona ───────────────────────────

class EvidenceWindowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ev_u", password="x")

    def test_config_evidence_uses_the_personas_own_window(self):
        """Twelve live fills thirty days back: measured on swing's 90-day
        window, unmeasured on scalp's 21-day one. The same rows, and the
        right answer is different — which is the whole point."""
        from bot_program.evidence import config_evidence
        scalp = _cfg(self.user, name="sc", extras={"persona": "scalp"})
        for _ in range(12):
            _fill(scalp, 1.0, days_ago=30)
        self.assertFalse(config_evidence(scalp)["measured"])
        # the window actually used IS 21: the default answers exactly what
        # an explicit 21 answers, and not what an explicit 90 answers
        self.assertEqual(config_evidence(scalp)["reason"],
                         config_evidence(scalp, days=21)["reason"])
        self.assertNotEqual(config_evidence(scalp)["reason"],
                            config_evidence(scalp, days=90)["reason"])

        swing = _cfg(self.user, name="sw", extras={"persona": "swing"})
        for _ in range(12):
            _fill(swing, 1.0, days_ago=30)
        ev = config_evidence(swing)
        self.assertTrue(ev["measured"])
        self.assertEqual(ev["lane"], "live")

    def test_an_explicit_days_still_wins_over_the_persona(self):
        """Every caller that names a window keeps it — the allocator's
        own 90-day lane is untouched by personas."""
        from bot_program.evidence import config_evidence
        cfg = _cfg(self.user, name="x", extras={"persona": "scalp"})
        for _ in range(12):
            _fill(cfg, 1.0, days_ago=30)
        self.assertTrue(config_evidence(cfg, days=90)["measured"])
        self.assertFalse(config_evidence(cfg, days=7)["measured"])

    def test_a_config_with_no_persona_keeps_the_ninety_day_default(self):
        from bot_program.evidence import DEFAULT_EVIDENCE_DAYS, config_evidence
        self.assertEqual(DEFAULT_EVIDENCE_DAYS, 90)
        cfg = _cfg(self.user, name="none")
        for _ in range(12):
            _fill(cfg, 1.0, days_ago=30)
        ev = config_evidence(cfg)
        self.assertTrue(ev["measured"])
        self.assertIn("90d", ev["reason"])


class PersonaRowsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rows_u", password="x")

    def test_live_and_paper_are_never_pooled(self):
        from bot_program.evidence import persona_rows
        cfg = _cfg(self.user, name="mix", extras={"persona": "swing"})
        for _ in range(11):
            _fill(cfg, 1.0, paper=False, days_ago=2)
        for _ in range(4):
            _fill(cfg, -1.0, paper=True, days_ago=2)
        row = {r["key"]: r for r in persona_rows()}["swing"]
        self.assertEqual(row["live"]["n"], 11)
        self.assertEqual(row["paper"]["n"], 4)
        self.assertAlmostEqual(row["live"]["r_sum"], 11.0)
        self.assertAlmostEqual(row["paper"]["r_sum"], -4.0)
        self.assertTrue(row["live"]["measured"])
        self.assertFalse(row["paper"]["measured"])

    def test_a_lane_below_the_floor_is_unmeasured_with_a_full_sentence(self):
        """'—' in a cell with no sentence beside it is the platform's
        oldest UI lie: it looks like a measured nothing."""
        from bot_program.evidence import MIN_EVIDENCE_N, persona_rows
        cfg = _cfg(self.user, name="thin", extras={"persona": "scalp"})
        for _ in range(2):
            _fill(cfg, 1.0, paper=True, days_ago=1)
        row = {r["key"]: r for r in persona_rows()}["scalp"]
        self.assertFalse(row["measured"])
        self.assertIn("unmeasured", row["sentence"])
        self.assertIn(str(MIN_EVIDENCE_N), row["sentence"])
        # nothing measured must not print as zero R
        self.assertIsNone(row["live"]["r_sum"])

    def test_a_persona_no_config_wears_names_the_command_that_fills_it(self):
        from bot_program.evidence import persona_rows
        rows = {r["key"]: r for r in persona_rows()}
        self.assertEqual(set(rows), {"scalp", "swing", "position"})
        row = rows["position"]
        self.assertEqual(row["n_configs"], 0)
        self.assertFalse(row["measured"])
        self.assertIn("persona apply", row["sentence"])

    def test_each_row_carries_its_own_window_band_and_weight(self):
        from bot_program.evidence import persona_rows
        rows = {r["key"]: r for r in persona_rows()}
        self.assertEqual(rows["scalp"]["evidence_days"], 21)
        self.assertEqual(rows["position"]["evidence_days"], 365)
        self.assertEqual(rows["scalp"]["horizon_weight"], 0.0)
        self.assertEqual(rows["swing"]["share_ceiling_pct"], 60.0)

    def test_a_wearing_config_carries_its_own_record_and_sentences(self):
        from bot_program.evidence import persona_rows
        cfg = _cfg(self.user, name="named", extras={"persona": "swing"})
        for _ in range(11):
            _fill(cfg, 0.5, paper=False, days_ago=3)
        row = {r["key"]: r for r in persona_rows()}["swing"]
        self.assertEqual(row["names"], ["named"])
        [c] = row["configs"]
        self.assertEqual(c["pk"], cfg.pk)
        self.assertEqual(c["live"]["n"], 11)
        self.assertIn("named live has earned", c["live_sentence"])
        self.assertIn("unmeasured", c["paper_sentence"])


# ── 5. the allocator learns the bands and the weight ────────────────────

class AllocatorBandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("band_u", password="x")

    def test_no_persona_keeps_the_platform_defaults(self):
        from bot_program.share_allocator import (DEFAULT_CEILING_PCT,
                                                 DEFAULT_FLOOR_PCT, bounds_for)
        lo, hi, why = bounds_for(_cfg(self.user, name="plain"))
        self.assertEqual((lo, hi), (DEFAULT_FLOOR_PCT, DEFAULT_CEILING_PCT))
        self.assertEqual(why, "")

    def test_the_persona_band_is_the_default_when_no_extras_band(self):
        from bot_program.share_allocator import bounds_for
        lo, hi, _ = bounds_for(_cfg(self.user, name="sc",
                                    extras={"persona": "scalp"}))
        self.assertEqual((lo, hi), (5.0, 25.0))
        lo, hi, _ = bounds_for(_cfg(self.user, name="po",
                                    extras={"persona": "position"}))
        self.assertEqual((lo, hi), (15.0, 50.0))

    def test_an_explicit_extras_band_wins_over_the_persona(self):
        """A persona is a preset; an extras key is an instruction."""
        from bot_program.share_allocator import bounds_for
        lo, hi, _ = bounds_for(_cfg(
            self.user, name="typed",
            extras={"persona": "scalp", "share_floor_pct": 8.0,
                    "share_ceiling_pct": 12.0}))
        self.assertEqual((lo, hi), (8.0, 12.0))
        # a half-typed band takes the persona's other half
        lo, hi, _ = bounds_for(_cfg(
            self.user, name="half",
            extras={"persona": "scalp", "share_ceiling_pct": 40.0}))
        self.assertEqual((lo, hi), (5.0, 40.0))

    def test_the_manual_lane_stays_exempt_even_wearing_a_persona(self):
        """The hand-taken pool is the operator's: a style typed onto it
        must not put a 25% ceiling back on the one pool the exemption
        exists to keep uncapped."""
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        from bot_program.share_allocator import bounds_for
        cfg = _cfg(self.user, name=MANUAL_CONFIG_NAME, symbols=[],
                   extras={"persona": "scalp"})
        lo, hi, _ = bounds_for(cfg)
        self.assertEqual(hi, 100.0)


class HorizonWeightTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hz_u", password="x")

    def _view(self, tilt=2, confidence=1.0, ac="stock"):
        from brain.horizon_models import HorizonView
        return HorizonView.objects.create(
            status=HorizonView.STATUS_OK,
            asset_class_tilts={ac: {"tilt": tilt, "confidence": confidence,
                                    "why": "t"}})

    def test_a_scalp_config_lands_exactly_one_and_says_why(self):
        from bot_program.share_allocator import horizon_for
        cfg = _cfg(self.user, name="sc", extras={"persona": "scalp"})
        hz = horizon_for(cfg, self._view())
        self.assertEqual(hz["factor"], 1.0)
        self.assertEqual(hz["persona"], "scalp")
        self.assertIn("scalp ignores the 5-year view", hz["label"])

    def test_the_weight_scales_the_tilt(self):
        from bot_program.share_allocator import HORIZON_TILT_STEP, horizon_for
        view = self._view(tilt=2, confidence=1.0)
        plain = horizon_for(_cfg(self.user, name="p"), view)
        self.assertAlmostEqual(plain["factor"],
                               1.0 + HORIZON_TILT_STEP * 2 * 1.0)
        swing = horizon_for(_cfg(self.user, name="sw",
                                 extras={"persona": "swing"}), view)
        self.assertAlmostEqual(swing["factor"],
                               1.0 + HORIZON_TILT_STEP * 2 * 1.0 * 0.5)
        self.assertIn("swing", swing["label"])

    def test_the_factor_never_leaves_the_clamp_whatever_the_weight(self):
        """position's ×1.5 on a full +2 would reach 1.15 exactly; a
        preset that grew past it must still be a weak prior, by
        construction rather than by the numbers happening to be small."""
        from bot_program.share_allocator import (HORIZON_FACTOR_MAX,
                                                 HORIZON_FACTOR_MIN,
                                                 horizon_for)
        cfg = _cfg(self.user, name="po", extras={"persona": "position"})
        up = horizon_for(cfg, self._view(tilt=2, confidence=1.0))
        down = horizon_for(cfg, self._view(tilt=-2, confidence=1.0))
        self.assertLessEqual(up["factor"], HORIZON_FACTOR_MAX + 1e-9)
        self.assertGreaterEqual(down["factor"], HORIZON_FACTOR_MIN - 1e-9)
        self.assertAlmostEqual(up["factor"], HORIZON_FACTOR_MAX)

    def test_the_why_sentence_names_the_persona_and_its_horizon(self):
        from bot_program.share_allocator import _why, horizon_for
        cfg = _cfg(self.user, name="sc", extras={"persona": "scalp"})
        hz = horizon_for(cfg, self._view())
        sentence = _why({"lane": "none", "score": 1.0, "measured": False},
                        {"factor": 1.0}, {"factor": 1.0, "measured": False},
                        {"factor": 1.0, "blind": True},
                        10.0, 10.0, 10.0, 10.0, False,
                        hz=hz, persona="scalp")
        self.assertTrue(sentence.startswith("persona scalp · "))
        self.assertIn("horizon 1.00 (scalp ignores the 5-year view)",
                      sentence)


class DeskPersonaShareTests(TestCase):
    """The capital desk shipped before this stage, so the persona share
    cap belongs in its chooser beside the rule and class caps."""

    def test_the_desk_caps_one_personas_share_of_a_ticks_risk(self):
        from bot_program import capital_desk
        self.assertEqual(capital_desk.DESK_MAX_PERSONA_SHARE, 0.50)
        src = _src("bot_program/capital_desk.py")
        self.assertIn("persona_share", src)
        self.assertIn("DESK_MAX_PERSONA_SHARE * share_base", src)


# ── 6. the catalogue gap the first Horizon view found ───────────────────

class CatalogueTests(TestCase):
    def test_every_horizon_universe_symbol_is_in_the_catalogue(self):
        """The first real HorizonView gave no call on eight of eleven
        sectors because XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC and UUP
        were simply absent. The gap cannot come back."""
        from brain.horizon import GOLD_CANDIDATES, HORIZON_UNIVERSE
        from instruments.services import INSTRUMENTS_DATA
        known = set()
        for symbols in INSTRUMENTS_DATA.values():
            known.update(symbols)
        for _key, _name, symbol in HORIZON_UNIVERSE:
            if symbol in GOLD_CANDIDATES:
                self.assertTrue(set(GOLD_CANDIDATES) & known,
                                "no gold proxy in the catalogue")
                continue
            self.assertIn(symbol, known,
                          f"{symbol} is in HORIZON_UNIVERSE and not in "
                          f"INSTRUMENTS_DATA — the view has no call to make")

    def test_the_new_sector_etfs_match_the_files_own_tuple_shape(self):
        from instruments.services import INSTRUMENTS_DATA
        etfs = INSTRUMENTS_DATA["etf"]
        for sym, name in (("XLV", "Health Care"), ("XLI", "Industrial"),
                          ("XLY", "Consumer Discretionary"),
                          ("XLP", "Consumer Staples"), ("XLU", "Utilities"),
                          ("XLB", "Materials"), ("XLRE", "Real Estate"),
                          ("XLC", "Communication Services"),
                          ("UUP", "Invesco DB US Dollar")):
            self.assertIn(sym, etfs)
            self.assertIsInstance(etfs[sym], tuple)
            self.assertEqual(len(etfs[sym]), 2)
            self.assertIn(name, etfs[sym][0])
            self.assertEqual(etfs[sym][1], etfs["XLF"][1])


# ── 7. the page ─────────────────────────────────────────────────────────

class PersonasPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("page_u", password="x")
        self.admin = User.objects.create_superuser("page_a", password="x")
        self.url = reverse("personas_dashboard")

    def test_login_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_the_page_renders_with_nothing_configured_at_all(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for key in ("scalp", "swing", "position"):
            self.assertIn(key, body)
        # every empty state is a full sentence naming its command
        self.assertIn("persona apply", body)
        # The leverage correction, in words, on the page — and scoped to
        # the personalities, which is the only place it is true. The
        # sweeping version ("this platform never borrows") was falsified
        # by the wall review: BotConfig carries leverage and margin_mode
        # and the futures engine POSTs both. tests/test_the_wall.py holds
        # the landing page to the same line; this holds /personas/.
        self.assertIn("No personality borrows to fund a position", body)
        low = body.lower()
        self.assertNotIn("this platform never borrows", low)
        self.assertNotIn("no margin knob anywhere", low)
        # Forex is where the platform does lever, and the page says so
        # rather than letting "neither is a loan" stand unqualified.
        self.assertIn("Forex is the exception", body)

    def test_the_page_shows_a_wearing_config_and_its_record(self):
        self.client.force_login(self.user)
        cfg = _cfg(self.user, name="worn", extras={"persona": "swing"})
        for _ in range(11):
            _fill(cfg, 1.0, days_ago=2)
        body = self.client.get(self.url).content.decode()
        self.assertIn("worn", body)
        self.assertIn("has earned", body)

    def test_an_unmeasured_lane_renders_a_dash_and_not_a_zero(self):
        """The old assertion here looked for '&mdash;' ANYWHERE in the
        body — and the page's own 'How to read this page' card prints
        that entity in every state, so the test passed whatever the lane
        rendered. It has to read the LANE (2026-09-12)."""
        self.client.force_login(self.user)
        cfg = _cfg(self.user, name="thin", extras={"persona": "scalp"})
        _fill(cfg, 1.0, paper=True, days_ago=1)
        body = self.client.get(self.url).content.decode()
        self.assertIn("unmeasured", body)
        # the scalp column's live lane: one fill, and it is PAPER, so the
        # live row must print an em-dash and never 0.00
        scalp_col = body.split("Scalp · scalp")[1].split("Swing · swing")[0]
        live_row = scalp_col.split(">live<")[1].split("</tr>")[0]
        self.assertIn("—", live_row)
        self.assertNotIn("0.00", live_row)

    def test_a_non_superuser_sees_no_apply_form(self):
        self.client.force_login(self.user)
        _cfg(self.user, name="target")
        body = self.client.get(self.url).content.decode()
        self.assertNotIn("hq_apply_persona", body)
        self.assertNotIn("/admin-dashboard/personas/apply/", body)

    def test_a_superuser_sees_an_apply_form_per_config(self):
        self.client.force_login(self.admin)
        _cfg(self.admin, name="unworn")
        _cfg(self.admin, name="worn", extras={"persona": "swing"})
        body = self.client.get(self.url).content.decode()
        self.assertEqual(body.count("/admin-dashboard/personas/apply/"), 2)

    def test_applying_from_the_page_writes_and_flashes_every_warning(self):
        from bot_program.models import AssetBotConfig
        self.client.force_login(self.admin)
        cfg = _cfg(self.admin, name="p", symbols=["BTCUSD"],
                   asset_class="crypto", timeframe="4h")
        _open(cfg, symbol="BTCUSD")
        resp = self.client.post(reverse("hq_apply_persona"),
                                {"config_id": cfg.pk,
                                 "persona": "position"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AssetBotConfig.objects.get(pk=cfg.pk).timeframe,
                         "1d")
        flashes = _flashes(resp)
        self.assertIn("now trades as position", flashes)
        self.assertIn("no 1d bars", flashes)
        self.assertIn("OPEN", flashes)

    def test_a_live_config_needs_the_pin(self):
        from bot_program.models import AssetBotConfig
        self.client.force_login(self.admin)
        cfg = _cfg(self.admin, name="lv", mode="live", symbols=["AAPL"],
                   timeframe="4h")
        resp = self.client.post(reverse("hq_apply_persona"),
                                {"config_id": cfg.pk, "persona": "scalp"},
                                follow=True)
        self.assertIn("PIN required", _flashes(resp))
        self.assertEqual(AssetBotConfig.objects.get(pk=cfg.pk).timeframe,
                         "4h")

        _pin(self.admin)
        resp = self.client.post(reverse("hq_apply_persona"),
                                {"config_id": cfg.pk, "persona": "scalp",
                                 "pin": PIN}, follow=True)
        self.assertEqual(AssetBotConfig.objects.get(pk=cfg.pk).timeframe,
                         "1h")
        self.assertIn("now trades as scalp", _flashes(resp))

    def test_the_apply_endpoint_is_superuser_and_post_only(self):
        self.client.force_login(self.user)
        cfg = _cfg(self.user, name="q")
        self.assertEqual(
            self.client.post(reverse("hq_apply_persona"),
                             {"config_id": cfg.pk,
                              "persona": "scalp"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("hq_apply_persona")).status_code, 405)

    def test_an_unknown_persona_or_config_changes_nothing(self):
        self.client.force_login(self.admin)
        cfg = _cfg(self.admin, name="z", timeframe="4h")
        resp = self.client.post(reverse("hq_apply_persona"),
                                {"config_id": cfg.pk, "persona": "daytrader"},
                                follow=True)
        self.assertIn("is not a personality", _flashes(resp))
        resp = self.client.post(reverse("hq_apply_persona"),
                                {"config_id": 999999, "persona": "scalp"},
                                follow=True)
        self.assertIn("No such bot config", _flashes(resp))

    def test_the_sidebar_row_and_the_evidence_card_both_exist(self):
        """A page nothing links to is a page nobody opens; the glyph must
        be this row's alone or the sidebar reads as two of the same."""
        base = _src("templates/base.html")
        self.assertIn("personas_dashboard", base)
        self.assertIn("Personalities", base)
        self.assertEqual(base.count("◨"), 1)
        self.client.force_login(self.user)
        body = self.client.get(reverse("evidence_ledger")).content.decode()
        self.assertIn("Personalities", body)
        self.assertIn("graded over its OWN window", body)


# ── 8. the command ──────────────────────────────────────────────────────

class PersonaCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("cmd_u", password="x")

    def test_list_prints_the_three_side_by_side_and_who_wears_them(self):
        cfg = _cfg(self.user, name="worn", extras={"persona": "swing"})
        _cfg(self.user, name="bare")
        out = _out("persona", "list")
        for key in ("scalp", "swing", "position"):
            self.assertIn(key, out)
        for knob in ("timeframe", "atr_stop_mult", "max_notional_fraction"):
            self.assertIn(knob, out)
        self.assertIn("grading window", out)
        self.assertIn("share floor", out)
        self.assertIn(f"[{cfg.pk}] worn", out)
        self.assertIn("bare", out)
        # Same scoped claim the page carries, in the shell twin.
        low = out.lower()
        self.assertIn("no personality borrows to fund a position", low)
        self.assertNotIn("this platform never borrows", low)
        self.assertNotIn("no margin anywhere in this code", low)
        self.assertIn("forex is the exception", low)

    def test_show_prints_one_preset_in_full_with_its_reasons(self):
        out = _out("persona", "show", "scalp")
        self.assertIn("SCALP", out)
        self.assertIn("grading window: 21 days", out)
        self.assertIn("horizon weight", out)
        self.assertIn("share band:", out)
        self.assertIn("max_notional_fraction", out)
        self.assertIn("THE HONEST LEVER", out)

    def test_show_refuses_an_unknown_key_and_names_the_three(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError) as ctx:
            _out("persona", "show", "daytrader")
        self.assertIn("scalp", str(ctx.exception))

    def test_apply_without_yes_prints_the_plan_and_writes_nothing(self):
        from bot_program.models import AssetBotConfig
        cfg = _cfg(self.user, name="c", symbols=["AAPL"], timeframe="4h")
        out = _out("persona", "apply", str(cfg.pk), "scalp")
        self.assertIn("timeframe", out)
        self.assertIn("plan only", out)
        self.assertIn("capital and account share are NOT touched", out)
        self.assertEqual(AssetBotConfig.objects.get(pk=cfg.pk).timeframe,
                         "4h")

    def test_apply_with_yes_writes_and_says_what_it_wrote(self):
        from bot_program.models import AssetBotConfig
        cfg = _cfg(self.user, name="c2", symbols=["AAPL"], timeframe="4h")
        out = _out("persona", "apply", str(cfg.pk), "scalp", "--yes")
        self.assertIn("written", out)
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertEqual(row.timeframe, "1h")
        self.assertEqual(row.extras["persona"], "scalp")

    def test_apply_refuses_an_unknown_config_or_key(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            _out("persona", "apply", "999999", "scalp")
        with self.assertRaises(CommandError):
            _out("persona", "apply")
        cfg = _cfg(self.user, name="c3")
        self.assertIn("refused",
                      _out("persona", "apply", str(cfg.pk), "nope"))

    def test_grade_prints_a_row_and_a_sentence_per_persona(self):
        cfg = _cfg(self.user, name="g", extras={"persona": "swing"})
        for _ in range(11):
            _fill(cfg, 1.0, days_ago=2)
        out = _out("persona", "grade")
        self.assertIn("persona", out)
        self.assertIn("21d", out)
        self.assertIn("365d", out)
        self.assertIn("has earned", out)
        self.assertIn("unmeasured", out)

    def test_the_command_is_registered_in_the_ops_catalogue(self):
        from core import ops_commands
        entry = ops_commands.get("persona")
        self.assertIsNotNone(entry, "the shell twin is not in the registry")
        self.assertEqual(entry["mirrors"], "/personas/")
        self.assertEqual(entry["category"], "decide")
        self.assertFalse(ops_commands.is_runnable(entry),
                         "apply writes — the Run lane must refuse it")
        doc = ast.get_docstring(ast.parse(_src(
            "bot_program/management/commands/persona.py"))) or ""
        for line in entry["usage"]:
            self.assertIn(line, doc)

# ── 9. what the adversarial review found (2026-09-12) ───────────────────
#
# Four defects, each of which the suite above passed over, and each the
# SAME class of failure this module exists to end: a knob that reads as
# set and does nothing.

class AtrFrameTests(TestCase):
    """A multiple is only as long as the frame it is measured on.

    `risk_levels.stop_and_target` cuts every ATR multiple from
    `extras['atr_timeframe']`, which DEFAULTS TO 4h — a key entirely
    separate from the config's `timeframe` column. Without it the scalp's
    "1.0 ATR, tight enough for an hourly frame" was a 4-hour ATR (two to
    four times the hourly range, so no tight stop and no justification
    for the raised notional cap), and the position persona's 2.5 ATR stop
    on a thirty-day hold was about 2% on a liquid equity — cleared twice
    by an ordinary week. Three presets, all describing trades the
    platform would not have taken.
    """

    def setUp(self):
        self.user = User.objects.create_user("atr_u", password="x")

    def _atr(self, symbol, timeframe, value):
        from indicators.models import TechnicalIndicator
        from instruments.models import Instrument
        inst, _ = Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
        return TechnicalIndicator.objects.create(
            instrument=inst, timeframe=timeframe, timestamp=timezone.now(),
            atr_14=Decimal(str(value)))

    def test_each_persona_measures_its_atr_on_the_frame_it_trades(self):
        from bot_program.personas import PERSONAS
        for p in PERSONAS.values():
            self.assertEqual(p.extras.get("atr_timeframe"),
                             p.fields["timeframe"],
                             f"{p.key} trades {p.fields['timeframe']} bars "
                             f"and cuts its stop from "
                             f"{p.extras.get('atr_timeframe')!r} — the "
                             f"multiples describe a different trade")

    def test_the_stop_is_actually_cut_from_the_personas_own_frame(self):
        """The behavioural half: three ATRs on one symbol, and the stop
        that comes back says which frame was read."""
        from bot_program.asset_engine.risk_levels import stop_and_target
        from bot_program.personas import apply_persona
        self._atr("AAPL", "1h", 1.0)
        self._atr("AAPL", "4h", 4.0)
        self._atr("AAPL", "1d", 8.0)

        scalp = _cfg(self.user, name="sc", symbols=["AAPL"])
        apply_persona(scalp, "scalp", user=self.user)
        stop, target, meta = stop_and_target(scalp, "AAPL", 100.0, "BUY")
        self.assertEqual(meta["levels_source"], "atr")
        # 1.0 x ATR(1h) = 1.0, not 1.0 x ATR(4h) = 4.0
        self.assertAlmostEqual(stop, 99.0, places=6)
        self.assertAlmostEqual(target, 102.0, places=6)

        pos = _cfg(self.user, name="po", symbols=["AAPL"])
        apply_persona(pos, "position", user=self.user)
        stop, _target, meta = stop_and_target(pos, "AAPL", 100.0, "BUY")
        self.assertEqual(meta["levels_source"], "atr")
        # 2.5 x ATR(1d) = 20.0, not 2.5 x ATR(4h) = 10.0
        self.assertAlmostEqual(stop, 80.0, places=6)

    def test_the_page_and_the_command_both_print_the_frame(self):
        """A knob written into extras and shown nowhere is the same lie
        from the other end."""
        from bot_program.personas import ALL_KNOBS, EXTRA_KNOBS
        self.assertIn("atr_timeframe", EXTRA_KNOBS)
        self.assertIn("atr_timeframe", ALL_KNOBS)
        self.assertIn("atr_timeframe", _out("persona", "show", "position"))


class DrainedAndDroppedKnobsTests(TestCase):
    """Two keys that would otherwise OUTRANK the persona in silence."""

    def setUp(self):
        self.user = User.objects.create_user("drop_u", password="x")

    def test_the_legacy_hold_key_is_drained_so_the_presets_ceiling_binds(self):
        """`time_stop_setting()` reads extras['max_hold_hours'] BEFORE the
        column the preset writes. Left in place, the one knob that decides
        when a position is closed would keep its old value while the page
        printed the persona's."""
        from bot_program.models import AssetBotConfig
        from bot_program.personas import (LEGACY_HOLD_EXTRAS_KEY,
                                          apply_persona, plan_for)
        cfg = _cfg(self.user, name="legacy", symbols=["AAPL"],
                   extras={LEGACY_HOLD_EXTRAS_KEY: 336})
        self.assertEqual(cfg.time_stop_setting()["hours"], 336.0)

        plan = plan_for(cfg, "swing")
        self.assertIn(LEGACY_HOLD_EXTRAS_KEY, plan["drops"])
        self.assertTrue(any("LEGACY" in w for w in plan["warnings"]),
                        plan["warnings"])

        apply_persona(cfg, "swing", user=self.user)
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertNotIn(LEGACY_HOLD_EXTRAS_KEY, row.extras)
        self.assertEqual(row.max_hold_hours, 72.0)
        self.assertEqual(row.time_stop_setting()["hours"], 72.0)

    def test_switching_persona_removes_the_previous_ones_notional_cap(self):
        """scalp writes max_notional_fraction 0.35; swing does not set the
        key at all. Merging alone left a scalp's cap on a swing book for
        ever, and sizing reads that override ahead of the class default."""
        from bot_program.asset_engine.sizing import (MAX_NOTIONAL_FRACTION,
                                                     max_notional_fraction)
        from bot_program.models import AssetBotConfig
        from bot_program.personas import apply_persona, plan_for
        cfg = _cfg(self.user, name="switch", symbols=["AAPL"])
        apply_persona(cfg, "scalp", user=self.user)
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertEqual(row.extras["max_notional_fraction"], 0.35)

        plan = plan_for(row, "swing")
        self.assertIn("max_notional_fraction", plan["drops"])
        self.assertTrue(any("max_notional_fraction" in w
                            for w in plan["warnings"]), plan["warnings"])

        apply_persona(row, "swing", user=self.user)
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertNotIn("max_notional_fraction", row.extras)
        self.assertAlmostEqual(max_notional_fraction(row, "stock"),
                               MAX_NOTIONAL_FRACTION.get("stock", 0.20))
        self.assertEqual(row.extras["persona"], "swing")

    def test_a_number_the_operator_typed_is_never_dropped(self):
        """Only a value still EXACTLY equal to what the previous persona
        wrote may be removed. A hand-typed cap is an instruction."""
        from bot_program.models import AssetBotConfig
        from bot_program.personas import apply_persona
        cfg = _cfg(self.user, name="typed", symbols=["AAPL"])
        apply_persona(cfg, "scalp", user=self.user)
        cfg.refresh_from_db()
        ex = dict(cfg.extras)
        ex["max_notional_fraction"] = 0.9          # the operator's own
        AssetBotConfig.objects.filter(pk=cfg.pk).update(extras=ex)
        cfg.refresh_from_db()
        apply_persona(cfg, "swing", user=self.user)
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertEqual(row.extras["max_notional_fraction"], 0.9)

    def test_a_drop_leaves_every_other_extras_key_alone(self):
        """The drop is a re-read-and-remove, not a rewrite of the JSON: a
        tick holding this config must not have its own keys reverted."""
        from bot_program.models import AssetBotConfig
        from bot_program.personas import apply_persona
        cfg = _cfg(self.user, name="keep", symbols=["AAPL"],
                   extras={"max_hold_hours": 200,
                           "shadow_until": "2026-02-02",
                           "account_share_pct": 41.0,
                           "capital_tracks_broker": True, "mine": [1, 2]})
        apply_persona(cfg, "position", user=self.user)
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertNotIn("max_hold_hours", row.extras)
        self.assertEqual(row.extras["shadow_until"], "2026-02-02")
        self.assertEqual(row.extras["account_share_pct"], 41.0)
        self.assertTrue(row.extras["capital_tracks_broker"])
        self.assertEqual(row.extras["mine"], [1, 2])
        self.assertEqual(row.extras["persona"], "position")

    def test_the_command_prints_the_drop_as_a_change(self):
        cfg = _cfg(self.user, name="cli", symbols=["AAPL"],
                   extras={"max_hold_hours": 500})
        out = _out("persona", "apply", str(cfg.pk), "scalp")
        self.assertIn("drop", out)
        self.assertIn("max_hold_hours", out)

    def test_the_audit_row_names_what_was_dropped(self):
        from bot_program.audit_models import AuditLogEntry
        from bot_program.personas import AUDIT_KIND, apply_persona
        cfg = _cfg(self.user, name="aud", symbols=["AAPL"],
                   extras={"max_hold_hours": 500})
        apply_persona(cfg, "scalp", user=self.user)
        row = AuditLogEntry.objects.filter(kind=AUDIT_KIND).last()
        self.assertIn("max_hold_hours", row.data["dropped"])


class WarningPrecisionTests(TestCase):
    """A warning that is false in one of its scenarios teaches an operator
    to skim the warnings, which is worse than not writing it."""

    def setUp(self):
        self.user = User.objects.create_user("warn_u", password="x")

    def test_an_atr_change_never_claims_a_placed_exit_moves(self):
        """`stop_and_target` runs ONCE, at entry: the levels already on an
        open trade are not re-cut when the multiples change. Only the time
        stop, which manage_positions re-reads every tick, moves under an
        open position."""
        from bot_program.personas import plan_for
        _bars("AAPL", "4h")
        cfg = _cfg(self.user, name="atr_only", symbols=["AAPL"],
                   max_hold_hours=72.0,
                   extras={"atr_stop_mult": 9.9, "atr_timeframe": "4h"})
        _open(cfg)
        plan = plan_for(cfg, "swing")
        self.assertIn("atr_stop_mult", plan["extras"])
        self.assertNotIn("max_hold_hours", plan["changes"])
        joined = " ".join(plan["warnings"])
        self.assertIn("ALREADY PLACED do NOT move", joined)
        self.assertNotIn("exit changes under them", joined)

    def test_the_time_stop_change_still_says_the_exit_moves(self):
        from bot_program.personas import plan_for
        _bars("AAPL", "4h")
        cfg = _cfg(self.user, name="time", symbols=["AAPL"],
                   max_hold_hours=336.0)
        t = _open(cfg)
        joined = " ".join(plan_for(cfg, "swing")["warnings"])
        self.assertIn("exit changes under them", joined)
        self.assertIn("opened_at", joined)
        self.assertIn(f"#{t.pk}", joined)


class ExistingCallersUnchangedTests(TestCase):
    """The window a caller NAMED is the window it gets — personas or not."""

    def setUp(self):
        self.user = User.objects.create_user("unch_u", password="x")
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(user=self.user, port=4003,
                                          is_primary_for_stocks=True)
        acct.set_credentials("U1234567")
        acct.username_enc, acct.password_enc = "x", "y"
        acct.last_equity = Decimal("2000.00")
        acct.last_equity_currency = "EUR"
        acct.last_equity_at = timezone.now()
        acct.save()

    def _follower(self, name, **extras):
        ex = {"capital_tracks_broker": True}
        ex.update(extras)
        return _cfg(self.user, name=name, mode="live", capital="1000",
                    extras=ex)

    def test_the_allocator_still_grades_every_pool_over_ninety_days(self):
        """The one number this whole feature must not have moved: the
        share allocator NAMES its own window, so a config wearing a
        21-day persona is still allocated on 90 days of evidence."""
        from unittest.mock import patch

        from bot_program import evidence as evidence_mod
        from bot_program.evidence import DEFAULT_EVIDENCE_DAYS, config_evidence
        from bot_program.share_allocator import (EVIDENCE_DAYS,
                                                 propose_share_plan)
        scalp = self._follower("sc", persona="scalp")
        self._follower("plain")
        for _ in range(12):
            _fill(scalp, 1.0, days_ago=30)

        seen = []
        real = evidence_mod.config_evidence

        def spy(cfg, **kw):
            seen.append(kw.get("days"))
            return real(cfg, **kw)

        with patch("bot_program.evidence.config_evidence", side_effect=spy), \
                patch("brain.context.get_brain_context", return_value=None), \
                patch("signals.opportunity_density.opportunity_density",
                      return_value={}), \
                patch("bot_program.news_risk.news_risk_by_class",
                      return_value={}):
            propose_share_plan(self.user)
        self.assertTrue(seen, "the allocator never read the evidence ledger")
        self.assertEqual(set(seen), {EVIDENCE_DAYS})
        self.assertEqual(EVIDENCE_DAYS, DEFAULT_EVIDENCE_DAYS)
        # and the two answers really are different for this config, so the
        # assertion above is not a tautology
        self.assertFalse(config_evidence(scalp)["measured"])
        self.assertTrue(config_evidence(scalp, days=EVIDENCE_DAYS)["measured"])

    def test_config_evidence_reports_the_window_it_used(self):
        """A lane that does not name its window cannot be compared with
        the lane beside it — and brain.horizon prints them side by side."""
        from bot_program.evidence import config_evidence
        scalp = _cfg(self.user, name="s2", extras={"persona": "scalp"})
        plain = _cfg(self.user, name="p2")
        self.assertEqual(config_evidence(scalp)["days"], 21)
        self.assertEqual(config_evidence(plain)["days"], 90)
        self.assertEqual(config_evidence(scalp, days=90)["days"], 90)
        # the unmeasured branch names it too — the state a config sits in
        # for months
        self.assertIn("21d", config_evidence(scalp)["reason"])
        self.assertIn("90d", config_evidence(plain)["reason"])
