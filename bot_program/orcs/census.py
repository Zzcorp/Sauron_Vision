"""THE CENSUS (spec §1.2, §10.3): the safety net, every 5 minutes on the
fast queue, behind the `orcs` switch.

  1. deaths    the sweep: a live Orc whose legs are all closed ends,
               FIRST, so a slot it held under the paper cap is free for
               this pass's births
  2. births    every OPEN row with no Orc that may have one is adopted
               (paper and demo rows oldest first, under the cap on the
               Orcs outside real money, counted once a pass; with the cap
               full those rows are not even read): by definition the entry
               moment was missed, so the thesis is reconstructed from the
               row
  3. stamps    an open leg whose stamp another writer dropped is stamped
               again (a full save from a stale copy in memory)
  4. reviews   a new reviewer verdict on an open leg is a fact
  5. pending   a close pending at the venue is a fact
  6. seeded    (O1b) an Orc born before its arms existed gets them, marked
               "late": graded, never counted for a seat
  7. O1c       the reasons the next tick's wake merges: the book (W7), the
               clock around a print (W5), a close pending (W10); the
               market's drums (the LiveQuote ring, news shocks, print
               surprises) and the routing of every unrouted drum within
               its user's book, as journal facts

Each row runs on its own: one that fails never stops the pass. The result
names no `skipped`, `parsed` or `attempted` key: the task gate reads those
as a health verdict (core/task_gate.py judge_result).
"""
import logging

from django.db import transaction

from bot_program.orcs.constants import STATE_DEAD, VENUE_LIVE

logger = logging.getLogger(__name__)


def _births(now) -> tuple:
    from bot_program.bot_grading import WORLD_LIVE, _world_filter
    from bot_program.models import AssetBotTrade
    from bot_program.orcs import birth
    born = 0
    rows = (AssetBotTrade.objects.select_related("config")
            .filter(status="OPEN", orc_leg__isnull=True)
            .order_by("opened_at", "id"))
    # THE CAP, COUNTED ONCE A PASS: with no room left the rows outside
    # real money are not read at all (the platform's own world filter), so
    # a full cap costs nothing per capped row, pass after pass, on the fast
    # queue the guards and the pollers share. `ensure` still checks the cap
    # itself on its fresh read: this count only spares it the work.
    room = birth.paper_left()
    if room <= 0:
        rows = _world_filter(rows, WORLD_LIVE)
    for row in rows:
        try:
            # no query: the config came with the row; a row skipped for
            # good (an options row, a config no tick manages) costs
            # `ensure` nothing
            if birth.skip_reason(row, row.config):
                continue
            capped = birth.world(row) != VENUE_LIVE
            if capped and room <= 0:
                continue
            orc = birth.ensure(row, adopted=True, now=now)
            if orc is not None and getattr(orc, "just_born", False):
                born += 1
                if capped:
                    room -= 1
        except Exception as e:  # noqa: BLE001 — one row never stops it
            logger.warning("[orcs] census: #%s not adopted: %s", row.pk, e)
    return born, born


def _restamp() -> int:
    from bot_program.models import AssetBotTrade
    from bot_program.orcs.models import OrcLeg
    n = 0
    legs = (OrcLeg.objects.select_related("trade")
            .filter(trade__status__in=("OPEN", "CLOSE_PENDING"))
            .exclude(orc__state=STATE_DEAD))
    for leg in legs:
        try:
            meta = leg.trade.metadata if isinstance(leg.trade.metadata,
                                                    dict) else {}
            stamp = meta.get("orc")
            if isinstance(stamp, dict) and stamp.get("idea") == leg.orc_id:
                continue
            with transaction.atomic():
                row = AssetBotTrade.objects.select_for_update().get(
                    pk=leg.trade_id)
                fresh = dict(row.metadata or {})
                if (isinstance(fresh.get("orc"), dict)
                        and fresh["orc"].get("idea") == leg.orc_id):
                    continue
                fresh["orc"] = {"idea": leg.orc_id, "leg": leg.seq,
                                "kind": leg.kind,
                                "parent_rule": str(row.rule_name or "")}
                row.metadata = fresh
                row.save(update_fields=["metadata"])
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[orcs] census: #%s not restamped: %s",
                           leg.trade_id, e)
    return n


def _seed_late(now) -> int:
    """An Orc born before its arms existed (O1a's births) gets the arms it
    lacks, seeded now from the row as it stands, and its O1a care track is
    brought to the arms' format in place, its own care state kept
    (ghost.seed_tracks), all marked "late": such an idea is graded but
    never counts for a seat (spec §6.4). Only living Orcs are counted."""
    from django.db.models import Count

    from bot_program.orcs import ghost
    from bot_program.orcs.constants import GHOST_ARMS, SEED_LATE
    from bot_program.orcs.models import Orc, OrcTrack
    have = dict(OrcTrack.objects.exclude(orc__state=STATE_DEAD)
                .values("orc").annotate(n=Count("id"))
                .values_list("orc", "n"))
    n = 0
    for orc in (Orc.objects.exclude(state=STATE_DEAD)
                .select_related("root_trade__config")):
        if have.get(orc.pk, 0) >= len(GHOST_ARMS):
            continue
        try:
            ghost.seed_tracks(orc, orc.root_trade, now=now, seed=SEED_LATE)
            n += 1
        except Exception as e:  # noqa: BLE001 — one idea never stops it
            logger.warning("[orcs] census: Orc %s not seeded: %s", orc.pk, e)
    return n


def run(now=None) -> dict:
    from django.utils import timezone

    from bot_program.orcs import facts, lifecycle
    from bot_program.orcs.switches import orcs_on
    if not orcs_on():
        return {"status": "skipped", "reason": "orcs_disabled"}
    now = now or timezone.now()
    out = {"status": "success", "born": 0, "adopted": 0, "died": 0,
           "facts": 0, "restamped": 0, "seeded": 0}
    # the dead first: the cap is counted after the sweep has ended the
    # Orcs whose legs closed where no receiver saw them
    steps = (
        ("died", lambda: lifecycle.sweep(now)),
        ("born", lambda: _births(now)),
        ("restamped", _restamp),
        ("seeded", lambda: _seed_late(now)),
    )
    for key, step in steps:
        try:
            value = step()
            if key == "born":
                out["born"], out["adopted"] = value
            else:
                out[key] = value
        except Exception as e:  # noqa: BLE001 — one step never stops the rest
            logger.warning("[orcs] census step %s failed: %s", key, e)
    try:
        legs = facts._open_legs()
        out["facts"] += facts.observe_reviews(now, legs=legs)
        out["facts"] += facts.observe_pending(now, legs=legs)
    except Exception as e:  # noqa: BLE001
        logger.warning("[orcs] census: facts not read: %s", e)
    from bot_program.orcs import drum_bus, wake
    o1c = (("book", lambda: wake.census_book(now)),
           ("clock", lambda: wake.census_clock(now)),
           ("pending_w10", lambda: wake.census_pending(now)),
           ("drums_published", lambda: drum_bus.census_market(now)),
           ("drums_routed", lambda: drum_bus.route(now)))
    for key, step in o1c:
        out[key] = 0
        try:
            out[key] = int(step() or 0)
        except Exception as e:  # noqa: BLE001 — one step never stops the rest
            logger.warning("[orcs] census step %s failed: %s", key, e)
    return out
