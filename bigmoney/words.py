"""Every English string the Big Money Board prints (spec §2.11).

One module, so the English-only and the money tripwires can read them all
at once (tests/test_big_money_board.py), and so a voice that quotes the
board later (PR8) quotes these words and no others. Every unread reason
carries its own remedy, so the Fixer can quote it as written.
"""
from __future__ import annotations

# ── evidence and role chips ──────────────────────────────────────────────
GRADE_WORDS = {"ROBUST": "Strong evidence",
               "CONDITIONAL": "Conditional evidence",
               "FRAGILE": "Weak evidence"}
ROLE_WORDS = {"lean": "counts in the lean",
              "current": "the slower current",
              "risk": "risk, not direction",
              "context": "context only"}

# ── lean labels ──────────────────────────────────────────────────────────
LEANS_UP = "Leans up"
LEANS_DOWN = "Leans down"
NO_CLEAR_LEAN = "No clear lean"
NO_FOOTPRINT = "No footprint with evidence in season"
UNREAD = "Unread"
LEAN_LABELS = (LEANS_UP, LEANS_DOWN, NO_CLEAR_LEAN, NO_FOOTPRINT, UNREAD)

# ── the page ─────────────────────────────────────────────────────────────
PAGE_TITLE = "Big Money · Sauron Vision"
H1 = "Big Money"
LEDE = ("Where the large players must move, read twice a day from free public "
        "footprints, and graded against what prices did next. Information, "
        "never a gate: no order reads this page.")
AS_OF = ("{run} read at {hhmm} UTC on {day}, from the market day of "
         "{market_day}.")
OFF = ("The board is off. The newest read below is from {when}; nothing new "
       "is read until the big_money_board switch is on.")
STALE = "The newest read is {n} hours old: shown, not current."
EMPTY = ("No read yet. The board reads at 05:20 and 23:20 UTC once its switch "
         "is on.")
SECTION_WORLD = "The world this week"
HEADERS_WORLD = ("Market", "Lean this week", "Why", "The month's current",
                 "Crowding", "Flows", "Record")
DOLLAR_HINT = "up = the dollar rises"
NO_COT_ROW = "no COT market until the players' reports (PR3)"
WEIGHT_ZERO_CHIP = "weight zero"
INSTRUMENT_HEADER = "Instrument"
CRYPTO_NOTE = ("No forced flow with published evidence exists for crypto: the "
               "lean stays quiet on purpose.")
DASH = "—"
DASH_TITLE = "unread: {reason}"
SECTION_INSTRUMENTS = "Other instruments"
INSTRUMENTS_LEDE = ("Each commodity and currency pair the CFTC reports on, read "
                    "on its own: the speculators' weekly change faded, their "
                    "crowding, and the month-end fix for the four fix pairs.")
SECTION_AHEAD = "Forced flows ahead (30 days)"
KIND_WORDS = {"announced": "announced",
              "computed": "computed from the rule",
              "estimate": "an estimate from prices"}
CALENDAR_ROW = "{day} · {event} · {kind}"
SOURCE_LINK = "source"
SECTION_TIDE = "The tide (the slower current, weak evidence)"
TIDE = ("Dollar liquidity (the Fed's balance sheet minus the Treasury's cash "
        "and the reverse repo): {state} over 4 weeks. Bank reserves {reserves}; "
        "foreign central banks' Treasuries at the Fed {custody}.")
TIDE_NOTE = ("With the reverse repo near empty, this is the Fed's balance sheet "
             "minus the Treasury's cash. Level charts of liquidity against "
             "prices broke after 2022: shown and scored, never counted in a "
             "lean.")
SECTION_STRESS = "Market stress"
STRESS = ("{level} (score {n} of 100): {components}. Read here only; the "
          "posture that binds real money is set by the crisis mode, not by "
          "this board.")
STRESS_LEVELS = {"calm": "Calm", "stressed": "Stressed", "crisis": "In crisis",
                 "recovery": "Stressed"}
