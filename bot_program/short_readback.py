"""THE SHORT READ-BACK (2026-10-31): a hand-taken short on a class nobody
has measured at eToro is read back from eToro right after its fill.

The operator, 2026-10-31: "je veux les short possible entierement svp"
(I want shorts fully possible, please). Until then the TAKE TRADE lane
sent a SELL at eToro only on the classes whose demo short round trip is
pinned (asset_engine/base.py ETORO_SHORT_PROVEN: stock and forex since
2026-10-01); an ETF, an index, a commodity or a crypto short was refused
after the trading PIN. The lane now sends it on every class eToro's own
eligibility allows. THE BOTS KEEP THE PROOF GATE: they short a class only
once its short is proven.

What stands in for the missing measurement, on this lane alone:

  BEFORE THE PIN  the ticket says it (ticket_advisory: "First shorts on
                  <class> at eToro are not measured yet. ..."). Every other
                  gate stands: the PIN, the class proof, the venue's row,
                  the venue minimum, the headroom, the in-doubt handling,
                  the venue's health.
  AT THE FILL     the fill's own orders:lookup body, the one market_order
                  polled until Filled (fill_reading, 2026-10-31: no second
                  GET on the 20-per-60-s quota the poll has just used);
                  with no such body in hand, ONE orders:lookup GET by the
                  order id (the adapter's order_status), never /portfolio,
                  which lags (MEASURED 2026-09-23: absent ~2 s after a
                  fill): the side, the units, the multiplier, the position
                  id, its state and its settlement, against what was sent
                  (judge). A WORKING order is read back when it fills, off
                  the fill's own reading (AssetBot._finish_working_entry).
  CLEAN           the round trip is recorded as a measured short
                  (bot_program/short_models.EtoroShortObservation: the
                  facts a developer pins today), which the bots' gate can
                  later be opened on.
  UNANSWERED      a read eToro did not answer (a 5xx, a 429, a transport
                  error) says nothing of the position (2026-10-31): the
                  row is NOT flagged (ok None, state "unread") and the
                  next tick of the lane that holds it reads it ONCE more
                  by the order id (AssetBot.manage_positions,
                  read_again_due). Only a second unanswered read flags
                  it. A lane that no longer ticks never reads it again:
                  G13 says it once READ_AGAIN_GRACE_S has passed.
  ANYTHING ELSE   a different side, size, multiplier, position or
                  settlement, no position at all, or two reads eToro did
                  not answer: the row is flagged (metadata
                  ["short_readback"] ok False) — the Horde's seat and its
                  care box say it — and Morgul sounds at once
                  (morgul.say_now: the staff chats and the alarm chat),
                  then stands as its G13 finding while the row is open,
                  under a title that says which of the three it found.
                  Nothing is closed, resized or sent again: the alarm is
                  the act.

No account figure rides any of it: the words name sides, units,
multipliers and states, never an amount or an id.
"""
import logging
import re
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

#: The ticket's words, before the PIN (manual_trade._preview).
TICKET_WARNING = ("First shorts on {words} at eToro are not measured yet. "
                  "The platform reads the position back right after the "
                  "fill and alarms at once if eToro holds something else.")
#: A class in the operator's words.
CLASS_WORDS = {"etf": "ETFs", "index": "indices", "commodity": "commodities",
               "crypto": "crypto", "stock": "stocks", "forex": "forex"}
#: How far the units read back may sit from the units sent, relative,
#: before they are another size (float noise on an 8-decimal coin).
UNITS_TOLERANCE = 1e-6
CLEAN, MISMATCH, MISSING, UNREAD, PENDING = (
    "clean", "mismatch", "missing", "unread", "pending")
