"""THE DOSSIER (spec §5.2a), assembled and stored, from code alone.

    S        the doctrine (O2; reserved in the size cap: S_TOKENS_RESERVE)
    MK       the market day: MK0 at the roll, one block per CLOSED session,
             MK-E (bot_program/orcs/dossier_market.py). Built by the beats,
             NEVER in the tick: a block the tick finds missing is listed in
             the tail ("— (session block london not built yet)")
    IN-slow  the instrument's frames and levels, per (symbol, 1h bar, model)
             (dossier_instrument.py), built on a miss
    PS       the position, per wake (dossier_position.py)
    tail     MK-now, IN-today, PS12, PS13 and this wake's reasons

Every block is one header line then its body as JSON with sorted keys, and
is content-addressed in OrcDossierBlock (hash = sha256 of kind, key and
text), so a wake stores the hash list and a replay is `text_of(hashes)`.
MK and IN-slow are shared, to the byte, by every Orc on a model (and a
symbol): the per-wake trim (`trim`) touches only the uncached parts, in
TRIM_ORDER. Money never appears; R and ATR units only.

Token counts are ESTIMATED (O1 has no network, and `count_tokens` is an
API call): 4 characters a prose token and 8.5 tokens a bar row, times the
model's factor (constants.TOKEN_FACTORS, MEASURED 2026-10-16: x1.00 on
Sonnet, Opus and Haiku 5.5; Fable 5.1 keeps the 1.35 guard).
"""
import hashlib
import json
import logging
import math
from datetime import timedelta

from bot_program.orcs.constants import (CHARS_PER_TOKEN,
                                        DOSSIER_MAX_TOKENS,
                                        DOSSIER_REFERENCE_MODEL,
                                        MK_GUARD_FAMILY, S_TOKENS_RESERVE,
                                        TOKEN_FACTORS, TOKENS_PER_BAR_ROW,
                                        TRIM_ORDER)

logger = logging.getLogger(__name__)

SEPARATOR = "\n\n"


# ── the store ────────────────────────────────────────────────────────────

def dumps(body) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def text_for(header, body) -> str:
    return f"[{header}]\n{dumps(body)}"


def hash_of(kind, key, text) -> str:
    return hashlib.sha256(f"{kind}|{key}|{text}".encode("utf-8")).hexdigest()


#: OrcSetting "token_factors", read at most once a minute per process.
_FACTORS = {"at": None, "value": {}}
FACTORS_TTL_S = 60


def family_of(model) -> str:
    """The model's family, the word after "claude-" in its id ("fable" for
    a Fable id; a family passes through). An empty name is the reference
    family; a name of no known family is the guard (the largest factor),
    so an unknown tokenizer is never sized small."""
    s = str(model or "").strip().lower()
    if not s:
        return DOSSIER_REFERENCE_MODEL
    for part in s.split("-"):
        if part in TOKEN_FACTORS:
            return part
    return MK_GUARD_FAMILY


def token_factor(model) -> float:
    import time
    now = time.monotonic()
    if _FACTORS["at"] is None or now - _FACTORS["at"] > FACTORS_TTL_S:
        over = {}
        try:
            from bot_program.orcs.models import OrcSetting
            over = OrcSetting.get("token_factors") or {}
        except Exception:  # noqa: BLE001
            over = {}
        _FACTORS["at"], _FACTORS["value"] = now, (
            over if isinstance(over, dict) else {})
    over = _FACTORS["value"]
    family = family_of(model)
    for key in (str(model or ""), family):
        try:
            if key in over:
                return float(over[key])
        except (TypeError, ValueError):
            continue
    return float(TOKEN_FACTORS.get(family, TOKEN_FACTORS[MK_GUARD_FAMILY]))


