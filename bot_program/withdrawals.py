"""Withdrawals asked for in advance — the reserve, the flows, the readiness.

The operator and Gandalf file a request ahead of time ("I will take X out
of the real account by the 5th") and the platform's whole answer is to
STOP DEPLOYING X. It does not sell anything, it does not move a share, it
does not touch a plan: the balance and the direction of the portfolio are
exactly what they were, and cash builds up as positions close on their
own. The places that size from the account read the reserve, and only
they do:

  tasks._follow_the_account     every pool that follows the account is
                                sized from the reading LESS what is held
                                back, so they all shrink by the same
                                proportion and their shares are untouched
  manual_trade.arm_manual_lane  the paths that write a follower's capital
  views_admin_hq.hq_follow      themselves — arming the lane, the Follow
  management/commands/follow    button, its shell twin — take the same
                                `deployable` base, so none of them sizes a
                                pool on reserved money, not even for the
                                moment before the follow that runs after
                                them (or for good, if that follow fails)
  AssetBot._leverage_headroom   the eToro cash gate never pledges the
                                reserved cash to a new order — it refuses
                                the order, never resizes it, never closes.
                                Only when that eToro row IS the book, and
                                only in its cash's currency: a reserve at
                                Saxo is not eToro's cash (held_back_in)

A pool with a TYPED capital is not reduced — nothing retunes a typed
number, and a reserve must not become the first thing that does. The
readiness block lists those pools with a plain warning instead. Paper
pools are never affected: they follow nothing.

WHAT IS HELD BACK is the reserve (every request still `reserved`) plus
any withdrawal already marked paid AFTER the reading being sized from:
that money has left, but the last reading still counts it, and for up to
one sync (15 minutes) the pools would otherwise grow back into it. A
withdrawal marked paid at a time BEFORE that reading, confirmed while the
readings still showed the money, is held back from it just the same
(held_through): the hold follows the readings, not the clock typed.

WHEN THE MONEY LEAVES, the request is marked paid with the amount and the
moment, and it becomes a FLOW. `flow_adjusted_value` takes every paid
withdrawal made after a reading off that reading, so the high-water mark,
the drawdown and the 24 h drop compare readings on one footing: the
money that left on purpose is not a loss, and the governor does not
de-risk the account for it. Paid withdrawals only — a reserve has not
left the account, and a reading that includes it is simply true.

The two numbers typed when marking it paid rewrite the recent history,
so they are checked against the readings first (mark_paid; the section
"Marking the money gone" says what and why): an amount larger than the
account held is refused, a blank "now" after the sync already read the
money gone is refused, and an amount or a time the readings contradict
must be confirmed. A paid row can be corrected later (correct_paid), PIN
in hand, keeping the old values in its note. A currency written only as
the fallback (no reading yet) is flagged, counted as the account's own,
and replaced by the reading's real one when the request is marked paid.

Every create, cancel, mark-paid and correction re-runs the pool follow at
once from the stored reading (the same call views_admin_hq makes after a
share changes), so the pools do not wait for the next sync, and sends one
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


def paid_flows(user, currency=None, *, exclude_pk=None) -> list:
    """[(paid_at, amount)] for every withdrawal marked paid, oldest first.

    `currency` narrows to one: the equity history is compared in the
    current reading's currency only (capital_truth), and a flow in another
    currency is a number nothing here converts. A flow whose currency was
    only ASSUMED (filed before any reading, and marked paid before one
    landed) is counted in whatever currency is asked for: the amount was
    typed as "the account's money", and leaving it out would read the
    withdrawal as a loss — the one thing this accounting exists to stop.
    `exclude_pk` leaves one request out: the one being marked or corrected,
    so the checks never measure a flow against itself.
    """
    from django.db.models import Q

    from .withdrawal_models import WithdrawalRequest
    rows = (WithdrawalRequest.objects
            .filter(user=user, status=WithdrawalRequest.STATUS_PAID,
                    paid_at__isnull=False)
            .order_by("paid_at"))
    if currency is not None:
        rows = rows.filter(Q(currency=currency) | Q(currency_assumed=True))
    if exclude_pk is not None:
        rows = rows.exclude(pk=exclude_pk)
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


def _counted_by(at):
    """The paid rows a reading taken at `at` still counts, as a filter:
    marked paid after it — or marked paid at an earlier time, confirmed
    while that reading (or a later one) still showed the money, so the
    mark wrote that reading down as `held_through`. The history reads
    `paid_at` alone; the hold reads both."""
    from django.db.models import Q
    return Q(paid_at__gt=at) | Q(held_through__gte=at)


def paid_since(user, at) -> Decimal:
    """Withdrawals a reading taken at `at` still counts and the account no
    longer holds (_counted_by): marked paid after it, or before it while
    it still showed the money."""
    from .withdrawal_models import WithdrawalRequest
    if at is None:
        return ZERO
    rows = (WithdrawalRequest.objects
            .filter(user=user, status=WithdrawalRequest.STATUS_PAID,
                    paid_at__isnull=False)
            .filter(_counted_by(at)))
    return sum((Decimal(r.flow_amount) for r in rows), ZERO)


_LOOK_UP = object()


def held_back(user, reading_at=_LOOK_UP) -> Decimal:
    """What must not be deployed out of a reading taken at `reading_at`:
    the reserve, plus every withdrawal that reading still counts — paid
    since it, or confirmed paid earlier while it still showed the money.

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


