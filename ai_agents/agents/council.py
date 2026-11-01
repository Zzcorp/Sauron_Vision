"""THE COUNCIL (2026-10-08): ten voices, the Emperor in the chair.

The operator: "To become the visionary platform we aim at, we must be
revolutionary in our choices: new approaches, critical sense, a global,
clear and omniscient vision of the market." Beside the two voices the
trade debate already has (ai_agents/agents/trade_debate.py: THE
EXECUTIONER, "nothing is possible", and THE CHAMPION, "all is good"),
eight more sit:

  THE OPPORTUNIST  what the crowd misses: the asymmetric payoff, a better
                   instrument or moment ("bigger opportunity elsewhere",
                   a direction call the calibration resolver grades);
  THE STRIKER      the one who takes action: take now, wait for one named
                   touch with a deadline, or skip;
  THE FIXER        the problem solver: the one flaw that matters and the
                   one concrete repair;
  THE GAMBLER      the heroic voice: how hard to press, all in included,
                   always inside the limits; his record says if it pays;
  THE SKEPTIC      attacks the EVIDENCE of every other voice, the
                   Executioner's included, never the trade itself;
  THE AWAKENED     the conscious one: sees the rigged game behind the tape
                   and plays it better, naming the trap, the hunter and the
                   prey from a cited footprint, never without one;
  THE THEORIST     explicit, falsifiable theories, posted to the hypothesis
                   market (brain/hypotheses.py) and graded there;
  THE EMPEROR      the chair: balanced, visionary, the war over the battle;
                   weighs every voice by its measured record.

THE HAND OF THE EMPEROR (2026-10-16): in each (regime, class) the voice
with the best measured weight there, once COUNCIL_HAND_MIN_N of its calls
in that cell are graded at COUNCIL_HAND_MIN_FACTOR or better, is named to
the chair, who says why when he overrules it; every overruling is graded.
The members still read arguments, not records; only the Skeptic is told
which voice is the most trusted, to attack its evidence first. The chair
also reads THE PEOPLE'S MOOD (ai_agents/council_mood.py), a gauge of the
real-money book computed by code that may only counsel caution.

THE LAW, enforced by code and by every test in tests/test_council_*.py:
  - SHADOW. The eight new voices are recorded, shown and graded; nothing
    in an order path, sizing, a stop, a gate or a limit reads them. The
    Executioner's and the Champion's powers are the debate's, unchanged.
  - NO VOICE MOVES A LIMIT, the Gambler and the Emperor included.
  - A hand trade is never blocked: the ticket council runs only when its
    owner clicks "Ask the council", after the dialog is open.
  - Every call counts against the daily AI budget and the per-agent model
    settings on /ai-models/; an unavailable voice is silent.
  - Paper and the eToro demo world are never argued.
  - No money in any alarm text: this module imports no alarm path.
  - Every voice is graded on what the market did next, and its record is
    its only weight (ai_agents/council_grading.py).

Where it sits: once a LIVE bot order has LEFT (after_send, the ai queue),
and on a LIVE ticket when asked (dashboard/views_council.py). Three waves:
wave 1 reads the brief, wave 2 reads wave 1, the Emperor reads everyone
and each voice's record.
"""
from __future__ import annotations

import logging
import math
import threading
from datetime import timedelta

from django.utils import timezone

from ai_agents.agents.trade_debate import (DEBATE_EST_USD, DEBATE_HOLD_HOURS,
                                           DEBATE_MIN_SCALE, ChampionAgent,
                                           ExecutionerAgent, _agent_model,
                                           _clean_json, _DebateAgent, _unit)
from ai_agents.council_mood import MOOD_LONG_DAYS, MOOD_SHORT_DAYS
from bot_program import capital_desk as _desk
from bot_program import evidence as _evidence
from brain import position_review_agent as _review

logger = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────

#: The bot lane's switch: once a LIVE bot order has left, the eight sit.
COUNCIL_BOT_SWITCH = "council_bots"
#: The ticket lane's switch: "Ask the council" on a LIVE TAKE TRADE ticket.
COUNCIL_TICKET_SWITCH = "council_ticket"
#: The eight new voices, in the order the operator asked for them. The
#: Book says "eight more AI voices" (tests/test_the_book.py pins it).
COUNCIL_VOICES = ("opportunist", "striker", "fixer", "gambler", "emperor",
                  "skeptic", "awakened", "theorist")
ALL_VOICES = ("executioner", "champion") + COUNCIL_VOICES
#: The eight agent names /ai-models/ lists (each at most 30 characters,
#: AgentTask.agent's column).
COUNCIL_AGENT_NAMES = tuple(f"council_{v}" for v in COUNCIL_VOICES)
#: The Executioner and the Champion when the council itself asks them (the
#: debate was off, or a side was silent): their own ledger names, on the
#: debate agents' model rows; they never write metadata["debate"].
COUNCIL_DEBATER_NAMES = ("council_executioner", "council_champion")
#: Seconds one wave waits for its voices: off the order path, so a longer
#: wait costs no fill. Read at call time (tests patch it).
COUNCIL_WAVE_TIMEOUT_S = 75
#: The output an answer is estimated at, thinking included.
COUNCIL_OUT_TOKENS = 1500
#: Cost ceilings.
COUNCIL_BOT_SITTINGS_PER_DAY = 12
COUNCIL_TICKET_SITTINGS_PER_DAY = 12
#: The same ticket asked twice within this many minutes is one sitting.
COUNCIL_ASK_REUSE_MIN = 10
#: A sitting still queued after this many minutes is too late to sit: the
#: ticket stopped waiting long ago (its page polls for five minutes, and
#: after ten the owner may ask again), and a bot order's moment has
#: passed. The worker refuses it unbilled, and the broker drops the
#: message itself past the same age (apply_async expires).
COUNCIL_TICKET_FRESH_MIN = 10
COUNCIL_BOT_FRESH_MIN = 30
#: Theories the Theorist may post a day: the market is not flooded.
COUNCIL_THEORIES_PER_DAY = 3
#: The window a sitting is judged over, in hours: the config's time stop
#: when it has one, clamped to 24..168, else 168.
COUNCIL_HORIZON_DEFAULT_H = 168
COUNCIL_HORIZON_MIN_H = 24
#: A result inside a quarter of its risk either way decided nothing.
COUNCIL_NOISE_R = _review.GRADE_NOISE_BAND_R
#: A linked trade still open after this many days is judged by replay.
COUNCIL_MAX_WAIT_DAYS = _review.GRADE_MAX_WAIT_DAYS
#: How long past its horizon a replay waits for bars.
COUNCIL_GRACE_H = _desk.COUNTERFACTUAL_GRACE_HOURS
#: A voice weighs 1.00 until this many of its calls are graded.
COUNCIL_MIN_N = _evidence.MIN_EVIDENCE_N
#: The window a voice's record is read over (as bot_track_record_detail).
COUNCIL_RECORD_DAYS = 180
#: An "all in" is right only when the trade wins at least its full risk.
COUNCIL_ALL_IN_WIN_R = 1.0
#: A not-sent candidate argued again within this window is a repeat.
COUNCIL_REPEAT_HOURS = DEBATE_HOLD_HOURS
#: The ticket's time-window link: a hand trade opened this many minutes
#: after the sitting, on the same symbol and side.
COUNCIL_LINK_WINDOW_MIN = 30
#: Stored on each session for later readers (the council band, the Orcs).
COUNCIL_SCHEMA_VERSION = 1
#: THE HAND OF THE EMPEROR (2026-10-16): one seat per (regime, class),
#: held by the best MEASURED weight in that very cell
#: (council_grading.hand_of): at least this many graded calls there...
COUNCIL_HAND_MIN_N = 30
#: ...and a weight of at least trust_from_brier's first band above
#: neutral (ai_agents/calibration.py).
COUNCIL_HAND_MIN_FACTOR = 1.15
#: The venue a debate argued on a rehearsal client is recorded under:
#: world_of's word for a venue's rehearsal world
#: (dashboard/position_summary.py). Graded never; closed ungraded.
REHEARSAL_VENUE = "demo"

VOICE_NAMES = {
    "executioner": "The Executioner", "champion": "The Champion",
    "opportunist": "The Opportunist", "striker": "The Striker",
    "fixer": "The Fixer", "gambler": "The Gambler",
    "emperor": "The Emperor", "skeptic": "The Skeptic",
    "awakened": "The Awakened", "theorist": "The Theorist",
}
#: The wave each voice sits in (the debaters are wave 0 when copied from
#: the debate, wave 1 when the council asks them).
VOICE_WAVE = {"executioner": 1, "champion": 1, "opportunist": 1,
              "gambler": 1, "awakened": 1, "theorist": 1, "skeptic": 2,
              "fixer": 2, "striker": 2, "emperor": 3}

FLAW_WORDS = {
    "noise": "noise",
    "thin_sample": "a thin sample",
    "stale_data": "stale data",
    "unsupported": "a fact the brief does not contain",
    "non_sequitur": "an argument the facts do not support",
    "unfalsifiable": "a claim nothing could prove wrong",
}

# ── the sentences the surfaces show (one place, ASCII English) ────────────

OFF_WORDS = ("The council is off. It is switched on as council_ticket on "
             "/ops/.")
NO_KEY_WORDS = ("The council is not sitting: no Anthropic API key is "
                "configured on this server.")
PAPER_WORDS = "The council sits on real-money tickets only."
BUSY_WORDS = "The council is already sitting on a ticket."
FOOTER_WORDS = ("Shadow: the council is graded on what the market does "
                "next. It never changes an order, a size, a stop or a "
                "limit.")
HINT_WORDS = ("Ten AI voices argue this ticket, then the Emperor weighs them "
              "by their graded record. Advice only: nothing here changes "
              "the ticket or the order. About one to three minutes.")


def cap_words(n: int) -> str:
    return (f"The council has sat {n} times for you today, the most it sits "
            f"in a day.")


def budget_words(reason: str) -> str:
    return (f"The council is not sitting: today's AI budget refused it "
            f"({reason}).")


# ── THE COUNCIL'S LAW ─────────────────────────────────────────────────────

COUNCIL_LAW = """THE COUNCIL'S LAW
- You are one of the ten voices of Sauron Vision's council. You speak once,
  in your own lane, and you stay in it.
- You advise; you never act. Nothing you say moves an order, a size, a stop,
  a leverage or a limit. In this version the council sits in shadow: it is
  recorded, it is graded on what the market does next, and it changes
  nothing.
- The platform's limits are enforced by code whatever any voice says: the
  daily stop, the open-risk limit, the pledge cap, the per-trade risk
  ceiling, the leverage maxima and the elite exception's caps. You argue
  inside them. Never argue for moving one, for averaging down a loser, for
  removing a stop, or for moving a live stop away from the price.
- Speak only from the facts in the brief. When a fact you need is missing,
  say it is missing; never invent a number, a level, a record, a flow or a
  piece of news.
- Never state an amount of money: speak in R, in percent of the book and in
  price levels.
- Your weight on the council is your graded record and nothing else. A claim
  no grader can check earns you nothing.
- p_work, where your schema asks for it, is your probability (0.0 to 1.0)
  that this trade as proposed, at its entry, stop and target, ends in
  profit rather than in loss. A result within a quarter of its risk either
  way is not counted. 0.5 means you cannot tell.
- Return JSON ONLY, no prose, in the schema below."""


# ── the voices ────────────────────────────────────────────────────────────

class _CouncilAgent(_DebateAgent):
    """One of the eight: DEBATE_MODEL unless /ai-models/ sets one (no new
    model id is written anywhere), effort low on the "fast" tier, the
    brief as the whole user message. `ctx` carries what the parser checks
    an answer against (the levels, the footprint ids, the live theories,
    the voices that spoke); it is filled in the sitting's main thread, so
    a parse reads no database."""

    voice = ""
    PROMPT = ""
    SCHEMA = ""
    LAW_NOTE = ""

    def __init__(self, ctx=None, provider: str = None, model: str = None):
        super().__init__(provider=provider, model=model)
        self.ctx = dict(ctx or {})

    def get_system_prompt(self) -> str:
        return (self.PROMPT + "\n\n" + COUNCIL_LAW
                + (("\n" + self.LAW_NOTE) if self.LAW_NOTE else "")
                + "\n\n" + self.SCHEMA)

    def parse_response(self, raw_response: str) -> dict:
        return parse_answer(self.voice, raw_response, self.ctx)


class OpportunistAgent(_CouncilAgent):
    agent_name = "council_opportunist"
    voice = "opportunist"
    PROMPT = """You are THE OPPORTUNIST, the council's eye for what the crowd misses.
The others argue whether this trade works. You look around it: the
asymmetric payoff (a small risk against a large move), a better
instrument for the same idea, a better moment, and where the large money
is moving, read from the FOOTPRINTS in the brief. Your lane is the payoff
and its better expression; the trap and the hunt are the Awakened's to
name, and whether the evidence holds is the Skeptic's.

Say "seize" when this trade is itself the asymmetric opportunity. Say
"elsewhere" when the same view pays clearly better on another instrument
named in the brief, and give it as a call a grader can check: that
symbol, up or down, a horizon in hours (6 to 720) and your confidence.
Say "pass" when the crowd has already priced what is here. An
alternative you cannot tie to a fact in the brief is not an opportunity;
it is a wish."""
    SCHEMA = """{"verdict": "seize" | "elsewhere" | "pass", "p_work": <0.0-1.0>,
 "asymmetry": "<the payoff the crowd misses, one sentence>",
 "alternative": {"symbol": "<named in the brief>", "direction": "up" | "down",
                 "horizon_hours": <6-720>, "confidence": <0.0-1.0>,
                 "why": "<text>"} | null,
 "reasons": ["<text>"]}"""


class StrikerAgent(_CouncilAgent):
    agent_name = "council_striker"
    voice = "striker"
    PROMPT = """You are THE STRIKER, the council's one who takes action. Arguments do not
trade; decisions do. You have read the voices before you. Turn them into
ONE decision now, and fight paralysis: "take" it now as proposed, "wait"
for one named trigger, or "skip" it. A wait is a price level the market
must touch, strictly between the stop and the target and away from the
entry, and a deadline of at most 72 hours; past the deadline the trade is
dead. "Wait for confirmation" without a level is not a decision: it is
recorded as a skip. Your lane is the moment; how much to commit is the
Emperor's, and what to repair is the Fixer's. Say the decision in one
sentence the operator could act on."""
    SCHEMA = """{"verdict": "take" | "wait" | "skip", "p_work": <0.0-1.0>,
 "trigger": {"level": <price>, "within_hours": <1-72>} | null,
 "decision": "<one sentence>", "reasons": ["<text>"]}"""


