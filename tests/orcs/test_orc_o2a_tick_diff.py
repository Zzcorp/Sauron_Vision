"""T12b, THE TICK DIFFERENTIAL: N1's runtime proof (the O2 spec N1 items 1,
5 and 7, A.42, A.45, A.45b; §1.1.7 T12b; 2026-11-05).

Two identical configs, each with one identical row and its Orc, run the
same real ticks (AssetBot.manage_positions, the broker a MagicMock, the
clock pinned). The minds' four gates are ON and the Orcs line is set. One
Orc holds one queued intent of each kind: a tighten whose would-stop is
strictly tighter than the real stop, with the second tick's price between
the two; a trim; a lock waiver of the live event; and an exit. The other
row's hook is unhooked. Per world:

- an unprotected live bot row: the trailing stop and the SL/TP check run
  after the hook;
- a protected eToro-style row: _manage_broker_stop runs after it;
- a manual row; a paper row.

Equal between the two rows, tick by tick: `closed`; the row (every column,
take_profit included, its metadata less "orc"); the AragornAction rows;
the broker's calls. Around the hook, a deep copy of trade.__dict__ (less
_state), trade.metadata and trade._care_tick is the same after it as
before. And the proof is not vacuous: each intent was taken by the tick
and the shadow arm moved and closed, while the position did not.

Run with:  python manage.py test tests.orcs.test_orc_o2a_tick_diff
"""
import copy
import json
from contextlib import ExitStack
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock, patch

from tests.orcs.helpers import (ROUTER, _config, _manual_config, _manual_row,
                                _on, _row, _switch, _user, born, tracks_of)
from tests.orcs.helpers_o2 import MindTestCase, minds_on

UTC = dt_tz.utc
FIXED = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
HOOK = "bot_program.orcs.observe.after_care"
#: The two ticks: the first where every queued intent has its room, the
#: second between the real stop (break-even, 100.2) and the would-stop.
TICK_1 = (FIXED + timedelta(minutes=5), "102.4")
TICK_2 = (FIXED + timedelta(minutes=10), "100.6")
WOULD_STOP = 101.0
#: The engine's knobs: break-even at +0.5R, so the stop the row holds moves
#: after the hook, on both rows alike.
EXTRAS = {"breakeven_at_r": 0.5, "breakeven_buffer_r": 0.1}


def _snap(row) -> dict:
    """Every column but the id and the config, the metadata less "orc"."""
    row.refresh_from_db()
    out = {}
    for f in type(row)._meta.concrete_fields:
        if f.name in ("id", "config"):
            continue
        value = getattr(row, f.attname)
        if f.name == "metadata":
            value = json.loads(json.dumps(value, sort_keys=True,
                                          default=str))
            value.pop("orc", None)
        out[f.name] = value
    return out


def _objects(trade) -> tuple:
    """A deep copy of what the tick hands the Orcs and reads again after:
    the row's own attributes (less _state), its metadata, its care stash."""
    return (copy.deepcopy({k: v for k, v in trade.__dict__.items()
                           if k != "_state"}),
            copy.deepcopy(trade.metadata),
            copy.deepcopy(getattr(trade, "_care_tick", None)))


