"""THE DECISION REPLAY HARNESS (the eToro feed spec, F1, §5.10; 2026-11-07).

The harness runs the REAL consumer code — today's money paths, untouched —
against fakes, and reads every decision back as plain data a golden table
can hold. Nothing here calls eToro, a broker or a model.

  * FakeClock: one fixed instant (T0, a Wednesday noon UTC: forex, crypto
    and commodities open, US stocks shut) that moves only when the scenario
    says. It is patched into django.utils.timezone.now — every reader that
    asks timezone.now() and every auto_now column (LiveQuote.updated_at) —
    and into the clocks of the shared rates cache and the quotes beat.
  * EtoroTrader: a fake eToro, named as the adapter so the engine's
    adapter_key reads "etoro". Its rates come from a script (a tick dict,
    or an exception the read raises); it RECORDS EVERY REQUEST it is
    given, with its arguments; and it FAILS EVERY WRITE the real client
    has — an order, a close, a cancel, a stop or a target move — with
    FakeWriteRefused, as a refusing venue reads, unless the scenario
    accepts writes (writes="accept"), when a close is answered in eToro's
    measured shape: PENDING, nothing executed, no price. ITS SURFACE IS THE
    REAL CLIENT'S (2026-11-07, the review of F1): a method the real
    EtoroTrader has and no scenario scripted is recorded and refused
    (FakeUnscripted), never missing — so an engine probe such as
    getattr(client, "modify_protective", None) takes the real client's
    branch — and a name the real client lacks is missing here too. The
    real client's local helpers answer as it does without the wire: its
    world, its key's name, and no instrument id known (no cache read).
  * Fake LiveQuote writers: write_live_quote goes through the real
    market_data.quotes.write_quote — its precedence and its 300 s hold —
    then dates the row on the fake clock.
  * Fixtures: synthetic rows (EURUSD, XAUUSD, AAPL, BTCUSD) at round
    synthetic values, and readers that turn a Mark, a row or a verdict
    into a dict.

tests/feed/test_decision_replay.py holds the golden scenarios: today's
decisions, recorded on main before F1 touched a money path.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

#: The replay's instant: Wednesday 2026-11-04 12:00 UTC.
T0 = datetime(2026, 11, 4, 12, 0, tzinfo=dt_tz.utc)
#: Where the engine asks for a symbol's client.
ROUTER = "bot_program.engine.broker_router.client_for_symbol"
#: The real client's writes (bot_program.engine.etoro_client.EtoroTrader):
#: every one fails unless the scenario accepts writes.
WRITE_METHODS = ("market_order", "close_position", "cancel_order",
                 "modify_protective", "modify_target")
#: eToro's measured answer to an accepted close (etoro_client
#: .close_position): submitted, nothing executed yet, no price.
PENDING_CLOSE = {"orderId": "c-1", "status": "PENDING",
                 "executedQty": "0.0"}


class FakeClock:
    """A clock that moves only when told. Use as a context manager."""

    def __init__(self, start=T0):
        self.now = start
        self._patches = []

    def advance(self, seconds=0, **kw):
        self.now = self.now + timedelta(seconds=seconds, **kw)
        return self.now

    def ago(self, seconds):
        return self.now - timedelta(seconds=seconds)

    def __call__(self):
        return self.now

    def _epoch(self):
        return self.now.timestamp()

    def __enter__(self):
        self._patches = [
            mock.patch("django.utils.timezone.now", side_effect=self),
            mock.patch("bot_program.engine.etoro_rates._now",
                       side_effect=self._epoch),
            mock.patch("bot_program.etoro_quotes._now",
                       side_effect=self._epoch),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        self._patches = []
        return False


class FakeWriteRefused(RuntimeError):
    """The fake eToro refused a write: the replay never sends anything."""


class FakeUnscripted(RuntimeError):
    """The real client has this method and the scenario scripted no answer:
    recorded, and refused."""


_REAL_SURFACE: dict = {}


def real_surface() -> frozenset:
    """Every method of the real eToro client (its callables, public and
    private, dunders aside)."""
    if "names" not in _REAL_SURFACE:
        import inspect

        from bot_program.engine.etoro_client import EtoroTrader as Real
        _REAL_SURFACE["names"] = frozenset(
            n for n in dir(Real) if not n.startswith("__")
            and callable(inspect.getattr_static(Real, n)))
    return _REAL_SURFACE["names"]


class EtoroTrader:
    """A FAKE eToro (see the module docstring). `rates`: {symbol: tick dict
    or an exception to raise}; a symbol with none raises. `positions`: the
    list get_positions answers, or None for a book that cannot be read."""

    PORTFOLIO_LAG_S = 0
    env = "live"
    demo = False

    def __init__(self, rates=None, *, writes="fail", positions=None,
                 close_answer=None):
        if writes not in ("fail", "accept"):
            raise ValueError(writes)
        self.rates = dict(rates or {})
        self.writes = writes
        self.positions = positions
        self.close_answer = dict(close_answer or PENDING_CLOSE)
        self.requests = []

    # ── what the replay reads back ───────────────────────────────────
    def _note(self, method, *args):
        self.requests.append((method,) + tuple(str(a) for a in args))

    @property
    def methods(self) -> list:
        return [r[0] for r in self.requests]

    @property
    def writes_sent(self) -> list:
        """Every write asked, with its arguments (a close's position id,
        symbol and quantity; an order's symbol, side and quantity; a stop
        or target move's position id and level)."""
        return [list(r) for r in self.requests if r[0] in WRITE_METHODS]

    # ── the real client's local helpers (no request) ─────────────────
    def _world(self):
        return "demo" if self.demo else "live"

    def _bkey(self):
        return "replay-key"

    def _known_id(self, symbol):
        """No id known without the wire: the rates cache is never read."""
        return None

    def __getattr__(self, name):
        if name.startswith("__") or name not in real_surface():
            raise AttributeError(name)

        def unscripted(*args, **kwargs):
            self._note(name, *args)
            raise FakeUnscripted(f"the replay scripted no answer for "
                                 f"eToro's {name}")
        unscripted.__name__ = name
        return unscripted

    # ── reads ────────────────────────────────────────────────────────
    def ticker(self, symbol):
        self._note("ticker", symbol)
        answer = self.rates.get(symbol)
        if answer is None:
            raise RuntimeError(f"eToro: no rate for {symbol} (replay)")
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)

    def get_positions(self, *a, **k):
        self._note("get_positions")
        if self.positions is None:
            raise RuntimeError("eToro: the book cannot be read (replay)")
        return [dict(p) for p in self.positions]

    def close_needs_position_id(self):
        return True

    # ── writes: refused unless the scenario accepts them ─────────────
    def _write(self, method, *args):
        self._note(method, *args)
        if self.writes != "accept":
            raise FakeWriteRefused(f"the replay refuses eToro's {method}")
        return dict(self.close_answer)

    def close_position(self, position_id, symbol, qty, client_order_id="",
                       open_order_id=""):
        return self._write("close_position", position_id, symbol, qty)

    def market_order(self, symbol, side, qty, *a, **k):
        return self._write("market_order", symbol, side, qty)

    def cancel_order(self, order_id):
        return self._write("cancel_order", order_id)

    def modify_protective(self, trade_id, new_price):
        self._write("modify_protective", trade_id, new_price)
        return {"ok": True, "price": float(new_price)}

    def modify_target(self, trade_id, new_price):
        self._write("modify_target", trade_id, new_price)
        return {"ok": True, "price": float(new_price)}


