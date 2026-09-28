"""Fetch the article BODY — which nothing in this platform ever did.

`NewsArticle.raw_content` is described in the codebase as "the full scraped
body". A retention task exists solely to blank it after RETAIN_NEWS_RAW_DAYS
because "raw_content is nearly all of its weight" (market_data/cleanup_tasks.py).
And no scraper has ever written a single character into it. Every other
reference in the tree is a READ or that strip: a retention policy for a field
nobody fills.

What the operator saw was an article page with empty content and only the AI's
opinion of it. What the AI saw was no better. `ai_agents/tasks.py` asks for
`content_summary or raw_content[:2000]`, and `content_summary` is whatever the
RSS `summary`/`description` held, capped at 1000 characters — which many feeds
ship empty, and most of the rest ship as a one-line teaser. So the sentiment
score, the urgency label, the affected-instrument match and the brain's news
context were, in the common case, computed from a headline. That is not a
degraded reading; it is a different measurement wearing the same name.

WHAT THIS MODULE WILL AND WILL NOT DO

It fetches pages the platform already holds URLs for, one at a time, and keeps
the extracted text for the same window the retention policy already sets. It
honours robots.txt before every host it has not asked about — the host a
redirect lands on included — identifies itself in the User-Agent, caps what it
will read and how long the whole fetch may take, refuses any host that
resolves off the public internet, and returns "" for anything it cannot get
cleanly rather than guessing. It does not follow links out of a page, does not
search, does not retry a refusal, never lets requests take a redirect on its
own, and never touches a URL the platform did not already store from a feed
the operator configured.

`extract_main_text` is deliberately network-free so it can be tested against
fixture HTML, which is the half that actually breaks.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

USER_AGENT = ("SauronVisionBot/1.0 (+news summarisation for one private "
              "trading account; contact: the deployment operator)")

# Read at most this much of a page. Long enough for a wire story with markup
# around it, short enough that one pathological URL cannot fill the disk.
MAX_BYTES = 2_000_000
# And keep at most this much extracted text. The AI path reads 2000 chars; the
# instrument matcher and the operator's eyes want more than that and nothing
# wants a novel. The retention task strips it after 90 days regardless.
MAX_TEXT_CHARS = 20_000
# Below this a "body" is a cookie wall, a paywall stub or a redirect notice,
# and storing it would make `raw_content` non-empty — which is worse than
# empty, because the retention task and every reader treat non-empty as "we
# have the article".
MIN_TEXT_CHARS = 400
# RFC 9309 §2.5: a crawler need not read more than 500 KiB of robots.txt.
ROBOTS_MAX_BYTES = 512_000

# Per socket operation — the connect, and EACH read. That is all requests'
# `timeout=` ever bounds.
FETCH_TIMEOUT_S = 12
# One wall clock for the WHOLE fetch: robots.txt, every redirect hop, the
# connect and the read. A host that dripped a byte every ten seconds reset
# the per-read timeout on every chunk, and robots.txt was worse —
# `RobotFileParser.read()` is `urllib.request.urlopen(url)` with no timeout
# at all — so one silent host held one of worker-slow's two slots (shared
# with the ai queue) until the container was restarted. The task swallows
# exceptions per article; a blocked recv never raises one.
FETCH_DEADLINE_S = 30
# Hops a story link may take. requests' own default (30) is for a browser; a
# feed link needs http→https, www. and one tracking redirect. Every hop is a
# new fetch here — resolved, robots-checked, on the same clock — never one
# requests takes on its own: the first host's robots answer says nothing
# about the host a 30x names, and a 30x into the compose network (web:8000,
# the metadata address) was followed from inside worker-slow.
MAX_REDIRECTS = 5
_REDIRECTS = (301, 302, 303, 307, 308)

# Tags that are never article prose. `header`/`footer`/`nav`/`aside` carry the
# site chrome that otherwise dominates a naive text extraction, and `form`
# carries newsletter signup copy that reads exactly like a sentence.
_STRIP_TAGS = ("script", "style", "noscript", "nav", "aside", "header",
               "footer", "form", "figure", "figcaption", "iframe", "svg",
               "button", "select", "template")

# robots.txt answers, per host, for the life of the process. A worker restarts
# often enough that this is not a stale-forever cache, and re-fetching
# robots.txt for every article in a batch would be its own rudeness.
_robots: dict = {}

# The charset a Content-Type header or a <meta> tag names. The <meta> form
# matches both `<meta charset=utf-8>` and the http-equiv content attribute.
_HEADER_CHARSET = re.compile(r"""charset\s*=\s*["']?\s*([A-Za-z0-9._:-]+)""", re.I)
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9._:-]+)""",
                           re.I)


def _refusal(url: str) -> str:
    """Why `url` must not be requested at all, or "" when it may be.

    The host is RESOLVED and refused when any address it answers with is
    not on the public internet — loopback, a private range, link-local
    (the cloud metadata address), multicast, nothing. A story link is
    third-party content; a request it steers into the compose network is
    one this platform must never make, GET-only or not. This runs before
    robots.txt is asked, which is itself a GET to the same host.
    """
    parts = urlparse(url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        return "not http"
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except Exception as e:  # noqa: BLE001 — unresolvable is unreachable
        return f"fetch failed: {type(e).__name__}"
    if not infos:
        return "fetch failed: unresolved"
    for info in infos:
        try:
            addr = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        except ValueError:
            return "private address"
        if not addr.is_global or addr.is_multicast:
            logger.debug("refusing %s: %s resolves to %s", url, host, addr)
            return "private address"
    return ""


def _get(url: str, *, get, deadline: float, accept: str):
    """One GET on the clock: (response, "") or (None, reason).

    The socket timeout is the smaller of FETCH_TIMEOUT_S and what is left
    of the budget, and requests is told NOT to follow a redirect — the
    caller decides whether the next hop may be fetched at all.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None, f"deadline ({FETCH_DEADLINE_S}s)"
    try:
        resp = get(url, timeout=min(FETCH_TIMEOUT_S, remaining), stream=True,
                   allow_redirects=False,
                   headers={"User-Agent": USER_AGENT, "Accept": accept})
    except Exception as e:  # noqa: BLE001 — a dead host is data, not a crash
        return None, f"fetch failed: {type(e).__name__}"
    return resp, ""