STRESS_COMPONENTS = {"index_drawdown": "the drawdown",
                     "index_5d": "the week's fall",
                     "realized_vol": "realized volatility",
                     "vix": "the VIX", "vix_term": "the VIX curve",
                     "hy_spread": "credit spreads",
                     "brain": "the Mind's regime"}
SECTION_RECORD = "The record"
HEADERS_RECORD = ("Footprint", "Market", "Claim", "Live", "Replayed", "Verdict",
                  "Against the round trip")
CLAIM_DIRECTION = "direction over {h} business days"
CLAIM_DIRECTION_DAYS = "direction over {h} days"
CLAIM_TAIL = "a deeper drawdown against the crowd over {h} business days"
ZEROED = ("Works against its claim so far: weight set to zero, never flipped; "
          "the reverse is a new hypothesis for the proving ground.")
REPLAY_NOTE = ("Replayed with publication lags: not a live record. FRED "
               "revisions overwrite stored values, so a replay reads revised "
               "figures.")
SECTION_SOURCES = "Sources"
HEADERS_SOURCES = ("Input", "Newest data", "Age", "Bound", "State")
SOURCE_STATES = ("fresh", "stale", "missing", "no key", "gap in the tape")
SECTION_NOT = "What this board is not"
NOT_LINES = (
    "Not a copy of BlackRock's 13F: a 13F is 45 to 135 days old when read; a "
    "crowding gauge at most, never timing.",
    "Not a flow chaser: flows reported after the fact are mostly the move "
    "itself; the board scores the follow-the-flow claim in public instead.",
    "Not a liquidity chart: two trending levels whose fit broke after 2022; "
    "context only.",
    "Not dark-pool buying: off-exchange prints arrive weeks late and carry no "
    "direction.",
    "Not dealer gamma: there is no free dealer-position data, and vendor "
    "levels are untested out of sample.",
    "Not a trade: nothing here places an order. A footprint becomes a rule "
    "only through the proving ground, on paper first.",
)
FOOTER = ("Every footprint is scored against the prices that followed. A dash "
          "is a footprint that could not be read, never a zero.")

# ── footprint names, for the record table ────────────────────────────────
FOOTPRINT_NAMES = {
    "rebalance": "Month-end rebalancing",
    "rebalance_reversal": "The rebalance unwinding",
    "fx_fix": "Hedging at the London fix",
    "cot_change": "Speculators' weekly change, faded",
    "crowding": "Speculators' crowding",
    "crowd_losing": "A crowd losing",
    "cta": "Trend followers",
    "vrp": "Fear against delivered",
    "flows": "Fund flows (the crowd's claim)",
    "opex": "Options expiry week",
    "tide": "The tide",
}

# ── cell words ───────────────────────────────────────────────────────────
REBALANCE_UP = ("Equities ran ahead of bonds this month ({z}): a 60/40 fund now "
                "holds {w} percent equities, so pension and target-date funds "
                "sell equities and buy bonds into month-end.")
REBALANCE_DOWN = ("Equities lagged bonds this month ({z}): a 60/40 fund now "
                  "holds {w} percent equities, so pension and target-date funds "
                  "buy equities and sell bonds into month-end.")
REBALANCE_SMALL = ("Equities and bonds sit near their weights this month ({z}): "
                   "little to rebalance.")
REBALANCE_TLT = (" Bond leg read on TLT (long bonds), a louder proxy than the "
                 "funds' own bonds.")
REBALANCE_ONE_LEG = " Bond leg unread: the equity drift alone."
REBALANCE_SEASON = ("Out of season: the window opens {day} (the last 5 business "
                    "days of the month).")
REBALANCE_FROM = "month-end rebalancing"
REVERSAL_WORDS = ("The month-end rebalance is done ({z} last month): its pressure "
                  "has tended to reverse within two weeks.")
REVERSAL_SEASON = ("Out of season: the reversal window is the first 5 business "
                   "days of the month.")
REVERSAL_FROM = "the rebalance unwinding"
FX_FIX_PAIR_UP = ("{index} beat the S&P 500 this month ({z}): hedgers sell {ccy} "
                  "into the month-end London 4 pm fix.")