#: The account's own keys on a lookup body: never kept on an observation.
PRIVATE_KEYS = ("accountId", "gcid", "cid", "CID", "portfolioId")
#: The prefix of every sentence a surface prints about a read-back.
SAID = "Read back from eToro after the fill: "
#: ...and about one eToro did not answer (2026-10-31): nothing was read.
UNSAID = "Not read back from eToro after the fill: "
#: How many reads by the order id a short eToro did not answer for gets
#: (2026-10-31): the one at the fill, then ONE more on the next tick of
#: the lane that holds it. Only an unanswered second read flags the row.
READS = 2
#: How long an unanswered read-back waits for that second read before
#: Morgul's G13 says it: a lane that no longer ticks never reads it again.
READ_AGAIN_GRACE_S = 15 * 60
UNREAD_ONCE = ("eToro did not answer the read by the order id; the next "
               "tick reads it once more")
UNREAD_TWICE = ("eToro answered neither read by the order id; nothing "
                "reads it again")
UNREAD_LATE = ("eToro did not answer the read by the order id, and no tick "
               "has read it again in {minutes} minutes")

_UNSET = object()


def class_words(icls) -> str:
    cls = str(icls or "").strip().lower()
    return CLASS_WORDS.get(cls, cls or "this class")


def unmeasured(client, icls, side, leverage=None) -> bool:
    """Whether a hand-taken order is a short eToro has not been measured
    on: an eToro carrier, a SELL, and short_<class> among the proofs the
    bots' gate still lacks at the ticket's multiplier (base.missing_proofs,
    read at call time: a short the platform proved on the demo account at
    1x is measured at 1x only, 2026-10-31; None reads as 1)."""
    if str(side or "").upper() != "SELL":
        return False
    from bot_program.asset_engine.base import missing_proofs
    from bot_program.engine.capabilities import adapter_key
    if adapter_key(client) != "etoro":
        return False
    return f"short_{icls}" in missing_proofs(str(icls), "SELL",
                                             leverage=leverage)


def ticket_advisory(client, icls, side, *, live=True, leverage=None) -> dict:
    """{"ok", "class", "reason"} for the TAKE TRADE preview: the warning
    before the PIN for an unmeasured short (unmeasured, at the ticket's
    multiplier), else ok. A warning, never a refusal; a paper ticket is
    never warned."""
    quiet = {"ok": True, "class": "", "reason": ""}
    if not live:
        return quiet
    try:
        if not unmeasured(client, icls, side, leverage=leverage):
            return quiet
    except Exception as e:  # noqa: BLE001 — an unread proof warns of nothing
        logger.warning("[short-readback] proof set unread for %s: %s",
                       icls, e)
        return quiet
    return {"ok": False, "class": str(icls),
            "reason": TICKET_WARNING.format(words=class_words(icls))}


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    got = _num(value)
    if got is None or got != int(got):
        return None
    return int(got)


def _dec(value):
    got = _num(value)
    if got is None:
        return None
    try:
        return Decimal(str(got))
    except (InvalidOperation, ValueError):
        return None


def _when(value):
    """An aware datetime off one of eToro's timestamps ("...T21:02:22.
    1944487Z": seven fractional digits are printed), or None."""
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", text).replace("Z", "+00:00")
    try:
        got = datetime.fromisoformat(text)
    except ValueError:
        return None
    if got.tzinfo is None:
        got = got.replace(tzinfo=dt_timezone.utc)
    return got


def _execution(reading) -> tuple:
    """(raw lookup body, asset, the first execution, its openingData)."""
    raw = (reading or {}).get("raw") or {}
    raw = raw if isinstance(raw, dict) else {}
    asset = raw.get("asset") if isinstance(raw.get("asset"), dict) else {}
    execs = raw.get("positionExecutions") or []
    first = execs[0] if execs and isinstance(execs[0], dict) else {}
    opening = (first.get("openingData")
               if isinstance(first.get("openingData"), dict) else {})
    return raw, asset, first, opening


