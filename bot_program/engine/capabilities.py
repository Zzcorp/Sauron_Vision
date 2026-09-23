"""WHAT EACH BROKER CAN ACTUALLY BE ASKED TO DO (2026-09-15)

Written before adding Saxo and eToro, because the seam they plug into had no
guard on it at all.

A broker client is duck-typed across roughly two dozen methods, and the only
thing the suite checked was `len(BROKER_ADAPTERS)` — it COUNTED the adapters.
An adapter missing `modify_protective` would pass every test and fail at
runtime, on a live position, at the moment a trailing stop is moved.

WHAT THE MEASUREMENT SHOWED

Only FIVE methods are implemented by all six adapters today: `ping`,
`ticker`, `klines`, `order_book`, `market_order`. Everything else varies, and
the variation is not sloppiness — it is real:

  * `net_liquidation` / `broker_portfolio` exist only on IBKR, which is why
    `sync_broker_account` reads only IBKR accounts.
  * `modify_protective` / `modify_target` are absent from both Binance
    clients and from PaperTrader, so a trailing stop or a break-even move
    cannot be asked of them.
  * options live on IBKR alone; leverage and margin type on Binance futures
    alone.

So a flat "every adapter implements every method" contract would be a lie
that fails on day one. The honest shape is TIERS: a capability is a set of
methods that go together, and each adapter fills the tiers it can.

WHY THIS IS DECLARED *AND* DERIVED

`ADAPTER_CAPABILITIES` is what this platform BELIEVES about each adapter.
`capabilities_of()` reads the class and reports what is actually there. The
test in tests/test_broker_contract.py confronts the two, so:

  * an adapter that quietly loses a method fails the suite
  * a new adapter that fills a tier only partly fails the suite, naming the
    method it is missing
  * a capability claimed here and not implemented fails the suite

Neither side can be edited into agreement with a bug without editing the
other, which is the whole point.

WHAT IT IS FOR, BEYOND CATCHING MISTAKES

It is a map of what to DELEGATE. The engine currently runs its own trailing
stop because IBKR does not hold one. eToro does, natively, and a trailing
stop held at the broker survives the platform being down while this one does
not. A capability table is how the engine stops doing by hand what a
particular venue does better — and how it keeps doing by hand what no venue
does at all. The time stop is the standing example: no broker holds one, so
`asset_engine` must, forever.
"""
from __future__ import annotations

#: A capability is a set of methods that are useless apart. Asking for half a
#: bracket is not half a feature, it is a position whose stop can be set and
#: never moved.
CAPABILITIES: dict = {
    # Reading the market. Without it nothing can decide at all.
    "market_data": ("ping", "ticker", "klines", "order_book"),
    # Opening a position.
    "execution": ("market_order",),
    # Knowing and unwinding what is open.
    "orders": ("cancel_order", "get_positions"),
    # Moving a protective leg after entry: the trailing stop and the
    # break-even move both live here.
    "brackets": ("modify_protective", "modify_target"),
    # The price a close actually filled at, from the venue rather than from
    # a mark read a moment earlier.
    "fills": ("closing_fill",),
    # Reading the account itself — what `sync_broker_account` needs.
    "account": ("net_liquidation", "broker_portfolio"),
    "options": ("option_chain", "option_greeks", "market_order_option"),
    # 2026-09-20. Asking a venue the smallest size it will accept, BEFORE an
    # order exists. Saxo alone can answer: its instrument details carry
    # LotSize/LotSizeType and MinimumTradeSize, and `_amount` already
    # enforces them by RAISING rather than upsizing. eToro cannot — the only
    # per-instrument payload its adapter reads is the market-data search
    # result, read for `instrumentId` and the symbol spelling, and it
    # carries no size field. So an eToro floor IN UNITS cannot be known
    # before the order and no adapter invents one; the operator may declare
    # a MONEY floor per config (extras['venue_min_notional'], read by
    # asset_engine/base.py::_venue_size_floor as a fourth, labelled state),
    # and the `fractional_units` tier below is a separate, labelled belief.
    # OANDA, Alpaca, IBKR, Binance and
    # PaperTrader go unasked for the same reason: no method, which the
    # engine reads as unmeasured and never as zero.
    "size_floor": ("min_tradable",),
    # 2026-09-23. A venue that takes a NON-WHOLE unit count. ONE method, and
    # it carries no number: eToro declares it as a BELIEF from the public
    # reference (create-an-order documents `units` as a double "greater than
    # 0" with no integer constraint; the portfolio example holds 0.049485
    # units), never as a measurement — the measured answer is per instrument
    # on POST /api/v2/trading/info/eligibility (`unitsQuantityType`), which
    # no adapter calls yet. The ENGINE reads it off the CLIENT the router
    # hands the entry and holds every stock size at WHOLE shares until the
    # `fractional_units_live` component is ON (core/platform_control),
    # which is flipped only after ETORO_DEPARTURE §4 D2c measured a
    # fractional fill. A money floor is NOT part of this tier: that number is
    # the operator's (extras['venue_min_notional']), never an adapter's.
    "fractional_units": ("takes_fractional_units",),
    "leverage": ("set_leverage", "set_margin_type"),
}

