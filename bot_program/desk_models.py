"""The capital desk's record — one plan per (user, venue) per fleet pass.

The operator's ask was "an agent that continuously recomputes, from the
opportunities available and the risk, the best way to place capital". These
two tables are what that agent leaves behind, and they exist for one reason:
a desk whose decisions cannot be re-read a week later is a desk nobody can
grade. Every candidate the fleet produced on a tick gets a row — the ones
taken AND the ones refused — with the evidence lane it was ranked on, the
marginal risk it would have added, and one reason in words.

`DeskDecision.counterfactual_r` is the whole point of the displaced rows. The
desk is graded on the DIFFERENCE between what it did and what the fleet would
have done undesked, so a displaced candidate carries its price, its stop, its
target and its horizon: Stage 3 walks the bars over that horizon and books
the R the trade would have made. Without those five fields a displacement is
an opinion; with them it is a measurement.

Nothing here is on the money path. The desk may only ever SHRINK a size
(`size_mult` <= 1.0) and every per-order ceiling in `execute_entry` is
re-judged after the multiplier lands, so a plan row can cost an opportunity
and can never cost more risk than the bot had already cleared (2026-09-12).
"""
import uuid

from django.conf import settings
from django.db import models


class DeskPlan(models.Model):
    """One capital-desk pass over one user's candidates on one venue.

    Keyed on (user, venue) and never on the fleet: paper and live are never
    netted anywhere else in this platform and they are not netted here. Two
    plans are written on a tick that produced candidates on both venues, each
    with its own budget, its own book and its own correlation penalty.

    `mode` is SHADOW or LIVE as the `capital_desk_mode_live` component stood
    when the plan was made. In SHADOW the fleet executed every candidate at
    its own size exactly as it always has and this row is the counterfactual
    being graded; in LIVE the displaced were skipped and the resized were
    multiplied. The column, not a lookup at read time: the switch can be
    flipped between the plan and its grade, and the grade is about the plan.
    """

    VENUE_PAPER = "paper"
    VENUE_LIVE = "live"
    VENUE_CHOICES = [(VENUE_PAPER, "Paper"), (VENUE_LIVE, "Live")]

    MODE_SHADOW = "shadow"
    MODE_LIVE = "live"
    MODE_CHOICES = [
        (MODE_SHADOW, "Shadow (recorded, the fleet is unchanged)"),
        (MODE_LIVE, "Live (the fleet obeys the plan)"),
    ]

    # One id per FLEET PASS, shared by that pass's per-venue plans, so the
    # two halves of a tick can be read back as one event.
    tick_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE,
                             related_name="desk_plans")
    venue = models.CharField(max_length=5, choices=VENUE_CHOICES)
    mode = models.CharField(max_length=6, choices=MODE_CHOICES,
                            default=MODE_SHADOW)

    # The arithmetic, in the account currency. `budget` is already net of
    # `book_risk` and already through the drawdown governor — it is what was
    # left to spend, not the gross allowance (see capital_desk.plan_for).
    budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    book_risk = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    new_risk_chosen = models.DecimalField(max_digits=18, decimal_places=2,
                                          default=0)
    # WHAT THE CHOOSER ACTUALLY SPENT. `new_risk_chosen` is the raw sum of
    # risk-at-stop over the entries taken; the budget is spent in MARGINAL
    # risk — sqrt((r+ri)'C(r+ri)) - sqrt(r'Cr) per pick — and the two are
    # different quantities. Without this column /desk/ drew the raw sum
    # against a budget consumed in marginal terms and could show "30 of 78
    # spent" on a tick the chooser had stopped at the budget's own edge:
    # the page telling the operator a number the desk never used.
    #
    # NULL, not 0. A plan written before this column existed did not record
    # a marginal total, and a zero there would claim the desk spent nothing
    # — the same lie in the other direction (2026-09-12).
    new_risk_marginal = models.DecimalField(max_digits=18, decimal_places=2,
                                            null=True, blank=True)

    n_candidates = models.IntegerField(default=0)
    n_chosen = models.IntegerField(default=0)
    n_displaced = models.IntegerField(default=0)
    n_resized = models.IntegerField(default=0)
    # Not in the first sketch of this table, and the page cannot be written
    # without it: a duplicate is neither a displacement (nothing refused it)
    # nor a choice (it did not trade), and collapsing it into either makes
    # the ladder's counts disagree with its rows.
    n_duplicate = models.IntegerField(default=0)
    n_not_desked = models.IntegerField(default=0)

    # How much of the correlation matrix was real. `matrix_pairs_total` is
    # the number of pairs the plan NEEDED; the difference is how much of the
    # diversification penalty was assumed away at rho = 0, which is the
    # honest caveat on every marginal risk on the plan.
    matrix_pairs_measured = models.IntegerField(default=0)
    matrix_pairs_total = models.IntegerField(default=0)

    # Non-empty when the desk itself failed. The fleet then ran UNDESKED
    # (every candidate executed at its own size) — the desk fails open,
    # because a ranking agent that goes down must not stop the bots.
    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # The grade (Stage 3): edge_r is the desk's set minus the default set, in
    # R. Positive means the ranking earned its keep on this plan.
    graded_at = models.DateTimeField(null=True, blank=True)
    edge_r = models.FloatField(null=True, blank=True)
    edge_detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "venue", "-created_at"]),
            models.Index(fields=["graded_at"]),
        ]

    def __str__(self):
        return (f"<DeskPlan #{self.pk} u{self.user_id} {self.venue} "
                f"{self.mode} {self.n_chosen}/{self.n_candidates}>")


