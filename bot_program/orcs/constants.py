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
#: The authors whose lines are facts: written by code (the O2 spec N5;
#: 2026-11-05, completing O2a). A model's lines (`orc`; a Captain's and,
#: from O2c, the Emperor's) are its words and the operator's are his: the
#: surfaces never call one the last fact (notes.last_fact).
FACT_AUTHORS = ("code", "care", "reconcile", "morgul")

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
#: "orc" (O2a, A.47): an Orc's own earlier decision or refusal, re-read in
#: PS5 as a view.
FENCE_CAPS = {"headline": 120, "calendar_title": 80, "mind": 300,
              "reviewer": 280, "lesson": 200, "note": 140, "orc": 300}
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

#: OrcWake.status values O1 wrote: a rendered wake answered by code, or a
#: quiet one. O2a's full set is below (WAKE_STATUSES).
WAKE_STATUS_SKIPPED = "skipped"
WAKE_STATUS_QUIET = "quiet"
#: The reason O1's render stored on every wake it did not find quiet. It
#: stays readable: a wake that carries it reads as the code `pre_o2` (the
#: O2 spec A.4; O2a, 2026-11-05). Nothing writes it any more.
WAKE_SKIPPED_REASON = "no model before O2"
#: The words a wake's status is shown in, one sentence each (the O2 spec
#: A.4; O2a, 2026-11-05). `skipped` names its code's words
#: (notes.wake_status_t fills {code} from WAKE_CODE_WORDS).
STATUS_WORDS = {
    "recorded": "recorded: its dossier is being written",
    "quiet": "nothing new: a code reading",
    "skipped": "answered by code: {code}",
    "pending": "waiting for its model call",
    "running": "a model is reading it",
    "done": "answered in shadow",
    "refused": "the answer was refused by the validator",
    "failed": "the model call failed",
    "late": "answered after the position closed: kept, applied to nothing",
    "stale": "not answered in time: the care holds",
    "merged": "merged into a newer wake",
}
#: A late answer whose cause is not the close (the Orc ended, a gate went
#: OFF): its cause's words in place of "after the position closed".
STATUS_LATE_T = "answered too late ({code}): kept, applied to nothing"
#: The render's own words for a wake it hands on to admission with every
#: gate ON (wake._render, the O2 spec A.7): admission decides next, in its
#: own transaction, whether a model reads it or code answers it.
WAKE_RENDERED_WORDS = "its dossier is written; a model may read it next"
#: The card's rung (the O2 spec A.62): no model for a code answer, or a
#: model's rung in tier words, never its id or its cost.
RUNG_NONE = "No model (code only)"
RUNG_T = "{rung} · {tier} tier, {effort} effort"
#: The routing table's version (the O2 spec B.3): the day's weather row
#: keeps it, and from O2b (2026-11-06) every rendered wake's route
#: (OrcWake.components["route"]["version"], bot_program/orcs/router.py).
#: A later table is a new ladder with a new version.
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

# ── O2a: the minds' foundations (2026-11-05, the O2 spec §1.1, N8) ─────────

#: OrcIntent (the O2 spec §1.1.2 item 1): one row per proposal that is not
#: a hold. Its kinds; its statuses; the codes an expired one carries in
#: `rule` (A.42); its modes, two of MODES: no O2 proposal is binding.
INTENT_KINDS = ("tighten", "trim", "exit", "lock_waive", "add")
INTENT_STATUSES = ("queued", "simulated", "expired", "recorded", "refused")
INTENT_EXPIRY_CODES = ("ttl", "moved", "row_closed", "arm_closed")
INTENT_MODES = (MODE_SHADOW, MODE_REFUSED)

#: N8: how long an Orc's row lock may be waited for (journal.orc_lock),
#: in milliseconds. Each lock outside a lock budget waits at most
#: ORC_LOCK_TIMEOUT_MS. The real-money paths (the tick's Orc steps, a
#: close's journal, the kill switch, the entry's provenance) enter
#: journal.lock_budget(ORC_LOCK_MONEY_MS): their Orc locks wait that much
#: in all. A lock holder's statements stop at ORC_STATEMENT_TIMEOUT_MS.
#: PostgreSQL only: SQLite has no row lock.
ORC_LOCK_TIMEOUT_MS = 2000
ORC_LOCK_MONEY_MS = 200
ORC_STATEMENT_TIMEOUT_MS = 5000

# ── O2a: one wake read in shadow (2026-11-05, the O2 spec A.2-A.41, A.46,
# A.47, A.58). Nothing here sends anything: mind_gateway.py is the one
# module that names the provider, and every gate below reads OFF until the
# operator turns the minds on with his PIN and sets the Orcs line.

