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

# ── O1c: the dossier from code, the score, the weather, the drums ─────────
# (spec §5.2a, §7.5.1-7.5.3, §4.7, §10.6, §10.7). Nothing here routes,
# calls a model or sends anything: O1 records.

#: §10.7 verbatim.
DOSSIER_MAX_TOKENS = 22000
BOARD_SYMBOLS = ("DXY", "US10Y", "XAUUSD", "WTIUSD", "SPX500", "NSDQ100",
                 "DAX40", "NIKKEI225", "BTCUSD", "EURUSD", "USDJPY")
MK_HEADLINES_PER_SESSION = 6
#: MK12 shrinks 6 -> 4 -> 3 headlines per model at build time (§5.2a D21).
MK_HEADLINE_STEPS = (6, 4, 3)
IN_HEADLINES = 8
MK_SESSION_MAX_TOKENS = 900
FENCE_CAPS = {"headline": 120, "calendar_title": 80, "mind": 300,
              "reviewer": 280, "lesson": 200, "note": 140}
#: V10 (§5.2a item 5, revised 2026-10-15): the T0 fact kinds that may
#: justify each action kind. `symbol`: the fact must be on this symbol;
#: `event`: a gap or calendar fact of the named event; `newer`: any fact
#: newer than the current plan. The I3 facts of an add arrive with the
#: mandate (O2). Enforced by the validator from O2; O1 ships the table and
#: the check.
_V10_REDUCE = {"kinds": ("bar", "structure", "predicate", "care"),
               "symbol": True}
_V10_ADD = {"kinds": ("structure", "bar"), "symbol": True, "i3": True}
V10_RELEVANCE = {
    "exit": _V10_REDUCE, "trim": _V10_REDUCE, "tighten": _V10_REDUCE,
    "lock_waive": {"kinds": ("gap", "calendar"), "event": True},
    "add": _V10_ADD, "reenter": _V10_ADD,
    "plan": {"kinds": "any", "newer": True},
}
NEWS_SHOCK_CORROBORATION_ATR1H = 1.0
NEWS_SHOCK_CORROBORATION_MIN = 15
BAND_ROUTINE_MAX = 30
BAND_MATERIAL_MAX = 55
BAND_COMPLEX_MAX = 75
BAND_HYSTERESIS = 5
BAND_HOLD_AFTER_URGENT_MIN = 60
STAKES_REAL = 10
STAKES_HAND = 5
STAKES_WOUND = 10
STAKES_L3 = 5
DRUM_MAX_HOP = 2
DRUM_JOIN_MIN = 15
DRUM_SETTLE_MIN = 15
DRUM_RHO_MIN = 0.7
MIN_WAKE_SPACING_MIN = 15
MARK_MAX_AGE_S = 120

#: §7.5.1: the weights (summing to 1.00) and the breakpoints x -> s.
COMPLEXITY_WEIGHTS = {"vol": 0.12, "regime": 0.10, "prints": 0.12,
                      "news": 0.06, "stress": 0.10, "gap": 0.08,
                      "stop": 0.10, "decision_point": 0.06, "size": 0.08,
                      "disagreement": 0.08, "reversibility": 0.10}
COMPLEXITY_BREAKPOINTS = {
    "vol": ((1.0, 0), (1.25, 40), (1.6, 75), (2.2, 100)),
    "news": ((1.0, 0), (2.0, 50), (4.0, 100)),
    "gap": ((0.0, 0), (0.2, 20), (0.5, 60), (1.0, 100)),
    "stop": ((0.5, 100), (1.0, 60), (2.0, 20), (3.0, 0)),
    "size": ((0.05, 0), (0.15, 40), (0.30, 80), (0.50, 100)),
    "disagreement": ((0.2, 0), (0.5, 60), (0.8, 100)),
}
#: §7.5.1 reversibility: the most irreversible candidate on the table.
REVERSIBILITY = {"R0": 0, "R1": 25, "R2": 40, "R3": 55, "R4": 75, "R5": 90,
                 "R6": 100}

#: MK is sized per model when it is built (§5.2a D21). What differs between
#: the models at build time is the tokenizer, so the dossier names a model
#: by its FAMILY (the word after "claude-" in its id: bot_program/orcs/
#: dossier.family_of), never by its id: a model id lives in
#: ai_agents/catalog.py alone (tests/test_model_catalog.py) and the orcs
#: package imports nothing of ai_agents. These are the families of the
#: Orcs' ladder, table v1 (catalog ORC_LADDER_V1; every ladder model maps
#: to one, pinned by tests/orcs/test_orc_dossier.py). A model of no known
#: family is sized as MK_GUARD_FAMILY, the largest factor.
MK_FAMILIES = ("haiku", "sonnet", "opus", "fable")
MK_GUARD_FAMILY = "fable"
#: Tokens per estimated token, per family. MEASURED 2026-10-16 (spec §5.2a):
#: count_tokens gave the same counts on Opus 5.5 and Haiku 5.5 as on
#: Sonnet 5.5; Fable 5.1 is unmeasured and keeps the 1.35x guard. O1 has
#: no network, so it estimates (4 characters a prose token, 8.5 tokens a
#: bar row) times this factor. OrcSetting "token_factors" overrides it, by
#: family or by the model's full name.
TOKEN_FACTORS = {"haiku": 1.0, "sonnet": 1.0, "opus": 1.0, "fable": 1.35}
#: The family an O1 wake's dossier is rendered for (no model is asked).
DOSSIER_REFERENCE_MODEL = "sonnet"
CHARS_PER_TOKEN = 4.0
TOKENS_PER_BAR_ROW = 8.5
#: S (the doctrine) as measured by the 2026-10-16 smoke: reserved in the cap.
S_TOKENS_RESERVE = 3930
#: The per-wake trim (§5.2a D21): uncached parts only, in this order. The
#: last, IN1's 1h rows beyond 3 days, is decided per (model, symbol) when
#: IN-slow is built, so the Orcs on one symbol still share IN-slow.
TRIM_ORDER = ("in12_5m", "in12_15m_old", "ps5_notes", "in9", "in1_1h_old")