class DeskDecision(models.Model):
    """What the desk decided about ONE candidate, and what came of it.

    `risk_dollars_default` is the risk the BOT had already cleared through
    every ceiling — the candidate at size 1.0. `marginal_risk` is what adding
    it to the chosen set plus the open book would cost at the portfolio
    level, which is the number the budget is spent in: two 40-dollar bets
    that correlate 0.9 cost nearly 80, two that correlate 0.0 cost 57.

    `rank` is the position in the greedy order the plan actually used, not a
    sort of `rank_key`: the desk picks by expected R PER UNIT of marginal
    risk, so the best candidate in R can be ranked below a slightly weaker
    one that diversifies. The ladder on /desk/ reads this column, so what the
    operator sees is the order the money was offered in.
    """

    LANE_CHOICES = [
        ("config_live", "This config, live"),
        ("user_live", "This user's fleet, live"),
        ("fleet_live", "All users' fleet, live"),
        ("fleet_paper", "Fleet paper (haircut)"),
        ("signal", "Signal lane (haircut)"),
        ("unmeasured", "Unmeasured — conviction x net RR"),
    ]

    OUTCOME_CHOSEN = "chosen"
    OUTCOME_RESIZED = "resized"
    OUTCOME_DISPLACED = "displaced"
    OUTCOME_DUPLICATE = "duplicate"
    OUTCOME_NOT_DESKED = "not_desked"
    # 19 characters. The column is 20 wide rather than the 16 first
    # sketched, because Postgres enforces max_length and a silently
    # truncated outcome would read as a different decision.
    OUTCOME_REFUSED_AFTER = "chosen_then_refused"
    OUTCOME_CHOICES = [
        (OUTCOME_CHOSEN, "Chosen at full size"),
        (OUTCOME_RESIZED, "Chosen, resized down"),
        (OUTCOME_DISPLACED, "Displaced"),
        (OUTCOME_DUPLICATE, "Duplicate of a better expression"),
        (OUTCOME_NOT_DESKED, "Not desked (the lane trades whole)"),
        (OUTCOME_REFUSED_AFTER, "Chosen, then refused at execution"),
    ]

    plan = models.ForeignKey(DeskPlan, on_delete=models.CASCADE,
                             related_name="decisions")
    config = models.ForeignKey("bot_program.AssetBotConfig",
                               on_delete=models.CASCADE,
                               related_name="desk_decisions")
    symbol = models.CharField(max_length=40)
    direction = models.CharField(max_length=4)
    rule_name = models.CharField(max_length=100, blank=True, default="")

    # The evidence the ranking key came from.
    lane = models.CharField(max_length=12, choices=LANE_CHOICES,
                            default="unmeasured")
    n = models.IntegerField(default=0)
    # NULL means UNMEASURED and that is not zero: a rule with three graded
    # fills has no expected R, and the page renders an em dash for it rather
    # than a 0.00 the operator would read as "measured, and flat".
    e_r = models.FloatField(null=True, blank=True)
    p_win = models.FloatField(null=True, blank=True)
    rank_key = models.FloatField(default=0.0)
    measured = models.BooleanField(default=False)
    decaying = models.BooleanField(default=False)

    risk_dollars_default = models.DecimalField(max_digits=18, decimal_places=2,
                                               default=0)
    marginal_risk = models.DecimalField(max_digits=18, decimal_places=2,
                                        default=0)
    corr_max = models.FloatField(null=True, blank=True)
    rank = models.IntegerField(default=0)

    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES)
    reason = models.CharField(max_length=120, blank=True, default="")
    size_mult = models.FloatField(default=1.0)

    # The counterfactual's five fields. A displaced decision is graded by
    # walking the bars from `created_at` over `horizon_hours` against these
    # levels, so they are stored even when nothing was sent.
    qty_default = models.DecimalField(max_digits=18, decimal_places=8,
                                      default=0)
    qty_final = models.DecimalField(max_digits=18, decimal_places=8,
                                    null=True, blank=True)
    price = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    stop = models.DecimalField(max_digits=18, decimal_places=8,
                               null=True, blank=True)
    target = models.DecimalField(max_digits=18, decimal_places=8,
                                 null=True, blank=True)
    horizon_hours = models.FloatField(default=168.0)

    trade = models.ForeignKey("bot_program.AssetBotTrade",
                              on_delete=models.SET_NULL,
                              null=True, blank=True,
                              related_name="desk_decisions")

    counterfactual_r = models.FloatField(null=True, blank=True)
    counterfactual_outcome = models.CharField(max_length=16, blank=True,
                                              default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rank", "id"]
        indexes = [
            models.Index(fields=["plan"]),
            models.Index(fields=["config", "symbol", "created_at"]),
            models.Index(fields=["outcome", "resolved_at"]),
        ]

    def __str__(self):
        return (f"<DeskDecision #{self.pk} {self.symbol} {self.direction} "
                f"{self.outcome} x{self.size_mult:.2f}>")
