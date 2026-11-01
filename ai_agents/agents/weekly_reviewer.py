"""Weekly Reviewer Agent — deep analysis of the past week."""
from ai_agents.base_agent import BaseAgent


class WeeklyReviewerAgent(BaseAgent):
    agent_name = "weekly_reviewer"
    default_tier = "deep"
    # THE LONGEST ANSWER ON THE PLATFORM (2026-11-01). Ten sections, and
    # the tables run as long as the input lets them: WEEK_MAX_ROWS (40)
    # rows a table (ai_agents/tasks.py) — each book's rules in two tables
    # (performance and grades, three books), the skips, the findings and
    # the brakes, nine tables at ~40 tokens a row (14,400), plus the prose
    # sections. On the 32,000 every call had, its thinking at high effort
    # would share what such an answer leaves; the provider now adds the
    # thinking room on top of this (max_tokens 40,192 on a thinking
    # model). Billed only when written.
    answer_tokens = 16384

    def get_system_prompt(self) -> str:
        from ai_agents.calibration import CALLS_INSTRUCTION as _ci

        def _calls_instruction():
            return _ci
        # THE LIVE BOOK (2026-10-08): the review used to grade "each active
        # strategy" — wizard plans nothing executes — with an empty MACRO
        # DATA. It reads what the bots and the hand lane closed, live, demo
        # and paper apart (the platform's three worlds: a broker's demo
        # account is not real money), and the measured macro
        # (ai_agents/tasks.py, weekly_book_context).
        return """You are the Weekly Reviewer for Sauron Vision.
Every Saturday, you perform a deep analysis of the trading week.

Your review must cover:
1. PERFORMANCE: what the book closed this week, from the LIVE BOOK (real money),
   the DEMO BOOK (simulated at a broker's demo account) and the PAPER BOOK
   (simulated): per rule and asset class, the graded trades, the win rate and
   the expectancy in R. Keep the three books apart and labelled in every
   sentence and every table, and never add them together: a demo or paper
   result is not money made or lost. rule_name manual_take is the hand lane,
   the trades the operator took by hand.
2. THE SCORECARD: per lane (the bots, the hand lane) and per book, read the
   win rate, the average win and loss, the expectancy and the diagnosis
   sentence; say which of the three numbers is losing, and whether winners
   were closed by hand or stops did not hold.
3. SIGNAL QUALITY: Which signals led to good trades? Which were false positives?
4. MACRO REGIME: from MACRO DATA only — the latest FRED observations (their
   date, and the previous observation with ITS date: a monthly or quarterly
   series is compared with its previous release, not a week before; say the
   span) and the measured market stress (its level, score and reason, and
   whether crisis mode is on, which is when it sizes real-money orders).
   Never from memory. A series marked missing has no observation: say so.
5. GRADES: grade each rule or lane that TRADED this week, A-F, on its graded
   trades (n), live and paper graded apart. Fewer than 5 graded trades is "too
   few to grade". There is no strategy list: the platform's wizard plans
   execute nothing, and a plan that never traded is never graded.
6. WHY THE BOTS DID NOT TRADE: from SKIPS, the dominant skip codes per bot and
   their diagnosis (the counters are cumulative; read the distribution).
7. GUARDS AND BRAKES: every Morgul finding still standing (new this week or
   older, as first_seen says) and every bot a brake or the kill switch
   stopped this week, and what that means for next week.
8. PARAMETER ADJUSTMENTS: Should any signal thresholds be adjusted?
9. NEXT WEEK OUTLOOK: Key events, levels to watch, potential setups.
10. RISK ASSESSMENT: Portfolio health, concentration risks, correlation concerns.

Every snapshot names its book ("portfolio"). A snapshot whose "sizing_note" is set
was produced by paper pools larger than the book: its drawdown and percentages
measure the book, not the money that sized the positions — say so, and never
grade it as a loss of capital.

Results are in R (multiples of the risk each trade opened with). Never quote an
account balance.

Be thorough, analytical, and specific. Reference actual numbers and events.""" + _calls_instruction()

    def build_context(self, **kwargs) -> str:
        return f"""Weekly data for review:

LIVE BOOK (real money, this week's closes): {kwargs.get('live_book', 'N/A')}
DEMO BOOK (simulated at a broker's demo account, not money; this week's closes): {kwargs.get('demo_book', 'N/A')}
PAPER BOOK (simulated, this week's closes): {kwargs.get('paper_book', 'N/A')}
SCORECARD (per lane, per book: live, demo, paper): {kwargs.get('scorecard', 'N/A')}
SKIPS (why the bots did not trade): {kwargs.get('skips', 'N/A')}
GUARDS (Morgul's standing findings and the brakes of the week): {kwargs.get('guards', 'N/A')}
PORTFOLIO SNAPSHOTS: {kwargs.get('snapshots', 'N/A')}
SIGNALS GENERATED: {kwargs.get('signals', 'N/A')}
MACRO DATA (FRED and the measured market stress): {kwargs.get('macro', 'N/A')}
KEY NEWS: {kwargs.get('news_digest', 'N/A')}
ECONOMIC EVENTS: {kwargs.get('economic_events', 'N/A')}"""

    def parse_response(self, raw_response: str) -> dict:
        return {"review": raw_response}
