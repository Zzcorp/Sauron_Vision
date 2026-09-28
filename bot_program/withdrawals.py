"""Withdrawals asked for in advance — the reserve, the flows, the readiness.

The operator and Gandalf file a request ahead of time ("I will take X out
of the real account by the 5th") and the platform's whole answer is to
STOP DEPLOYING X. It does not sell anything, it does not move a share, it
does not touch a plan: the balance and the direction of the portfolio are
exactly what they were, and cash builds up as positions close on their
own. Three places read the reserve, and only three:

  tasks._follow_the_account     every pool that follows the account is
                                sized from the reading LESS what is held
                                back, so they all shrink by the same
                                proportion and their shares are untouched
  manual_trade.arm_manual_lane  the one path that writes a follower's
                                capital itself, when the lane is armed
  AssetBot._leverage_headroom   the eToro cash gate never pledges the
                                reserved cash to a new order — it refuses
                                the order, never resizes it, never closes

A pool with a TYPED capital is not reduced — nothing retunes a typed
number, and a reserve must not become the first thing that does. The
readiness block lists those pools with a plain warning instead. Paper
pools are never affected: they follow nothing.

WHAT IS HELD BACK is the reserve (every request still `reserved`) plus
any withdrawal already marked paid AFTER the reading being sized from:
that money has left, but the last reading still counts it, and for up to
one sync (15 minutes) the pools would otherwise grow back into it.

WHEN THE MONEY LEAVES, the request is marked paid with the amount and the
moment, and it becomes a FLOW. `flow_adjusted_value` takes every paid
withdrawal made after a reading off that reading, so the high-water mark,
the drawdown and the 24 h drop compare readings on one footing: the
money that left on purpose is not a loss, and the governor does not
de-risk the account for it. Paid withdrawals only — a reserve has not
left the account, and a reading that includes it is simply true.

Every create, cancel and mark-paid re-runs the pool follow at once from
the stored reading (the same call views_admin_hq makes after a share
changes), so the pools do not wait for the next sync, and sends one
message to the group. Neither may break the request: both are guarded.

Nothing in this module places, closes or cancels an order.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

EM_DASH = "—"
ZERO = Decimal("0")
#: Above this share of the account a request is accepted with a warning:
#: half the account held back is a pool fleet at half its size.
WARN_FRACTION = Decimal("0.5")
#: A withdrawal marked paid this far in the future is a typo, not a plan —
#: a future flow would be taken off the CURRENT reading.
FUTURE_SLACK = timedelta(minutes=5)
#: The currency written when no reading has ever landed, and said so.
FALLBACK_CURRENCY = "USD"


def who_label(code) -> str:
    from .withdrawal_models import WithdrawalRequest
    return dict(WithdrawalRequest.WHO_CHOICES).get(str(code or ""), "")


def money(value, currency="") -> str:
    """'1,234.56 EUR', or an em dash for a number nobody measured."""
    if value is None:
        return EM_DASH
    try:
        text = f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return EM_DASH
    return f"{text} {currency}".strip()


# ── The reserve and the flows ────────────────────────────────────────────

def reserved_total(user) -> Decimal:
    """The sum of every request still reserved — held back from sizing."""
    from django.db.models import Sum

    from .withdrawal_models import WithdrawalRequest
    total = (WithdrawalRequest.objects
             .filter(user=user, status=WithdrawalRequest.STATUS_RESERVED)
             .aggregate(s=Sum("amount"))["s"])
    return Decimal(total or 0)


def paid_flows(user, currency=None) -> list:
    """[(paid_at, amount)] for every withdrawal marked paid, oldest first.

    `currency` narrows to one: the equity history is compared in the
    current reading's currency only (capital_truth), and a flow in another
    currency is a number nothing here converts.
    """
    from .withdrawal_models import WithdrawalRequest
    rows = (WithdrawalRequest.objects
            .filter(user=user, status=WithdrawalRequest.STATUS_PAID,
                    paid_at__isnull=False)
            .order_by("paid_at"))
    if currency is not None:
        rows = rows.filter(currency=currency)
    return [(r.paid_at, Decimal(r.flow_amount)) for r in rows]


def flow_adjusted_value(value, at, flows):
    """`value` as it would read had every later withdrawal already left.

    value - sum(amount for paid_at > at). A reading taken BEFORE a
    withdrawal still holds the money; taking it off makes that reading
    comparable with the ones taken after, which no longer do. A reading
    taken after every flow is returned unchanged. Same type in as out:
    float for the history readers, Decimal for the money paths.
    """
    if at is None or not flows:
        return value
    out = sum((Decimal(str(amount)) for paid_at, amount in flows
               if paid_at is not None and paid_at > at), ZERO)
    if isinstance(value, Decimal):
        return value - out
    return float(value) - float(out)


def paid_since(user, at) -> Decimal:
    """Withdrawals marked paid after `at` — money a reading taken at `at`
    still counts and the account no longer holds."""
    if at is None:
        return ZERO
    return sum((amount for paid_at, amount in paid_flows(user)
                if paid_at > at), ZERO)


_LOOK_UP = object()


def held_back(user, reading_at=_LOOK_UP) -> Decimal:
    """What must not be deployed out of a reading taken at `reading_at`:
    the reserve, plus every withdrawal paid since that reading.

    Left out, `reading_at` is the book's own stored reading — which is
    what every caller of _follow_the_account sizes from (the sync stores
    before it follows; the others pass account_equity). None means "no
    reading to be older than", and only the reserve counts.
    """
    if reading_at is _LOOK_UP:
        from .capital_truth import account_equity
        reading = account_equity(user)
        reading_at = reading["at"] if reading else None
    return reserved_total(user) + paid_since(user, reading_at)


def deployable(user, value, reading_at=_LOOK_UP):
    """(what the pools may be sized from, what is held back) — the reading
    less the hold, floored at zero. A reading smaller than the hold sizes
    every follower at 0: it opens nothing, and closes nothing either."""
    held = held_back(user, reading_at)
    base = Decimal(str(value)) - held
    return (base if base > 0 else ZERO), held


# ── Readiness: is the cash there, and what shrinks ───────────────────────

def _free_cash(user, book):
    """(free cash, read at, note) on the book, or (None, None, why).

    Only eToro stores a cash figure (last_available_cash, written by the
    sync from EtoroTrader.margin_cells). It counts only when it was read
    in the world the row trades now — the same test the cash gate
    applies — and a withdrawal paid since it was read is taken off,
    because the cell still holds that money. Saxo and IBKR store no cash
    cell: an em dash, never a zero.
    """
    from .capital_truth import broker_kind
    if book is None:
        return None, None, "no broker row is the book"
    if broker_kind(book) != "etoro":
        return None, None, (f"{broker_kind(book).upper()} stores no cash "
                            f"figure — only the account value")
    cash = getattr(book, "last_available_cash", None)
    at = getattr(book, "last_margin_at", None)
    if cash is None or at is None:
        return None, None, "the sync has never stored eToro's available cash"
    world = "demo" if getattr(book, "demo", False) else "live"
    if str(getattr(book, "last_margin_world", "") or "") != world:
        return None, at, (f"the cash figure was read in another world than "
                          f"the {world} one this row trades")
    return Decimal(cash) - paid_since(user, at), at, ""


def readiness(user) -> dict:
    """Everything the page's readiness block shows, measured once.

    {value, currency, at, age_seconds, reserved, paid_unread, held,
     deployable, free_cash, cash_at, cash_note, cash_ready, shortfall,
     following, following_note, typed_live, paper, n_active, book_name}

    Numbers are Decimals, None when not measured — the page prints an em
    dash, never a zero. `cash_ready` is None when the cash cannot be read.
    Pure DB reads: no broker call on a render path.
    """
    from .capital_truth import (account_equity, allocate_shares,
                                broker_backed, broker_kind, followers_of,
                                tracks_broker)
    from .models import AssetBotConfig
    from .withdrawal_models import WithdrawalRequest

    reading = account_equity(user)
    book = broker_backed(user)
    value = (Decimal(str(round(float(reading["value"]), 2)))
             if reading else None)
    currency = (reading["currency"] if reading else "") or ""
    reserved = reserved_total(user)
    paid_unread = paid_since(user, reading["at"]) if reading else ZERO
    held = reserved + paid_unread
    base = None
    if value is not None:
        base = value - held
        base = base if base > 0 else ZERO

    free_cash, cash_at, cash_note = _free_cash(user, book)
    cash_ready = shortfall = None
    if free_cash is not None:
        cash_ready = free_cash >= reserved
        shortfall = (reserved - free_cash) if not cash_ready else ZERO

    following, following_note = [], ""
    followers = followers_of(user)
    if followers:
        alloc = allocate_shares(followers)
        if not alloc["ok"]:
            following_note = (f"The shares do not fit in the account "
                              f"({alloc['reason']}), so no pool follows it "
                              f"until they do.")
        for cfg in followers:
            share = alloc["plan"].get(cfg.pk) if alloc["ok"] else None
            row = {"name": cfg.name, "asset_class": cfg.asset_class,
                   "share_pct": (share * 100.0 if share is not None
                                 else None),
                   "now": Decimal(cfg.capital or 0),
                   "before": None, "after": None}
            if share is not None and value is not None:
                row["before"] = Decimal(str(round(float(value) * share, 2)))
                row["after"] = Decimal(str(round(float(base) * share, 2)))
            following.append(row)

    typed_live, paper = [], []
    for cfg in (AssetBotConfig.objects.filter(user=user, enabled=True)
                .order_by("asset_class", "name")):
        if cfg.mode == "paper":
            paper.append({"name": cfg.name, "asset_class": cfg.asset_class,
                          "capital": Decimal(cfg.capital or 0),
                          "currency": cfg.base_currency or ""})
        elif not tracks_broker(cfg):
            cap = Decimal(cfg.capital or 0)
            typed_live.append({
                "name": cfg.name, "asset_class": cfg.asset_class,
                "capital": cap, "currency": cfg.base_currency or "",
                # The dangerous direction, said out loud: a typed pool
                # larger than what is left to deploy sizes against the
                # money the reserve is holding back.
                "over": base is not None and cap > base})

    return {
        "value": value, "currency": currency,
        "at": reading["at"] if reading else None,
        "age_seconds": reading["age_seconds"] if reading else None,
        "book_name": ({"saxo": "Saxo Bank", "etoro": "eToro",
                       "ibkr": "IBKR"}.get(broker_kind(book), "broker")
                      if book is not None else ""),
        "reserved": reserved, "paid_unread": paid_unread, "held": held,
        "deployable": base,
        "free_cash": free_cash, "cash_at": cash_at, "cash_note": cash_note,
        "cash_ready": cash_ready, "shortfall": shortfall,
        "following": following, "following_note": following_note,
        "typed_live": typed_live, "paper": paper,
        "n_active": WithdrawalRequest.objects.filter(
            user=user, status=WithdrawalRequest.STATUS_RESERVED).count(),
    }


# ── Parsing what the form sends ──────────────────────────────────────────

def parse_amount(raw):
    """(Decimal, "") or (None, why). Accepts '1234.56', '1,234.56' and the
    French '1 234,56'; refuses anything that is not a positive amount of
    money with at most two decimals."""
    if isinstance(raw, bool):
        return None, "the amount must be a number"
    if isinstance(raw, (int, float, Decimal)):
        text = str(raw)
    else:
        text = str(raw or "").strip().replace(" ", "").replace(" ", "")
        text = text.replace("_", "")
        if "," in text and "." in text:
            text = text.replace(",", "")
        elif "," in text:
            # "1,234" is a thousand in English and one-point-two in French:
            # refused rather than guessed, since either guess moves money.
            head, _, tail = text.rpartition(",")
            if len(tail) == 3 and text.count(",") == 1:
                return None, (f"{raw!s} could be read two ways — write it "
                              f"as {head}{tail} or {head}.{tail}")
            text = text.replace(",", ".")
    if not text:
        return None, "the amount is missing"
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, f"{raw!s} is not an amount"
    if not amount.is_finite():
        return None, "the amount must be a finite number"
    if amount <= 0:
        return None, "the amount must be more than zero"
    if amount != amount.quantize(Decimal("0.01")):
        return None, "the amount has more than two decimals"
    if amount >= Decimal("1e12"):
        return None, "the amount is too large to be a withdrawal"
    return amount.quantize(Decimal("0.01")), ""


def parse_date(raw):
    """(date or None, "") or (None, why) — 'YYYY-MM-DD', blank allowed."""
    text = str(raw or "").strip()
    if not text:
        return None, ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date(), ""
    except ValueError:
        return None, f"{text} is not a date (YYYY-MM-DD)"


def parse_moment(raw):
    """(aware datetime or None, "") or (None, why). The form's
    datetime-local, read as UTC — the page says so beside the field."""
    text = str(raw or "").strip()
    if not text:
        return None, ""
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=dt_timezone.utc), ""
    return None, f"{text} is not a date and time (YYYY-MM-DD HH:MM, UTC)"


def _who(raw):
    code = str(raw or "").strip().lower()
    return code if who_label(code) else ""


# ── The three acts ───────────────────────────────────────────────────────

def create_request(user, *, requested_by, amount, wanted_by=None,
                   reason="") -> dict:
    """File a request and reserve its amount at once.

    {"ok": True, "request", "warnings": [...]} or {"error": "..."} — an
    error writes nothing. Refused: no one named as asking, an amount that
    is not a positive number, and a reserve that would be larger than the
    latest account reading (less anything already withdrawn since it).
    Accepted with a warning: more than half the account held back, an old
    reading, no reading at all, a wanted-by date already past.
    """
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.utils import timezone

    from .capital_truth import TRACKING_FRESH_SECONDS, account_equity
    from .withdrawal_models import WithdrawalRequest

    who = _who(requested_by)
    if not who:
        return {"error": "Say who is asking: the operator or Gandalf. "
                         "Nothing was reserved."}
    amt, why = parse_amount(amount)
    if amt is None:
        return {"error": f"Refused: {why}. Nothing was reserved."}
    if wanted_by is not None and not hasattr(wanted_by, "year"):
        wanted_by, why = parse_date(wanted_by)
        if why:
            return {"error": f"Refused: {why}. Nothing was reserved."}
    reason = str(reason or "").strip()[:2000]

    warnings = []
    with transaction.atomic():
        # One request at a time per book: two forms submitted together
        # must not both pass the "not larger than the account" test on
        # the same total. (A no-op lock on SQLite, a row lock on Postgres.)
        get_user_model().objects.select_for_update().filter(
            pk=user.pk).first()
        reading = account_equity(user)
        already = reserved_total(user)
        total = already + amt
        if reading is None:
            currency = FALLBACK_CURRENCY
            warnings.append(
                "No account reading has landed yet, so the amount could not "
                "be checked against the account, and the currency is "
                f"recorded as {FALLBACK_CURRENCY} by default.")
        else:
            currency = reading["currency"] or FALLBACK_CURRENCY
            value = Decimal(str(round(float(reading["value"]), 2)))
            gone = paid_since(user, reading["at"])
            room = value - gone
            if total > room:
                less = (f", less {money(gone, currency)} already withdrawn "
                        f"since that reading" if gone else "")
                return {"error": (
                    f"Refused: {money(total, currency)} would be reserved "
                    f"in total, and the account reads "
                    f"{money(value, currency)}{less}. A reserve cannot be "
                    f"larger than the account. Nothing was reserved.")}
            if room > 0 and total > room * WARN_FRACTION:
                pct = float(total / room * 100)
                warnings.append(
                    f"{money(total, currency)} is now reserved in total — "
                    f"{pct:.0f}% of the account "
                    f"({money(room, currency)}). Every pool that follows "
                    f"the account shrinks by that proportion; nothing is "
                    f"sold.")
            if reading["age_seconds"] > TRACKING_FRESH_SECONDS:
                warnings.append(
                    f"The account reading is "
                    f"{reading['age_seconds'] / 3600:.1f}h old; the check "
                    f"above used it as it stands.")
        if wanted_by is not None and wanted_by < timezone.now().date():
            warnings.append(f"The wanted-by date {wanted_by:%Y-%m-%d} is "
                            f"already past.")
        wr = WithdrawalRequest.objects.create(
            user=user, requested_by=who, amount=amt, currency=currency,
            wanted_by=wanted_by, reason=reason)
    logger.info("[withdrawals] %s: #%s %s reserved by %s — %s in total",
                user.username, wr.pk, money(amt, currency), who,
                money(total, currency))
    _after(user, wr, "requested")
    return {"ok": True, "request": wr, "warnings": warnings}


def _locked(user, request_id):
    """The user's own request, row-locked, or None."""
    from .withdrawal_models import WithdrawalRequest
    try:
        pk = int(request_id)
    except (TypeError, ValueError):
        return None
    return (WithdrawalRequest.objects.select_for_update()
            .filter(pk=pk, user=user).first())


