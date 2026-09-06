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
honours robots.txt before every host it has not asked about, identifies itself
in the User-Agent, caps what it will read, and returns "" for anything it
cannot get cleanly rather than guessing. It does not follow links out of a
page, does not search, does not retry a refusal, and never touches a URL the
platform did not already store from a feed the operator configured.

`extract_main_text` is deliberately network-free so it can be tested against
fixture HTML, which is the half that actually breaks.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse
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

FETCH_TIMEOUT_S = 12

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


def _robots_allows(url: str) -> bool:
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
        host = f"{parts.scheme}://{parts.netloc}"
        rp = _robots.get(host)
        if rp is None:
            rp = RobotFileParser()
            rp.set_url(urlunparse((parts.scheme, parts.netloc,
                                   "/robots.txt", "", "", "")))
            try:
                rp.read()
            except Exception as e:  # noqa: BLE001 — unreadable means allowed
                logger.debug("robots unreadable for %s (%s) — allowing", host, e)
                rp = True            # sentinel: no restrictions known
            _robots[host] = rp
        if rp is True:
            return True
        return bool(rp.can_fetch(USER_AGENT, url))
    except Exception as e:  # noqa: BLE001 — never raise into a beat task
        logger.debug("robots check failed for %s: %s", url, e)
        return False


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
    """
    if not url:
        return "", "no url"
    if not _robots_allows(url):
        return "", "robots"

    try:
        import requests
    except Exception as e:  # noqa: BLE001
        return "", f"requests unavailable: {e}"

    get = (session or requests).get
    try:
        resp = get(url, timeout=FETCH_TIMEOUT_S, stream=True,
                   headers={"User-Agent": USER_AGENT,
                            "Accept": "text/html,application/xhtml+xml"})
    except Exception as e:  # noqa: BLE001 — a dead host is data, not a crash
        return "", f"fetch failed: {type(e).__name__}"

    try:
        status = int(getattr(resp, "status_code", 0) or 0)
        if status != 200:
            return "", f"http {status}"
        ctype = str((getattr(resp, "headers", None) or {}).get(
            "Content-Type", "")).lower()
        if ctype and "html" not in ctype:
            # A PDF or a JSON endpoint is not something this extractor can
            # read, and feeding it to an HTML parser produces plausible
            # nonsense rather than an error.
            return "", f"content-type {ctype.split(';')[0]}"

        # Bounded read. `resp.text` would materialise whatever the host sent.
        chunks, size = [], 0
        try:
            for chunk in resp.iter_content(chunk_size=65536,
                                           decode_unicode=False):
                if not chunk:
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break
        except Exception as e:  # noqa: BLE001
            return "", f"read failed: {type(e).__name__}"

        raw = b"".join(
            c if isinstance(c, bytes) else str(c).encode("utf-8", "ignore")
            for c in chunks)
        encoding = (getattr(resp, "encoding", None) or "utf-8")
        try:
            html = raw.decode(encoding, "replace")
        except (LookupError, TypeError):
            html = raw.decode("utf-8", "replace")

        text = extract_main_text(html)
        if len(text) < MIN_TEXT_CHARS:
            # Storing this would make raw_content non-empty, and every reader
            # in the tree treats non-empty as "we have the article".
            return "", f"too short ({len(text)} chars) — paywall or wall"
        return text, "ok"
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
