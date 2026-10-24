"""BORN (spec §1.2): one Orc per open position, idempotent.

Called on commit from the three places a position starts (execute_entry
for an immediate fill, _finish_working_entry when a working entry fills,
TAKE TRADE's _book_row) and from the census, which adopts whatever the
hooks missed. Every path goes through `ensure`, which:
  1. skips a row that can never act: not OPEN, an entry still working at
     the venue, an options row or config, a config no tick manages;
  2. reads the row's money world with the platform's own rule
     (dashboard.position_summary.world_of: live, demo or paper) and caps
     the Orcs outside real money, paper and eToro demo together
     (OrcSetting "max_paper_orcs", 10);
  3. freezes `manual`, FAILING TOWARD MANUAL: the operator's ticket must
     never become a bot idea with commission class because a read failed
     (the care's own lane read fails toward a bot, position_care.py:583-588);
  4. seats the idea at L0 on (world, class, rule key): a demo row never
     sits on the real-money seat;
  5. freezes r_money from the initial stop (manual_close._risk_dollars);
  6. writes the thesis, the army type, the stamp on the row, the care
     ghost, the journal's first lines and the observer's memory;
  7. after the commit, tells the operator of an adopted REAL-MONEY row
     (never a paper or demo one).
All of it writes the Orc tables and the one stamp; nothing is sent to a
venue and no model is called.
"""
import logging
from decimal import Decimal
from functools import partial

from django.db import IntegrityError, transaction
from django.utils import timezone

from bot_program.orcs.constants import (COMMISSION_ADVISE, COMMISSION_CLASS,
                                        LEG_ROOT, MAX_PAPER_ORCS,
                                        RULE_KEY_ANY, RULE_KEY_MANUAL,
                                        STATE_BORN, STATE_DEAD, VENUE_DEMO,
                                        VENUE_LIVE, VENUE_PAPER)

logger = logging.getLogger(__name__)

SKIP_NOT_OPEN = "not an open position"
SKIP_WORKING = "an entry still working at the venue"
SKIP_OPTIONS = "an options row: no Orc acts on a premium"
SKIP_UNTICKED = "a config no tick manages"


# ── the hooks ─────────────────────────────────────────────────────────────

def ensure_on_commit(trade, cache=None) -> None:
    """The entry paths' hook: registers the birth to run once the booking
    commits (so a rolled-back ticket births nothing), with no query of its
    own. A working entry registers nothing: it is born at its fill.
    Never raises."""
    try:
        pk = getattr(trade, "pk", None)
        if pk is None:
            return
        meta = trade.metadata if isinstance(trade.metadata, dict) else {}
        if meta.get("entry_working"):
            return
        transaction.on_commit(partial(_ensure_quietly, pk, trade, cache),
                              robust=True)
    except Exception as e:  # noqa: BLE001 — the Orcs never stop an entry
        logger.warning("[orcs] birth not registered for #%s: %s",
                       getattr(trade, "pk", "?"), e)


def _ensure_quietly(pk, obj=None, cache=None) -> None:
    from bot_program.orcs.switches import orcs_on
    try:
        if not orcs_on(cache):
            return
        if obj is None:
            from bot_program.models import AssetBotTrade
            obj = AssetBotTrade.objects.filter(pk=pk).first()
            if obj is None:
                return
        # ensure reads the row fresh and copies the stamp onto `obj`, the
        # caller's copy in memory
        ensure(obj)
    except Exception as e:  # noqa: BLE001 — never raises
        logger.warning("[orcs] #%s was not born: %s", pk, e)


# ── the rules ─────────────────────────────────────────────────────────────

def fail_toward_manual(trade, cfg) -> bool:
    """The operator's own idea: the manual rule, or the manual lane. Any
    read that fails says manual (never a bot idea with commission class)."""
    try:
        from bot_program.manual_trade import MANUAL_RULE
        from bot_program.share_allocator import _is_manual_lane
        return (str(trade.rule_name or "") == MANUAL_RULE
                or bool(_is_manual_lane(cfg)))
    except Exception as e:  # noqa: BLE001 — fails toward manual
        logger.info("[orcs] #%s: the lane is unread, manual: %s",
                    getattr(trade, "pk", "?"), e)
        return True