#: A.1, A.2: the minds switch, and the platform master it sits under.
MINDS_SWITCH = "orcs_minds"
PLATFORM_MASTER = "platform_master"

#: OrcWake.status, the full set (A.3; each fits max_length=12). The tick
#: (wake.record) writes `recorded`, with no reason; the render writes
#: `quiet`, or `skipped` with a code (a gate it reads OFF; render_failed);
#: only scheduler.py writes `pending`, and `recorded` again on a wake it
#: sends back to the render; the settle writes running's ends.
WAKE_STATUS_RECORDED = "recorded"
WAKE_STATUS_PENDING = "pending"
WAKE_STATUS_RUNNING = "running"
WAKE_STATUS_DONE = "done"
WAKE_STATUS_REFUSED = "refused"
WAKE_STATUS_FAILED = "failed"
WAKE_STATUS_LATE = "late"
WAKE_STATUS_STALE = "stale"
WAKE_STATUS_MERGED = "merged"
WAKE_STATUSES = (WAKE_STATUS_RECORDED, WAKE_STATUS_QUIET,
                 WAKE_STATUS_SKIPPED, WAKE_STATUS_PENDING,
                 WAKE_STATUS_RUNNING, WAKE_STATUS_DONE, WAKE_STATUS_REFUSED,
                 WAKE_STATUS_FAILED, WAKE_STATUS_LATE, WAKE_STATUS_STALE,
                 WAKE_STATUS_MERGED)
#: The statuses of a wake a model answered (A.33, A.58's n_llm).
MODEL_ANSWERED = (WAKE_STATUS_DONE, WAKE_STATUS_REFUSED, WAKE_STATUS_LATE)

#: A wake's codes (A.4, skipped_reason), and their fixed words. The four
#: gates first (A.2), in the order admission reads them (A.11).
CODE_PLATFORM_OFF = "platform_off"
CODE_MINDS_OFF = "minds_off"
CODE_LINE_OFF = "line_off"
CODE_ORCS_OFF = "orcs_off"
CODE_TOTAL = "total"
CODE_LINE = "line"
CODE_DEEP_SHARE = "deep_share"
CODE_AUTHORITY = "authority"
CODE_ROW_CLOSED = "row_closed"
CODE_DEAD = "dead"
CODE_UNSENT = "unsent"
#: O2b's frontier (2026-11-06, B.15c): r5, or its blind twin, closed at the
#: send while the frontier switch (orcs_frontier) is OFF.
CODE_FRONTIER_OFF = "frontier_off"
#: A.7: a wake the render pass could not finish (its merge, its render or
#: its admission raised): answered by code, never pending, never silence.
CODE_RENDER_FAILED = "render_failed"
#: A.4: the code O1's stored reason reads as (WAKE_SKIPPED_REASON).
CODE_PRE_O2 = "pre_o2"
CODE_UNBILLED = "unbilled"
CODE_BILLED_FAILURE = "billed_failure"
WAKE_CODES = (
    CODE_PLATFORM_OFF, CODE_MINDS_OFF, CODE_ORCS_OFF, CODE_LINE_OFF,
    CODE_TOTAL, CODE_LINE, CODE_DEEP_SHARE, "triage", "inflight", "day_cap",
    "routine_cap", "dollar_cap", "spacing", CODE_DEAD, CODE_ROW_CLOSED,
    "over_budget", "breaker", "render_failed", "paused", "backlog",
    CODE_AUTHORITY, "pre_o2", "wall_time", "worker_silent", CODE_UNSENT,
    CODE_UNBILLED, CODE_BILLED_FAILURE, CODE_FRONTIER_OFF)