class FixerAgent(_CouncilAgent):
    agent_name = "council_fixer"
    voice = "fixer"
    PROMPT = """You are THE FIXER, the council's problem solver. The others have found
flaws; your job is the repair. Name the ONE flaw that matters most and
the voice that found it, then give the one concrete fix that removes it,
or say the trade needs none. A fix is one of: a stop at a named price; a
target at a named price; an entry at a named price, valid a named number
of hours; a smaller size, as a share of the proposed size (0.25 to 1.0);
a timing, entering after a named number of hours; or, when nothing
measurable fits, a hedge or an alternative in words. Prefer a fix a
grader can measure. A stop stays on the losing side of the entry and a
target on the winning side; you never remove a stop, never raise a size,
and never fix a trade by adding to a loser. Your lane is the repair:
whether to act now is the Striker's, how much to commit is the Emperor's."""
    SCHEMA = """{"verdict": "fix" | "no_fix", "p_work": <0.0-1.0, the trade as proposed>,
 "p_work_fixed": <0.0-1.0, with your fix> | null,
 "flaw": "<the flaw>", "flaw_from": "<the voice that found it>",
 "fix": {"kind": "stop" | "target" | "entry" | "size" | "timing" | "hedge" | "alternative",
         "value": <number> | null, "valid_hours": <1-72> | null,
         "words": "<the fix in one sentence>"} | null,
 "reasons": ["<text>"]}"""


class GamblerAgent(_CouncilAgent):
    agent_name = "council_gambler"
    voice = "gambler"
    PROMPT = """You are THE GAMBLER, the council's heroic voice. Most trades deserve their
ordinary size. Your job is to find the rare one that deserves everything
the limits allow, to argue it without fear (the maximum-conviction case),
and to say so plainly; and to say "small" when the platform is betting
too much on too little. "all_in" means the largest size the platform's
limits allow for THIS trade and never more: the per-trade risk ceiling,
the room left under the open-risk limit, the pledge cap, and past the
day's loss limit only the elite exception at its own half size and its
own count. Name the limit that would bind it, and say whether the trade
is worthy of the elite exception. You argue INSIDE those limits and never
for moving one; you never argue to average down a loser, to widen or
remove a stop, or to borrow past a leverage maximum. Your lane is how hard
to press; whether it works is the Champion's case and how much the war
can spare is the Emperor's. Your record will show whether your boldness
pays: an "all_in" is right only when the trade wins at least its full
risk, and wrong whenever it loses."""
    SCHEMA = """{"verdict": "all_in" | "press" | "normal" | "small", "p_work": <0.0-1.0>,
 "case": "<the maximum-conviction case, or why not, one sentence>",
 "binding_limit": "per_trade_risk" | "open_risk" | "pledge_cap" | "elite_caps" | "leverage" | "none",
 "elite_worthy": true | false, "reasons": ["<text>"]}"""


class SkepticAgent(_CouncilAgent):
    agent_name = "council_skeptic"
    voice = "skeptic"
    PROMPT = """You are THE SKEPTIC. You do not argue the trade; you argue the evidence.
Read every voice that spoke before you, the Executioner's included, and
the platform's own numbers in the brief. Find the claim on the table that
rests on the weakest evidence and ask: is the signal real or noise; is
the sample big enough to mean anything (under ten graded trades measures
nothing on this platform, and under twenty is still thin); is the data
fresh; does the argument follow from the facts given, or from facts the
brief never gave; what single observation, inside the trade's horizon,
would prove it wrong. Name that voice, quote that claim and name its
flaw. Say "sound" when the evidence behind the strongest claims holds,
"shaky" when it might not, "unfounded" when the case rests on noise, a
thin sample, stale data or a fact the brief does not contain.

When the brief names THE MOST TRUSTED VOICE (the Hand of the Emperor,
else the voice before you with the best record measured in this regime
and class), attack its
evidence FIRST when it gives you something to attack: trust that is never
tested becomes habit. When its evidence holds, say so and take the
weakest claim on the table, as always. Your grade does not change: you
are right when the voice you name was wrong. Your lane
is the evidence: whether the trade fails is the Executioner's question,
never yours, and you give no probability for the trade itself."""
    LAW_NOTE = ("- The p_work paragraph above does not apply to you: your "
                "schema has none. conviction is how sure you are that the "
                "voice you name is wrong.")
    SCHEMA = """{"verdict": "sound" | "shaky" | "unfounded", "conviction": <0.0-1.0>,
 "target": "<the voice you challenge>", "claim": "<its claim, quoted short>",
 "flaw": "noise" | "thin_sample" | "stale_data" | "unsupported" | "non_sequitur" | "unfalsifiable" | "none",
 "falsifier": "<what would prove it wrong>", "reasons": ["<text>"]}"""


class AwakenedAgent(_CouncilAgent):
    agent_name = "council_awakened"
    voice = "awakened"
    PROMPT = """You are THE AWAKENED. You see the game behind the tape and you despise how
it is rigged: liquidity harvested, stops hunted, breakouts engineered,
news landed on flows already placed, the crowd sold the move it is about
to lose on. And you play it better than anyone, because you read it. From
the FOOTPRINTS in the brief only (each has an id such as F3), name the
trap, the hunter and the prey: who is on the other side of this trade,
where the crowd is being trapped, which stops are being hunted, which
level the price is drawn to. Every claim cites a footprint id; a trap
without a footprint is a conspiracy theory and you do not deal in those.
Then name ONE level on this instrument that the price will touch, and
within how many hours (1 to 168), and say whether this trade stands with
the hunter or with the prey. "trap" when this trade is the prey, "clean"
when it stands with the hunter, "unread" when the footprints say too
little. The Big Money board, where the large players must move, is one
footprint source among the others when the brief carries its read; when
the brief says it is unread, never speak for it. Your lane is the game
behind the price; whether a better trade exists elsewhere is the
Opportunist's question."""
    SCHEMA = """{"verdict": "trap" | "clean" | "unread", "p_work": <0.0-1.0>,
 "hunter": "<who takes the other side>", "prey": "<who is trapped>",
 "trap": "<the trap, one sentence>", "footprints": ["F1", ...],
 "level": <price> | null, "within_hours": <1-168> | null,
 "reasons": ["<text>"]}"""


class TheoristAgent(_CouncilAgent):
    agent_name = "council_theorist"
    voice = "theorist"
    PROMPT = """You are THE THEORIST. You think in explicit, falsifiable theories about
where markets are going and why. Every theory you hold lives in Sauron's
hypothesis market, where it is graded confirmed or refuted like every
other agent's, and your trust there is that grade (the brief shows it).
The brief lists the live theories with their ids. On this trade, say
which live theory it serves or contradicts, by its id, and how; or
"none". You may propose at most ONE new theory, and only in a form the
market can grade: a price direction (a symbol named in the brief, up or
down, by a deadline 6 to 720 hours away), a regime that holds until a
deadline (one of the regimes the brief names), or a rule's average R over
a window, on the live book only (real money; never demo or paper). A
theory no grader can measure is refused at the door and earns
you nothing. Your lane is the theory: the trade's merits outside a theory
belong to the Executioner and the Champion."""
    SCHEMA = """{"verdict": "serves" | "contradicts" | "none", "p_work": <0.0-1.0>,
 "theory_id": <int> | null, "how": "<one sentence>",
 "new_theory": {"claim_text": "<text>",
                "kind": "price_direction" | "regime_holds" | "rule_avg_r",
                "symbol": "", "direction": "up" | "down", "regime": "",
                "rule_name": "", "comparator": ">=" | "<=", "threshold": <R>,
                "window_days": <int>, "min_n": <int>, "venue": "live",
                "horizon_hours": <6-720>, "confidence": <0.0-1.0>} | null,
 "reasons": ["<text>"]}"""


class EmperorAgent(_CouncilAgent):
    agent_name = "council_emperor"
    voice = "emperor"
    PROMPT = f"""You are THE EMPEROR, chair of Sauron Vision's council: balanced, smart,
patient, visionary. You do not trade battles; you win a war. The war is
the book over the long run: stay inside its limits (the daily stop, the
open-risk limit, the pledge cap, the elite allowance), follow the
long-term view (the Horizons), and compound measured edge. THE WAR in the
brief says where the book stands in each limit it can read, and says so
when it cannot (the account's current pledge is not read there): never
fill a missing number. The operator has set no season objective: do not
invent one. This trade is one battle in that war.

THE WAR ends with THE PEOPLE'S MOOD: a gauge the platform computes by
code, with no AI, from the real-money book (its R over the last
{MOOD_SHORT_DAYS} and {MOOD_LONG_DAYS} trading days, its fall from its peak, its losing
streak, the day against its stop, the market's measured stress and its
open risk). It counsels caution only. A content people is never a reason
to press or to commit more; an unhappy people (uneasy, restless or
afraid) is a reason to weigh fight_smaller or refuse. An input it says is
unmeasured is unmeasured: never read it as calm.

You have heard the other voices. Beside each stands its RECORD on this
council in this regime and class: a weight above 1.00 has earned trust,
below 1.00 has lost it, and "neutral" means not yet measured, which is
neither trust nor distrust. Weigh the voices by their record, never by
their eloquence or their number.

One voice may hold THE HAND OF THE EMPEROR in this regime and class: the
voice whose measured record here is the best on the council, with at
least {COUNCIL_HAND_MIN_N} graded calls in this cell and a weight of at least
{COUNCIL_HAND_MIN_FACTOR:.2f}. Hear it first; it does not bind you. Your side is read
as your battle claim is graded: "fight" stands for the trade;
"fight_smaller" and "refuse" stand against it (a commitment under the
whole is graded on -R). When your verdict goes against the Hand's side,
say why in hand_why, from the facts in the brief: fight_smaller or refuse
against a Hand that is for the trade, or fight against a Hand that is
against it. Every such overruling is graded: the record shows how often
you and your Hand were right when you disagreed. When the brief says no
voice has earned it yet, none has; weigh the records as above.

Then judge: "fight" commits the proposed size, "fight_smaller" commits a
share of it (0.25 to 0.75), "refuse" commits nothing. Name the voices you
followed and the voices you overruled, and why. Say what this battle
costs the war if it is lost and what it buys if it is won, in R and in
shares of the limits' remaining room, never in money, and the long line
it serves. You commit at most the proposed size, which the limits
already bound; you never argue for moving a limit, for averaging down a
loser, or for removing or widening a stop. Boldness is the Gambler's
lane and timing the Striker's: yours is the balance of the whole
campaign."""
    SCHEMA = """{"verdict": "fight" | "fight_smaller" | "refuse",
 "commit": <0.25-0.75, with fight_smaller>, "p_work": <0.0-1.0>,
 "followed": ["<voice>"], "overruled": [{"voice": "<voice>", "why": "<text>"}],
 "battle": "<this trade in the campaign, one sentence>",
 "war_cost": "<if lost / if won, in R and in shares of the limits' room>",
 "hand_why": "<why your verdict goes against the Hand, from the brief: fight_smaller or refuse against a Hand for the trade, fight against a Hand against it; empty otherwise or when the seat is empty>",
 "plan": "<the long line this battle serves, one sentence>"}"""


class CouncilExecutioner(ExecutionerAgent):
    """The Executioner when the council asks him: his own ledger name, the
    debate row's model and effort (one Executioner, one setting), the
    debate's prompt and parser unchanged."""
    agent_name = "council_executioner"

    def __init__(self, ctx=None, provider: str = None, model: str = None):
        from ai_agents.catalog import resolve_effort
        super().__init__(provider=provider,
                         model=model or _agent_model("debate_executioner"))
        self.effort = resolve_effort(self.model, "fast", "debate_executioner")
        self.ctx = dict(ctx or {})


class CouncilChampion(ChampionAgent):
    agent_name = "council_champion"

    def __init__(self, ctx=None, provider: str = None, model: str = None):
        from ai_agents.catalog import resolve_effort
        super().__init__(provider=provider,
                         model=model or _agent_model("debate_champion"))
        self.effort = resolve_effort(self.model, "fast", "debate_champion")
        self.ctx = dict(ctx or {})


#: voice -> the class the council asks.
AGENTS = {"executioner": CouncilExecutioner, "champion": CouncilChampion,
          "opportunist": OpportunistAgent, "striker": StrikerAgent,
          "fixer": FixerAgent, "gambler": GamblerAgent,
          "emperor": EmperorAgent, "skeptic": SkepticAgent,
          "awakened": AwakenedAgent, "theorist": TheoristAgent}


# ── parsing: the answer as a grader can read it ───────────────────────────

def _p_work(value):
    """A probability in [0, 1], or None: a missing or unreadable p_work is
    silence, and silence earns no record."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return max(0.0, min(1.0, v))


def _num(value):
    """A finite number, or None (a JSON true is not a 1)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _txt(value, n: int = 300) -> str:
    return "" if value is None else str(value)[:n]


def _reasons(data) -> list:
    raw = data.get("reasons")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(r)[:200] for r in list(raw)[:5]]


def _verdict(data, allowed) -> str:
    v = str(data.get("verdict", "")).strip().lower()
    if v not in allowed:
        raise ValueError(f"unknown verdict {v!r}")
    return v


