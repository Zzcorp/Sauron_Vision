# -*- coding: utf-8 -*-
"""THE BOOK OF SAURON: the words of /book/, as data (2026-09-27).

The operator (2026-09-27): a "Sauron Bible / book" page beside the Wall,
in the public part of the site, that tells the story and the current
work.

This module is the page's whole public text, and it is public itself:
this repository is. templates/landing/the_book.html lays it out and
core/views_book.py fills in the counted numbers, so the next batch that
has something to say adds a line here, not a page there:

  * CHAPTERS: the numbered chapters in reading order. Each names the kind
    of block the template draws under its prose ("facts", "facets",
    "circuit", "principles", "timeline", "progress", "closing").
  * ERAS and MILESTONES: the road so far. Every milestone carries the day
    it happened and the short hash of the commit it comes from;
    tests/test_the_book.py holds each hash to the history as it stood
    when this was written (the container has no .git to ask).
  * IN_PROGRESS and GO_LIVE: the work on the bench, always said as in
    progress and never as done.
  * LEXICON: the words a plain reader meets on the way.

The page's one staff-only chapter is NOT here, nor anywhere in git: it is
private, and core.views_book reads it at runtime, from a file outside the
repository, for a signed-in staff user only (see that module).

THE RULES THIS TEXT IS WRITTEN UNDER (the test file walks them):
  1. NUMBERS. A count the platform measures comes from core.wall_facts as
     a {key} placeholder the view formats, never typed here: this page
     must not repeat the "667 tests green" the Wall once carried. Any other
     figure is a dated fact from the history or a default dated in its
     chapter.
  2. PUBLIC. The page is served to anyone and this file is published. No
     name, no whereabouts, no account figure, no identifier, no ticker
     held, no host, no command, no key.
  3. WORDS. English, plain and warm. Every sentence is traceable to the
     code, to a commit or to the French book verified on 2026-09-26.
"""

#: The day this book was written, in words and as a date.
WRITTEN = "2026-09-27"
WRITTEN_WORDS = "27 September 2026"

HERO = {
    "badge": "Written 27 September 2026",
    "title_lead": "The Book of",
    "title_accent": "Sauron",
    "subtitle": "The story · the machine · the road so far",
    "lede": (
        "Where the machine comes from, what it is made of, how a trade is "
        "born inside it, the rules that keep it honest, and every step of "
        "the road it has travelled so far."),
}

#: The four counts under the eye: core.wall_facts keys, in order.
HERO_STATS = [
    {"key": "tests_green", "label": "Automated tests passing"},
    {"key": "evaluators", "label": "Signal evaluators"},
    {"key": "instruments", "label": "Instruments tracked"},
    {"key": "broker_adapters", "label": "Broker adapters"},
]

#: The strip under the six pictures: core.wall_facts keys, in order.
COUNTED = [
    {"key": "bots", "label": "Bots configured"},
    {"key": "signals_graded", "label": "Signals graded"},
    {"key": "trades_graded", "label": "Trades graded"},
    {"key": "agent_calls_graded", "label": "Predictions graded"},
    {"key": "chain_length", "label": "Entries in the audit chain"},
    {"key": "components", "label": "Parts under a switch"},
]


# ── The chapters ────────────────────────────────────────────────────────────

