"""The Orcs' tables (spec §10.1, §10.7), imported from bot_program/models.py
like aragorn_models, so the app label is bot_program.

O1 ships the tables its own commits write: the seat, the Orc, its legs,
its journal, its tracks and grade, the setting, and the three tables of
the dossier and the drums (O1c). OrcWake ships as a table only; O1c writes
it. The tables only O2 writes (OrcIntent, OrcActionGrade, Captain,
CaptainOrder and the 2026-10-09 additions marked O2) ship in O2's own
migration (§10.7).

No `choices=` on any status or kind column: the allowed values are tuples
in bot_program/orcs/constants.py, so a later PR adds one without a
migration.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class OrcSeat(models.Model):
    """The authority a (venue, class, rule key) has earned (§10.1). Every
    seat is born at L0: shadow, no power."""
    venue = models.CharField(max_length=8)                 # paper | demo | live
    asset_class = models.CharField(max_length=12)
    rule_key = models.CharField(max_length=100, default="*")
    level = models.PositiveSmallIntegerField(default=0)    # 0..4
    status = models.CharField(max_length=12, default="active")
    pinned = models.BooleanField(default=False)
    reason = models.CharField(max_length=300, blank=True)
    model_routine = models.CharField(max_length=50, blank=True)
    model_decisive = models.CharField(max_length=50, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    changed_by = models.CharField(max_length=40, blank=True)
    changed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("venue", "asset_class", "rule_key")]

    def __str__(self):
        return f"{self.venue}/{self.asset_class}/{self.rule_key}: L{self.level}"


class Orc(models.Model):
    """One per IDEA: a root position, every leg the Orc adds, and at most
    one re-entry (§1.1). Displayed as "Orc #<root trade id>"."""
    seat = models.ForeignKey(OrcSeat, on_delete=models.PROTECT,
                             related_name="orcs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE, related_name="orcs")
    config = models.ForeignKey("bot_program.AssetBotConfig",
                               on_delete=models.CASCADE, related_name="orcs")
    root_trade = models.OneToOneField("bot_program.AssetBotTrade",
                                      on_delete=models.CASCADE,
                                      related_name="orc")
    # frozen at birth
    symbol = models.CharField(max_length=40)
    side = models.CharField(max_length=4)
    asset_class = models.CharField(max_length=12)
    paper = models.BooleanField(default=True)
    manual = models.BooleanField(default=False)

    state = models.CharField(max_length=16, default="born", db_index=True)
    commission = models.CharField(max_length=10, default="advise")
    stood_down = models.BooleanField(default=False)
    hand_hold_until = models.DateTimeField(null=True, blank=True)
    captain_may_cut = models.BooleanField(default=False)
    last_step_tick = models.CharField(max_length=40, blank=True)
    hand_touched = models.BooleanField(default=False)
    killed = models.BooleanField(default=False)
    #: the money 1R stood for at birth; NULL means no R, L0 for life
    r_money = models.DecimalField(max_digits=14, decimal_places=4,
                                  null=True, blank=True)
    ccy = models.CharField(max_length=10, blank=True)
    adds_used = models.SmallIntegerField(default=0)
    reentries_used = models.SmallIntegerField(default=0)
    attempt = models.SmallIntegerField(default=1)
    reverse_of = models.ForeignKey("self", null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="reversals")
    adopted = models.BooleanField(default=False)
    thesis = models.JSONField(default=dict, blank=True)
    plan = models.JSONField(default=dict, blank=True)
    plan_version = models.IntegerField(default=0)
    plan_changes_24h = models.JSONField(default=list, blank=True)
    stop_level = models.DecimalField(max_digits=18, decimal_places=8,
                                     null=True, blank=True)
    stop_why = models.CharField(max_length=200, blank=True)
    stop_at = models.DateTimeField(null=True, blank=True)
    trail_owner = models.BooleanField(default=False)
    lock_waiver = models.JSONField(default=dict, blank=True)
    be_swap_floor = models.DecimalField(max_digits=18, decimal_places=8,
                                        null=True, blank=True)
    watches = models.JSONField(default=list, blank=True)
    #: the observer's memory: what the journal last said about the row
    seen = models.JSONField(default=dict, blank=True)
    latest_note = models.CharField(max_length=140, blank=True)
    latest_note_at = models.DateTimeField(null=True, blank=True)
    last_wake_at = models.DateTimeField(null=True, blank=True)
    last_good_wake_at = models.DateTimeField(null=True, blank=True)
    next_wake_due = models.DateTimeField(null=True, blank=True)
    last_facts_hash = models.CharField(max_length=64, blank=True)
    llm_wakes_today = models.SmallIntegerField(default=0)
    routine_wakes_today = models.SmallIntegerField(default=0)
    spend_today_usd = models.DecimalField(max_digits=10, decimal_places=6,
                                          default=0)
    routine_spend_today_usd = models.DecimalField(max_digits=10,
                                                  decimal_places=6,
                                                  default=0)
    care_owned_reason = models.CharField(max_length=200, blank=True)
    care_owned_at = models.DateTimeField(null=True, blank=True)
    born_at = models.DateTimeField(auto_now_add=True)
    died_at = models.DateTimeField(null=True, blank=True)
    # §10.7, written from O1
    army_type = models.CharField(max_length=16, blank=True)
    army_why = models.JSONField(default=dict, blank=True)
    #: the Horde's denormalised read (§9.5): the last journal entries,
    #: refreshed at every append (bot_program/orcs/notes.py)
    card = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["state", "asset_class"],
                         name="orc_state_class"),
            models.Index(fields=["user", "state"], name="orc_user_state"),
            models.Index(fields=["next_wake_due"], name="orc_next_wake"),
        ]

    def __str__(self):
        return f"Orc #{self.root_trade_id} {self.symbol} {self.state}"

    @property
    def label(self) -> str:
        return f"Orc #{self.root_trade_id}"


class OrcLeg(models.Model):
    """One trade row of an idea: the root, an add or the re-entry. A row
    belongs to one idea at most (§10.1)."""
    orc = models.ForeignKey(Orc, on_delete=models.CASCADE,
                            related_name="legs")
    trade = models.OneToOneField("bot_program.AssetBotTrade",
                                 on_delete=models.CASCADE,
                                 related_name="orc_leg")
    kind = models.CharField(max_length=12)                 # root|add|reentry
    seq = models.SmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("orc", "seq")]

    def __str__(self):
        return f"{self.orc_id}:{self.seq} {self.kind} #{self.trade_id}"


class OrcWake(models.Model):
    """A request to think (§1.3). O1 ships the table; O1c writes the
    detected wakes with their complexity score and dossier hashes."""
    orc = models.ForeignKey(Orc, on_delete=models.CASCADE,
                            related_name="wakes")
    created_at = models.DateTimeField(auto_now_add=True)
    reasons = models.JSONField(default=list, blank=True)
    dedupe_key = models.CharField(max_length=120)
    priority = models.FloatField(default=0)
    kind = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=12, default="pending")
    model = models.CharField(max_length=50, blank=True)
    est_usd = models.DecimalField(max_digits=10, decimal_places=6,
                                  default=0)
    skipped_reason = models.CharField(max_length=200, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # §10.7, written from O1 (the score and the hashes)
    score = models.FloatField(null=True, blank=True)
    components = models.JSONField(default=dict, blank=True)
    band = models.CharField(max_length=12, blank=True)
    day_class = models.CharField(max_length=12, blank=True)
    block_hashes = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dedupe_key"],
                                    condition=Q(status="pending"),
                                    name="orcwake_one_pending_per_key"),
        ]
        indexes = [models.Index(fields=["orc", "-created_at"],
                                name="orcwake_orc_created")]


class OrcJournal(models.Model):
    """The append-only memory (§1.4). Facts carry an id (F41) the model
    may cite; nothing updates a row once written."""
    orc = models.ForeignKey(Orc, on_delete=models.CASCADE,
                            related_name="journal")
    at = models.DateTimeField(default=timezone.now, db_index=True)
    kind = models.CharField(max_length=16)
    author = models.CharField(max_length=12, default="code")
    fact_id = models.CharField(max_length=8, blank=True)
    headline = models.CharField(max_length=200)
    body = models.JSONField(default=dict, blank=True)
    snapshot = models.JSONField(null=True, blank=True)
    facts_hash = models.CharField(max_length=64, blank=True)
    wake = models.ForeignKey(OrcWake, null=True, blank=True,
                             on_delete=models.SET_NULL,
                             related_name="entries")
    model = models.CharField(max_length=50, blank=True)
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cache_read = models.IntegerField(default=0)
    cache_write = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6,
                                   default=0)
    #: the dossier blocks this entry was written against (§5.2a)
    block_hashes = models.JSONField(default=list, blank=True)

    class Meta:
        indexes = [models.Index(fields=["orc", "-at"],
                                name="orcjournal_orc_at")]

    def __str__(self):
        return f"{self.orc_id} {self.kind} {self.fact_id} {self.headline[:60]}"


class OrcTrack(models.Model):
    """One arm of the grade (§6.1): the care ghost on its OWN state (§3.3),
    the playbook, the shadow track, the multi-ghost policies."""
    orc = models.ForeignKey(Orc, on_delete=models.CASCADE,
                            related_name="tracks")
    arm = models.CharField(max_length=16)
    state = models.JSONField(default=dict, blank=True)
    open = models.BooleanField(default=True)
    last_bar_at = models.DateTimeField(null=True, blank=True)
    exit_price = models.DecimalField(max_digits=18, decimal_places=8,
                                     null=True, blank=True)
    exit_at = models.DateTimeField(null=True, blank=True)
    exit_why = models.CharField(max_length=200, blank=True)
    exit_r = models.FloatField(null=True, blank=True)
    mfe_r = models.FloatField(null=True, blank=True)
    tail_capped = models.BooleanField(default=False)

    class Meta:
        unique_together = [("orc", "arm")]


class OrcGrade(models.Model):
    """One per dead idea (§6.3), written by O1b's grading. Venues and bar
    sources are never pooled."""
    orc = models.OneToOneField(Orc, on_delete=models.CASCADE,
                               related_name="grade")
    r_money = models.DecimalField(max_digits=14, decimal_places=4,
                                  null=True, blank=True)
    ai_cost_usd = models.DecimalField(max_digits=10, decimal_places=6,
                                      default=0)
    orc_r = models.FloatField(null=True, blank=True)
    orc_r_gross = models.FloatField(null=True, blank=True)
    ghost_r = models.FloatField(null=True, blank=True)
    play_r = models.FloatField(null=True, blank=True)
    actual_r = models.FloatField(null=True, blank=True)
    r_avail = models.FloatField(null=True, blank=True)
    capture_orc = models.FloatField(null=True, blank=True)
    capture_ghost = models.FloatField(null=True, blank=True)
    capture_play = models.FloatField(null=True, blank=True)
    delta_care = models.FloatField(null=True, blank=True)
    delta_play = models.FloatField(null=True, blank=True)
    net_edge_money = models.DecimalField(max_digits=14, decimal_places=4,
                                         null=True, blank=True)
    level_at_birth = models.SmallIntegerField(default=0)
    venue = models.CharField(max_length=8, blank=True)
    counts_for_seat = models.BooleanField(default=False)
    bar_source = models.CharField(max_length=12, blank=True)
    hand_touched = models.BooleanField(default=False)
    seat_block = models.IntegerField(null=True, blank=True)
    exit_label = models.CharField(max_length=80, blank=True)
    policy_r = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    expectation_hit_rate = models.FloatField(null=True, blank=True)
    flipflop_rate = models.FloatField(null=True, blank=True)
    n_wakes = models.IntegerField(default=0)
    n_llm = models.IntegerField(default=0)
    n_actions = models.IntegerField(default=0)
    n_refused = models.IntegerField(default=0)
    # §10.7, written from O1 (the council-of-war classifier on the arms)
    fell = models.CharField(max_length=12, blank=True)
    sub_label = models.CharField(max_length=24, blank=True)
    army_type = models.CharField(max_length=16, blank=True)
    first_divergence = models.CharField(max_length=8, blank=True)
    graded_at = models.DateTimeField(default=timezone.now, db_index=True)


class OrcSetting(models.Model):
    """Small operator settings (§10.1), the AragornSetting pattern:
    max_paper_orcs from O1, the drum map from O1c, the budget keys from
    O2."""
    key = models.CharField(max_length=64, unique=True)
    value = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=40, blank=True)

    def __str__(self):
        return f"{self.key}={self.value}"

    @classmethod
    def get(cls, key, default=None):
        """The stored value, or `default` when the key has no row or the
        table cannot be read."""
        try:
            row = cls.objects.filter(key=key).only("value").first()
        except Exception:  # noqa: BLE001 — an unread setting is its default
            return default
        return default if row is None else row.value


class OrcDossierBlock(models.Model):
    """A content-addressed block of the dossier (§5.2a), written by O1c:
    each journal entry and wake stores the hash list, so a replay costs
    one copy per block."""
    hash = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=16)
    body = models.JSONField(default=dict, blank=True)
    text = models.TextField(blank=True)
    tokens_est = models.IntegerField(default=0)
    built_at = models.DateTimeField(default=timezone.now, db_index=True)
    #: MK is sized per model at build time (§5.2a, D21): the model's
    #: family (bot_program/orcs/dossier.family_of), never its id
    model = models.CharField(max_length=50, blank=True)
    #: the builder's natural key (O1c: "2026-10-22|london|<model>"), so a
    #: built block is found without its text and never built twice
    key = models.CharField(max_length=160, blank=True, db_index=True)


class OrcDayBaseline(models.Model):
    """The day's weather per (user, class) (§7.5.3), written by O1c."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE,
                             related_name="orc_day_baselines")
    asset_class = models.CharField(max_length=12)
    trading_day = models.DateField()
    day_class = models.CharField(max_length=12, blank=True)
    score = models.FloatField(null=True, blank=True)
    components = models.JSONField(default=dict, blank=True)
    caps = models.JSONField(default=dict, blank=True)
    frontier_quota = models.SmallIntegerField(default=0)
    routing_version = models.CharField(max_length=20, blank=True)
    computed_at = models.DateTimeField(auto_now=True)
    history = models.JSONField(default=list, blank=True)

    class Meta:
        unique_together = [("user", "asset_class", "trading_day")]


class OrcDrum(models.Model):
    """A war drum (§4.7), written by O1c as a journal fact only: prices and
    ATR in the payload, never another idea's R, money or note."""
    wave_id = models.CharField(max_length=40, db_index=True)
    origin = models.CharField(max_length=40)
    orc = models.ForeignKey(Orc, null=True, blank=True,
                            on_delete=models.SET_NULL,
                            related_name="drums")
    hop = models.SmallIntegerField(default=0)
    kind = models.CharField(max_length=16)
    symbol = models.CharField(max_length=40)
    asset_class = models.CharField(max_length=12, blank=True)
    legs = models.JSONField(default=list, blank=True)
    direction = models.SmallIntegerField(default=0)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    fact_id = models.CharField(max_length=8, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    #: who the routing reached (O1 measures the reach before any wake)
    reach = models.JSONField(default=list, blank=True)
    #: O1c: a drum routes within ONE user's book (a stop level or a
    #: holding is private); null for a drum no user's book owns
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                             blank=True, on_delete=models.CASCADE,
                             related_name="orc_drums")
    #: when the census routed it (null: not yet)
    routed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["symbol", "-at"],
                                name="orcdrum_symbol_at")]
