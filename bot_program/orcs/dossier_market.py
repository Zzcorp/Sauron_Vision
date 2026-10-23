"""MK, THE MARKET DAY (spec §5.2a "MK: the market day"), shared by every
Orc on a model and built only by the beats (orc-day-roll, orc-session-
close): never in the tick.

  MK0        at the roll: MK1 the day header (session times, the classes
             shut, crypto 24/7, the board's instruments), MK5 the macro
             line, the MK6 plan (today's and tomorrow's high-impact
             prints), MK9 the long view, MK10 and MK11 as dashes. Immutable
             for the trading day.
  a session  once it has CLOSED: MK2 the board in that session, the prints
             that landed, MK3 the regime clock, MK4 the posture at its
             close, MK7 the Mind at its close, MK8 a brief that landed in
             it, MK12 its headlines (6, then 4, then 3, until the block fits
             MK_SESSION_MAX_TOKENS for the model, decided when it is built;
             a block still over at 3 is stored once, marked over_budget).
             Immutable once written: a late article never rebuilds it.
  MK-E       the Emperor's line, its own block after the sessions, so MK0
             never changes when it lands. O1: "— (no order yet today)".
  MK-now     the tail (per wake, uncached): the session running, the prints
             since the last close, the newest Mind and brief, the new
             headlines, the board's live move, the user's correlation
             clusters, the book as shares of its limits (never money).

MK carries platform-level reads only (the Mind, the strategist, the
calendar, the news, the board); nothing of any user's book enters MK0 or a
session block, so one copy serves every user. MK-now's clusters and book
are per user and live in the tail.

# O2: MK-E carries the Emperor's daily order (§4.6), written once it lands.
"""
import logging
from datetime import timedelta

from bot_program.orcs import dossier, fence, sources
from bot_program.orcs.constants import (BOARD_SYMBOLS, DRUM_RHO_MIN,
                                        MK_HEADLINE_STEPS,
                                        MK_HEADLINES_PER_SESSION,
                                        MK_SESSION_MAX_TOKENS)
from bot_program.orcs.sessions import (SESSION_NAMES, closed_sessions,
                                       current_session, day_bounds,
                                       session_windows, trading_day)

logger = logging.getLogger(__name__)

SHUT_CLASSES = ("forex", "index", "commodity", "stock", "etf")
NEXT_WEEK_DASH = "— (the free feed carries the current week only)"
NO_ORDER_DASH = "— (no order yet today)"


def _key(td, name, model="") -> str:
    """The block's natural key: the trading day, the block, and the model's
    family (MK is sized per tokenizer when it is built)."""
    fam = dossier.family_of(model) if model else ""
    return f"{td.isoformat()}|{name}" + (f"|{fam}" if fam else "")


def _hm(at) -> str:
    return f"{at:%H:%M}"


def _window(start, end) -> str:
    return f"{_hm(start)}-{_hm(end)} UTC"


# ── MK0 ──────────────────────────────────────────────────────────────────

def _mk1(td, start, end) -> dict:
    from core.exchange_status import market_clock
    sessions_ = {name: _window(s, e) for name, s, e in session_windows(td)}
    mid = start + (end - start) / 2
    shut = {}
    for cls in SHUT_CLASSES:
        try:
            clock = market_clock(cls, "", "", now_utc=mid)
            shut[cls] = ("open" if clock.get("is_open") else
                         f"shut until {clock.get('reopens_words') or '—'}")
        except Exception:  # noqa: BLE001
            shut[cls] = "— (clock unread)"
    board = {}
    for sym in BOARD_SYMBOLS:
        if sym == "US10Y":
            board[sym] = sources.US10Y_DASH
            continue
        inst = sources._instrument(sym)
        board[sym] = (f"listed ({inst.asset_class})" if inst is not None
                      else f"— (no instrument for {sym})")
    return {"sessions": sessions_, "classes_at_midday": shut,
            "crypto": "24/7", "board": board}


def _mk5(at) -> dict:
    out = {s: sources.shown(sources.fred(s, at)) for s in sources.MK5_SERIES}
    out["VIX/VIX3M"] = sources.shown(sources.vix_term(at))
    out["note"] = "VIX/VIX3M above 1 is an inverted curve"
    return out


def _mk6(td, now) -> dict:
    start, end = day_bounds(td)
    today = sources.calendar(start, end)
    out = {"today": (sources.calendar_rows(today["value"], start)
                     if not today.get("dash") else today["dash"])}
    if td.weekday() == 4:
        out["tomorrow"] = NEXT_WEEK_DASH
    else:
        tom = sources.calendar(end, end + timedelta(days=1))
        out["tomorrow"] = (sources.calendar_rows(tom["value"], start)
                           if not tom.get("dash") else tom["dash"])
    return out


