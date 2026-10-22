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

# ── O1b: ghosted and graded (spec §3.3, §5.2, §5.4, §6.1-6.4, §6.10) ──────

#: The levels the menu offers (§2.2 I11): a stop needs this much room, in
#: ATR of its timeframe, on both the tick price and the closing-side mark,
#: and sits no farther than this many ATR(4h) from the mark.
MIN_STOP_ROOM_ATR = 0.5
MAX_LEVEL_DIST_ATR4H = 3.0
#: The menu's timeframes; 1d joins only while its venue bars are fresh.
MENU_TFS = ("1h", "4h")
MENU_DAILY_TF = "1d"

#: The gap model (§3.6): fewer measured samples than this is unmeasured,
#: and an unmeasured gap refuses a waiver (Corsairs ask 12). The class
#: that never shuts reads the p90 of the 1h range over this many days.
GAP_RANGE_DAYS = 30
#: How far back the gap model reads a print title's history.
GAP_LOOKBACK_DAYS = 400
#: The most 1h bars one gap measurement reads: the whole lookback of a
#: class that never shuts, and a day to spare. The window's NEWEST bars.
GAP_MAX_BARS = 24 * GAP_LOOKBACK_DAYS + 48

#: The grade (§6.3): capture only on an idea that offered half an R; the
#: display caps a pyramid's capture.
CAPTURE_MIN_AVAIL_R = 0.5
CAPTURE_DISPLAY_MAX = 2.0
#: aragorn.PROMOTE_Z (aragorn.py:83), copied: the 80% bounds of a block.
PROMOTE_Z = 1.2816
SEAT_WINDOW = 20
#: The council of war's labels (§6.10): "costly" past this, a label only.
HONOUR_TOLERANCE_R = 0.05
TRIPWIRE_IDEA_R = -1.2
#: A block fault needs at least this many ideas in its group (the spec is
#: silent; a builder's choice, documented as such).
BLOCK_FAULT_MIN_N = 5

#: The tail (§6.1): a bot idea's arms run to the later of the root's close
#: and its birth plus this many times the class's no-progress hours; a
#: manual idea's to the root's close plus GRADE_MAX_WAIT_DAYS
#: (position_review_agent.py:69).
TAIL_CAP_NO_PROGRESS_X = 1.5
TAIL_CAP_MANUAL_DAYS = 30

#: The arms (§6.1). `orc_shadow` is the O arm; the multi-ghost policies
#: run simulate.EXIT_POLICIES on 4h venue bars.
ARM_CARE, ARM_PLAYBOOK, ARM_ORC = "care", "playbook", "orc_shadow"
MULTI_GHOST_POLICIES = ("chandelier3", "staged")
MULTI_GHOST_TF = "4h"
GHOST_ARMS = (ARM_CARE, ARM_PLAYBOOK, ARM_ORC) + MULTI_GHOST_POLICIES
#: The tail's bars for the care-like arms.
TAIL_TF = "1h"

#: The playbook (§5.4). O1's arm runs no Orc power (O3 adds trail
#: ownership and lock waivers), so its version names that.
PLAYBOOK_VERSION = "o1"
#: T-STRUCT trails on 1h swings below +2R MFE, on 4h swings from there.
TSTRUCT_SWITCH_R = 2.0
#: K-DRAW: the mark within this many ATR(4h) of the draw.
KDRAW_ATR4H = 0.5
KDRAW_FRACTION = 0.5
#: P-LOCK / P-TRIM / P-HOLD are listed within this many hours of a
#: high-impact print (entry_timing.EVENT_ATTACK_HOURS).
PRINT_WITHIN_H = 3.0

#: The basis fallback (§5.2, D2): platform levels are shifted by the mark
#: less the last 1h platform close; structure levels are kept only while
#: the last BASIS_SAMPLES hourly samples sit within this many ATR(1h).
BASIS_SAMPLES = 10
BASIS_UNSTABLE_ATR1H = 0.25

#: A frame is fresh while its newest bar ended within this many bar
#: lengths of OPEN market time.
FRESH_BAR_LENGTHS = 2
#: A bar that ended is FINAL once the bar refresh has passed over it: the
#: refresh stores the forming candle and rewrites it on its next pass,
#: BAR_REFRESH_S later (config/celery.py "refresh-bot-bars"). Final: its
#: successor is stored (the pass that wrote it rewrote this one too), or
#: BAR_REFRESH_S plus BAR_FINAL_MARGIN_S have gone by since its end.
BAR_REFRESH_S = 600
BAR_FINAL_MARGIN_S = 120
#: The Olog-hai and the stock/ETF decision bar is 1d once this many fresh
#: 1d venue bars exist (§1.6); 4h until then. The venue's 1d is its own 4h
#: bars by UTC day (orcs/bars.py): no 1d candle is asked.
DAILY_DECISION_MIN_BARS = 60
#: Market hours without a ghost step that flag the idea "ticks missed".
UNMANAGED_TICK_GAP_MIN = 30
#: The O arm's stop path keeps at most this many points.
STOP_PATH_MAX = 200
#: The thesis check's verdict counts for X-THESIS this long
#: (thesis_check.THESIS_STOP_TTL_HOURS).
THESIS_FRESH_H = 24
#: The predicates' states (§1.4).
PRED_MET, PRED_UNMET, PRED_UNCHECKED = "met", "unmet", "unchecked"
#: The grade's verdicts (§6.10) and the first divergence (§6.3).
FELL_WON, FELL_HONOURABLE, FELL_FAULT = "won", "honourable", "fault"
DIVERGE_HOLD, DIVERGE_REDUCE, DIVERGE_ADD = "hold", "reduce", "add"
#: How a track was seeded: at birth, at adoption, or late by the census
#: (an Orc born before its arms existed; it never counts for a seat).
SEED_BIRTH, SEED_ADOPT, SEED_LATE = "birth", "adopt", "late"