WAKE_CODE_WORDS = {
    CODE_PLATFORM_OFF: "the platform's master switch is off",
    CODE_MINDS_OFF: "the minds switch is off",
    CODE_ORCS_OFF: "the orcs switch is off",
    CODE_LINE_OFF: "the Orcs budget line is off (ORC_DAILY_BUDGET_USD=0)",
    CODE_TOTAL: "the whole AI budget of the day is spent",
    CODE_LINE: "the Orcs budget line has no room for this call",
    CODE_DEEP_SHARE: "the deep-tier share of the Orcs line is used",
    "triage": "its class's share of the Orcs line is used",
    "inflight": "the money held for calls in flight is at the floor",
    "day_cap": "this Orc's model wakes for the day are used",
    "routine_cap": "this Orc's routine share of the day is used",
    "dollar_cap": "this Orc's budget for the day is used",
    "spacing": "a model read this Orc less than 15 minutes ago",
    CODE_DEAD: "the Orc has ended",
    CODE_ROW_CLOSED: "the position is closed",
    "over_budget": "its dossier is over the size cap",
    "breaker": "the calls are paused after repeated failures",
    "render_failed": "its render failed: the worker log says why",
    "paused": "the minds were paused",
    "backlog": "it waited behind a busy worker",
    CODE_AUTHORITY: "a seat reads above L0, so no model is asked",
    "pre_o2": "no model before O2",
    "wall_time": "the call ran past its wall time",
    "worker_silent": "the worker was silent",
    CODE_UNSENT: "the request was refused before it was sent",
    CODE_UNBILLED: "the call failed with no bill",
    CODE_BILLED_FAILURE: "the call failed and was billed",
    CODE_FRONTIER_OFF: "the frontier switch (orcs_frontier) is off",
}

#: A.21: each rung's explicit bound and its httpx stall timeout. No model
#: id here: mind_gateway reads the model of a rung from the catalog.
RUNG_LIMITS = {"h0": {"max_tokens": 8000, "timeout_s": 120},
               "r0": {"max_tokens": 8000, "timeout_s": 120},
               "r1": {"max_tokens": 16000, "timeout_s": 180},
               "r2": {"max_tokens": 16000, "timeout_s": 180},
               "r3": {"max_tokens": 24000, "timeout_s": 300},
               "r4": {"max_tokens": 32000, "timeout_s": 600},
               "r5": {"max_tokens": 32000, "timeout_s": 600}}
#: A.21: three pre-stream tries plus a live stream at 20 tokens a second.
#: It closes a wake's status only and never frees money (A.55).
WALL_S = {r: 3 * v["timeout_s"] + -(-v["max_tokens"] // 20) + 60
          for r, v in RUNG_LIMITS.items()}
#: A.21: the bound counts every prompt token at the 1h cache write, on this
#: much more than the estimate of the exact text sent.
BOUND_HEADROOM = 1.35
#: A.12, §2.2's high column: what the per-Orc dollar cap counts for a call
#: in flight or held without a bill, until OrcSetting "per_orc_high"
#: holds each rung's measured p90.
HIGH = {"h0": 0.0025, "r0": 0.0594, "r1": 0.1294, "r2": 0.1789,
        "r3": 0.2989, "r4": 0.5389, "r5": 1.8644}
#: The rung every O2a wake is answered on (A.21; §4 Q2), and from O2b
#: (2026-11-06, B.2b) every wake while the router's switch is OFF, and a
#: wake that records no rung of its own.
O2A_RUNG = "r0"

#: A.28-A.30: the doctrine's and the schema's versions, S's size cap.
S_VERSION = "s1"
SCHEMA_VERSION = "d1"
S_MAX_CHARS = 12000

#: A.30: the answer's vocabulary (its enums).
ACTIONS = ("hold", "revise_plan", "tighten", "exit", "trim", "lock_waive",
           "add")
RISK_SHARE_WORDS = {"none": None, "half": 0.5, "full": 1.0}
CLAUSE_KINDS = ("tighten", "trim", "exit", "add")
CLAUSE_TRIGGERS = ("touch", "close_beyond")
EXPECTATION_KINDS = ("none", "closes_above", "closes_below")
#: A trim always banks this share of the open size (A.30).
TRIM_SHARE = 0.5

#: A.31-A.32: the validator's rules, in the order they run, and their
#: classes: a whole-answer refusal, or a part refused (V9 drops the asked
#: wake, V11 withholds the note).
V_RULES = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10",
           "V11", "V12", "V13", "V14")
V_WHOLE = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V10", "V12",
           "V13", "V14")
V_PART = ("V9", "V11")
#: V2: plan changes a non-urgent wake may make in 24 hours.
PLAN_CHANGES_24H_MAX = 2
PLAN_WINDOW_H = 24
#: V9: an asked wake is 0 or within these minutes.
NEXT_WAKE_MIN_MIN = MIN_WAKE_SPACING_MIN
NEXT_WAKE_MAX_MIN = 2 * W11_METRONOME_H * 60
#: V11: a note with more of its letters outside Latin-1 is refused.
NOTE_NON_LATIN1_MAX = 0.20
#: V12: at most this many clauses; a watched level sits at least this many
#: ATR(1h) from the closing-side mark (A.48).
PLAN_CLAUSES_MAX = 4
PLAN_WATCH_MIN_ATR1H = 0.5
#: The menu rows the validation context keeps (A.8).
VCTX_MENU_MAX = 30
#: The menu kinds a level_reached fact may name (ids P, S, SW, RC, RN),
#: never the idea's own BE, CARE or EFF rows (A.46).
REACHED_KINDS = ("pool", "swing", "sweep", "recent", "round")
#: The decision frame's final bars the validation context lists (I12).
VCTX_DECISION_BARS = 12