def held_back_in(user, currency, reading_at):
    """(held back in `currency`, {other currency: held}) — held_back split
    by currency, for the one reader that must never mix two: the eToro
    cash gate, which subtracts from a cash CELL in one currency.

    The pool sizing subtracts the whole hold from the reading as a number
    (held_back): a reserve in the wrong currency there only ever sizes the
    pools smaller. The cash gate is different — subtracting 500 EUR from
    1,000 USD of cash is a number nobody measured, in either direction —
    so it takes this split, subtracts only its own currency, and refuses
    the order while anything else is held. A request whose currency was
    only assumed counts as `currency`: it was typed as the account's money.
    """
    from .withdrawal_models import WithdrawalRequest
    want = str(currency or "").upper()
    split: dict = {}

    def _add(r, amount):
        key = want if r.currency_assumed else str(r.currency or "").upper()
        split[key] = split.get(key, ZERO) + Decimal(amount)

    for r in WithdrawalRequest.objects.filter(
            user=user, status=WithdrawalRequest.STATUS_RESERVED):
        _add(r, r.amount)
    if reading_at is not None:
        for r in WithdrawalRequest.objects.filter(
                user=user, status=WithdrawalRequest.STATUS_PAID,
                paid_at__isnull=False).filter(_counted_by(reading_at)):
            _add(r, r.flow_amount)
    held = split.pop(want, ZERO)
    return held, {c: v for c, v in split.items() if v > 0}


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
    # Only the withdrawals paid in the cell's own currency come off it —
    # the same split the cash gate makes; nothing here converts.
    ccy = str(getattr(book, "last_equity_currency", "") or "")
    gone = sum((amount for paid_at, amount in paid_flows(user, currency=ccy)
                if paid_at > at), ZERO)
    return Decimal(cash) - gone, at, ""