def _next_hop(url: str, resp) -> str:
    """The absolute URL a 3xx points at, or "" when it names none."""
    location = str((getattr(resp, "headers", None) or {}).get("Location", "")
                   or "").strip()
    return urljoin(url, location) if location else ""


def _read_bounded(resp, *, max_bytes: int, deadline: float):
    """Up to `max_bytes` of the body, or None when the deadline passed first.

    Streamed: `resp.text` would materialise whatever the host sent, and a
    per-read timeout is reset by every chunk a dripping host sends — the
    budget is on the clock, not on the socket.
    """
    chunks, size = [], 0
    for chunk in resp.iter_content(chunk_size=65536, decode_unicode=False):
        if time.monotonic() > deadline:
            return None
        if not chunk:
            continue
        chunks.append(chunk)
        size += len(chunk)
        if size >= max_bytes:
            break
    return b"".join(
        c if isinstance(c, bytes) else str(c).encode("utf-8", "ignore")
        for c in chunks)


def _close(resp) -> None:
    try:
        resp.close()
    except Exception:  # noqa: BLE001
        pass


def _read_robots(host: str, *, session=None, deadline: float):
    """A RobotFileParser for `host`, or True when its file cannot be read.

    Through requests, with the fetch's timeout and deadline — never
    `RobotFileParser.read()`, whose `urlopen` has no timeout. The verdict
    table is read()'s own: 401/403 disallow everything, any other 4xx
    allows everything, 200 is parsed, and a 5xx leaves a parser that has
    read nothing, which can_fetch answers with no. A redirect is taken by
    hand, on the same clock and behind the same address guard.
    """
    import requests

    get = (session or requests).get
    rp = RobotFileParser()
    rp.set_url(host + "/robots.txt")
    url = rp.url
    for _hop in range(MAX_REDIRECTS + 1):
        why = _refusal(url)
        if not why:
            resp, why = _get(url, get=get, deadline=deadline, accept="text/plain")
        if why:
            logger.debug("robots unreadable for %s (%s) — allowing", host, why)
            return True
        try:
            status = int(getattr(resp, "status_code", 0) or 0)
            if status in _REDIRECTS:
                url = _next_hop(url, resp)
                if not url:
                    return True
                continue
            if status in (401, 403):
                rp.disallow_all = True
            elif 400 <= status < 500:
                rp.allow_all = True
            elif status == 200:
                raw = _read_bounded(resp, max_bytes=ROBOTS_MAX_BYTES,
                                    deadline=deadline)
                if raw is None:
                    logger.debug("robots unreadable for %s (deadline) — allowing",
                                 host)
                    return True
                rp.parse(raw.decode("utf-8", "replace").splitlines())
            return rp
        finally:
            _close(resp)
    logger.debug("robots unreadable for %s (redirect loop) — allowing", host)
    return True