CHAPTERS = [
    {
        "id": "origin",
        "numeral": "I",
        "nav": "The origin",
        "title": "Where Sauron comes from",
        "kicker": (
            "A project born on 5 April 2026 from one simple idea: a machine "
            "that sees everything. Along the way it learned to believe only "
            "what it measures."),
        "paragraphs": [
            ("Sauron Vision was born on 5 April 2026. That day a first "
             "version went online, and it already held the heart of the "
             "idea: artificial-intelligence agents, alerts, a tool that "
             "tests strategies on the past, signals, and a news collector."),
            ("Three days later came the first trading bot, connected to "
             "Binance, a cryptocurrency exchange, behind a PIN code. Then, "
             "within a few days: an emergency stop button, a simulator that "
             "trades without real money, circuit breakers, and a public "
             "front page, the Wall."),
            ("The code borrows its names from The Lord of the Rings: "
             "“Amon Hen” for the first section of the menu, "
             "“Gollum” for the guide who knows the way to Mordor. "
             "On its public page, Sauron presents itself as the all-seeing "
             "trading intelligence platform."),
            ("Why build it? To trade on its own, across several families of "
             "investments, in a closed loop: form a view, filter the risk, "
             "place the order, grade the result, and use that grade for the "
             "next decision. No black box: every step can be inspected."),
            ("The history of the code is kept in commits, the dated records "
             "of every change: 304 of them by the time this book was "
             "written. There were 45 in April, then none until August, then "
             "134 in August and 125 in September, each counted on the day "
             "its record carries. Since 9 August every one of them has been "
             "co-written with Claude, and most of the work on real money "
             "dates from September."),
        ],
        "kind": "facts",
        "items": [
            {"value": "5 April 2026",
             "text": ("The first commit: “Sauron Vision — initial "
                      "deploy”.")},
            {"value": "304",
             "text": "commits by the time this book was written."},
            {"value": "259",
             "text": ("of them co-written with Claude: every one since "
                      "9 August 2026.")},
            {"value": "{tests_green}", "count": "tests_green",
             "text": ("automated tests passing at the last full run, the "
                      "figure the Wall publishes.")},
        ],
    },
    {
        "id": "machine",
        "numeral": "II",
        "nav": "What it is",
        "title": "Sauron in six pictures",
        "kicker": (
            "An eye that watches, bots that act, gates that say no, a brain "
            "that grades itself, pages to see everything, and messages to "
            "tell it."),
        "paragraphs": [
            ("Sauron Vision is an automated trading platform. Trading means "
             "buying investments and selling them later (shares, "
             "currencies, gold, cryptocurrencies) to gain on the difference "
             "in price. With real money, Sauron always goes through a "
             "broker, the intermediary that holds the account and carries "
             "out the orders; in its own simulation it does everything "
             "itself, with no broker at all. Today that broker is eToro."),
            ("Picture a small team in which each member has one job. Nobody "
             "does everything, and everyone is checked by the others."),
            ("One rule runs through every internal page: what has not been "
             "measured is never shown as true. An unknown figure is written "
             "as a dash, never as a zero. Only the public pages, the Wall "
             "and this book, show 0 when a counter fails, and that is "
             "deliberate, because they are the platform's public front "
             "door."),
            ("Behind these six pictures stand {components} parts that can "
             "each be switched on or off, {shell_commands} registered "
             "commands, and {tests_green} automated tests: small programs "
             "that check the code does what it says."),
        ],
        "kind": "facets",
        "items": [
            {"glyph": "eye", "title": "The eye",
             "text": ("The Oculus, the first page of the menu. It answers a "
                      "single question: is the machine turning? It sets the "
                      "platform's cycles side by side, owns no data of its "
                      "own, and always keeps three cases apart: a measured "
                      "number, “not measured”, and a part that is "
                      "switched off.")},
            {"glyph": "bots", "title": "The bots",
             "text": ("Each bot is tied to one family of investments: shares "
                      "and ETFs, currencies, commodities, cryptocurrencies, "
                      "options. It either trades in Sauron's own simulation "
                      "(“paper”) or is connected to the broker "
                      "(“live”), and a live bot trades real money "
                      "only once the broker's demo box is unticked. A new bot "
                      "is born switched off, in simulation.")},
            {"glyph": "gates", "title": "The gates",
             "text": ("Before every order, a line of checks can say no: the "
                      "proof for that family of investments, what the broker "
                      "allows, the money available, the day's loss, the "
                      "concentration, the circuit breakers. When a gate says "
                      "no, nothing leaves. Above them all, an emergency stop "
                      "switches every bot off, then tries to close "
                      "everything.")},
            {"glyph": "brain", "title": "The brain",
             "text": ("Sauron's Mind reads, summarises, and makes predictions "
                      "that can be checked, each one graded later. An agent "
                      "that is often wrong loses influence. The brain only "
                      "advises: it can pause a rule, and it never sends an "
                      "order.")},
            {"glyph": "pages", "title": "The pages",
             "text": ("The Operations Center, with its live, portfolio, "
                      "history and bots tabs; the Treasury, which shows "
                      "where the money is; each trade's own page; and the "
                      "public Wall.")},
            {"glyph": "messages", "title": "The messages",
             "text": ("A Telegram group where Sauron announces what it does: "
                      "every opening, every closing, every refusal and every "
                      "problem, in English.")},
        ],
    },
    {
        "id": "circuit",
        "numeral": "III",
        "nav": "How a trade is born",
        "title": "How a trade is born, lives and ends",
        "kicker": "Ten steps, from a view to a graded result.",
        "paragraphs": [
            ("A trade is a bet on a price: you buy an investment expecting "
             "it to rise, or sell it expecting it to fall, and later you "
             "close it. Here is the real path of a trade inside Sauron, in "
             "order."),
            ("Every five minutes, each bot that is switched on takes a turn. "
             "It first watches over what it already holds, then checks that "
             "it is still allowed to open something, and only then looks "
             "through its instruments."),
        ],
        "kind": "circuit",
        "items": [
            {"title": "The signal",
             "text": ("A signal is a dated view on an instrument, up or down, "
                      "with a score. Several families of rules produce them: "
                      "reading the charts, the tone of the news, the economy, "
                      "the companies' fundamentals.")},
            {"title": "The vote",
             "text": ("It takes recent signals, 24 hours old at most and "
                      "scored at least 0.60, and a vote that leans far enough "
                      "one way: each rule weighs according to its past "
                      "results, and opposing views subtract. By default a "
                      "single strong signal can be enough. Rules still "
                      "“in research” are watched, but do not "
                      "vote.")},
            {"title": "The stop and the target",
             "text": ("The stop is the price at which the loss is cut; the "
                      "target, the price at which the gain is taken. Both "
                      "follow the instrument's normal restlessness: the stop "
                      "at 1.5 times its average move, the target at 3 times. "
                      "The aim is a gain twice the accepted loss, and costs "
                      "are deducted before a trade is judged worth "
                      "taking.")},
            {"title": "The size",
             "text": ("The quantity is never a fixed amount. It is computed "
                      "so that, if the stop is hit, the loss is a precise "
                      "share of the bot's own reserve: 0.25% by default. "
                      "That is “1R”, one unit of risk, the same on "
                      "every trade by default; in the attack mode, "
                      "conviction sets each trade at a half, three quarters "
                      "or all of it.")},
            {"title": "The gates",
             "text": ("Before anything is sent: the proof for the class, the "
                      "broker's sheet for that instrument, the money "
                      "available, the day's maximum loss, the total "
                      "exposure, the concentration on one instrument, the "
                      "same bet hidden under several names, the circuit "
                      "breakers. A single no is enough, and nothing "
                      "leaves.")},
            {"title": "The order, protected at the broker",
             "text": ("The order leaves in one piece, with its stop and its "
                      "target placed at the broker. eToro keeps them on its "
                      "side, so the trade stays protected even if Sauron "
                      "stops. eToro may move the levels it receives, "
                      "sometimes far: on 25 September it shifted them "
                      "slightly, and on 26 September a stop sent 5% from the "
                      "price was held nearly 10% from it. When it moves a "
                      "bot's stop, the fill message says so. If a real-money "
                      "trade ever loses its stop, an alert goes out, even "
                      "when the bots' messages are muted; only the shared "
                      "quiet hours, when set, hold it back.")},
            {"title": "The watch",
             "text": ("Every 15 minutes during market hours, from 13:00 to "
                      "21:45 UTC, Sauron compares what it holds with what "
                      "the broker holds. That is one of two ways it learns "
                      "that a stop or a target was hit; the five-minute turn "
                      "also compares the price with both.")},
            {"title": "The close",
             "text": ("Sauron first sends the closing order to the broker. "
                      "If the broker does not answer, the line waits as "
                      "“close pending” and the close is tried "
                      "again. Nothing is ever written “closed” "
                      "without the broker's answer.")},
            {"title": "The announcement",
             "text": ("The opening and the closing arrive in the Telegram "
                      "group, in English; the closing says its result and "
                      "how it ended: target reached, stopped out, time "
                      "limit, expired or closed by hand.")},
            {"title": "The grade",
             "text": ("Every closed trade is graded (target reached, stopped "
                      "out, closed by hand, expired or time limit) with its "
                      "result in R. Those grades decide which rules climb "
                      "and which fall.")},
        ],
        "loop": "The grade feeds the next decision",
        "after": [
            ("The last step closes the loop. A rule that wins climbs a "
             "ladder of four rungs: research (no trades at all), "
             "simulation, small real (a quarter of the size), full real. A "
             "rule that falls apart climbs back down on its own."),
        ],
        "note": ("The settings quoted in this chapter are the platform's "
                 "defaults as verified on 26 September 2026."),
    },
    {
        "id": "principles",
        "numeral": "IV",
        "nav": "The principles",
        "title": "The rules that make Sauron trustworthy",
        "kicker": "Each one was learned, often from one precise incident.",
        "paragraphs": [
            ("Sauron handles money, so its rules of conduct matter more "
             "than its investment ideas. Most of them were born from a "
             "mistake avoided just in time, or from a measurement that "
             "contradicted a certainty."),
            ("They bind the machine, Claude, and everyone who operates it. "
             "They are not there to make things harder: they are there so "
             "that no loss ever comes from something we only believed we "
             "knew."),
        ],
        "kind": "principles",
        "items": [
            {"title": "Measure before believing",
             "text": ("Only the broker can contradict the code. On 22 "
                      "September, the connection to eToro, written from the "
                      "documentation, met a real key: of its four layers, "
                      "three were wrong, while 7,459 tests and four reviews "
                      "held them to be right. Since then, anything the "
                      "broker has not confirmed is treated as a "
                      "hypothesis.")},
            {"title": "A claim is not a measurement",
             "text": ("On the morning of 23 September, everything at IBKR "
                      "was believed closed. The moment the broker answered, "
                      "the platform measured the opposite, with no "
                      "protective stop on what remained. Had "
                      "“closed” been written down on someone's "
                      "word, it would have stayed unwatched. Nobody ever "
                      "writes “closed” by hand.")},
            {"title": "Unknown is never zero",
             "text": ("There are three answers: measured, measured at zero, "
                      "and unknown. On the internal pages, whatever could "
                      "not be measured reads “not measured” or a "
                      "dash, never 0. The public Wall once showed "
                      "“667 tests green” and invented prices; all "
                      "of it was replaced with real counts. The public pages, "
                      "the Wall and this book, keep a single, deliberate "
                      "exception: a failed counter shows 0 there.")},
            {"title": "Refuse rather than trim",
             "text": ("When a safety rule says no, nothing leaves. An order "
                      "that would lock too much money at the broker is "
                      "refused, not shrunk. A refused leverage is never "
                      "quietly swapped for an order without it.")},
            {"title": "Read the refusal, never guess",
             "text": ("When the broker or the platform says why it refuses, "
                      "that text is read first. On 7 September, three false "
                      "causes were invented while the log held the true one. "
                      "Every false lead costs time.")},
            {"title": "Design, then attack, before touching money",
             "text": ("Every change that can send or size an order is first "
                      "designed, then attacked by three reviewers from three "
                      "angles (the money, the written contract, and "
                      "“would you ship this tonight?”), then by a "
                      "critic. On 20 September this process caught the "
                      "platform's worst defect: every exit on real eToro "
                      "would have opened an opposite trade instead of "
                      "closing one.")},
            {"title": "One proof per family",
             "text": ("A family of investments may send an order to eToro "
                      "only after its proof: an order filled and then "
                      "closed, written into the code with its test. It is "
                      "deliberately not a box to tick, since nothing can "
                      "tick a proof that was never measured. When the gate "
                      "arrived on 24 September the list was empty and every "
                      "eToro order was refused, even in demo; crypto earned "
                      "the first proof, on the real account: measured on 26 "
                      "September, written into the code on the 27th.")},
            {"title": "The PIN guards real money",
             "text": ("On the pages, the trading PIN is asked for at the "
                      "gestures that open the way to real money: unticking "
                      "the broker's demo box, switching on a real bot, "
                      "placing or closing a real order by hand, applying a "
                      "capital plan. Switching a bot off never asks for "
                      "it.")},
            {"title": "The guards watch the machine",
             "text": ("Since 27 September the platform has the Morgul "
                      "guards: a watchdog outside the engine that checks "
                      "every five minutes for what Sauron must never do (a "
                      "booking while its market is shut, a real-money trade "
                      "with no stop at the broker, a close stuck pending, a "
                      "price far from the market), tells the group, and can "
                      "only ever stop a bot. Both of its switches are off on "
                      "arrival.")},
            {"title": "No capital moves without a human",
             "text": ("The parts that could move capital on their own, the "
                      "share allocator and the capital desk, run in shadow: "
                      "they propose and apply nothing until weeks of grades "
                      "have been read. Applying an allocation plan takes the "
                      "PIN on the page, or an explicit confirmation in a "
                      "command. One exception, off by default: a switch that "
                      "would let share cuts apply themselves after a "
                      "shock.")},
            {"title": "An error kept on the cautious side",
             "text": ("One calculation of a share of capital is wrong, but "
                      "always towards “too small”. Every fix tried "
                      "broke one of the platform's guarantees: one doubled a "
                      "reserve at a stroke, another split the accounts in "
                      "two, the third disarmed the automatic brake on "
                      "losses. It stays as it is: breaking a guarantee to "
                      "correct a caution is not an improvement.")},
        ],
    },
    {
        "id": "road",
        "numeral": "V",
        "nav": "Milestones",
        "title": "The road so far",
        "kicker": (
            "From a first bot in April to the first measured orders at "
            "eToro in September, one dated step at a time."),
        "paragraphs": [
            ("Sauron was built in waves. First, seven days of momentum in "
             "April. Then four months of work outside the history, recorded "
             "all at once on 9 August. Then, from August, an almost daily "
             "build, co-written with Claude, and often reviewed and attacked "
             "by adversarial reviewers."),
            ("September was the month of real money: the first orders at "
             "IBKR and their refusals, the search for a broker that lets the "
             "server work on its own, the move to eToro, the first eToro "
             "orders in demo, and then the first proofs."),
        ],
        "kind": "timeline",
    },
    {
        "id": "in-progress",
        "numeral": "VI",
        "nav": "In progress",
        "title": "What is being built now",
        "kicker": (
            "On 27 September 2026 these were written and reviewed, not yet "
            "landed."),
        "paragraphs": [
            ("Every batch is first designed, then attacked, then checked by "
             "thousands of automated tests before it lands. Each line here "
             "is said as in progress until then, and moves to the road so "
             "far, with its date, the day it lands."),
        ],
        "kind": "progress",
        "road_title": "The road to real money",
        "after": [
            ("The aim is written in the plan for the move to eToro: every "
             "class traded at eToro, on its own, with IBKR retired. The "
             "second half is done: IBKR has been retired since 23 "
             "September. The first half is being built now, one class after "
             "another."),
            ("Why eToro? Because it lets the server work alone: two keys "
             "are enough, with no human sign-in every day. IBKR asked for a "
             "confirmation on a phone almost daily, and on 16 September its "
             "two-factor sign-in stayed stuck in a loop. The move has a "
             "price, accepted with open eyes: no broker is left for "
             "options."),
            ("The real limit is not money but calibration: knowing which "
             "rules truly work. Hence the research fleet trading pretend "
             "money, the graded predictions, the register of proofs, and a "
             "generator that proposes new strategies every week. Each one "
             "is born inactive, at the research stage, until a human "
             "approves it."),
        ],
    },
    {
        "id": "closing",
        "numeral": "VII",
        "nav": "Closing",
        "title": "A last word",
        "kicker": "Look, measure, and stop when something does not add up.",
        "paragraphs": [
            ("Sauron has been built since 5 April, commit after commit. It "
             "is not finished, and it says so: what is proven is written "
             "down, and what is not is refused."),
            ("Nobody needs to be an expert to follow it. It is enough to do "
             "what Sauron does itself: look, measure, take nothing on "
             "trust, and stop when something does not add up. Switching a "
             "bot off is always allowed, and it never asks for a PIN."),
            ("The next pages of this book will be written the same way, one "
             "dated line at a time."),
        ],
        "kind": "closing",
    },
]