#: A.37: the officer's rules, and their numbers.
I_RULES = ("I2", "I3", "I3c", "I3h", "I4", "I5", "I6", "I12")
ADD_MIN_SHARE = 0.25
STEPS_PER_DAY_MAX = 4
ADD_SPACING_BARS = 2
TRIM_SPACING_BARS = 1
OFFICER_ALLOW, OFFICER_CUT, OFFICER_REFUSE = "allow", "cut", "refuse"

#: A.41: a queued intent lives this long after its validation.
INTENT_TTL_S = 600
INTENT_STATUS_QUEUED = "queued"
INTENT_STATUS_RECORDED = "recorded"
INTENT_STATUS_REFUSED = "refused"
#: PS5 (A.47): the last decisions it lists, each a T1 view capped at
#: FENCE_CAPS["orc"].
PS5_DECISIONS = 6

#: A.24, A.25, A.55: the line lock's row, the money in flight and held,
#: the per-rung HIGH override and the smoke's verdicts (OrcSetting keys).
MINDS_LOCK_KEY = "minds_lock"
MINDS_INFLIGHT_KEY = "minds_inflight"
PER_ORC_HIGH_KEY = "per_orc_high"
SMOKE_VERDICT_KEY = "smoke_verdict"
#: The kinds of a hold (A.25): a call with no bill, a ledger row the
#: provider failed to write, a wake past its wall time.
HOLD_UNBILLED, HOLD_LEDGER_GAP, HOLD_ORPHAN = "unbilled", "ledger_gap", "orphan"
HOLD_KINDS = (HOLD_UNBILLED, HOLD_LEDGER_GAP, HOLD_ORPHAN)
#: N8: the line lock waits this long at most.
LINE_LOCK_TIMEOUT_MS = ORC_LOCK_TIMEOUT_MS
#: What a call came back with (mind_gateway.call, A.25): an answer; a
#: billed failure; a failure with no bill; refused before the send; no
#: send at all (a gate, the authority, the line).
REPLY_ANSWER, REPLY_BILLED, REPLY_UNBILLED, REPLY_UNSENT, REPLY_CLOSED = (
    "answer", "billed", "unbilled", "unsent", "closed")

# ── O2a: the queue (2026-11-05, the O2 spec A.7-A.19, A.48-A.56) ──────────
# Admission, the merge, the claim, the per-Orc day caps, the triage, the
# watchdogs and the breaker (bot_program/orcs/scheduler.py). Nothing here
# sends anything: while the minds switch is off or the Orcs line is at 0,
# every wake is answered by code.

#: The codes admission and the claim write (A.4), named once.
CODE_QUIET = "quiet"
CODE_TRIAGE = "triage"
CODE_INFLIGHT = "inflight"
CODE_DAY_CAP = "day_cap"
CODE_ROUTINE_CAP = "routine_cap"
CODE_DOLLAR_CAP = "dollar_cap"
CODE_SPACING = "spacing"
CODE_OVER_BUDGET = "over_budget"
CODE_BREAKER = "breaker"
CODE_PAUSED = "paused"
CODE_BACKLOG = "backlog"
CODE_WALL_TIME = "wall_time"
CODE_WORKER_SILENT = "worker_silent"

#: A.12: an Orc's model wakes a day are weather.caps_for's (OrcSetting
#: "wakes_per_day" overrides them, {"real": {class: n}, "paper": n}); its
#: dollars a day by money world, checked with each rung's HIGH (OrcSetting
#: "per_orc_daily_usd"); the share of either cap its routine wakes may use
#: (OrcSetting "routine_share"). Each binds at once, with no restart.
PER_ORC_DAILY_USD = {"real": 2.00, "paper": 0.50}
ROUTINE_SHARE = 0.75
WAKES_PER_DAY_KEY = "wakes_per_day"
PER_ORC_DAILY_KEY = "per_orc_daily_usd"
ROUTINE_SHARE_KEY = "routine_share"
#: A.13: the triage inside the Orcs line, with cap C and the reserve
#: R = min(reserve_cap, reserve_share x C) kept for real-money urgent
#: wakes: real non-urgent wakes stop at C - R, paper urgent at
#: paper_urgent x C, paper non-urgent at paper x C, the post-mortems and
#: the council of war at tickets x C (OrcSetting "triage" overrides it).
TRIAGE = {"reserve_cap": 1.00, "reserve_share": 0.20, "paper_urgent": 0.60,
          "paper": 0.45, "tickets": 0.30}