def _robots_allows(url: str, *, session=None, deadline: float | None = None) -> bool:
    """Whether robots.txt permits our User-Agent on this URL.

    A host whose robots.txt cannot be read is treated as ALLOWED, which is
    what the standard says and is also the only answer that does not make an
    unreachable file into a silent platform-wide outage. A host that refuses
    is remembered so the batch does not ask again.
    """
    try:
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        host = urlunparse((parts.scheme, parts.netloc, "", "", "", ""))
        rp = _robots.get(host)
        if rp is None:
            if deadline is None:
                deadline = time.monotonic() + FETCH_DEADLINE_S
            rp = _read_robots(host, session=session, deadline=deadline)
            _robots[host] = rp
        if rp is True:
            return True
        return bool(rp.can_fetch(USER_AGENT, url))
    except Exception as e:  # noqa: BLE001 — never raise into a beat task
        logger.debug("robots check failed for %s: %s", url, e)
        return False


def _decode_html(raw: bytes, ctype: str) -> str:
    """`raw` as text, by what the page says it is.

    In the order HTML ranks its sources: the charset the Content-Type header
    names, else the <meta charset> in the document, else what the bytes
    themselves look like (requests' own apparent_encoding detector, run
    here because a streamed response's content is gone by now), else UTF-8.

    Never `Response.encoding`. For any text/* without a charset parameter
    requests sets it to ISO-8859-1 — RFC 2616's default, which every byte
    satisfies, so no decode error ever fell through to the UTF-8 fallback
    written for exactly this case — and a UTF-8 page that declares its
    charset only in <meta>, which is common, stored 'Société Générale' as
    'SociÃ©tÃ© GÃ©nÃ©rale' in raw_content, on the article page and in the
    analyst's reading.
    """
    m = _HEADER_CHARSET.search(ctype or "")
    encoding = m.group(1) if m else ""
    if not encoding:
        m = _META_CHARSET.search(raw[:16384])
        encoding = m.group(1).decode("ascii", "ignore") if m else ""
    if not encoding:
        try:
            from requests.compat import chardet
            encoding = (chardet.detect(raw[:200_000]) or {}).get("encoding") or ""
        except Exception as e:  # noqa: BLE001 — a missing detector is not a crash
            logger.debug("charset detection unavailable: %s", e)
    for candidate in (encoding, "utf-8"):
        if not candidate:
            continue
        try:
            return raw.decode(candidate, "replace")
        except (LookupError, TypeError):
            continue
    return raw.decode("utf-8", "replace")