def ticked(cfg, row) -> bool:
    """A tick manages this row: an enabled config, a braked one
    (runner.manage_braked), or a stopped one's paper row
    (runner.manage_stopped_paper)."""
    from bot_program.asset_engine import disarm
    return bool(getattr(cfg, "enabled", False)
                or disarm.keeps_managing(cfg)
                or (row.paper and disarm.manages_paper_only(cfg)))


def skip_reason(row, cfg) -> str:
    """Why a row gets no Orc (yet), or "" (§1.2)."""
    from bot_program.asset_engine.base import is_entry_working
    if row.status != "OPEN":
        return SKIP_NOT_OPEN
    if is_entry_working(row):
        return SKIP_WORKING
    if (str(row.asset_class) == "options"
            or str(getattr(cfg, "asset_class", "")) == "options"):
        return SKIP_OPTIONS
    if not ticked(cfg, row):
        return SKIP_UNTICKED
    return ""


def world(row) -> str:
    """The row's money world, by the platform's one rule
    (dashboard.position_summary.world_of, the reader bot_grading's world
    filter and Morgul agree with): VENUE_LIVE, VENUE_DEMO or VENUE_PAPER.
    An eToro demo row is paper=False with broker_env "paper": demo, never
    real money. Not fenced: a birth that cannot read the world fails and
    the census tries again, rather than freezing a guess into the seat."""
    from dashboard.position_summary import world_of
    return {VENUE_PAPER: VENUE_PAPER,
            VENUE_DEMO: VENUE_DEMO}.get(world_of(row), VENUE_LIVE)


def paper_cap() -> int:
    """How many Orcs outside real money (paper and demo) may live at once."""
    from bot_program.orcs.models import OrcSetting
    try:
        return int(OrcSetting.get("max_paper_orcs", MAX_PAPER_ORCS))
    except (TypeError, ValueError):
        return MAX_PAPER_ORCS


def paper_left() -> int:
    """The room left under the cap: the cap less the live Orcs whose seat
    is not real money (paper and demo, the seat's venue being the row's
    world frozen at birth)."""
    from bot_program.orcs.models import Orc
    used = (Orc.objects.exclude(state=STATE_DEAD)
            .exclude(seat__venue=VENUE_LIVE).count())
    return paper_cap() - used


def paper_room() -> bool:
    return paper_left() > 0


def r_money(row):
    """The money 1R stood for at birth, from the initial stop
    (manual_close._risk_dollars: the forex and options multipliers
    included); None when the row has no stop. A scaled-out row is measured
    on its original size."""
    from bot_program.manual_close import _risk_dollars
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    so = meta.get("scale_out") if isinstance(meta.get("scale_out"),
                                             dict) else {}
    probe = row
    if so.get("original_qty") is not None:
        import copy
        probe = copy.copy(row)
        try:
            probe.qty = Decimal(str(so["original_qty"]))
        except Exception:  # noqa: BLE001
            probe = row
    risk = _risk_dollars(probe)
    if not risk or risk <= 0:
        return None
    return Decimal(str(round(risk, 4)))


def _seat(row, manual, venue):
    from bot_program.orcs.models import OrcSeat
    seat, _ = OrcSeat.objects.get_or_create(
        venue=venue, asset_class=str(row.asset_class or "")[:12],
        rule_key=RULE_KEY_MANUAL if manual else RULE_KEY_ANY)
    return seat


def _leg_orc(pk):
    from bot_program.orcs.models import OrcLeg
    leg = OrcLeg.objects.select_related("orc").filter(trade_id=pk).first()
    return leg.orc if leg is not None else None


def _existing(pk):
    """The fast path: the row's idea when it has one already."""
    return _leg_orc(pk)


# ── the birth ─────────────────────────────────────────────────────────────

