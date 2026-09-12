"""The command registry — every shell twin and diagnostic, in one list.

The decisions of this platform live on eight pages, and each page has a
shell twin (`component`, `proposals`, `actuator`, `shares`, `follow`,
`bot`) and a set of read-only diagnostics beside it (`open_trades`,
`preflight_live`, `why_no_trade`). By 2026-09-12 nothing on any screen
said those twins existed: an operator learned a command's name from a
runbook paragraph or a colleague, and the runbook and the commands
drifted apart in silence. This module is the one place the catalogue
lives; /ops/ renders it and `python manage.py ops` prints it, so both
show the same list by construction.

Every `usage` line is COPIED from the command's own module docstring —
tests/test_ops_cockpit.py opens each command file and asserts every
usage line appears there verbatim, so a flag renamed in the command
without this list following it fails the suite rather than misleading
the operator. Likewise every registered management command must exist
and every management command under bot_program/brain/signals/core must
be registered or named in EXEMPT: the registry cannot drift in either
direction.

Pure Python, no Django import at module level: `ops` and the page both
import it before anything else, and a registry that needs the ORM to be
read cannot be printed when the ORM is what is broken.
"""

# Categories: 'read' answers a question and writes nothing; 'decide' is a
# page's Apply/Reject/On/Off button as a command (its `list` verb is read,
# its other verbs write); 'ops' is a one-off operational write — a seed,
# a backfill, a recalculation.
CATEGORIES = (
    ("read", "Read — answers a question, writes nothing"),
    ("decide", "Decide — a page's buttons as a command (list is read; the rest write)"),
    ("ops", "Ops — one-off operational writes: seed, backfill, recalculate"),
)