def estimate_tokens(text, bar_rows=0, model=DOSSIER_REFERENCE_MODEL) -> int:
    """(prose characters / 4 + 8.5 per bar row) x the model's factor."""
    rows = max(0, int(bar_rows or 0))
    prose = len(str(text or ""))
    raw = prose / CHARS_PER_TOKEN + rows * TOKENS_PER_BAR_ROW
    return int(math.ceil(raw * token_factor(model) - 1e-9))


def block(kind, key, text, body=None, model="", *, bar_rows=0, at=None):
    """Store a block once (content-addressed) and return its hash."""
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from bot_program.orcs.models import OrcDossierBlock
    h = hash_of(kind, key, text)
    meta = dict(body or {})
    meta.setdefault("key", key)
    meta["bar_rows"] = int(bar_rows or 0)
    try:
        with transaction.atomic():
            OrcDossierBlock.objects.get_or_create(
                hash=h, defaults={"kind": str(kind)[:16], "key": str(key)[:160],
                                  "body": meta, "text": text,
                                  "model": str(model or "")[:50],
                                  "tokens_est": estimate_tokens(
                                      text, bar_rows, model or
                                      DOSSIER_REFERENCE_MODEL),
                                  "built_at": at or timezone.now()})
    except IntegrityError:
        pass                          # a twin built it in the same instant
    return h


def find(kind, key):
    from bot_program.orcs.models import OrcDossierBlock
    return (OrcDossierBlock.objects.filter(kind=kind, key=key)
            .order_by("built_at", "id").first())


def text_of(hashes) -> str:
    """The dossier as it was sent: each block's text, in order."""
    from bot_program.orcs.models import OrcDossierBlock
    rows = {b.hash: b.text for b in OrcDossierBlock.objects.filter(
        hash__in=list(hashes or ()))}
    return SEPARATOR.join(rows.get(h, f"[missing block {h[:12]}]")
                          for h in hashes or ())


# ── the per-wake trim ────────────────────────────────────────────────────

def _tokens_of(items, model) -> int:
    chars = 0
    for x in items or ():
        chars += len(x) if isinstance(x, str) else len(dumps(x))
    return estimate_tokens("x" * chars, 0, model) if chars else 0


def trim(parts, model, *, budget=None) -> tuple:
    """(parts, trimmed): the uncached parts emptied in TRIM_ORDER until the
    whole fits `budget` (DOSSIER_MAX_TOKENS less S by default). A part not
    in TRIM_ORDER (MK, IN-slow, PS, the tail's head) is never touched."""
    budget = (DOSSIER_MAX_TOKENS - S_TOKENS_RESERVE) if budget is None \
        else int(budget)
    total = sum(_tokens_of(v, model) for v in parts.values())
    trimmed = []
    for name in TRIM_ORDER:
        if total <= budget:
            break
        if parts.get(name):
            total -= _tokens_of(parts[name], model)
            parts[name] = []
            trimmed.append(name)
    return parts, trimmed


# ── the context a wake renders from ──────────────────────────────────────

def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def decision_tf(orc) -> str:
    """W2's and PS13's decision timeframe: a Mercenary's 1h; else the
    timeframe the birth wrote into the thesis's structure predicate (the
    decision timeframe then: 1d only once 60 fresh 1d venue bars existed),
    4h by default."""
    if str(getattr(orc, "army_type", "") or "") == "mercenaries":
        return "1h"
    for p in (getattr(orc, "thesis", None) or {}).get("invalidation") or []:
        if isinstance(p, dict) and p.get("kind") == "displaced_bos_against":
            return str(p.get("tf") or "4h")
    return "4h"


def _mark(row, price, now):
    """(source, age_s, m, quote): the mark the decision rests on. A real
    row: the venue's stamp (venue_mark.resolve); a paper row: its venue's
    quote. One LiveQuote read."""
    from bot_program import venue_mark
    q = None
    try:
        from market_data.models import LiveQuote
        q = LiveQuote.objects.filter(instrument__symbol=row.symbol).first()
    except Exception:  # noqa: BLE001
        q = None
    try:
        mk = venue_mark.resolve(row, q, now=now)
    except Exception:  # noqa: BLE001
        mk = None
    if mk is None or mk.price is None:
        return "none", None, _f(price), q
    return str(mk.source or "none"), mk.age_s, _f(mk.price), q