def cancel_request(user, request_id, *, acted_by, note="") -> dict:
    """Release a reserve. Only a reserved request can be cancelled; a paid
    one has left the account and stays in the history as it happened."""
    from django.db import transaction
    from django.utils import timezone

    from .withdrawal_models import WithdrawalRequest
    who = _who(acted_by)
    if not who:
        return {"error": "Say who is cancelling: the operator or Gandalf. "
                         "Nothing changed."}
    with transaction.atomic():
        wr = _locked(user, request_id)
        if wr is None:
            return {"error": "No such request. Nothing changed."}
        if wr.status != WithdrawalRequest.STATUS_RESERVED:
            return {"error": (f"Request #{wr.pk} is already "
                              f"{wr.get_status_display().lower()}. Nothing "
                              f"changed.")}
        wr.status = WithdrawalRequest.STATUS_CANCELLED
        wr.cancelled_at = timezone.now()
        wr.acted_by = who
        wr.closing_note = str(note or "").strip()[:2000]
        wr.save(update_fields=["status", "cancelled_at", "acted_by",
                               "closing_note", "updated_at"])
    logger.info("[withdrawals] %s: #%s cancelled by %s", user.username,
                wr.pk, who)
    _after(user, wr, "cancelled")
    return {"ok": True, "request": wr, "warnings": []}


