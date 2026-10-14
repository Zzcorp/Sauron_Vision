"""THE PUBLIC LEAK WALK (2026-10-14): what a public page must never carry.

The Wall (/wall/) and the Book (/book/) are read by anyone who finds the
address, and this repository is public. Since the Book's second edition
the tests have walked every byte of both answers — the visible words, the
<head>, the <style> and <script> blocks and every comment — for generic
words no public page may say, for e-mail addresses, IP addresses and
identifier-length digit runs, for commit hashes, and for THE PRIVATE
TERMS: the handful of short phrases the operator keeps private (identity,
whereabouts, who holds what). Until this module the walk lived in a test
file and the private terms were stored there as bare sha256 digests of
short lowercase phrases, which a public repository must not hold: a hash
of a short phrase with no secret is a confirm-my-guess oracle.

Now:

  * the walk lives here, importable by the views and by the tests;
  * the private terms are READ FROM THE SERVER'S ENVIRONMENT at call time
    (SAURON_PRIVATE_TERMS, pipe-separated, any case, any length: a term
    is kept whole) and nowhere else. Nothing derived from them — no
    digest, no count of the real list — is in this tree. With the
    variable unset or empty the list is the canary alone, said once per
    process at INFO, and every walk still runs;
  * one term is always armed, CANARY, which the tests plant in clear to
    prove the walk finds a term wherever it hides;
  * the two public views call `withhold_if_private` on the rendered body:
    a page that carries a private term is NOT sent. The visitor receives
    a neutral placeholder (templates/landing/withheld.html, status 200,
    never cached), the log carries the COUNT of terms and never a term
    (one ERROR line per page per hour, DEBUG for the rest of a GET
    storm), staff is told once a day through notify_staff, and the health
    digest reads the event off a cache key (core/component_digest.py). A
    public GET writes no database row;
  * THE VISITOR'S OWN WORDS ARE NOT THE PAGE'S (2026-10-14, review). The
    walk reads the body as served, and a public page echoes two things a
    visitor types: nothing of the query string (the Wall's og:url is the
    canonical path, never request.build_absolute_uri with the query), and
    the Host header, in every absolute address ({% static_abs %}, the
    og:url), which a leading-dot ALLOWED_HOSTS entry lets a visitor set to
    any subdomain. The views pass the request, and the host it carries is
    blanked from the walked text before the terms are looked for. Without
    that, an anonymous GET could put a guess on the page and read the
    verdict off the placeholder — a confirm-my-guess oracle against the
    server's live list — and forge the incident staff is told about;
  * the walk is fenced: if it raises, the page is published as rendered
    with one warning. A leak check must never become the way to take the
    front door down.

Only the private-term check runs at render time (measured on the Wall's
278 KB answer: about 3 ms). The forbidden words, the patterns and the
commit hashes stay test-time checks (`leaks`): the Wall legitimately
carries "password" and "token" on its login form and five-figure counts,
which tests/test_wall_public_safety.py scrubs by hand.

A term is compared the way a page is read: NFC-normalised, lowercased,
split into word tokens and joined by one space, so "Jean-Pierre" and
"jean pierre" are one term, and a term is found only as whole words.

Read-only: no write, no broker, no order, no secret in this file.
"""
import functools
import html
import logging
import os
import re
import unicodedata

from django.core.cache import cache
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.cache import patch_cache_control

logger = logging.getLogger(__name__)

#: Generic words and phrases the public page must never carry, anywhere in
#: the answer (compared lowercased, entities decoded). The private ones
#: come from the environment (private_terms).
FORBIDDEN_WORDS = [
    # the account
    "balance", "equity", "p&l", "pnl", "profit and loss",
    "account number", "account id", "order id", "orderid", "position id",
    "positionid", "usd", "€", "$",
    # identifiers, keys, hosts, commands
    "chat id", "chat_id", "api key", "api_key", "user key", "user_key",
    "secret", "token", "password", "vps", "ssh ", "docker", "compose",
    "caddy", "daphne", "gunicorn", "celery", "redis", "postgres", "nginx",
    "hostname", "localhost", "127.0.0.1", "manage.py", ".env", "sudo",
    "systemctl", "git pull", "--yes", "/stop", "/status",
]
#: The stylesheet's own words that share letters with the list above.
CODE_WORDS = ("text-wrap: balance",)

#: The private terms: the environment variable they are read from, its
#: separator (a term may hold spaces and commas; a pipe never belongs to a
#: name), and the one term always armed. A term has no length bound: the
#: walk looks for each between two spaces of the page's joined tokens,
#: whose cost does not depend on the term's length, so a five-word
#: address is covered whole rather than dropped (2026-10-14, review).
PRIVATE_TERMS_ENV = "SAURON_PRIVATE_TERMS"
PRIVATE_TERMS_SEP = "|"
CANARY = "canary private phrase"