FX_FIX_PAIR_DOWN = ("{index} lagged the S&P 500 this month ({z}): hedgers buy "
                    "{ccy} into the month-end London 4 pm fix.")
FX_FIX_ROW = "Across {n} pairs, the month-end hedge flows {verb}."
FX_FIX_VERBS = {"up": "favour the dollar", "down": "lean against the dollar",
                "flat": "cancel out"}
FX_FIX_SEASON = ("Out of season: the window is the last 2 business days of the "
                 "month, from {day}.")
FX_FIX_FROM = "month-end hedge flows at the fix"
COT_BOUGHT = ("Speculators bought hard last week ({z}, report {day}): prices "
              "have tended to follow the hedgers on the other side over the "
              "next 1 to 3 weeks.")
COT_SOLD = ("Speculators sold hard last week ({z}, report {day}): prices have "
            "tended to follow the hedgers on the other side over the next 1 to "
            "3 weeks.")
COT_ORDINARY = "Speculators' weekly change ordinary ({z})."
COT_CONTEXT = " Context only here: no evidence it forecasts {market}."
COT_FROM = "the speculators' weekly change, faded"
CROWDING_CROWDED = ("Speculators crowded {side} (COT index {idx}, report {day}): "
                    "a fatter left tail, not a lower average.")
CROWDING_HEAVY = "Speculators heavy {side} (COT index {idx}, report {day})."
CROWDING_NORMAL = "Speculators not crowded (COT index {idx})."
CROWD_LOSING = ("Speculators are {degree} {side} and the price has moved {z} "
                "against them since {day}: forced exits are likely.")
CROWD_NOT_LOSING = "The crowd is not losing: no forced exit in sight."
CROWD_NONE = "No crowd at an extreme."
CTA_WORDS = ("Trend followers are {side} on {n} of three horizons (1, 3 and 12 "
             "months).")
CTA_SHORT = "{side} on {n} of three horizons"
CTA_TRIGGER = (" Their nearest trigger: a close {beyond} {level} turns the "
               "{horizon} signal {turn} ({k} daily moves away).")
CTA_HORIZONS = {21: "1-month", 63: "3-month", 252: "12-month"}
VRP_HIGH = ("Fear priced above what the market delivers ({z}): equity risk has "
            "been paid over the following quarter.")
VRP_LOW = ("Fear priced below what the market delivers ({z}): thin reward for "
           "equity risk over a quarter.")
VRP_MID = "Fear priced about as delivered ({z})."
FLOWS = ("{etf}: {ratio:.1f} times its usual dollar volume over 5 days, price "
         "{way}. Flows mostly follow price: shown and scored, never a lean.")
OPEX = "Monthly options expiry week (Friday {day}): context only."
OPEX_SEASON = "Out of season: the expiry week is the week of the third Friday."

# ── risk flags ───────────────────────────────────────────────────────────
FLAG_CROWDED_LONG = "crowded long"
FLAG_CROWDED_SHORT = "crowded short"
FLAG_HEAVY_LONG = "heavy long"
FLAG_HEAVY_SHORT = "heavy short"
FLAG_LEAN_CROWDED = "the lean is crowded: a fatter left tail"
FLAG_CROWD_LOSING = "crowded and losing: forced exits likely"
FLAG_STRESSED = "market stressed"
FLAG_CRISIS = "market in crisis"
FLAG_FORCED_SOON = "forced flows within 2 business days: {events}"