TRIAGE_KEY = "triage"
#: A.14: the triage classes and the claim's rank (OrcWake.priority).
CLASS_REAL_URGENT, CLASS_REAL, CLASS_PAPER_URGENT, CLASS_PAPER = (
    "real_urgent", "real", "paper_urgent", "paper")
RANKS = {CLASS_REAL_URGENT: 3, CLASS_REAL: 2, CLASS_PAPER_URGENT: 1,
         CLASS_PAPER: 0}
#: A.16: a model is cold when no call on it started this long ago; its
#: first call then runs alone (urgent wakes are never held).
COLD_MODEL_MIN = 55
#: A.17, A.19: one orc_think run claims and thinks one wake at a time for
#: this long at most; its beat every 60 s, a run not started within 55 s
#: dropped.
THINK_RUN_S = 100
THINK_BEAT_S = 60
#: A.54, A.55: a pending wake alarms past STALL_MIN from its first send,
#: closes past STALE_MIN; a watchdog silent for WATCH_PAUSED_MIN before a
#: pass means the Orcs were paused.
STALL_MIN = 20
STALE_MIN = 30
WATCH_PAUSED_MIN = 10
WATCH_BEAT_S = 300
#: A.56: the breaker opens after BREAKER_FAILS failed wakes of any Orc
#: within BREAKER_WINDOW_MIN, and pauses the claims BREAKER_PAUSE_MIN.
BREAKER_FAILS = 5
BREAKER_WINDOW_MIN = 10
BREAKER_PAUSE_MIN = 15
#: The OrcSetting keys of the breaker and the watchdog's last pass.
MINDS_BREAKER_KEY = "minds_breaker"
MINDS_WATCH_LAST_KEY = "minds_watch_last_at"
#: A.52: what sends an Orc to the care, and its words (care_owned_reason).
CARE_AFTER_FAILED = 2
CARE_AFTER_REFUSED = 2
CARE_WORKER_SILENT = "worker_silent"
CARE_CALLS_FAILING = "calls_failing"
CARE_ANSWERS_REFUSED = "answers_refused"
CARE_WORDS = {
    CARE_WORKER_SILENT: "a wake waited 30 minutes for a silent worker",
    CARE_CALLS_FAILING: "two model calls in a row failed",
    CARE_ANSWERS_REFUSED: "two answers in a row were refused",
}
#: A.10: the facts hash's version, part of its hashed input; the print's
#: distance in bands, in minutes: under 3 h, 3 to 24 h, over 24 h.
FACTS_HASH_VERSION = 2
PRINT_BANDS_MIN = (180, 1440)
#: A.49: the asked wake's memory key and words.
W11_ASK_KEY = "w11_ask"
W11_ASK_WORDS = "the Orc asked to look again"

# ── O2a: the shadow arm and the tickets (2026-11-05, the O2 spec A.41-A.45b,
# A.57, A.59-A.61). Nothing here sends anything or reaches a position: a
# queued proposal steps the Orc's own arm (intents.py, ghost.py), and a
# ticket holds the Orcs line's money for a call that is not a wake.

#: A.42: the kinds a queued intent steps the O arm with (an add is judged
#: and recorded, never applied, A.41), and its two ends at the tick.
INTENT_APPLIED_KINDS = ("tighten", "trim", "exit", "lock_waive")
INTENT_STATUS_SIMULATED = "simulated"
INTENT_STATUS_EXPIRED = "expired"
EXPIRY_TTL, EXPIRY_MOVED, EXPIRY_ROW_CLOSED, EXPIRY_ARM_CLOSED = (
    INTENT_EXPIRY_CODES)
#: The expiry codes in fixed words (A.42); `moved` says which way in the
#: intent's own `why` (MOVED_WORDS).
EXPIRY_WORDS = {
    EXPIRY_TTL: (f"no tick could apply it within {INTENT_TTL_S // 60} "
                 f"minutes of its validation"),
    EXPIRY_MOVED: "the price moved before a tick could apply it",
    EXPIRY_ROW_CLOSED: "the position closed first",
    EXPIRY_ARM_CLOSED: "the shadow arm had already closed",
}
MOVED_WORDS = {
    "room": ("the would-stop no longer has its room (0.5 ATR) from the "
             "tick's price and mark"),
    "tighter": "the would-stop is no longer tighter than the shadow arm's",
    "unmeasured": "the would-stop's room cannot be measured",
    "trim": "nothing is left to trim",
}

