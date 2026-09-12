"""The evidence ledger page — /evidence/.

The numbers live in bot_program.evidence, shared with the strategy
generator's snapshot and the shadow gate; this module only renders them.
Three tables, all read-only: RULES (graded signals, paper and live fills,
the regret), CONFIGS (what each pool did, and what its shadow called), and
a pointer to the agents' calls ledger on /calibration/.

A fourth card (2026-09-12): PERSONALITIES. The same graded rows, grouped
by the trader personality a config wears and windowed by the window that
personality declares — 21 days for scalp, 90 for swing, 365 for position.
One 90-day window graded all three as if they were the same evidence,
which is why it is broken out here rather than folded into the config
table.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from bot_program.evidence import (  # noqa: F401 — re-exported for callers
    config_rows, persona_rows, rule_rows, shadow_agent_for,
)

logger = logging.getLogger(__name__)


@login_required
def evidence_ledger(request):
    rules = rule_rows()
    configs = config_rows()
    totals = {
        "rules": len(rules),
        "sig_n": sum(r["sig_n"] for r in rules),
        "paper_r": round(sum(r["paper_r"] for r in rules), 2),
        "live_r": round(sum(r["live_r"] for r in rules), 2),
        "regret_r": round(sum(r["regret_r"] for r in rules), 2),
        "shadow_calls": sum(c["calls_n"] for c in configs),
    }
    # Fenced: the persona grade is one card, and a ledger that 500s
    # because personas are mid-migration hides the three tables that have
    # nothing to do with them.
    personas, personas_error = [], ""
    try:
        personas = persona_rows()
    except Exception as e:  # noqa: BLE001
        logger.warning("[evidence] persona grade unreadable: %s", e)
        personas_error = (f"The personality grade could not be read ({e}). "
                          f"The three tables below are unaffected.")
    return render(request, "dashboard/evidence.html", {
        "page_id": "evidence", "rules": rules, "configs": configs,
        "totals": totals, "personas": personas,
        "personas_error": personas_error,
    })