def fill_reading(res):
    """The fill's own orders:lookup body (market_order's raw["lookup"],
    the last body its fill poll read) as an order_status reading, so the
    read-back judges what is in hand and spends no second GET
    (2026-10-31). None unless that body is Filled (status 3) with its
    first position execution, the shape order_status reads as "filled";
    the read-back then asks once by the order id."""
    raw = (res or {}).get("raw") if isinstance(res, dict) else None
    lookup = raw.get("lookup") if isinstance(raw, dict) else None
    if not isinstance(lookup, dict):
        return None
    from bot_program.engine.etoro_client import _status_of
    sid, _words = _status_of(lookup)
    execs = lookup.get("positionExecutions") or []
    first = execs[0] if execs and isinstance(execs[0], dict) else None
    if sid != 3 or not first:
        return None
    reading = {"state": "filled", "statusId": sid, "raw": lookup}
    pid = first.get("positionId") or first.get("positionID")
    if pid:
        reading["positionId"] = str(pid)
    return reading


def judge(reading, *, sent_units, sent_leverage=1, position_id="") -> dict:
    """{"ok", "state", "facts", "held"}: eToro's reading of the order
    (the adapter's order_status: a dict, or None for could-not-ask)
    against the SELL that was sent. Pure. A read eToro did not answer is
    ok None: it says nothing of the position (after_fill decides whether
    to read again or to flag it)."""
    if reading is None:
        return {"ok": None, "state": UNREAD, "held": {},
                "facts": ["eToro did not answer the read by the order id"]}
    _raw, asset, first, opening = _execution(reading)
    pid = str(first.get("positionId") or first.get("positionID")
              or reading.get("positionId") or "")
    held = {"side": str(asset.get("side") or "").strip().lower(),
            "units": _num(opening.get("units")
                          if opening.get("units") is not None
                          else first.get("remainingUnits")),
            "leverage": _int(asset.get("leverage")),
            "position_id": pid,
            "state": str(first.get("state") or "").strip().lower(),
            "settlement": str(asset.get("settlementType") or "").strip()}
    if reading.get("state") != "filled" or not first or not pid:
        return {"ok": False, "state": MISSING, "held": held,
                "facts": ["eToro shows no position for this order"]}
    facts = []
    if not held["side"]:
        facts.append("eToro names no side for it")
    elif held["side"] != "short":
        facts.append(f"eToro holds it as a {held['side']}, not a short")
    units, sent = held["units"], float(sent_units or 0)
    if units is None:
        facts.append("eToro states no units for it")
    elif abs(units - sent) > UNITS_TOLERANCE * max(1.0, abs(sent)):
        facts.append(f"eToro holds {units:g} units, not the {sent:g} sent")
    want = int(sent_leverage or 1)
    if held["leverage"] is None:
        facts.append("eToro states no multiplier for it")
    elif held["leverage"] != want:
        facts.append(f"eToro holds it at {held['leverage']}x, not the "
                     f"{want}x sent")
    if position_id and pid != str(position_id):
        facts.append("eToro names another position than the fill")
    if held["state"] and held["state"] != "open":
        facts.append(f"eToro reads the position {held['state']} already")
    if held["settlement"] and held["settlement"].upper() != "CFD":
        facts.append(f"eToro settled it {held['settlement'].upper()}; a "
                     f"short is a CFD")
    return {"ok": not facts, "state": MISMATCH if facts else CLEAN,
            "facts": facts, "held": held}


def _facts(record) -> list:
    return [str(f) for f in record.get("facts") or [] if str(f).strip()]


def _waits(record) -> bool:
    """An unanswered read-back still waiting for its second read."""
    return (isinstance(record, dict) and record.get("ok") is None
            and record.get("state") == UNREAD)


def words(record) -> str:
    """The sentence the Horde's seat and care box print for a flagged
    read-back, or "" for none, a pending one, one still waiting for its
    second read, or a clean one. An unanswered one says nothing was read
    (UNSAID), never what eToro holds."""
    if not isinstance(record, dict) or record.get("ok") is not False:
        return ""
    lead = UNSAID if record.get("state") == UNREAD else SAID
    return lead + ("; ".join(_facts(record))
                   or "eToro holds something else") + "."


