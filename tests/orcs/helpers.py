"""Shared fixtures for the Orcs' suites. No network anywhere: every broker
is a MagicMock and every switch a PlatformComponent row."""
from decimal import Decimal

from django.contrib.auth import get_user_model

from tests.test_aragorn import _switch  # noqa: F401  (re-exported)
from tests.test_risk_limits_bind import _config  # noqa: F401  (re-exported)

ROUTER = "bot_program.engine.broker_router.client_for_symbol"


def _user(name="orc_u"):
    return get_user_model().objects.create_user(name, password="x")


def _on(on=True):
    """The orcs switch, and the platform master the census's gate reads."""
    _switch("platform_master", True)
    _switch("orcs", on)


def _manual_config(user, asset_class="crypto", **kw):
    from bot_program.manual_trade import MANUAL_CONFIG_NAME
    return _config(user, asset_class, name=MANUAL_CONFIG_NAME, symbols=[],
                   **kw)


def _row(cfg, *, qty="1", entry="100", stop="98", side="BUY", paper=True,
         cls=None, symbol="BTCUSD", meta=None, rule="golden_cross",
         status="OPEN", target="110"):
    """An open trade row: entry 100, stop 98, so 102 is +1R."""
    from bot_program.models import AssetBotTrade
    base = {} if stop is None else {"initial_stop_loss": float(stop)}
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cls or cfg.asset_class, symbol=symbol,
        side=side, qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=None if stop is None else Decimal(stop),
        take_profit=None if target is None else Decimal(target),
        status=status, paper=paper, rule_name=rule,
        metadata={**base, **(meta or {})})


def _manual_row(cfg, **kw):
    from bot_program.manual_trade import MANUAL_RULE
    kw.setdefault("rule", MANUAL_RULE)
    return _row(cfg, **kw)


def born(test, trade, **kw):
    """ensure() with the after-commit work run, as the hooks run it."""
    from bot_program.orcs.birth import ensure
    with test.captureOnCommitCallbacks(execute=True):
        return ensure(trade, **kw)


def journal(orc, **filters):
    from bot_program.orcs.models import OrcJournal
    return list(OrcJournal.objects.filter(orc=orc, **filters)
                .order_by("at", "id"))


def headlines(orc, **filters):
    return [e.headline for e in journal(orc, **filters)]