class TheTickDifferentialTests(MindTestCase):

    def setUp(self):
        from market_data.models import EconomicEvent
        _switch("aragorn")
        _on()
        minds_on(self)
        self.event = EconomicEvent.objects.create(
            title="US CPI", country="US",
            datetime=FIXED + timedelta(minutes=70), impact="high",
            currency_affected="USD", source="forexfactory")

    # ── the worlds ───────────────────────────────────────────────────────

    def _side(self, world, tag):
        """One config and its row, the Orc born on it."""
        from bot_program.models import AssetBotTrade
        user = _user(f"o2a_diff_{world}_{tag}")
        live = world in ("bot", "protected")
        if world == "manual":
            cfg = _manual_config(user, extras=dict(EXTRAS))
            row = _manual_row(cfg)
        else:
            cfg = _config(user, mode="live" if live else "paper",
                          name="diff", extras=dict(EXTRAS))
            meta = {}
            if live:
                meta = {"broker": "etoro", "broker_env": "live"}
            if world == "protected":
                meta.update(protected=True, protective_trade_id="P1")
            row = _row(cfg, paper=not live, meta=meta)
        AssetBotTrade.objects.filter(pk=row.pk).update(
            opened_at=FIXED - timedelta(hours=1))
        row.refresh_from_db()
        orc = born(self, row, at=FIXED - timedelta(hours=1))
        row.refresh_from_db()
        return cfg, row, orc

    def _queue(self, orc, wake, kind, at, **kw):
        """An OrcIntent queued as the settle queues one."""
        from bot_program.orcs import journal
        from bot_program.orcs.constants import INTENT_TTL_S
        from bot_program.orcs.models import OrcIntent
        level = kw.pop("level", {})
        stop = kw.pop("would_stop", None)
        it = OrcIntent.objects.create(
            orc=orc, wake=wake, kind=kind, level=level,
            level_id=str(level.get("level_id") or ""),
            would_stop=None if stop is None else Decimal(str(stop)),
            mode="shadow", status="queued", why="queued for the shadow arm",
            expires_at=at + timedelta(seconds=INTENT_TTL_S), rung="r0",
            s_version="s1", schema_version="d1", **kw)
        OrcIntent.objects.filter(pk=it.pk).update(created_at=at)
        journal.remember(orc, intents_queued=(
            lambda cur, pk=it.pk: [x for x in (cur or [])
                                   if isinstance(x, int)] + [pk]))
        return it

    def _client(self, price):
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": price}
        client.get_positions.return_value = []
        client.close_needs_position_id.return_value = True
        client.modify_protective.return_value = {"ok": True, "price": None}
        return client

    def _run(self, cfg, row, *, at, price, hooked, checks):
        from bot_program.aragorn_models import AragornAction
        from bot_program.asset_engine.base import make_bot
        from bot_program.orcs import observe
        from tests.test_risk_limits_bind import _quote
        _quote("BTCUSD", price)
        client = self._client(price)
        bot = make_bot(cfg)
        AragornAction.objects.all().delete()
        real = observe.after_care

        def spy(bot_, trade, price_, cared=""):
            # the tick swallows what its hook raises: the copies are
            # compared after the pass
            before = _objects(trade)
            real(bot_, trade, price_, cared)
            checks.append((before, _objects(trade)))
        with ExitStack() as stack:
            stack.enter_context(patch(ROUTER, return_value=client))
            stack.enter_context(patch("django.utils.timezone.now",
                                      return_value=at))
            stack.enter_context(patch(HOOK, side_effect=spy) if hooked
                                else patch(HOOK, return_value=None))
            stack.enter_context(self.captureOnCommitCallbacks(execute=True))
            closed = bot.manage_positions()
        return {"closed": closed, "row": _snap(row),
                "actions": list(AragornAction.objects.order_by("id")
                                .values_list("kind", "detail", "symbol",
                                             "rule_name", "stats")),
                "calls": [repr(c) for c in client.mock_calls]}

    def _differential(self, world, *, managed):
        from bot_program.orcs.models import OrcIntent, OrcWake
        (cfg_a, row_a, orc_a) = self._side(world, "a")
        (cfg_b, row_b, orc_b) = self._side(world, "b")
        wake = OrcWake.objects.create(
            orc=orc_b, reasons=[], dedupe_key=f"diff:{orc_b.pk}",
            kind="routine", status="done",
            components={"vctx": {
                "atr": {"1h": 1.0, "4h": 2.0},
                "events": {f"C{self.event.pk}": {
                    "at": self.event.datetime.isoformat(), "ccy": "USD",
                    "kind": "print", "minutes": 70}}}})
        before = TICK_1[0] - timedelta(minutes=1)
        tighten = self._queue(orc_b, wake, "tighten", before, level={
            "level_id": "S1h-L1", "kind": "swing", "tf": "1h",
            "price": 101.2, "stop": WOULD_STOP}, would_stop=WOULD_STOP)
        trim = self._queue(orc_b, wake, "trim", before, share=0.5, level={
            "level_id": "P1h-H1", "kind": "pool", "tf": "1h", "price": 103.0,
            "stop": 103.2})
        waive = self._queue(orc_b, wake, "lock_waive", before,
                            event_id=f"C{self.event.pk}")
        checks, outs = [], []
        for n, (at, price) in enumerate((TICK_1, TICK_2), start=1):
            if n == 2:
                exit_ = self._queue(orc_b, wake, "exit",
                                    at - timedelta(minutes=1))
            a = self._run(cfg_a, row_a, at=at, price=price, hooked=False,
                          checks=checks)
            b = self._run(cfg_b, row_b, at=at, price=price, hooked=True,
                          checks=checks)
            outs.append((a, b))
            with self.subTest(world=world, tick=n):
                self.assertEqual(a["closed"], b["closed"])
                self.assertEqual(a["row"], b["row"])
                self.assertEqual(a["actions"], b["actions"])
                self.assertEqual(a["calls"], b["calls"])
                self.assertEqual(len(checks), n, "the hook ran once a tick")
                self.assertEqual(checks[-1][0], checks[-1][1],
                                 "the tick's objects are untouched")
            if n == 1:
                state = tracks_of(orc_b)["orc_shadow"].state
                self.assertEqual(state["mode"], "would")
                self.assertEqual(state["orc_stop"], WOULD_STOP)
                self.assertEqual(state["waived"], f"C{self.event.pk}")
        # not vacuous: every intent taken, the arm moved and closed in
        # shadow, the real stop strictly looser than the would-stop and the
        # second price between them, and the position still open
        for it in (tighten, trim, waive, exit_):
            it.refresh_from_db()
            self.assertEqual(it.status, "simulated", it.kind)
        self.assertEqual(OrcIntent.objects.filter(status="queued").count(),
                         0)
        arm = tracks_of(orc_b)["orc_shadow"]
        self.assertFalse(arm.open)
        self.assertEqual(arm.state["exit"]["kind"], "orc")
        self.assertEqual(tracks_of(orc_a)["orc_shadow"].state["mode"],
                         "real", "the unhooked Orc's arm never stepped")
        real_stop = Decimal(str(outs[-1][1]["row"]["stop_loss"]))
        self.assertLess(real_stop, Decimal(str(WOULD_STOP)))
        self.assertLess(real_stop, Decimal(TICK_2[1]))
        self.assertLess(Decimal(TICK_2[1]), Decimal(str(WOULD_STOP)))
        self.assertEqual(outs[-1][1]["row"]["status"], "OPEN")
        self.assertEqual(outs[-1][1]["row"]["take_profit"], Decimal("110"))
        self.assertEqual(managed(outs), True)

    def test_an_unprotected_live_bot_row(self):
        """The trailing stop and the SL/TP check run after the hook: the
        engine's break-even moved the row's own stop on both rows."""
        self._differential("bot", managed=lambda outs: outs[0][1]["row"][
            "stop_loss"] > Decimal("98"))

    def test_a_protected_etoro_style_row(self):
        """_manage_broker_stop runs after the hook: the venue was asked to
        move the stop, the same asks from both rows."""
        self._differential("protected", managed=lambda outs: any(
            "modify_protective" in c for c in outs[0][1]["calls"]))

    def test_a_manual_row(self):
        self._differential("manual", managed=lambda outs: outs[0][1]["row"][
            "metadata"]["care"]["soft_why"] in ("breakeven", "event lock"))

    def test_a_paper_row(self):
        self._differential("paper", managed=lambda outs: outs[0][1]["row"][
            "stop_loss"] > Decimal("98"))