# ── The road so far ─────────────────────────────────────────────────────────

ERAS = [
    {"id": "first-days", "span": "5 – 11 April 2026",
     "title": "The first seven days",
     "summary": ("The first version goes online on 5 April. On the 8th comes "
                 "the first bot, on Binance, behind a PIN code; then the "
                 "emergency stop, simulated trading, the circuit breakers "
                 "and the Wall.")},
    {"id": "outside-history", "span": "11 April – 9 August",
     "title": "Four months outside the history",
     "summary": ("Numbered phases, up to the sixtieth, recorded all at once "
                 "on 9 August: signals that grade themselves, the promotion "
                 "ladder for rules, the brain, bots for shares, currencies, "
                 "commodities and options, and three brokers: Alpaca, OANDA "
                 "and IBKR.")},
    {"id": "wiring", "span": "9 – 18 August",
     "title": "Wiring the chain",
     "summary": ("A single server runs everything, with a step-by-step "
                 "guide. Safeguards that had been built but never called "
                 "are wired in. On 10 August the full chain reaches a "
                 "simulated trade for the first time, costs included; on "
                 "the 18th, evolution starts proposing and testing variants "
                 "of rules.")},
    {"id": "readable", "span": "19 – 31 August",
     "title": "A platform you can read",
     "summary": ("The PIN becomes a real gate. The pages update themselves. "
                 "Money gets a single answer everywhere: reserves, used, "
                 "free. IBKR becomes configurable, and its trades leave "
                 "with a stop placed at the broker.")},
    {"id": "towards-real", "span": "1 – 10 September",
     "title": "First steps towards real money",
     "summary": ("The Long and Short buttons can send real orders, after an "
                 "arming step checked by the PIN. On the 7th, the first real "
                 "order comes back with a mere notice from the broker, "
                 "taken for a refusal: nothing was opened. On the 10th, a "
                 "second refusal, over the broker's account minimum, which "
                 "is now read before the order.")},
    {"id": "measure", "span": "11 – 15 September",
     "title": "Measure before betting",
     "summary": ("A fleet of research bots, in simulation, covers 166 "
                 "symbols. Every prediction becomes a graded claim. The "
                 "capital desk ranks every candidate under one risk budget. "
                 "The Oculus shows whether the machine is turning. On the "
                 "15th a campaign of two to three months in simulation is "
                 "decided; it later gives way to real money, one proven "
                 "class at a time.")},
    {"id": "new-broker", "span": "16 – 20 September",
     "title": "Looking for another broker",
     "summary": ("IBKR's two-factor sign-in stays stuck in a loop on the "
                 "16th. eToro arrives, and two keys are enough, with no daily "
                 "sign-in; Saxo too, with one sign-in the platform then "
                 "keeps alive. The Treasury shows where the money is, the "
                 "interface switches to English, and the retirement of IBKR "
                 "is written down before it is done.")},
    {"id": "etoro-measured", "span": "22 – 23 September",
     "title": "eToro measured, IBKR switched off",
     "summary": ("A real eToro key: the first probe answers “not "
                 "found”, and the connection is corrected from the real "
                 "answers. Switching eToro to real money now asks for the "
                 "PIN. On the 23rd the first eToro orders leave, in demo; at "
                 "IBKR the last trades are closed at the New York open, and "
                 "IBKR is retired.")},
    {"id": "proofs-guards", "span": "24 – 27 September",
     "title": "The proofs and the guards",
     "summary": ("The proof gate refuses any eToro order from a class not "
                 "yet proven. Sauron reads each day what eToro allows, "
                 "instrument by instrument. On the 26th the bots finally "
                 "speak on Telegram and the first real-money orders at "
                 "eToro are sent; on the 27th what they measured is written "
                 "into the code, crypto earns the first proof, and the "
                 "Morgul guards arrive.")},
]

