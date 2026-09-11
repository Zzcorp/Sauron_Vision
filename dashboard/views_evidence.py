"""The evidence ledger page — /evidence/.

The numbers live in bot_program.evidence, shared with the strategy
generator's snapshot and the shadow gate; this module only renders them.
Three tables, all read-only: RULES (graded signals, paper and live fills,
the regret), CONFIGS (what each pool did, and what its shadow called), and
a pointer to the agents' calls ledger on /calibration/.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from bot_program.evidence import (  # noqa: F401 — re-exported for callers
    config_rows, rule_rows, shadow_agent_for,
)


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
    return render(request, "dashboard/evidence.html", {
        "page_id": "evidence", "rules": rules, "configs": configs,
        "totals": totals,
    })