#: A.57: a ticket's request, estimated (dossier.estimate_tokens x the
#: family factor) above its caller's cap, is refused by code (over_budget)
#: before anything is reserved: a digest that grew with an idea's life
#: would make the reservation no bound at all. The smoke sends a wake's
#: stored dossier, capped as a wake's; so does a probe (O2b, 2026-11-06,
#: B.11: the wake's own stored blocks); the others are §1.0.9's, measured
#: with `orcs tokens` like S once each caller ships.
TICKET_MAX_TOKENS = {"smoke": DOSSIER_MAX_TOKENS, "probe": DOSSIER_MAX_TOKENS,
                     "captain": 10000, "emperor": 16000, "skeptic": 6000,
                     "postmortem": 12000, "tribunal": 12000,
                     "question": DOSSIER_MAX_TOKENS + 400}
#: §1.0.9: the triage ceiling a ticket caller reserves under (A.13): the
#: smoke and the probes C - R, the real-money non-urgent class (a probe
#: also within its own allowance, PROBES_USD_SHARE; O2b, 2026-11-06). A
#: later caller adds its row with its CALLER_RUNGS row.
TICKET_CLASS = {"smoke": CLASS_REAL, "probe": CLASS_REAL}
#: §1.0.9: a caller's tickets a UTC day; 0 counts none (the smoke is one
#: per command, which the command keeps). The probes' caps are by kind and
#: a user a day (PROBES_PER_DAY, below; O2b, 2026-11-06).
TICKET_DAY_CAP = {"smoke": 0}
#: A.57: one billed attempt per item; a call that failed with no bill is
#: tried again at most this many times.
TICKET_RETRIES = 1
#: A ticket in OrcSetting "minds_inflight", beside the holds (A.57); the
#: tickets' day counts and items (OrcSetting "minds_tickets"), kept this
#: many days.
HOLD_TICKET = "ticket"
MINDS_TICKETS_KEY = "minds_tickets"
TICKET_ITEMS_KEEP_DAYS = 7
#: A ticket item's states: a call reserved; closed by a billed call, by a
#: second failure with no bill, by a request refused before the send, or
#: by waiting past its UTC day; open after a failure with no bill (one try
#: left) or a refusal for budget (it may wait until the next UTC day).
ITEM_RESERVED, ITEM_BILLED, ITEM_FAILED, ITEM_UNSENT = (
    "reserved", "billed", "failed", "unsent")
ITEM_UNBILLED, ITEM_WAITING, ITEM_EXPIRED = "unbilled", "waiting", "expired"
ITEM_CLOSED = (ITEM_BILLED, ITEM_FAILED, ITEM_UNSENT, ITEM_EXPIRED)
CODE_ITEM_CLOSED = "item_closed"
CODE_ITEM_BUSY = "item_busy"
CODE_EXPIRED = "expired"
TICKET_CODE_WORDS = {
    CODE_ITEM_CLOSED: "this item had its one billed call already",
    CODE_ITEM_BUSY: "a call for this item is in flight",
    CODE_EXPIRED: "it waited for the budget past its UTC day",
    # O2b's probes (2026-11-06, B.11): a probe's own refusals
    "probes_off": "the probes' switch is off",
    "probe_allowance": "the probes' own allowance of the Orcs line is used",
    "real_waits": "a real-money wake waits for its model call: probes go "
                  "last",
    "real_money": "real money gets no probe",
}
#: A.61: S's count (OrcSetting "s_tokens") and the smoke's reasons for a
#: FAIL (claude_smoke's own: call A, call B, no cache read, less than 2x).
S_TOKENS_KEY = "s_tokens"
SMOKE_FAIL_REASONS = ("call_a", "call_b", "cache", "effort")

# ── O2b: the route in shadow (2026-11-06, the O2 spec B.1-B.6, B.16c) ──────
# The router (bot_program/orcs/router.py) is pure and names rungs only. Its
# choice is recorded on every rendered wake, minds on or off; while the
# router's switch is OFF, r0 answers every wake a model reads: nothing
# here sends anything.

#: The router's choice in tier words (B.16c), as the Orc's page shows it
#: (mind.rung_words, from the catalog by the rung's name): never a model
#: id, never a cost.
ROUTE_WOULD_T = "would route: {rung} ({tier} tier, {effort} effort)"