#: One line per milestone: (day, era id, title, one or two sentences,
#: short hash of the commit it comes from). A milestone is dated the day
#: it happened, which can be up to three days before its commit landed.
MILESTONES = [
    ("2026-04-05", "first-days", "The first commit",
     "The first version of Sauron Vision goes online, with AI agents, "
     "alerts, a strategy tester, signals and a news collector.",
     "54e35ba"),
    ("2026-04-08", "first-days", "The first bot, on Binance",
     "The bots arrive, connected to a cryptocurrency exchange, behind a PIN "
     "code.",
     "b3f3e0b"),
    ("2026-04-10", "first-days", "Emergency stop, simulation and the Wall",
     "An emergency stop button, a simulator without real money, circuit "
     "breakers and the public Wall are added.",
     "f7114f4"),
    ("2026-08-09", "outside-history", "Four months, recorded at once",
     "The brain, the bots for shares, currencies, commodities and options, "
     "and the signals that grade themselves land together. From now on, "
     "Claude co-writes the code.",
     "acaa3de"),
    ("2026-08-10", "wiring", "The first simulated trade, costs included",
     "For the first time the whole chain runs from a price to a simulated "
     "trade, and simulated trades pay their costs.",
     "e91eb62"),
    ("2026-08-18", "wiring", "Evolution wakes",
     "The dormant evolution layer becomes a living loop: variants of rules "
     "are proposed, run and graded.",
     "7611cb2"),
    ("2026-08-19", "readable", "The PIN becomes a real gate",
     "The PIN can be typed at last, a forgotten PIN has a way back in, and "
     "an unattended screen locks behind it, enforced by the server.",
     "feb2b10"),
    ("2026-08-19", "readable", "The Wall tells the truth again",
     "Real counts replace invented figures on the public page: the "
     "platform as it is, and no made-up market data.",
     "29bb1d3"),
    ("2026-08-20", "readable", "Pages that move on their own",
     "A session that survives the page, pages that update themselves, and "
     "a brain no longer punished for what it could not measure.",
     "f35e9d0"),
    ("2026-08-25", "readable", "One answer for the money",
     "The money question gets one answer everywhere: reserves, used, free "
     "and cash.",
     "a12325a"),
    ("2026-08-26", "readable", "No IBKR trade leaves unprotected",
     "Orders sent to IBKR now leave with their stop resting at the broker.",
     "eb22386"),
    ("2026-08-28", "readable", "Unmeasured is not zero",
     "The rule enters the pages: what was never measured is never shown as "
     "a zero.",
     "5c864bc"),
    ("2026-09-01", "towards-real", "Long and Short go real",
     "The manual buttons learn to send real orders, refusing first, and "
     "only after an arming step checked by the PIN.",
     "0b6d44a"),
    ("2026-09-07", "towards-real", "The first real order",
     "The first real order sent to IBKR comes back with a mere notice, "
     "taken for a refusal: nothing was opened.",
     "10863a8"),
    ("2026-09-10", "towards-real", "The broker's minimum, read first",
     "A second order is refused over the broker's account minimum; that "
     "floor is now read before the order, not after.",
     "bd4f40e"),
    ("2026-09-11", "measure", "The research fleet",
     "A fleet of research bots starts trading in simulation, fed by a data "
     "source that needs no key.",
     "a920d8d"),
    ("2026-09-11", "measure", "No prose without a claim",
     "Every prediction the brain writes must carry a claim the platform "
     "can grade.",
     "c8c2e79"),
    ("2026-09-12", "measure", "The capital desk",
     "Every candidate of every bot, ranked once, under one risk budget, in "
     "shadow.",
     "56bf344"),
    ("2026-09-12", "measure", "The share allocator",
     "A portfolio that moves with the evidence, shadow first: it proposes, "
     "and a human applies.",
     "475b584"),
    ("2026-09-13", "measure", "The Oculus",
     "A page shows, cycle by cycle, whether the machine is really turning, "
     "and which wheels are engaged.",
     "bfe4625"),
    ("2026-09-15", "measure", "A campaign in simulation",
     "Two to three months in simulation are planned, to arrive with "
     "evidence; the plan later gives way to real money, one proven class "
     "at a time.",
     "530e18d"),
    ("2026-09-17", "new-broker", "eToro joins the fleet",
     "A broker whose two keys let the server work without a human at the "
     "door.",
     "dc08cdf"),
    ("2026-09-18", "new-broker", "Saxo signs in once",
     "One sign-in, and the platform keeps the door open from then on.",
     "7aaf06d"),
    ("2026-09-20", "new-broker", "The platform speaks English",
     "The interface switches to English, and a close really closes.",
     "a72b756"),
    ("2026-09-20", "new-broker", "A close is not an opposite order",
     "The review catches the worst defect: on real eToro every exit would "
     "have opened an opposite trade. It is fixed before any real order.",
     "d3c735f"),
    ("2026-09-20", "new-broker", "The Treasury",
     "A page shows where the money is.",
     "1da56db"),
    ("2026-09-20", "new-broker", "IBKR's retirement, written first",
     "The retirement of IBKR is written down before it is done.",
     "aa53b4d"),
    ("2026-09-22", "etoro-measured", "eToro measured with a real key",
     "The first probe answers “not found”; every path is "
     "corrected from the real answers instead of the documentation.",
     "ea0bb54"),
    ("2026-09-23", "etoro-measured", "The demo box is guarded",
     "Unticking the demo box is the switch to real money, so it now asks "
     "for the PIN.",
     "adcfdbd"),
    ("2026-09-23", "etoro-measured", "First eToro orders, in demo",
     "The first eToro orders are sent on the demo account and closed; the "
     "three defects they measured are fixed and pinned.",
     "0f9909c"),
    ("2026-09-23", "etoro-measured", "IBKR retired",
     "The retirement of IBKR is planned and attacked first; at the New York "
     "open the last trades are closed, and later that day IBKR is retired "
     "from the platform.",
     "9b8d958"),
    ("2026-09-24", "proofs-guards", "The proof gate",
     "Every eToro order is refused while its class has not proven, in "
     "demo, that it can open and close.",
     "caf0811"),
    ("2026-09-25", "proofs-guards", "What eToro allows",
     "Sauron reads each day, instrument by instrument, the floor, the caps "
     "and the leverage eToro allows; the first proof begins in demo.",
     "7759c43"),
    ("2026-09-26", "proofs-guards", "The bots speak on Telegram",
     "Bot openings and closings reach the Telegram group at last.",
     "37836e1"),
    ("2026-09-26", "proofs-guards", "Only real faults",
     "The morning digest reports real faults only, each part judged on its "
     "own rhythm, in English.",
     "48689f7"),
    ("2026-09-26", "proofs-guards", "Sauron answers its group",
     "Asked in the group, Sauron can report its status and explain why it "
     "did not trade, in English; the one thing it may change is the brake. "
     "Switched off on arrival.",
     "daf1343"),
    ("2026-09-26", "proofs-guards", "Every signal announced",
     "Every new signal, from every rule, is announced once on Telegram, and "
     "every message follows one English house style.",
     "097e72c"),
    ("2026-09-26", "proofs-guards", "Each instrument in eToro's spelling",
     "Every instrument is sent under eToro's own name for it; a look-alike "
     "is refused, never adopted.",
     "9df34a7"),
    ("2026-09-26", "proofs-guards", "Conviction sets the risk",
     "Leverage per class, and an attack mode: conviction sets the risk, "
     "while the multiplier only sets the cash the broker locks, never past "
     "what a demo proof pinned.",
     "2882a94"),
    ("2026-09-27", "proofs-guards", "The real side measured",
     "The first real-money orders at eToro, two tiny ones sent the evening "
     "before, measured sending, withdrawing, filling and closing on the real "
     "account; what they taught is now written into the code.",
     "ab47af2"),
    ("2026-09-27", "proofs-guards", "A plain page for every trade",
     "Each trade's page opens on a plain summary: the result live, one "
     "close button with a preview and the PIN, and the technical record "
     "folded underneath.",
     "92d1c11"),
    ("2026-09-27", "proofs-guards", "The probes read their own market",
     "A probe is called stale only when it falls behind its own market, "
     "counted from the bar's close: a healthy weekend no longer reads as a "
     "fault.",
     "0a9133a"),
    ("2026-09-27", "proofs-guards", "Switching off says what it leaves",
     "A switched-off bot no longer manages what it holds, and every way of "
     "switching one off now says so.",
     "8db05d5"),
    ("2026-09-27", "proofs-guards", "The Morgul guards",
     "A watchdog outside the engine checks every five minutes for what "
     "Sauron must never do, tells the group, and can only ever stop a bot. "
     "Both switches are off on arrival.",
     "cf30b5d"),
    ("2026-09-27", "proofs-guards", "No simulated fill on a shut market",
     "A simulated trade never fills or exits while its market is shut, and "
     "a shut market's last price is no longer stamped as fresh.",
     "a92454a"),
    ("2026-09-27", "proofs-guards", "The briefs read the real book",
     "The morning brief and the evening summary count every trade the "
     "platform holds: real money first, then the simulated book.",
     "c3d12e9"),
    ("2026-09-27", "proofs-guards", "The suite, counted",
     "The full suite runs once on the day's combined work, and its count "
     "becomes the number the Wall publishes.",
     "3994ffc"),
]