def _mk9(at) -> dict:
    return {"horizon": sources.shown(sources.horizon(at)),
            "prophecies": "—",
            "season": "no season objective set by the operator"}


def build_mk0(td, model, *, now):
    model = dossier.family_of(model)
    start, end = day_bounds(td)
    body = {"day": td.isoformat(), "rolls": "17:00 New York",
            "mk1": _mk1(td, start, end), "mk5": _mk5(start),
            "mk6": _mk6(td, start), "mk9": _mk9(start),
            "mk10": "— (not built)", "mk11": "— (the council has not sat)"}
    text = dossier.text_for(
        f"MK0 {td.isoformat()} | built {now:%Y-%m-%dT%H:%MZ} | {model} | "
        f"sources: the session clock, FRED, the calendar, the Horizon",
        body)
    return dossier.block("mk0", _key(td, "mk0", model), text,
                         {"day": td.isoformat()}, model, at=now)


def mk0(td, model, *, now=None, build=True):
    """MK0's hash: found, else built (`build`)."""
    from django.utils import timezone
    b = dossier.find("mk0", _key(td, "mk0", model))
    if b is not None:
        return b.hash
    if not build:
        return None
    return build_mk0(td, model, now=now or timezone.now())


# ── the session blocks ───────────────────────────────────────────────────

def _regimes(start, end) -> object:
    try:
        from bot_program.persona_mix import regime_series
        out = []
        for frm, _to, label, conf in regime_series(start, end):
            out.append(f"{_hm(max(frm, start))} {label} "
                       f"{float(conf or 0):.2f}")
        return out or "— (no regime recorded)"
    except Exception as e:  # noqa: BLE001
        return f"— (the regime clock unread: {type(e).__name__})"


def _session_body(td, name, start, end, n_headlines, blind) -> dict:
    day_start, _ = day_bounds(td)
    board = {s: sources.shown(sources.board_session(s, start, end,
                                                    day_open_at=day_start))
             for s in BOARD_SYMBOLS}
    cal = sources.calendar(start, end)
    news = sources.headlines(start, end, n=n_headlines, blind=blind)
    brief = sources.brief(end, since=start)
    return {"session": name, "window": _window(start, end),
            "mk2": board,
            "prints": (sources.calendar_rows(cal["value"], end)
                       if not cal.get("dash") else cal["dash"]),
            "mk3": {"regimes": _regimes(start, end),
                    "held_back": "— (the synthesizer's held votes are not "
                                 "read in O1)"},
            "mk4": sources.shown(sources.posture(end)),
            "mk7": sources.shown(sources.mind(end)),
            "mk8": (sources.shown(brief) if not brief.get("dash")
                    else "— (no brief landed)"),
            "mk12": (news["value"] if not news.get("dash") else news["dash"])}


def build_session(td, name, model, *, now):
    """One closed session's block, sized for `model` at build time."""
    model = dossier.family_of(model)
    win = {n: (s, e) for n, s, e in session_windows(td)}
    start, end = win[name]
    blind, _since = sources.analyst_blind(end)
    steps = [k for k in MK_HEADLINE_STEPS if k <= MK_HEADLINES_PER_SESSION] \
        or [MK_HEADLINES_PER_SESSION]
    cap = MK_SESSION_MAX_TOKENS
    text = body = None
    for k in steps:
        body = _session_body(td, name, start, end, k, blind)
        text = dossier.text_for(
            f"MK {name} {td.isoformat()} | {_window(start, end)} | closed | "
            f"built {now:%Y-%m-%dT%H:%MZ} | {model} | sources: the board's "
            f"1h bars, the calendar, the stress reading, the Mind, the "
            f"strategist, the news titles", body)
        if dossier.estimate_tokens(text, 0, model) <= cap:
            break
    over = dossier.estimate_tokens(text, 0, model) > cap
    return dossier.block("mk_session", _key(td, name, model), text,
                         {"day": td.isoformat(), "session": name,
                          "headlines": len(body["mk12"])
                          if isinstance(body["mk12"], list) else 0,
                          "over_budget": over}, model, at=now)


def mk_session(td, name, model, *, now=None, build=True):
    """A CLOSED session's hash: found, else built (`build`); None while the
    session is still running."""
    from django.utils import timezone
    now = now or timezone.now()
    b = dossier.find("mk_session", _key(td, name, model))
    if b is not None:
        return b.hash
    win = {n: e for n, _s, e in session_windows(td)}
    if name not in win or win[name] > now or not build:
        return None
    return build_session(td, name, model, now=now)