#: Searched over the whole answer, and over its visible text.
WHOLE_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "an e-mail address"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "an IP address"),
    (re.compile(r"(?<![\d,.])\d{5,}(?![\d,])"), "an identifier-length digit run"),
]
VISIBLE_PATTERNS = [
    (re.compile(r"\bpositions?\b"), "a position"),
    # the brake's command ("bot off 12"), not the English "switch a bot off"
    (re.compile(r"\bbot off \d"), "a command"),
]

#: The public pages the views walk, by the short name the cache keys use.
PAGES = {"book": "The Book", "wall": "The Wall"}
#: Set by a withhold, read by the health digest: {"at": datetime, "n": int}.
WITHHELD_KEY = "sv:leak_walk:withheld:%s"
WITHHELD_TTL = 48 * 3600
#: Set when staff was told, so an anonymous GET storm tells them once a day.
TOLD_KEY = "sv:leak_walk:told:%s"
TOLD_TTL = 24 * 3600
#: Set when the ERROR line was written, so a GET storm on a withheld page
#: (the Wall is the public front door, with no rate limit) writes one
#: ERROR line an hour and the rest at DEBUG; the count still reaches
#: /health/ and the digest through WITHHELD_KEY.
LOGGED_KEY = "sv:leak_walk:logged:%s"
LOGGED_TTL = 3600
TEMPLATE = "landing/withheld.html"


# ── reading a page ──────────────────────────────────────────────────────────

def tokens(text):
    """The word tokens of a text, NFC-normalised and lowercased."""
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text).lower())


def whole(body):
    """Every byte a visitor receives, entities decoded, lowercased: the
    <head>, the <style> and <script> blocks and every comment included.
    The counted numbers' own attribute is taken out (a large count is not
    an identifier), and so are the colours (#030806 is the page's black)
    and the stylesheet's own words (CODE_WORDS)."""
    text = re.sub(r'data-count="\d+"', " ", html.unescape(body)).lower()
    text = re.sub(r"#[0-9a-f]{3,8}(?![0-9a-z])", " ", text)
    for word in CODE_WORDS:
        text = text.replace(word, " ")
    return text


def visible(body):
    """The words a visitor reads."""
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<(style|script|head)\b.*?</\1>", " ", body,
                  flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    return " ".join(text.split())


# ── the private terms ───────────────────────────────────────────────────────

def normalised(term) -> str:
    """A term as the walk compares it: its tokens joined by one space."""
    return " ".join(tokens(str(term)))


@functools.lru_cache(maxsize=16)
def _terms_of(raw: str) -> frozenset:
    """The configured terms out of one raw value, each kept whole, the
    canary added; blanks and duplicates fall away."""
    terms = {CANARY}
    for piece in raw.split(PRIVATE_TERMS_SEP):
        term = normalised(piece)
        if term:
            terms.add(term)
    return frozenset(terms)


def private_terms(raw=None) -> frozenset:
    """The private terms, normalised, the canary always among them. Read
    from the environment at CALL time (so a test patches os.environ), or
    from `raw` when one is given."""
    if raw is None:
        raw = os.environ.get(PRIVATE_TERMS_ENV) or ""
    return _terms_of(str(raw))


def configured() -> bool:
    """Whether the environment holds at least one term beyond the canary."""
    return len(private_terms()) > 1


def private_terms_in(text, terms=None) -> list:
    """Every private term the text carries, as the text itself says it,
    sorted. Whole tokens only, however many a term holds: the text is
    tokenised exactly as the terms were, and each term is looked for
    between two spaces of the joined tokens."""
    if terms is None:
        terms = private_terms()
    else:
        terms = {t for t in (normalised(t) for t in terms) if t}
    if not terms:
        return []
    joined = " " + " ".join(tokens(text)) + " "
    return sorted(term for term in terms if " %s " % term in joined)


# ── the whole walk (test time) ──────────────────────────────────────────────

def leaks(body, *, terms=None, forbidden=FORBIDDEN_WORDS, commits=()) -> list:
    """What an answer carries that a public page must not, in words."""
    text = whole(body)
    found = ["says %r" % word for word in forbidden if word in text]
    found += ["carries the private term %r" % gram
              for gram in private_terms_in(text, terms)]
    for pattern, what in WHOLE_PATTERNS:
        hit = pattern.search(text)
        if hit:
            found.append("shows %s: %r" % (what, hit.group(0)))
    for commit in commits:
        if re.search(r"(?<![0-9a-f])%s(?![0-9a-f])" % re.escape(commit), text):
            found.append("shows the commit %s" % commit)
    shown = visible(body)
    for pattern, what in VISIBLE_PATTERNS:
        hit = pattern.search(shown)
        if hit:
            found.append("shows %s: %r" % (what, hit.group(0)))
    if "@" in shown:
        found.append("shows an @")
    return found