def readiness(user) -> dict:
    """Everything the page's readiness block shows, measured once.

    {value, currency, at, age_seconds, reserved, paid_unread, held,
     deployable, free_cash, cash_at, cash_note, cash_ready, cash_ready_note,
     shortfall, following, following_note, not_retuned, typed_live, paper,
     foreign_ccy, n_active, book_name}

    Numbers are Decimals, None when not measured — the page prints an em
    dash, never a zero. `cash_ready` is None when the cash cannot be read,
    or cannot be compared (a request in another currency than the cash).
    Pure DB reads: no broker call on a render path.

    `following` carries the number the sync WILL write, not a hope: a pool
    whose orders route to a broker other than the book is skipped by
    tasks._follow_the_account, so here it has no "after" number, says
    where it trades, and is listed again in `not_retuned` beside the typed
    pools — the page the two men use to judge whether the reserve is
    really applied must not show a pool shrinking that will not move
    (review, 2026-09-28). The test is capital_truth.foreign_venue, the
    sync's own.
    """
    from .capital_truth import (account_equity, allocate_shares,
                                broker_backed, broker_kind, followers_of,
                                foreign_venue, tracks_broker)
    from .models import AssetBotConfig
    from .withdrawal_models import WithdrawalRequest

    reading = account_equity(user)
    book = broker_backed(user)
    book_kind = broker_kind(book) if book is not None else ""
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

    active = list(WithdrawalRequest.objects.filter(
        user=user, status=WithdrawalRequest.STATUS_RESERVED))
    # Requests in a REAL currency other than the reading's: the sizing
    # takes them off as a number, the cash gate refuses every order while
    # they are held, and they cannot be marked withdrawn — all three said
    # on the page, with the way out.
    foreign_ccy = []
    if reading is not None:
        for wr in active:
            if not wr.currency_assumed and wr.currency != currency:
                foreign_ccy.append({"id": wr.pk,
                                    "amount_text": money(wr.amount,
                                                         wr.currency),
                                    "currency": wr.currency})

    free_cash, cash_at, cash_note = _free_cash(user, book)
    cash_ready = shortfall = None
    cash_ready_note = ""
    if free_cash is not None:
        if foreign_ccy:
            cash_ready_note = (f"a request is in another currency than the "
                               f"account's {currency or '?'}")
        else:
            cash_ready = free_cash >= reserved
            shortfall = (reserved - free_cash) if not cash_ready else ZERO

    following, following_note, not_retuned = [], "", []
    followers = followers_of(user)
    if followers:
        alloc = allocate_shares(followers)
        if not alloc["ok"]:
            following_note = (f"The shares do not fit in the account "
                              f"({alloc['reason']}), so no pool follows it "
                              f"until they do.")
        venue_of: dict = {}
        for cfg in followers:
            share = alloc["plan"].get(cfg.pk) if alloc["ok"] else None
            foreign = foreign_venue(user, cfg, book_kind, venue_of)
            row = {"name": cfg.name, "asset_class": cfg.asset_class,
                   "share_pct": (share * 100.0 if share is not None
                                 else None),
                   "now": Decimal(cfg.capital or 0),
                   "before": None, "after": None, "foreign": foreign}
            if share is not None and value is not None:
                row["before"] = Decimal(str(round(float(value) * share, 2)))
                if not foreign:
                    row["after"] = Decimal(str(round(float(base) * share,
                                                     2)))
            following.append(row)
            if foreign:
                not_retuned.append(row)

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
                       "ibkr": "IBKR"}.get(book_kind, "broker")
                      if book is not None else ""),
        "reserved": reserved, "paid_unread": paid_unread, "held": held,
        "deployable": base,
        "free_cash": free_cash, "cash_at": cash_at, "cash_note": cash_note,
        "cash_ready": cash_ready, "cash_ready_note": cash_ready_note,
        "shortfall": shortfall,
        "following": following, "following_note": following_note,
        "not_retuned": not_retuned,
        "typed_live": typed_live, "paper": paper,
        "foreign_ccy": foreign_ccy,
        "n_active": len(active),
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