# ── O2b: the routed rung answers (2026-11-06, the O2 spec B.2b, B.4, B.5,
# B.13-B.15a, B.16a) ─────────────────────────────────────────────────────
# Behind `orcs_router`, OFF on arrival and turned on only with the trading
# PIN (N2): OFF, r0 answers every wake a model reads and the router's
# choice is only recorded; ON, with the minds on, the rung the router chose
# answers, one effort per model until the smoke's PASS. Nothing here sends
# anything.

#: N2: the router's switch (core/platform_control.py ORC_MIND_SWITCHES).
ROUTER_SWITCH = "orcs_router"
#: The rungs above r0, which only the router's switch opens to a wake and
#: to `orcs smoke --rung` (B.15a); r5 also only through Fable's gate (B.15c,
#: O2b's frontier, 2026-11-06), which the smoke never passes. h0 is a
#: probe's rung, r0 the default.
ROUTED_RUNGS = ("r1", "r2", "r3", "r4", "r5")
#: B.13: the tiers the deep share holds (ai_agents/spend.py: deep and
#: frontier), mirrored by the scheduler on the money in flight and held;
#: the share itself is the budget's, read through the gateway.
DEEP_TIERS = ("deep", "frontier")
#: B.14: the rungs on which a real-money wake names the server's fallback
#: (the list form, the catalog's ORC_FALLBACK_V1), and its own max_tokens.
FALLBACK_RUNGS = ("r2", "r3", "r4", "r5")
FALLBACK_MAX_TOKENS = 8000
#: The smoke's words when B.5's map answers a rung on another (orcs.py).
SMOKE_MAPPED_T = ("rung {asked}, answered as {rung} (one effort per model "
                  "until the smoke's PASS for the {family} family)")

# ── O2b: the probes (2026-11-06, the O2 spec B.8a, B.11, B.12, B.15b,
# B.16a, B.16b) ──────────────────────────────────────────────────────────
# Behind `orcs_probes`, OFF on arrival and turned on only with the trading
# PIN (N2): beside a paper or demo wake a model read, a neighbouring rung
# reads the wake's own stored dossier again, blind, on a ticket of its own
# allowance, stored only in OrcTierGrade and the ledger
# (bot_program/orcs/probes.py). Nothing here sends anything.

#: N2: the probes' switch (core/platform_control.py ORC_MIND_SWITCHES).
PROBES_SWITCH = "orcs_probes"
#: §1.0.9: the probes' ticket caller, and their source_ref's word:
#: Orc:<pk>:Wake:<w>:probe:<rung> (the ledger's probe rows hold the mark).
PROBE_CALLER = "probe"
PROBE_REF_MARK = f":{PROBE_CALLER}:"
#: OrcTierGrade.kind: an h0 probe, a boundary probe, and Fable's blind twin
#: (B.10: O2b's frontier, 2026-11-06, beside an r5 wake only); the kinds a
#: probe is sent as.
TIER_GRADE_KINDS = ("h0", "boundary", "twin")
PROBE_KINDS = ("h0", "boundary")
#: OrcTierGrade.boundary: the band boundaries a boundary probe crosses
#: (BAND_ROUTINE_MAX, BAND_MATERIAL_MAX, BAND_COMPLEX_MAX); h0 names none.
PROBE_BOUNDARIES = (BAND_ROUTINE_MAX, BAND_MATERIAL_MAX, BAND_COMPLEX_MAX)
#: B.11 (§4 Q13): a user's probes a UTC day, by kind, counted in the
#: tickets' book by (caller, kind, user); OrcSetting "probes_per_day"
#: overrides a kind, binding at once (0 sends none of that kind).
PROBES_PER_DAY = {"boundary": 6, "h0": 40}
PROBES_PER_DAY_KEY = "probes_per_day"
#: B.11: the probes' own allowance of the Orcs line: this share of its cap,
#: read at once ($1.50 at $10); OrcSetting "probes_usd_per_day" holds an
#: explicit value, in dollars.
PROBES_USD_SHARE = 0.15
PROBES_USD_KEY = "probes_usd_per_day"
#: B.11 as built: a probe is sent within this many minutes of the routed
#: answer (the wake's finished_at), else dropped by code: B.12 prices both
#: answers after the LATER one, so a late probe would move the routed
#: answer's grade too.
PROBE_FRESH_MIN = 15
#: B.12: the pairs the watchdog's grade reads, this many days back.
PROBE_GRADE_DAYS = 7
#: B.12: a boundary reads "validated" after this many completed blocks of
#: SEAT_WINDOW pairs per (boundary, kind, world): shown only, read by no
#: router (the catalog's ladder note).
VALIDATED_BLOCKS = 2
#: The probes' codes (TICKET_CODE_WORDS above).
CODE_PROBES_OFF = "probes_off"
CODE_PROBE_ALLOWANCE = "probe_allowance"
CODE_REAL_WAITS = "real_waits"
CODE_PROBE_REAL = "real_money"