def context_for(orc, row, *, price, now, cache=None, reasons=None,
                bot=None) -> dict:
    """Everything the dossier and the score read, once per recorded wake.
    Never raises: a part that cannot be read is said."""
    from bot_program.orcs import bars, integrity, menu, playbook, sources
    from bot_program.orcs.facts import initial_stop
    cache = cache if isinstance(cache, dict) else {}
    meta = row.metadata if isinstance(getattr(row, "metadata", None),
                                      dict) else None
    care = (meta or {}).get("care") if isinstance((meta or {}).get("care"),
                                                  dict) else {}
    p = _f(price)
    entry = _f(getattr(row, "entry_price", None))
    stop0 = initial_stop(row) if meta is not None else None
    rpu = abs(entry - stop0) if entry and stop0 else None
    row_ok = (meta is not None and bool(entry) and str(row.side).upper()
              in ("BUY", "SELL"))
    real = not bool(getattr(row, "paper", True))
    source, age, m, q = _mark(row, p, now)
    if m is None:
        m = p
    tf = decision_tf(orc)
    frame = bars.frame(row.symbol, tf, asset_class=row.asset_class, now=now,
                       cache=cache)
    f1h = bars.frame(row.symbol, "1h", asset_class=row.asset_class, now=now,
                     cache=cache)
    atr1h = f1h.atr if f1h is not None else None
    frame_fresh = bool(frame is not None and frame.venue and frame.fresh)
    key = ("orcs:menu", row.symbol)
    mn = cache.get(key)
    if mn is None:
        mn = menu.symbol_levels(row.symbol, row.asset_class, now=now, mark=m,
                                cache=cache)
        cache[key] = mn
    rows = menu.for_idea(mn, side=row.side, entry=entry, risk_per_unit=rpu,
                         mark=m, care_state=care)
    sign = 1 if str(row.side).upper() == "BUY" else -1
    # the effective stop: the tightest of the row's own stop (the engine's
    # or the venue's), the care's soft stop and the stop the venue holds;
    # a row the care has not touched yet still has its own
    eff = None
    for lv in (_f(getattr(row, "stop_loss", None)), _f(care.get("soft_stop")),
               _f(care.get("venue_stop"))):
        if lv is not None and (eff is None or sign * (lv - eff) > 0):
            eff = lv
    th = (meta or {}).get("thesis") if isinstance((meta or {}).get("thesis"),
                                                  dict) else None
    preds = getattr(orc, "_orc_results", None)
    if preds is None:
        preds = [{"state": v.get("state"), "kind": k.split(":")[0]}
                 for k, v in ((orc.seen or {}).get("predicates") or {})
                 .items() if isinstance(v, dict)]
    blind, since = sources.analyst_blind(now)
    posture = sources.posture(now)
    cal = sources.calendar(now - timedelta(hours=1), now + timedelta(hours=72))
    nxt = None
    if not cal.get("dash"):
        ccys = _currencies(row)
        for ev in cal["value"]:
            if ev["ccy"] in ccys and ev["at"] >= now - timedelta(minutes=15):
                nxt = ev
                break
    print_ = ({"title": nxt["title"], "minutes": (nxt["at"] - now)
               .total_seconds() / 60.0} if nxt else None)
    pctx = {"side": row.side, "mfe_r": _f(care.get("mfe_r")), "p": p,
            "m": m, "effective": eff, "atr": dict(mn.atr or {}),
            "paper": not real, "legs": 1, "thesis": th,
            "predicates": preds, "now": now, "print": print_,
            "waiver": None}
    try:
        cands = playbook.candidates(rows, pctx)
    except Exception as e:  # noqa: BLE001
        logger.info("[orcs] Orc %s: candidates unread: %s", orc.pk, e)
        cands = []
    stale, missing, contra = [], [], []
    if posture.get("dash"):
        stale.append(posture["dash"])
    if blind:
        stale.append(f"— (tags blind since "
                     f"{since}{' UTC' if since[:2].isdigit() else ''})")
    if cal.get("dash"):
        stale.append(cal["dash"])
    if q is not None and source == "venue" and atr1h:
        qv = _f(getattr(q, "last", None))
        if qv is not None and m is not None and abs(qv - m) > \
                _contradiction_atr() * atr1h:
            contra.append(f"the venue mark and the platform quote differ by "
                          f"{abs(qv - m) / atr1h:.1f} x ATR(1h)")
    mind = sources.mind(now)
    if not mind.get("dash") and not posture.get("dash") and \
            (posture["value"] or {}).get("level") == "crisis" and \
            (mind["value"] or {}).get("regime") == "risk_on":
        contra.append("the Mind reads risk_on during a crisis posture")
    verdict = integrity.verdict(
        mark_source=source, mark_age_s=age, real=real, decision_tf=tf,
        frame_fresh=frame_fresh,
        frame_end=frame.newest_end if frame is not None else None,
        row_ok=row_ok, contradictions=contra, stale=stale, missing=missing)
    f5 = verdict["critical"] or False
    mark_fresh = not any("mark" in c for c in verdict["critical"])
    allowed, why_not = integrity.allowed_actions_l0(f5=f5,
                                                    mark_fresh=mark_fresh)
    return {"now": now, "price": p, "m": m, "mark_source": source,
            "mark_age_s": age, "real": real, "rpu": rpu, "entry": entry,
            "care": care, "effective": eff, "tf": tf, "frame": frame,
            "atr1h": atr1h, "menu": mn, "rows": rows,
            "candidates": integrity.shrink(cands, f5, mark_fresh=mark_fresh),
            "all_candidates": cands, "integrity": verdict, "f5": f5,
            "allowed": allowed, "why_not": why_not, "posture": posture,
            "blind": (blind, since), "calendar": cal, "next_event": nxt,
            "thesis_check": th, "predicates": preds, "cache": cache,
            "reasons": list(reasons or []), "bot": bot, "mind": mind}


