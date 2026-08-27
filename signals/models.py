"""Signal models — detected trading opportunities."""
from django.db import models
from instruments.models import Instrument
from core.constants import Direction, Urgency


class Signal(models.Model):
    SIGNAL_TYPES = [
        ("technical", "Technical"),
        ("fundamental", "Fundamental"),
        ("sentiment", "Sentiment"),
        ("macro", "Macro"),
        ("flow", "Institutional Flow"),
        ("ai_generated", "AI Generated"),
        ("composite", "Composite"),
    ]

    OUTCOME_CHOICES = [
        ("hit_target", "Hit Target"),
        ("stopped_out", "Stopped Out"),
        ("expired", "Expired"),
        ("manual_close", "Manually Closed"),
    ]

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="signals")
    signal_type = models.CharField(max_length=20, choices=SIGNAL_TYPES)
    direction = models.CharField(max_length=10, choices=Direction.CHOICES)
    urgency = models.CharField(max_length=10, choices=Urgency.CHOICES)

    title = models.CharField(max_length=300)
    description = models.TextField()
    rule_name = models.CharField(max_length=100)

    score = models.FloatField()
    sub_scores = models.JSONField(default=dict)

    price_at_signal = models.DecimalField(max_digits=20, decimal_places=8)
    suggested_entry = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    suggested_stop = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    suggested_target = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    risk_reward_ratio = models.FloatField(null=True)

    portfolio_impact = models.TextField(blank=True)
    conflicts_with = models.ManyToManyField("self", blank=True, symmetrical=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expired_at = models.DateTimeField(null=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, blank=True)

    # Self-grading fields (Phase 1.0 — "the system grades itself")
    realized_r = models.FloatField(null=True, blank=True)
    mfe = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    mae = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    time_to_outcome_seconds = models.IntegerField(null=True, blank=True)

    # Live exposure, in the two statuses the rest of the platform counts as
    # exposure (AssetBotTrade.STATUS_CHOICES: CLOSE_PENDING is still open at
    # the broker while the bot wants it flat).
    ACTED_STATUSES = ("OPEN", "CLOSE_PENDING")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["instrument", "is_active"]),
            models.Index(fields=["outcome", "expired_at"], name="signals_sig_outcome_idx"),
            models.Index(fields=["signal_type", "expired_at"], name="signals_sig_type_idx"),
        ]

    def __str__(self):
        return f"[{self.direction.upper()}] {self.title} (score: {self.score:.2f})"

    # ── Has anything already acted on this signal? ──────────────────────
    #
    # The report that produced this: the engine entered EURGBP on a rule,
    # the rail card sat there looking like an untaken idea, and the same
    # symbol was then booked a second time by hand. A signal something has
    # already acted on has to SAY so, or the rail is inviting the operator
    # to double-stack the engine's own exposure.
    #
    # There is no signal FK on a trade to read. Adding one would only fix
    # trades opened after the migration, and the join has to work on the
    # book as it stands — so it is derived from what both entry paths
    # already write:
    #
    #   manual  bot_program.manual_trade stamps metadata["signal_id"] with
    #           this row's pk. Exact, one trade to one signal.
    #   bot     asset_engine.base._open copies BotDecision.rule_name onto
    #           AssetBotTrade.rule_name, and decide() lifts that name off
    #           the winning Signal. So the honest join is the STRING
    #           rule_name — the same join RuleControl, the graders and the
    #           track-record lanes already use — narrowed by symbol and by
    #           time: a position opened BEFORE this signal fired cannot
    #           have been opened because of it.
    #
    # What the string join cannot claim: a bot decision whose winning rule
    # came back empty is tagged "asset_bot_signal_consensus" /
    # "asset_bot_weighted_consensus", which matches no Signal.rule_name.
    # Those trades stay unjoined rather than being guessed at — an unmarked
    # card is a card that says nothing, a wrongly-marked one is a lie.
    #
    # Only LIVE exposure counts. A rule that entered and has already exited
    # leaves the idea open again, and a permanent TAKEN badge over a flat
    # book would be the same failure pointing the other way.
    @property
    def acted(self):
        """The live position this signal is already answerable for, or None.

        Cached per instance: the rail template reads it three times per
        card (wrapper class, badge, popup) and one render must not cost
        three queries.
        """
        if not hasattr(self, "_acted_cache"):
            self._acted_cache = self._resolve_acted()
        return self._acted_cache

    def _resolve_acted(self):
        if not self.pk or not self.created_at:
            return None
        try:
            from django.db.models import Q
            from bot_program.models import AssetBotTrade

            match = Q(metadata__signal_id=self.pk)
            if self.rule_name:
                match |= Q(rule_name=self.rule_name)
            trade = (AssetBotTrade.objects
                     .filter(symbol=self.instrument.symbol,
                             status__in=self.ACTED_STATUSES,
                             opened_at__gte=self.created_at)
                     .filter(match)
                     .order_by("-opened_at")
                     .first())
        except Exception:  # noqa: BLE001 — the rail renders regardless
            return None
        if trade is None:
            return None
        meta = trade.metadata or {}
        exact = meta.get("signal_id") == self.pk
        return {
            # "manual" only on the exact metadata join or the manual flag —
            # never inferred from the rule string, which is what a bot wrote.
            "by": "manual" if (exact or meta.get("manual")) else "bot",
            "exact": bool(exact),
            "side": trade.side,
            "qty": float(trade.qty),
            "venue": "PAPER" if trade.paper else "LIVE",
            "rule": trade.rule_name or "",
            "trade_id": trade.pk,
            "opened_at": trade.opened_at,
            "entry": float(trade.entry_price) if trade.entry_price else None,
            "stop": float(trade.stop_loss) if trade.stop_loss else None,
            "target": float(trade.take_profit) if trade.take_profit else None,
            # The stop RESTS AT THE BROKER for a bracketed position, which
            # is the difference between "protected while the platform is
            # down" and "protected only while it is up". The card should
            # not make an operator open another page to learn which.
            "protected": bool((trade.metadata or {}).get("protected")),
            # Live money on the bet, or None. None rather than 0.0: a
            # position whose instrument has no quote has an UNKNOWN P&L,
            # and a zero there reads as flat.
            "pnl": self._acted_pnl(trade),
        }

    def _acted_pnl(self, trade):
        """Unrealised money on an open trade at the current mark."""
        try:
            from portfolio.services import value_per_unit
            quote = getattr(self.instrument, "live_quote", None)
            mark = float(quote.last) if quote and quote.last else None
            entry = float(trade.entry_price) if trade.entry_price else None
            qty = float(trade.qty) if trade.qty else None
            if not (mark and entry and qty):
                return None
            move = (mark - entry) if trade.side == "BUY" else (entry - mark)
            return move * qty * value_per_unit(trade)
        except Exception:  # noqa: BLE001 — a card must not 500 the rail
            return None