# ── calendar events ──────────────────────────────────────────────────────
EV_MONTH_END = "Month-end"
EV_QUARTER_END = "Quarter-end"
EV_REBALANCE_OPENS = "Month-end rebalancing window opens"
EV_REVERSAL_OPENS = "Rebalance reversal window opens"
EV_FX_FIX_OPENS = "Month-end FX fix window opens"
EV_OPEX = "Monthly options expiry"
EV_QUARTERLY_OPEX = "Quarterly options expiry and index rebalances"
EV_VIX_EXPIRY = "VIX expiry"
EV_COT = "COT report (positions of Tuesday)"
EV_COT_DELAYED = "COT report, delayed by a holiday"
EV_13F = "13F deadline (holdings of the quarter)"
EV_FOMC = "FOMC decision"
EV_FOMC_BLACKOUT = "FOMC blackout begins"
EV_FINANCING = "Treasury financing estimates"
EV_REFUNDING = "Treasury refunding statement"
EV_TIC = "Treasury foreign-flows release (TIC)"
EV_RUSSELL_RANK = "Russell rank day"
EV_RUSSELL_PRELIM = "Russell preliminary lists"
EV_RUSSELL_LOCKDOWN = "Russell lockdown"
EV_RUSSELL_RECON = "Russell reconstitution at the close"
EV_MSCI_ANNOUNCED = "MSCI review announced"
EV_MSCI_EFFECTIVE = "MSCI review effective at the close"
EV_SP500_REBALANCE = "S&P 500 quarterly rebalance at the close"
EV_NDX_RECON = "Nasdaq-100 annual reconstitution at the close"
EV_TAX_DATE = "Corporate tax date (drains bank reserves)"
EV_FUNDING_DEADLINE = "US government funding deadline"
EV_TREND_TRIGGER = "Trend followers' trigger on {market}"

PLAY_REBALANCE = ("Balanced funds sell what outran its target into the month's "
                  "close; the move has tended to give back within two weeks.")
PLAY_FX_FIX = ("Hedgers adjust at the last London fix of the month; the currency "
               "move into it has tended to be predictable.")
PLAY_INDEX = ("Do not chase additions: the announcement effect has faded to "
              "under one percent; pressure before the close has tended to "
              "reverse after it.")
PLAY_EVENT_RISK = "An event-risk window: no direction is claimed."
PLAY_TREND = "A close beyond this level turns trend followers the other way."

# ── unread reasons (each carries its remedy) ─────────────────────────────
R_NO_KEY = "FRED key not set (FRED_API_KEY): {series} unread"
R_FRED_STALE = "{series}: no observation in {n} days (bound {b})"
R_FRED_NONE = ("{series}: no observation stored (manage.py big_money "
               "fred-history --yes)")
R_FRED_THIN = ("{series}: {n} observations, {m} needed (manage.py big_money "
               "fred-history --yes)")
R_UNITS = "units of {series} unknown ({units})"
R_COT_NONE = "COT: no report for {symbol} (no futures market maps to it)"
R_COT_STALE = ("COT report stale ({n} days, bound {b}): manage.py smart_money "
               "cot-backfill --yes")
R_COT_THIN = ("COT history thin: {n} weeks, 52 needed (manage.py smart_money "
              "cot-backfill --yes)")
R_COT_NO_OI = "COT report of {day} for {symbol} has no open interest"
R_CLOSES_THIN = ("{symbol}: {n} daily closes, {m} needed (manage.py "
                 "backfill_bars --symbols {symbol} --intervals 1d --bars 1600)")
R_CLOSE_STALE = "{symbol}: last close {n} days old (bound {b})"
R_CLOSE_STALE_CRYPTO = ("{symbol}: last close {n} days old (bound {b}): the "
                        "00:10 UTC crypto daily close (fetch-eod-crypto, "
                        "switch scraper_eod) writes it")
R_NO_CLOSE_YET = "{symbol}: no close for {date} yet: the morning read fills it"
R_NO_VOLUME = ("{symbol}: no traded volume stored (manage.py backfill_bars "
               "--symbols {symbol} --intervals 1d --bars 1600)")
R_CALENDAR_RUNWAY = ("calendar: announced dates end on {date}; computed dates "
                     "only after it")
R_HOLIDAYS_END = "holiday table ends: weekdays counted as business days"
R_NOT_REPLAYED = "not replayed (live only)"
R_UNREADABLE = "unreadable: {name}"
R_FIX_PAIRS = "fewer than 2 fix pairs readable: {reasons}"
R_STRESS_NONE = "market stress: neither an index nor the VIX could be read"
R_GAP = "SPX500 tape: {n} days without a stored close before {day}"