# ── The bench ───────────────────────────────────────────────────────────────

#: Work written and reviewed but not landed on 2026-09-27. Said as in
#: progress; a line moves to MILESTONES, with its hash, the day it lands.
IN_PROGRESS = [
    {"title": "The news band keeps its cards",
     "text": ("After a page had been open for a long time, hovering a "
              "headline in the scrolling news band at the top could open "
              "nothing. The cause is found and the fix is written, so the "
              "band's cards stay alive for as long as the page is open.")},
    {"title": "Telegram messages written for people",
     "text": ("Messages that read like a log line become one plain sentence "
              "with the facts beneath it, the technical record folded, and "
              "a button that opens the trade's own page.")},
    {"title": "The Monday game plan, in full",
     "text": ("The briefing page will show the Monday game plan in full, "
              "every line of it.")},
]

#: The road to real money, in order. Every step is still ahead.
GO_LIVE = [
    {"title": "A proof for every class, in demo",
     "text": ("Each remaining class earns its proof in the demo account, at "
              "the leverage it will actually use: an order filled, then "
              "closed, and written into the code with its test.")},
    {"title": "Real money only with the PIN, in person",
     "text": ("Unticking the demo box is the switch to real money. It asks "
              "for the trading PIN, typed in person on the page and never "
              "sent in a message.")},
    {"title": "One class at a time",
     "text": ("One class ticked at a time and one configuration switched on "
              "per session; then a full five-minute cycle and its Telegram "
              "message are watched before the next.")},
]