#: What this platform believes each adapter provides. MEASURED on 2026-09-15
#: by inspecting the classes, not aspirational — a table of what ought to be
#: there would fail on the day it was written and be deleted by the next
#: person to see it red.
ADAPTER_CAPABILITIES: dict = {
    "alpaca": ("market_data", "execution", "orders", "brackets", "fills"),
    "binance": ("market_data", "execution"),
    # NOT "orders": it lists positions and cannot cancel a resting order.
    # Found by the conformance test on its first run, against a table this
    # author had written from memory a minute earlier — which is the whole
    # argument for deriving the second opinion from the class.
    "binance_futures": ("market_data", "execution", "leverage"),
    # 2026-09-17. NOT "orders": the reference documents no cancel for a
    # pending order. NOT "fills": no closed-position history is documented
    # and the close confirmation has not met a real key. A method that
    # existed and could not act would pass this table's test and lie.
    # 2026-09-23. NOT "leverage" either: that tier means set_leverage /
    # set_margin_type — per-SYMBOL venue state, Binance futures' shape.
    # eToro's multiplier is a FIELD OF EACH ORDER BODY (market_order's
    # `leverage=` kwarg, refused before the POST when it is not a whole
    # number in [1, LEVERAGE_MAX] or arrives above 1 without a stop). Two
    # fake methods to satisfy the tier would be exactly the lie the header
    # warns about, so the per-order shape is a kwarg contract on
    # "execution", written in asset_engine/base.py first and pinned by
    # tests/test_etoro_leverage.py. `margin_cells` belongs to no tier.
    # "fractional_units" 2026-09-23: a belief, see the tier — sent only
    # while fractional_units_live is ON; D2c measures it.
    # "orders" 2026-09-24 (D3b): MEASURED 2026-09-23 20:29 UTC on the demo
    # segment - DELETE v3 -> 202, the lookup then 7 Canceled. cancel_order
    # is lookup-first and refuses (False) any id it cannot read; the real
    # spelling raises until measured; order_status is in no tier.
    "etoro": ("market_data", "execution", "orders", "brackets",
              "account", "fractional_units"),
    "ibkr": ("market_data", "execution", "orders", "brackets", "account",
             "options"),
    "oanda": ("market_data", "execution", "orders", "brackets", "fills"),
    # 2026-09-17. The full contract, every method read off developer.saxo
    # by two independent readers (scratchpad saxo_spec.md). "fills" is
    # earned by /port/v1/closedpositions and the audit log's FinalFill;
    # "orders" by DELETE /trade/v2/orders; "brackets" by PATCH on the
    # related legs. Four facts only SIM can settle are named in the
    # adapter and probed by `saxo_smoke` before any order exists.
    # "size_floor" 2026-09-20: the ONLY venue that can be asked its
    # minimum trade size before an order. The tier above says why eToro
    # cannot be; asset_engine/base.py::_venue_size_floor says what the
    # engine does with an unmeasured answer, which is refuse nothing.
    "saxo": ("market_data", "execution", "orders", "brackets", "fills",
             "account", "size_floor"),
    # The simulator deliberately fills only what it can honestly simulate.
    # It is what a live config falls back to when credentials are missing,
    # and `asset_engine` REFUSES to trade when it gets one — so a PaperTrader
    # that claimed "brackets" would make that refusal harder to see, not
    # easier.
    "paper": ("market_data", "execution"),
}


#: Adapter CLASS NAME -> broker key. The engine holds a client, not a
#: name, and a live row must be able to record WHICH broker carried it —
#: an attribution the platform can otherwise only infer from today's
#: routing rule, which is wrong for every row opened before a flag moved.
#: Held against the published adapter list by tests/test_broker_contract.py.
ADAPTER_CLASS_KEYS = {
    "AlpacaTrader": "alpaca",
    "BinanceClient": "binance",
    "BinanceFuturesClient": "binance_futures",
    "EtoroTrader": "etoro",
    "IBKRTrader": "ibkr",
    "OANDATrader": "oanda",
    "PaperTrader": "paper",
    "SaxoTrader": "saxo",
}


def adapter_key(client_or_class) -> str:
    """The broker key for a client instance or class, or "" when unknown.

    An empty string rather than a guess: a row that records the wrong
    broker is worse than one that records none, because the divergence
    view would then confidently compare it against the wrong holdings.
    """
    name = getattr(client_or_class, "__name__", None) \
        or type(client_or_class).__name__
    return ADAPTER_CLASS_KEYS.get(name, "")


def capabilities_of(client_or_class) -> tuple:
    """The capabilities actually present on a client, by inspection.

    A tier counts only when EVERY method in it is present and callable.
    Half a bracket is not half a capability.
    """
    target = (client_or_class if isinstance(client_or_class, type)
              else type(client_or_class))
    out = []
    for name, methods in CAPABILITIES.items():
        if all(callable(getattr(target, m, None)) for m in methods):
            out.append(name)
    return tuple(out)


def missing_methods(client_or_class, capability: str) -> tuple:
    """Which methods of `capability` this client does not have."""
    target = (client_or_class if isinstance(client_or_class, type)
              else type(client_or_class))
    return tuple(m for m in CAPABILITIES.get(capability, ())
                 if not callable(getattr(target, m, None)))


def has_capability(client, capability: str) -> bool:
    """Can this client be asked for `capability`?

    Asked of the INSTANCE rather than a table, so a client the router built
    in some unusual way answers for itself. The table is what the suite
    checks; this is what the engine calls.
    """
    return not missing_methods(client, capability)


def declared(adapter: str) -> tuple:
    """What the table says `adapter` provides, or () for an unknown name."""
    return tuple(ADAPTER_CAPABILITIES.get(adapter, ()))