#: The detector's memory of the reason keys it has recorded.
WAKE_KEYS_KEPT = 200
#: W4 (§1.3): +1R, +2R, +3R; -0.5R, -0.75R (thesis_check.DEEP_MAE_R).
W4_THRESHOLDS = (1.0, 2.0, 3.0, -0.5, -0.75)
#: The give-back: ur <= this share of the best after a best of +1R.
W4_GIVEBACK_SHARE = 0.5
#: W5: minutes from a high-impact print (T-180, T-60, T+15), earnings 24h.
W5_OFFSETS_MIN = (-180, -60, 15)
W5_EARNINGS_H = 24
#: W5 at T+15 is fired at most this long after the print.
W5_LATE_MIN = 60
#: W11: the metronome every 4 hours while the market is open; a stock or
#: ETF at the open + 60 min and the close - 90 min; 2 h before a weekend.
W11_METRONOME_H = 4
W11_OPEN_AFTER_MIN = 60
W11_CLOSE_BEFORE_MIN = 90
W11_WEEKEND_BEFORE_H = 2
#: W7: open risk at this share of its limit.
W7_OPEN_RISK_SHARE = 0.8
#: W3: the mark within this many ATR(1h) of an invalidation level, once per
#: level per 4 hours.
W3_NEAR_ATR1H = 0.1
W3_ONCE_H = 4
#: PS13: the venue mark against the platform quote, a contradiction past
#: this many ATR(1h).
MARK_QUOTE_CONTRADICTION_ATR1H = 0.5

#: §4.7 the declared factor map, version 1 (OrcSetting "drum_factor_map"
#: overrides it). The USD factor reaches gold and silver (quoted in USD),
#: EURUSD and USDJPY (their legs), the US indices and the dollar index.
DRUM_FACTOR_MAP_V1 = {
    "v": 1,
    "map": {"USD": ["XAUUSD", "XAGUSD", "EURUSD", "USDJPY", "SPX500",
                    "NSDQ100", "DXY"]},
}
DRUM_KINDS = ("stop_hit", "sweep", "thesis_turned", "level_break",
              "news_shock", "print_surprise", "fill", "lock")
#: The care's lock transitions that drum (never a trail step).
DRUM_LOCK_WHYS = ("breakeven", "event lock", "weekend lock")
#: A drum's journal kind and its fact id's prefix.
DRUM_PREFIX = "DR"
#: The LiveQuote ring the census keeps for the news-shock corroboration.
RING_SAMPLES = 8
RING_TTL_S = 3600

#: OrcWake.status values O1 writes (no `pending`: dispatch is O2's).
WAKE_STATUS_SKIPPED = "skipped"
WAKE_STATUS_QUIET = "quiet"
WAKE_SKIPPED_REASON = "no model before O2"
#: The words a wake's status is shown in.
STATUS_WORDS = {"skipped": "recorded only: no model before O2",
                "quiet": "nothing new: a code reading"}
#: The routing table's version the weather is computed for (display only).
ROUTING_VERSION = "table-v1"

#: The eToro tape (§5.2a item 3, IN12): 15m and 5m candles, behind the
#: `orcs_tape` switch AND a recorded headroom measurement. The tape takes
#: at most this share of the candle rate measured clean.
TAPE_INTERVALS = ("15m", "5m")
TAPE_SHARE = 0.25
TAPE_SWITCH = "orcs_tape"
DRUMS_SWITCH = "orcs_drums"
HEADROOM_KEY = "etoro_candle_headroom"

#: The trading day rolls at 17:00 New York (§5.2a, §7.5.3).
TRADING_DAY_ROLL_NY_HOUR = 17

# ── O1d: seen (spec §9, §9.5, §10.2). Read-only surfaces, no model. ──────

#: The operator's own thesis (§1.4, §9.2 "the operator's thesis field"):
#: a journal entry of its own kind, author `operator`, never a fact (no
#: F-id: it is his text, never a T0 fact), kept beside the entry's thesis.
#: Orc.thesis itself is never rewritten.
JOURNAL_KINDS = JOURNAL_KINDS + ("thesis",)
THESIS_OPERATOR_MAX = 600
#: The idea's gross risk cap (§2.2 I2, §10.6), printed in the risk line;
#: no mandate binds in O1.
GROSS_MAX_R = 2.0
#: The Horde's contract while the switch is ON (§9.5): additive keys.
SLOT_V = 2
#: Every key that describes an Orc's act or outcome carries a mode
#: (§9.5, revised 2026-10-15). Every Orc is in shadow in O1.
MODE_BINDING, MODE_SHADOW, MODE_REFUSED = "binding", "shadow", "refused"
MODES = (MODE_BINDING, MODE_SHADOW, MODE_REFUSED)
#: A rank is provisional below this many graded ideas (§6.9, §3.7).
RANK_GATE_N = 20
#: The pages: the dead ideas listed, the journal and the wakes shown.
PAGE_DEAD_DAYS = 30
PAGE_JOURNAL_MAX = 100
PAGE_WAKES_MAX = 10