# ── The acts ─────────────────────────────────────────────────────────────

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
        assumed = reading is None or not reading["currency"]
        if reading is None:
            currency = FALLBACK_CURRENCY
            warnings.append(
                "No account reading has landed yet, so the amount could not "
                "be checked against the account, and the currency is "
                f"recorded as {FALLBACK_CURRENCY} by default. Marking it "
                "withdrawn records the account's own currency once a "
                "reading has landed.")
        else:
            currency = reading["currency"] or FALLBACK_CURRENCY
            if assumed:
                warnings.append(
                    "The account reading states no currency, so the request "
                    f"is recorded in {FALLBACK_CURRENCY} by default; marking "
                    "it withdrawn records the account's own currency.")
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
            currency_assumed=assumed, wanted_by=wanted_by, reason=reason)
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


# ── Marking the money gone: the checks a flow must pass ──────────────────
#
# A paid withdrawal is taken off every reading made before it, so the two
# numbers typed on "Mark withdrawn" — how much, and when — rewrite the
# account's whole recent history for the drawdown governor and the shock
# detector. The review of 2026-09-28 found both could be typed wrong with
# nothing to stop it:
#
#   * AN AMOUNT TOO LARGE — "2000" for a 200 request on a 1,000 account —
#     lowers every earlier reading by 2,000, and a real 37.5% loss after it
#     read as no drawdown at all for 90 days: the opposite of the rule this
#     accounting keeps (err toward de-risking, never toward trusting money
#     that may be gone). So an amount larger than the account held when it
#     left is refused outright, and one that differs from the amount asked
#     for by more than PAID_TOLERANCE must be confirmed on the form.
#
#   * A MOMENT TOO LATE — the blank "now", pressed a few minutes after the
#     sync already read the lower balance — takes the amount off a reading
#     that no longer holds it: a false fall of the whole amount (a 25%
#     drawdown and a shock, for a 20% withdrawal) until the next sync, and
#     the pools held back twice. So when the readings already show the
#     fall, the blank default is refused and the form asks for the time.
#
#   * A MOMENT TOO EARLY — before the broker's balance moved — leaves the
#     readings in between holding money the flow says had gone: a false
#     fall that stays in the 90-day window. Confirmed on the form, or not
#     at all. The second pass of that review found the tick was asked
#     only once the readings showed a fall: a time before the latest
#     reading, while every reading still held the money, went through
#     silently — and released the reserve at once, because the hold
#     (paid_since) kept only a withdrawal paid AFTER the reading being
#     sized from, and this one said it was paid before it. So that case
#     asks the tick too, and the mark writes down the reading it was
#     checked against (held_through): the flow is held back from that
#     reading and every earlier one, exactly as a blank "now" would have
#     been, until the next reading — the history reads the time typed,
#     the hold reads the readings. A fall the market noise hid (the
#     readings did fall by at least the amount, only not by "about" it)
#     is a fall: no tick, and no second hold from a reading that already
#     lacks the money.
#
# The readings are the sync's own history (BrokerEquityReading) in the
# current reading's currency and world — the rows the governor reads. When
# nothing can be checked (no reading, no history) the act goes through as
# typed, as it did before; and a paid row can now be CORRECTED, PIN in
# hand, so a wrong number is no longer fixed only in the database.

#: Two readings a sync apart move with the market as well as with a
#: withdrawal. A fall within this share of the account of the amount "is
#: the amount"; and a withdrawal no bigger than it cannot be told from the
#: market at all — nor, counted twice for one sync, raise a shock on its
#: own (share_allocator.SHOCK_DROP_PCT is 3%).
NOISE_FRACTION = Decimal("0.02")
#: A paid amount this close to the amount asked for — a broker's fee, a
#: rounding — is taken as typed; further off, it must be confirmed. A
#: slipped digit is ten times off, never five percent.
PAID_TOLERANCE = Decimal("0.05")
#: The fall a request's money made is looked for from this long before it
#: was filed: the money may have been sent the same day, then filed.
LEFT_LOOKBACK = timedelta(days=1)
#: The reading a paid amount is checked against must be this recent
#: before the moment given; an older one says nothing about that day.
BOUND_MAX_AGE = timedelta(days=1)

CONFIRM_WORDS = "tick “I have checked” and send again"


