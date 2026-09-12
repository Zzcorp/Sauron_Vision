"""EntryCandidate — what a bot WOULD do, before it does it.

`AssetBot.scan_symbol` was one inline function from "is a position already
on" to "push the fill to the websocket", and a fleet of configs ran it one
config after another. Nothing could look at the whole tick's opportunities
side by side: by the time the third config proposed its entry, the first two
had already filled. The capital desk needs exactly that view, so the entry
path is split at the point where the bot has finished deciding and sizing
but has not yet sent anything — `propose_entry` produces one of these, and
`execute_entry` consumes it.

The candidate carries the bot's OWN final size (`qty_default`, after the
allocator lane, the promotion lane, the correlation taper and rounding) and
the arithmetic the desk ranks on. The desk may only ever shrink that size:
`execute_entry` re-judges qty_default x size_mult against every ceiling the
bot applied the first time, and a multiplier past MAX_RISK_FRACTION is
refused there, not clamped (2026-09-12).

Not persisted. It lives for one tick, in memory, and holds a reference to
the bot that produced it so the executing pass can hand it straight back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from django.utils import timezone


# The horizon a candidate is graded over when the config's time stop is off
# (`time_stop_setting()["hours"]` is 0.0 exactly then). One trading week: the
# desk's counterfactual walk needs SOME bound, and "forever" would never
# resolve a displaced decision.
DEFAULT_HORIZON_HOURS = 168.0


@dataclass
class EntryCandidate:
    """One proposed entry, sized by its bot, not yet sent.

    `venue` is where the row WOULD be filed: 'paper' when the config is in
    paper mode OR the rule's promotion stage forces paper, else 'live'. It
    is the same rule `execute_entry` uses for `AssetBotTrade.paper`, so a
    desk budget keyed on it never nets a paper candidate against live risk.

    `per_unit_risk` is |price - stop| x value_per_unit — account-currency
    loss per unit at the initial stop — and `risk_dollars_default` is that
    times `qty_default`. This is the ACTUAL risk at entry; `sizing` carries
    the pre-multiplier `risk_dollars` the sizer asked for, which is a
    different number whenever any lane scaled the quantity.
    """
    bot: Any = field(repr=False)
    cfg_id: int
    user_id: int
    symbol: str
    instrument_id: Optional[int]
    asset_class: str
    venue: str                       # 'paper' | 'live'
    decision: Any                    # BotDecision: direction/score/reasons/rule_name
    price: float                     # the fill the levels and size are relative to
    market_price: float              # the raw ticker before any paper haircut
    stop: float                      # POST-floor stop — the one that will be placed
    target: float
    level_meta: dict
    cost_reason: str
    stage: dict                      # stage_policy() verdict for the rule
    sizing: dict                     # size_position() output (pre-multiplier)
    qty_default: float               # the bot's own final size (post J/K/L)
    per_unit_risk: float
    risk_dollars_default: float
    notional_default: float
    value_per_unit: float
    corr_scale: float = 1.0
    horizon_hours: float = DEFAULT_HORIZON_HOURS
    created_at: datetime = field(default_factory=timezone.now)

    @property
    def direction(self) -> str:
        return self.decision.direction

    @property
    def rule_name(self) -> str:
        return self.decision.rule_name or ""

    def summary(self) -> dict:
        """The candidate without its bot — loggable, JSON-safe."""
        return {
            "cfg_id": self.cfg_id, "user_id": self.user_id,
            "symbol": self.symbol, "asset_class": self.asset_class,
            "venue": self.venue, "direction": self.direction,
            "rule_name": self.rule_name, "score": float(self.decision.score),
            "price": self.price, "stop": self.stop, "target": self.target,
            "qty_default": self.qty_default,
            "per_unit_risk": self.per_unit_risk,
            "risk_dollars_default": self.risk_dollars_default,
            "notional_default": self.notional_default,
            "corr_scale": self.corr_scale,
            "horizon_hours": self.horizon_hours,
            "created_at": self.created_at.isoformat(),
        }