def ensure(trade, *, adopted=False, now=None):
    """The row's Orc, born now if it has none and may have one; None when
    the row is skipped or the paper cap is full. Idempotent: a second call,
    or a race with another process, returns the one Orc."""
    from bot_program.models import AssetBotTrade
    pk = getattr(trade, "pk", None)
    if pk is None:
        return None
    existing = _existing(pk)
    if existing is not None:
        return existing
    row = AssetBotTrade.objects.select_related("config").filter(pk=pk).first()
    if row is None:
        return None
    cfg = row.config
    if skip_reason(row, cfg):
        return None
    venue = world(row)
    if venue != VENUE_LIVE and not paper_room():
        return None
    now = now or timezone.now()
    manual = fail_toward_manual(row, cfg)
    # read before the lock: the bars, the calendar and the clock
    from bot_program.orcs import army, situation, thesis
    sit = situation.situation_for(row, cfg, manual=manual, now=now)
    assigned = army.assign(sit)
    the_menu = menu_at_birth(row, now)
    the_thesis = thesis.build(row, cfg, manual=manual,
                              source="reconstructed" if adopted else "entry",
                              menu=the_menu, army_type=assigned["base"])
    try:
        with transaction.atomic():
            orc = _create(row, cfg, manual=manual, adopted=adopted,
                          sit=sit, assigned=assigned, the_thesis=the_thesis,
                          the_menu=the_menu, now=now)
            if orc is None:
                # born by another process while we read (the row lock
                # serialises births on Postgres; this re-check sees it)
                return _leg_orc(pk)
            if adopted and orc.seat.venue == VENUE_LIVE:
                transaction.on_commit(partial(notify_adopted, orc.pk),
                                      robust=True)
    except IntegrityError:
        # another process made it between our check and our create (the
        # one-to-ones from the row to its Orc and its leg)
        return _leg_orc(pk)
    orc.just_born = True
    stamp = (row.metadata or {}).get("orc")
    if isinstance(stamp, dict) and trade is not row:
        try:
            trade.metadata = {**(trade.metadata or {}), "orc": stamp}
        except Exception:  # noqa: BLE001
            pass
    return orc


def menu_at_birth(row, now):
    """The symbol's menu at birth (bot_program/orcs/menu.py), on the venue's
    bars; None when it cannot be read. Never raises."""
    try:
        from bot_program.orcs import menu
        return menu.symbol_levels(row.symbol, str(row.asset_class or ""),
                                  now=now)
    except Exception as e:  # noqa: BLE001 — an unread menu is no menu
        logger.info("[orcs] #%s: the menu at birth was not read: %s",
                    getattr(row, "pk", "?"), e)
        return None


def menu_line(the_menu) -> str:
    if the_menu is None:
        return "The menu at birth is empty: its bars could not be read."
    if not the_menu.levels:
        why = "; ".join(the_menu.why) or "no level within reach"
        return f"The menu at birth is empty: {why}."
    tfs = ", ".join(the_menu.tfs) or "no"
    source = the_menu.source or "no source"
    return (f"The menu at birth: {len(the_menu.levels)} levels on {tfs} "
            f"venue bars ({source}).")