def _moment(paid_at, now):
    """(when, blank, why) from what the form sent: blank means now."""
    if paid_at in (None, ""):
        return now, True, ""
    if hasattr(paid_at, "tzinfo"):
        return ((paid_at if paid_at.tzinfo is not None
                 else paid_at.replace(tzinfo=dt_timezone.utc)), False, "")
    when, why = parse_moment(paid_at)
    if why:
        return None, False, why
    if when is None:
        return now, True, ""
    return when, False, ""


def _utc(at):
    return at.astimezone(dt_timezone.utc) if at.tzinfo is not None else at


def _hm(at) -> str:
    """'2026-09-28 10:15 UTC' — the form's datetime-local is read as UTC,
    so every moment a refusal names is in the same clock. An em dash for
    a moment never recorded."""
    if at is None:
        return EM_DASH
    return f"{_utc(at):%Y-%m-%d %H:%M} UTC"


def _book_history(user, reading, *, since, until) -> list:
    """[(at, Decimal value)] oldest first: the book's own readings in the
    stored reading's currency and world, from `since` to `until` — the
    rows equity_high_water reads — with the stored reading itself added
    when its history row is missing (a failed insert must not hide it)."""
    from django.db.models import Q

    from .capital_truth import broker_backed, broker_env, broker_kind
    from .equity_models import BrokerEquityReading
    book = broker_backed(user)
    if book is None:
        return []
    rows = BrokerEquityReading.objects.filter(
        broker=broker_kind(book), account_pk=book.pk,
        currency=reading["currency"] or "", at__gte=since, at__lte=until)
    env = broker_env(book)
    if env:
        rows = rows.filter(Q(env="") | Q(env=env))
    out = [(at, Decimal(v)) for at, v in
           rows.order_by("at").values_list("at", "value")]
    r_at = reading["at"]
    if since <= r_at <= until and all(at != r_at for at, _v in out):
        out.append((r_at, Decimal(str(round(float(reading["value"]), 2)))))
        out.sort(key=lambda p: p[0])
    return out


def _gone(flows, after, upto) -> Decimal:
    """Withdrawals paid in (after, upto]."""
    return sum((amount for paid_at, amount in flows
                if after < paid_at <= upto), ZERO)


def _value_before(user, reading, when, flows):
    """(what the account held just before `when`, the reading's time) —
    the latest reading at or before it, less what was paid between — or
    (None, None) when no reading that recent exists."""
    if when >= reading["at"]:
        at = reading["at"]
        value = Decimal(str(round(float(reading["value"]), 2)))
    else:
        points = _book_history(user, reading, since=when - BOUND_MAX_AGE,
                               until=when)
        if not points:
            return None, None
        at, value = points[-1]
    return value - _gone(flows, at, when), at


def _where_it_left(user, reading, amount, *, since, flows):
    """The latest pair of consecutive readings between which the account
    fell by about `amount` — {a_at, a, b_at, b} — or None.

    "About" is within NOISE_FRACTION of the account; other withdrawals
    paid between the two are taken off the first before comparing. A
    withdrawal no bigger than the noise is never matched: it cannot be
    told from the market."""
    points = _book_history(user, reading, since=since, until=reading["at"])
    for (a_at, a_v), (b_at, b_v) in reversed(list(zip(points,
                                                      points[1:]))):
        a_cmp = a_v - _gone(flows, a_at, b_at)
        tol = abs(a_cmp) * NOISE_FRACTION
        if amount <= tol:
            continue
        if abs((a_cmp - b_v) - amount) <= tol:
            return {"a_at": a_at, "a": a_cmp, "b_at": b_at, "b": b_v}
    return None