def _contradiction_atr() -> float:
    from bot_program.orcs.constants import MARK_QUOTE_CONTRADICTION_ATR1H
    return MARK_QUOTE_CONTRADICTION_ATR1H


def _currencies(row) -> list:
    from bot_program.orcs.situation import currencies
    return currencies(row)


# ── the render ───────────────────────────────────────────────────────────

def render(orc, row, ctx, *, as_of, model=DOSSIER_REFERENCE_MODEL) -> dict:
    """The wake's dossier, stored block by block: {hashes, shared (how many
    leading hashes are the shared MK and IN-slow prefix), ps, tail, tokens,
    trimmed, over_budget, withheld, integrity}. MK is found, never built;
    IN-slow is built on a miss; PS and the tail are written per wake."""
    from bot_program.orcs import (dossier_instrument, dossier_market,
                                  dossier_position, fence)
    from bot_program.orcs.sessions import trading_day
    model = family_of(model)
    td = trading_day(as_of)
    mk_hashes, missing = dossier_market.day_hashes(td, model, as_of)
    in_hash = dossier_instrument.in_slow(row.symbol, row.asset_class, model,
                                         now=as_of, cache=ctx.get("cache"))
    shared = mk_hashes + [in_hash]
    held = dossier_position.held_symbols(orc)
    ctx["held"] = held
    ps_sections = dossier_position.ps(orc, row, ctx)
    mk_now_text, mk_now = dossier_market.mk_now(orc.user, held, as_of,
                                                real=ctx.get("real"),
                                                cache=ctx.get("cache"))
    today = dossier_instrument.in_today(row, as_of, ctx)
    po3 = ctx.get("po3")
    verdict = ctx.get("integrity") or {}
    if isinstance(po3, dict) and po3.get("timeframe") == "4h":
        # PS13's third contradiction (§5.2a): the day's parts read on the
        # 4h fallback; never critical, never an abstention
        verdict.setdefault("contradictions", []).append(
            "PO3 read on a 4h fallback")
        if verdict.get("flag") in ("ok", "stale"):
            verdict["flag"] = "contradiction"
    parts = {"ps": [dumps(ps_sections)], "ps5_notes": [],
             "mk_now": [mk_now_text],
             "in12_5m": today.pop("in12_5m", []),
             "in12_15m_old": today.pop("in12_15m_old", []),
             "in9": today.pop("in9", []), "today": [dumps(today)]}
    from bot_program.orcs.models import OrcDossierBlock
    fixed = sum(b.tokens_est for b in OrcDossierBlock.objects.filter(
        hash__in=shared).only("tokens_est"))
    budget = DOSSIER_MAX_TOKENS - S_TOKENS_RESERVE - fixed
    parts, trimmed = trim(parts, model, budget=budget)
    today["in9"] = parts["in9"] or ("— (trimmed for size)" if "in9" in
                                    trimmed else [])
    tape = today.get("in12") if isinstance(today.get("in12"), dict) else {}
    if "in12_5m" in trimmed and isinstance(tape.get("5m"), dict):
        tape["5m"] = "— (trimmed for size)"
    if "in12_15m_old" in trimmed and isinstance(tape.get("15m"), dict):
        for slot in tape["15m"].values():
            if isinstance(slot, dict):
                slot["rows"] = (slot.get("rows") or [])[-8:]
    ps_sections["ps5"]["notes"] = parts["ps5_notes"] or "— (no note: the " \
        "Orc writes none before O2)"
    who = f"Orc #{orc.root_trade_id}"
    ps_text = text_for(f"PS {who} | {as_of:%Y-%m-%d %H:%M} UTC | code only",
                       ps_sections)
    ps_hash = block("ps", f"{orc.pk}|{as_of.isoformat()}", ps_text,
                    {"orc": orc.pk}, model, at=as_of)
    tail_body = {
        "mk_missing": [f"— (session block {n} not built yet)"
                       if n != "mk0" else "— (the day header not built yet)"
                       for n in missing],
        "mk_now": mk_now,
        "in_today": today,
        "ps12": dossier_position.ps12(ctx, row),
        "ps13": ctx.get("integrity") or {},
        "reasons": [str(r.get("t") or r.get("code") or "")
                    for r in ctx.get("reasons") or []],
        "trimmed": trimmed,
    }
    tail_text = text_for(f"TAIL {who} | {as_of:%Y-%m-%d %H:%M} UTC | "
                         f"MK-now, IN-today, PS12, PS13", tail_body)
    tail_hash = block("tail", f"{orc.pk}|{as_of.isoformat()}", tail_text,
                      {"orc": orc.pk}, model,
                      bar_rows=dossier_instrument.tape_rows(today), at=as_of)
    hashes = shared + [ps_hash, tail_hash]
    tokens = S_TOKENS_RESERVE + fixed + estimate_tokens(ps_text, 0, model) \
        + estimate_tokens(tail_text,
                          dossier_instrument.tape_rows(today), model)
    withheld = sum(fence.withheld_in(t) and t.count(fence.WITHHELD)
                   for t in (ps_text, tail_text))
    return {"hashes": hashes, "shared": len(shared), "ps": ps_hash,
            "tail": tail_hash, "tokens": int(tokens), "trimmed": trimmed,
            "over_budget": tokens > DOSSIER_MAX_TOKENS,
            "withheld": int(withheld), "integrity": ctx.get("integrity"),
            "model": model, "missing": missing}