# ── render time ─────────────────────────────────────────────────────────────

_SAID = False


def say_canary_only_once():
    """One INFO line per process when no list is configured. Nothing on
    the health digest: a deliberate choice is not a fault to nag about."""
    global _SAID
    if _SAID:
        return
    _SAID = True
    if not configured():
        logger.info("the public leak walk runs with the canary only: %s is "
                    "not set", PRIVATE_TERMS_ENV)


def _tell_staff(page: str) -> None:
    """notify_staff once a day per page, behind a cache gate so an
    anonymous GET storm pays no Notification query; never a term."""
    try:
        if not cache.add(TOLD_KEY % page, 1, TOLD_TTL):
            return
        from bot_program.notifications import notify_staff
        name = PAGES.get(page, page)
        notify_staff(
            title="%s was withheld: a private term reached the public page" % name,
            body=("%s rendered with a private term in it and was not sent: "
                  "visitors see a placeholder until the page is fixed. The "
                  "term is in the server's private list, not in this "
                  "message; /health/ and the log carry the count." % name),
            url="/health/", cooldown_hours=24)
    except Exception as exc:  # noqa: BLE001 — telling is not the page's job
        logger.warning("staff could not be told that %s was withheld (%s)",
                       PAGES.get(page, page), type(exc).__name__)


def _log_withheld(page: str, n: int) -> None:
    """One ERROR line per page per hour (behind a cache gate, like the
    telling), DEBUG for every further GET of the same withheld page: the
    first occurrence is loud, a crawler's loop is not 36,000 ERROR lines
    an hour. A cache that cannot be asked keeps the line loud."""
    name = PAGES.get(page, page)
    try:
        loud = cache.add(LOGGED_KEY % page, 1, LOGGED_TTL)
    except Exception:  # noqa: BLE001
        loud = True
    (logger.error if loud else logger.debug)(
        "%s was withheld: %d private term(s) in the rendered page", name, n)


def withheld(page: str, found) -> HttpResponse:
    """The placeholder answer for a page that carried a private term, and
    its side effects: the ERROR line with the count (once an hour), the
    cache key the digest reads, staff told once a day. Never a term,
    never a DB row."""
    n = len(found)
    name = PAGES.get(page, page)
    _log_withheld(page, n)
    try:
        cache.set(WITHHELD_KEY % page, {"at": timezone.now(), "n": n},
                  WITHHELD_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("the withhold of %s could not be recorded (%s)",
                       name, type(exc).__name__)
    _tell_staff(page)
    other = "wall" if page == "book" else "book"
    try:
        body = render_to_string(TEMPLATE, {
            "page": page, "other": other,
            "other_name": PAGES.get(other, other),
            "other_url": "/%s/" % other})
    except Exception as exc:  # noqa: BLE001 — a placeholder with no template
        logger.warning("the withheld page could not be rendered (%s)",
                       type(exc).__name__)
        body = ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                "<title>Sauron Vision</title></head><body><p>This page is not "
                "published right now. Come back later.</p></body></html>")
    response = HttpResponse(body)
    patch_cache_control(response, no_store=True)
    return response


def visitors_words(request) -> list:
    """What the visitor typed that the page echoes, lowercased: the Host
    header (with and without its port), which every absolute address on
    the page carries. A term a visitor plants there is theirs, not the
    page's, and is never read as a leak. No request, or a host that
    cannot be read: nothing to blank."""
    if request is None:
        return []
    try:
        host = str(request.get_host() or "").strip().lower()
    except Exception:  # noqa: BLE001 — Django already refused a bad host
        return []
    if not host:
        return []
    bare = host.rsplit(":", 1)[0] if ":" in host else host
    return sorted({host, bare}, key=len, reverse=True)


def withhold_if_private(page: str, body: str, request=None):
    """The answer to send INSTEAD of `body`, or None when the body may go
    out. `request`, when given, is the visitor's: what it echoes onto the
    page (visitors_words) is blanked before the terms are looked for.
    Fenced: a walk that raises costs one warning and the page is
    published as rendered."""
    try:
        say_canary_only_once()
        text = whole(body)
        for word in visitors_words(request):
            text = text.replace(word, " ")
        found = private_terms_in(text)
    except Exception as exc:  # noqa: BLE001 — the front door stays open
        logger.warning("the leak walk of %s could not run (%s); the page is "
                       "published as rendered", PAGES.get(page, page),
                       type(exc).__name__)
        return None
    if not found:
        return None
    return withheld(page, found)