def _judge_the_flow(user, wr, amount, when, *, blank, confirm, act):
    """(refusal, currency to stamp, warnings, held through) for a flow of
    `amount` at `when` on request `wr` — refusal "" when it may be
    written. `held through` is the latest reading when it is after `when`
    and still shows the money: the hold keeps the flow back from it
    (held_through); None when the time typed agrees with the readings, or
    nothing could be checked.

    `act` is "mark" or "correct": the words differ, the rules do not."""
    from .capital_truth import account_equity
    reading = account_equity(user)
    if reading is None:
        return "", None, ["No account reading has landed, so the amount "
                          "and the time could not be checked against the "
                          "account."], None
    rc = reading["currency"] or ""
    stamp = None
    if wr.currency_assumed:
        stamp = rc or None
    elif wr.currency != rc:
        if act == "mark":
            in_rc = rc or "the account's currency"
            way_out = (f"Cancel it and file it again in {in_rc}, then mark "
                       f"that one withdrawn.")
        else:
            way_out = "It cannot be checked against the account."
        return (f"Refused: request #{wr.pk} is in {wr.currency} and the "
                f"account now reads in {rc or 'no stated currency'}. "
                f"Nothing here converts, so the account's history would "
                f"read this withdrawal as a loss. {way_out} Nothing "
                f"changed."), None, [], None
    ccy = rc or wr.currency
    exclude = wr.pk if act == "correct" else None
    flows = paid_flows(user, currency=rc, exclude_pk=exclude)

    # WHERE THE MONEY LEFT, first: a blank "now" after the readings
    # already show it gone is refused with the interval it left in, before
    # the amount is weighed against a reading that no longer holds it —
    # otherwise a 900 withdrawal from 1,000, marked after the sync read
    # 100, would be told "900 cannot have left an account that held 100".
    left = _where_it_left(user, reading, amount, flows=flows,
                          since=min(wr.created_at, when) - LEFT_LOOKBACK)
    span = fell = ""
    if left is not None:
        fell = (f"the account fell from {money(left['a'], ccy)} "
                f"({_hm(left['a_at'])}) to {money(left['b'], ccy)} "
                f"({_hm(left['b_at'])})")
        span = (f"after {_hm(left['a_at'])} and no later than "
                f"{_hm(left['b_at'])}")
        # The first reading without the money, to the minute the form
        # takes: after the last reading with it, and not after this one.
        safe = _utc(left["b_at"]).replace(second=0, microsecond=0)
        if when > reading["at"] and blank:
            return (f"Refused: the readings say the money has already "
                    f"left — {fell}, about {money(amount, ccy)}. Give the "
                    f"time it left, {span} ({safe:%Y-%m-%d %H:%M} is "
                    f"safe). Left blank, it would be counted twice until "
                    f"the next sync: a false fall of the whole amount, and "
                    f"the pools held back twice. Nothing changed."), None, [], None

    held, held_at = _value_before(user, reading, when, flows)
    if held is not None and amount > held:
        hint = ""
        if left is not None and when > left["b_at"]:
            hint = (f" If it left before that reading, give the time it "
                    f"left: {span}.")
        return (f"Refused: {money(amount, ccy)} cannot have left an "
                f"account that held {money(held, ccy)} when it left (the "
                f"reading of {_hm(held_at)}, less anything withdrawn "
                f"after it). A withdrawal marked larger than the money "
                f"that left would hide every real loss before it — check "
                f"the amount.{hint} Nothing changed."), None, [], None

    checks = []
    through = None
    if left is not None:
        if when > reading["at"]:
            checks.append(
                f"the time given, {_hm(when)}, is after the latest "
                f"reading ({_hm(reading['at'])}), which already reads the "
                f"money gone — {fell} — so it would be counted twice "
                f"until the next sync; the time it left is {span}.")
        elif when <= left["a_at"]:
            checks.append(
                f"the time given, {_hm(when)}, is before the reading of "
                f"{_hm(left['a_at'])}, which still holds the money — "
                f"{fell} — so the readings in between would read as a "
                f"loss for 90 days; the time it left is {span}.")
    elif when < reading["at"] and held is not None:
        # A MOMENT TOO EARLY with no fall in sight: what the account held
        # just before `when`, less anything else withdrawn since, against
        # the latest reading. Short of the amount by more than the noise,
        # the money is still there by the readings — and a withdrawal no
        # bigger than the noise cannot be told from the market at all.
        latest = Decimal(str(round(float(reading["value"]), 2)))
        fall = held - _gone(flows, when, reading["at"]) - latest
        tol = abs(held) * NOISE_FRACTION
        if amount > tol and fall < amount - tol:
            through = reading["at"]
            checks.append(
                f"the time given, {_hm(when)}, is before the latest "
                f"reading ({_hm(reading['at'])}), which still holds the "
                f"money — nothing has left the account yet by the "
                f"readings — so the readings in between would read as a "
                f"loss for 90 days; leave the time blank to mark it now.")
    asked = Decimal(wr.amount)
    if abs(amount - asked) > asked * PAID_TOLERANCE:
        checks.append(
            f"{money(amount, ccy)} withdrawn is not the "
            f"{money(asked, ccy)} asked for (more than "
            f"{PAID_TOLERANCE * 100:.0f}% apart).")
    if checks and not confirm:
        return ("Refused until checked: " + " Also, ".join(checks)
                + f" If it is right as typed, {CONFIRM_WORDS}. Nothing "
                f"changed."), None, [], None
    return "", stamp, [], through