# What the page's Run lane may execute: only entries that are read_only AND
# runnable. `run_args` is the FIXED argv the button passes — the browser
# never supplies an argument, so the only variability is which registered
# read-only command runs (2026-09-12: free-form argv from a form field is a
# shell on the web, and the PIN gates would be the only thing between a
# stolen session and `component off platform_master`).
COMMANDS = [
    # ── decide: the pages' buttons ──────────────────────────────────────
    {
        "name": "component",
        "title": "Platform components",
        "purpose": "Turn platform components on and off from the shell — the same write as the health page's toggle, with the nearest key suggested on a typo.",
        "usage": [
            "python manage.py component list",
            "python manage.py component list --category agent",
            "python manage.py component on generator_auto_research",
            "python manage.py component off actuator_mode_live scraper_etoro",
        ],
        "mirrors": "/health/",
        "read_only": False,
        "run_args": [],
        "category": "decide",
    },
    {
        "name": "proposals",
        "title": "Generator proposals",
        "purpose": "Read, arm or reject the strategy generator's proposals — the brain page's click, with the same blocker check and audit row.",
        "usage": [
            "python manage.py proposals list",
            "python manage.py proposals approve 10 11",
            'python manage.py proposals reject 12 --notes "duplicates rule X"',
        ],
        "mirrors": "/generated/",
        "read_only": False,
        "run_args": [],
        "category": "decide",
    },
    {
        "name": "actuator",
        "title": "Rule actuator",
        "purpose": "The rule actuator's Apply / Reject / Rollback buttons as a command; --stale rejects every proposal a newer one supersedes.",
        "usage": [
            "python manage.py actuator list",
            "python manage.py actuator apply 11 9",
            "python manage.py actuator reject 2 4 6",
            "python manage.py actuator reject --stale",
            "python manage.py actuator rollback 11",
        ],
        "mirrors": "/rule-control/",
        "read_only": False,
        "run_args": [],
        "category": "decide",
    },
    {
        "name": "shares",
        "title": "Share allocator",
        "purpose": "The share allocator's page as a command: propose, apply (LIVE mode, --yes), reject, rollback and grade the plans that size each live follower pool.",
        "usage": [
            "python manage.py shares list                  # mode, pending, applied, last grade",
            "python manage.py shares list --user alice",
            "python manage.py shares propose --user alice  # a plan now, or the reason there is none",
            "python manage.py shares apply 12              # plan only",
            "python manage.py shares apply 12 --yes        # write it (LIVE mode only)",
            "python manage.py shares reject 12 13",
            "python manage.py shares rollback 12 --yes",
            "python manage.py shares grade                 # score every plan whose 24h closed",
        ],
        "mirrors": "/shares/",
        "read_only": False,
        "run_args": [],
        "category": "decide",
    },
    {
        "name": "follow",
        "title": "Follow the account",
        "purpose": "Make a live pool a share of the account, or stop it following — the asset-bots page's Follow form, through the same arithmetic, writing only with --yes.",
        "usage": [
            "python manage.py follow                      # who follows, at what share",
            "python manage.py follow 14 --share 20        # plan only",
            "python manage.py follow 14 --share 20 --yes  # write it",
            "python manage.py follow 14 --yes             # automatic share",
            "python manage.py follow 14 --stop --yes      # stop following, pool stays",
        ],
        "mirrors": "/asset-bots/",
        "read_only": False,
        "run_args": [],
        "category": "decide",
    },
    {
        "name": "bot",
        "title": "Asset bot on/off",
        "purpose": "Enable or disable an asset bot — the admin page's toggle with its own rule: --yes plays the PIN's role to arm a live config, stopping never asks.",
        "usage": [
            "python manage.py bot list",
            "python manage.py bot off 1",
            "python manage.py bot on 6            # paper: writes; live: plan only",
            "python manage.py bot on 6 --yes      # live: writes",
        ],
        "mirrors": "/asset-bots/",
        "read_only": False,
        "run_args": [],
        "category": "decide",
    },
    # ── read: the diagnostics ───────────────────────────────────────────
    {
        "name": "open_trades",
        "title": "Open trades",
        "purpose": "Every position the bots hold with the platform's own mark, unrealised P&L and R against the stop; a trade without a stop is flagged.",
        "usage": [
            "python manage.py open_trades",
            "python manage.py open_trades --symbol SOL",
            "python manage.py open_trades --all      # closed rows of the last 7 days too",
        ],
        "mirrors": "/command/",
        "read_only": True,
        "run_args": [],
        "category": "read",
    },
    {
        "name": "preflight_live",
        "title": "Preflight live",
        "purpose": "Answer, in one pass, whether it is safe to arm real money right now — switches, connection, money, live configs, bars, PIN — from cached columns only.",
        "usage": [
            "python manage.py preflight_live",
            "python manage.py preflight_live --user mathe",
        ],
        "mirrors": "/health/",
        "read_only": True,
        "run_args": [],
        "category": "read",
    },
    {
        "name": "why_no_trade",
        "title": "Why no trade",
        "purpose": "Answer, in one pass, why the bots are not opening positions — master switch, component rows, beats, symbols, bars and gates, including the silent ones.",
        "usage": [
            "python manage.py why_no_trade",
            "python manage.py why_no_trade --symbols 8",
        ],
        "mirrors": "/health/",
        "read_only": True,
        "run_args": [],
        "category": "read",
    },
    {
        "name": "ibkr-doctor",
        "title": "IBKR doctor",
        "purpose": "Why is the broker unreachable? One read-only host script that gathers every fact the runbook says to look at, in the order that decides.",
        "usage": [
            "./deploy/ibkr-doctor            slot 1 (ibgateway)",
            "./deploy/ibkr-doctor --slot 2   a second login's container",
        ],
        "mirrors": "/health/",
        "read_only": True,
        "run_args": [],
        "category": "read",
        # A shell script beside the compose file, not a management command:
        # the registry-completeness test skips it and the Run lane refuses it.
        "management_command": False,
        "runnable": False,
        "runnable_reason": "runs on the host, needs docker",
    },
    # ── ops: one-off writes ─────────────────────────────────────────────
    {
        "name": "seed_components",
        "title": "Seed components",
        "purpose": "Register all platform components — every switch the code knows, created OFF where it does not yet exist in the database.",
        "usage": [
            "python manage.py seed_components",
        ],
        "mirrors": "/health/",
        "read_only": False,
        "run_args": [],
        "category": "ops",
    },
    {
        "name": "seed_research_fleet",
        "title": "Seed the research fleet",
        "purpose": "Seed paper bots across the whole keyless catalogue, chunked ten symbols a config, within a budget the bar refresh can afford; --dry-run only prints.",
        "usage": [
            "python manage.py seed_research_fleet                 # every keyless class",
            "python manage.py seed_research_fleet --budget 80     # fewer symbols",
            "python manage.py seed_research_fleet --dry-run       # print, write nothing",
            "python manage.py seed_research_fleet --reset         # remove the fleet",
        ],
        "mirrors": "/asset-bots/",
        "read_only": False,
        "run_args": [],
        "category": "ops",
    },
    {
        "name": "backfill_bars",
        "title": "Backfill bars",
        "purpose": "Backfill historical OHLCV bars for every asset class, keylessly, so the long-window rules have the lookback they need.",
        "usage": [
            "python manage.py backfill_bars --symbols BTCUSD,ETHUSD",
            "python manage.py backfill_bars --symbols BTCUSD --intervals 4h --bars 800",
            "python manage.py backfill_bars --symbols GLDM,SLV --intervals 1d --bars 300",
            "python manage.py backfill_bars --from-configs        # every enabled bot",
        ],
        "mirrors": "/forensics/",
        "read_only": False,
        "run_args": [],
        "category": "ops",
    },
    {
        "name": "recalculate_all_indicators",
        "title": "Recalculate indicators",
        "purpose": "Recompute every indicator over the stored bars — the step backfill_bars prints as its 'Next'; a Celery task reached through the shell, not a management command.",
        "usage": [
            'python manage.py shell -c "from indicators.tasks import recalculate_all_indicators as r; print(r())"',
        ],
        "mirrors": "/forensics/",
        "read_only": False,
        "run_args": [],
        "category": "ops",
        "management_command": False,
        "runnable": False,
        "runnable_reason": "a Celery task, run through manage.py shell",
    },
]