def mk_e(td):
    """MK-E, the Emperor's line: its own block, after the sessions."""
    # O2: the Emperor's daily order (§4.6) replaces the dash once it lands
    # (OrcJournal kind "emperor"); MK0's bytes never change for it.
    key = _key(td, "mk_e")
    b = dossier.find("mk_e", key)
    if b is not None:
        return b.hash
    text = dossier.text_for(f"MK-E {td.isoformat()} | the Emperor's line",
                            {"emperor": NO_ORDER_DASH})
    return dossier.block("mk_e", key, text, {"day": td.isoformat()})


def build_day(td, model, *, now) -> int:
    """MK0 and every closed session still missing for `model`: the beats'
    one entry. Returns how many blocks it built (0 on a second call)."""
    built = 0
    if dossier.find("mk0", _key(td, "mk0", model)) is None:
        build_mk0(td, model, now=now)
        built += 1
    for name in closed_sessions(now) if trading_day(now) == td \
            else list(SESSION_NAMES):
        if dossier.find("mk_session", _key(td, name, model)) is None:
            try:
                build_session(td, name, model, now=now)
                built += 1
            except Exception as e:  # noqa: BLE001 — one never stops the rest
                logger.warning("[orcs] MK %s %s (%s) not built: %s", td, name,
                               model, e)
    return built


def day_hashes(td, model, now) -> tuple:
    """([hash], [missing]) of the day's MK for `model` as it stands at
    `now`: MK0, each closed session, MK-E. FOUND, never built: the tick
    lists what is missing ("mk0" or a session's name)."""
    from bot_program.orcs.models import OrcDossierBlock
    keys = {_key(td, "mk0", model): "mk0"}
    closed = closed_sessions(now) if trading_day(now) == td else []
    for name in closed:
        keys[_key(td, name, model)] = name
    found = {b.key: b.hash for b in OrcDossierBlock.objects.filter(
        key__in=list(keys)).only("key", "hash")}
    hashes, missing = [], []
    for key, name in keys.items():
        if key in found:
            hashes.append(found[key])
        else:
            missing.append(name)
    hashes.append(mk_e(td))
    return hashes, missing


# ── MK-now (the tail) ────────────────────────────────────────────────────

def _clusters(user, symbols) -> object:
    corr = sources.correlation(user, symbols)
    if corr.get("dash"):
        return corr["dash"]
    hot = []
    for pair, rho in sorted(corr["value"]["pairs"].items()):
        try:
            if abs(float(rho)) >= DRUM_RHO_MIN:
                hot.append(f"{pair} {rho}")
        except ValueError:
            continue                    # "—": unmeasured, never 0.0
    return hot or f"— (no pair measured at |rho| >= {DRUM_RHO_MIN})"


def mk_now(user, held_symbols, now, *, real=True, cache=None) -> tuple:
    """(text, body) of MK-now for one user's wake."""
    td = trading_day(now)
    closed = closed_sessions(now)
    wins = {n: (s, e) for n, s, e in session_windows(td)}
    since = wins[closed[-1]][1] if closed else day_bounds(td)[0]
    blind, _s = sources.analyst_blind(now)
    cal = sources.calendar(since, now + timedelta(minutes=1))
    news = sources.headlines(since, now, n=MK_HEADLINES_PER_SESSION,
                             blind=blind)
    board = {}
    live = sources.quotes([s for s in BOARD_SYMBOLS if s != "US10Y"])
    for sym in BOARD_SYMBOLS:
        if sym == "US10Y":
            board[sym] = sources.US10Y_DASH
            continue
        q = live[sym]
        if q.get("dash"):
            board[sym] = q["dash"]
        else:
            ch = q["value"].get("change_pct")
            board[sym] = f"{ch:+.2f}%" if ch is not None else "—"
    book = sources.book(user, real=real, cache=cache)
    body = {"session": current_session(now) or "between sessions",
            "since": f"{since:%H:%M} UTC",
            "prints_since": (sources.calendar_rows(cal["value"], now)
                             if not cal.get("dash") else cal["dash"]),
            "posture": sources.shown(sources.posture(now)),
            "mind": sources.shown(sources.mind(now)),
            "brief": sources.shown(sources.brief(now)),
            "headlines": (news["value"] if not news.get("dash")
                          else news["dash"]),
            "board_live": board,
            "clusters": _clusters(user, held_symbols),
            "book": ({k: book["value"][k] for k in ("daily_loss_mode",
                                                    "open_risk_t")}
                     if not book.get("dash") else book["dash"])}
    text = dossier.text_for(f"MK-now {now:%Y-%m-%d %H:%M} UTC | the session "
                            f"in progress", body)
    return text, body