from .models_smc import SmcSignal  # noqa: F401
from .models_control import (  # noqa: F401
    RuleControl, RuleAction, MetaAllocation, PromotionEvent, RuleMutation,
)
from .models_opportunity import OpportunitySetup, OpportunityFlag, DiscoveredSetup  # noqa: F401
from .models_events import FastEvent  # noqa: F401


# ── WS push on signal creation ──────────────────────────────────────────
# dashboard.consumers.push_signal_notification existed with ZERO call
# sites: the frontend had a 'signal' message handler, the backend had a
# broadcaster, and no code path ever connected a created Signal to either
# — so the rail only ever changed on a page load. A post_save receiver is
# the one choke point every creation path shares (rule adapter, SMC
# bridge, opportunity scanner, event engine).
from django.db.models.signals import post_save as _post_save  # noqa: E402
from django.dispatch import receiver as _receiver  # noqa: E402


@_receiver(_post_save, sender=Signal, dispatch_uid="ws_push_new_signal")
def _push_new_signal(sender, instance, created, **kwargs):
    if not created or not instance.is_active:
        return
    try:
        from dashboard.consumers import push_signal_notification
        push_signal_notification({
            "id": instance.id,
            "symbol": instance.instrument.symbol,
            "direction": instance.direction,
            "title": instance.title or "",
            "score": float(instance.score or 0),
            "urgency": instance.urgency or "",
        })
    except Exception:  # noqa: BLE001 — a WS hiccup must never fail creation
        pass