def ticket_note(record) -> str:
    """The confirmation's words after the fill, or ""."""
    said = words(record)
    if said:
        return (said + " Morgul has sounded the alarm: check the position "
                       "at eToro.")
    if _waits(record):
        return (UNSAID + "; ".join(_facts(record) or [UNREAD_ONCE]) + ". "
                "Morgul sounds if that read fails too, or finds eToro "
                "holding something else.")
    return ""


def read_again_due(trade) -> bool:
    """Whether the lane's tick reads this row's short back once more
    (2026-10-31): its read-back at the fill went unanswered."""
    meta = getattr(trade, "metadata", None)
    return _waits((meta or {}).get("short_readback")
                  if isinstance(meta, dict) else None)


def read_again_late(record, now) -> bool:
    """An unanswered read-back no tick has read again within
    READ_AGAIN_GRACE_S of its first read (Morgul's G13 says it)."""
    if not _waits(record):
        return False
    try:
        at = datetime.fromisoformat(str(record.get("at") or ""))
    except ValueError:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=dt_timezone.utc)
    return (now - at).total_seconds() > READ_AGAIN_GRACE_S


def late_words() -> str:
    return UNREAD_LATE.format(minutes=READ_AGAIN_GRACE_S // 60)


def _record(trade, record) -> None:
    meta = dict(trade.metadata or {})
    meta["short_readback"] = record
    trade.metadata = meta
    trade.save(update_fields=["metadata"])


def mark_pending(trade, *, icls, sent_units, sent_leverage=1,
                 now=None) -> dict:
    """A WORKING short: its read-back waits for the fill
    (AssetBot._finish_working_entry calls after_fill then)."""
    from django.utils import timezone
    record = {"ok": None, "state": PENDING, "facts": [], "held": {},
              "class": str(icls),
              "sent": {"side": "SELL", "units": float(sent_units),
                       "leverage": int(sent_leverage or 1),
                       "position_id": ""},
              "at": (now or timezone.now()).isoformat()}
    _record(trade, record)
    return record


def after_fill(trade, client, *, icls=None, sent_units=None,
               sent_leverage=None, position_id=None, reading=_UNSET,
               now=None) -> dict:
    """Read the short back, record the verdict on the row, then record a
    clean one as a measured short or sound Morgul. `reading` is an
    order_status reading already in hand (the fill's own lookup,
    fill_reading, or a WORKING order's fill); else ONE order_status GET
    by the row's order id. A read eToro did not answer is recorded as
    waiting (ok None) the first time, read once more by the lane's next
    tick (read_again_due), and flagged only when that read goes
    unanswered too (READS). Never raises: a failure anywhere is logged
    and the row keeps what it has."""
    from django.utils import timezone
    now = now or timezone.now()
    meta = dict(trade.metadata or {})
    pending = meta.get("short_readback") if isinstance(
        meta.get("short_readback"), dict) else {}
    sent = pending.get("sent") or {}
    icls = str(icls or pending.get("class") or trade.asset_class or "")
    units = float(sent_units if sent_units is not None
                  else (sent.get("units") or meta.get("qty_requested")
                        or trade.qty or 0))
    lev = int(sent_leverage if sent_leverage is not None
              else (sent.get("leverage") or meta.get("leverage") or 1))
    # the fill's position id rides the waiting record to the second read
    pid = str(position_id or sent.get("position_id") or "")
    reads = (int(pending.get("reads") or 1) + 1
             if pending.get("state") == UNREAD else 1)
    if reading is _UNSET:
        oid = str(trade.broker_order_id or "")
        try:
            reading = client.order_status(oid) if oid else None
        except Exception as e:  # noqa: BLE001 — could-not-ask, said
            logger.warning("[short-readback] %s #%s: order_status raised "
                           "%s", trade.symbol, trade.pk, e)
            reading = None
    verdict = judge(reading, sent_units=units, sent_leverage=lev,
                    position_id=pid)
    if verdict["state"] == UNREAD:
        last = reads >= READS
        verdict = dict(verdict, ok=False if last else None,
                       facts=[UNREAD_TWICE if last else UNREAD_ONCE])
    record = {"ok": verdict["ok"], "state": verdict["state"],
              "facts": verdict["facts"], "held": verdict["held"],
              "class": icls, "reads": reads,
              "sent": {"side": "SELL", "units": units, "leverage": lev,
                       "position_id": pid},
              "at": now.isoformat()}
    try:
        _record(trade, record)
    except Exception as e:  # noqa: BLE001
        logger.error("[short-readback] %s #%s: the verdict was not "
                     "recorded on the row: %s", trade.symbol, trade.pk, e)
    if verdict["ok"]:
        try:
            _observe(trade, client, reading, icls, units, now)
        except Exception as e:  # noqa: BLE001 — the row keeps its verdict
            logger.warning("[short-readback] %s #%s: the observation was "
                           "not recorded: %s", trade.symbol, trade.pk, e)
    elif verdict["ok"] is None:
        logger.warning("[short-readback] %s #%s: eToro did not answer the "
                       "read-back; the next tick reads it once more",
                       trade.symbol, trade.pk)
    else:
        logger.error("[short-readback] %s #%s: the read-back is flagged "
                     "(%s): %s", trade.symbol, trade.pk, verdict["state"],
                     "; ".join(verdict["facts"]))
        try:
            from bot_program import morgul
            morgul.say_now(morgul.short_readback_finding(trade), now=now)
        except Exception as e:  # noqa: BLE001 — G13 says it on the beat
            logger.error("[short-readback] %s #%s: Morgul could not be "
                         "sounded at once (%s); its beat says it",
                         trade.symbol, trade.pk, e)
    return record


def scrub(value):
    """`value` with the account's own keys (PRIVATE_KEYS) taken out at
    every depth: what a record may keep of an eToro body."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()
                if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def observation_facts(reading, *, units=0, order_id="") -> dict:
    """The fields of an EtoroShortObservation off an order_status reading
    (2026-10-31, shared by the read-back and the demo proof runner): the
    venue's spelling and id, the side, the settlement, the multiplier, the
    units, the order and position ids, the open rate, the fees, the legs
    held, the times, and the lookup body less the account's own keys.
    `units` and `order_id` stand in where the body prints none."""
    raw, asset, first, opening = _execution(reading)
    return dict(
        venue_symbol=str(asset.get("symbol") or ""),
        instrument_id=_int(asset.get("instrumentId")),
        side=str(asset.get("side") or "").lower(),
        settlement=str(asset.get("settlementType") or ""),
        leverage=_int(asset.get("leverage")) or 1,
        units=Decimal(str(_num(opening.get("units")) or units)),
        order_id=str(raw.get("orderId") or order_id or ""),
        position_id=str(first.get("positionId") or first.get("positionID")
                        or ""),
        open_rate=_dec(opening.get("avgPrice")),
        fees=_dec(opening.get("fees")),
        total_costs=_dec(raw.get("totalCosts")),
        requested_amount=_dec(raw.get("requestedAmount")),
        stop_held=_dec(first.get("stopLossRate")),
        target_held=_dec(first.get("takeProfitRate")),
        opened_at=_when(opening.get("openTime")),
        executed_at=_when(opening.get("executionTime")),
        lookup={k: v for k, v in raw.items() if k not in PRIVATE_KEYS})


def _observe(trade, client, reading, icls, units, now):
    """The clean read-back as an EtoroShortObservation."""
    from bot_program.short_models import EtoroShortObservation
    return EtoroShortObservation.objects.create(
        trade=trade, asset_class=icls, symbol=trade.symbol,
        world="demo" if getattr(client, "demo", False) else "live",
        read_at=now,
        **observation_facts(reading, units=units,
                            order_id=trade.broker_order_id or ""))
