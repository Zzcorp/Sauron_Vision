"""The Orcs' constants (spec §10.6, §10.7). Allowed values of the status
and kind columns live here as tuples, never as model `choices`, so a later
PR adds a value without a migration. Later PRs append their own sections.
"""

# ── O1a: lifecycle, journal, census ──────────────────────────────────────

#: Orc.state (§1.2). O1 writes born and dead only; active, care_owned and
#: reentry_window arrive with the wakes (O2) and the re-entry (O5).
STATE_BORN = "born"
STATE_ACTIVE = "active"
STATE_CARE_OWNED = "care_owned"
STATE_REENTRY = "reentry_window"
STATE_DEAD = "dead"
ORC_STATES = (STATE_BORN, STATE_ACTIVE, STATE_CARE_OWNED, STATE_REENTRY,
              STATE_DEAD)

#: OrcLeg.kind (§10.1).
LEG_ROOT, LEG_ADD, LEG_REENTRY = "root", "add", "reentry"
LEG_KINDS = (LEG_ROOT, LEG_ADD, LEG_REENTRY)

#: OrcJournal.kind (§1.4), with the 2026-10-09 additions.
JOURNAL_KINDS = (
    "birth", "adopt", "fact", "wake", "reading", "decision", "plan",
    "intent", "refusal", "action", "takeover", "return", "captain",
    "question", "answer", "postmortem", "grade", "budget", "error",
    "drum", "breach", "temperament", "rank", "heritage", "scar", "emperor",
)
#: OrcJournal.author (§1.4).
AUTHORS = ("code", "orc", "care", "captain", "operator", "morgul",
           "reconcile")

#: Orc.commission (§3.2): an operator's ticket starts at advise; a bot
#: idea follows its class seat.
COMMISSION_ADVISE = "advise"
COMMISSION_CLASS = "class"
COMMISSIONS = (COMMISSION_ADVISE, "reduce", "trail", COMMISSION_CLASS)

#: OrcSeat (§10.1, §10.4): one per (venue, class, rule key). Every seat is
#: born at L0, shadow. The venue is the row's MONEY WORLD in the platform's
#: own words (dashboard.position_summary.world_of): an eToro demo row
#: (paper=False, broker_env "paper") sits on a "demo" seat, never on the
#: real-money one, so demo evidence is never pooled with real money.
SEAT_STATUSES = ("active", "suspended", "revoked")
VENUE_PAPER, VENUE_DEMO, VENUE_LIVE = "paper", "demo", "live"
VENUES = (VENUE_PAPER, VENUE_DEMO, VENUE_LIVE)
RULE_KEY_ANY = "*"
RULE_KEY_MANUAL = "manual_take"

#: A trade row's status that ends a leg (§1.2).
LEG_DONE_STATUSES = ("CLOSED", "CANCELED")

#: At most this many Orcs outside real money (paper and eToro demo) alive
#: at once (§10.6); OrcSetting "max_paper_orcs" overrides it. Real-money
#: rows are never capped.
MAX_PAPER_ORCS = 10
MAX_REENTRIES = 1
REENTRY_WINDOW_MARKET_H = 24
#: The census holds its cache lock this long (its beat is 300 s).
CENSUS_LOCK_TTL_S = 240
#: A stop level moving inside one quarter R writes no new fact (§1.4: a
#: trail grind is one fact per quarter R, not one per tick).
CARE_FACT_STEP_R = 0.25

#: The reviewer's verdicts that are a read worth a fact (a model answer);
#: "none" and "no_quote" are the deterministic layer's rows.
REVIEW_FACT_VERDICTS = ("hold", "tighten", "take_part", "exit")

# ── §2 the mandate numbers a type may only tighten (§1.6) ────────────────
MAX_ADDS = 2
RISK_SHARES = (0.5, 1.0)
ADD_PRE_SHUT_H = 6
EVENT_WAIVER_FLOOR_R = -0.5
GAP_MIN_SAMPLES = 8

# ── §1.6 the army types: assignment thresholds ───────────────────────────
#: A hand ticket is a quick strike when its stop sits within this many
#: ATR(1h) and the instrument's spread within MERC_SPREAD_MAX_ATR1H.
MERC_STOP_MAX_ATR1H = 1.2
MERC_SPREAD_MAX_ATR1H = 0.1
#: A hand ticket whose stop is 1-3 x ATR(4h) is a daily position (Line).
LINE_STOP_ATR4H = (1.0, 3.0)
#: A hand ticket with a stop of 2 x ATR(1d) or more is a siege (Olog-hai).
OLOG_STOP_MIN_ATR1D = 2.0
#: An operator's thesis horizon of two weeks or more is a siege too.
OLOG_HORIZON_H = 336
#: The expected hold when no persona says one (§1.6, the Corsair overlay).
DEFAULT_HOLD_H = 72.0
#: The Corsair overlay: two high-impact prints inside the hold, or a
#: measured gap p90 of half an R.
CORSAIR_MIN_PRINTS = 2
CORSAIR_GAP_P90_R = 0.5
#: Bars read for the ATRs the assignment measures, and the ATR period.
ATR_BARS = 60
ATR_PERIOD = 14
#: Uruk-hai: the elite exception's evidence bar (portfolio/risk_gate.py:
#: 243-245, ELITE_MIN_N, ELITE_MIN_WIN_RATE, ELITE_MIN_AVG_R; copied so
#: army.py stays pure, pinned equal by tests/orcs/test_orc_army.py), the
#: lineage at Warg-rider (L2) or above, and the operator's PIN privilege.
URUK_MIN_N = 20
URUK_MIN_WIN_RATE = 0.55
URUK_MIN_AVG_R = 0.20
URUK_MIN_LEVEL = 2
URUK_PRIVILEGE = "uruk_hai"

# §1.6 the types (tighter than §2)
#: Line adds at half size; 1.0 is the Uruk-hai's PIN-granted privilege.
LINE_RISK_SHARE_MAX = 0.5
CORSAIR_EVENT_WAIVER_FLOOR_R = -0.3
CORSAIR_GAP_MIN_SAMPLES = 12
CORSAIR_ADD_PRE_SHUT_H = 12