# Management commands under bot_program/brain/signals/core that the
# catalogue deliberately leaves out, each with the reason. A command missing
# from both this set and COMMANDS fails tests/test_ops_cockpit.py.
EXEMPT = {
    "ops": "the catalogue itself",
    "bot_health": "heartbeat dump superseded by /health/ and why_no_trade",
    "bot_reconcile": "Binance-only reconciliation, run by the worker on restart",
    "backfill_taxlot_currency": "one-off data migration (forex tax lots)",
    "render_ibkr_env": "deploy step, writes .env — the runbook's, not the cockpit's",
    "seed_bots": "starter fleet seeder superseded by seed_research_fleet",
    "repair_hypothesis_grading": "one-off repair of measurement-failure refutations",
    "grade_signals": "nightly beat task; its CLI form is for the scheduler",
    "scan_smc": "manual scanner for one symbol — a development aid",
    "scan_smc_mtf": "manual scanner for one symbol — a development aid",
    "track_smc_lifecycle": "beat task's CLI form",
    "seed_advanced_strategies": "one-off seeder (phase 34-38)",
    "seed_strategies": "one-off seeder (phase 31)",
    "build_icons": "build step, rasterizes the mark",
    "create_users": "first-install step — creates accounts, runbook §3",
}

# The Django apps whose management commands the registry must account for.
REGISTRY_APPS = ("bot_program", "brain", "signals", "core")


def get(name: str):
    """The registry entry named `name`, or None."""
    for entry in COMMANDS:
        if entry["name"] == name:
            return entry
    return None


def is_management_command(entry: dict) -> bool:
    return bool(entry.get("management_command", True))


def is_runnable(entry: dict) -> bool:
    """True iff the page's Run lane may execute this entry: read-only,
    a real management command, and not flagged unrunnable."""
    return (bool(entry.get("read_only"))
            and is_management_command(entry)
            and bool(entry.get("runnable", True)))


def runnable_names() -> set:
    return {e["name"] for e in COMMANDS if is_runnable(e)}


def by_category() -> list:
    """[(key, label, [entries])] in CATEGORIES order — what the page and
    `ops` both iterate, so they group identically."""
    out = []
    for key, label in CATEGORIES:
        rows = [e for e in COMMANDS if e["category"] == key]
        out.append((key, label, rows))
    return out