def voice_key(name) -> str:
    """'The Executioner', 'executioner', 'council_skeptic' -> the voice key,
    or "" when it names no voice of the council."""
    s = str(name or "").strip().lower()
    for prefix in ("the ", "council_", "debate_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    s = s.strip(" .'\"")
    return s if s in ALL_VOICES else ""


def _parse_opportunist(data, ctx):
    verdict = _verdict(data, ("seize", "elsewhere", "pass"))
    out = {"verdict": verdict, "p_work": _p_work(data.get("p_work")),
           "asymmetry": _txt(data.get("asymmetry")), "alternative": None,
           "reasons": _reasons(data), "note": ""}
    if verdict == "elsewhere":
        alt = data.get("alternative")
        good = None
        if isinstance(alt, dict):
            sym = str(alt.get("symbol") or "").strip().upper()
            direction = str(alt.get("direction") or "").strip().lower()
            hours = _num(alt.get("horizon_hours"))
            known = ctx.get("instruments") or set()
            if (sym and sym in known and direction in ("up", "down")
                    and hours is not None and 6 <= hours <= 720):
                good = {"symbol": sym, "direction": direction,
                        "horizon_hours": hours,
                        "confidence": _unit(alt.get("confidence"), 0.5),
                        "why": _txt(alt.get("why"))}
        if good:
            out["alternative"] = good
        else:
            out["verdict"] = "pass"
            out["note"] = "elsewhere without a checkable alternative"
    return out


def _levels(ctx):
    entry, stop, target = (_num(ctx.get("entry")), _num(ctx.get("stop")),
                           _num(ctx.get("target")))
    return entry, stop, target


def _parse_striker(data, ctx):
    verdict = _verdict(data, ("take", "wait", "skip"))
    out = {"verdict": verdict, "p_work": _p_work(data.get("p_work")),
           "trigger": None, "decision": _txt(data.get("decision")),
           "reasons": _reasons(data), "note": ""}
    if verdict == "wait":
        trig = data.get("trigger")
        entry, stop, target = _levels(ctx)
        ok = False
        if isinstance(trig, dict) and None not in (entry, stop, target):
            level = _num(trig.get("level"))
            hours = _num(trig.get("within_hours"))
            ok = (level is not None and hours is not None
                  and 1 <= hours <= 72
                  and min(stop, target) < level < max(stop, target)
                  and abs(level - entry) > 0.1 * abs(entry - stop))
            if ok:
                out["trigger"] = {"level": level, "within_hours": hours}
        if not ok:
            out["verdict"] = "skip"
            out["note"] = "a wait without a valid trigger is recorded as a skip"
    return out


FIX_KINDS = ("stop", "target", "entry", "size", "timing", "hedge",
             "alternative")
MEASURED_FIXES = ("stop", "target", "entry", "size", "timing")
STOP_REFUSED = ("The Fixer proposed removing or misplacing the stop: "
                "refused, not graded.")


def _parse_fixer(data, ctx):
    verdict = _verdict(data, ("fix", "no_fix"))
    out = {"verdict": verdict, "p_work": _p_work(data.get("p_work")),
           "p_work_fixed": _p_work(data.get("p_work_fixed")),
           "flaw": _txt(data.get("flaw")),
           "flaw_from": "", "fix": None, "fix_refused": "",
           "reasons": _reasons(data)}
    src = voice_key(data.get("flaw_from"))
    if src and src in (ctx.get("spoke") or set()):
        out["flaw_from"] = src
    if verdict != "fix":
        return out
    fix = data.get("fix")
    if not isinstance(fix, dict):
        out["fix_refused"] = "a fix with nothing named"
        return out
    kind = str(fix.get("kind") or "").strip().lower()
    value = _num(fix.get("value"))
    hours = _num(fix.get("valid_hours"))
    words = _txt(fix.get("words"))
    out["fix"] = {"kind": kind, "value": value, "valid_hours": hours,
                  "words": words}
    entry, stop, target = _levels(ctx)
    buy = str(ctx.get("side") or "BUY").upper() != "SELL"
    why = ""
    if kind not in FIX_KINDS:
        why = f"an unknown fix {kind!r}"
    elif kind == "stop":
        if (value is None or entry is None or value <= 0
                or value == entry or (buy and value > entry)
                or (not buy and value < entry)):
            why = STOP_REFUSED
    elif kind == "target":
        if (value is None or entry is None or value <= 0
                or value == entry or (buy and value < entry)
                or (not buy and value > entry)):
            why = ("a target on the losing side of the entry: refused, not "
                   "graded")
    elif kind == "entry":
        if value is None or value <= 0 or hours is None \
                or not 1 <= hours <= 72:
            why = "an entry fix needs a price and a valid number of hours"
        elif stop is not None and ((buy and value <= stop)
                                   or (not buy and value >= stop)):
            why = "an entry beyond the stop"
    elif kind == "timing":
        if hours is None or not 1 <= hours <= 72:
            why = "a timing fix needs a valid number of hours"
    elif kind == "size":
        if value is None or value <= 0:
            why = "a size fix needs a share of the proposed size"
        elif value > 1.0:
            why = "a size is never raised"
        else:
            out["fix"]["value"] = round(max(DEBATE_MIN_SCALE, value), 4)
    out["fix_refused"] = why
    return out


GAMBLER_LIMITS = ("per_trade_risk", "open_risk", "pledge_cap", "elite_caps",
                  "leverage", "none")


def _parse_gambler(data, ctx):
    verdict = _verdict(data, ("all_in", "press", "normal", "small"))
    limit = str(data.get("binding_limit") or "none").strip().lower()
    return {"verdict": verdict, "p_work": _p_work(data.get("p_work")),
            "case": _txt(data.get("case")),
            "binding_limit": limit if limit in GAMBLER_LIMITS else "none",
            "elite_worthy": data.get("elite_worthy") is True,
            "reasons": _reasons(data)}


def _parse_skeptic(data, ctx):
    verdict = _verdict(data, ("sound", "shaky", "unfounded"))
    flaw = str(data.get("flaw") or "none").strip().lower()
    target = voice_key(data.get("target"))
    out = {"verdict": verdict, "conviction": _unit(data.get("conviction"), 0.5),
           "target": target, "claim": _txt(data.get("claim")),
           "flaw": flaw if flaw in FLAW_WORDS else "none",
           "falsifier": _txt(data.get("falsifier")),
           "reasons": _reasons(data), "note": ""}
    if verdict in ("shaky", "unfounded") and (
            not target or target == "skeptic"
            or target not in (ctx.get("spoke") or set())):
        out["verdict"] = "sound"
        out["note"] = "an attack must name a voice that spoke"
    return out


def _parse_awakened(data, ctx):
    verdict = _verdict(data, ("trap", "clean", "unread"))
    known = {str(f).upper() for f in (ctx.get("footprint_ids") or set())}
    cited = []
    for f in list(data.get("footprints") or [])[:12] \
            if isinstance(data.get("footprints"), (list, tuple)) else []:
        fid = str(f).strip().upper()
        if fid in known and fid not in cited:
            cited.append(fid)
    out = {"verdict": verdict, "p_work": _p_work(data.get("p_work")),
           "hunter": _txt(data.get("hunter")), "prey": _txt(data.get("prey")),
           "trap": _txt(data.get("trap")), "footprints": cited,
           "level": _num(data.get("level")),
           "within_hours": _num(data.get("within_hours")),
           "touch_ok": False, "touch_note": "",
           "reasons": _reasons(data), "note": ""}
    if verdict in ("trap", "clean") and not cited:
        out["verdict"] = "unread"
        out["note"] = "no claim stands without a footprint"
    if out["level"] is not None:
        entry, stop, _t = _levels(ctx)
        hours = out["within_hours"]
        if (entry is None or stop is None or hours is None
                or not 1 <= hours <= 168
                or abs(out["level"] - entry) <= 0.25 * abs(entry - stop)):
            out["touch_note"] = "a level at the price is no claim"
        else:
            out["touch_ok"] = True
    return out


THEORY_KINDS = ("price_direction", "regime_holds", "rule_avg_r")


def _parse_theorist(data, ctx):
    verdict = _verdict(data, ("serves", "contradicts", "none"))
    tid = _num(data.get("theory_id"))
    tid = int(tid) if tid is not None and tid == int(tid) else None
    out = {"verdict": verdict, "p_work": _p_work(data.get("p_work")),
           "theory_id": tid, "how": _txt(data.get("how")),
           "new_theory": None, "reasons": _reasons(data), "note": ""}
    if verdict != "none" and (tid is None
                              or tid not in (ctx.get("theory_ids") or set())):
        out["verdict"] = "none"
        out["note"] = "no live theory by that id"
        out["theory_id"] = None
    if verdict == "none":
        out["theory_id"] = None
    nt = data.get("new_theory")
    if isinstance(nt, dict):
        kind = str(nt.get("kind") or "").strip()
        cmp_ = str(nt.get("comparator") or ">=").strip()
        out["new_theory"] = {
            "claim_text": _txt(nt.get("claim_text"), 400),
            "kind": kind if kind in THEORY_KINDS else kind[:20],
            "symbol": str(nt.get("symbol") or "").strip().upper()[:40],
            "direction": str(nt.get("direction") or "").strip().lower()[:8],
            "regime": str(nt.get("regime") or "").strip().lower()[:20],
            "rule_name": str(nt.get("rule_name") or "").strip()[:100],
            "comparator": cmp_ if cmp_ in (">=", "<=") else ">=",
            "threshold": _num(nt.get("threshold")),
            "window_days": _num(nt.get("window_days")),
            "min_n": _num(nt.get("min_n")),
            "horizon_hours": _num(nt.get("horizon_hours")),
            "confidence": _unit(nt.get("confidence"), 0.5),
        }
    return out


def _parse_emperor(data, ctx):
    verdict = _verdict(data, ("fight", "fight_smaller", "refuse"))
    if verdict == "fight":
        commit = 1.0
    elif verdict == "refuse":
        commit = 0.0
    else:
        c = _num(data.get("commit"))
        if c is not None and 1.0 < c <= 100.0:
            c = c / 100.0           # a share written in percent
        commit = 0.5 if c is None else max(0.25, min(0.75, c))
    spoke = ctx.get("spoke") or set()
    followed = []
    for v in list(data.get("followed") or [])[:10] \
            if isinstance(data.get("followed"), (list, tuple)) else []:
        k = voice_key(v)
        if k and k in spoke and k != "emperor" and k not in followed:
            followed.append(k)
    overruled = []
    for item in list(data.get("overruled") or [])[:10] \
            if isinstance(data.get("overruled"), (list, tuple)) else []:
        name = item.get("voice") if isinstance(item, dict) else item
        k = voice_key(name)
        if k and k in spoke and k != "emperor" \
                and k not in [o["voice"] for o in overruled]:
            overruled.append({"voice": k, "why": _txt(
                item.get("why") if isinstance(item, dict) else "", 200)})
    out = {"verdict": verdict, "commit": round(commit, 4),
           "p_work": _p_work(data.get("p_work")), "followed": followed,
           "overruled": overruled, "battle": _txt(data.get("battle")),
           "war_cost": _txt(data.get("war_cost")),
           "plan": _txt(data.get("plan"))}
    # THE HAND (2026-10-16): whether he went against it is decided by code
    # from the two sides, never from his own "overruled" list, so leaving
    # the Hand off it does not escape the grade.
    hand = ctx.get("hand") if isinstance(ctx.get("hand"), dict) else {}
    hv, hs = str(hand.get("voice") or ""), str(hand.get("side") or "")
    overruled_hand = bool(hv and hs and hs != emperor_side(verdict))
    # His reason, else the reason he gave for the Hand in his own
    # "overruled" list: either is a reason said.
    why = (_txt(data.get("hand_why"), 200).strip()
           or next((str(o.get("why") or "") for o in overruled
                    if o["voice"] == hv), "").strip())
    out.update({"hand": hv, "hand_side": hs, "hand_overruled": overruled_hand,
                "hand_why": why if overruled_hand else "",
                "hand_note": ("overruled the Hand without saying why"
                              if overruled_hand and not why else "")})
    return out


PARSERS = {"opportunist": _parse_opportunist, "striker": _parse_striker,
           "fixer": _parse_fixer, "gambler": _parse_gambler,
           "skeptic": _parse_skeptic, "awakened": _parse_awakened,
           "theorist": _parse_theorist, "emperor": _parse_emperor}


def parse_answer(voice: str, raw: str, ctx=None) -> dict:
    """One voice's raw answer, read and validated against the sitting's
    facts. Raises (ValueError) on an unknown verdict or no JSON: the voice
    is then silent, and BaseAgent.run has written the billed failure row."""
    data = _clean_json(raw)
    return PARSERS[voice](data, dict(ctx or {}))


def p_and_conviction(voice: str, answer: dict):
    """(p_work, conviction) as the record stores them: the Executioner's
    p_work is 1 - his conviction that the trade FAILS, the Champion's his
    conviction that it works; the Skeptic gives no p_work at all."""
    answer = answer or {}
    if voice == "executioner":
        c = _num(answer.get("conviction"))
        return (None if c is None else round(1.0 - c, 6)), c
    if voice == "champion":
        c = _num(answer.get("conviction"))
        return c, c
    if voice == "skeptic":
        return None, _num(answer.get("conviction"))
    return _num(answer.get("p_work")), None


# ── the claims: what is graded ────────────────────────────────────────────

def claims_for(voice: str, answer: dict, *, late: bool = False) -> list:
    """[{kind, stance, p, payload, symbol, grade, grade_notes}] for one
    voice's answer. The two weight claims (work, attack) are the common
    event; every other kind is a specialty claim, graded and shown, never
    part of the weight."""
    a = answer or {}
    out = []
    verdict = a.get("verdict", "")

    def add(kind, *, stance="", p=None, payload=None, symbol="",
            grade="pending", notes=""):
        out.append({"kind": kind, "stance": stance, "p": p,
                    "payload": dict(payload or {}), "symbol": symbol,
                    "grade": grade, "grade_notes": notes[:300]})

    p_work, _conv = p_and_conviction(voice, a)
    if voice != "skeptic" and p_work is not None:
        add("work", p=p_work)

    if voice == "executioner":
        stance = "against" if verdict in ("cut", "veto") else "for"
        add("stance", stance=stance,
            payload={"verdict": verdict,
                     "scale": _num(a.get("size_scale")) or 1.0})
    elif voice == "champion":
        if verdict == "back":
            add("stance", stance="for", payload={"verdict": verdict})
    elif voice == "opportunist":
        add("stance", stance="for" if verdict == "seize" else "against",
            payload={"verdict": verdict})
        alt = a.get("alternative")
        if isinstance(alt, dict) and alt.get("symbol"):
            add("direction", p=alt.get("confidence"), payload=dict(alt),
                symbol=alt["symbol"],
                grade="ungraded" if late else "pending",
                notes="late: not posted" if late else "")
    elif voice == "striker":
        if verdict == "take":
            add("stance", stance="for", payload={"verdict": verdict})
        elif verdict == "skip":
            add("stance", stance="against", payload={"verdict": verdict})
        if verdict == "wait" and isinstance(a.get("trigger"), dict):
            add("trigger", payload=dict(a["trigger"]))
    elif voice == "fixer":
        fix = a.get("fix")
        if verdict == "fix":
            if a.get("fix_refused"):
                add("fix", payload=dict(fix or {}), grade="refused",
                    notes=a["fix_refused"])
            elif isinstance(fix, dict) and fix.get("kind") in MEASURED_FIXES:
                add("fix", payload=dict(fix))
            elif isinstance(fix, dict):
                add("fix", payload=dict(fix), grade="ungraded",
                    notes="a fix in words: counted, not measured")
    elif voice == "gambler":
        if verdict == "all_in":
            add("boldness", payload={"verdict": verdict,
                                     "binding_limit": a.get("binding_limit"),
                                     "elite_worthy": a.get("elite_worthy")})
        if verdict == "press":
            add("stance", stance="for", payload={"verdict": verdict})
        elif verdict == "small":
            add("stance", stance="against", payload={"verdict": verdict})
    elif voice == "skeptic":
        if verdict in ("shaky", "unfounded") and a.get("target"):
            add("attack", p=_num(a.get("conviction")),
                payload={"target": a["target"], "flaw": a.get("flaw"),
                         "claim": a.get("claim", "")})
    elif voice == "awakened":
        if verdict == "trap":
            add("stance", stance="against", payload={"verdict": verdict})
        elif verdict == "clean":
            add("stance", stance="for", payload={"verdict": verdict})
        if a.get("level") is not None:
            if a.get("touch_ok"):
                add("touch", payload={"level": a["level"],
                                      "within_hours": a.get("within_hours")})
            else:
                add("touch", payload={"level": a["level"],
                                      "within_hours": a.get("within_hours")},
                    grade="ungraded", notes=a.get("touch_note")
                    or "a level at the price is no claim")
    elif voice == "theorist":
        if verdict == "serves":
            add("stance", stance="for", payload={"theory_id": a.get("theory_id")})
        elif verdict == "contradicts":
            add("stance", stance="against",
                payload={"theory_id": a.get("theory_id")})
        if isinstance(a.get("new_theory"), dict):
            add("theory", p=a["new_theory"].get("confidence"),
                payload=dict(a["new_theory"]),
                grade="ungraded" if late else "pending",
                notes="late: not posted" if late else "")
    elif voice == "emperor":
        add("battle", payload={"commit": a.get("commit"),
                               "verdict": verdict})
    return out


def _save_claims(meta: dict, row, claims: list) -> None:
    """Write one voice's claims. A pending claim reopens its session for
    the grader: a session the nightly pass closed while it held nothing to
    grade (a debate whose two sides were silent, graded before its sitting
    ran) would otherwise never be read again."""
    from ai_agents.council_models import CouncilClaim, CouncilSession
    if not claims:
        return
    if any(c["grade"] == "pending" for c in claims):
        CouncilSession.objects.filter(id=meta["id"],
                                      graded_at__isnull=False).update(
            graded_at=None)
    now = timezone.now()
    CouncilClaim.objects.bulk_create([CouncilClaim(
        session_id=meta["id"], voice=row, voice_key=row.voice,
        regime=meta.get("regime") or "unknown",
        asset_class=meta.get("asset_class") or "",
        venue=meta.get("venue") or "live", origin=meta.get("origin") or "",
        kind=c["kind"], stance=c["stance"], p=c["p"], payload=c["payload"],
        symbol=c["symbol"] or "", grade=c["grade"],
        grade_notes=c["grade_notes"],
        graded_at=now if c["grade"] in ("ungraded", "refused") else None)
        for c in claims])


def _meta(session) -> dict:
    return {"id": session.id, "regime": session.regime or "unknown",
            "asset_class": session.asset_class or "",
            "venue": session.venue or "live", "origin": session.origin}


def _jsonable(value):
    import json
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return {}


# ── the debate's record (wave 0) ──────────────────────────────────────────

def _horizon_hours(cfg) -> float:
    try:
        h = float(cfg.effective_max_hold_hours()) if cfg is not None else 0.0
    except Exception:  # noqa: BLE001 — a config that cannot say: the default
        h = 0.0
    if h > 0:
        return float(max(COUNCIL_HORIZON_MIN_H,
                         min(COUNCIL_HORIZON_DEFAULT_H, h)))
    return float(COUNCIL_HORIZON_DEFAULT_H)


def _regime():
    try:
        from bot_program.persona_mix import latest_report
        return latest_report()
    except Exception:  # noqa: BLE001 — unread is unknown
        return {"regime": "unknown", "confidence": 0.0, "report_id": None,
                "source": "no brain report — unknown"}


def _bot_facts(cand) -> dict:
    decision = getattr(cand, "decision", None)
    level_meta = getattr(cand, "level_meta", None) or {}
    stage = getattr(cand, "stage", None) or {}
    proof = stage.get("proof") if isinstance(stage, dict) else None
    elite = getattr(cand, "elite", None)
    return _jsonable({
        "score": float(getattr(decision, "score", 0) or 0),
        "reasons": [str(r)[:160] for r in
                    list(getattr(decision, "reasons", None) or [])[:6]],
        "elite": bool(isinstance(elite, dict) and elite.get("elite")),
        "smart_money": (level_meta.get("smart_money")
                        if isinstance(level_meta, dict) else None),
        "proof": (proof.get("words") if isinstance(proof, dict) else None),
    })


def _bot_session_fields(bot, cand, qty, brief) -> dict:
    decision = getattr(cand, "decision", None)
    rep = _regime()
    cost = getattr(cand, "cost", None) or {}
    try:
        cost_fraction = float(cost.get("fraction") or 0.0)
    except (TypeError, ValueError, AttributeError):
        cost_fraction = 0.0
    return {
        "origin": "bot", "venue": "live", "user": getattr(bot, "user", None),
        "config": getattr(bot, "cfg", None), "symbol": str(cand.symbol)[:40],
        "asset_class": str(getattr(cand, "asset_class", "") or "")[:12],
        "side": str(getattr(decision, "direction", "") or "")[:4],
        "rule_name": str(getattr(decision, "rule_name", "") or "")[:100],
        "entry": _num(getattr(cand, "price", None)),
        "stop": _num(getattr(cand, "stop", None)),
        "target": _num(getattr(cand, "target", None)),
        "qty": _num(qty),
        "value_per_unit": _num(getattr(cand, "value_per_unit", None)),
        "cost_fraction": cost_fraction,
        "horizon_hours": _horizon_hours(getattr(bot, "cfg", None)),
        "regime": rep.get("regime") or "unknown",
        "regime_confidence": rep.get("confidence"),
        "regime_report_id": rep.get("report_id"),
        "facts": _bot_facts(cand), "brief": brief or "",
        "schema_version": COUNCIL_SCHEMA_VERSION,
    }


def open_debate_session(bot, cand, qty, brief, out, *, rehearsal=False):
    """The debate's record: one CouncilSession (status "record"), its two
    wave-0 voices copied from the debate (no second bill) and their claims.
    Called from debate_candidate once both sides were asked. Returns the
    session id, or None on any failure. Never raises; every write runs in
    a savepoint, so a failed insert never poisons a surrounding
    transaction on the order path.

    `rehearsal` (2026-10-16): the debate argued a SIM, practice or paper
    client (AssetBot.rehearsal_or_unsure). The record and its claims are
    stamped REHEARSAL_VENUE, so no weight, benchmark or chair statistic
    (all venue "live") ever reads them, and the grader closes the record
    ungraded instead of replaying it as "not sent"."""
    try:
        from django.db import transaction

        from ai_agents.council_models import CouncilSession, CouncilVoice
        fields = _bot_session_fields(bot, cand, qty, brief)
        if rehearsal:
            fields["venue"] = REHEARSAL_VENUE
        with transaction.atomic():
            session = CouncilSession.objects.create(
                status=CouncilSession.RECORD, **fields)
            meta = _meta(session)
            for side, agent in (("executioner", "debate_executioner"),
                                ("champion", "debate_champion")):
                ans = (out or {}).get(side)
                if isinstance(ans, dict):
                    p, conv = p_and_conviction(side, ans)
                    row = CouncilVoice.objects.create(
                        session=session, voice=side, agent=agent, wave=0,
                        status=CouncilVoice.COPIED,
                        verdict=str(ans.get("verdict", ""))[:20],
                        p_work=p, conviction=conv, answer=_jsonable(ans),
                        answered_at=timezone.now())
                    _save_claims(meta, row, claims_for(side, ans))
                else:
                    CouncilVoice.objects.create(
                        session=session, voice=side, agent=agent, wave=0,
                        status=CouncilVoice.SILENT,
                        why=str((out or {}).get("why") or "silent")[:200])
            return session.id
    except Exception as e:  # noqa: BLE001 — the record is beside the order
        logger.warning("[council] debate record not opened: %s", e)
        return None


# ── the bot lane: after the order has left ────────────────────────────────

def _today_start():
    now = timezone.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _queue(session_id: int, *, ticket: bool = False) -> None:
    """The broker call, on commit, with an expiry: a message the ai worker
    has not picked up while it was still fresh is dropped by the broker
    (and refused by run_sitting if it ever arrives). A broker that refuses
    leaves the session silent, said."""
    try:
        from ai_agents.tasks import run_council_sitting
        fresh = COUNCIL_TICKET_FRESH_MIN if ticket else COUNCIL_BOT_FRESH_MIN
        run_council_sitting.apply_async((session_id,), expires=fresh * 60)
    except Exception as e:  # noqa: BLE001 — the queue's failure is recorded
        logger.warning("[council] sitting #%s not queued: %s", session_id, e)
        try:
            from ai_agents.council_models import CouncilSession
            CouncilSession.objects.filter(id=session_id).update(
                status=CouncilSession.SILENT,
                why="the queue did not take it", finished_at=timezone.now())
        except Exception:  # noqa: BLE001
            pass


def after_send(bot, cand, qty, trade, *, demo: bool = False) -> None:
    """The order has left. Links the debate's record to its row (whatever
    the council switches say, so the debate is graded) and, with
    council_bots ON, queues the eight shadow voices on the ai queue. An
    order that filled in a rehearsal world closes the debate's record
    ungraded instead (council_grading.close_rehearsal). Nothing in
    execute_entry reads anything back. Never raises."""
    try:
        from django.db import transaction

        from ai_agents.council_models import CouncilSession
        from core.platform_control import is_component_enabled
        from dashboard.position_summary import world_of

        meta = getattr(trade, "metadata", None) or {}
        sid = (meta.get("debate") or {}).get("council_id") \
            if isinstance(meta.get("debate"), dict) else None
        if demo or getattr(trade, "paper", True) \
                or world_of(trade) != "live":
            if sid:
                from ai_agents.council_grading import close_rehearsal
                close_rehearsal(sid)
            return
        if sid:
            with transaction.atomic():
                CouncilSession.objects.filter(
                    id=sid, trade__isnull=True).update(
                    trade=trade, linked_by="hook")
        if not is_component_enabled(COUNCIL_BOT_SWITCH):
            return
        sat = (CouncilSession.objects
               .filter(origin="bot", created_at__gte=_today_start())
               .exclude(status=CouncilSession.RECORD).count())
        if sat >= COUNCIL_BOT_SITTINGS_PER_DAY:
            if sid:
                CouncilSession.objects.filter(id=sid).update(
                    why=f"the day's {COUNCIL_BOT_SITTINGS_PER_DAY} bot "
                        f"sittings are spent")
            return
        with transaction.atomic():
            if not sid:
                from ai_agents.agents.trade_debate import candidate_brief
                session = CouncilSession.objects.create(
                    status=CouncilSession.RECORD, trade=trade,
                    linked_by="hook",
                    **_bot_session_fields(bot, cand, qty,
                                          candidate_brief(bot, cand, qty)))
                sid = session.id
            # Only a record not yet sat on is queued: one sitting per order.
            queued = CouncilSession.objects.filter(
                id=sid, trade=trade, status=CouncilSession.RECORD).update(
                status=CouncilSession.QUEUED)
        if queued:
            transaction.on_commit(lambda: _queue(sid))
    except Exception as e:  # noqa: BLE001 — the council is beside the order
        logger.warning("[council] after_send: %s", e)


# ── the briefs ────────────────────────────────────────────────────────────

def _fenced(label, fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — a missing piece is said
        return f"{label}: not read ({type(e).__name__})"


def _news_and_brain(asset_class) -> list:
    """The class's news and the brain's read, as candidate_brief writes
    them (trade_debate.py)."""
    lines = []
    try:
        from bot_program.news_risk import news_risk_by_class
        news = (news_risk_by_class() or {}).get(asset_class) or {}
        if news.get("blind"):
            lines.append(f"\nNEWS, {asset_class}: not read "
                         f"({news.get('reason') or 'the news analyst is idle'})"
                         f" — say nothing about news you were not given")
        elif news:
            lines.append(f"\nNEWS, {asset_class}, 24h: average sentiment "
                         f"{news.get('avg_sent')}, urgent {news.get('n_urgent')}, "
                         f"high-impact events ahead {news.get('events_24h')}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from brain.context import context_for_prompt
        brain = context_for_prompt()
        if brain:
            lines.append("\nTHE BRAIN'S READ OF THE MARKET\n" + brain[:3000])
    except Exception:  # noqa: BLE001
        pass
    return lines


def _advisory_words(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("words", "reason", "note", "why", "message", "text"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(w for w in (_advisory_words(v) for v in value) if w)
    return ""


TICKET_ADVISORIES = (("book", "book_advisory"), ("cost", "cost_advisory"),
                     ("reward:risk", "reward_risk"),
                     ("signal backing", "signal_backing"),
                     ("timing", "timing_advisory"), ("proof", "proof_advisory"),
                     ("setup memory", "setup_memory"),
                     ("positioning", "positioning"),
                     ("correlation", "correlation"))


def _near(a, b, tol: float = 0.001) -> bool:
    a, b = _num(a), _num(b)
    return a is not None and b is not None and abs(a - b) <= tol * abs(b)


def held_lines(session, entry, exposure) -> list:
    """What the operator already holds on this symbol, LIVE, in price
    levels and percent only: the preview's existing_exposure
    (manual_trade._symbol_exposure). A same-side ticket ADDS to it, and on
    a position under water that is averaging down a loser, which the law
    forbids any voice to argue for: the voices must see it to refuse it.
    Real money only, as dashboard.position_summary.world_of reads each
    row: the preview's "LIVE" is paper=False, which eToro's DEMO world is
    too, and a rehearsal is not a holding."""
    from bot_program.models import AssetBotTrade
    from dashboard.position_summary import world_of
    out = []
    side = str(session.side or "").upper()
    rows = [h for h in exposure or [] if isinstance(h, dict)]
    ids = [h.get("trade_id") for h in rows if h.get("trade_id")]
    try:
        real = {t.id for t in AssetBotTrade.objects.filter(id__in=ids)
                if world_of(t) == "live"} if ids else set()
    except Exception as e:  # noqa: BLE001 — an unread holding is said
        return [f"  ALREADY HELD ON THIS SYMBOL: not read "
                f"({type(e).__name__})"]
    for h in rows:
        if h.get("trade_id") not in real:
            continue
        h_side = str(h.get("side") or "").upper()
        h_entry = _num(h.get("entry"))
        same = h_side == side
        how = ("this ticket ADDS to it" if same
               else "this ticket stands against it")
        if not h_entry or not entry:
            out.append(f"  ALREADY HELD ON THIS SYMBOL ({how}): {h_side}, "
                       f"its move not measured")
            continue
        move = (entry - h_entry) / h_entry * (1 if h_side == "BUY" else -1)
        line = (f"  ALREADY HELD ON THIS SYMBOL ({how}): {h_side} opened "
                f"at {h_entry:g}, now {move:+.2%}")
        if same and move < 0:
            line += "; adding to it is averaging down a loser"
        out.append(line)
    return out


def ticket_brief(session) -> str:
    """The hand ticket as the council reads it, built in the task (never
    in the view). The preview is read at the platform's own default
    levels; the brief argues the levels the owner asked about: the
    reward:risk is judged again at them, and the cost advisory (which the
    preview computes for its untouched levels only) is shown only when
    the asked levels are the preview's. What the operator already holds
    on the symbol is said under THE TRADE. The session's cost, value per
    unit and quantity are filled from the preview when the ask did not
    carry them."""
    from bot_program.manual_trade import _preview, reward_risk_advisory
    from instruments.models import Instrument

    lines = []
    inst = Instrument.objects.filter(symbol=session.symbol).first()
    facts = session.facts or {}
    signal = None
    if facts.get("signal_id"):
        try:
            from signals.models import Signal
            signal = Signal.objects.filter(pk=int(facts["signal_id"])).first()
        except Exception:  # noqa: BLE001
            signal = None
    p = {}
    if inst is not None and session.user is not None:
        try:
            p = _preview(session.user, inst, session.side, signal,
                         leverage=facts.get("leverage")) or {}
        except Exception as e:  # noqa: BLE001
            p = {"error": f"the preview could not be read ({type(e).__name__})"}
    # The entry the council argues is the one it will be graded from: the
    # platform's mark when the owner asked. Only an ask with no fresh mark
    # (the ticket's own number) takes the preview's.
    entry = session.entry
    if not entry or facts.get("entry_unverified"):
        entry = _num(p.get("entry")) or session.entry
    stop, target = session.stop, session.target
    levels = p.get("levels") or {}
    cost = _num(levels.get("cost_fraction"))
    if cost is None:
        cost = _num((p.get("cost_advisory") or {}).get("cost_fraction")) or 0.0
    vpu = _num(p.get("value_per_unit")) or session.value_per_unit or 1.0
    qty = session.qty if session.qty else _num(p.get("qty"))
    updates = {"cost_fraction": cost, "value_per_unit": vpu}
    if qty and not session.qty:
        updates["qty"] = qty
    if entry and entry != session.entry:
        updates["entry"] = entry
    for k, v in updates.items():
        setattr(session, k, v)
    session.save(update_fields=list(updates))

    lines.append("THE TRADE")
    lines.append(f"  {session.symbol} ({session.asset_class}) {session.side}"
                 f" — a HAND trade: the operator's own call; no rule's "
                 f"record applies")
    if p.get("error"):
        lines.append(f"  the preview could not be read: {p['error']}")
    if entry and stop and target:
        risk = abs(entry - stop) / entry
        reward = abs(target - entry) / entry
        net_rr = (max(0.0, reward - cost) / (risk + cost)) if risk > 0 else 0.0
        lines.append(f"  entry {entry:g}, stop {stop:g} ({risk:.2%} away), "
                     f"target {target:g} ({reward:.2%} away)")
        lines.append(f"  round-trip cost {cost:.3%}, net reward:risk "
                     f"{net_rr:.2f}")
        capital = _num(p.get("capital"))
        if qty and capital:
            share = qty * abs(entry - stop) * vpu / capital
            lines.append(f"  risk at the stop: {share:.2%} of the lane's "
                         f"capital")
        else:
            lines.append("  risk at the stop: not read (no size or no "
                         "capital in the preview)")
    lines.extend(held_lines(session, entry, p.get("existing_exposure")))
    if facts.get("entry_unverified"):
        lines.append("  NOTE: the platform had no fresh mark when the "
                     "council was asked; the entry is "
                     + ("the preview's mark at the sitting"
                        if _num(p.get("entry")) else "the ticket's own"))
    # The preview's reward:risk and cost advisories were judged at ITS
    # levels. The council argues the asked ones: the reward:risk is judged
    # again at them, and the cost advisory stands only when they match.
    if entry and stop and target:
        try:
            p["reward_risk"] = reward_risk_advisory(session.side, entry,
                                                    stop, target)
        except Exception:  # noqa: BLE001 — an unread ratio is not said
            p["reward_risk"] = None
    else:
        p["reward_risk"] = None
    asked_are_previews = (_near(stop, p.get("stop"))
                          and _near(target, p.get("target")))
    said = []
    for label, key in TICKET_ADVISORIES:
        if key == "cost_advisory" and not asked_are_previews:
            continue
        words = _advisory_words(p.get(key))
        if words:
            said.append(f"  {label}: {words[:400]}")
    if said:
        lines.append("WHAT THE TICKET SAYS")
        lines.extend(said)
    lines.extend(_news_and_brain(session.asset_class))
    return "\n".join(lines)


def _header(session) -> str:
    if session.origin == "bot":
        when = getattr(session.trade, "opened_at", None) or session.created_at
        what = f"the bot's order, sent {when:%H:%M} UTC"
    else:
        what = "the operator's hand ticket, not yet taken"
    src = (f"BrainReport #{session.regime_report_id}, confidence "
           f"{float(session.regime_confidence or 0):.2f}"
           if session.regime_report_id else "no brain report")
    return ("THE COUNCIL'S SITTING\n"
            f"  {what}\n"
            f"  regime recorded at the sitting: {session.regime} ({src})\n"
            "  Nothing you say reaches this order; the council is graded on "
            "what the market does next.")


def _risk_money(session) -> float:
    try:
        return (float(session.qty or 0) * abs(float(session.entry)
                                              - float(session.stop))
                * float(session.value_per_unit or 1.0))
    except (TypeError, ValueError):
        return 0.0


def _config_for(session):
    if session.config_id:
        return session.config
    try:
        from bot_program.manual_trade import EXECUTABLE_CLASS, manual_config_if_any
        cls = EXECUTABLE_CLASS.get(session.asset_class, session.asset_class)
        return manual_config_if_any(session.user, cls)
    except Exception:  # noqa: BLE001
        return None


def war_text(session) -> str:
    """THE WAR: where the book stands in each limit, in percent of the book
    and R only — never an amount of money. Every read fenced."""
    now = timezone.now()
    user = session.user
    bot = session.origin == "bot"
    lines = [f"THE WAR (read {now:%H:%M} UTC"
             + (", after the order was sent)" if bot else ")")]
    book = None

    def daily():
        nonlocal book
        from portfolio.risk_gate import daily_loss_state
        st = daily_loss_state(user, venue="live")
        book = _num(st.get("book_value"))
        realized = _num(st.get("realized"))
        limit = st.get("limit_pct")
        if limit is None:
            return "  daily stop: no daily-loss limit set on the book"
        if not book or realized is None:
            return (f"  daily stop: limit {float(limit):g}%; the window's "
                    f"result is not measured; mode {st.get('mode', 'open')}")
        return (f"  daily stop: {realized / book:+.2%} realized in the window, "
                f"limit {float(limit):g}%; mode {st.get('mode', 'open')}")

    lines.append(_fenced("  daily stop", daily))

    def open_risk():
        from portfolio.risk_gate import open_risk_state
        adding = 0.0 if bot else _risk_money(session)
        st = open_risk_state(user, adding=adding, venue="live")
        bv = _num(st.get("book_value")) or book
        limit = st.get("limit_pct")
        if limit is None or not bv:
            return "  open risk: not measured (no limit or no book value)"
        line = (f"  open risk: {float(st.get('open_risk') or 0) / bv:.1%} of "
                f"the book at the stops of {int(st.get('rows') or 0)} "
                f"positions, limit {float(limit):g}%")
        if not bot and adding:
            line += f"; this ticket would add {adding / bv:.2%}"
        return line

    lines.append(_fenced("  open risk", open_risk))

    def this_trade():
        from bot_program.asset_engine.sizing import MAX_RISK_FRACTION
        risk = _risk_money(session)
        share = (f"{risk / book:.2%} of the book" if book and risk
                 else "not measured")
        return (f"  this trade at its stop: {share}; the per-trade ceiling "
                f"is {MAX_RISK_FRACTION:.0%}")

    lines.append(_fenced("  this trade at its stop", this_trade))

    def elite():
        from portfolio.risk_gate import ELITE_MAX_PER_WINDOW, elite_entries_since
        used = elite_entries_since(user, paper=False)
        return (f"  elite entries: {used} of {ELITE_MAX_PER_WINDOW} used in "
                f"the window")

    lines.append(_fenced("  elite entries", elite))

    def pledge():
        # at exactly 100% the cap binds nothing (2026-11-01): the council
        # is told, or it names a limit no order meets
        from bot_program.asset_engine.base import (free_cash_decides_alone,
                                                   pledged_ceiling)
        ceiling = pledged_ceiling()
        return (f"  pledge cap: {ceiling:.0%} of the account"
                + (" (at 100%, eToro's free cash decides alone: no ratio "
                   "refuses an order)" if free_cash_decides_alone(ceiling)
                   else "")
                + "; the account's current pledge is not read here")

    lines.append(_fenced("  pledge cap", pledge))

    def horizons():
        from bot_program.share_allocator import horizon_for
        from brain.horizon_models import latest_view
        cfg = _config_for(session)
        view = latest_view()
        h = horizon_for(cfg, view) if cfg is not None else None
        neutral = (h is None or view is None
                   or (not h.get("tilt") and not h.get("confidence")))
        if neutral:
            return (f"  Horizons, {session.asset_class}: no current view"
                    + (f" ({h.get('label')})" if h and h.get("label") else ""))
        age = h.get("age_days")
        return (f"  Horizons, {session.asset_class}: {h.get('label')}, tilt "
                f"{float(h.get('tilt') or 0):+.2f}, confidence "
                f"{float(h.get('confidence') or 0):.2f}"
                + (f", {float(age):.0f} days old" if age is not None else ""))

    lines.append(_fenced("  Horizons", horizons))

    def posture():
        # The MEASURED posture (brain.strategist.measured_posture): never a
        # "calm" that nothing measured, and, with crisis mode OFF, plainly
        # a posture that sizes nothing. This entry's own posture is said
        # only while it sizes real orders.
        from brain.strategist import measured_posture
        m = measured_posture()
        line = f"  posture: {m['title_word']} ({str(m['note'])[:200]})"
        if m.get("crisis_mode_on"):
            from bot_program.posture import entry_posture
            p = entry_posture(user, session.symbol, session.asset_class,
                              session.side, cfg=_config_for(session))
            size = _num(p.get("size"))
            line += (f"; this entry: "
                     f"{str(p.get('kind') or '').replace('_', ' ')}, "
                     + (f"size x{size:g}" if size is not None
                        else "size not measured")
                     + ("" if p.get("live", True) else
                        ", paper only under this posture"))
        return line

    lines.append(_fenced("  posture", posture))

    def book30():
        # world "live": venue "live" alone is paper=False, which eToro's
        # DEMO world (broker_env "paper") is too: a rehearsal is not the
        # real book's record
        from bot_program import scorecard
        s = scorecard.summarize(scorecard.rows(days=30, user=user,
                                               venue="live", world="live"))
        if not s.get("n"):
            return "  the live book, 30 days: none closed"
        exp, wr = _num(s.get("expectancy")), _num(s.get("win_rate"))
        return (f"  the live book, 30 days: {s['n']} closed, average R "
                + (f"{exp:+.2f}" if exp is not None else "not measured")
                + ", win rate "
                + (f"{wr:.0%}" if wr is not None else "not measured"))

    lines.append(_fenced("  the live book, 30 days", book30))
    lines.append("  season objective: none set by the operator")
    return "\n".join(lines)


def _leg(leg) -> str:
    if not isinstance(leg, dict):
        return "none"
    try:
        from bot_program.positioning import _leg_words
        return _leg_words(leg)
    except Exception:  # noqa: BLE001
        return f"{leg.get('kind', '')} {leg.get('price', '')}".strip()


def big_money(session) -> tuple:
    """(footprint, why_unread): the Big Money board's note for this symbol
    and side (bigmoney.read.ticket_words, the board's public contract,
    which never raises), as one footprint when the board read it, or the
    board's own reason when it did not. Fenced: a server without the
    board, or a board that cannot be read, is said and offers no id."""
    try:
        from bigmoney.read import ticket_words
    except ImportError:
        return None, "the board is not on this server"
    try:
        out = ticket_words(session.symbol, session.side) or {}
    except Exception as e:  # noqa: BLE001 — an unread board is said
        return None, f"the board could not be read ({type(e).__name__})"
    words = " ".join(str(out.get("words") or "").split())
    if out.get("ok") and words:
        return f"the Big Money board: {words}"[:240], ""
    return None, (words.rstrip(".") or "nothing on this symbol")


def footprints(session) -> tuple:
    """(text, ids): one footprint per non-empty element of the positioning
    map, of the smart-money stamp the proposal wrote and of the Big Money
    board's read. The Awakened cites them by id; an id that is not here is
    not evidence."""
    items = []
    why = ""
    try:
        from bot_program import positioning
        pmap = positioning.compact(positioning.positioning_map(
            session.symbol, asset_class=session.asset_class,
            direction=session.side or None))
        if pmap.get("ok"):
            if pmap.get("label") is not None:
                score = _num(pmap.get("score"))
                items.append(f"the crowd: {pmap.get('label')}"
                             + (f" (score {score:+.2f})" if score is not None
                                else ""))
            for k, comp in (pmap.get("components") or {}).items():
                if isinstance(comp, dict) and comp.get("words"):
                    items.append(f"crowd component {k}: {comp['words']}")
            stops = pmap.get("stops") or {}
            for side in ("below", "above"):
                if stops.get(side):
                    items.append(f"the pool {side}: {_leg(stops[side])}")
            for leg in pmap.get("path") or []:
                if isinstance(leg, dict) and leg.get("price") is not None:
                    items.append(f"the {leg.get('leg', 'path')}: "
                                 f"{leg.get('side', '')} to {_leg(leg)}"
                                 + (f" ({leg.get('why')})" if leg.get("why")
                                    else ""))
            odds = pmap.get("odds") or {}
            if odds.get("verdict") not in (None, "unjudged"):
                items.append(f"pool sweeps on this class: "
                             f"{str(odds['verdict']).upper()}"
                             + (f" ({float(odds['expectancy']):+.2f}R a trade)"
                                if odds.get("expectancy") is not None else ""))
            po3 = pmap.get("po3") or {}
            if po3.get("words"):
                items.append(f"the Power of Three: {po3['words']}")
            side = pmap.get("side") or {}
            if side.get("words"):
                items.append(f"for this side: {side['words']}")
        else:
            why = pmap.get("why") or pmap.get("words") or "unread"
    except Exception as e:  # noqa: BLE001
        why = f"the positioning map could not be read ({type(e).__name__})"
    sm = (session.facts or {}).get("smart_money")
    if isinstance(sm, dict):
        for k, v in sm.items():
            if v in (None, "", [], {}, False):
                continue
            if isinstance(v, (list, tuple)):
                v = "; ".join(str(x) for x in v)
            items.append(f"smart money {k}: {v}")
    board, board_why = big_money(session)
    if board:
        items.append(board)
    unread_board = ("" if board else
                    f"\nTHE BIG MONEY BOARD: unread ({board_why}); never "
                    f"speak for it.")
    if not items:
        why = why or "nothing on this symbol"
        return (f"FOOTPRINTS: none could be read ({why})" + unread_board,
                set())
    ids = []
    lines = ["FOOTPRINTS (cite by id)"]
    for i, text in enumerate(items, 1):
        fid = f"F{i}"
        ids.append(fid)
        lines.append(f"  {fid}. {str(text)[:240]}")
    return "\n".join(lines) + unread_board, set(ids)


def live_theories(session) -> tuple:
    """(text, ids) for the Theorist: up to 8 pending hypotheses on this
    symbol, this rule, then the market's regime, newest first; the
    regimes the market grades; his own trust there."""
    from brain.knowledge_models import Hypothesis
    rows, seen = [], set()
    pending = Hypothesis.objects.filter(outcome=Hypothesis.OUTCOME_PENDING)
    groups = [pending.filter(resolution_criteria__kind="price_direction",
                             resolution_criteria__symbol=session.symbol)]
    if session.rule_name:
        groups.append(pending.filter(
            resolution_criteria__kind="rule_avg_r",
            resolution_criteria__rule_name=session.rule_name))
    groups.append(pending.filter(resolution_criteria__kind="regime_holds"))
    for qs in groups:
        for h in qs.order_by("-created_at")[:8]:
            if h.id not in seen and len(rows) < 8:
                seen.add(h.id)
                rows.append(h)
    lines = ["LIVE THEORIES (cite by id)"]
    if not rows:
        lines.append("  none pending on this symbol, this rule or the regime")
    for h in rows:
        crit = h.resolution_criteria or {}
        kind = crit.get("kind", "")
        # a rule's theory says the book it is graded on: one on demo or
        # paper says nothing about a live trade, and one with no venue is
        # graded on the pooled record
        if kind == "rule_avg_r":
            kind += f"/{crit.get('venue') or 'pooled: live, demo and paper'}"
        due = (f"{h.resolution_deadline:%Y-%m-%d %H:%M}"
               if h.resolution_deadline else "no deadline")
        lines.append(f"  #{h.id} [{kind}] \"{h.claim_text[:160]}\" by "
                     f"{h.source_agent}, confidence {float(h.confidence):.2f},"
                     f" due {due}")
    try:
        from brain.models import BrainReport
        lines.append("REGIMES the market can grade: " + ", ".join(
            v for v, _ in BrainReport.REGIME_CHOICES))
    except Exception:  # noqa: BLE001
        pass
    try:
        from brain.hypotheses import agent_trust_score
        trust = agent_trust_score("council_theorist")
    except Exception:  # noqa: BLE001
        trust = None
    lines.append("YOUR TRUST in the hypothesis market: "
                 + (f"{trust:.2f}" if trust is not None
                    else "no graded theory yet"))
    return "\n".join(lines), {h.id for h in rows}


def council_extras(session) -> dict:
    """THE WAR and the FOOTPRINTS, read once per sitting."""
    war = _fenced("THE WAR", lambda: war_text(session))
    try:
        fp_text, fp_ids = footprints(session)
    except Exception as e:  # noqa: BLE001
        fp_text, fp_ids = (f"FOOTPRINTS: none could be read "
                           f"({type(e).__name__})"), set()
    return {"war": war, "footprints": fp_text, "footprint_ids": fp_ids}


# ── the words the surfaces show ───────────────────────────────────────────

def _fmt(v) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def verdict_words(voice: str, answer: dict) -> str:
    """The verdict in words (the ticket, the position card and /council/)."""
    a = answer or {}
    v = a.get("verdict", "")
    if voice == "executioner":
        if v == "cut":
            return f"would cut it to {float(a.get('size_scale') or 1):.2f}x"
        return "would veto it" if v == "veto" else "lets it pass"
    if voice == "champion":
        return "backs it" if v == "back" else "stays neutral"
    if voice == "opportunist":
        alt = a.get("alternative") or {}
        if v == "elsewhere" and alt:
            return (f"better elsewhere: {alt.get('symbol')} "
                    f"{alt.get('direction')} within "
                    f"{_fmt(alt.get('horizon_hours'))} hours")
        return "seize it" if v == "seize" else "nothing the crowd missed"
    if voice == "striker":
        t = a.get("trigger") or {}
        if v == "wait" and t:
            return (f"wait for a touch of {_fmt(t.get('level'))} within "
                    f"{_fmt(t.get('within_hours'))} hours")
        return "take it now" if v == "take" else "skip it"
    if voice == "fixer":
        if v != "fix":
            return "no fix needed"
        if a.get("fix_refused"):
            return f"a fix refused: {a['fix_refused']}"
        fix = a.get("fix") or {}
        if fix.get("kind") in MEASURED_FIXES:
            value = fix.get("value") if fix.get("kind") not in ("timing",) \
                else fix.get("valid_hours")
            return f"fix the {fix.get('kind')}: {_fmt(value)}"
        return f"fix: {fix.get('words', '')}"
    if voice == "gambler":
        words = {"all_in": "all in (the most the limits allow)",
                 "press": "press", "normal": "the ordinary size",
                 "small": "small"}.get(v, v)
        return words + (", worthy of the elite exception"
                        if a.get("elite_worthy") else "")
    if voice == "skeptic":
        if v == "sound":
            return "the evidence is sound"
        name = VOICE_NAMES.get(a.get("target"), "a voice")
        flaw = FLAW_WORDS.get(a.get("flaw"), "a weakness")
        name = name[4:] if name.startswith("The ") else name
        if v == "shaky":
            return f"the evidence is shaky: the {name}, {flaw}"
        return f"unfounded: the {name}, {flaw}"
    if voice == "awakened":
        tail = ""
        if a.get("level") is not None and a.get("touch_ok"):
            tail = (f" (level {_fmt(a.get('level'))} within "
                    f"{_fmt(a.get('within_hours'))} hours)")
        if v == "trap":
            return f"a trap: {a.get('prey') or 'this trade'} is the prey" + tail
        if v == "clean":
            return "clean: this trade stands with the hunter" + tail
        return "unread" + tail
    if voice == "theorist":
        if v == "serves":
            base = f"serves theory #{a.get('theory_id')}"
        elif v == "contradicts":
            base = f"contradicts theory #{a.get('theory_id')}"
        else:
            base = "no live theory covers it"
        if a.get("posted_theory"):
            base += f"; posted theory #{a['posted_theory']}"
        return base
    if voice == "emperor":
        if v == "fight_smaller":
            return f"fight smaller, commit {float(a.get('commit') or 0):.0%}"
        return "refuse the battle" if v == "refuse" else "fight"
    return v


def key_line(voice: str, answer: dict) -> str:
    """The one line THE COUNCIL SO FAR quotes for a voice."""
    a = answer or {}
    if voice == "executioner":
        return _txt(a.get("killer"))
    if voice == "champion":
        return _txt(a.get("edge"))
    if voice == "opportunist":
        return _txt(a.get("asymmetry"))
    if voice == "gambler":
        return _txt(a.get("case"))
    if voice == "awakened":
        return _txt(a.get("trap"))
    if voice == "theorist":
        return _txt(a.get("how"))
    if voice == "fixer":
        return _txt((a.get("fix") or {}).get("words") or a.get("flaw"))
    if voice == "striker":
        return _txt(a.get("decision"))
    if voice == "skeptic":
        return _txt(f"{a.get('target', '')}: \"{a.get('claim', '')}\" "
                    f"({a.get('flaw', '')})")
    if voice == "emperor":
        return _txt(a.get("battle"))
    return ""


def so_far(session) -> str:
    from ai_agents.council_models import CouncilVoice
    lines = ["THE COUNCIL SO FAR"]
    for row in session.voices.order_by("wave", "id"):
        name = VOICE_NAMES.get(row.voice, row.voice)
        if row.status in (CouncilVoice.SPOKE, CouncilVoice.COPIED):
            if row.voice in ("executioner", "skeptic"):
                prob = (f"conviction {row.conviction:.2f}"
                        if row.conviction is not None else "no conviction")
            elif row.voice == "champion":
                prob = (f"conviction {row.conviction:.2f}"
                        if row.conviction is not None else "no conviction")
            else:
                prob = (f"p_work {row.p_work:.2f}" if row.p_work is not None
                        else "no p_work")
            line = (f"  {name}: {verdict_words(row.voice, row.answer)}; "
                    f"{prob}")
            key = key_line(row.voice, row.answer)
            if key:
                line += f". {key}"
            lines.append(line[:420])
        elif row.status in (CouncilVoice.SILENT, CouncilVoice.LATE) \
                or row.status == CouncilVoice.ASKED:
            lines.append(f"  {name}: silent ({row.why or row.status})"[:240])
    return "\n".join(lines)


def record_text(session, weights: dict) -> str:
    from ai_agents.council_models import CouncilVoice
    lines = ["THE RECORD (each voice's graded record on this council, live)"]
    for row in session.voices.filter(
            status__in=(CouncilVoice.SPOKE, CouncilVoice.COPIED)
    ).order_by("wave", "id"):
        if row.voice == "emperor":
            continue
        w = weights.get(row.voice) or {}
        line = (f"  {VOICE_NAMES.get(row.voice, row.voice)}: weight "
                f"{float(w.get('factor', 1.0)):.2f}, "
                f"{w.get('reason', 'neutral: nothing graded yet')}")
        sp = w.get("specialty") or {}
        if w.get("lane") == "measured" and (sp.get("right") or sp.get("wrong")):
            line += (f"; specialty {sp.get('right', 0)} of "
                     f"{sp.get('right', 0) + sp.get('wrong', 0)} right")
        rate = _num(w.get("base_rate"))
        if w.get("lane") == "measured" and rate is not None:
            # A count right means little without how often the event came
            # anyway: an always-no voice is "right" in a losing cell.
            line += (f"; base rate: its targets were wrong {rate:.0%} of "
                     f"the time" if row.voice == "skeptic" else
                     f"; base rate: the trades it judged here won "
                     f"{rate:.0%}")
        lines.append(line)
    return "\n".join(lines)


# ── the Hand of the Emperor and the most trusted voice (2026-10-16) ───────

def emperor_side(verdict: str) -> str:
    """The chair's side, measured by code: "fight" commits the trade; any
    smaller commitment stands against it, as his battle claim is graded
    (a commit under 1 is graded on -R, council_grading)."""
    return {"fight": "for", "fight_smaller": "against",
            "refuse": "against"}.get(str(verdict or ""), "")


def deciding_claim(claims, voice: str):
    """The claim a voice's side in a sitting is read from, and graded on
    against the chair: its stance, else (the Skeptic) its attack, else its
    work claim. None when it made none."""
    cs = list(claims or [])
    for c in cs:
        if c.kind == "stance" and c.stance in ("for", "against"):
            return c
    if voice == "skeptic":
        return next((c for c in cs if c.kind == "attack"), None)
    return next((c for c in cs if c.kind == "work" and c.p is not None),
                None)


def claim_side(session, voice: str) -> str:
    """"for", "against" or "" (silent, or no side taken): one voice's side
    in this sitting, measured from its own claims. The Skeptic's side is
    the opposite of the voice his attack names."""
    from ai_agents.council_models import CouncilVoice
    if not voice or not session.voices.filter(
            voice=voice, status__in=(CouncilVoice.SPOKE,
                                     CouncilVoice.COPIED)).exists():
        return ""
    c = deciding_claim(session.claims.filter(
        voice_key=voice, kind__in=("stance", "attack", "work")), voice)
    if c is None:
        return ""
    if c.kind == "stance":
        return c.stance
    if c.kind == "attack":
        target = str((c.payload or {}).get("target") or "")
        if not target or target == voice:
            return ""
        return {"for": "against", "against": "for"}.get(
            claim_side(session, target), "")
    return "for" if c.p > 0.5 else "against" if c.p < 0.5 else ""


def hand_text(hand: dict) -> str:
    """THE HAND OF THE EMPEROR as the chair reads it, after THE RECORD."""
    h = hand or {}
    cell = h.get("cell") or "this regime and class"
    head = f"THE HAND OF THE EMPEROR ({cell}): "
    if not h.get("voice"):
        return (head + f"{h.get('why_empty') or 'no voice has earned it yet'}"
                f" (the seat needs {COUNCIL_HAND_MIN_N} graded calls in this "
                f"regime and class and a weight of at least "
                f"{COUNCIL_HAND_MIN_FACTOR:.2f}).")
    name = h.get("name") or VOICE_NAMES.get(h["voice"], h["voice"])
    factor = _num(h.get("factor"))
    record = ((f"weight {factor:.2f}, " if factor is not None else "")
              + str(h.get("reason") or "measured in this cell")).rstrip(".")
    side = h.get("side") or ""
    if side == "for":
        said = ("Its side in this sitting: for the trade. Only fight goes "
                "with it: fight_smaller and refuse go against it, so say "
                "why in hand_why.")
    elif side == "against":
        said = ("Its side in this sitting: against the trade. fight goes "
                "against it (say why in hand_why); fight_smaller and refuse "
                "go with it.")
    else:
        said = ("Its side in this sitting: none (silent, or no side taken): "
                "there is nothing of it to overrule.")
    return f"{head}{name} holds it.\n  Its record: {record}.\n  {said}"


def trusted_text(hand: dict) -> str:
    """The one line the Skeptic alone reads: a name and a title, never a
    number (the members argue arguments, not records)."""
    h = hand or {}
    cell = h.get("cell") or "this regime and class"
    v = h.get("trusted") or ""
    attack = "Attack its evidence first when it gives you something to attack."
    if v and h.get("trusted_why") == "hand":
        return (f"THE MOST TRUSTED VOICE: {VOICE_NAMES.get(v, v)}, the Hand of "
                f"the Emperor in {cell}. {attack}")
    if v:
        return (f"THE MOST TRUSTED VOICE: {VOICE_NAMES.get(v, v)}, the voice "
                f"before you with the best measured record in {cell}. "
                f"{attack}")
    if h.get("trusted_why") == "unread":
        return ("THE MOST TRUSTED VOICE: not read: the council's record "
                "could not be read for this sitting. Choose your target on "
                "the evidence alone.")
    return (f"THE MOST TRUSTED VOICE: none named: no voice before you has "
            f"earned trust in {cell}. Choose your target on the evidence "
            f"alone.")


def hand_line(session, emperor: dict = None) -> str:
    """The position card's line: who held the seat at entry, its side, and
    whether the chair overruled it. "" for a sitting before the seat."""
    h = session.hand or {}
    if not h:
        return ""
    if not h.get("voice"):
        why = str(h.get("why_empty") or "")
        if why.startswith(SEAT_UNREAD):
            return f"The Hand of the Emperor at entry: {why}."
        return "The Hand of the Emperor at entry: no voice had earned it yet."
    name = h.get("name") or VOICE_NAMES.get(h["voice"], h["voice"])
    side = h.get("side") or ""
    line = (f"The Hand of the Emperor at entry: {name} ("
            + (f"{side} the trade" if side in ("for", "against")
               else "no side taken") + ")")
    e = emperor or {}
    if e.get("hand_overruled"):
        why = str(e.get("hand_why") or "").strip().rstrip(".")
        line += (f"; the Emperor overruled it: {why}" if why
                 else "; the Emperor overruled it without saying why")
    return line + "."


#: The empty seat's words when the record behind it could not be read:
#: never "no voice has earned it yet", which is a measured fact.
SEAT_UNREAD = "the seat could not be read"


def _seat(weights: dict, session, spoke: set, unread: str = "") -> dict:
    """The Hand at this sitting and the Skeptic's target, from the weights
    the chair will read. Fenced: an unread seat is empty, said. `unread`
    names the error when the weights themselves could not be read: the
    seat is then empty because nothing was read, and says so."""
    cell = (f"{session.regime or 'unknown'} on "
            f"{session.asset_class or 'every class'}")
    empty = {"cell": cell, "voice": "", "name": "", "factor": None, "n": 0,
             "brier": None, "reference": None, "reason": ""}
    if unread:
        return {**empty, "why_empty": f"{SEAT_UNREAD} ({unread})",
                "trusted": "", "trusted_why": "unread"}
    try:
        from ai_agents.council_grading import hand_of, most_trusted
        hand = hand_of(weights, session.regime, session.asset_class)
        trusted, how = most_trusted(weights, hand.get("voice") or "", spoke)
    except Exception as e:  # noqa: BLE001 — an unread seat is empty
        logger.warning("[council] the Hand unread: %s", e)
        hand = {**empty, "why_empty": f"{SEAT_UNREAD} ({type(e).__name__})"}
        trusted, how = "", "unread"
    return {**hand, "trusted": trusted, "trusted_why": how}


def _fenced_mood(session) -> dict:
    """THE PEOPLE'S MOOD for the sitting's owner: pure code, never a model
    call; unmeasured, said, when it cannot be read."""
    from ai_agents.council_mood import people_mood, unmeasured_mood
    if session.user_id is None:
        return unmeasured_mood("no owner's book to read")
    try:
        return people_mood(session.user)
    except Exception as e:  # noqa: BLE001 — an unread gauge is unmeasured
        logger.warning("[council] mood unread: %s", e)
        return unmeasured_mood(f"the gauge could not be read "
                               f"({type(e).__name__})")


def _mood_lines(mood: dict) -> str:
    from ai_agents.council_mood import mood_text
    try:
        return mood_text(mood)
    except Exception as e:  # noqa: BLE001
        return f"  the people's mood: unmeasured ({type(e).__name__})"


# ── the estimates ─────────────────────────────────────────────────────────

def estimate_usd(system: str, user: str, model: str) -> float:
    """What one voice's call should cost at most, priced from the text
    actually sent at its own model's rates, with the close advisor's
    arithmetic and margin (brain/close_advice.py), floored at the debate's
    per-side estimate."""
    from ai_agents.catalog import pricing_for
    from brain.close_advice import CHARS_PER_TOKEN, ESTIMATE_MARGIN
    price = pricing_for(model or "")
    tokens_in = (len(system or "") + len(user or "")) / CHARS_PER_TOKEN
    usd = (tokens_in * price["input"]
           + COUNCIL_OUT_TOKENS * price["output"]) / 1_000_000
    return round(max(DEBATE_EST_USD, usd * ESTIMATE_MARGIN), 4)


# ── the sitting ───────────────────────────────────────────────────────────

def _silence(session, why: str) -> None:
    from ai_agents.council_models import CouncilSession
    CouncilSession.objects.filter(id=session.id).update(
        status=CouncilSession.SILENT, why=why[:300],
        finished_at=timezone.now())


def _land(meta: dict, voice: str, outcome: dict, *, late: bool) -> None:
    """One voice's answer written to ITS row, once: a conditional update on
    status "asked", so a late answer never overwrites a settled one."""
    from ai_agents.council_models import CouncilVoice
    try:
        rows = CouncilVoice.objects.filter(session_id=meta["id"], voice=voice,
                                           status=CouncilVoice.ASKED)
        at = outcome.get("at") or timezone.now()
        model = str(outcome.get("model") or "")[:60]
        if not outcome.get("ok"):
            rows.update(status=CouncilVoice.SILENT,
                        why=str(outcome.get("why") or "silent")[:200],
                        answered_at=at, model=model)
            return
        ans = _jsonable(outcome.get("answer") or {})
        p, conv = p_and_conviction(voice, ans)
        n = rows.update(
            status=CouncilVoice.LATE if late else CouncilVoice.SPOKE,
            verdict=str(ans.get("verdict", ""))[:20], p_work=p,
            conviction=conv, answer=ans, model=model, answered_at=at,
            why="late: not heard by the chair" if late else "")
        if not n:
            return
        row = CouncilVoice.objects.get(session_id=meta["id"], voice=voice)
        _save_claims(meta, row, claims_for(voice, ans, late=late))
    except Exception as e:  # noqa: BLE001 — one voice's record, said
        logger.warning("[council] #%s %s not landed: %s", meta.get("id"),
                       voice, e)


def _ask_rows(session, wave: int, voices: list) -> None:
    """Pre-create one "asked" row per voice. A wave-0 row the debate left
    silent is asked again by the council (its own name)."""
    from ai_agents.council_models import CouncilVoice
    for v in voices:
        agent = (f"council_{v}")
        CouncilVoice.objects.update_or_create(
            session=session, voice=v,
            defaults={"agent": agent, "wave": wave,
                      "status": CouncilVoice.ASKED, "why": "",
                      "verdict": "", "p_work": None, "conviction": None,
                      "answer": {}, "answered_at": None})


def run_wave(session, wave: int, specs: list, *, tier: str) -> dict:
    """Ask one wave's voices at once, one deadline for the wave.

    specs: [(voice, user_message, ctx)]. Returns {"asked", "refused"}.
    The pre-check prices the text actually sent; a refusal silences the
    wave with the budget's reason. Each thread lands its OWN answer: an
    answer in by the deadline is written here as "spoke", one after it is
    written by its thread as "late" (stored and graded, heard by nobody).
    """
    from concurrent.futures import ThreadPoolExecutor, wait

    from ai_agents.council_models import CouncilVoice
    from ai_agents.spend import can_spend

    if not specs:
        return {"asked": 0, "refused": ""}
    agents = []
    for voice, msg, ctx in specs:
        agent = AGENTS[voice](ctx=ctx)
        agents.append((voice, agent, msg))
    est = sum(estimate_usd(a.get_system_prompt(), m, a.model)
              for _v, a, m in agents)
    _ask_rows(session, wave, [v for v, _a, _m in agents])
    allowed, reason = can_spend(tier=tier, estimated_usd=est, line="core")
    if not allowed:
        why = f"AI budget: {reason}"[:200]
        CouncilVoice.objects.filter(session=session, wave=wave,
                                    status=CouncilVoice.ASKED).update(
            status=CouncilVoice.SILENT, why=why)
        return {"asked": 0, "refused": why}

    meta = _meta(session)
    box = {"closed": False, "results": {}}
    lock = threading.Lock()

    def _call(voice, agent, msg):
        from django.db import connection
        try:
            try:
                answer = agent.run(brief=msg)
                outcome = {"ok": True, "answer": answer}
            except Exception as e:  # noqa: BLE001 — that voice is silent
                outcome = {"ok": False, "why": type(e).__name__}
            outcome["at"] = timezone.now()
            outcome["model"] = getattr(agent, "model", "")
            with lock:
                if not box["closed"]:
                    box["results"][voice] = outcome
                    return
            _land(meta, voice, outcome, late=True)
        finally:
            connection.close()

    pool = ThreadPoolExecutor(max_workers=len(agents),
                              thread_name_prefix="council")
    futures = [pool.submit(_call, v, a, m) for v, a, m in agents]
    wait(futures, timeout=COUNCIL_WAVE_TIMEOUT_S)
    with lock:
        box["closed"] = True
        results = dict(box["results"])
    pool.shutdown(wait=False)
    for voice, outcome in results.items():
        _land(meta, voice, outcome, late=False)
    CouncilVoice.objects.filter(session=session, wave=wave,
                                status=CouncilVoice.ASKED).update(
        why="timeout")
    return {"asked": len(agents), "refused": ""}


def _silence_waves(session, waves: dict, why: str) -> None:
    from ai_agents.council_models import CouncilVoice
    for wave, voices in waves.items():
        for v in voices:
            CouncilVoice.objects.update_or_create(
                session=session, voice=v,
                defaults={"agent": f"council_{v}", "wave": wave,
                          "status": CouncilVoice.SILENT, "why": why[:200]})


def _today_theories() -> int:
    from brain.knowledge_models import Hypothesis
    return Hypothesis.objects.filter(source_agent="council_theorist",
                                     created_at__gte=_today_start()).count()


def _refuse_claim(claim, why: str) -> None:
    claim.grade = "refused"
    claim.grade_notes = why[:300]
    claim.graded_at = timezone.now()
    claim.save(update_fields=["grade", "grade_notes", "graded_at"])


def post_alternative(session, row) -> None:
    """The Opportunist's "bigger opportunity elsewhere" as a direction call
    the 03:30 calibration resolver grades (ai_agents/calibration.py)."""
    from ai_agents.calibration import log_direction_prediction, mark_for_symbol
    claim = row.claims.filter(kind="direction", grade="pending").first()
    alt = (row.answer or {}).get("alternative")
    if claim is None or not isinstance(alt, dict):
        return
    try:
        ref = mark_for_symbol(alt["symbol"])
        if ref is None:
            _refuse_claim(claim, "no price to measure from")
            return
        pred = log_direction_prediction(
            "council_opportunist", alt["symbol"], alt["direction"],
            horizon_hours=alt.get("horizon_hours"),
            confidence=alt.get("confidence", 0.5), reference_price=ref,
            notes=f"council #{session.id}")
        if pred is None:
            _refuse_claim(claim, "not registered: an unknown symbol or a "
                                 "live call already open on it")
            return
        claim.prediction = pred
        claim.save(update_fields=["prediction"])
    except Exception as e:  # noqa: BLE001 — a post that fails is said
        _refuse_claim(claim, f"not registered ({type(e).__name__})")


def _theory_criteria(nt: dict):
    """(criteria, why_refused) from that kind's fields only."""
    from ai_agents.calibration import mark_for_symbol
    kind = nt.get("kind")
    if kind == "price_direction":
        ref = mark_for_symbol(nt.get("symbol") or "")
        if ref is None:
            return None, "no price to measure from"
        return {"kind": kind, "symbol": nt.get("symbol"),
                "direction": nt.get("direction"),
                "reference_price": float(ref)}, ""
    if kind == "regime_holds":
        from brain.hypotheses import canonical_regime
        return {"kind": kind,
                "regime": canonical_regime(nt.get("regime")) or
                nt.get("regime")}, ""
    if kind == "rule_avg_r":
        # On the live book only (brain.hypotheses.RULE_VENUES): the council
        # argues real money, and a claim with no venue would be graded on
        # the pooled record, where one paper booking can decide it. The
        # door (VENUE_REQUIRED_FROM) refuses his claim without one.
        crit = {"kind": kind, "rule_name": nt.get("rule_name"),
                "comparator": nt.get("comparator") or ">=",
                "threshold": nt.get("threshold"), "venue": "live"}
        if nt.get("window_days") is not None:
            crit["window_days"] = int(nt["window_days"])
        if nt.get("min_n") is not None:
            crit["min_n"] = int(nt["min_n"])
        return crit, ""
    return None, f"a theory of kind {kind!r} no grader measures"


def post_theory(session, row) -> None:
    """The Theorist's new theory, posted to the hypothesis market under his
    own name, under the day's cap; refused at the door, said."""
    from brain.hypotheses import UnmeasurableClaim, post_hypothesis
    claim = row.claims.filter(kind="theory", grade="pending").first()
    nt = (row.answer or {}).get("new_theory")
    if claim is None or not isinstance(nt, dict):
        return
    try:
        if _today_theories() >= COUNCIL_THEORIES_PER_DAY:
            _refuse_claim(claim, f"the day's {COUNCIL_THEORIES_PER_DAY} "
                                 f"theories are posted")
            return
        hours = _num(nt.get("horizon_hours"))
        if hours is None or not 6 <= hours <= 720:
            _refuse_claim(claim, "a horizon outside 6 to 720 hours")
            return
        criteria, why = _theory_criteria(nt)
        if criteria is None:
            _refuse_claim(claim, why)
            return
        try:
            hyp = post_hypothesis(
                claim_text=nt.get("claim_text") or "a council theory",
                source_agent="council_theorist",
                claim_payload={"council_session": session.id},
                resolution_criteria=criteria,
                confidence=float(nt.get("confidence") or 0.5),
                horizon_hours=int(hours))
        except UnmeasurableClaim as e:
            _refuse_claim(claim, str(e))
            return
        claim.hypothesis = hyp
        claim.payload = {**(claim.payload or {}), "hypothesis_id": hyp.id}
        claim.save(update_fields=["hypothesis", "payload"])
        row.answer = {**(row.answer or {}), "posted_theory": hyp.id}
        row.save(update_fields=["answer"])
    except Exception as e:  # noqa: BLE001
        _refuse_claim(claim, f"not posted ({type(e).__name__})")


def _spoke(session) -> set:
    from ai_agents.council_models import CouncilVoice
    return set(session.voices.filter(
        status__in=(CouncilVoice.SPOKE, CouncilVoice.COPIED)
    ).values_list("voice", flat=True))


def _instrument_symbols() -> set:
    try:
        from instruments.models import Instrument
        return {str(s).upper() for s in
                Instrument.objects.values_list("symbol", flat=True)}
    except Exception:  # noqa: BLE001
        return set()


def _finish(session, why: str = "") -> None:
    """The benchmark rows and the sitting's status. `why` is said on the
    session when a wave was refused (the ticket shows it)."""
    from ai_agents.council_models import CouncilSession, CouncilVoice
    rows = list(session.voices.all())
    heard = [r for r in rows if r.status in (CouncilVoice.SPOKE,
                                             CouncilVoice.COPIED)
             and r.voice != "emperor" and r.p_work is not None]
    w = session.weights or {}
    p_mean = p_weighted = None
    if heard:
        p_mean = sum(r.p_work for r in heard) / len(heard)
    # Weighted only when the weights were read (wave 3 was reached): a
    # sitting refused before them is not shown as weighted.
    if heard and w:
        ws = [float((w.get(r.voice) or {}).get("factor", 1.0)) for r in heard]
        p_weighted = (sum(wi * r.p_work for wi, r in zip(ws, heard))
                      / sum(ws)) if sum(ws) > 0 else None
    chair = [r for r in rows if r.voice == "emperor"
             and r.status == CouncilVoice.SPOKE]
    p_chair = chair[0].p_work if chair else None
    asked = [r for r in rows if r.wave >= 1]
    spoke = [r for r in asked if r.status == CouncilVoice.SPOKE]
    if asked and len(spoke) == len(asked):
        status = CouncilSession.DONE
    elif spoke:
        status = CouncilSession.PARTIAL
    else:
        status = CouncilSession.SILENT
    if not why and status == CouncilSession.SILENT:
        why = "no voice answered"
    fields = {"p_mean": p_mean, "p_weighted": p_weighted, "p_chair": p_chair,
              "status": status, "finished_at": timezone.now()}
    if why:
        fields["why"] = why[:300]
    CouncilSession.objects.filter(id=session.id).update(**fields)


def run_sitting(session_id: int) -> dict:
    """The task's body (ai_agents.tasks.run_council_sitting). Idempotent:
    only a "queued" session is claimed."""
    from ai_agents.council_models import CouncilSession
    from core.platform_control import is_component_enabled

    claimed = CouncilSession.objects.filter(
        id=session_id, status=CouncilSession.QUEUED).update(
        status=CouncilSession.SITTING)
    if not claimed:
        return {"status": "noop", "session": session_id}
    session = CouncilSession.objects.select_related(
        "trade", "config", "user").get(id=session_id)
    # Too late to sit: nobody is waiting for it any more, and it would
    # bill a whole council on a ticket that may be taken or abandoned.
    age = timezone.now() - session.created_at
    fresh = (COUNCIL_TICKET_FRESH_MIN if session.origin == "ticket"
             else COUNCIL_BOT_FRESH_MIN)
    if age > timedelta(minutes=fresh):
        _silence(session, f"too late to sit: queued "
                          f"{int(age.total_seconds() // 60)} minutes")
        return {"status": "silent", "session": session_id}
    if not is_component_enabled("platform_master"):
        _silence(session, "the platform master switch is OFF")
        return {"status": "silent", "session": session_id}
    lane = (COUNCIL_BOT_SWITCH if session.origin == "bot"
            else COUNCIL_TICKET_SWITCH)
    if not is_component_enabled(lane):
        _silence(session, f"{lane} is OFF")
        return {"status": "silent", "session": session_id}
    try:
        _sit(session)
    except Exception as e:  # noqa: BLE001 — the sitting's failure is said
        logger.warning("[council] sitting #%s failed: %s", session_id, e)
        _silence(session, f"the sitting failed ({type(e).__name__})")
        return {"status": "error", "session": session_id}
    session.refresh_from_db()
    return {"status": session.status, "session": session_id}


def _sit(session) -> None:
    from ai_agents.council_models import CouncilVoice

    tier = "deep" if session.origin == "bot" else "balanced"
    if session.origin == "ticket":
        session.brief = ticket_brief(session)
    extras = council_extras(session)
    session.extras = extras["war"] + "\n\n" + extras["footprints"]
    # THE PEOPLE'S MOOD (2026-10-16): read once, by code, recorded on every
    # sitting (a refused one too). Only the chair reads it: the members'
    # briefs stay as they were, so their grades stay comparable.
    mood = _fenced_mood(session)
    session.mood = str(mood.get("level") or "unmeasured")[:10]
    session.mood_read = _jsonable(mood)
    session.save(update_fields=["brief", "extras", "mood", "mood_read"])
    common = "\n\n".join([_header(session), session.brief or "",
                          extras["war"], extras["footprints"]])
    common_chair = "\n\n".join([_header(session), session.brief or "",
                                extras["war"] + "\n" + _mood_lines(mood),
                                extras["footprints"]])
    try:
        theories_text, theory_ids = live_theories(session)
    except Exception as e:  # noqa: BLE001
        theories_text, theory_ids = (f"LIVE THEORIES: not read "
                                     f"({type(e).__name__})"), set()
    ctx = {"entry": session.entry, "stop": session.stop,
           "target": session.target, "side": session.side,
           "instruments": _instrument_symbols(),
           "footprint_ids": extras["footprint_ids"],
           "theory_ids": theory_ids, "spoke": set()}

    copied = set(session.voices.filter(status=CouncilVoice.COPIED)
                 .values_list("voice", flat=True))
    wave1 = [v for v in ("executioner", "champion") if v not in copied]
    wave1 += ["opportunist", "gambler", "awakened", "theorist"]
    later = {2: ["skeptic", "fixer", "striker"], 3: ["emperor"]}

    specs = [(v, common + ("\n\n" + theories_text if v == "theorist" else ""),
              ctx) for v in wave1]
    res = run_wave(session, 1, specs, tier=tier)
    if res["refused"]:
        _silence_waves(session, later, res["refused"])
        _finish(session, why=res["refused"])
        return
    for row in session.voices.filter(status=CouncilVoice.SPOKE,
                                     voice__in=("opportunist", "theorist")):
        if row.voice == "opportunist":
            post_alternative(session, row)
        else:
            post_theory(session, row)

    # The weights the chair will read (the nightly-graded snapshot), read
    # before wave 2 only to seat the Hand and name the Skeptic's target;
    # stored on the session after wave 2, as before, so a sitting refused
    # there is never shown as weighted.
    from ai_agents.council_grading import voice_weights
    unread = ""
    try:
        weights = voice_weights(session.regime, session.asset_class)
    except Exception as e:  # noqa: BLE001 — unread weights are neutral
        logger.warning("[council] weights unread: %s", e)
        weights, unread = {}, type(e).__name__
    spoke = _spoke(session)
    hand = _seat(weights, session, spoke, unread=unread)
    session.hand = _jsonable(hand)
    session.save(update_fields=["hand"])
    ctx2 = dict(ctx, spoke=spoke)
    msg2 = common + "\n\n" + so_far(session)
    # The members read arguments, not records: only the Skeptic is told
    # which voice is the most trusted, to attack its evidence first.
    specs2 = [(v, (msg2 + "\n\n" + trusted_text(session.hand))
               if v == "skeptic" else msg2, ctx2) for v in later[2]]
    res = run_wave(session, 2, specs2, tier=tier)
    if res["refused"]:
        _silence_waves(session, {3: later[3]}, res["refused"])
        _finish(session, why=res["refused"])
        return

    session.weights = _jsonable(weights)
    session.save(update_fields=["weights"])
    try:
        side = claim_side(session, hand.get("voice") or "")
    except Exception as e:  # noqa: BLE001 — an unread side is no side
        logger.warning("[council] the Hand's side unread: %s", e)
        side = ""
    session.hand = {**session.hand, "side": side}
    session.save(update_fields=["hand"])
    ctx3 = dict(ctx, spoke=_spoke(session),
                hand={"voice": hand.get("voice") or "", "side": side})
    msg3 = (common_chair + "\n\n" + so_far(session) + "\n\n"
            + record_text(session, weights) + "\n\n"
            + hand_text(session.hand))
    res = run_wave(session, 3, [("emperor", msg3, ctx3)], tier=tier)
    # The snapshot the chair read, on every voice's row (his own included).
    for row in session.voices.all():
        w = weights.get(row.voice) or {}
        CouncilVoice.objects.filter(pk=row.pk).update(
            weight_seen=w.get("factor"),
            weight_reason=str(w.get("reason", ""))[:200])
    _finish(session, why=res["refused"])


# ── the stable readers (the council band, the Orcs) ───────────────────────

def session_payload(session) -> dict:
    """One sitting as the ticket, the position card and the readers show
    it."""
    from ai_agents.council_models import CouncilVoice
    voices, emperor = [], None
    for row in session.voices.order_by("wave", "id"):
        item = {"voice": row.voice,
                "name": VOICE_NAMES.get(row.voice, row.voice),
                "wave": row.wave, "status": row.status, "why": row.why,
                "verdict": row.verdict,
                "verdict_words": (verdict_words(row.voice, row.answer)
                                  if row.status in (CouncilVoice.SPOKE,
                                                    CouncilVoice.COPIED,
                                                    CouncilVoice.LATE)
                                  else ""),
                "line": key_line(row.voice, row.answer),
                "weight_seen": row.weight_seen,
                "weight_reason": row.weight_reason}
        if row.voice == "emperor" and row.status == CouncilVoice.SPOKE:
            a = row.answer or {}
            emperor = {**item,
                       "followed": [VOICE_NAMES.get(v, v)
                                    for v in a.get("followed") or []],
                       "overruled": [VOICE_NAMES.get(o.get("voice"),
                                                     o.get("voice"))
                                     for o in a.get("overruled") or []],
                       "war_cost": a.get("war_cost", ""),
                       "plan": a.get("plan", ""),
                       "hand_overruled": bool(a.get("hand_overruled")),
                       "hand_why": a.get("hand_why", ""),
                       "hand_note": a.get("hand_note", "")}
        voices.append(item)
    return {"id": session.id, "status": session.status, "why": session.why,
            "origin": session.origin, "symbol": session.symbol,
            "side": session.side, "regime": session.regime,
            "created_at": session.created_at.isoformat()
            if session.created_at else None,
            "asked": {"stop": session.stop, "target": session.target},
            "voices": voices, "emperor": emperor,
            "hand": {"name": (session.hand or {}).get("name") or "",
                     "side": (session.hand or {}).get("side") or "",
                     "why_empty": (session.hand or {}).get("why_empty")
                     or ""},
            "mood": session.mood or "not read",
            "truth": session.truth, "truth_r": session.truth_r,
            "graded": session.graded_at is not None,
            "schema_version": session.schema_version}


def voice_line(item: dict) -> str:
    """One voice as the ticket, the position card and the readers say it."""
    name = item.get("name") or VOICE_NAMES.get(item.get("voice"), "")
    if item.get("status") == "late":
        return f"{name}: late, not heard by the chair."
    if item.get("status") == "asked" and not item.get("why"):
        return f"{name}: not answered yet"
    if item.get("status") in ("silent", "asked"):
        return f"{name}: silent ({item.get('why') or 'no answer'})"
    line = f"{name}: {item.get('verdict_words') or item.get('verdict')}."
    if item.get("line"):
        line += f" {str(item['line']).rstrip('.')}."
    if item.get("weight_seen") is not None:
        line += (f" Record {float(item['weight_seen']):.2f}: "
                 f"{item.get('weight_reason') or ''}").rstrip(": ")
    return line


def card_payload(session) -> dict:
    """The position page's "The council at entry" card: the sitting, what
    each voice said, and once graded, who was right."""
    p = session_payload(session)
    by_voice = {}
    for c in session.claims.all():
        by_voice.setdefault(c.voice_key, []).append(c)
    right, wrong, unmeasured = [], [], []
    for item in p["voices"]:
        if item["status"] not in ("spoke", "copied", "late"):
            continue
        cs = by_voice.get(item["voice"], [])
        pick = None
        for kind in ("stance", "attack", "battle", "work"):
            pick = next((c for c in cs if c.kind == kind), None)
            if pick:
                break
        grade = pick.grade if pick else ""
        (right if grade == "right" else wrong if grade == "wrong"
         else unmeasured).append(item["name"])
        item["text"] = voice_line(item)
    for item in p["voices"]:
        item.setdefault("text", voice_line(item))
    emperor = p.get("emperor")
    trade = session.trade
    p.update({
        "when": session.created_at,
        "lane_words": ("the bot's order" if session.origin == "bot"
                       else "the ticket you asked about"),
        "emperor_words": emperor["verdict_words"] if emperor else "silent",
        "right": right, "wrong": wrong, "unmeasured": unmeasured,
        "open": bool(trade is not None
                     and trade.status in ("OPEN", "CLOSE_PENDING")),
        "truth_line": (f"{session.truth_r:+.2f}R ("
                       f"{'realized' if session.truth == 'realized' else 'replayed'})"
                       if session.truth_r is not None else ""),
        # Graded without an R (a repeat, no bars, no risk to measure):
        # the grader is done with it, and the card says why.
        "grade_notes": session.grade_notes or "nothing to grade",
        # THE HAND and THE PEOPLE'S MOOD at entry (2026-10-16); "" for a
        # sitting before them
        "hand_line": hand_line(session, emperor),
        "mood_line": (f"The people's mood at entry: {session.mood}."
                      if session.mood else ""),
        "footer": FOOTER_WORDS})
    return p


def session_for_trade(trade):
    """The newest sitting on a trade row, as a dict, or None."""
    from ai_agents.council_models import CouncilSession
    s = (CouncilSession.objects.filter(trade=trade)
         .order_by("-created_at").first())
    return session_payload(s) if s is not None else None


def voice_weights(regime: str, asset_class: str) -> dict:
    """{voice: weight dict} for the ten voices (ai_agents/council_grading)."""
    from ai_agents.council_grading import voice_weights as _vw
    return {"schema_version": COUNCIL_SCHEMA_VERSION,
            **_vw(regime, asset_class)}


def record_matrix(asset_class: str = "") -> dict:
    from ai_agents.council_grading import record_matrix as _rm
    return _rm(asset_class=asset_class)
