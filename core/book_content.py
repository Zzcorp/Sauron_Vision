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
    tests/test_the_book.py holds each hash to the history as it stood at
    each edition, pasted there in two blocks, the first edition's and
    this one's (the container has no .git to ask).
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

#: The day this book was first written, and the day of this edition, in
#: words and as dates. The bench's kicker and the circuit's note carry the
#: edition's day: both are re-read, and re-dated, with every edition.
FIRST_WRITTEN = "2026-09-27"
FIRST_WRITTEN_WORDS = "27 September 2026"
WRITTEN = "2026-10-08"
WRITTEN_WORDS = "8 October 2026"

HERO = {
    "badge": "First written %s · revised %s" % (FIRST_WRITTEN_WORDS,
                                                WRITTEN_WORDS),
    "title_lead": "The Book of",
    "title_accent": "Sauron",
    "subtitle": "The story · the machine · the road so far",
    "lede": (
        "Where the machine comes from, what it is made of, how a trade is "
        "born inside it, what stands around it, the rules that keep it "
        "honest, and every step of the road it has travelled so far."),
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
    # 2026-10-08: "in the watchdog", not "on the watch", since the guards
    # ship switched off; and the proving ground's verdicts, a table count.
    {"key": "guards", "label": "Guards in the watchdog"},
    {"key": "proving_verdicts", "label": "Proving verdicts written"},
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
             "of every change: 304 of them by 27 September 2026, when this "
             "book was first written. There were 45 in April, then none "
             "until August, then 134 in August and 125 in September up to "
             "that day, each counted on the day its record carries. Since "
             "9 August every one of them had been co-written with Claude, "
             "and most of the work on real money dated from September."),
            ("From 29 September the work arrived in batches, each "
             "one designed, reviewed and run against the whole suite of "
             "tests before it was merged. The first week of October brought "
             "the proving ground, the care of open trades, and a clock and "
             "a venue check in front of every entry; the road below carries "
             "each step with its day."),
        ],
        "kind": "facts",
        "items": [
            {"value": "5 April 2026",
             "text": ("The first commit: “Sauron Vision — initial "
                      "deploy”.")},
            {"value": "304",
             "text": ("commits by 27 September 2026, when this book was "
                      "first written.")},
            {"value": "259",
             "text": ("of them co-written with Claude: every one from "
                      "9 August 2026 to that day.")},
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
                      "proof for that family of investments, the rule's own "
                      "verdict, the clock, the venue's health, a quote that "
                      "looks like a market, what the broker allows, the money "
                      "available, the day's loss, the risk already open, the "
                      "concentration, the circuit breakers. When a gate says "
                      "no, nothing leaves. Above them all, an emergency stop "
                      "switches every bot off, then tries to close "
                      "everything.")},
            {"glyph": "brain", "title": "The brain",
             "text": ("Sauron's Mind reads, summarises, and makes predictions "
                      "that can be checked, each one graded later. An agent "
                      "that is often wrong loses influence. The brain never "
                      "sends an order. It can pause a rule, and with its "
                      "switch on, two of its agents argue each real-money "
                      "bot order before it leaves; after a first stretch in "
                      "shadow they may cut its size or refuse it, never "
                      "raise it.")},
            {"glyph": "pages", "title": "The pages",
             "text": ("The Operations Center, with its live, portfolio, "
                      "history and bots tabs; the Treasury, which shows "
                      "where the money is; each trade's own page; and the "
                      "public Wall.")},
            {"glyph": "messages", "title": "The messages",
             "text": ("A Telegram group where Sauron announces what it does "
                      "(every opening, every closing, every refusal and every "
                      "problem, in English) and answers what it is asked. A "
                      "second bot, in a second group, rings only for a "
                      "critical problem.")},
        ],
    },
    {
        "id": "circuit",
        "numeral": "III",
        "nav": "How a trade is born",
        "title": "How a trade is born, lives and ends",
        "kicker": "Eleven steps, from a view to a graded result.",
        "paragraphs": [
            ("A trade is a bet on a price: you buy an investment expecting "
             "it to rise, or sell it expecting it to fall, and later you "
             "close it. Here is the real path of a trade inside Sauron, in "
             "order."),
            ("Every five minutes, each bot that is switched on takes a turn. "
             "It first watches over what it already holds, then checks that "
             "it is still allowed to open something, and only then looks "
             "through its instruments. A bot stopped by a brake still takes "
             "the first part of its turn: it goes on watching over what it "
             "holds, and opens nothing."),
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
                      "That is “1R”, one unit of risk; in the attack "
                      "mode, conviction sets each trade at a half, three "
                      "quarters or all of it. Several things may then make "
                      "it smaller. On real money, a rule the proving ground "
                      "has not passed enters at a quarter unless its own "
                      "graded record has earned more, and a rule on "
                      "Aragorn's probation is cut to a quarter on top; an "
                      "exceptional entry past the day's stop goes at half; "
                      "and, when their switches are on, the market's "
                      "posture, the read of the crowd and the trade debate "
                      "may cut it further.")},
            {"title": "The gates",
             "text": ("Before anything is sent: the proof for the class and, "
                      "for a sell, its own proof; the rule's verdict from the "
                      "proving ground; the clock; an open market; the "
                      "venue's health; a quote that looks like a market; the "
                      "broker's sheet for that instrument; the money "
                      "available; the day's maximum loss; the risk already "
                      "open; the total size carried; the concentration on "
                      "one instrument; the same bet hidden under several "
                      "names; the circuit breakers. A single no is enough, "
                      "and nothing leaves.")},
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
                      "quiet hours, when set, hold it back. Just before a "
                      "bot's real-money order leaves, the price is read once "
                      "more, and a fill worse than planned, on a bot's order "
                      "or a hand-taken one, moves the stop closer by the "
                      "same distance, so the loss at the stop stays the one "
                      "chosen. An order whose answer never comes "
                      "back is held in doubt and looked for at the venue, "
                      "never sent a second time blind.")},
            {"title": "The care",
             "text": ("While a trade is open, and when Aragorn's switch is "
                      "on, each turn looks after it: the stop moves to "
                      "break-even at +1R and trails behind the price from "
                      "+1.5R; a trade that has done nothing for days is let "
                      "go; before a weekend or a high-impact print, "
                      "a winner up half a unit of risk or more is locked at break-even, "
                      "and a real-money loser at five times leverage or more is cut. "
                      "Every tighter stop on a real-money trade is copied "
                      "onto the stop resting at eToro, so the lock outlives "
                      "the platform. A trade opened by hand keeps the profit "
                      "locks and is never cut by a rule.")},
            {"title": "The watch",
             "text": ("Every 15 minutes, around the clock, Sauron compares "
                      "what it holds with what the broker holds: forex, "
                      "commodities and crypto trade through the night, and "
                      "a stop the broker fires in the night is seen within "
                      "the quarter hour. That is one of two ways it learns that "
                      "a stop or a target was hit; the five-minute turn also "
                      "compares the price with both.")},
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
            ("The last step closes the loop. A rule climbs a ladder of four "
             "rungs: research (no trades at all), simulation, small real (a "
             "quarter of the size), full real. With the ladder's switch on, "
             "a rule that falls apart climbs back down on its own, and one "
             "measured as losing on real money drops straight back to "
             "simulation. Real money also "
             "follows the proving ground: a rule it has not passed trades "
             "at a quarter even on the top rung, unless its own record has "
             "earned more, and a rung given by hand without that proof says "
             "so."),
        ],
        "note": ("The settings quoted in this chapter are the platform's "
                 "defaults as verified on 26 September 2026, and again on "
                 "%s." % WRITTEN_WORDS),
    },
    {
        "id": "safeguards",
        "numeral": "IV",
        "nav": "The safeguards",
        "title": "What stands around a trade",
        "kicker": ("Before the order, while it is open, and when the machine "
                   "itself fails."),
        "paragraphs": [
            ("A trade is born in the chapter before this one. This chapter "
             "is about everything that stands around it: the checks that "
             "can stop it leaving, the care it gets while it is open, the "
             "guards that watch the machine, and the alarm that rings when "
             "something is wrong. Most of it arrived between 28 September "
             "and 7 October 2026, and most of it ships switched off, "
             "waiting for a person to turn it on."),
            ("The platform counts {guards} guards in its watchdog and "
             "{money_switches} switches it marks as decisions about real "
             "money. Each of those switches is off on arrival, none of them "
             "is turned on by an “all on” button, and each one is a "
             "decision of its own."),
            ("Real money has to prove itself twice. A family of investments "
             "may trade at eToro only after one of its orders has filled "
             "and closed there, and {proof_classes} families have; a sell "
             "needs a proof of its own, which {short_classes} families "
             "have. A rule, for its part, keeps its full size on real money "
             "only once the proving ground, or its own graded record, has "
             "said yes."),
        ],
        "kind": "principles",
        "items": [
            {"title": "Proof before money",
             "text": ("Each night, when its switch is on, the proving ground "
                      "replays every live rule bar by bar with the engine's "
                      "own costs and stops: the last 30% of the history "
                      "stays unseen until the end, five slices of time are "
                      "judged apart, the costs are doubled, and the bound is "
                      "corrected for every variant tried. A rule measured as "
                      "losing on a family and a side is refused real money "
                      "there; one that passed keeps its full size; every "
                      "other enters at a quarter, unless its own graded "
                      "record has earned more. A rule set to real money by "
                      "hand without that proof is labelled so.")},
            {"title": "The clock",
             "text": ("No bot opens a real-money trade in a share, an ETF, "
                      "a currency or a commodity while its exchange is shut; "
                      "a ticket placed by hand is warned and left to its "
                      "owner. Crypto aside, which never shuts, no bot opens a trade "
                      "in the twenty minutes around New York's five o'clock "
                      "rollover, in a market's first quarter hour, in a "
                      "share's last ten minutes, or on a Friday in the hour "
                      "or so before its market shuts for the weekend; and "
                      "none opens one from an hour before to a quarter hour "
                      "after a high-impact print on its currency. In the "
                      "three hours before such a print, the attack mode may "
                      "not raise a size. The guard that watches for a "
                      "booking on a shut market reads the very clock the "
                      "gate reads.")},
            {"title": "The venue's health",
             "text": ("An order whose answer never comes back is held in "
                      "doubt and looked for in the venue's own list before "
                      "the instrument trades again; it is never sent a "
                      "second time blind. Three failures inside three "
                      "minutes, or one failed order, make the venue sick: "
                      "the bots' new real-money entries wait for ten quiet "
                      "minutes, while closes and stop moves go on and a "
                      "ticket placed by hand is warned. Since 7 October a "
                      "burst of “too many requests” pauses the bots' new "
                      "real-money entries for a short while before the venue "
                      "is called sick, and the alert that says it is sick "
                      "names its times and its count.")},
            {"title": "A price that looks like a market",
             "text": ("No bot enters on a quote that is crossed, stale, "
                      "frozen or far from a second source. Every real-money "
                      "bot order takes one last look at the price just "
                      "before it leaves, and is held back if the price has "
                      "run or if half the spread would eat more than 15% of "
                      "the distance to its stop; a ticket placed by hand is "
                      "warned of such a quote, and the last word is a "
                      "person's. A single aberrant print, or a "
                      "feed frozen for 45 minutes, can no longer close a "
                      "trade or move its stop.")},
            {"title": "The care of an open trade",
             "text": ("When Aragorn's switch is on, every open trade is "
                      "looked after on each turn. Its stop goes to "
                      "break-even at +1R and trails from +1.5R; a trade that "
                      "has gone nowhere for days is let go; before a weekend "
                      "or a high-impact print, "
                      "a winner up half a unit of risk or more is locked at break-even, "
                      "and a real-money loser at five times leverage or more is cut. "
                      "A trade opened by hand keeps the profit locks and is never cut by a rule. "
                      "Every tighter stop on "
                      "a real-money trade is copied onto the stop resting at "
                      "eToro, so the lock outlives the platform if the "
                      "server stops.")},
            {"title": "Beyond the crowd's stops",
             "text": ("With its switch on, a stop that would sit where the "
                      "crowd's stops pile up (an untaken swing, equal highs "
                      "or lows, a round number) is placed beyond them, "
                      "within one average move, and the size shrinks so the "
                      "money at risk stays the same. Trails and break-evens "
                      "leave the same zones.")},
            {"title": "Aragorn",
             "text": ("With his switch on, every four hours Aragorn judges "
                      "each rule on each family of investments: a loser on "
                      "real money goes back to simulation, a newcomer rides "
                      "at a quarter of its size on probation, and a benched "
                      "rule returns only on fresh evidence from simulation. "
                      "The trades placed by hand are never his to judge.")},
            {"title": "The loser floor",
             "text": ("Each night, with its switch on, the ladder reads "
                      "every rule's whole graded record: one with 20 or more "
                      "graded signals and an expectancy at or under zero, or "
                      "a thin edge under a low hit rate, leaves real money "
                      "for simulation at once, unless its owner promoted it "
                      "by hand in the last seven days. A breakout that wins "
                      "a third of the time with a large payoff keeps its "
                      "place.")},
            {"title": "The trade debate",
             "text": ("With its switch on, two AI agents argue every "
                      "real-money bot order just before it leaves: the "
                      "Executioner says why it will fail, the Champion why "
                      "it will work. For the first 30 graded trades they "
                      "only record their case; after that the Executioner "
                      "may cut a size, never below a quarter, or refuse the "
                      "entry, and past the day's loss limit an exceptional "
                      "entry also needs the Champion to win. They speak once "
                      "every other gate has said yes, just before the last "
                      "look at the price, and never on a simulated or demo "
                      "trade.")},
            {"title": "The market's posture",
             "text": ("With its switch on, a stress score read every quarter "
                      "hour (the fall of the index, its volatility, the VIX, "
                      "credit spreads) sets the market's posture: calm, "
                      "stressed, crisis or recovery, up at once and down "
                      "slowly. In a crisis, a real-money trade that needs "
                      "the market to rise, or one that sells a haven, goes "
                      "to simulation instead, while trades that ride the "
                      "fall or buy a haven may still go; the posture also "
                      "caps leverage.")},
            {"title": "The limits of the book",
             "text": ("The book has one daily stop, 3% of it by default. "
                      "Past it a bot may open only an exceptional entry, "
                      "with a measured edge on that venue and a reward at "
                      "least twice its risk, at half its size and two a day "
                      "at most; at one and a half times the limit, nothing "
                      "opens. What the open trades would lose together at "
                      "their stops is capped at 15% of the book by default, "
                      "and "
                      "an entry past that cap is refused, never shrunk; what "
                      "they carry together is capped at four times the "
                      "book, and the share of the account the broker may "
                      "lock is its owner's setting, half by default.")},
            {"title": "The guards and the brake",
             "text": ("With their switch on, the Morgul guards look every "
                      "five minutes for what Sauron must never do, from a "
                      "booking on a shut market to a real-money stop that "
                      "did not hold, and tell the group. With a second "
                      "switch on as well, a few of them may brake, and a "
                      "brake means one thing: open nothing new. "
                      "What the bot holds goes on being managed as before. A "
                      "bot switched off by hand, or by the emergency stop, "
                      "is not ticked at all, and every switch-off records "
                      "who did it, when and why.")},
            {"title": "The alarm",
             "text": ("With its switch on, a second bot, in a second group "
                      "of the people who keep watch, rings for a critical "
                      "problem and for nothing else: never a heartbeat, "
                      "never “back to normal”, never an amount. A "
                      "problem that stands is said again every three hours. "
                      "Once it is set up, every five-minute turn pings a "
                      "watcher outside the server, which raises the alarm "
                      "when the pings stop.")},
            {"title": "Real money, unmistakable",
             "text": ("Real money is the platform's only solid red: a marker "
                      "on every row and every bot, a pill on every page "
                      "while a live bot is armed, and the words REAL MONEY "
                      "on Telegram. A demo fill is never called live.")},
        ],
    },
    {
        "id": "principles",
        "numeral": "V",
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
                      "September, written into the code on the 27th. By 29 "
                      "September every other family Sauron trades at eToro "
                      "had earned its own in demo. A sell waits for a proof "
                      "of its own: shares and currencies earned theirs on 1 "
                      "October, while the venue refused the index sells sent "
                      "that evening.")},
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
                      "price far from the market, a stop that did not hold), "
                      "tells the group, and can only ever stop a bot from "
                      "opening something new. Both of its switches are off "
                      "on arrival.")},
            {"title": "Every switch to real money is a person's",
             "text": ("The parts that could move capital on their own, the "
                      "share allocator and the capital desk, run in shadow: "
                      "they propose and apply nothing until weeks of grades "
                      "have been read. Applying an allocation plan takes the "
                      "PIN on the page, or an explicit confirmation in a "
                      "command. Every switch the platform marks as a "
                      "decision about real money (share cuts after a shock, "
                      "one shared pool, Aragorn, the trade debate, the "
                      "market's posture, the stops beyond the crowd, and the "
                      "rest) is off on arrival and never turned on by an "
                      "“all on” button: each is a decision of its own, "
                      "made by a person.")},
            {"title": "An error kept on the cautious side",
             "text": ("One calculation of a share of capital is wrong, but "
                      "always towards “too small”. Every fix tried "
                      "broke one of the platform's guarantees: one doubled a "
                      "reserve at a stroke, another split the accounts in "
                      "two, the third disarmed the automatic brake on "
                      "losses. It stays as it is: breaking a guarantee to "
                      "correct a caution is not an improvement. Since 1 "
                      "October every pool that follows the account can draw "
                      "on the whole of it instead; with that switch on, "
                      "there is no slice left to get wrong.")},
        ],
    },
    {
        "id": "road",
        "numeral": "VI",
        "nav": "Milestones",
        "title": "The road so far",
        "kicker": (
            "From a first bot in April to real money that follows its proof "
            "in October, one dated step at a time."),
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
            ("October was the month of the safeguards: one account with its "
             "limits, guardians behind switches that ship off, backtests "
             "that can say no, the care of open trades, and a clock and a "
             "check of the venue in front of every entry."),
        ],
        "kind": "timeline",
    },
    {
        "id": "in-progress",
        "numeral": "VII",
        "nav": "In progress",
        "title": "What is being built now",
        # Re-dated with every edition: the bench empties as batches land,
        # and the empty bench has its own words (the test holds both).
        "kicker": ("On %s the bench was empty: every batch written so far "
                   "had landed on the road." % WRITTEN_WORDS),
        "paragraphs": [
            ("Every batch is first designed, then attacked, then checked by "
             "thousands of automated tests before it lands. Each line here "
             "is said as in progress until then, and moves to the road so "
             "far, with its date, the day it lands."),
        ],
        "kind": "progress",
        "road_title": "The road to real money",
        "after": [
            ("The aim was written in the plan for the move to eToro: every "
             "class traded at eToro, on its own, with IBKR retired. IBKR "
             "has been retired since 23 September, and by 29 September "
             "every class Sauron trades at eToro had earned its proof "
             "there. What remains is the slower part: earning, rule by "
             "rule, the right to a full size."),
            ("Why eToro? Because it lets the server work alone: two keys "
             "are enough, with no human sign-in every day. IBKR asked for a "
             "confirmation on a phone almost daily, and on 16 September its "
             "two-factor sign-in stayed stuck in a loop. The move has a "
             "price, accepted with open eyes: no broker is left for "
             "options."),
            ("The real limit is not money but calibration: knowing which "
             "rules truly work. Hence the research fleet trading pretend "
             "money, the graded predictions, the register of proofs, the "
             "proving ground, and a generator that proposes new strategies "
             "every week. Each one is born inactive, at the research stage, "
             "until a human approves it."),
        ],
    },
    {
        "id": "closing",
        "numeral": "VIII",
        "nav": "Closing",
        "title": "A last word",
        "kicker": "Look, measure, and stop when something does not add up.",
        "paragraphs": [
            ("Sauron has been built since 5 April, commit after commit. It "
             "is not finished, and it says so: what is proven is written "
             "down, and what is not is refused or kept small."),
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
    # The second edition (2026-10-08): the ten days after the first.
    {"id": "second-alarm", "span": "28 – 30 September",
     "title": "A second alarm, and a proof for every family",
     "summary": ("This book goes online and the Wall gains a door to it. A "
                 "second bot rings for critical problems only. ETFs, "
                 "currencies, shares, indices and commodities earn their "
                 "proofs in demo, so every family Sauron trades at eToro "
                 "has one. A live bot is judged on the real book alone, a "
                 "watcher outside the server can hear when it goes quiet, "
                 "and real money is marked in solid red everywhere.")},
    {"id": "one-account", "span": "1 – 2 October",
     "title": "One account, its limits and its guardians",
     "summary": ("Sells earn their own proofs, family by family. One shared "
                 "pool, one daily stop with an exceptional door past it, "
                 "and a cap on the risk open at once. The trade debate, "
                 "Aragorn, the market's posture, the care of open trades "
                 "and stops beyond the crowd arrive behind switches that "
                 "ship off, and the proving ground starts saying no.")},
    {"id": "reading-the-market", "span": "3 – 4 October",
     "title": "A market read whole",
     "summary": ("The proving ground compares ways of leaving a trade. "
                 "Sauron learns where the crowd's stops sit, asks whether a "
                 "trade's reason is still alive, reads its own reports for "
                 "next steps, and gets a free macro calendar. Signals cool "
                 "down, the book's size is capped in money, and a tighter "
                 "stop is copied onto the venue's own.")},
    {"id": "venue-and-clock", "span": "5 – 8 October",
     "title": "The venue, the clock and the proof",
     "summary": ("The engine stops deciding on a dead or aberrant price, "
                 "values a real trade at the venue's own rate, holds an "
                 "unanswered order in doubt, and holds back new entries "
                 "while a venue is sick. A high-impact print is treated like a weekend, "
                 "the clock judges every entry, and the comparison with the "
                 "venue runs around the clock. A measured loser leaves real "
                 "money, and real money follows the proving ground's "
                 "verdict. On the 7th a busy venue is no longer called sick "
                 "at once, the venue is asked before a missing trade is "
                 "booked closed, the price bars stop flooding it with "
                 "requests, and the "
                 "scorecard says what closed each trade. On the 8th the "
                 "chart's levels are redrawn, each kind told apart at a "
                 "glance, and a real trade is valued at its venue's own "
                 "price from its first minute.")},
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
    # ── The second edition (2026-10-08) ─────────────────────────────────
    ("2026-09-28", "second-alarm", "The Book, and the bench landed",
     "This book goes online beside the Wall, and the three lines it first "
     "listed as in progress land with it: the news band keeps its cards, "
     "Telegram messages are written for people, and the Monday game plan "
     "is shown whole.",
     "45a4c93"),
    ("2026-09-28", "second-alarm", "“All on” skips the live-money switches",
     "One tap of “all on” would have armed seven switches that each "
     "reach real money, with no PIN; the review caught it, and each of them "
     "is now turned on alone.",
     "893e0e2"),
    ("2026-09-28", "second-alarm", "A second alarm",
     "A second bot, in a second group, rings for a critical problem and for "
     "nothing else: never a heartbeat, never an amount.",
     "d864661"),
    ("2026-09-28", "second-alarm", "ETFs and currencies earn their proofs",
     "An ETF round trip measured in demo on 23 September becomes a proof, "
     "and so do two currency round trips sent the same minute, at 1x and "
     "5x.",
     "0b7878e"),
    ("2026-09-29", "second-alarm", "A proof for every family",
     "Shares, indices and commodities fill and close in demo the same "
     "morning, so every family Sauron trades at eToro now has its proof.",
     "91d92c5"),
    ("2026-09-29", "second-alarm", "A day of Sauron",
     "The Wall draws the platform's day as a ring around its schedule, read "
     "from the schedule itself, so a changed cadence changes the picture.",
     "306269d"),
    ("2026-09-29", "second-alarm", "Fresh bars from the venue",
     "An armed crypto bot had been deciding on a candle a month old; the "
     "venue's fresh bars now reach the table before the old ones leave it.",
     "3a16bb1"),
    ("2026-09-30", "second-alarm", "Each book judged on its own",
     "A live bot is judged on the real book alone, so simulated trades no "
     "longer refuse real-money entries, and a watcher outside the server "
     "can raise the alarm when the platform goes quiet.",
     "6cee455"),
    ("2026-09-30", "second-alarm", "Real money, unmistakable",
     "Real money becomes the platform's only solid red: a marker on every "
     "row and bot, a pill on every page while a live bot is armed, and a "
     "demo fill never called live.",
     "f237940"),
    ("2026-09-30", "second-alarm", "The ladder climbs on its own",
     "Every automatic promotion had been rolled back by the database, its "
     "reason longer than its column; now each one holds, recorded under its "
     "reason.",
     "349996a"),
    ("2026-10-01", "one-account", "Selling, family by family",
     "A sell is refused until one has filled and closed in demo: shares and "
     "currencies earn theirs, while the venue refuses the index sells sent "
     "that evening.",
     "d80d644"),
    ("2026-10-01", "one-account", "One account, one pool",
     "Switched on, every live bot and the hand lane draw on the whole "
     "account, bound by its cash, the pledge cap, the day's loss and the "
     "single-trade cap.",
     "53b8b6a"),
    ("2026-10-01", "one-account", "One daily stop",
     "The book gets one daily stop; past it, only an exceptional entry with "
     "a measured edge may open, at half size, until an absolute stop at one "
     "and a half times the limit.",
     "32a1e9f"),
    ("2026-10-01", "one-account", "A cap on the risk open at once",
     "What the open trades would lose together at their stops is capped, "
     "and an entry that would pass the cap is refused, never shrunk.",
     "aef3687"),
    ("2026-10-01", "one-account", "The trade debate",
     "Two AI agents, the Executioner and the Champion, argue each "
     "real-money bot order; they record their case first and bind only "
     "after thirty graded trades.",
     "d7082be"),
    ("2026-10-01", "one-account", "Aragorn and the market's posture",
     "A guardian judges which rule may trade real money on which family, "
     "open trades get their care, and a stress score sets the market's "
     "posture, all behind switches that ship off.",
     "a6c11d8"),
    ("2026-10-02", "one-account", "Beyond the crowd's stops",
     "A stop that would sit where the crowd's stops pile up is moved beyond "
     "them, the size shrunk so the risk is unchanged.",
     "25e0c76"),
    ("2026-10-02", "one-account", "A stop that did not hold",
     "A real-money close worse than -1.2R is said once, in R and in prices, "
     "never in money.",
     "0cd406e"),
    ("2026-10-02", "one-account", "The proving ground",
     "Backtests that can say no: the live rules replayed bar by bar with "
     "the engine's own costs and stops, judged on data they never chose "
     "from, with the costs doubled.",
     "c86ebc4"),
    ("2026-10-02", "one-account", "The scorecard",
     "One table splits a record into what makes it: win rate, average win, "
     "average loss, winners closed early by hand, losers that had once been "
     "+1R.",
     "c649558"),
    ("2026-10-03", "reading-the-market", "Exit policies, compared",
     "The proving ground runs the same signals under several ways of "
     "leaving a trade, side by side.",
     "95da5dc"),
    ("2026-10-03", "reading-the-market", "Sauron reads its own reports",
     "After each brief and review, a second pass proposes a few next steps, "
     "acted on only when a person approves.",
     "abacd6a"),
    ("2026-10-03", "reading-the-market", "Where the crowd's stops sit",
     "The chart redraws every minute where the crowd's stops and pools sit; "
     "information, never a gate.",
     "0ccfcde"),
    ("2026-10-03", "reading-the-market", "Is the reason still alive?",
     "For each open trade Sauron reads the structure and the odds of coming "
     "back from this deep, and answers hold, adjust, exit or watch; an "
     "adjust only ever tightens the stop.",
     "c71a5f9"),
    ("2026-10-03", "reading-the-market", "A free macro calendar",
     "The paid calendar had answered “payment required” for a "
     "month; a free weekly feed now comes first, so payrolls and "
     "central-bank days are seen again.",
     "8b5463a"),
    ("2026-10-04", "reading-the-market", "Signals that cool down",
     "A rule may not fire twice on one instrument within a day, can be kept "
     "off the families where it fails, and its own record caps how loud it "
     "may call.",
     "0902acf"),
    ("2026-10-04", "reading-the-market", "A cap on what the book carries",
     "The open trades may carry a set multiple of the book, counted in "
     "money and never in a foreign currency's units.",
     "df72157"),
    ("2026-10-04", "reading-the-market", "The mirror",
     "Every tighter stop the platform holds on a real-money trade is copied "
     "onto the stop resting at eToro, tighten-only, so the lock outlives "
     "the platform.",
     "a48b298"),
    ("2026-10-05", "venue-and-clock", "The mark sanity",
     "An aberrant print or a frozen feed can no longer close a trade, bank "
     "a half or move a stop: a jump waits for a second print or a second "
     "source.",
     "7f9664d"),
    ("2026-10-05", "venue-and-clock", "The event window",
     "From an hour before a high-impact print to a quarter hour after it, "
     "a winner up half a unit of risk or more is locked at break-even, "
     "and a real-money loser at five times leverage or more is cut, "
     "as before a weekend. A trade opened by hand is never cut by a rule.",
     "ed8cb31"),
    ("2026-10-05", "venue-and-clock", "In doubt, never twice",
     "An order whose answer never came back is held in doubt and looked for "
     "at the venue, never sent again blind, and a sick venue holds the "
     "bots' new real-money entries.",
     "0dd8c1d"),
    ("2026-10-05", "venue-and-clock", "A last look before leaving",
     "Every real-money bot order reads the price once more just before it "
     "leaves, and a worse fill moves the stop by the same distance.",
     "b5c0c4e"),
    ("2026-10-05", "venue-and-clock", "A measured loser leaves real money",
     "A rule with enough graded signals and an expectancy at or under zero "
     "goes back to simulation at once.",
     "6d48449"),
    ("2026-10-06", "venue-and-clock", "The clock judges every entry",
     "No bot opens a trade in the rollover, in a market's first quarter "
     "hour, in a share's last minutes, in Friday's last hour or around a "
     "high-impact print.",
     "fa096a1"),
    ("2026-10-06", "venue-and-clock", "Reconciled around the clock",
     "The comparison with the venue runs every quarter hour, day and night: "
     "a trade the venue stopped in the night had stayed open here until the "
     "next afternoon.",
     "aab7d82"),
    ("2026-10-06", "venue-and-clock", "The floor reads expectancy",
     "The loser floor is led by expectancy, so a breakout that wins a third "
     "of the time with a large payoff keeps its place.",
     "2f9fcf2"),
    ("2026-10-06", "venue-and-clock", "Real tails kept",
     "The proving ground refuses broken bars and drops no real loss: a gap "
     "through a stop is kept, capped, and a run with too much of either is "
     "called insufficient.",
     "1c5a876"),
    ("2026-10-07", "venue-and-clock", "No entry on a shut market",
     "A bot's live entry is refused while its exchange is shut, and the gate "
     "reads the very clock the guard reads, so the two can no longer "
     "disagree.",
     "7031773"),
    ("2026-10-07", "venue-and-clock", "Size by proof",
     "A rule the proving ground measured as losing is refused real money, "
     "one that passed keeps its full size, and every other enters at a "
     "quarter unless its own record has earned more.",
     "996b408"),
    ("2026-10-07", "venue-and-clock", "A brake keeps the care",
     "A brake now means open nothing new: what the bot holds keeps its "
     "exits, stops and locks, and every switch-off records who, when and "
     "why.",
     "94a7287"),
    ("2026-10-07", "venue-and-clock", "A busy venue is not a sick venue",
     "A burst of “too many requests” from the venue now pauses the bots' "
     "new real-money entries for a short while before the venue is called "
     "sick, and the alert that says a venue is sick names its times and "
     "its count.",
     "2899df5"),
    ("2026-10-07", "venue-and-clock", "Asked before it is booked",
     "Before a trade missing from the venue's list is booked closed, the "
     "venue is asked about that trade; a close the venue made is booked at "
     "the stop or target it held, and said as an estimate.",
     "fc7b00d"),
    ("2026-10-07", "venue-and-clock", "The bars stop flooding the venue",
     "The refresh of the price bars asks the venue one request at a time, "
     "paced, stops at the first refusal, and yields to the trading reads.",
     "5eb7c38"),
    ("2026-10-07", "venue-and-clock", "What closed each trade",
     "The scorecard says what closed each trade, how many exit prices are "
     "estimates, and how many venue closes fell outside the exchange's "
     "hours.",
     "8960905"),
    ("2026-10-08", "venue-and-clock", "The chart's levels, redrawn",
     "On the price chart, the pools where the crowd's stops sit, the swing "
     "points, the Asian range and the round numbers each take a look of "
     "their own and are told apart at a glance. The lines that carry money "
     "stay the loudest.",
     "5afc234"),
    ("2026-10-08", "venue-and-clock", "A real trade valued at its venue's price",
     "A real trade is valued at its venue's own price from its first "
     "minute, never against the quote of another instrument, such as a "
     "future's quote standing in for a spot price. Without the venue's "
     "price the page says it waits, and a close is never booked at a price "
     "too old to be the venue's.",
     "0bf225d"),
]


# ── The bench ───────────────────────────────────────────────────────────────

#: Work written and reviewed but not landed on WRITTEN. Said as in
#: progress; a line moves to MILESTONES, with its hash, the day it lands.
#: The three lines of the first edition landed on 2026-09-28 (45a4c93).
IN_PROGRESS = []

#: The road a class travels to real money, in order: the same for every
#: class, save where the text says otherwise (crypto's proof was measured
#: on the real account). The multiplier is not part of a proof since
#: 5 October: the attack mode reads the venue's own list.
GO_LIVE = [
    {"title": "A proof for every class, at eToro",
     "text": ("Each class earns its proof at eToro, most of them in the "
              "demo account and crypto on the real one: an order filled, "
              "then closed, and written into the code with its test. A sell "
              "waits for a proof of its own. The multiplier is not part of "
              "the proof: with its switch on, the attack mode reads the "
              "venue's own list.")},
    {"title": "Real money only with the PIN, in person",
     "text": ("Unticking the demo box is the switch to real money. It asks "
              "for the trading PIN, typed in person on the page and never "
              "sent in a message.")},
    {"title": "One class at a time",
     "text": ("One class ticked at a time and one configuration switched on "
              "per session; then a full five-minute cycle and its Telegram "
              "message are watched before the next.")},
    {"title": "Then each rule earns its size",
     "text": ("On real money a rule enters at a quarter of its size until "
              "the proving ground has passed it on that class and side, or "
              "its own graded record has earned more; one measured as "
              "losing there is refused.")},
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
               "the loss at the stop, which depends on the risk chosen. In "
               "the attack mode, with its switch on, each entry takes the "
               "highest multiplier the venue lists that its stop allows; "
               "since 5 October no demo proof caps it.")},
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
               "send any order to eToro, and a sell needs a proof of its "
               "own.")},
    {"term": "The proving ground",
     "plain": ("The platform's own strict backtest: a rule's history "
               "replayed with the engine's costs and stops and judged on "
               "data it never chose from. Its verdict decides whether a "
               "rule may trade real money at its full size.")},
    {"term": "Expectancy",
     "plain": ("What a rule wins or loses per trade, on average, counted in "
               "R.")},
    {"term": "Trading PIN",
     "plain": ("The code that authorises real-money actions on the pages. "
               "Switching a bot off never asks for it.")},
    {"term": "The brake",
     "plain": ("Stopping a bot from opening anything new. Since 7 October a "
               "brake (the guards', the group's, the alarm group's or one "
               "typed on the server) leaves what the bot holds managed as "
               "before: its exits, its stops and its locks. A bot switched "
               "off by hand, or by the emergency stop, is not ticked at "
               "all: what it still holds keeps only the stop and target "
               "resting at the broker.")},
    {"term": "Morgul",
     "plain": ("The guards: a watchdog outside the engine that, with its "
               "switch on, looks every five minutes for what must never "
               "happen and tells the group; with a second switch on as "
               "well, it may brake a bot.")},
    {"term": "Aragorn",
     "plain": ("The guardian who decides, every four hours when his switch "
               "is on, which rule may trade real money on which family of "
               "investments, and which stays in simulation.")},
    {"term": "In doubt",
     "plain": ("An order whose answer never came back. It is looked for at "
               "the venue, and never sent again blind.")},
]