def tick(last, *, spread="0.0002"):
    """A rates answer: lastPrice with a bid and an ask around it."""
    last, half = Decimal(str(last)), Decimal(str(spread)) / 2
    return {"lastPrice": str(last), "bid": str(last - half),
            "ask": str(last + half)}


@contextlib.contextmanager
def route_to(client):
    """Every client the engine asks for is `client`."""
    with mock.patch(ROUTER, return_value=client):
        yield client


# ── fixtures ─────────────────────────────────────────────────────────────

def user(name):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.create_user(name, password="x")


def instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def live_config(owner, asset_class, name="replay"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=owner, asset_class=asset_class, name=name, enabled=True,
        mode="live", symbols=[], capital=Decimal("10000"))


def real_row(cfg, symbol, *, side="BUY", entry, stop, target, qty="1",
             meta=None, status="OPEN", position_id="p-1"):
    """An eToro real row, as the lanes stamp one."""
    from bot_program.models import AssetBotTrade
    m = {"broker": "etoro", "initial_stop_loss": float(stop),
         "broker_position_id": position_id, "value_per_unit": 1.0}
    m.update(meta or {})
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)), take_profit=Decimal(str(target)),
        status=status, paper=False, rule_name="replay", metadata=m)


def stamp(price, *, age_s, clock, bid=None, ask=None, via="tick"):
    """A venue stamp (metadata["venue_mark"]) `age_s` old on the clock."""
    vm = {"price": float(price), "at": clock.ago(age_s).isoformat(),
          "source": "etoro", "via": via}
    if bid is not None:
        vm["bid"] = float(bid)
    if ask is not None:
        vm["ask"] = float(ask)
    return {"venue_mark": vm}


def write_live_quote(symbol, *, source, last, clock, bid=None, ask=None,
                     age_s=0, asset_class="forex"):
    """A fake LiveQuote writer: the real write_quote, then the row dated
    `age_s` before the clock. True when the precedence let it write."""
    from market_data.models import LiveQuote
    from market_data.quotes import write_quote
    inst = instrument(symbol, asset_class)
    ok = write_quote(symbol, last=last, source=source, bid=bid, ask=ask,
                     instrument=inst)
    if ok and age_s:
        LiveQuote.objects.filter(instrument=inst).update(
            updated_at=clock.ago(age_s))
    return ok


def live_quote(symbol):
    from market_data.models import LiveQuote
    return LiveQuote.objects.filter(instrument__symbol=symbol).first()


# ── readers: decisions as plain data ─────────────────────────────────────

def num(value):
    """A number as golden text: Decimal's normal form, or None."""
    if value is None:
        return None
    return format(Decimal(str(value)).normalize(), "f")


def mark_of(mk):
    if mk is None:
        return None
    return {"price": num(mk.price), "source": mk.source,
            "age_s": None if mk.age_s is None else int(round(mk.age_s)),
            "stand_in": mk.stand_in}


def row_state(trade):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.get(pk=trade.pk)
    meta = t.metadata or {}
    return {"status": t.status, "exit_price": num(t.exit_price),
            "pnl": num(t.pnl),
            "exit_fill_source": meta.get("exit_fill_source"),
            "unpriced": bool(meta.get("exit_price_unavailable")),
            "exit_mark_age_s": meta.get("exit_mark_age_s"),
            "inferred": meta.get("exit_price_inferred")}