def mark_paid(user, request_id, *, acted_by, paid_amount=None, paid_at=None,
              note="") -> dict:
    """The money has been sent at the broker: the reserve ends, the flow
    begins. `paid_amount` defaults to the amount asked for and `paid_at`
    to now; both are what the flow accounting reads, so the moment should
    be the moment the broker's balance moved."""
    from django.db import transaction
    from django.utils import timezone

    from .withdrawal_models import WithdrawalRequest
    who = _who(acted_by)
    if not who:
        return {"error": "Say who sent the withdrawal: the operator or "
                         "Gandalf. Nothing changed."}
    amt = None
    if paid_amount not in (None, ""):
        amt, why = parse_amount(paid_amount)
        if amt is None:
            return {"error": f"Refused: {why}. Nothing changed."}
    now = timezone.now()
    if paid_at in (None, ""):
        when = now
    elif hasattr(paid_at, "tzinfo"):
        when = (paid_at if paid_at.tzinfo is not None
                else paid_at.replace(tzinfo=dt_timezone.utc))
    else:
        when, why = parse_moment(paid_at)
        if why:
            return {"error": f"Refused: {why}. Nothing changed."}
        when = when or now
    if when > now + FUTURE_SLACK:
        return {"error": ("Refused: the withdrawal time is in the future. "
                          "Mark it when the money is sent. Nothing "
                          "changed.")}
    with transaction.atomic():
        wr = _locked(user, request_id)
        if wr is None:
            return {"error": "No such request. Nothing changed."}
        if wr.status != WithdrawalRequest.STATUS_RESERVED:
            return {"error": (f"Request #{wr.pk} is already "
                              f"{wr.get_status_display().lower()}. Nothing "
                              f"changed.")}
        wr.status = WithdrawalRequest.STATUS_PAID
        wr.paid_amount = amt if amt is not None else wr.amount
        wr.paid_at = when
        wr.acted_by = who
        wr.closing_note = str(note or "").strip()[:2000]
        wr.save(update_fields=["status", "paid_amount", "paid_at",
                               "acted_by", "closing_note", "updated_at"])
    logger.info("[withdrawals] %s: #%s withdrawn — %s at %s, marked by %s",
                user.username, wr.pk, money(wr.paid_amount, wr.currency),
                when.isoformat(), who)
    _after(user, wr, "paid")
    return {"ok": True, "request": wr, "warnings": []}


# ── After every act: the pools follow at once, the group hears ───────────

def _after(user, wr, event) -> None:
    refollow(user)
    try:
        from .notifications import notify_withdrawal
        notify_withdrawal(user, wr, event=event,
                          reserved_total=reserved_total(user))
    except Exception as e:  # noqa: BLE001 — a message must never undo the act
        logger.warning("[withdrawals] notification failed: %s", e)


def refollow(user) -> bool:
    """Re-size every following pool from the stored reading NOW, as
    views_admin_hq does after a share changes — rather than leaving the
    pools on the old reserve until the next sync, up to 15 minutes away.
    True when it ran. Never raises: the request is already written."""
    try:
        from .capital_truth import account_equity
        from .tasks import _follow_the_account
        reading = account_equity(user)
        if reading is None:
            return False
        _follow_the_account(user, float(reading["value"]),
                            reading["currency"])
        return True
    except Exception as e:  # noqa: BLE001 — the request stands regardless
        logger.warning("[withdrawals] pool follow after the request failed: "
                       "%s", e)
        return False