def mark_paid(user, request_id, *, acted_by, paid_amount=None, paid_at=None,
              note="", confirm=False) -> dict:
    """The money has been sent at the broker: the reserve ends, the flow
    begins. `paid_amount` defaults to the amount asked for and `paid_at`
    to now; both are what the flow accounting reads, so the moment should
    be the moment the broker's balance moved.

    Checked against the readings before anything is written (see above):
    an amount larger than the account held is refused; a blank time when
    the readings already show the money gone is refused with the interval
    it left in; an amount far from the one asked for, or a time the
    readings contradict, needs `confirm` — a time before the latest
    reading while it still shows the money too, and the flow is then held
    back from that reading (held_through) as a blank "now" would be. A
    request whose currency was assumed takes the reading's own; one in a
    real other currency is refused — its flow would never be counted, and
    would read as a loss.
    """
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
    when, blank, why = _moment(paid_at, now)
    if why:
        return {"error": f"Refused: {why}. Nothing changed."}
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
        paid = amt if amt is not None else Decimal(wr.amount)
        refusal, stamp, warnings, through = _judge_the_flow(
            user, wr, paid, when, blank=blank, confirm=bool(confirm),
            act="mark")
        if refusal:
            return {"error": refusal}
        fields = ["status", "paid_amount", "paid_at", "held_through",
                  "acted_by", "closing_note", "updated_at"]
        if stamp:
            wr.currency, wr.currency_assumed = stamp, False
            fields += ["currency", "currency_assumed"]
        wr.status = WithdrawalRequest.STATUS_PAID
        wr.paid_amount = paid
        wr.paid_at = when
        wr.held_through = through
        wr.acted_by = who
        wr.closing_note = str(note or "").strip()[:2000]
        wr.save(update_fields=fields)
    logger.info("[withdrawals] %s: #%s withdrawn — %s at %s, marked by %s",
                user.username, wr.pk, money(wr.paid_amount, wr.currency),
                when.isoformat(), who)
    _after(user, wr, "paid")
    return {"ok": True, "request": wr, "warnings": warnings}