# ── The words ───────────────────────────────────────────────────────────────

LEXICON = [
    {"term": "Commit", "plain": "A dated record of one change to the code."},
    {"term": "Broker",
     "plain": ("The intermediary that holds the account and carries out the "
               "orders to buy and sell. Today eToro; before it, IBKR "
               "(Interactive Brokers).")},
    {"term": "Demo and real",
     "plain": ("eToro's two worlds: a virtual account in pretend money, where "
               "most proofs are made, and the real account. The demo box "
               "chooses, and unticking it asks for the PIN. Inside Sauron, "
               "“paper” is its own simulation, and "
               "“live” means sent to the broker.")},
    {"term": "The Oculus",
     "plain": ("The first page of the menu: it shows, cycle by cycle, "
               "whether the machine is really turning.")},
    {"term": "Bot",
     "plain": ("A program that trades one family of investments. Every five "
               "minutes it watches over what it holds, then looks for "
               "something to open.")},
    {"term": "Signal",
     "plain": ("A dated view on an instrument, up or down, with a confidence "
               "score.")},
    {"term": "Stop and target",
     "plain": ("The stop is the price at which a trade is cut to limit the "
               "loss; the target, the price at which the gain is taken. For "
               "an order sent to the broker, both rest at the broker.")},
    {"term": "R, the unit of risk",
     "plain": ("The loss planned if the stop is hit. A trade at +2R gained "
               "twice what it risked; at −1R, it lost exactly what was "
               "planned.")},
    {"term": "Leverage",
     "plain": ("Taking a larger trade than the money put down. It changes "
               "the money the broker locks and the financing costs, never "
               "the loss at the stop, which depends on the risk chosen.")},
    {"term": "Margin",
     "plain": "The money the broker locks to keep a trade open."},
    {"term": "ETF",
     "plain": ("A basket of investments listed on an exchange, bought like a "
               "single share.")},
    {"term": "Asset class",
     "plain": ("A family of investments: shares, ETFs, indices, currencies "
               "(forex), commodities, cryptocurrencies, options.")},
    {"term": "Proof",
     "plain": ("An order filled and then closed, whose values are written "
               "into the code with their test. Without one, a class cannot "
               "send any order to eToro.")},
    {"term": "Trading PIN",
     "plain": ("The code that authorises real-money actions on the pages. "
               "Switching a bot off never asks for it.")},
    {"term": "The brake",
     "plain": ("Switching a bot off. It does not close what the bot holds: "
               "those trades keep their stop at the broker.")},
]