def extract_main_text(html: str) -> str:
    """The article prose in `html`, or "" when there is none worth keeping.

    Network-free on purpose: this is the half that breaks, and it can only be
    tested if it takes a string.

    Strategy, in order: an explicit <article>; else the element whose
    descendant <p> text is longest — which beats "longest element" because a
    page's <body> always wins that contest, and beats "all <p> on the page"
    because that concatenates the story with three sidebars of teasers.
    """
    try:
        from bs4 import BeautifulSoup
    except Exception as e:  # noqa: BLE001
        logger.warning("bs4 unavailable — cannot extract article text: %s", e)
        return ""

    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:  # noqa: BLE001 — lxml may be absent in a slim install
        try:
            soup = BeautifulSoup(html or "", "html.parser")
        except Exception as e:  # noqa: BLE001
            logger.debug("unparseable html: %s", e)
            return ""

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    def prose(node) -> str:
        chunks = []
        for p in node.find_all("p"):
            t = " ".join((p.get_text(" ", strip=True) or "").split())
            # One-clause paragraphs are captions, bylines, "Read more" and
            # cookie copy. The threshold is low enough to keep a real short
            # lede and high enough to drop most chrome.
            if len(t) >= 40:
                chunks.append(t)
        return "\n\n".join(chunks)

    best = ""
    article = soup.find("article")
    if article is not None:
        best = prose(article)

    if len(best) < MIN_TEXT_CHARS:
        for node in soup.find_all(["main", "div", "section", "body"]):
            text = prose(node)
            if len(text) > len(best):
                best = text

    return best[:MAX_TEXT_CHARS]


def fetch_article_body(url: str, *, session=None) -> "tuple[str, str]":
    """(text, reason). `text` is "" whenever we did not get a clean body.

    `reason` is always populated and is for the log, not the operator: it
    distinguishes "robots said no" from "the page was a paywall stub" from
    "the host timed out", which is the difference between a URL worth trying
    again tomorrow and one that never will be.

    One deadline (FETCH_DEADLINE_S) covers everything below. A redirect is
    one hop of a new fetch — address guard, robots.txt, the clock — and
    requests never takes one on its own.
    """
    if not url:
        return "", "no url"

    try:
        import requests
    except Exception as e:  # noqa: BLE001
        return "", f"requests unavailable: {e}"

    get = (session or requests).get
    deadline = time.monotonic() + FETCH_DEADLINE_S

    for _hop in range(MAX_REDIRECTS + 1):
        why = _refusal(url)
        if why:
            return "", why
        if not _robots_allows(url, session=session, deadline=deadline):
            return "", "robots"
        resp, why = _get(url, get=get, deadline=deadline,
                         accept="text/html,application/xhtml+xml")
        if why:
            return "", why

        try:
            status = int(getattr(resp, "status_code", 0) or 0)
            if status in _REDIRECTS:
                url = _next_hop(url, resp)
                if not url:
                    return "", f"http {status} without a location"
                continue
            if status != 200:
                return "", f"http {status}"
            ctype = str((getattr(resp, "headers", None) or {}).get(
                "Content-Type", "")).lower()
            if ctype and "html" not in ctype:
                # A PDF or a JSON endpoint is not something this extractor can
                # read, and feeding it to an HTML parser produces plausible
                # nonsense rather than an error.
                return "", f"content-type {ctype.split(';')[0]}"

            try:
                raw = _read_bounded(resp, max_bytes=MAX_BYTES, deadline=deadline)
            except Exception as e:  # noqa: BLE001
                return "", f"read failed: {type(e).__name__}"
            if raw is None:
                return "", f"deadline ({FETCH_DEADLINE_S}s)"

            text = extract_main_text(_decode_html(raw, ctype))
            if len(text) < MIN_TEXT_CHARS:
                # Storing this would make raw_content non-empty, and every reader
                # in the tree treats non-empty as "we have the article".
                return "", f"too short ({len(text)} chars) — paywall or wall"
            return text, "ok"
        finally:
            _close(resp)

    return "", f"too many redirects (>{MAX_REDIRECTS})"