def correct_paid(user, request_id, *, acted_by, paid_amount=None,
                 paid_at=None, note="", confirm=False) -> dict:
    """Put right the amount or the moment of a withdrawal already marked
    paid — the two numbers the history is read net of.

    Before 2026-09-28 a wrong value could only be fixed in the database;
    and since a moment too early leaves a false fall in the 90-day window,
    and the broker's balance may move later than the button was pressed,
    the fix has to be a page act. Blank fields keep what is there. The same
    checks as mark_paid, measured without this flow itself; the old values
    are kept in the closing note, so the history of the row is its own.
    Only a paid request can be corrected — a reserve is cancelled and
    filed again instead.
    """
    from django.db import transaction
    from django.utils import timezone

    from .withdrawal_models import WithdrawalRequest
    who = _who(acted_by)
    if not who:
        return {"error": "Say who is correcting it: the operator or "
                         "Gandalf. Nothing changed."}
    amt = None
    if paid_amount not in (None, ""):
        amt, why = parse_amount(paid_amount)
        if amt is None:
            return {"error": f"Refused: {why}. Nothing changed."}
    now = timezone.now()
    when = None
    if paid_at not in (None, ""):
        when, _blank, why = _moment(paid_at, now)
        if why:
            return {"error": f"Refused: {why}. Nothing changed."}
        if when > now + FUTURE_SLACK:
            return {"error": ("Refused: the withdrawal time is in the "
                              "future. Nothing changed.")}
    with transaction.atomic():
        wr = _locked(user, request_id)
        if wr is None:
            return {"error": "No such request. Nothing changed."}
        if wr.status != WithdrawalRequest.STATUS_PAID:
            return {"error": (f"Request #{wr.pk} is "
                              f"{wr.get_status_display().lower()}, not "
                              f"withdrawn: only a withdrawal can be "
                              f"corrected. Nothing changed.")}
        old_amt, old_at = Decimal(wr.flow_amount), wr.paid_at
        # The form's time box holds the stored moment to the minute: sent
        # back untouched, it is the same moment, not a correction.
        if (when is not None and old_at is not None
                and _utc(old_at).replace(second=0, microsecond=0)
                == _utc(when)):
            when = None
        new_amt = amt if amt is not None else old_amt
        new_at = when if when is not None else old_at
        if new_at is None:
            return {"error": (f"Request #{wr.pk} has no withdrawal time on "
                              f"record: give the time the money left. "
                              f"Nothing changed.")}
        if new_amt == old_amt and new_at == old_at:
            return {"error": (f"Nothing to correct: request #{wr.pk} "
                              f"already reads {money(old_amt, wr.currency)} "
                              f"at {_hm(old_at)}. Nothing changed.")}
        refusal, stamp, warnings, through = _judge_the_flow(
            user, wr, new_amt, new_at, blank=False, confirm=bool(confirm),
            act="correct")
        if refusal:
            return {"error": refusal}
        fields = ["paid_amount", "paid_at", "held_through", "acted_by",
                  "closing_note", "updated_at"]
        if stamp:
            wr.currency, wr.currency_assumed = stamp, False
            fields += ["currency", "currency_assumed"]
        line = (f"Corrected {_hm(now)} by {who_label(who)}: was "
                f"{money(old_amt, wr.currency)} at {_hm(old_at)}, now "
                f"{money(new_amt, wr.currency)} at {_hm(new_at)}.")
        extra = str(note or "").strip()[:2000]
        if extra:
            line += f" {extra}"
        wr.closing_note = "\n".join(p for p in (wr.closing_note, line) if p)
        wr.paid_amount = new_amt
        wr.paid_at = new_at
        wr.held_through = through
        wr.acted_by = who
        wr.save(update_fields=fields)
    logger.info("[withdrawals] %s: #%s corrected by %s — %s at %s (was %s "
                "at %s)", user.username, wr.pk, who,
                money(new_amt, wr.currency), new_at.isoformat(),
                money(old_amt, wr.currency), _hm(old_at))
    _after(user, wr, "corrected", was=(old_amt, old_at))
    return {"ok": True, "request": wr, "warnings": warnings}


# ── After every act: the pools follow at once, the group hears ───────────

def _after(user, wr, event, **extra) -> None:
    refollow(user)
    try:
        from .notifications import notify_withdrawal
        notify_withdrawal(user, wr, event=event,
                          reserved_total=reserved_total(user), **extra)
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