# ── the morning brief (no decimals, no %, no currency, no level) ─────────
BRIEF_MARKET = "• {market}: {label} this week{from_part}{flag_part}"
BRIEF_COMMODITY = ("• {symbol}: {label} this week (the speculators' weekly "
                   "change, faded)")
BRIEF_TREND = "• Trend followers: {markets} within one daily move of a trigger"
BRIEF_TIDE = ("• Tide: dollar liquidity {state} over 4 weeks (context, weak "
              "evidence)")
BRIEF_AHEAD = "• Ahead: {events}"
BRIEF_UNREAD = "• Unread: {reasons}{more}"
BRIEF_STALE = "• The newest read is {n} hours old: not shown"
BRIEF_NONE = "• No read yet"

# ── the ticket note ──────────────────────────────────────────────────────
TICKET_LABEL = "BIG MONEY"
TICKET_SUFFIX = "Information, never a gate."
TICKET_ROW = "{market}: {label} this week ({from_words}). Your {side} is {way}."
TICKET_NO_CLEAR = "{market}: no clear lean this week. Your {side} meets no lean."
TICKET_NO_FOOTPRINT = "No footprint with evidence leans {market} this week."
TICKET_PAIR = ("Dollar: {label} this week ({from_words}). Your {side} of {pair} "
               "{buys} the dollar: {way}.")
TICKET_FIX_PAIR = ("{pair}: the month-end fix {verb} {ccy} ({z}). Your {side} is "
                   "{way}.")
TICKET_COMMODITY = ("{symbol}: {label} this week (the speculators' weekly "
                    "change, faded). Your {side} is {way}.")
TICKET_CROWDING = " Crowding: {words}"
TICKET_TREND = " Trend followers: {words}."
TICKET_AHEAD = " Ahead: {event} {day}."
TICKET_READ_AT = " Read {when} UTC."
TICKET_OUTSIDE = "This instrument is outside the board's markets: nothing read."
TICKET_OFF = "The board is off: nothing read."
TICKET_STALE = "The newest read is {n} hours old: not shown as current."
TICKET_NONE = "No read yet: nothing read."
NO_READ = "No read yet."
TICKET_UNREAD = "Unread: {reason}."
TICKET_ERROR = "The board could not be read ({name})."

# ── the record ───────────────────────────────────────────────────────────
VERDICT_FEW = "too few to judge ({n} of {m})"
VERDICT_PAYS = "pays so far"
VERDICT_AGAINST = "works against its claim so far"
VERDICT_NONE = "no edge measured yet"
VERDICT_TAIL = ("crowded readings were followed by {x:.1f} times the usual "
                "drawdown ({n} readings)")
COST_LINE = ("Measured: {m:+.1f} bp per signed reading. The platform's assumed "
             "round trip for {klass}: {c:g} bp.")
COST_SHORT = " Does not clear twice the round trip."
UNSCORED = "no close on {date}: unscored"

# ── the task ─────────────────────────────────────────────────────────────
TASK_WARNING = "Big money board: {n} of {m} footprints unread: {reasons}"

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
          "Nov", "Dec")


def day(d) -> str:
    """'Fri 30 Oct' (Ddd D Mon)."""
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def day_year(d) -> str:
    """'Fri 30 Oct 2026' (Ddd D Mon YYYY)."""
    return f"{day(d)} {d.year}"


def day_short(d) -> str:
    """'30 Oct' (D Mon)."""
    return f"{d.day} {MONTHS[d.month - 1]}"


def z(value) -> str:
    """A z-score as the board prints it: '+1.2 sd'."""
    return f"{float(value):+.1f} sd"


def every_string():
    """Every module-level string here, for the language tripwires."""
    out = []
    for name, value in globals().items():
        if name.startswith("_") or name in ("every_string",):
            continue
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, (tuple, list)):
            out.extend(v for v in value if isinstance(v, str))
        elif isinstance(value, dict):
            out.extend(v for v in value.values() if isinstance(v, str))
    return out