def _create(row, cfg, *, manual, adopted, sit, assigned, the_thesis,
            the_menu=None, now=None):
    from bot_program.models import AssetBotTrade
    from bot_program.orcs import facts, ghost, journal
    from bot_program.orcs.constants import SEED_ADOPT, SEED_BIRTH
    from bot_program.orcs.models import Orc, OrcLeg
    locked = AssetBotTrade.objects.select_for_update().get(pk=row.pk)
    if OrcLeg.objects.filter(trade_id=row.pk).exists():
        return None
    if locked.status != "OPEN":
        return None
    seat = _seat(locked, manual, world(locked))
    orc = Orc.objects.create(
        seat=seat, user_id=cfg.user_id, config=cfg, root_trade=locked,
        symbol=locked.symbol, side=str(locked.side or "").upper(),
        asset_class=str(locked.asset_class or "")[:12],
        paper=bool(locked.paper), manual=manual, state=STATE_BORN,
        commission=COMMISSION_ADVISE if manual else COMMISSION_CLASS,
        r_money=r_money(locked),
        ccy=str(getattr(cfg, "base_currency", "") or "")[:10],
        adopted=bool(adopted), thesis=the_thesis,
        army_type=assigned["base"],
        army_why={**assigned, "situation": _compact(sit)})
    OrcLeg.objects.create(orc=orc, trade=locked, kind=LEG_ROOT, seq=1)
    # THE STAMP (§10.1): metadata["orc"] merged on the row read fresh under
    # its lock above (the _save_care / AssetBot._merge_row_metadata
    # pattern: other writers are never clobbered by a stale copy), in the
    # same transaction as the Orc and its leg.
    meta = dict(locked.metadata or {})
    meta["orc"] = {"idea": orc.pk, "leg": 1, "kind": LEG_ROOT,
                   "parent_rule": str(locked.rule_name or "")}
    locked.metadata = meta
    locked.save(update_fields=["metadata"])
    row.metadata = meta
    # THE ARMS (O1b, §6.1): every arm seeded once, in this transaction,
    # before any Orc candidate can exist
    ghost.seed_tracks(orc, locked, now=now,
                      seed=SEED_ADOPT if adopted else SEED_BIRTH)
    journal.append(orc, "adopt" if adopted else "birth",
                   facts.birth_line(locked, adopted=adopted),
                   body={"leg": locked.pk, "manual": manual,
                         "seat": [seat.venue, seat.asset_class,
                                  seat.rule_key],
                         "commission": orc.commission},
                   # the seat's level at the birth, frozen for the grade
                   # (a seat promoted later changes nothing)
                   remember={"level_at_birth": int(seat.level or 0)})
    journal.append(orc, "fact", facts.army_line(assigned),
                   body={"army": assigned["base"], "why": assigned["why"]},
                   fact=True)
    if assigned.get("overlay"):
        journal.append(orc, "fact", facts.overlay_line(assigned),
                       body={"overlay": assigned["overlay"],
                             "why": assigned["overlay_why"]}, fact=True)
    journal.append(orc, "fact", menu_line(the_menu),
                   body=({"menu": the_menu.as_dict()} if the_menu is not None
                         else {"menu": None}),
                   fact=True, remember={"menu_source": (
                       the_menu.source if the_menu is not None else "")})
    if the_menu is not None and the_menu.levels and not [
            p for p in (the_thesis.get("invalidation") or [])
            if p.get("kind") == "close_beyond"]:
        # an empty menu already said why in the line above
        journal.append(orc, "fact",
                       "No level invalidation written at birth: no 4h "
                       "structure level stands between the entry and the "
                       "stop.", body={"predicate": "close_beyond"},
                       fact=True)
    facts.baseline(orc, locked)
    return orc


def _compact(sit) -> dict:
    keep = ("persona", "hold_h", "stop_distance", "atr", "atr_source",
            "spread", "spread_source", "prints", "exotic_legs", "gap_p90_r",
            "crypto_weekend", "exchange", "at")
    out = {k: sit.get(k) for k in keep}
    out["shuts"] = [{k: s.get(k) for k in ("at", "kind", "hours")}
                    for s in (sit.get("shuts") or [])[:6]]
    return out


# ── the operator's line ───────────────────────────────────────────────────

def adoption_line(orc) -> str:
    side = "long" if str(orc.side).upper() == "BUY" else "short"
    head = f"Orc #{orc.root_trade_id} adopted {orc.symbol} {side}"
    if orc.manual:
        return (f"{head} (advise). Its thesis is reconstructed; state yours "
                f"on its page.")
    return (f"{head} (bot idea, shadow). Its thesis is reconstructed from the "
            f"entry's record.")


def notify_adopted(orc_id) -> bool:
    """One line to the operator's own channel for an adopted REAL-MONEY
    row (paper and eToro demo rows: the journal only; the seat's venue is
    the row's world). Never the alarm group. Quiet hours apply
    (dispatch_notification). Never raises."""
    try:
        from bot_program.notifications import (NOTIFY_MARKS,
                                               dispatch_notification)
        from bot_program.orcs.models import Orc
        orc = Orc.objects.select_related("user", "seat").get(pk=orc_id)
        if orc.seat.venue != VENUE_LIVE:
            return False
        return bool(dispatch_notification(
            orc.user, "orc_adopted", title=adoption_line(orc), body="",
            url=f"/orcs/{orc.root_trade_id}/",
            row_data={"kind": "orc_adopted", "orc": orc.pk,
                      "mark": NOTIFY_MARKS.get("orc_adopted", "")}))
    except Exception as e:  # noqa: BLE001
        logger.warning("[orcs] the adoption of Orc %s was not told: %s",
                       orc_id, e)
        return False