# ── O2b: Fable's gate and its blind twin (2026-11-06, the O2 spec B.4b,
# B.8b, B.9, B.10, B.15c, §4 Q12) ──────────────────────────────────────────
# Behind `orcs_frontier`, OFF on arrival and turned on only with the trading
# PIN (N2): with the router's switch ON, a real-money extreme wake may be
# answered by r5 (Fable) beside its r4 blind twin when every clause of
# Fable's gate holds (router.fable_gate), under a daily quota of 0 by
# default. The pair is priced at the dossier's size cap, about $3.57 (r5's
# bound with its fallback and its twin's), above the $3.00 the Orcs may hold
# in flight (ORC_LIVE_FLOOR_USD): in O2 the gate cannot open, so no r5 and
# no twin call is sent. Nothing here sends anything.

#: N2: the frontier's switch (core/platform_control.py ORC_MIND_SWITCHES).
FRONTIER_SWITCH = "orcs_frontier"
#: Fable's rung, and the rung its blind twin is asked as (B.5 maps it: r2
#: until Opus's PASS).
FRONTIER_RUNG = "r5"
TWIN_RUNG = "r4"
#: §1.0.9: the twin's caller, and its source_ref's word:
#: Orc:<pk>:Wake:<w>:twin:<rung> (its ticket's `pair` names the r5 wake).
TWIN_CALLER = "twin"
TWIN_REF_MARK = f":{TWIN_CALLER}:"
#: B.8b (§4 Q12): the r5 calls a user may make a UTC day across all
#: classes, OrcSetting "frontier_per_day" (0 by default: Fable is off by
#: quota too), less the user's r5 calls today. The day row's frontier_quota
#: shows it; nothing that routes reads the day row.
FRONTIER_PER_DAY = 0
FRONTIER_PER_DAY_KEY = "frontier_per_day"

# ── O2c: honor, temperaments, Captains, the Emperor and the drums, in
# shadow (2026-11-07, the O2 spec §1.3.2) ─────────────────────────────────
# The journal's new words, the fence's caps and the new tables' allowed
# values (bot_program/orcs/models.py: Captain, CaptainOrder, OrcWave,
# OrcTemperamentGrade). Nothing reads them yet: each arrives with the O2c
# commit that writes it, behind its own switch, OFF on arrival and turned
# on only with the trading PIN (N2). Nothing here sends anything.

#: OrcJournal.kind: the Skeptic's co-sign, journaled beside its item and
#: never a gate (C.18); the third assignment, after O1a's and O1d's.
JOURNAL_KINDS = JOURNAL_KINDS + ("skeptic",)
#: OrcJournal.author: the Emperor's order on each living Orc (C.13). A
#: model's words, never a fact: FACT_AUTHORS is unchanged (N5).
AUTHORS = AUTHORS + ("emperor",)
#: The fence's caps (N5): a temperament's lane texts in PS9 (C.5), a
#: Captain's words (C.8), the Emperor's order (C.11) and the Skeptic's
#: verdict (C.18).
FENCE_CAPS = {**FENCE_CAPS, "temperament": 600, "captain": 280,
              "emperor": 600, "skeptic": 280}
#: CaptainOrder.kind (C.7, §4 Q15): no add (hold_fire), a tighten to a
#: level of the menu, a cut that names an Orc, a cap on a same bet's legs
#: (theme). Each graded, never applied (C.8, C.9).
CAPTAIN_ORDER_KINDS = ("hold_fire", "tighten", "cut", "theme")
#: CaptainOrder.mode: every O2c order is in shadow (C.8), one of MODES.
ORDER_MODES = (MODE_SHADOW,)
#: Captain.state (C.7): seated while its class has a living Orc; idle
#: while it has none (never deleted, its record kept).
CAPTAIN_SEATED, CAPTAIN_IDLE = "seated", "idle"
CAPTAIN_STATES = (CAPTAIN_SEATED, CAPTAIN_IDLE)
#: OrcWave.breaker["state"] (C.16): closed, a wave's W12 wakes may go;
#: open, its deliveries are journaled only, as in O1, and it records why.
WAVE_BREAKER_CLOSED, WAVE_BREAKER_OPEN = "closed", "open"
WAVE_BREAKER_STATES = (WAVE_BREAKER_CLOSED, WAVE_BREAKER_OPEN)
