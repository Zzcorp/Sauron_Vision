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
    "ibkr": ("market_data", "execution", "orders", "brackets", "account",
             "options"),
    "oanda": ("market_data", "execution", "orders", "brackets", "fills"),
    # The simulator deliberately fills only what it can honestly simulate.
    # It is what a live config falls back to when credentials are missing,
    # and `asset_engine` REFUSES to trade when it gets one — so a PaperTrader
    # that claimed "brackets" would make that refusal harder to see, not
    # easier.
    "paper": ("market_data", "execution"),
}


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
