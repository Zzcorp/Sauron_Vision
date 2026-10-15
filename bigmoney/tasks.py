"""The Big Money Board's beat task (spec §2.10).

05:20 UTC every day (after the 22:30 end-of-day bars, the crypto daily
close that market_data.tasks.fetch_eod_crypto writes at 00:10 UTC, and the
03:30 calibration resolver, before the 07:00 brief) and 23:20 UTC Monday to
Friday (after the 22:30 bars, for eToro's overnight session). Behind the
big_money_board switch, OFF on arrival. Writes BigMoneyRead, BigMoneyCell
and, on the morning run, AgentPrediction direction calls; nothing else.

A read that fails outright is never stored: it would overwrite a good read
of the same day and delete its pending claims, or, dated a weekend day,
outrank Friday's read on the page, the brief and the ticket. Its warning
still reaches the digest through the return value.
"""
import logging

from celery import shared_task

from core.task_gate import guarded_task

logger = logging.getLogger(__name__)


def run_board(run="morning", *, now=None) -> dict:
    """read_board -> store -> score due cells -> calibration calls (morning
    only). The result speaks core.task_gate.judge_result's vocabulary: a
    warning in its own words when a footprint is blind, so the daily digest
    names the blind input."""
    from bigmoney import words as W
    from bigmoney.read import read_board
    from bigmoney.score import calibrate, score_due, store_board

    board = read_board(run=run, now=now)
    failed = bool(board.get("failed"))
    stored = 0 if failed else store_board(board)
    try:
        score_due()
    except Exception as e:  # noqa: BLE001
        logger.warning("[big money] scoring failed: %s", e)
    if run == "morning" and not failed:
        try:
            calibrate(board)
        except Exception as e:  # noqa: BLE001
            logger.warning("[big money] calibration failed: %s", e)
    m, n = int(board.get("footprints") or 0), int(board.get("unread_count") or 0)
    if n:
        return {"status": "warning",
                "reason": W.TASK_WARNING.format(
                    n=n, m=m, reasons="; ".join((board.get("reasons") or [])[:2])),
                "parsed": m, "stored": stored}
    return {"status": "success", "parsed": m, "stored": stored}


@shared_task
@guarded_task("big_money_board")
def compute_big_money_board(run="morning"):
    return run_board(run)
